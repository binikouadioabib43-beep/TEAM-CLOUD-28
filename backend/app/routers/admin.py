"""Espace agents et administrateurs : validation, tarifs, collectes, tableau de bord, Snowflake."""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Collection, CollectionCost, CollectionStop, Commune, Declaration, DeclarationItem, Material,
    Parameter, Payment, PointsTransaction, RelayPoint, Report, Tariff, User, utcnow,
)
from ..schemas import (
    CollectionCostIn, CollectionPlanIn, MaterialIn, ParameterIn, PaymentUpdateIn, RejectIn,
    RelayPointIn, ReportStatusIn, StopUpdateIn, TariffIn, ValidationIn,
)
from ..security import require_roles
from ..serializers import (
    collection_out, declaration_out, payment_out, relay_out, report_out, tariff_out, user_out,
)
from ..services.business import confirm_report, get_param, set_tariff, validate_declaration
from ..services.routing import optimize_route

router = APIRouter(prefix="/api/admin")
staff = require_roles("agent", "admin")
admin_only = require_roles("admin")


# --- Signalements -------------------------------------------------------------

@router.get("/reports")
def list_reports(status: str | None = None, _: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Report).order_by(Report.created_at.desc()).limit(300)
    if status:
        stmt = stmt.where(Report.status == status)
    return [report_out(r) for r in db.scalars(stmt)]


@router.patch("/reports/{report_id}/status")
def update_report(report_id: int, data: ReportStatusIn, _: User = Depends(staff),
                  db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Signalement introuvable")
    if r.status in ("COLLECTE", "REJETE"):
        raise HTTPException(400, "Signalement deja clos")
    r.status = data.status
    if data.status in ("CONFIRME", "COLLECTE"):
        confirm_report(db, r)
    if data.status == "COLLECTE" and data.validated_weight_kg is not None:
        r.validated_weight_kg = data.validated_weight_kg
    db.commit()
    db.refresh(r)
    return report_out(r)


# --- Declarations ---------------------------------------------------------------

@router.get("/declarations")
def list_declarations(status: str | None = None, _: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Declaration).order_by(Declaration.created_at.desc()).limit(300)
    if status:
        stmt = stmt.where(Declaration.status == status)
    return [declaration_out(d) for d in db.scalars(stmt)]


@router.post("/declarations/{decl_id}/validate")
def validate(decl_id: int, data: ValidationIn, agent: User = Depends(staff), db: Session = Depends(get_db)):
    d = db.get(Declaration, decl_id)
    if d is None:
        raise HTTPException(404, "Declaration introuvable")
    validate_declaration(db, d, {i.item_id: i.validated_weight_kg for i in data.items}, agent)
    db.commit()
    db.refresh(d)
    return declaration_out(d)


@router.post("/declarations/{decl_id}/reject")
def reject(decl_id: int, data: RejectIn, agent: User = Depends(staff), db: Session = Depends(get_db)):
    d = db.get(Declaration, decl_id)
    if d is None:
        raise HTTPException(404, "Declaration introuvable")
    if d.status in ("VALIDEE", "REJETEE"):
        raise HTTPException(400, "Declaration deja traitee")
    d.status, d.rejection_reason = "REJETEE", data.reason
    d.validated_by, d.validated_at = agent.id, utcnow()
    db.commit()
    db.refresh(d)
    return declaration_out(d)


# --- Remunerations ----------------------------------------------------------------

@router.get("/payments")
def list_payments(status: str | None = None, _: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Payment).order_by(Payment.created_at.desc()).limit(300)
    if status:
        stmt = stmt.where(Payment.status == status)
    return [payment_out(p) for p in db.scalars(stmt)]


@router.patch("/payments/{payment_id}")
def update_payment(payment_id: int, data: PaymentUpdateIn, _: User = Depends(admin_only),
                   db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if p is None:
        raise HTTPException(404, "Paiement introuvable")
    if p.status != "EN_ATTENTE":
        raise HTTPException(400, "Paiement deja traite")
    p.status, p.method, p.reference = data.status, data.method, data.reference
    if data.status == "PAYEE":
        p.paid_at = utcnow()
    db.commit()
    return payment_out(p)


# --- Tarifs, matieres, parametres, points relais -----------------------------------

@router.get("/tariffs/history")
def tariff_history(_: User = Depends(staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(Tariff).order_by(Tariff.material_id, Tariff.valid_from.desc()))
    return [tariff_out(t) for t in rows]


@router.put("/materials/{material_id}/tariff")
def update_tariff(material_id: int, data: TariffIn, admin: User = Depends(admin_only),
                  db: Session = Depends(get_db)):
    mat = db.get(Material, material_id)
    if mat is None:
        raise HTTPException(404, "Matiere introuvable")
    if not mat.is_recyclable:
        mat.is_recyclable = True
    t = set_tariff(db, mat, data.price_fcfa_per_kg, admin.id, data.note)
    db.commit()
    db.refresh(t)
    return tariff_out(t)


@router.post("/materials", status_code=201)
def create_material(data: MaterialIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(Material).where(Material.code == data.code)):
        raise HTTPException(409, "Ce code matiere existe deja")
    mat = Material(code=data.code, name=data.name)
    db.add(mat)
    db.flush()
    set_tariff(db, mat, data.price_fcfa_per_kg, admin.id, "Creation")
    db.commit()
    return {"id": mat.id, "code": mat.code, "name": mat.name}


@router.get("/parameters")
def list_parameters(_: User = Depends(staff), db: Session = Depends(get_db)):
    return [{"key": p.key, "value": p.value, "description": p.description}
            for p in db.scalars(select(Parameter).order_by(Parameter.key))]


@router.put("/parameters/{key}")
def update_parameter(key: str, data: ParameterIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    p = db.get(Parameter, key)
    if p is None:
        raise HTTPException(404, "Parametre inconnu")
    try:
        float(data.value)
    except ValueError:
        raise HTTPException(400, "Valeur numerique attendue")
    p.value = data.value
    db.commit()
    return {"key": p.key, "value": p.value}


@router.post("/relay-points", status_code=201)
def create_relay(data: RelayPointIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    p = RelayPoint(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return relay_out(p)


@router.get("/users")
def list_users(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(500))]


# --- Collectes et itineraires ---------------------------------------------------------

@router.get("/collection-candidates")
def collection_candidates(_: User = Depends(staff), db: Session = Depends(get_db)):
    reports = db.scalars(select(Report).where(Report.status == "CONFIRME", Report.collection_id.is_(None)))
    decls = db.scalars(select(Declaration).where(
        Declaration.mode == "COLLECTE_DOMICILE", Declaration.status == "SOUMISE",
        Declaration.collection_id.is_(None)))
    return {
        "reports": [{"id": r.id, "latitude": r.latitude, "longitude": r.longitude,
                     "commune": r.commune.name if r.commune else None,
                     "ai_estimated_weight_kg": r.ai_estimated_weight_kg} for r in reports],
        "declarations": [{"id": d.id, "latitude": d.latitude, "longitude": d.longitude,
                          "user": d.user.full_name, "total_estimated_kg": d.total_estimated_kg}
                         for d in decls],
    }


@router.post("/collections", status_code=201)
def plan_collection(data: CollectionPlanIn, agent: User = Depends(staff), db: Session = Depends(get_db)):
    if data.depot_relay_point_id:
        relay = db.get(RelayPoint, data.depot_relay_point_id)
        if relay is None:
            raise HTTPException(400, "Point de depart inconnu")
        depot, label = (relay.latitude, relay.longitude), relay.name
    elif data.depot_latitude is not None and data.depot_longitude is not None:
        depot, label = (data.depot_latitude, data.depot_longitude), "Depot personnalise"
    else:
        raise HTTPException(400, "Indique un point de depart")

    stops = []
    for rid in data.report_ids:
        r = db.get(Report, rid)
        if r is None or r.status != "CONFIRME" or r.collection_id:
            raise HTTPException(400, f"Signalement {rid} non planifiable")
        stops.append(("SIGNALEMENT", r))
    for did in data.declaration_ids:
        d = db.get(Declaration, did)
        if d is None or d.mode != "COLLECTE_DOMICILE" or d.status != "SOUMISE" or d.collection_id:
            raise HTTPException(400, f"Declaration {did} non planifiable")
        stops.append(("DECLARATION", d))
    if not stops:
        raise HTTPException(400, "Selectionne au moins un arret")

    route = optimize_route(depot, [(o.latitude, o.longitude) for _, o in stops])
    speed = get_param(db, "VITESSE_MOYENNE_KMH")
    stop_min = get_param(db, "TEMPS_ARRET_MIN")
    cost = (route["distance_km"] * get_param(db, "COUT_CARBURANT_FCFA_KM")
            + len(stops) * get_param(db, "COUT_MAIN_OEUVRE_FCFA_ARRET")
            + get_param(db, "COUT_FIXE_TOURNEE_FCFA"))
    col = Collection(
        name=data.name, planned_date=data.planned_date, depot_label=label,
        depot_latitude=depot[0], depot_longitude=depot[1], vehicle_type=data.vehicle_type,
        total_distance_km=route["distance_km"],
        estimated_duration_min=round(route["distance_km"] / speed * 60 + len(stops) * stop_min),
        estimated_cost_fcfa=int(round(cost)), created_by=agent.id,
    )
    db.add(col)
    db.flush()
    for seq, (idx, leg) in enumerate(zip(route["order"], route["legs_km"]), start=1):
        kind, obj = stops[idx]
        col.stops.append(CollectionStop(
            sequence=seq, stop_type=kind, latitude=obj.latitude, longitude=obj.longitude,
            report_id=obj.id if kind == "SIGNALEMENT" else None,
            declaration_id=obj.id if kind == "DECLARATION" else None,
            distance_from_previous_km=leg,
        ))
        obj.collection_id = col.id
        obj.status = "PLANIFIE" if kind == "SIGNALEMENT" else "PLANIFIEE"
    db.commit()
    db.refresh(col)
    return collection_out(col)


@router.get("/collections")
def list_collections(_: User = Depends(staff), db: Session = Depends(get_db)):
    return [collection_out(c) for c in db.scalars(select(Collection).order_by(Collection.planned_date.desc()))]


@router.get("/collections/{col_id}")
def get_collection(col_id: int, _: User = Depends(staff), db: Session = Depends(get_db)):
    c = db.get(Collection, col_id)
    if c is None:
        raise HTTPException(404, "Tournee introuvable")
    return collection_out(c)


@router.patch("/collections/{col_id}/stops/{stop_id}")
def update_stop(col_id: int, stop_id: int, data: StopUpdateIn, agent: User = Depends(staff),
                db: Session = Depends(get_db)):
    s = db.get(CollectionStop, stop_id)
    if s is None or s.collection_id != col_id:
        raise HTTPException(404, "Arret introuvable")
    s.status, s.collected_weight_kg = data.status, data.collected_weight_kg
    if s.report_id and data.status == "FAIT":
        r = db.get(Report, s.report_id)
        r.status = "COLLECTE"
        r.validated_weight_kg = data.collected_weight_kg
        confirm_report(db, r)
    col = s.collection
    if col.status == "PLANIFIEE":
        col.status = "EN_COURS"
    if all(x.status != "A_FAIRE" for x in col.stops):
        col.status = "TERMINEE"
    db.commit()
    db.refresh(col)
    return collection_out(col)


@router.post("/collections/{col_id}/costs", status_code=201)
def add_cost(col_id: int, data: CollectionCostIn, _: User = Depends(staff), db: Session = Depends(get_db)):
    c = db.get(Collection, col_id)
    if c is None:
        raise HTTPException(404, "Tournee introuvable")
    c.costs.append(CollectionCost(**data.model_dump()))
    db.commit()
    db.refresh(c)
    return collection_out(c)


# --- Tableau de bord ------------------------------------------------------------------

@router.get("/dashboard")
def dashboard(_: User = Depends(staff), db: Session = Depends(get_db)):
    reports = list(db.scalars(select(Report)))
    items = db.execute(
        select(DeclarationItem, Declaration, Material)
        .join(Declaration, DeclarationItem.declaration_id == Declaration.id)
        .join(Material, DeclarationItem.material_id == Material.id)
        .where(Declaration.status == "VALIDEE")
    ).all()
    payments = list(db.scalars(select(Payment)))
    declarations = list(db.scalars(select(Declaration)))
    collections = list(db.scalars(select(Collection)))

    status_counts = defaultdict(int)
    for r in reports:
        status_counts[r.status] += 1

    by_material = defaultdict(lambda: {"kg": 0.0, "amount_fcfa": 0})
    for item, _, mat in items:
        by_material[mat.name]["kg"] += item.validated_weight_kg or 0
        by_material[mat.name]["amount_fcfa"] += item.amount_fcfa or 0
    kg_recycled = sum(v["kg"] for v in by_material.values())

    now = utcnow()
    months = []
    for i in range(5, -1, -1):
        y, m = divmod(now.year * 12 + now.month - 1 - i, 12)
        months.append(f"{y:04d}-{m + 1:02d}")
    monthly = {m: {"month": m, "reports": 0, "kg": 0.0, "amount_fcfa": 0} for m in months}
    for r in reports:
        key = r.created_at.strftime("%Y-%m")
        if key in monthly:
            monthly[key]["reports"] += 1
    for item, decl, _ in items:
        key = (decl.validated_at or decl.created_at).strftime("%Y-%m")
        if key in monthly:
            monthly[key]["kg"] += item.validated_weight_kg or 0
            monthly[key]["amount_fcfa"] += item.amount_fcfa or 0

    communes = {c.id: c.name for c in db.scalars(select(Commune))}
    by_commune = defaultdict(lambda: {"reports": 0, "open": 0})
    for r in reports:
        name = communes.get(r.commune_id, "Hors zone")
        by_commune[name]["reports"] += 1
        if r.status in ("SIGNALE", "CONFIRME", "PLANIFIE"):
            by_commune[name]["open"] += 1

    # Fiabilite de l'IA : ecart entre poids estime par photo et poids reellement collecte
    pairs = [(r.ai_estimated_weight_kg, r.validated_weight_kg) for r in reports
             if r.ai_estimated_weight_kg and r.validated_weight_kg]
    mape = (sum(abs(a - v) / v for a, v in pairs) / len(pairs) * 100) if pairs else None
    validated_decls = [d for d in declarations if d.status == "VALIDEE" and d.total_estimated_kg]
    decl_ratio = (sum(d.total_validated_kg or 0 for d in validated_decls)
                  / sum(d.total_estimated_kg for d in validated_decls)) if validated_decls else None

    real_costs = sum(sum(x.amount_fcfa for x in c.costs) or c.estimated_cost_fcfa for c in collections)
    relay_count = sum(1 for d in declarations if d.mode == "POINT_RELAIS")
    points_total = db.scalar(select(func.coalesce(func.sum(PointsTransaction.points), 0)))

    return {
        "kpis": {
            "reports_total": len(reports),
            "reports_open": sum(status_counts[s] for s in ("SIGNALE", "CONFIRME", "PLANIFIE")),
            "reports_collected": status_counts["COLLECTE"],
            "declarations_total": len(declarations),
            "declarations_pending": sum(1 for d in declarations if d.status in ("SOUMISE", "PLANIFIEE")),
            "kg_recycled": round(kg_recycled, 1),
            "amount_paid_fcfa": sum(p.amount_fcfa for p in payments if p.status == "PAYEE"),
            "amount_pending_fcfa": sum(p.amount_fcfa for p in payments if p.status == "EN_ATTENTE"),
            "points_distributed": int(points_total or 0),
            "users_total": db.scalar(select(func.count(User.id))),
            "relay_share_pct": round(relay_count / len(declarations) * 100, 1) if declarations else 0,
            "collections_total": len(collections),
            "collection_cost_fcfa": real_costs,
            "ai_weight_error_pct": round(mape, 1) if mape is not None else None,
            "declared_vs_validated_ratio": round(decl_ratio, 3) if decl_ratio else None,
        },
        "reports_by_status": dict(status_counts),
        "by_material": [{"material": k, "kg": round(v["kg"], 1), "amount_fcfa": v["amount_fcfa"]}
                        for k, v in sorted(by_material.items())],
        "monthly": [{**v, "kg": round(v["kg"], 1)} for v in monthly.values()],
        "by_commune": sorted(({"commune": k, **v} for k, v in by_commune.items()),
                             key=lambda x: x["reports"], reverse=True),
    }


# --- Snowflake -----------------------------------------------------------------------

@router.get("/snowflake/diagnostics")
def snowflake_diagnostics(_: User = Depends(admin_only)):
    from ..services.snowflake_client import run_diagnostics
    return run_diagnostics()


@router.post("/snowflake/sync")
def snowflake_sync(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    from ..services.snowflake_client import SnowflakeNotConfigured, sync_to_snowflake
    try:
        return {"ok": True, "tables": sync_to_snowflake(db)}
    except SnowflakeNotConfigured as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Erreur Snowflake : {exc}")
