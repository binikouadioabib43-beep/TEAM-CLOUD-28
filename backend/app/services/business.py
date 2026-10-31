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


def validate_declaration(db: Session, decl: Declaration, validated: dict[int, float], agent: User) -> Declaration:
    """Valide les poids reels, calcule la remuneration au tarif du jour et attribue les points.

    `validated` associe l'id de chaque ligne a son poids reellement pese.
    """
    if decl.status in ("VALIDEE", "REJETEE"):
        raise HTTPException(400, f"Declaration deja {decl.status.lower()}")
    max_kg = get_param(db, "POIDS_MAX_LIGNE_KG")
    total_kg, total_amount = 0.0, 0
    now = utcnow()
    for item in decl.items:
        if item.id not in validated:
            raise HTTPException(400, f"Poids valide manquant pour la ligne {item.id}")
        weight = float(validated[item.id])
        if weight < 0 or weight > max_kg:
            raise HTTPException(400, f"Poids invalide pour la ligne {item.id}")
        tariff = current_tariff(db, item.material_id, now)
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

    if total_amount > 0:
        db.add(Payment(user_id=decl.user_id, declaration_id=decl.id, amount_fcfa=total_amount))

    # Points de fidelite : uniquement pour les apports en point relais.
    if decl.mode == "POINT_RELAIS" and total_kg > 0:
        points = int(math.floor(total_kg * get_param(db, "POINTS_PAR_KG_POINT_RELAIS"))
                     + get_param(db, "BONUS_DEPOT_POINT_RELAIS"))
        decl.points_awarded = points
        add_points(db, decl.user, points, "Depot en point relais", declaration_id=decl.id)
    return decl


def confirm_report(db: Session, report: Report) -> None:
    if report.points_awarded:
        return
    points = int(get_param(db, "POINTS_SIGNALEMENT_CONFIRME"))
    report.points_awarded = points
    add_points(db, report.user, points, "Signalement confirme", report_id=report.id)
