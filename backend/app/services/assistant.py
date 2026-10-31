"""Assistant conversationnel EcoAbidjan ("Eco").

Fonctionnement hybride :
1. Un moteur local comprend la demande (intention), calcule les faits utiles a partir des
   VRAIES donnees (tarifs, portefeuille, declarations, points relais proches, indicateurs)
   et prepare des suggestions et des liens vers les bons ecrans.
2. Si Snowflake est connecte, Cortex AI (SNOWFLAKE.CORTEX.COMPLETE) redige la reponse a
   partir de ces faits et de l'historique de conversation. Sinon, ou en cas d'erreur,
   le moteur local repond lui-meme : l'assistant fonctionne toujours.
Les chiffres viennent toujours des calculs locaux : le modele ne les invente pas.
"""
import json
import re
import time
import unicodedata
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ChatMessage, Commune, Declaration, DeclarationItem, Material, Payment, RelayPoint, Report,
    User, utcnow,
)
from .business import current_tariff, get_param
from .routing import haversine_km

STAFF = ("agent", "admin")

KNOWLEDGE = """EcoAbidjan aide a garder Abidjan propre et a valoriser les dechets.
- Signaler un depot sauvage : ecran "Signaler", prendre une photo, indiquer la position GPS. L'IA identifie les matieres
  (plastique, carton, aluminium, verre, organique, textile) et donne une estimation INDICATIVE du poids. Un agent confirme
  le signalement : le citoyen gagne alors des points.
- Revendre ses dechets recyclables (menages, commercants, citoyens) : ecran "Declarer". Deux modes : depot en point relais
  (remuneration + points de fidelite) ou collecte a domicile (remuneration seulement). Le montant final = poids pese par
  l'agent x tarif du jour. Le poids declare n'est qu'une estimation.
- Seuil Y : la collecte a domicile n'est possible qu'a partir d'un poids minimum (seuil Y, voir faits). En dessous,
  l'usager depose en point relais, ce qui lui rapporte aussi des points.
- Points : gagnes par kg depose en point relais (+ bonus par depot) et par signalement confirme. Ils se convertissent
  en FCFA (valeur d'un point et minimum de conversion dans les faits) depuis le portefeuille.
- Paiement : apres validation, la remuneration passe "en attente" puis "payee" (Mobile Money, especes ou virement).
- Statuts d'un signalement : signale -> confirme -> planifie (tournee) -> collecte, ou rejete.
- Statuts d'une declaration : soumise -> (planifiee si collecte a domicile) -> validee ou rejetee.
- Bonnes pratiques de tri : vider et rincer les bouteilles, aplatir les cartons et les garder au sec, ecraser les canettes,
  separer les matieres. Le verre et les dechets organiques ne sont pas rachetes pour l'instant.
- Agents : confirment les signalements, pesent et valident les declarations, suivent les tournees optimisees.
- Administrateurs : tableau de bord, tarifs (historique conserve), parametres, paiements, connexion Snowflake."""

MATERIAL_SYNONYMS = {
    "PLASTIQUE": ("plastique", "plastiques", "bouteille", "bouteilles", "pet", "bidon", "bidons", "sachet", "sachets"),
    "CARTON": ("carton", "cartons", "papier", "papiers"),
    "ALUMINIUM": ("aluminium", "alu", "canette", "canettes", "cannette", "cannettes"),
}

# intention -> mots-cles (texte normalise sans accents)
INTENTS = {
    "salutation": ("bonjour", "bonsoir", "salut", "hello", "coucou", "akwaba", "bjr", "yo"),
    "remerciement": ("merci", "super", "parfait", "genial", "top"),
    "tarifs": ("tarif", "prix", "combien le kilo", "par kilo", "fcfa", "rachat", "achete", "acheter", "vaut"),
    "relais": ("relais", "point relais", "ou deposer", "deposer", "proche", "pres de moi", "adresse", "horaire"),
    "signaler": ("signaler", "signalement", "depot sauvage", "ordure", "ordures", "tas", "decharge", "sale", "photo"),
    "declarer": ("declarer", "declaration", "vendre", "revendre", "recycler", "recyclage", "collecte a domicile"),
    "points": ("point", "points", "fidelite", "bonus", "recompense", "convertir", "conversion"),
    "declarer_seuil": ("seuil", "seuil y", "minimum", "domicile"),
    "paiement": ("paiement", "paye", "payer", "argent", "gain", "gains", "gagne", "solde", "mobile money", "orange money",
                 "wave", "momo", "remuneration", "portefeuille"),
    "statut": ("statut", "suivi", "ou en est", "mes declarations", "mes signalements", "historique", "valide", "rejete"),
    "tri": ("trier", "tri", "conseil", "astuce", "preparer", "rincer", "verre", "organique", "recyclable"),
    "ia": ("ia", "intelligence artificielle", "estimation", "poids estime", "analyse", "cortex", "snowflake"),
    "compte": ("compte", "inscription", "inscrire", "mot de passe", "connexion", "connecter", "profil"),
    "tableau_bord": ("tableau de bord", "kpi", "indicateur", "indicateurs", "resume", "bilan", "statistique", "stats",
                     "chiffres", "situation"),
    "a_valider": ("a valider", "en attente de validation", "declarations a traiter", "pesee", "valider"),
    "paiements_attente": ("paiements en attente", "a payer", "payer les usagers"),
    "tournee": ("tournee", "tournees", "itineraire", "collecte du jour", "camion", "tricycle", "planifier"),
    "aide": ("aide", "help", "que peux tu", "tu sais faire", "comment ca marche", "fonctionne"),
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_quantities(text: str) -> dict[str, float]:
    """Repere des quantites du type « 5 kg de plastique », « 3,5 kilos carton », « 20 canettes »."""
    norm = normalize(text)
    found: dict[str, float] = {}
    words = "|".join(sorted({w for ws in MATERIAL_SYNONYMS.values() for w in ws}, key=len, reverse=True))
    pattern = rf"(\d+(?:[.,]\d+)?)\s*(kg|kgs|kilo|kilos|kilogrammes?|g|grammes?)?\s*(?:de |d'|du |des )?\s*({words})\b"
    for qty, unit, word in re.findall(pattern, norm):
        value = float(qty.replace(",", "."))
        if unit.startswith("g") and not unit.startswith("k"):
            value /= 1000
        elif not unit and word in ("canette", "canettes", "cannette", "cannettes"):
            value *= 0.015  # une canette ~15 g
        elif not unit and word in ("bouteille", "bouteilles"):
            value *= 0.03   # une bouteille PET ~30 g
        code = next(c for c, ws in MATERIAL_SYNONYMS.items() if word in ws)
        found[code] = round(found.get(code, 0) + value, 3)
    return found


def detect_intent(text: str, user: User | None) -> str:
    norm = normalize(text)
    if parse_quantities(text):
        return "estimation"
    scores = {}
    for intent, keywords in INTENTS.items():
        # accepte le pluriel : « tarif » reconnait aussi « tarifs »
        score = sum(len(k) for k in keywords if re.search(rf"\b{re.escape(k)}[sx]?\b", norm))
        if score:
            scores[intent] = score
    staff_only = {"tableau_bord", "a_valider", "paiements_attente", "tournee"}
    if not (user and user.role in STAFF):
        scores = {k: v for k, v in scores.items() if k not in staff_only}
    return max(scores, key=scores.get) if scores else "inconnu"


# --- Faits issus des donnees -------------------------------------------------------

def _fcfa(n) -> str:
    return f"{int(round(n or 0)):,}".replace(",", " ") + " FCFA"


def _kg(n) -> str:
    return f"{(n or 0):.1f}".rstrip("0").rstrip(".").replace(".", ",") + " kg"


def tariffs(db: Session) -> list[dict]:
    out = []
    for m in db.scalars(select(Material).where(Material.is_active, Material.is_recyclable)):
        t = current_tariff(db, m.id)
        if t:
            out.append({"code": m.code, "matiere": m.name, "fcfa_par_kg": t.price_fcfa_per_kg})
    return out


def nearest_relays(db: Session, lat: float | None, lon: float | None, user: User | None, n: int = 3) -> list[dict]:
    if lat is None and user and user.commune:
        lat, lon = user.commune.latitude, user.commune.longitude
    relays = list(db.scalars(select(RelayPoint).where(RelayPoint.is_active)))
    rows = []
    for p in relays:
        d = haversine_km((lat, lon), (p.latitude, p.longitude)) if lat is not None else None
        rows.append({"nom": p.name, "adresse": p.address, "horaires": p.opening_hours,
                     "distance_km": round(d, 1) if d is not None else None})
    rows.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))
    return rows[:n]


def user_facts(db: Session, user: User) -> dict:
    payments = list(db.scalars(select(Payment).where(Payment.user_id == user.id)))
    decls = list(db.scalars(select(Declaration).where(Declaration.user_id == user.id)
                            .order_by(Declaration.created_at.desc()).limit(5)))
    reports = list(db.scalars(select(Report).where(Report.user_id == user.id)
                              .order_by(Report.created_at.desc()).limit(5)))
    return {
        "nom": user.full_name, "profil": user.role, "commune": user.commune.name if user.commune else None,
        "points": user.points_balance,
        "gains_payes_fcfa": sum(p.amount_fcfa for p in payments if p.status == "PAYEE"),
        "gains_en_attente_fcfa": sum(p.amount_fcfa for p in payments if p.status == "EN_ATTENTE"),
        "dernieres_declarations": [
            {"numero": d.id, "statut": d.status, "kg_declares": d.total_estimated_kg,
             "kg_valides": d.total_validated_kg, "montant_fcfa": d.total_amount_fcfa,
             "points": d.points_awarded, "motif_rejet": d.rejection_reason}
            for d in decls],
        "derniers_signalements": [
            {"numero": r.id, "statut": r.status, "poids_estime_ia_kg": r.ai_estimated_weight_kg,
             "points": r.points_awarded} for r in reports],
    }


def staff_facts(db: Session) -> dict:
    by_status = dict(db.execute(select(Report.status, func.count()).group_by(Report.status)).all())
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    kg_month = db.scalar(
        select(func.coalesce(func.sum(DeclarationItem.validated_weight_kg), 0))
        .join(Declaration, DeclarationItem.declaration_id == Declaration.id)
        .where(Declaration.status == "VALIDEE", Declaration.validated_at >= month_start))
    top = db.execute(
        select(Commune.name, func.count(Report.id))
        .join(Report, Report.commune_id == Commune.id)
        .where(Report.status.in_(["SIGNALE", "CONFIRME"]))
        .group_by(Commune.name).order_by(func.count(Report.id).desc()).limit(3)).all()
    week_ago = utcnow() - timedelta(days=7)
    return {
        "signalements_par_statut": by_status,
        "nouveaux_signalements_7j": db.scalar(select(func.count(Report.id)).where(Report.created_at >= week_ago)),
        "declarations_a_valider": db.scalar(select(func.count(Declaration.id))
                                            .where(Declaration.status.in_(["SOUMISE", "PLANIFIEE"]))),
        "paiements_en_attente_nb": db.scalar(select(func.count(Payment.id)).where(Payment.status == "EN_ATTENTE")),
        "paiements_en_attente_fcfa": db.scalar(select(func.coalesce(func.sum(Payment.amount_fcfa), 0))
                                               .where(Payment.status == "EN_ATTENTE")),
        "kg_recycles_ce_mois": round(kg_month or 0, 1),
        "communes_les_plus_touchees": [{"commune": c, "signalements_ouverts": n} for c, n in top],
    }


def estimate(db: Session, quantities: dict[str, float]) -> dict:
    lines, total = [], 0
    prices = {t["code"]: t for t in tariffs(db)}
    for code, kg in quantities.items():
        t = prices.get(code)
        if not t:
            continue
        amount = round(kg * t["fcfa_par_kg"])
        total += amount
        lines.append({"matiere": t["matiere"], "kg": kg, "fcfa_par_kg": t["fcfa_par_kg"], "montant_fcfa": amount})
    kg_total = sum(l["kg"] for l in lines)
    points = int(kg_total * get_param(db, "POINTS_PAR_KG_POINT_RELAIS") + get_param(db, "BONUS_DEPOT_POINT_RELAIS")) \
        if kg_total else 0
    return {"lignes": lines, "total_fcfa": total, "points_si_point_relais": points}


# --- Moteur local ----------------------------------------------------------------

def _links_for(intent: str, user: User | None) -> list[dict]:
    staff = bool(user and user.role in STAFF)
    if not user:
        return [{"label": "Creer un compte", "route": ""}]
    table = {
        "signaler": [("📸 Signaler un depot", "signaler")],
        "declarer": [("♻ Declarer mes dechets", "declarer")],
        "estimation": [("♻ Declarer ces dechets", "declarer"), ("📍 Points relais", "relais")],
        "relais": [("📍 Voir la carte des points relais", "relais")],
        "points": [("⭐ Mon portefeuille", "portefeuille")],
        "paiement": [("💰 Mon portefeuille", "portefeuille")],
        "statut": [("🕘 Mon historique", "historique")],
        "tableau_bord": [("📊 Tableau de bord", "dashboard")],
        "a_valider": [("✅ Declarations a valider", "validations")],
        "paiements_attente": [("💰 Paiements", "paiements")],
        "tournee": [("🚚 Tournees", "tournees")],
    }
    links = table.get(intent, [])
    if staff:
        links = [l for l in links if l[1] in ("dashboard", "validations", "paiements", "tournees")]
    else:
        links = [l for l in links if l[1] not in ("dashboard", "validations", "paiements", "tournees")]
    return [{"label": a, "route": b} for a, b in links]


def suggestions_for(user: User | None, intent: str) -> list[str]:
    if user and user.role in STAFF:
        base = ["Resume de la situation", "Declarations a valider", "Paiements en attente", "Planifier une tournee"]
    elif user:
        base = ["J'ai 5 kg de plastique et 3 kg de carton", "Point relais le plus proche", "Mes gains et mes points",
                "Comment signaler un depot ?", "Conseils de tri"]
    else:
        base = ["Comment ca marche ?", "Quels sont les tarifs ?", "Comment creer un compte ?"]
    return [s for s in base if normalize(s) != intent][:4]


def local_reply(intent: str, facts: dict, user: User | None) -> str:
    name = user.full_name.split(" ")[0] if user else None
    t = facts.get("tarifs", [])
    tarif_txt = "\n".join(f"- **{x['matiere']}** : {x['fcfa_par_kg']} FCFA/kg" for x in t)

    if intent == "salutation":
        hello = f"Bonjour {name} 👋" if name else "Bonjour 👋"
        if user and user.role in STAFF:
            return f"{hello} Je suis **Eco**, ton assistant. Je peux te resumer la situation, lister les declarations a valider ou les paiements en attente."
        return (f"{hello} Je suis **Eco**, l'assistant d'EcoAbidjan. Je peux estimer ce que tes dechets te rapportent, "
                "trouver le point relais le plus proche, suivre tes gains et t'aider a signaler un depot sauvage.")
    if intent == "remerciement":
        return "Avec plaisir ! Ensemble pour une Abidjan plus propre ♻"
    if intent == "tarifs":
        return f"Voici les tarifs de rachat en vigueur :\n{tarif_txt}\n\nLe montant final est calcule sur le poids pese par l'agent."
    if intent == "estimation":
        e = facts["estimation"]
        if not e["lignes"]:
            return "Je n'ai pas reconnu de matiere rachetee. Nous rachetons le carton, le plastique et l'aluminium."
        lines = "\n".join(f"- {l['matiere']} : {_kg(l['kg'])} x {l['fcfa_par_kg']} F = **{_fcfa(l['montant_fcfa'])}**"
                          for l in e["lignes"])
        return (f"Estimation de ta remuneration :\n{lines}\n\n**Total : {_fcfa(e['total_fcfa'])}**"
                f"\n\nEn deposant en point relais, tu gagnes aussi environ **{e['points_si_point_relais']} points**. "
                "Le montant final depend du poids pese par l'agent.")
    if intent == "relais":
        rel = facts.get("points_relais", [])
        lines = "\n".join(
            f"- **{r['nom']}**" + (f" — {r['distance_km']} km" if r["distance_km"] is not None else "")
            + (f"\n  {r['adresse']} · {r['horaires']}" if r["adresse"] else "") for r in rel)
        hint = "" if facts.get("position_connue") else "\n\nActive ta localisation pour un classement par distance exact."
        return f"Points relais les plus proches :\n{lines}{hint}"
    if intent == "signaler":
        return ("Pour signaler un depot sauvage :\n1. Ouvre **Signaler**\n2. Prends une photo du depot\n"
                "3. Indique la position (bouton 📍 ou clic sur la carte)\n4. Envoie : l'IA identifie les matieres et estime le poids.\n\n"
                f"Quand un agent confirme ton signalement, tu gagnes **{facts.get('points_signalement', 15)} points**.")
    if intent == "declarer":
        return ("Pour revendre tes dechets recyclables :\n1. Ouvre **Declarer**\n2. Choisis *point relais* (plus de points) "
                f"ou *collecte a domicile* (a partir de {facts['regles']['seuil_y_kg_collecte_domicile']:g} kg)\n3. Ajoute chaque matiere et son poids estime\n4. Un agent pese et valide : tu es paye au tarif du jour.\n\n"
                f"Tarifs actuels :\n{tarif_txt}")
    if intent in ("points", "paiement") and user and "utilisateur" in facts:
        u = facts["utilisateur"]
        rg = facts["regles"]
        return (f"Ton solde : **⭐ {u['points']} points**\n- Gains deja payes : **{_fcfa(u['gains_payes_fcfa'])}**\n"
                f"- En attente de paiement : **{_fcfa(u['gains_en_attente_fcfa'])}**\n\n"
                f"Les points s'obtiennent en deposant en point relais et quand tes signalements sont confirmes. "
                f"1 point = {rg['valeur_point_fcfa']:g} FCFA, convertible des {rg['points_minimum_conversion']:g} points dans ton portefeuille.")
    if intent == "statut" and user and "utilisateur" in facts:
        u = facts["utilisateur"]
        if not u["dernieres_declarations"] and not u["derniers_signalements"]:
            return "Tu n'as encore ni declaration ni signalement. Veux-tu commencer ?"
        out = []
        for d in u["dernieres_declarations"][:3]:
            extra = f", {_fcfa(d['montant_fcfa'])}" if d["montant_fcfa"] else ""
            extra += f" — motif : {d['motif_rejet']}" if d["motif_rejet"] else ""
            out.append(f"- Declaration n°{d['numero']} : **{d['statut'].lower()}**{extra}")
        for r in u["derniers_signalements"][:3]:
            out.append(f"- Signalement n°{r['numero']} : **{r['statut'].lower()}**")
        return "Voici ton suivi :\n" + "\n".join(out)
    if intent == "declarer_seuil":
        rg = facts["regles"]
        return (f"La collecte a domicile est possible a partir de **{rg['seuil_y_kg_collecte_domicile']:g} kg** au total (seuil Y). "
                "En dessous, un passage du camion coute plus cher que la valeur des dechets : depose-les en **point relais**, "
                f"tu gagnes {rg['points_par_kg_point_relais']:g} points par kg + {rg['bonus_par_depot_point_relais']:g} points de bonus.")
    if intent == "tri":
        return ("Conseils pour bien preparer tes dechets :\n- **Plastique** : vide et rince les bouteilles, retire les restes\n"
                "- **Carton** : aplatis-le et garde-le au sec\n- **Aluminium** : ecrase les canettes pour gagner de la place\n"
                "- Separe bien chaque matiere\n\nLe verre et les dechets organiques ne sont pas rachetes pour l'instant.")
    if intent == "ia":
        return ("Quand tu envoies une photo, l'IA (Snowflake Cortex AI quand il est actif) repere les matieres visibles et "
                "estime le volume et le poids du tas. C'est une **estimation indicative** : le poids reel est verifie lors de la collecte, "
                "et l'ecart est suivi pour ameliorer l'IA.")
    if intent == "compte":
        if user:
            return f"Tu es connecte en tant que **{user.full_name}** ({user.role}). Pour te deconnecter, utilise le bouton *Quitter* en haut."
        return "Clique sur **Inscription** sur l'ecran d'accueil : nom, e-mail, telephone (pour Mobile Money), profil et mot de passe. C'est gratuit."
    if intent == "tableau_bord" and "indicateurs" in facts:
        s = facts["indicateurs"]
        st = s["signalements_par_statut"]
        top = ", ".join(f"{c['commune']} ({c['signalements_ouverts']})" for c in s["communes_les_plus_touchees"]) or "—"
        return (f"Situation actuelle :\n- Signalements a confirmer : **{st.get('SIGNALE', 0)}**, confirmes a collecter : **{st.get('CONFIRME', 0)}**, "
                f"planifies : **{st.get('PLANIFIE', 0)}**\n- Nouveaux signalements (7 jours) : **{s['nouveaux_signalements_7j']}**\n"
                f"- Declarations a valider : **{s['declarations_a_valider']}**\n"
                f"- Paiements en attente : **{s['paiements_en_attente_nb']}** ({_fcfa(s['paiements_en_attente_fcfa'])})\n"
                f"- Recycle ce mois-ci : **{_kg(s['kg_recycles_ce_mois'])}**\n- Communes les plus touchees : {top}")
    if intent == "a_valider" and "indicateurs" in facts:
        return f"Il y a **{facts['indicateurs']['declarations_a_valider']} declarations** a peser et valider."
    if intent == "paiements_attente" and "indicateurs" in facts:
        s = facts["indicateurs"]
        return f"**{s['paiements_en_attente_nb']} paiements** sont en attente, pour un total de **{_fcfa(s['paiements_en_attente_fcfa'])}**."
    if intent == "tournee" and "indicateurs" in facts:
        n = facts["indicateurs"]["signalements_par_statut"].get("CONFIRME", 0)
        return (f"**{n} signalements confirmes** attendent une collecte. Dans **Tournees**, choisis un point de depart : "
                "l'itineraire est optimise automatiquement avec la distance, la duree et le cout estimes.")
    if intent == "aide":
        if user and user.role in STAFF:
            return "Je peux te donner un resume de la situation, le nombre de declarations a valider, les paiements en attente et t'aider a planifier une tournee."
        return ("Je peux :\n- estimer ce que tes dechets te rapportent (ex. *« 4 kg de plastique »*)\n- trouver le point relais le plus proche\n"
                "- suivre tes gains, tes points et tes declarations\n- t'expliquer comment signaler un depot sauvage\n- te donner des conseils de tri")
    return ("Je n'ai pas bien compris 🤔 Tu peux me demander par exemple : *« Combien pour 5 kg de carton ? »*, "
            "*« Ou est le point relais le plus proche ? »* ou *« Ou en sont mes paiements ? »*.")


# --- Cortex -------------------------------------------------------------------

def _use_cortex() -> bool:
    if settings.assistant_provider == "local":
        return False
    return settings.snowflake_configured


def cortex_reply(question: str, history: list[dict], facts: dict, user: User | None) -> str:
    from .snowflake_client import connect

    profile = f"{user.full_name} ({user.role})" if user else "visiteur non connecte"
    system = (
        "Tu es Eco, l'assistant de l'application EcoAbidjan (gestion et valorisation des dechets a Abidjan, Cote d'Ivoire). "
        "Tu reponds en francais simple, chaleureux et concis (5 phrases maximum ou une courte liste), en markdown leger. "
        "Utilise UNIQUEMENT les faits fournis pour les chiffres, montants, points, statuts et adresses : n'invente jamais de chiffre. "
        "Si une information manque, dis-le et oriente vers l'ecran adapte. Rappelle que les estimations sont indicatives "
        "quand tu parles de poids ou de montants. Refuse poliment les sujets sans rapport avec l'application, la proprete "
        "ou le recyclage.\n\n"
        f"Utilisateur : {profile}\n\nConnaissances :\n{KNOWLEDGE}\n\n"
        f"Faits calcules a partir des donnees (JSON) :\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    messages = [{"role": "system", "content": system}, *history[-8:], {"role": "user", "content": question}]
    options = {"temperature": 0.3, "max_tokens": 600}
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, PARSE_JSON(%s), PARSE_JSON(%s))",
                    (settings.cortex_chat_model, json.dumps(messages, ensure_ascii=False), json.dumps(options)))
        raw = cur.fetchone()[0]
    finally:
        conn.close()
    data = json.loads(raw) if isinstance(raw, str) else raw
    text = data["choices"][0].get("messages") or data["choices"][0].get("message") or ""
    if not text.strip():
        raise ValueError("Reponse vide de Cortex")
    return text.strip()


# --- Point d'entree -------------------------------------------------------------

def answer(db: Session, *, question: str, session_id: str, user: User | None,
           lat: float | None = None, lon: float | None = None) -> dict:
    started = time.perf_counter()
    intent = detect_intent(question, user)
    facts: dict = {
        "tarifs": tariffs(db), "points_signalement": int(get_param(db, "POINTS_SIGNALEMENT_CONFIRME")),
        "regles": {
            "seuil_y_kg_collecte_domicile": get_param(db, "SEUIL_Y_KG"),
            "points_par_kg_point_relais": get_param(db, "POINTS_PAR_KG_POINT_RELAIS"),
            "bonus_par_depot_point_relais": get_param(db, "BONUS_DEPOT_POINT_RELAIS"),
            "valeur_point_fcfa": get_param(db, "POINT_VALEUR_FCFA"),
            "points_minimum_conversion": get_param(db, "POINTS_MIN_CONVERSION"),
        },
    }
    if intent in ("relais", "estimation", "declarer") or lat is not None:
        facts["points_relais"] = nearest_relays(db, lat, lon, user)
        facts["position_connue"] = lat is not None
    if intent == "estimation":
        facts["estimation"] = estimate(db, parse_quantities(question))
    if user and user.role not in STAFF:
        facts["utilisateur"] = user_facts(db, user)
    if user and user.role in STAFF:
        facts["indicateurs"] = staff_facts(db)

    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(list(db.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc()).limit(8))))
    ]

    provider, model, error = "local", "eco-regles-v1", None
    reply = None
    if _use_cortex():
        try:
            reply = cortex_reply(question, history, facts, user)
            provider, model = "snowflake-cortex", settings.cortex_chat_model
        except Exception as exc:  # noqa: BLE001
            error = f"Cortex indisponible, reponse locale : {exc}"[:500]
    if reply is None:
        reply = local_reply(intent, facts, user)

    latency = int((time.perf_counter() - started) * 1000)
    uid = user.id if user else None
    db.add(ChatMessage(session_id=session_id, user_id=uid, role="user", content=question, intent=intent))
    db.add(ChatMessage(session_id=session_id, user_id=uid, role="assistant", content=reply, intent=intent,
                       provider=provider, model=model, latency_ms=latency, error=error))
    db.commit()
    return {
        "reply": reply, "intent": intent, "provider": provider, "model": model, "latency_ms": latency,
        "suggestions": suggestions_for(user, intent), "links": _links_for(intent, user),
    }
