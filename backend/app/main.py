"""Point d'entree FastAPI. Lancer avec : uvicorn backend.app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from . import models  # noqa: F401  (enregistre les tables)
from .routers import admin, assistant, citizen, public
from .seed import run_seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        run_seed(db)
    yield


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
