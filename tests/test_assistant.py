from backend.app.services.assistant import detect_intent, parse_quantities

from .conftest import login

SID = "testsession0001"


def _chat(client, msg, headers=None, sid=SID, **extra):
    r = client.post("/api/assistant/chat", headers=headers or {}, json={"message": msg, "session_id": sid, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_parse_quantities_understands_units_and_synonyms():
    q = parse_quantities("J'ai 5 kg de plastique, 3,5 kilos de carton et 500 g d'alu")
    assert q == {"PLASTIQUE": 5.0, "CARTON": 3.5, "ALUMINIUM": 0.5}
    assert parse_quantities("100 canettes") == {"ALUMINIUM": 1.5}
    assert parse_quantities("bonjour") == {}


def test_detect_intent():
    assert detect_intent("Quels sont vos tarifs ?", None) == "tarifs"
    assert detect_intent("ou est le point relais le plus proche", None) == "relais"
    assert detect_intent("comment signaler un depot sauvage", None) == "signaler"
    # les intentions reservees au personnel ne sont pas proposees aux visiteurs
    assert detect_intent("resume du tableau de bord", None) != "tableau_bord"


def test_visitor_gets_tariffs_without_login(client):
    r = _chat(client, "Quels sont les tarifs ?", sid="visiteur000001")
    assert r["intent"] == "tarifs" and r["provider"] == "local"
    for m in client.get("/api/materials").json():
        if m["price_fcfa_per_kg"]:
            assert f"{m['name']}** : {m['price_fcfa_per_kg']} FCFA/kg" in r["reply"]
    assert r["suggestions"]


def test_estimation_uses_real_tariffs(client):
    user = login(client, "menage@ecoabidjan.ci")
    r = _chat(client, "Combien pour 5 kg de plastique et 3 kg de carton ?", headers=user, sid="menage0000001")
    assert r["intent"] == "estimation"
    plastique = 5 * client.get("/api/materials").json()[1]["price_fcfa_per_kg"]
    assert f"{plastique + 600:,}".replace(",", " ") in r["reply"]
    assert any(l["route"] == "declarer" for l in r["links"])


def test_user_wallet_answer_and_history(client):
    user = login(client, "citoyen@ecoabidjan.ci")
    points = client.get("/api/me", headers=user).json()["points_balance"]
    r = _chat(client, "Combien j'ai de points ?", headers=user, sid="citoyen000001")
    assert str(points) in r["reply"].replace(" ", "")
    hist = client.get("/api/assistant/history", headers=user, params={"session_id": "citoyen000001"}).json()
    assert [m["role"] for m in hist[-2:]] == ["user", "assistant"]
    # un visiteur ne peut pas lire l'historique d'un usager connecte
    assert client.get("/api/assistant/history", params={"session_id": "citoyen000001"}).json() == []


def test_relay_answer_sorted_by_distance(client):
    r = _chat(client, "point relais proche de moi", sid="visiteur000002", latitude=5.34, longitude=-4.083)
    assert r["intent"] == "relais"
    first = r["reply"].split("\n")[1]
    assert "Yopougon" in first and "km" in first


def test_staff_summary_and_stats(client, admin):
    r = _chat(client, "Resume de la situation", headers=admin, sid="admin00000001")
    assert r["intent"] == "tableau_bord" and "Declarations a valider" in r["reply"]
    stats = client.get("/api/admin/assistant/stats", headers=admin).json()
    assert stats["questions_30j"] >= 1
    citizen = login(client, "citoyen@ecoabidjan.ci")
    assert client.get("/api/admin/assistant/stats", headers=citizen).status_code == 403


def test_unknown_question_and_validation(client):
    r = _chat(client, "xyzzy", sid="visiteur000003")
    assert r["intent"] == "inconnu" and r["suggestions"]
    bad = client.post("/api/assistant/chat", json={"message": "", "session_id": SID})
    assert bad.status_code == 422
