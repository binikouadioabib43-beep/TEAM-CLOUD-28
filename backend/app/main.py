"""Point d'entree FastAPI. Lancer avec : uvicorn backend.app.main:app --reload"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from . import models  # noqa: F401  (enregistre les tables)
from .routers import admin, assistant, citizen, public
from .seed import run_seed


log = logging.getLogger("ecoabidjan")


def _sync_once() -> None:
    from .services.snowflake_client import sync_to_snowflake
    with SessionLocal() as db:
        summary = sync_to_snowflake(db)
    log.info("Synchronisation Snowflake : %s lignes", sum(summary.values()))


async def snowflake_sync_loop() -> None:
    """Copie periodique des donnees vers Snowflake (si un compte est configure dans .env)."""
    while True:
        try:
            await asyncio.to_thread(_sync_once)
        except Exception as exc:  # noqa: BLE001 - l'application continue sans Snowflake
            log.warning("Synchronisation Snowflake impossible : %s", exc)
        await asyncio.sleep(settings.snowflake_sync_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        run_seed(db)
    task = None
    if settings.snowflake_configured and settings.snowflake_sync_minutes > 0:
        task = asyncio.create_task(snowflake_sync_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="EcoAbidjan API", version="1.0.0", lifespan=lifespan)
app.include_router(public.router)
app.include_router(citizen.router)
app.include_router(admin.router)
app.include_router(assistant.router)

if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(settings.frontend_dir / "index.html")
