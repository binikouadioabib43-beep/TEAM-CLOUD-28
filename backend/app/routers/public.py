"""Authentification et referentiels publics."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Commune, Material, RelayPoint, User
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, get_current_user, hash_password, verify_password
from ..serializers import relay_out, user_out
from ..services.business import current_tariff
from ..services.routing import haversine_km

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "ai_provider": settings.ai_provider,
            "snowflake_configured": settings.snowflake_configured}


@router.post("/auth/register", status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(409, "Un compte existe deja avec cet e-mail")
    if data.role == "commercant" and not data.business_name:
        raise HTTPException(400, "Le nom du commerce est obligatoire")
    if data.commune_id is not None and db.get(Commune, data.commune_id) is None:
        raise HTTPException(400, "Commune inconnue")
    user = User(**data.model_dump(exclude={"password"}), password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user), "user": user_out(user)}


@router.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "E-mail ou mot de passe incorrect")
    if not user.is_active:
        raise HTTPException(403, "Compte desactive")
    return {"token": create_token(user), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.get("/communes")
def communes(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "latitude": c.latitude, "longitude": c.longitude}
            for c in db.scalars(select(Commune).order_by(Commune.name))]


@router.get("/materials")
def materials(db: Session = Depends(get_db)):
    out = []
    for m in db.scalars(select(Material).where(Material.is_active).order_by(Material.id)):
        t = current_tariff(db, m.id)
        out.append({"id": m.id, "code": m.code, "name": m.name, "description": m.description,
                    "is_recyclable": m.is_recyclable,
                    "price_fcfa_per_kg": t.price_fcfa_per_kg if t else None})
    return out


@router.get("/relay-points")
def relay_points(lat: float | None = None, lon: float | None = None, db: Session = Depends(get_db)):
    points = [relay_out(p) for p in db.scalars(select(RelayPoint).where(RelayPoint.is_active))]
    if lat is not None and lon is not None:
        for p in points:
            p["distance_km"] = round(haversine_km((lat, lon), (p["latitude"], p["longitude"])), 2)
        points.sort(key=lambda p: p["distance_km"])
    return points
