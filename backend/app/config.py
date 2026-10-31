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
        # Assistant : auto = Cortex si Snowflake est connecte, sinon moteur local
        self.assistant_provider = os.getenv("ASSISTANT_PROVIDER", "auto").lower()
        self.cortex_chat_model = os.getenv("CORTEX_CHAT_MODEL", "claude-3-5-sonnet")

        self.snowflake = {
            key: os.getenv(f"SNOWFLAKE_{key.upper()}") or None
            for key in SNOWFLAKE_KEYS
        }
        # externalbrowser = connexion via la page Snowflake du navigateur (SSO), sans mot de passe stocke
        self.snowflake["authenticator"] = (self.snowflake["authenticator"] or "").lower() or None
        self.frontend_dir = BASE_DIR / "frontend"

    @property
    def snowflake_configured(self) -> bool:
        sf = self.snowflake
        return bool(sf["account"] and sf["user"] and (
            sf["password"] or sf["private_key_file"] or sf["authenticator"] == "externalbrowser"))

    def update_snowflake(self, values: dict) -> None:
        """Met a jour la configuration Snowflake en memoire et dans le fichier .env."""
        for key, value in values.items():
            self.snowflake[key] = value or None
        save_env({f"SNOWFLAKE_{k.upper()}": (v or "") for k, v in values.items()})


SNOWFLAKE_KEYS = (
    "account", "user", "password", "private_key_file", "authenticator",
    "role", "warehouse", "database", "schema",
)


def save_env(updates: dict) -> None:
    """Ecrit ou remplace des cles dans .env en conservant le reste du fichier."""
    env_file = BASE_DIR / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and key in updates:
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        os.environ[k] = v


settings = Settings()
