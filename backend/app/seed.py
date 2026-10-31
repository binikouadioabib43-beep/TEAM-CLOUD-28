"""Donnees de reference (communes, matieres, tarifs, parametres) et jeu de demonstration."""
import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AIAnalysis, Commune, Declaration, DeclarationItem, Material, Parameter, Payment, Photo,
    RelayPoint, Report, Tariff, User, utcnow,
)
from .security import hash_password
from .services.business import DEFAULT_PARAMETERS, DEFAULT_TARIFFS, confirm_report, validate_declaration

DEMO_PASSWORD = "Demo@2026"

COMMUNES = [
    ("Abobo", 5.4167, -4.0167, 1030658), ("Adjame", 5.3667, -4.0167, 372978),
    ("Attecoube", 5.3333, -4.0400, 260911), ("Cocody", 5.3600, -3.9700, 447055),
    ("Koumassi", 5.2900, -3.9500, 433139), ("Marcory", 5.3000, -3.9800, 249858),
    ("Plateau", 5.3250, -4.0200, 7488), ("Port-Bouet", 5.2550, -3.9250, 419033),
    ("Treichville", 5.2950, -4.0050, 102580), ("Yopougon", 5.3450, -4.0750, 1571065),
    ("Bingerville", 5.3550, -3.8850, 204656), ("Songon", 5.3200, -4.2500, 81568),
    ("Anyama", 5.4950, -4.0520, 389592),
]

MATERIALS = [
    ("CARTON", "Carton", "Cartons d'emballage, cartons ondules", True),
    ("PLASTIQUE", "Plastique", "Bouteilles PET, bidons, sachets", True),
    ("ALUMINIUM", "Aluminium", "Canettes, barquettes aluminium", True),
    ("VERRE", "Verre", "Non rachete pour l'instant", False),
    ("ORGANIQUE", "Organique", "Restes alimentaires, vegetaux", False),
]

RELAY_POINTS = [
    ("Point Relais Cocody Angre", "Cocody", "Angre 8e tranche, pres du marche", 5.3950, -3.9900),
    ("Point Relais Yopougon Siporex", "Yopougon", "Carrefour Siporex", 5.3400, -4.0830),
    ("Point Relais Abobo Gare", "Abobo", "Gare d'Abobo", 5.4210, -4.0200),
    ("Point Relais Marcory Zone 4", "Marcory", "Rue du Dr Blanchard", 5.2930, -3.9780),
    ("Point Relais Treichville Marche", "Treichville", "Avenue 16, marche de Treichville", 5.2990, -4.0080),
    ("Point Relais Koumassi Remblais", "Koumassi", "Boulevard du Gabon", 5.2950, -3.9450),
    ("Point Relais Adjame Liberte", "Adjame", "Carrefour Liberte", 5.3600, -4.0230),
]


def seed_reference(db: Session) -> None:
    if db.scalar(select(func.count(Commune.id))):
        return
    for name, lat, lon, pop in COMMUNES:
        db.add(Commune(name=name, latitude=lat, longitude=lon, population=pop))
    for code, name, desc, recyclable in MATERIALS:
        db.add(Material(code=code, name=name, description=desc, is_recyclable=recyclable))
    for key, (value, desc) in DEFAULT_PARAMETERS.items():
        db.add(Parameter(key=key, value=value, description=desc))
    db.flush()

    start = utcnow() - timedelta(days=365)
    for code, price in DEFAULT_TARIFFS.items():
        mat = db.scalar(select(Material).where(Material.code == code))
        db.add(Tariff(material_id=mat.id, price_fcfa_per_kg=price, valid_from=start,
                      note="Referentiel initial"))
    communes = {c.name: c for c in db.scalars(select(Commune))}
    for name, commune, address, lat, lon in RELAY_POINTS:
        db.add(RelayPoint(name=name, commune_id=communes[commune].id, address=address,
                          latitude=lat, longitude=lon, opening_hours="Lun-Sam 8h-18h",
                          capacity_kg=2000))
    db.add(User(email="admin@ecoabidjan.ci", full_name="Administrateur EcoAbidjan",
                password_hash=hash_password(DEMO_PASSWORD), role="admin"))
    db.add(User(email="agent@ecoabidjan.ci", full_name="Agent de collecte",
                password_hash=hash_password(DEMO_PASSWORD), role="agent",
                commune_id=communes["Cocody"].id))
    db.commit()


def seed_demo(db: Session) -> None:
    """Genere 6 mois d'activite fictive pour que le tableau de bord soit parlant."""
    if db.scalar(select(func.count(Report.id))):
        return
    rng = random.Random(42)
    communes = list(db.scalars(select(Commune)))
    materials = {m.code: m for m in db.scalars(select(Material))}
    relays = list(db.scalars(select(RelayPoint)))
    agent = db.scalar(select(User).where(User.role == "agent"))

    pwd = hash_password(DEMO_PASSWORD)
    citizen = User(email="citoyen@ecoabidjan.ci", full_name="Awa Kone", role="citoyen",
                   password_hash=pwd, commune_id=communes[9].id, phone="+225 07 00 00 01")
    household = User(email="menage@ecoabidjan.ci", full_name="Famille Yao", role="menage",
                     password_hash=pwd, commune_id=communes[3].id, household_size=6)
    trader = User(email="commercant@ecoabidjan.ci", full_name="Moussa Traore", role="commercant",
                  password_hash=pwd, commune_id=communes[8].id, business_name="Maquis Le Bon Gout",
                  business_type="Restauration")
    db.add_all([citizen, household, trader])
    others = []
    for i in range(12):
        c = rng.choice(communes)
        u = User(email=f"usager{i + 1}@demo.ci", full_name=f"Usager demo {i + 1}",
                 role=rng.choice(["citoyen", "menage", "commercant"]), password_hash=pwd,
                 commune_id=c.id)
        others.append(u)
    db.add_all(others)
    db.flush()
    people = [citizen, household, trader, *others]
    now = utcnow()

    for _ in range(70):
        c = rng.choice(communes)
        created = now - timedelta(days=rng.randint(0, 180), hours=rng.randint(0, 23))
        status = rng.choices(["SIGNALE", "CONFIRME", "COLLECTE", "REJETE"], [3, 3, 5, 1])[0]
        est = round(rng.uniform(20, 600), 1)
        r = Report(user_id=rng.choice(people).id, commune_id=c.id,
                   latitude=c.latitude + rng.uniform(-0.012, 0.012),
                   longitude=c.longitude + rng.uniform(-0.012, 0.012),
                   description="Depot sauvage (donnee de demonstration)", status=status,
                   ai_estimated_weight_kg=est, created_at=created, updated_at=created)
        if status == "COLLECTE":
            r.validated_weight_kg = round(est * rng.uniform(0.6, 1.4), 1)
        db.add(r)
        db.flush()
        photo = Photo(report_id=r.id, file_path="demo.jpg", original_name="demo.jpg",
                      content_type="image/jpeg", sha256="0" * 64, uploaded_at=created)
        db.add(photo)
        db.flush()
        shares = [rng.random() for _ in range(3)]
        tot = sum(shares)
        db.add(AIAnalysis(
            photo_id=photo.id, report_id=r.id, provider="demo", model="jeu-de-demonstration",
            materials=[{"code": code, "share": round(s / tot, 3), "confidence": 0.6}
                       for code, s in zip(["PLASTIQUE", "CARTON", "ORGANIQUE"], shares)],
            estimated_weight_kg=est, estimated_volume_m3=round(est / 150, 2), confidence=0.6,
            summary="Analyse fictive generee pour la demonstration.", created_at=created,
        ))
        if status in ("CONFIRME", "COLLECTE"):
            db.refresh(r)
            confirm_report(db, r)

    for _ in range(110):
        user = rng.choice(people)
        created = now - timedelta(days=rng.randint(0, 180), hours=rng.randint(0, 23))
        mode = rng.choices(["POINT_RELAIS", "COLLECTE_DOMICILE"], [3, 1])[0]
        relay = rng.choice(relays) if mode == "POINT_RELAIS" else None
        commune = user.commune or rng.choice(communes)
        d = Declaration(user_id=user.id, mode=mode, relay_point_id=relay.id if relay else None,
                        latitude=None if relay else commune.latitude + rng.uniform(-0.01, 0.01),
                        longitude=None if relay else commune.longitude + rng.uniform(-0.01, 0.01),
                        created_at=created)
        codes = rng.sample(["CARTON", "PLASTIQUE", "ALUMINIUM"], rng.randint(1, 3))
        scale = 8 if user.role == "commercant" else 1
        for code in codes:
            d.items.append(DeclarationItem(material_id=materials[code].id,
                                           estimated_weight_kg=round(rng.uniform(1, 15) * scale, 1)))
        d.total_estimated_kg = round(sum(i.estimated_weight_kg for i in d.items), 1)
        db.add(d)
        db.flush()
        if created < now - timedelta(days=2) and rng.random() < 0.85:
            if rng.random() < 0.07:
                d.status, d.rejection_reason = "REJETEE", "Matieres non conformes"
            else:
                validated = {i.id: round(i.estimated_weight_kg * rng.uniform(0.75, 1.1), 1)
                             for i in d.items}
                validate_declaration(db, d, validated, agent)
                d.validated_at = created + timedelta(days=rng.randint(0, 2))
                db.flush()
                pay =db.scalar(select(Payment).where(Payment.declaration_id == d.id))
                if pay:
                    pay.created_at = d.validated_at
                    if rng.random() < 0.7:
                        pay.status, pay.paid_at = "PAYEE", d.validated_at + timedelta(days=1)
                        pay.reference = f"OM-{rng.randint(100000, 999999)}"
    db.commit()


def run_seed(db: Session) -> None:
    seed_reference(db)
    if settings.seed_demo:
        seed_demo(db)
