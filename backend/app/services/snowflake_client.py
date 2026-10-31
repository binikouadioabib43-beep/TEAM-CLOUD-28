"""Acces Snowflake : connexion, diagnostic de l'environnement et synchronisation analytique."""
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from .. import models


class SnowflakeNotConfigured(RuntimeError):
    pass


KEY_FILE = settings.data_dir / "snowflake_rsa_key.p8"
_shared_conn = None
last_sync: dict = {"at": None, "ok": None, "detail": None}


def ensure_keypair() -> str:
    """Cree (une seule fois) la cle privee RSA dans data/ et renvoie la cle publique a declarer dans Snowflake."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if not KEY_FILE.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_FILE.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return "".join(l for l in pem.splitlines() if "PUBLIC KEY" not in l)


class _SharedConnection:
    """Session ouverte une seule fois en mode navigateur : close() ne la ferme pas."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def reset_connection() -> None:
    global _shared_conn
    if _shared_conn is not None:
        try:
            _shared_conn.close()
        except Exception:  # noqa: BLE001
            pass
    _shared_conn = None


def connect():
    global _shared_conn
    if settings.snowflake["authenticator"] == "externalbrowser" and _shared_conn is not None \
            and not _shared_conn.is_closed():
        return _SharedConnection(_shared_conn)
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
    if sf["authenticator"] == "externalbrowser":
        # Ouvre la page de connexion Snowflake dans le navigateur ; le jeton est garde en cache
        # par le systeme (si le compte l'autorise) pour ne pas redemander a chaque requete.
        kwargs["authenticator"] = "externalbrowser"
        kwargs["client_store_temporary_credential"] = True
    elif sf["private_key_file"]:
        kwargs["private_key_file"] = sf["private_key_file"]
    else:
        kwargs["password"] = sf["password"]
    kwargs["application"] = "EcoAbidjan"
    if sf["authenticator"] == "externalbrowser":
        kwargs["client_session_keep_alive"] = True
        _shared_conn = snowflake.connector.connect(**kwargs)
        return _SharedConnection(_shared_conn)
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
    models.CollectionStop, models.CollectionCost, models.ChatMessage,
]
# Colonnes jamais envoyees vers l'entrepot analytique.
EXCLUDED_COLUMNS = {"users": {"password_hash", "email", "phone"}}


SETUP_SCRIPTS = ("01_setup.sql", "02_tables.sql", "04_analytics_views.sql", "06_simulation_generator.sql")


def run_setup_scripts() -> dict:
    """Execute les scripts d'installation avec le role de la connexion (USE ROLE retire).

    Chaque instruction est executee separement : une erreur (ex. droit manquant) est
    notee sans bloquer la suite. Renvoie le bilan et la synthese de la simulation.
    """
    from snowflake.connector.util_text import split_statements
    import io
    import re as _re

    from ..config import BASE_DIR

    conn = connect()
    report = {"scripts": [], "synthese": [], "controles": []}
    try:
        cur = conn.cursor()
        role = cur.execute("SELECT CURRENT_ROLE()").fetchone()[0]
        for name in SETUP_SCRIPTS:
            sql = (BASE_DIR / "snowflake" / name).read_text(encoding="utf-8")
            sql = _re.sub(r"(?im)^\s*USE ROLE [^;]+;", "", sql)
            ok, errors = 0, []
            for stmt, _ in split_statements(io.StringIO(sql), remove_comments=True):
                if not stmt.strip():
                    continue
                try:
                    cur.execute(stmt)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{stmt.strip()[:70]}… → {str(exc).splitlines()[0][:200]}")
            report["scripts"].append({"script": name, "ok": ok, "erreurs": errors})
        cur.execute("USE SCHEMA ECOABIDJAN.SIM")
        cols = None
        for row in cur.execute("SELECT * FROM V_SYNTHESE_COMMUNE ORDER BY MENAGES DESC"):
            cols = cols or [c[0] for c in cur.description]
            report["synthese"].append(dict(zip(cols, [float(v) if isinstance(v, Decimal) else v for v in row])))
        for row in cur.execute(
                "SELECT 'Communes pilotes', COUNT(*) FROM COMMUNES_PILOTES UNION ALL "
                "SELECT 'Menages', COUNT(*) FROM MENAGES UNION ALL SELECT 'Commercants', COUNT(*) FROM COMMERCANTS"):
            report["controles"].append({"controle": row[0], "valeur": row[1]})
        report["role"] = role
    finally:
        conn.close()
    return report


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
    except Exception as exc:
        conn.cursor().execute("ROLLBACK")
        last_sync.update(at=datetime.now().isoformat(timespec="seconds"), ok=False, detail=str(exc)[:300])
        raise
    finally:
        conn.close()
    last_sync.update(at=datetime.now().isoformat(timespec="seconds"), ok=True,
                     detail=f"{sum(summary.values())} lignes")
    return summary
