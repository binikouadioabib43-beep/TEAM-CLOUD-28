"""Referentiel (communes, matieres, tarifs, parametres) et simulation du projet pilote.

Simulation : 4 communes pilotes (Cocody, Yopougon, Abobo, Koumassi), 500 menages,
200 commercants et 150 citoyens, avec 90 jours d'activite (declarations, pesees,
paiements, points, conversions, signalements et tournees). Resultat reproductible (graine fixe).
"""
import math
import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AIAnalysis, Collection, CollectionCost, CollectionStop, Commune, Declaration, DeclarationItem,
    Material, Parameter, Payment, Photo, RelayPoint, Report, Tariff, User, utcnow,
)
from .security import hash_password
from .services.business import (
    DEFAULT_PARAMETERS, DEFAULT_TARIFFS, confirm_report, convert_points, get_param, validate_declaration,
)
from .services.routing import haversine_km, optimize_route

DEMO_PASSWORD = "Demo@2026"
PILOT_COMMUNES = ("Cocody", "Yopougon", "Abobo", "Koumassi")
SIM_DAYS = 90
N_MENAGES, N_COMMERCANTS, N_CITOYENS = 500, 200, 150

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

# 2 points relais par commune pilote (+ 3 hors pilote pour l'extension)
RELAY_POINTS = [
    ("Point Relais Cocody Angre", "Cocody", "Angre 8e tranche, pres du marche", 5.3950, -3.9900),
    ("Point Relais Cocody Riviera 2", "Cocody", "Carrefour Riviera 2", 5.3480, -3.9600),
    ("Point Relais Yopougon Siporex", "Yopougon", "Carrefour Siporex", 5.3400, -4.0830),
    ("Point Relais Yopougon Niangon", "Yopougon", "Niangon Lokoa, gare wôrô-wôrô", 5.3250, -4.1000),
    ("Point Relais Abobo Gare", "Abobo", "Gare d'Abobo", 5.4210, -4.0200),
    ("Point Relais Abobo PK18", "Abobo", "PK18, marche", 5.4420, -4.0350),
    ("Point Relais Koumassi Remblais", "Koumassi", "Boulevard du Gabon", 5.2950, -3.9450),
    ("Point Relais Koumassi Grand Marche", "Koumassi", "Grand marche de Koumassi", 5.2880, -3.9560),
    ("Point Relais Marcory Zone 4", "Marcory", "Rue du Dr Blanchard", 5.2930, -3.9780),
    ("Point Relais Treichville Marche", "Treichville", "Avenue 16, marche de Treichville", 5.2990, -4.0080),
    ("Point Relais Adjame Liberte", "Adjame", "Carrefour Liberte", 5.3600, -4.0230),
]

FIRST_NAMES = ["Awa", "Aya", "Adjoua", "Amenan", "Affoue", "Mariam", "Fatou", "Aminata", "Salimata", "Christelle",
               "Grace", "Esther", "Kouadio", "Koffi", "Yao", "Kouame", "Konan", "Ibrahim", "Moussa", "Seydou",
               "Souleymane", "Drissa", "Jean-Marc", "Serge", "Didier", "Hermann", "Arsene", "Franck", "Rachel", "Nadege"]
LAST_NAMES = ["Kone", "Traore", "Ouattara", "Coulibaly", "Bamba", "Diabate", "Toure", "Cisse", "Kouassi", "Yao",
              "Koffi", "N'Guessan", "Kouame", "Konan", "Aka", "Brou", "Gbagbo", "Tano", "Zadi", "Gnagne", "Dosso",
              "Fofana", "Sangare", "Kra", "Assi", "Ehui", "Amani", "Djedje", "Seri", "Bley"]
# type de commerce -> (part, multiplicateur de volume, materiaux dominants)
BUSINESS_TYPES = {
    "Maquis / restaurant": (0.30, 1.0, {"PLASTIQUE": 0.45, "ALUMINIUM": 0.35, "CARTON": 0.20}),
    "Boutique / epicerie": (0.30, 0.8, {"CARTON": 0.55, "PLASTIQUE": 0.40, "ALUMINIUM": 0.05}),
    "Supermarche": (0.08, 3.0, {"CARTON": 0.65, "PLASTIQUE": 0.30, "ALUMINIUM": 0.05}),
    "Commerce du marche": (0.22, 1.2, {"PLASTIQUE": 0.55, "CARTON": 0.40, "ALUMINIUM": 0.05}),
    "Bar / buvette": (0.10, 1.1, {"ALUMINIUM": 0.50, "PLASTIQUE": 0.40, "CARTON": 0.10}),
}
# poids relatif des communes dans l'echantillon (proche de leur population)
PILOT_WEIGHTS = {"Yopougon": 0.36, "Abobo": 0.26, "Cocody": 0.20, "Koumassi": 0.18}


def seed_reference(db: Session) -> None:
    # Parametres ajoutes apres coup : crees s'ils manquent
    for key, (value, desc) in DEFAULT_PARAMETERS.items():
        if db.get(Parameter, key) is None:
            db.add(Parameter(key=key, value=value, description=desc))
    if db.scalar(select(func.count(Commune.id))):
        db.commit()
        return
    for name, lat, lon, pop in COMMUNES:
        db.add(Commune(name=name, latitude=lat, longitude=lon, population=pop, is_pilot=name in PILOT_COMMUNES))
    for code, name, desc, recyclable in MATERIALS:
        db.add(Material(code=code, name=name, description=desc, is_recyclable=recyclable))
    db.flush()

    start = utcnow() - timedelta(days=365)
    for code, price in DEFAULT_TARIFFS.items():
        mat = db.scalar(select(Material).where(Material.code == code))
        db.add(Tariff(material_id=mat.id, price_fcfa_per_kg=price, valid_from=start, note="Referentiel initial"))
    communes = {c.name: c for c in db.scalars(select(Commune))}
    for name, commune, address, lat, lon in RELAY_POINTS:
        db.add(RelayPoint(name=name, commune_id=communes[commune].id, address=address, latitude=lat,
                          longitude=lon, opening_hours="Lun-Sam 8h-18h", capacity_kg=3000))
    pwd = hash_password(DEMO_PASSWORD)
    db.add(User(email="admin@ecoabidjan.ci", full_name="Administrateur EcoAbidjan", password_hash=pwd, role="admin"))
    db.add(User(email="agent@ecoabidjan.ci", full_name="Agent de collecte", password_hash=pwd, role="agent",
                commune_id=communes["Cocody"].id))
    db.commit()


# --- Simulation -----------------------------------------------------------------------

def _jitter(rng, lat, lon, spread=0.018):
    return lat + rng.uniform(-spread, spread), lon + rng.uniform(-spread, spread)


def _split(rng, total: float, mix: dict[str, float]) -> dict[str, float]:
    out = {}
    for code, share in mix.items():
        kg = total * share * rng.uniform(0.6, 1.4)
        if kg >= 0.2:
            out[code] = round(kg, 1)
    return out


def simulate_pilot(db: Session) -> dict:
    if db.scalar(select(func.count(Report.id))):
        return {}
    rng = random.Random(2026)
    now = utcnow()
    communes = {c.name: c for c in db.scalars(select(Commune))}
    pilot = [communes[n] for n in PILOT_COMMUNES]
    materials = {m.code: m for m in db.scalars(select(Material))}
    relays = list(db.scalars(select(RelayPoint)))
    relays_by_commune = {c.id: [r for r in relays if r.commune_id == c.id] for c in pilot}
    agent = db.scalar(select(User).where(User.role == "agent"))
    seuil_y = get_param(db, "SEUIL_Y_KG")
    pwd = hash_password(DEMO_PASSWORD)  # meme mot de passe pour tous les comptes simules

    def pick_commune():
        return rng.choices(pilot, weights=[PILOT_WEIGHTS[c.name] for c in pilot])[0]

    def person():
        return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

    # Comptes de demonstration nominatifs (communes pilotes)
    demo = [
        User(email="citoyen@ecoabidjan.ci", full_name="Awa Kone", role="citoyen", password_hash=pwd,
             commune_id=communes["Yopougon"].id, phone="+225 07 00 00 01"),
        User(email="menage@ecoabidjan.ci", full_name="Famille Yao", role="menage", password_hash=pwd,
             commune_id=communes["Cocody"].id, household_size=6),
        User(email="commercant@ecoabidjan.ci", full_name="Moussa Traore", role="commercant", password_hash=pwd,
             commune_id=communes["Koumassi"].id, business_name="Maquis Le Bon Gout",
             business_type="Maquis / restaurant"),
    ]
    db.add_all(demo)

    households, traders, citizens = [demo[1]], [demo[2]], [demo[0]]
    homes = {}
    for i in range(N_MENAGES - 1):
        c = pick_commune()
        u = User(email=f"menage{i + 1:03d}@sim.ecoabidjan.ci", full_name=f"Famille {rng.choice(LAST_NAMES)}",
                 role="menage", password_hash=pwd, commune_id=c.id, household_size=rng.choice([2, 3, 4, 5, 5, 6, 7, 8, 10]),
                 created_at=now - timedelta(days=rng.randint(SIM_DAYS, SIM_DAYS + 20)))
        households.append(u)
    btypes = list(BUSINESS_TYPES)
    for i in range(N_COMMERCANTS - 1):
        c = pick_commune()
        bt = rng.choices(btypes, weights=[BUSINESS_TYPES[b][0] for b in btypes])[0]
        u = User(email=f"commercant{i + 1:03d}@sim.ecoabidjan.ci", full_name=person(), role="commercant",
                 password_hash=pwd, commune_id=c.id, business_type=bt,
                 business_name=f"{bt.split(' /')[0]} {rng.choice(LAST_NAMES)}",
                 created_at=now - timedelta(days=rng.randint(SIM_DAYS, SIM_DAYS + 20)))
        traders.append(u)
    for i in range(N_CITOYENS - 1):
        c = pick_commune()
        citizens.append(User(email=f"citoyen{i + 1:03d}@sim.ecoabidjan.ci", full_name=person(), role="citoyen",
                             password_hash=pwd, commune_id=c.id))
    db.add_all(households + traders + citizens)
    db.flush()
    communes_by_id = {c.id: c for c in communes.values()}
    for u in households + traders + citizens:
        c = communes_by_id[u.commune_id]
        homes[u.id] = _jitter(rng, c.latitude, c.longitude)

    # --- Declarations : comportement selon le profil ---
    stats = {"declarations": 0, "domicile_refusees_seuil_y": 0}

    def declare(u: User, day_offset: float, kg_by_code: dict[str, float]):
        total = sum(kg_by_code.values())
        if not total:
            return
        lat, lon = homes[u.id]
        home_wanted = rng.random() < (0.65 if u.role == "commercant" else 0.45)
        if home_wanted and total < seuil_y:
            stats["domicile_refusees_seuil_y"] += 1  # oriente vers un point relais par le seuil Y
            home_wanted = False
        created = now - timedelta(days=day_offset)
        if home_wanted:
            d = Declaration(user_id=u.id, mode="COLLECTE_DOMICILE", latitude=lat, longitude=lon, created_at=created)
        else:
            near = min(relays_by_commune[u.commune_id], key=lambda r: haversine_km((lat, lon), (r.latitude, r.longitude)))
            d = Declaration(user_id=u.id, mode="POINT_RELAIS", relay_point_id=near.id, created_at=created)
        for code, kg in kg_by_code.items():
            d.items.append(DeclarationItem(material_id=materials[code].id, estimated_weight_kg=kg))
        d.total_estimated_kg = round(total, 1)
        db.add(d)
        stats["declarations"] += 1
        return d

    pending_validation = []
    for u in households:
        if rng.random() > 0.78:  # ~22 % d'inscrits peu actifs
            continue
        period = rng.uniform(7, 18)
        size = u.household_size or 4
        t = rng.uniform(0, period)
        while t < SIM_DAYS:
            total = rng.uniform(1.5, 4.0) * (size / 4) ** 0.7 * (period / 10)
            d = declare(u, SIM_DAYS - t, _split(rng, total, {"PLASTIQUE": 0.5, "CARTON": 0.35, "ALUMINIUM": 0.15}))
            if d is not None:
                pending_validation.append(d)
            t += period * rng.uniform(0.7, 1.3)
    for u in traders:
        if rng.random() > 0.88:
            continue
        _, mult, mix = BUSINESS_TYPES.get(u.business_type, (0, 1.0, {"PLASTIQUE": 0.5, "CARTON": 0.5}))
        period = rng.uniform(4, 10)
        t = rng.uniform(0, period)
        while t < SIM_DAYS:
            total = rng.uniform(8, 25) * mult * (period / 7)
            d = declare(u, SIM_DAYS - t, _split(rng, total, mix))
            if d is not None:
                pending_validation.append(d)
            t += period * rng.uniform(0.7, 1.3)
    db.flush()

    # --- Pesee / validation par les agents, paiements ---
    cache: dict = {}
    for d in pending_validation:
        age_days = (now - d.created_at).days
        if age_days < 3:
            continue  # encore en attente : alimente la file de validation et les tournees
        if rng.random() < 0.03:
            d.status, d.rejection_reason = "REJETEE", rng.choice(["Matieres souillees", "Melange non trie"])
            d.validated_by, d.validated_at = agent.id, d.created_at + timedelta(days=1)
            continue
        ratio = rng.uniform(0.82, 1.05)  # les usagers surestiment legerement
        pay = validate_declaration(db, d, {i.id: round(i.estimated_weight_kg * ratio, 1) for i in d.items}, agent, cache)
        d.validated_at = d.created_at + timedelta(days=rng.choice([0, 1, 1, 2]))
        if pay:
            pay.created_at = d.validated_at
            if age_days > 6 and rng.random() < 0.85:
                pay.status, pay.paid_at = "PAYEE", d.validated_at + timedelta(days=rng.randint(1, 4))
                pay.method = rng.choice(["MOBILE_MONEY"] * 9 + ["ESPECES"])
                pay.reference = f"MM-{rng.randint(10**7, 10**8 - 1)}"
    db.flush()

    # --- Signalements de depots sauvages ---
    reporters = citizens + rng.sample(households, 120)
    hotspots = [(c, _jitter(rng, c.latitude, c.longitude, 0.02)) for c in pilot for _ in range(6)]
    for _ in range(420):
        c, (hlat, hlon) = rng.choice(hotspots)
        u = rng.choice(reporters)
        created = now - timedelta(days=rng.uniform(0, SIM_DAYS))
        age = (now - created).days
        if age > 14:
            status = rng.choices(["COLLECTE", "REJETE"], [92, 8])[0]
        elif age > 4:
            status = rng.choices(["COLLECTE", "CONFIRME", "REJETE"], [55, 38, 7])[0]
        else:
            status = rng.choices(["SIGNALE", "CONFIRME"], [70, 30])[0]
        mix = {"PLASTIQUE": rng.uniform(0.3, 0.6), "ORGANIQUE": rng.uniform(0.1, 0.4),
               "CARTON": rng.uniform(0.05, 0.25), "TEXTILE": rng.uniform(0, 0.1)}
        tot = sum(mix.values())
        est = round(rng.lognormvariate(math.log(120), 0.7), 1)
        r = Report(user_id=u.id, commune_id=c.id, latitude=hlat + rng.uniform(-0.004, 0.004),
                   longitude=hlon + rng.uniform(-0.004, 0.004), description="Depot sauvage (simulation)",
                   status=status, ai_estimated_weight_kg=est, created_at=created,
                   updated_at=created + timedelta(days=rng.uniform(1, 6)) if status == "COLLECTE" else created)
        if status == "COLLECTE":
            r.validated_weight_kg = round(est * rng.uniform(0.7, 1.35), 1)
        db.add(r)
        db.flush()
        ph = Photo(report_id=r.id, file_path="simulation.jpg", original_name="simulation.jpg",
                   content_type="image/jpeg", sha256="0" * 64, uploaded_at=created)
        db.add(ph)
        db.flush()
        db.add(AIAnalysis(photo_id=ph.id, report_id=r.id, provider="simulation", model="donnees-synthetiques",
                          materials=[{"code": k, "share": round(v / tot, 3), "confidence": round(rng.uniform(0.5, 0.9), 2)}
                                     for k, v in mix.items()],
                          estimated_weight_kg=est, estimated_volume_m3=round(est / 140, 2),
                          confidence=round(rng.uniform(0.5, 0.85), 2), created_at=created,
                          summary="Analyse simulee (jeu de donnees synthetiques)."))
        if status in ("CONFIRME", "COLLECTE"):
            keep = r.updated_at
            confirm_report(db, r)
            # valeur explicite (et differente) : empeche la mise a jour automatique de la date
            r.updated_at = keep + timedelta(microseconds=1)
    db.flush()

    # --- Tournees passees (signalements collectes, regroupes par commune et par semaine) ---
    collected = list(db.scalars(select(Report).where(Report.status == "COLLECTE")))
    groups: dict[tuple, list[Report]] = {}
    for r in collected:
        groups.setdefault((r.commune_id, r.updated_at.isocalendar()[1]), []).append(r)
    for (cid, week), reps in sorted(groups.items(), key=lambda kv: kv[0][1]):
        depot = relays_by_commune[cid][0]
        route = optimize_route((depot.latitude, depot.longitude), [(r.latitude, r.longitude) for r in reps])
        day = min(r.updated_at for r in reps).date()
        cost = int(route["distance_km"] * 150 + len(reps) * 500 + 5000)
        col = Collection(name=f"Tournee {communes_by_id[cid].name} S{week}", planned_date=day,
                         depot_label=depot.name, depot_latitude=depot.latitude, depot_longitude=depot.longitude,
                         vehicle_type="CAMIONNETTE" if len(reps) > 6 else "TRICYCLE", status="TERMINEE",
                         total_distance_km=route["distance_km"],
                         estimated_duration_min=round(route["distance_km"] / 18 * 60 + len(reps) * 10),
                         estimated_cost_fcfa=cost, created_by=agent.id)
        db.add(col)
        db.flush()
        for seq, (idx, leg) in enumerate(zip(route["order"], route["legs_km"]), start=1):
            r = reps[idx]
            col.stops.append(CollectionStop(sequence=seq, stop_type="SIGNALEMENT", report_id=r.id,
                                            latitude=r.latitude, longitude=r.longitude,
                                            distance_from_previous_km=leg, status="FAIT",
                                            collected_weight_kg=r.validated_weight_kg))
            r.collection_id = col.id
        col.costs.append(CollectionCost(cost_type="CARBURANT", amount_fcfa=int(route["distance_km"] * rng.uniform(130, 180))))
        col.costs.append(CollectionCost(cost_type="MAIN_OEUVRE", amount_fcfa=len(reps) * 500))
        col.costs.append(CollectionCost(cost_type="VEHICULE", amount_fcfa=5000))

    # --- Conversion de points par une partie des usagers ---
    minimum = int(get_param(db, "POINTS_MIN_CONVERSION"))
    for u in households + traders + citizens:
        if u.points_balance >= minimum and rng.random() < 0.45 and u not in demo:
            pts = (u.points_balance // 100) * 100
            pay = convert_points(db, u, pts)
            pay.created_at = now - timedelta(days=rng.uniform(1, 20))
            if rng.random() < 0.8:
                pay.status, pay.paid_at, pay.reference = "PAYEE", pay.created_at + timedelta(days=1), f"MM-{rng.randint(10**7, 10**8 - 1)}"
    db.commit()
    return stats


def run_seed(db: Session) -> None:
    seed_reference(db)
    if settings.seed_demo:
        simulate_pilot(db)
