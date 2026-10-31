import os
import sys
import tempfile
from pathlib import Path

import pytest

# Base de test isolee, creee avant l'import de l'application
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ecoabidjan_test_")
os.environ.pop("DATABASE_URL", None)
os.environ["AI_PROVIDER"] = "local"
os.environ["SEED_DEMO"] = "true"
# Ignore la configuration Snowflake du fichier .env local pendant les tests
for _key in ("ACCOUNT", "USER", "PASSWORD", "PRIVATE_KEY_FILE", "AUTHENTICATOR"):
    os.environ[f"SNOWFLAKE_{_key}"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

DEMO_PASSWORD = "Demo@2026"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password=DEMO_PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin@ecoabidjan.ci")


@pytest.fixture(scope="session")
def agent(client):
    return login(client, "agent@ecoabidjan.ci")
