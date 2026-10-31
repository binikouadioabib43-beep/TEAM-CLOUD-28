"""Relance complete de la simulation du projet pilote.

Usage :  python -m backend.app.simulate
Efface la base locale (SQLite ou PostgreSQL configuree), recree les tables et genere
4 communes pilotes, 500 menages, 200 commercants, 150 citoyens et 90 jours d'activite.
"""
import time

from sqlalchemy import func, select

from . import models  # noqa: F401
from .database import Base, SessionLocal, engine
from .models import Collection, Declaration, Payment, PointsTransaction, Report, User
from .seed import seed_reference, simulate_pilot


def main() -> None:
    started = time.perf_counter()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_reference(db)
        stats = simulate_pilot(db)
        count = lambda m, *w: db.scalar(select(func.count(m.id)).where(*w))  # noqa: E731
        print("Simulation du projet pilote terminee en", round(time.perf_counter() - started, 1), "s")
        print(f"  Menages      : {count(User, User.role == 'menage')}")
        print(f"  Commercants  : {count(User, User.role == 'commercant')}")
        print(f"  Citoyens     : {count(User, User.role == 'citoyen')}")
        print(f"  Declarations : {count(Declaration)} (dont {stats['domicile_refusees_seuil_y']} orientees vers un point relais par le seuil Y)")
        print(f"  Signalements : {count(Report)}")
        print(f"  Tournees     : {count(Collection)}")
        print(f"  Paiements    : {count(Payment)}")
        print(f"  Mouvements de points : {count(PointsTransaction)}")


if __name__ == "__main__":
    main()
