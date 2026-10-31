"""Schemas d'entree (validation des donnees envoyees par le client)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=160)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=30)
    role: Literal["citoyen", "menage", "commercant"] = "citoyen"
    commune_id: int | None = None
    household_size: int | None = Field(default=None, ge=1, le=50)
    business_name: str | None = Field(default=None, max_length=120)
    business_type: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Adresse e-mail invalide")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class DeclarationItemIn(BaseModel):
    material_id: int
    estimated_weight_kg: float = Field(gt=0, le=1000)


class DeclarationIn(BaseModel):
    mode: Literal["POINT_RELAIS", "COLLECTE_DOMICILE"]
    relay_point_id: int | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    note: str | None = Field(default=None, max_length=500)
    items: list[DeclarationItemIn] = Field(min_length=1, max_length=10)


class ValidationItemIn(BaseModel):
    item_id: int
    validated_weight_kg: float = Field(ge=0, le=1000)


class ValidationIn(BaseModel):
    items: list[ValidationItemIn]


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class ReportStatusIn(BaseModel):
    status: Literal["CONFIRME", "REJETE", "COLLECTE"]
    validated_weight_kg: float | None = Field(default=None, ge=0, le=100000)


class TariffIn(BaseModel):
    price_fcfa_per_kg: int = Field(gt=0, le=100000)
    note: str | None = Field(default=None, max_length=255)


class MaterialIn(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z_]+$")
    name: str = Field(min_length=2, max_length=80)
    price_fcfa_per_kg: int = Field(gt=0, le=100000)


class ParameterIn(BaseModel):
    value: str = Field(min_length=1, max_length=255)


class RelayPointIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    commune_id: int | None = None
    address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accepted_materials: str = "CARTON,PLASTIQUE,ALUMINIUM"
    opening_hours: str | None = None
    capacity_kg: float | None = None


class CollectionPlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    planned_date: date
    depot_relay_point_id: int | None = None
    depot_latitude: float | None = None
    depot_longitude: float | None = None
    vehicle_type: str = "TRICYCLE"
    report_ids: list[int] = []
    declaration_ids: list[int] = []


class CollectionCostIn(BaseModel):
    cost_type: Literal["CARBURANT", "MAIN_OEUVRE", "VEHICULE", "AUTRE"]
    amount_fcfa: int = Field(gt=0)
    note: str | None = None


class StopUpdateIn(BaseModel):
    status: Literal["A_FAIRE", "FAIT", "IMPOSSIBLE"]
    collected_weight_kg: float | None = Field(default=None, ge=0)


class PaymentUpdateIn(BaseModel):
    status: Literal["PAYEE", "ANNULEE"]
    reference: str | None = Field(default=None, max_length=80)
    method: Literal["MOBILE_MONEY", "ESPECES", "VIREMENT"] = "MOBILE_MONEY"
