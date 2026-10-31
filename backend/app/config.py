"""Configuration de l'application, lue depuis les variables d'environnement ou le fichier .env."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_env_file() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "oui"}


class Settings:
    def __init__(self) -> None:
        self.app_name = "EcoAbidjan"
        data_dir = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.database_url = os.getenv(
            "DATABASE_URL", f"sqlite:///{(data_dir / 'ecoabidjan.db').as_posix()}"
        )
        # A remplacer en production (au moins 32 caracteres aleatoires)
        self.secret_key = os.getenv("SECRET_KEY", "dev-secret-ecoabidjan-a-remplacer-en-production")
        self.token_hours = int(os.getenv("TOKEN_HOURS", "24"))
        self.seed_demo = _bool("SEED_DEMO", True)
        self.upload_dir = Path(os.getenv("UPLOAD_DIR", data_dir / "uploads"))
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "8"))

        self.ai_provider = os.getenv("AI_PROVIDER", "local").lower()
        self.cortex_model = os.getenv("CORTEX_VISION_MODEL", "claude-3-5-sonnet")
        self.cortex_stage = os.getenv("CORTEX_IMAGE_STAGE", "@ECOABIDJAN.RAW.PHOTOS_STAGE")

        self.snowflake = {
            key: os.getenv(f"SNOWFLAKE_{key.upper()}") or None
            for key in (
                "account", "user", "password", "private_key_file",
                "role", "warehouse", "database", "schema",
            )
        }
        self.frontend_dir = BASE_DIR / "frontend"

    @property
    def snowflake_configured(self) -> bool:
        sf = self.snowflake
        return bool(sf["account"] and sf["user"] and (sf["password"] or sf["private_key_file"]))


settings = Settings()
