"""Modele de donnees operationnel (PostgreSQL/PostGIS en production, SQLite en local).

Les memes tables sont repliquees dans Snowflake (schema CORE) pour l'analytique.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Roles et statuts -------------------------------------------------------
ROLES = ("citoyen", "menage", "commercant", "agent", "admin")
REPORT_STATUSES = ("SIGNALE", "CONFIRME", "PLANIFIE", "COLLECTE", "REJETE")
DECLARATION_STATUSES = ("SOUMISE", "PLANIFIEE", "VALIDEE", "REJETEE")
DECLARATION_MODES = ("POINT_RELAIS", "COLLECTE_DOMICILE")
PAYMENT_STATUSES = ("EN_ATTENTE", "PAYEE", "ANNULEE")


class Commune(Base):
    __tablename__ = "communes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="citoyen")
    commune_id: Mapped[int | None] = mapped_column(ForeignKey("communes.id"), nullable=True)
    household_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    commune: Mapped[Commune | None] = relationship()


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recyclable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tariff(Base):
    """Historique des tarifs de rachat. Le tarif en vigueur a valid_to = NULL."""
    __tablename__ = "tariffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    price_fcfa_per_kg: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    material: Mapped[Material] = relationship()


class Parameter(Base):
    """Parametres metier modifiables (bareme de points, couts de collecte...)."""
    __tablename__ = "parameters"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RelayPoint(Base):
    __tablename__ = "relay_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    commune_id: Mapped[int | None] = mapped_column(ForeignKey("communes.id"), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accepted_materials: Mapped[str] = mapped_column(String(255), default="CARTON,PLASTIQUE,ALUMINIUM")
    opening_hours: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capacity_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    commune: Mapped[Commune | None] = relationship()


class Report(Base):
    """Signalement d'un depot sauvage."""
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    commune_id: Mapped[int | None] = mapped_column(ForeignKey("communes.id"), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="SIGNALE", index=True)
    ai_estimated_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()
    commune: Mapped[Commune | None] = relationship()
    photos: Mapped[list["Photo"]] = relationship(back_populates="report")
    analyses: Mapped[list["AIAnalysis"]] = relationship(back_populates="report")


class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True, index=True)
    declaration_id: Mapped[int | None] = mapped_column(ForeignKey("declarations.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    report: Mapped[Report | None] = relationship(back_populates="photos")


class AIAnalysis(Base):
    """Tracabilite complete de chaque analyse IA (fournisseur, modele, reponse brute)."""
    __tablename__ = "ai_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    materials: Mapped[list] = mapped_column(JSON, default=list)
    estimated_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OK")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    report: Mapped[Report | None] = relationship(back_populates="analyses")


class Declaration(Base):
    """Declaration de dechets recyclables par un menage ou un commercant."""
    __tablename__ = "declarations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="POINT_RELAIS")
    relay_point_id: Mapped[int | None] = mapped_column(ForeignKey("relay_points.id"), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="SOUMISE", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_estimated_kg: Mapped[float] = mapped_column(Float, default=0)
    total_validated_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_amount_fcfa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    validated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    relay_point: Mapped[RelayPoint | None] = relationship()
    items: Mapped[list["DeclarationItem"]] = relationship(
        back_populates="declaration", cascade="all, delete-orphan"
    )


class DeclarationItem(Base):
    """Ligne de declaration : poids estime par l'usager puis poids reellement valide."""
    __tablename__ = "declaration_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    declaration_id: Mapped[int] = mapped_column(ForeignKey("declarations.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    estimated_weight_kg: Mapped[float] = mapped_column(Float)
    validated_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    tariff_id: Mapped[int | None] = mapped_column(ForeignKey("tariffs.id"), nullable=True)
    unit_price_fcfa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_fcfa: Mapped[int | None] = mapped_column(Integer, nullable=True)

    declaration: Mapped[Declaration] = relationship(back_populates="items")
    material: Mapped[Material] = relationship()


class Payment(Base):
    """Remuneration due a un usager apres validation d'une declaration."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    declaration_id: Mapped[int] = mapped_column(ForeignKey("declarations.id"), unique=True)
    amount_fcfa: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="EN_ATTENTE")
    method: Mapped[str] = mapped_column(String(30), default="MOBILE_MONEY")
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()


class PointsTransaction(Base):
    __tablename__ = "points_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))
    declaration_id: Mapped[int | None] = mapped_column(ForeignKey("declarations.id"), nullable=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Collection(Base):
    """Tournee de collecte avec itineraire optimise."""
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    planned_date: Mapped[date] = mapped_column(Date)
    depot_label: Mapped[str] = mapped_column(String(120))
    depot_latitude: Mapped[float] = mapped_column(Float)
    depot_longitude: Mapped[float] = mapped_column(Float)
    vehicle_type: Mapped[str] = mapped_column(String(40), default="TRICYCLE")
    status: Mapped[str] = mapped_column(String(20), default="PLANIFIEE")
    total_distance_km: Mapped[float] = mapped_column(Float, default=0)
    estimated_duration_min: Mapped[float] = mapped_column(Float, default=0)
    estimated_cost_fcfa: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    stops: Mapped[list["CollectionStop"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan",
        order_by="CollectionStop.sequence",
    )
    costs: Mapped[list["CollectionCost"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class CollectionStop(Base):
    __tablename__ = "collection_stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    stop_type: Mapped[str] = mapped_column(String(20))  # SIGNALEMENT | DECLARATION
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    declaration_id: Mapped[int | None] = mapped_column(ForeignKey("declarations.id"), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    distance_from_previous_km: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="A_FAIRE")
    collected_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    collection: Mapped[Collection] = relationship(back_populates="stops")


class ChatMessage(Base):
    """Historique des conversations avec l'assistant (tracabilite et analyse des besoins)."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CollectionCost(Base):
    __tablename__ = "collection_costs"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    cost_type: Mapped[str] = mapped_column(String(30))  # CARBURANT | MAIN_OEUVRE | VEHICULE | AUTRE
    amount_fcfa: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    collection: Mapped[Collection] = relationship(back_populates="costs")
