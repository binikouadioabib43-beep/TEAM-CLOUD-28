"""Acces Snowflake : connexion, diagnostic de l'environnement et synchronisation analytique."""
import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from .. import models


class SnowflakeNotConfigured(RuntimeError):
    pass


def connect():
    if not settings.snowflake_configured:
        raise SnowflakeNotConfigured(
            "Snowflake n'est pas configure (SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER et mot de passe ou cle)."
        )
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SnowflakeNotConfigured(
            "Paquet manquant : pip install -r requirements-optional.txt"
        ) from exc
    sf = settings.snowflake
    kwargs = {k: sf[k] for k in ("account", "user", "role", "warehouse", "database", "schema") if sf[k]}
    if sf["private_key_file"]:
        kwargs["private_key_file"] = sf["private_key_file"]
    else:
        kwargs["password"] = sf["password"]
    kwargs["application"] = "EcoAbidjan"
    return snowflake.connector.connect(**kwargs)


def run_diagnostics() -> list[dict]:
    """Verifie reellement ce qui est disponible dans le compte, sans rien supposer."""
    checks: list[dict] = []
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        return [{"check": "Connexion", "ok": False, "detail": str(exc)}]

    def probe(label: str, sql: str, params: tuple = ()):
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            checks.append({"check": label, "ok": True, "detail": str(row[0] if row else "")[:300]})
        except Exception as exc:  # noqa: BLE001
            checks.append({"check": label, "ok": False, "detail": str(exc)[:300]})

    try:
        checks.append({"check": "Connexion", "ok": True, "detail": "OK"})
        probe("Version Snowflake", "SELECT CURRENT_VERSION()")
        probe("Region du compte", "SELECT CURRENT_REGION()")
        probe("Role courant", "SELECT CURRENT_ROLE()")
        probe("Entrepot courant", "SELECT CURRENT_WAREHOUSE()")
        probe("Base / schema", "SELECT CURRENT_DATABASE() || '.' || CURRENT_SCHEMA()")
        probe("Cortex AI_COMPLETE (texte)",
              "SELECT AI_COMPLETE(%s, 'Reponds uniquement par le mot OK')", (settings.cortex_model,))
        probe("Parametre CORTEX_ENABLED_CROSS_REGION",
              "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT")
        stage = settings.cortex_stage.lstrip("@")
        probe("Stage photos (" + stage + ")", f"DESC STAGE {stage}")
        probe("Table CORE.REPORTS", "SELECT COUNT(*) FROM CORE.REPORTS")
    finally:
        conn.close()
    return checks


# Ordre de chargement : respecte les dependances logiques entre tables.
SYNC_MODELS = [
    models.Commune, models.User, models.Material, models.Tariff, models.Parameter,
    models.RelayPoint, models.Collection, models.Report, models.Declaration, models.Photo,
    models.AIAnalysis, models.DeclarationItem, models.Payment, models.PointsTransaction,
    models.CollectionStop, models.CollectionCost,
]
# Colonnes jamais envoyees vers l'entrepot analytique.
EXCLUDED_COLUMNS = {"users": {"password_hash", "email", "phone"}}


def _value(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


def sync_to_snowflake(db: Session) -> dict:
    """Recharge integralement les tables CORE de Snowflake depuis la base operationnelle.

    Adapte aux volumes d'un MVP ; au-dela, passer a un chargement incremental
    (colonnes updated_at + MERGE) ou a Snowpipe.
    """
    conn = connect()
    summary = {}
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for model in SYNC_MODELS:
            table = model.__tablename__
            excluded = EXCLUDED_COLUMNS.get(table, set())
            cols = [c.name for c in model.__table__.columns if c.name not in excluded]
            rows = db.execute(select(*[model.__table__.c[c] for c in cols])).all()
            target = f"CORE.{table.upper()}"
            cur.execute(f"DELETE FROM {target}")
            if rows:
                placeholders = ", ".join(["%s"] * len(cols))
                cur.executemany(
                    f"INSERT INTO {target} ({', '.join(c.upper() for c in cols)}) VALUES ({placeholders})",
                    [tuple(_value(v) for v in r) for r in rows],
                )
            summary[table] = len(rows)
        cur.execute("COMMIT")
    except Exception:
        conn.cursor().execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return summary
