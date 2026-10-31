"""Espace usager : signalements avec photo + GPS, declarations, portefeuille."""
import hashlib
import uuid
from io import BytesIO
from pathlib import Path

import jwt
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (
    AIAnalysis, Commune, Declaration, DeclarationItem, Material, Payment, Photo,
    PointsTransaction, RelayPoint, Report, User,
)
from ..schemas import DeclarationIn
from ..security import get_current_user, require_roles
from ..serializers import declaration_out, iso, payment_out, report_out
from ..services.ai import analyze_photo
from ..services.business import check_seuil_y, convert_points, current_tariff, get_param
from ..services.routing import haversine_km

router = APIRouter(prefix="/api")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def nearest_commune(db: Session, lat: float, lon: float) -> Commune | None:
    best, best_d = None, 1e9
    for c in db.scalars(select(Commune)):
        d = haversine_km((lat, lon), (c.latitude, c.longitude))
        if d < best_d:
            best, best_d = c, d
    return best if best_d <= 15 else None


@router.post("/reports", status_code=201)
async def create_report(
    photo: UploadFile = File(...),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    description: str | None = Form(None, max_length=1000),
    address: str | None = Form(None, max_length=255),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if photo.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Formats acceptes : JPEG, PNG ou WebP")
    content = await photo.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, f"Photo trop lourde (max {settings.max_upload_mb} Mo)")
    try:
        Image.open(BytesIO(content)).verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Le fichier n'est pas une image valide")

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[photo.content_type]
    filename = f"{uuid.uuid4().hex}{ext}"
    path = settings.upload_dir / filename
    path.write_bytes(content)

    commune = nearest_commune(db, latitude, longitude)
    report = Report(user_id=user.id, commune_id=commune.id if commune else None,
                    latitude=latitude, longitude=longitude, description=description, address=address)
    db.add(report)
    db.flush()
    ph = Photo(report_id=report.id, file_path=filename, original_name=photo.filename,
               content_type=photo.content_type, size_bytes=len(content),
               sha256=hashlib.sha256(content).hexdigest())
    db.add(ph)
    db.flush()

    result = analyze_photo(path)
    db.add(AIAnalysis(
        photo_id=ph.id, report_id=report.id, provider=result["provider"], model=result["model"],
        prompt_version=result["prompt_version"], materials=result["materials"],
        estimated_weight_kg=result["estimated_weight_kg"],
        estimated_volume_m3=result["estimated_volume_m3"], confidence=result["confidence"],
        summary=result["summary"], raw_response=result["raw_response"], status=result["status"],
        error=result["error"], duration_ms=result["duration_ms"],
    ))
    report.ai_estimated_weight_kg = result["estimated_weight_kg"]
    db.commit()
    db.refresh(report)
    return report_out(report)


@router.get("/reports/mine")
def my_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc()))
    return [report_out(r) for r in rows]


@router.get("/reports/map")
def reports_map(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signalements actifs (sans donnees personnelles) pour la carte publique."""
    rows = db.scalars(select(Report).where(Report.status.in_(["SIGNALE", "CONFIRME", "PLANIFIE"]))
                      .order_by(Report.created_at.desc()).limit(500))
    return [{"id": r.id, "latitude": r.latitude, "longitude": r.longitude, "status": r.status,
             "ai_estimated_weight_kg": r.ai_estimated_weight_kg, "created_at": iso(r.created_at)}
            for r in rows]


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int, token: str, db: Session = Depends(get_db)):
    """Les balises <img> ne peuvent pas envoyer d'en-tete : le jeton passe en parametre."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Jeton invalide")
    ph = db.get(Photo, photo_id)
    if ph is None:
        raise HTTPException(404, "Photo introuvable")
    report = db.get(Report, ph.report_id) if ph.report_id else None
    if payload.get("role") not in ("agent", "admin") and (report is None or str(report.user_id) != payload["sub"]):
        raise HTTPException(403, "Acces reserve")
    path = (settings.upload_dir / ph.file_path).resolve()
    if not path.is_file() or Path(settings.upload_dir).resolve() not in path.parents:
        raise HTTPException(404, "Fichier absent (donnee de demonstration)")
    return FileResponse(path, media_type=ph.content_type)


@router.post("/declarations", status_code=201)
def create_declaration(
    data: DeclarationIn,
    user: User = Depends(require_roles("menage", "commercant", "citoyen")),
    db: Session = Depends(get_db),
):
    if data.mode == "POINT_RELAIS":
        relay = db.get(RelayPoint, data.relay_point_id) if data.relay_point_id else None
        if relay is None or not relay.is_active:
            raise HTTPException(400, "Choisis un point relais valide")
    elif data.latitude is None or data.longitude is None:
        raise HTTPException(400, "La position GPS est obligatoire pour une collecte a domicile")

    decl = Declaration(user_id=user.id, mode=data.mode,
                       relay_point_id=data.relay_point_id if data.mode == "POINT_RELAIS" else None,
                       latitude=data.latitude, longitude=data.longitude, note=data.note)
    seen = set()
    for item in data.items:
        mat = db.get(Material, item.material_id)
        if mat is None or not mat.is_active or not mat.is_recyclable:
            raise HTTPException(400, "Matiere non rachetee")
        if mat.id in seen:
            raise HTTPException(400, f"{mat.name} apparait deux fois")
        if current_tariff(db, mat.id) is None:
            raise HTTPException(400, f"Aucun tarif en vigueur pour {mat.name}")
        seen.add(mat.id)
        decl.items.append(DeclarationItem(material_id=mat.id, estimated_weight_kg=item.estimated_weight_kg))
    decl.total_estimated_kg = round(sum(i.estimated_weight_kg for i in data.items), 2)
    check_seuil_y(db, data.mode, decl.total_estimated_kg)
    db.add(decl)
    db.commit()
    db.refresh(decl)
    return declaration_out(decl)


@router.get("/declarations/mine")
def my_declarations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Declaration).where(Declaration.user_id == user.id)
                      .order_by(Declaration.created_at.desc()))
    return [declaration_out(d) for d in rows]


@router.post("/declarations/estimate")
def estimate(data: DeclarationIn, db: Session = Depends(get_db)):
    """Simulation de la remuneration avant envoi (aucune ecriture)."""
    lines, total = [], 0
    for item in data.items:
        mat = db.get(Material, item.material_id)
        t = current_tariff(db, item.material_id) if mat else None
        if t is None:
            continue
        amount = int(round(item.estimated_weight_kg * t.price_fcfa_per_kg))
        total += amount
        lines.append({"material": mat.name, "kg": item.estimated_weight_kg,
                      "price_fcfa_per_kg": t.price_fcfa_per_kg, "amount_fcfa": amount})
    return {"lines": lines, "total_fcfa": total}


class ConvertIn(BaseModel):
    points: int = Field(gt=0, le=1_000_000)


@router.post("/wallet/convert", status_code=201)
def convert(data: ConvertIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pay = convert_points(db, user, data.points)
    db.commit()
    db.refresh(pay)
    return payment_out(pay)


@router.get("/rules")
def rules(db: Session = Depends(get_db)):
    """Regles metier publiques (affichees dans l'appli et utilisees par l'assistant)."""
    return {
        "seuil_y_kg": get_param(db, "SEUIL_Y_KG"),
        "points_par_kg_point_relais": get_param(db, "POINTS_PAR_KG_POINT_RELAIS"),
        "bonus_depot_point_relais": get_param(db, "BONUS_DEPOT_POINT_RELAIS"),
        "points_signalement_confirme": get_param(db, "POINTS_SIGNALEMENT_CONFIRME"),
        "point_valeur_fcfa": get_param(db, "POINT_VALEUR_FCFA"),
        "points_min_conversion": get_param(db, "POINTS_MIN_CONVERSION"),
    }


@router.get("/wallet")
def wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payments = list(db.scalars(select(Payment).where(Payment.user_id == user.id)
                               .order_by(Payment.created_at.desc())))
    points = db.scalars(select(PointsTransaction).where(PointsTransaction.user_id == user.id)
                        .order_by(PointsTransaction.created_at.desc()).limit(50))
    return {
        "points_balance": user.points_balance,
        "point_value_fcfa": get_param(db, "POINT_VALEUR_FCFA"),
        "points_min_conversion": int(get_param(db, "POINTS_MIN_CONVERSION")),
        "total_earned_fcfa": sum(p.amount_fcfa for p in payments if p.status != "ANNULEE"),
        "paid_fcfa": sum(p.amount_fcfa for p in payments if p.status == "PAYEE"),
        "pending_fcfa": sum(p.amount_fcfa for p in payments if p.status == "EN_ATTENTE"),
        "payments": [payment_out(p) for p in payments],
        "points_history": [{"points": t.points, "reason": t.reason, "created_at": iso(t.created_at)}
                           for t in points],
    }
