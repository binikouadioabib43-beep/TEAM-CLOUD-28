"""Assistant conversationnel : accessible a tous (visiteurs et connectes)."""
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import ChatMessage, User, utcnow
from ..security import require_roles
from ..serializers import iso
from ..services.assistant import answer, suggestions_for

router = APIRouter(prefix="/api")
_bearer = HTTPBearer(auto_error=False)


def optional_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                  db: Session = Depends(get_db)) -> User | None:
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = db.get(User, int(payload["sub"]))
    return user if user and user.is_active else None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


@router.post("/assistant/chat")
def chat(data: ChatIn, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return answer(db, question=data.message.strip(), session_id=data.session_id, user=user,
                  lat=data.latitude, lon=data.longitude)


@router.get("/assistant/welcome")
def welcome(user: User | None = Depends(optional_user)):
    name = user.full_name.split(" ")[0] if user else None
    hello = f"Bonjour {name} 👋" if name else "Bonjour 👋"
    if user and user.role in ("agent", "admin"):
        text = f"{hello} Je suis **Eco**, ton assistant. Demande-moi un resume de la situation ou ce qui reste a traiter."
    else:
        text = (f"{hello} Je suis **Eco**, l'assistant d'EcoAbidjan. Pose-moi ta question, par ecrit ou a la voix 🎤 : "
                "tarifs, points relais, gains, signalements, conseils de tri…")
    provider = "snowflake-cortex" if settings.snowflake_configured and settings.assistant_provider != "local" else "local"
    return {"reply": text, "suggestions": suggestions_for(user, ""), "provider": provider}


@router.get("/assistant/history")
def history(session_id: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    stmt = select(ChatMessage).where(ChatMessage.session_id == session_id)
    stmt = stmt.where(ChatMessage.user_id == user.id) if user else stmt.where(ChatMessage.user_id.is_(None))
    rows = db.scalars(stmt.order_by(ChatMessage.id.desc()).limit(30))
    return [{"role": m.role, "content": m.content, "created_at": iso(m.created_at)} for m in reversed(list(rows))]


@router.get("/admin/assistant/stats")
def stats(_: User = Depends(require_roles("agent", "admin")), db: Session = Depends(get_db)):
    """Ce que les usagers demandent : utile pour ameliorer le service."""
    since = utcnow() - timedelta(days=30)
    base = select(ChatMessage).where(ChatMessage.role == "user", ChatMessage.created_at >= since).subquery()
    intents = db.execute(select(base.c.intent, func.count()).group_by(base.c.intent)
                         .order_by(func.count().desc())).all()
    providers = db.execute(select(ChatMessage.provider, func.count(), func.avg(ChatMessage.latency_ms))
                           .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
                           .group_by(ChatMessage.provider)).all()
    return {
        "questions_30j": sum(n for _, n in intents),
        "par_intention": [{"intention": i or "inconnu", "nombre": n} for i, n in intents],
        "par_moteur": [{"moteur": p, "reponses": n, "latence_moyenne_ms": round(l or 0)} for p, n, l in providers],
    }
