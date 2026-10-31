"""Analyse des photos de depots sauvages.

Deux fournisseurs :
- "snowflake" : Snowflake Cortex AI, fonction AI_COMPLETE avec une image deposee sur un stage
  (TO_FILE). Necessite un modele multimodal disponible dans la region du compte.
- "local"     : estimation heuristique hors ligne par analyse des couleurs (mode demo).

Les resultats sont TOUJOURS indicatifs : le poids reel est valide par un agent.
"""
import json
import re
import time
from pathlib import Path

from PIL import Image

from ..config import settings

PROMPT_VERSION = "v1"
KNOWN_MATERIALS = ("PLASTIQUE", "CARTON", "ALUMINIUM", "VERRE", "ORGANIQUE", "TEXTILE", "AUTRE")
# Densites apparentes indicatives (kg/m3) de dechets en vrac.
BULK_DENSITY = {
    "PLASTIQUE": 35, "CARTON": 60, "ALUMINIUM": 45, "VERRE": 300,
    "ORGANIQUE": 450, "TEXTILE": 120, "AUTRE": 180,
}

VISION_PROMPT = """Tu es un expert en gestion des dechets a Abidjan. Analyse cette photo d'un depot sauvage.
Identifie les matieres visibles et estime le volume et le poids du tas. Reponds UNIQUEMENT par un JSON valide :
{"materiaux":[{"code":"PLASTIQUE|CARTON|ALUMINIUM|VERRE|ORGANIQUE|TEXTILE|AUTRE","part":0.0,"confiance":0.0}],
 "volume_m3":0.0,"poids_kg":0.0,"confiance":0.0,"resume":"une phrase en francais"}
Les parts doivent faire 1 au total. Si la photo ne montre pas de dechets, renvoie materiaux vide et poids_kg 0."""


def _normalize(result: dict) -> dict:
    mats = []
    for m in result.get("materiaux") or []:
        code = str(m.get("code", "AUTRE")).upper()
        code = code if code in KNOWN_MATERIALS else "AUTRE"
        mats.append({
            "code": code,
            "share": round(max(0.0, min(1.0, float(m.get("part", 0)))), 3),
            "confidence": round(max(0.0, min(1.0, float(m.get("confiance", 0)))), 3),
        })
    total = sum(m["share"] for m in mats)
    if total > 0:
        for m in mats:
            m["share"] = round(m["share"] / total, 3)
    mats.sort(key=lambda m: m["share"], reverse=True)
    return {
        "materials": mats,
        "estimated_volume_m3": round(float(result.get("volume_m3") or 0), 3),
        "estimated_weight_kg": round(float(result.get("poids_kg") or 0), 1),
        "confidence": round(float(result.get("confiance") or 0), 3),
        "summary": result.get("resume"),
    }


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith('"'):
        text = json.loads(text)  # AI_COMPLETE peut renvoyer une chaine JSON echappee
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Aucun JSON dans la reponse du modele")
    return json.loads(match.group(0))


# --- Fournisseur local -------------------------------------------------------

def analyze_local(path: Path) -> dict:
    img = Image.open(path).convert("RGB")
    img.thumbnail((160, 160))
    hsv = img.convert("HSV")
    counts = dict.fromkeys(KNOWN_MATERIALS, 0)
    background = 0
    for h, s, v in hsv.getdata():
        if v < 35:
            background += 1  # ombres
        elif 12 <= h <= 32 and 60 <= s <= 210 and 60 <= v <= 225:
            counts["CARTON"] += 1
        elif s < 35 and 110 <= v <= 205:
            counts["ALUMINIUM"] += 1
        elif s < 35 and v > 205:
            counts["PLASTIQUE"] += 1  # sachets et bouteilles clairs
        elif 40 <= h <= 115 and s >= 50 and v < 170:
            counts["ORGANIQUE"] += 1  # vegetation, restes alimentaires
        elif 125 <= h <= 175 and s < 140 and v > 150:
            background += 1  # ciel
        elif s >= 110:
            counts["PLASTIQUE"] += 1  # plastiques colores
        else:
            counts["AUTRE"] += 1
    total_px = sum(counts.values()) + background
    waste_px = sum(counts.values())
    coverage = waste_px / total_px if total_px else 0
    volume = round(0.2 + coverage * 2.3, 2)  # tas photographie : 0,2 a 2,5 m3
    shares = {k: c / waste_px for k, c in counts.items() if waste_px and c / waste_px >= 0.03}
    weight = sum(volume * share * BULK_DENSITY[k] for k, share in shares.items())
    raw = {
        "materiaux": [{"code": k, "part": v, "confiance": 0.35} for k, v in shares.items()],
        "volume_m3": volume,
        "poids_kg": round(weight, 1),
        "confiance": 0.3,
        "resume": "Estimation heuristique hors ligne (couleurs dominantes). A confirmer sur le terrain.",
    }
    return {"provider": "local", "model": "heuristique-couleurs-v1",
            "raw_response": json.dumps(raw, ensure_ascii=False), **_normalize(raw)}


# --- Fournisseur Snowflake Cortex --------------------------------------------

def analyze_snowflake(path: Path) -> dict:
    from .snowflake_client import connect

    stage = settings.cortex_stage if settings.cortex_stage.startswith("@") else "@" + settings.cortex_stage
    relative = f"reports/{path.name}"
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"PUT 'file://{path.resolve().as_posix()}' {stage}/reports/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        try:
            cur.execute(f"ALTER STAGE {stage.lstrip('@')} REFRESH")
        except Exception:  # noqa: BLE001 - table de repertoire optionnelle
            pass
        cur.execute(
            "SELECT AI_COMPLETE(%s, %s, TO_FILE(%s, %s))",
            (settings.cortex_model, VISION_PROMPT, stage, relative),
        )
        text = cur.fetchone()[0]
    finally:
        conn.close()
    return {"provider": "snowflake-cortex", "model": settings.cortex_model,
            "raw_response": text, **_normalize(_extract_json(text))}


def analyze_photo(path: Path) -> dict:
    """Analyse une photo ; en cas d'echec de Cortex, repli sur l'heuristique locale (trace dans `error`)."""
    started = time.perf_counter()
    error = None
    if settings.ai_provider == "snowflake":
        try:
            result = analyze_snowflake(path)
        except Exception as exc:  # noqa: BLE001
            error = f"Cortex indisponible, repli local : {exc}"[:1000]
            result = analyze_local(path)
    else:
        result = analyze_local(path)
    result["error"] = error
    result["status"] = "OK" if error is None else "REPLI"
    result["prompt_version"] = PROMPT_VERSION
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    return result
