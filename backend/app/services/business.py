"""Regles metier : tarifs, parametres, remunerations et points de fidelite."""
import math
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Declaration, Material, Parameter, Payment, PointsTransaction, Report, Tariff, User, utcnow,
)

# Valeurs par defaut, modifiables depuis l'administration (table parameters).
DEFAULT_PARAMETERS = {
    "POINTS_PAR_KG_POINT_RELAIS": ("10", "Points gagnes par kg valide depose en point relais"),
    "BONUS_DEPOT_POINT_RELAIS": ("20", "Bonus fixe par depot valide en point relais"),
    "POINTS_SIGNALEMENT_CONFIRME": ("15", "Points pour un signalement confirme par un agent"),
    "COUT_CARBURANT_FCFA_KM": ("150", "Cout carburant par km de tournee"),
    "COUT_MAIN_OEUVRE_FCFA_ARRET": ("500", "Cout main d'oeuvre par arret"),
    "COUT_FIXE_TOURNEE_FCFA": ("5000", "Cout fixe par tournee (vehicule)"),
    "VITESSE_MOYENNE_KMH": ("18", "Vitesse moyenne en ville pour estimer la duree"),
    "TEMPS_ARRET_MIN": ("10", "Temps moyen passe a chaque arret"),
    "POIDS_MAX_LIGNE_KG": ("1000", "Poids maximum declarable par ligne"),
    "SEUIL_Y_KG": ("10", "Seuil Y : poids minimum pour une collecte a domicile ; en dessous, orientation vers un point relais"),
    "POINT_VALEUR_FCFA": ("1", "Conversion : valeur d'un point en FCFA"),
    "POINTS_MIN_CONVERSION": ("500", "Nombre minimum de points pour demander une conversion"),
}

# Referentiel initial des tarifs (FCFA/kg).
DEFAULT_TARIFFS = {"CARTON": 200, "PLASTIQUE": 250, "ALUMINIUM": 300}


def get_param(db: Session, key: str) -> float:
    row = db.get(Parameter, key)
    raw = row.value if row else DEFAULT_PARAMETERS[key][0]
    return float(raw)


def current_tariff(db: Session, material_id: int, at: datetime | None = None) -> Tariff | None:
    at = at or utcnow()
    stmt = (
        select(Tariff)
        .where(Tariff.material_id == material_id, Tariff.valid_from <= at)
        .where((Tariff.valid_to.is_(None)) | (Tariff.valid_to > at))
        .order_by(Tariff.valid_from.desc())
    )
    return db.scalars(stmt).first()


def set_tariff(db: Session, material: Material, price: int, user_id: int | None, note: str | None) -> Tariff:
    """Clot le tarif en vigueur et en ouvre un nouveau : l'historique est conserve."""
    if price <= 0:
        raise HTTPException(400, "Le tarif doit etre positif")
    now = utcnow()
    old = current_tariff(db, material.id, now)
    if old:
        old.valid_to = now
    new = Tariff(material_id=material.id, price_fcfa_per_kg=price, valid_from=now,
                 created_by=user_id, note=note)
    db.add(new)
    return new


def add_points(db: Session, user: User, points: int, reason: str, *,
               declaration_id: int | None = None, report_id: int | None = None) -> None:
    if points == 0:
        return
    user.points_balance = (user.points_balance or 0) + points
    db.add(PointsTransaction(user_id=user.id, points=points, reason=reason,
                             declaration_id=declaration_id, report_id=report_id))


def validate_declaration(db: Session, decl: Declaration, validated: dict[int, float], agent: User,
                         cache: dict | None = None) -> Payment | None:
    """Valide les poids reels, calcule la remuneration au tarif du jour et attribue les points.

    `validated` associe l'id de chaque ligne a son poids reellement pese.
    `cache` (facultatif) memorise tarifs et parametres pour les traitements en masse.
    Renvoie le paiement cree (ou None si le montant est nul).
    """
    if decl.status in ("VALIDEE", "REJETEE"):
        raise HTTPException(400, f"Declaration deja {decl.status.lower()}")
    if cache is not None:
        def param(key):
            if key not in cache:
                cache[key] = get_param(db, key)
            return cache[key]

        def tariff_for(material_id, at):
            k = ("tarif", material_id)
            if k not in cache:
                cache[k] = current_tariff(db, material_id, at)
            return cache[k]
    else:
        def param(key):
            return get_param(db, key)

        def tariff_for(material_id, at):
            return current_tariff(db, material_id, at)
    max_kg = param("POIDS_MAX_LIGNE_KG")
    total_kg, total_amount = 0.0, 0
    now = utcnow()
    for item in decl.items:
        if item.id not in validated:
            raise HTTPException(400, f"Poids valide manquant pour la ligne {item.id}")
        weight = float(validated[item.id])
        if weight < 0 or weight > max_kg:
            raise HTTPException(400, f"Poids invalide pour la ligne {item.id}")
        tariff = tariff_for(item.material_id, now)
        if tariff is None:
            raise HTTPException(400, f"Aucun tarif en vigueur pour {item.material.name}")
        item.validated_weight_kg = round(weight, 2)
        item.tariff_id = tariff.id
        item.unit_price_fcfa = tariff.price_fcfa_per_kg
        item.amount_fcfa = int(round(weight * tariff.price_fcfa_per_kg))
        total_kg += weight
        total_amount += item.amount_fcfa

    decl.total_validated_kg = round(total_kg, 2)
    decl.total_amount_fcfa = total_amount
    decl.status = "VALIDEE"
    decl.validated_by = agent.id
    decl.validated_at = now

    payment = None
    if total_amount > 0:
        payment = Payment(user_id=decl.user_id, declaration_id=decl.id, amount_fcfa=total_amount)
        db.add(payment)

    # Points de fidelite : uniquement pour les apports en point relais.
    if decl.mode == "POINT_RELAIS" and total_kg > 0:
        points = int(math.floor(total_kg * param("POINTS_PAR_KG_POINT_RELAIS"))
                     + param("BONUS_DEPOT_POINT_RELAIS"))
        decl.points_awarded = points
        add_points(db, decl.user, points, "Depot en point relais", declaration_id=decl.id)
    return payment


def check_seuil_y(db: Session, mode: str, total_kg: float) -> None:
    """Seuil Y : sous ce poids, une collecte a domicile coute plus qu'elle ne rapporte."""
    seuil = get_param(db, "SEUIL_Y_KG")
    if mode == "COLLECTE_DOMICILE" and total_kg < seuil:
        raise HTTPException(
            400, f"La collecte a domicile est reservee aux apports d'au moins {seuil:g} kg (seuil Y). "
                 "Depose plutot tes dechets dans un point relais : tu gagnes en plus des points de fidelite.")


def convert_points(db: Session, user: User, points: int) -> Payment:
    """Convertit des points en FCFA (verses comme une remuneration, en Mobile Money)."""
    minimum = int(get_param(db, "POINTS_MIN_CONVERSION"))
    if points < minimum:
        raise HTTPException(400, f"Minimum {minimum} points pour une conversion")
    if points > (user.points_balance or 0):
        raise HTTPException(400, "Solde de points insuffisant")
    amount = int(round(points * get_param(db, "POINT_VALEUR_FCFA")))
    add_points(db, user, -points, "Conversion en FCFA")
    pay = Payment(user_id=user.id, kind="CONVERSION_POINTS", points_converted=points, amount_fcfa=amount)
    db.add(pay)
    return pay


def confirm_report(db: Session, report: Report) -> None:
    if report.points_awarded:
        return
    points = int(get_param(db, "POINTS_SIGNALEMENT_CONFIRME"))
    report.points_awarded = points
    add_points(db, report.user, points, "Signalement confirme", report_id=report.id)
