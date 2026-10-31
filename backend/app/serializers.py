"""Conversion des objets en dictionnaires JSON renvoyes par l'API."""
from .models import (
    AIAnalysis, Collection, Declaration, Payment, RelayPoint, Report, Tariff, User,
)


def iso(dt):
    return dt.isoformat() if dt else None


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name, "phone": u.phone,
        "role": u.role, "commune_id": u.commune_id,
        "commune": u.commune.name if u.commune else None,
        "household_size": u.household_size, "business_name": u.business_name,
        "business_type": u.business_type, "points_balance": u.points_balance,
        "created_at": iso(u.created_at),
    }


def analysis_out(a: AIAnalysis) -> dict:
    return {
        "id": a.id, "photo_id": a.photo_id, "provider": a.provider, "model": a.model,
        "prompt_version": a.prompt_version, "materials": a.materials,
        "estimated_weight_kg": a.estimated_weight_kg, "estimated_volume_m3": a.estimated_volume_m3,
        "confidence": a.confidence, "summary": a.summary, "status": a.status, "error": a.error,
        "duration_ms": a.duration_ms, "created_at": iso(a.created_at),
    }


def report_out(r: Report) -> dict:
    return {
        "id": r.id, "user_id": r.user_id, "reporter": r.user.full_name if r.user else None,
        "commune_id": r.commune_id, "commune": r.commune.name if r.commune else None,
        "latitude": r.latitude, "longitude": r.longitude, "address": r.address,
        "description": r.description, "status": r.status,
        "ai_estimated_weight_kg": r.ai_estimated_weight_kg,
        "validated_weight_kg": r.validated_weight_kg, "points_awarded": r.points_awarded,
        "collection_id": r.collection_id,
        "photos": [f"/api/photos/{p.id}" for p in r.photos],
        "analysis": analysis_out(r.analyses[-1]) if r.analyses else None,
        "created_at": iso(r.created_at),
    }


def declaration_out(d: Declaration) -> dict:
    return {
        "id": d.id, "user_id": d.user_id, "user": d.user.full_name if d.user else None,
        "user_role": d.user.role if d.user else None,
        "mode": d.mode, "relay_point_id": d.relay_point_id,
        "relay_point": d.relay_point.name if d.relay_point else None,
        "latitude": d.latitude, "longitude": d.longitude, "status": d.status, "note": d.note,
        "total_estimated_kg": d.total_estimated_kg, "total_validated_kg": d.total_validated_kg,
        "total_amount_fcfa": d.total_amount_fcfa, "points_awarded": d.points_awarded,
        "rejection_reason": d.rejection_reason, "validated_at": iso(d.validated_at),
        "collection_id": d.collection_id, "created_at": iso(d.created_at),
        "items": [
            {
                "id": i.id, "material_id": i.material_id, "material": i.material.name,
                "material_code": i.material.code, "estimated_weight_kg": i.estimated_weight_kg,
                "validated_weight_kg": i.validated_weight_kg, "unit_price_fcfa": i.unit_price_fcfa,
                "amount_fcfa": i.amount_fcfa,
            }
            for i in d.items
        ],
    }


def tariff_out(t: Tariff) -> dict:
    return {
        "id": t.id, "material_id": t.material_id, "material": t.material.name,
        "material_code": t.material.code, "price_fcfa_per_kg": t.price_fcfa_per_kg,
        "valid_from": iso(t.valid_from), "valid_to": iso(t.valid_to), "note": t.note,
    }


def relay_out(p: RelayPoint) -> dict:
    return {
        "id": p.id, "name": p.name, "commune_id": p.commune_id,
        "commune": p.commune.name if p.commune else None, "address": p.address,
        "latitude": p.latitude, "longitude": p.longitude,
        "accepted_materials": p.accepted_materials.split(","),
        "opening_hours": p.opening_hours, "capacity_kg": p.capacity_kg, "is_active": p.is_active,
    }


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id, "user_id": p.user_id, "user": p.user.full_name if p.user else None,
        "kind": p.kind, "points_converted": p.points_converted,
        "declaration_id": p.declaration_id, "amount_fcfa": p.amount_fcfa, "status": p.status,
        "method": p.method, "reference": p.reference,
        "created_at": iso(p.created_at), "paid_at": iso(p.paid_at),
    }


def collection_out(c: Collection) -> dict:
    real_cost = sum(x.amount_fcfa for x in c.costs)
    return {
        "id": c.id, "name": c.name, "planned_date": c.planned_date.isoformat(),
        "depot_label": c.depot_label, "depot_latitude": c.depot_latitude,
        "depot_longitude": c.depot_longitude, "vehicle_type": c.vehicle_type, "status": c.status,
        "total_distance_km": c.total_distance_km, "estimated_duration_min": c.estimated_duration_min,
        "estimated_cost_fcfa": c.estimated_cost_fcfa, "real_cost_fcfa": real_cost,
        "collected_kg": round(sum(s.collected_weight_kg or 0 for s in c.stops), 1),
        "stops": [
            {
                "id": s.id, "sequence": s.sequence, "stop_type": s.stop_type,
                "report_id": s.report_id, "declaration_id": s.declaration_id,
                "latitude": s.latitude, "longitude": s.longitude,
                "distance_from_previous_km": s.distance_from_previous_km,
                "status": s.status, "collected_weight_kg": s.collected_weight_kg,
            }
            for s in c.stops
        ],
        "costs": [
            {"id": x.id, "cost_type": x.cost_type, "amount_fcfa": x.amount_fcfa, "note": x.note}
            for x in c.costs
        ],
    }
