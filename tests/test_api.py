from io import BytesIO

from PIL import Image, ImageDraw

from backend.app.services.routing import haversine_km, optimize_route

from .conftest import login


def _register(client, email, role="menage", **extra):
    body = {"email": email, "full_name": "Test Usager", "password": "motdepasse1", "role": role, **extra}
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _materials(client):
    return {m["code"]: m for m in client.get("/api/materials").json()}


def _fake_dump_photo() -> bytes:
    img = Image.new("RGB", (400, 300), (120, 160, 210))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 150, 200, 280], fill=(170, 120, 60))   # carton
    d.rectangle([200, 140, 380, 290], fill=(230, 40, 40))   # plastique colore
    d.ellipse([120, 120, 220, 200], fill=(170, 170, 170))   # metal
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def test_health_and_reference_data(client):
    assert client.get("/api/health").json()["status"] == "ok"
    mats = _materials(client)
    assert mats["CARTON"]["price_fcfa_per_kg"] == 200
    assert mats["PLASTIQUE"]["price_fcfa_per_kg"] == 250
    assert mats["ALUMINIUM"]["price_fcfa_per_kg"] == 300
    assert len(client.get("/api/communes").json()) == 13
    assert client.get("/api/relay-points").json()


def test_register_rejects_duplicate_and_bad_login(client):
    _register(client, "doublon@test.ci")
    r = client.post("/api/auth/register", json={"email": "doublon@test.ci", "full_name": "X Y",
                                                 "password": "motdepasse1"})
    assert r.status_code == 409
    assert client.post("/api/auth/login", json={"email": "doublon@test.ci", "password": "faux"}).status_code == 401


def test_declaration_validation_pays_and_awards_points(client, agent):
    user = _register(client, "menage1@test.ci")
    mats = _materials(client)
    relay = client.get("/api/relay-points").json()[0]
    r = client.post("/api/declarations", headers=user, json={
        "mode": "POINT_RELAIS", "relay_point_id": relay["id"],
        "items": [{"material_id": mats["CARTON"]["id"], "estimated_weight_kg": 10},
                  {"material_id": mats["ALUMINIUM"]["id"], "estimated_weight_kg": 2}],
    })
    assert r.status_code == 201, r.text
    decl = r.json()
    assert decl["status"] == "SOUMISE" and decl["total_estimated_kg"] == 12

    weights = {"Carton": 8.0, "Aluminium": 2.5}
    items = [{"item_id": i["id"], "validated_weight_kg": weights[i["material"]]} for i in decl["items"]]
    v = client.post(f"/api/admin/declarations/{decl['id']}/validate", headers=agent, json={"items": items})
    assert v.status_code == 200, v.text
    out = v.json()
    assert out["status"] == "VALIDEE"
    assert out["total_validated_kg"] == 10.5
    assert out["total_amount_fcfa"] == 8 * 200 + int(round(2.5 * 300))  # 2350
    assert out["points_awarded"] == int(10.5 * 10 + 20)  # 125

    wallet = client.get("/api/wallet", headers=user).json()
    assert wallet["pending_fcfa"] == 2350
    assert wallet["points_balance"] == 125

    again = client.post(f"/api/admin/declarations/{decl['id']}/validate", headers=agent, json={"items": items})
    assert again.status_code == 400


def test_home_collection_needs_gps_seuil_y_and_gets_no_points(client, agent):
    user = _register(client, "commerce@test.ci", role="commercant", business_name="Boutique Test")
    mats = _materials(client)
    bad = client.post("/api/declarations", headers=user, json={
        "mode": "COLLECTE_DOMICILE", "items": [{"material_id": mats["PLASTIQUE"]["id"], "estimated_weight_kg": 12}]})
    assert bad.status_code == 400
    # sous le seuil Y (10 kg), la collecte a domicile est refusee
    below = client.post("/api/declarations", headers=user, json={
        "mode": "COLLECTE_DOMICILE", "latitude": 5.30, "longitude": -4.00,
        "items": [{"material_id": mats["PLASTIQUE"]["id"], "estimated_weight_kg": 5}]})
    assert below.status_code == 400 and "seuil Y" in below.json()["detail"]
    ok = client.post("/api/declarations", headers=user, json={
        "mode": "COLLECTE_DOMICILE", "latitude": 5.30, "longitude": -4.00,
        "items": [{"material_id": mats["PLASTIQUE"]["id"], "estimated_weight_kg": 12}]}).json()
    v = client.post(f"/api/admin/declarations/{ok['id']}/validate", headers=agent,
                    json={"items": [{"item_id": ok["items"][0]["id"], "validated_weight_kg": 4}]}).json()
    assert v["total_amount_fcfa"] == 1000
    assert v["points_awarded"] == 0


def test_non_recyclable_material_refused(client):
    user = _register(client, "menage2@test.ci")
    mats = _materials(client)
    relay = client.get("/api/relay-points").json()[0]
    r = client.post("/api/declarations", headers=user, json={
        "mode": "POINT_RELAIS", "relay_point_id": relay["id"],
        "items": [{"material_id": mats["VERRE"]["id"], "estimated_weight_kg": 3}]})
    assert r.status_code == 400


def test_report_with_photo_runs_ai_and_confirmation_awards_points(client, agent):
    user = _register(client, "citoyen1@test.ci", role="citoyen")
    r = client.post("/api/reports", headers=user,
                    data={"latitude": "5.3605", "longitude": "-3.9705", "description": "Tas de dechets"},
                    files={"photo": ("depot.jpg", _fake_dump_photo(), "image/jpeg")})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["commune"] == "Cocody"
    a = rep["analysis"]
    assert a["provider"] == "local" and a["status"] == "OK"
    assert a["materials"] and abs(sum(m["share"] for m in a["materials"]) - 1) < 0.01
    assert a["estimated_weight_kg"] > 0

    photo = client.get(rep["photos"][0], params={"token": user["Authorization"].split()[1]})
    assert photo.status_code == 200

    c = client.patch(f"/api/admin/reports/{rep['id']}/status", headers=agent, json={"status": "CONFIRME"})
    assert c.json()["points_awarded"] == 15
    assert client.get("/api/me", headers=user).json()["points_balance"] == 15


def test_report_rejects_non_image(client):
    user = _register(client, "citoyen2@test.ci", role="citoyen")
    r = client.post("/api/reports", headers=user, data={"latitude": "5.3", "longitude": "-4.0"},
                    files={"photo": ("x.jpg", b"pas une image", "image/jpeg")})
    assert r.status_code == 400


def test_tariff_change_keeps_history_and_applies_to_new_validations(client, admin, agent):
    mats = _materials(client)
    r = client.put(f"/api/admin/materials/{mats['PLASTIQUE']['id']}/tariff", headers=admin,
                   json={"price_fcfa_per_kg": 275, "note": "Test"})
    assert r.status_code == 200
    assert _materials(client)["PLASTIQUE"]["price_fcfa_per_kg"] == 275
    hist = [t for t in client.get("/api/admin/tariffs/history", headers=admin).json() if t["material_code"] == "PLASTIQUE"]
    assert len(hist) == 2 and sum(1 for t in hist if t["valid_to"] is None) == 1
    # un agent ne peut pas changer les tarifs
    assert client.put(f"/api/admin/materials/{mats['PLASTIQUE']['id']}/tariff", headers=agent,
                      json={"price_fcfa_per_kg": 1}).status_code == 403


def test_collection_planning_and_stop_completion(client, agent):
    cand = client.get("/api/admin/collection-candidates", headers=agent).json()
    report_ids = [r["id"] for r in cand["reports"]][:5]
    assert report_ids, "le jeu de demo doit contenir des signalements confirmes"
    relay = client.get("/api/relay-points").json()[0]
    r = client.post("/api/admin/collections", headers=agent, json={
        "name": "Test", "planned_date": "2026-11-02", "depot_relay_point_id": relay["id"],
        "report_ids": report_ids})
    assert r.status_code == 201, r.text
    col = r.json()
    assert len(col["stops"]) == len(report_ids)
    assert col["total_distance_km"] > 0 and col["estimated_cost_fcfa"] > 0
    stop = col["stops"][0]
    upd = client.patch(f"/api/admin/collections/{col['id']}/stops/{stop['id']}", headers=agent,
                       json={"status": "FAIT", "collected_weight_kg": 120}).json()
    assert upd["status"] == "EN_COURS" and upd["collected_kg"] == 120
    rep = [x for x in client.get("/api/admin/reports?status=COLLECTE", headers=agent).json() if x["id"] == stop["report_id"]]
    assert rep and rep[0]["validated_weight_kg"] == 120
    cost = client.post(f"/api/admin/collections/{col['id']}/costs", headers=agent,
                       json={"cost_type": "CARBURANT", "amount_fcfa": 4000}).json()
    assert cost["real_cost_fcfa"] == 4000


def test_dashboard_and_permissions(client, admin):
    citizen = login(client, "citoyen@ecoabidjan.ci")
    assert client.get("/api/admin/dashboard", headers=citizen).status_code == 403
    assert client.get("/api/admin/dashboard").status_code == 401
    d = client.get("/api/admin/dashboard", headers=admin).json()
    assert d["kpis"]["reports_total"] > 0
    assert d["kpis"]["kg_recycled"] > 0
    assert d["kpis"]["amount_paid_fcfa"] > 0
    assert len(d["monthly"]) == 6
    assert len({m["month"] for m in d["monthly"]}) == 6


def test_payment_marked_paid(client, admin):
    pending = client.get("/api/admin/payments?status=EN_ATTENTE", headers=admin).json()
    p = pending[0]
    r = client.patch(f"/api/admin/payments/{p['id']}", headers=admin,
                     json={"status": "PAYEE", "reference": "OM-TEST", "method": "MOBILE_MONEY"})
    assert r.json()["status"] == "PAYEE"
    assert client.patch(f"/api/admin/payments/{p['id']}", headers=admin, json={"status": "PAYEE"}).status_code == 400


def test_snowflake_is_server_side_only(client, admin):
    status = client.get("/api/admin/snowflake/status", headers=admin).json()
    assert status["configured"] is False and "password" not in status
    # aucune configuration Snowflake possible depuis l'API / l'interface
    assert client.put("/api/admin/snowflake/config", headers=admin, json={}).status_code in (404, 405)
    assert client.post("/api/admin/snowflake/sync", headers=admin).status_code in (404, 405)
    from backend.app.services.snowflake_client import run_diagnostics
    assert run_diagnostics()[0]["ok"] is False


def test_pilot_simulation_meets_hackathon_constraints(client, admin):
    p = client.get("/api/admin/pilot", headers=admin).json()
    assert len(p["communes"]) >= 4
    assert {"Cocody", "Yopougon", "Abobo", "Koumassi"} <= {c["commune"] for c in p["communes"]}
    assert p["totaux"]["menages"] >= 500 and p["totaux"]["commercants"] >= 200
    assert p["regles"]["seuil_y"]["valeur_kg"] == 10
    assert "justification" in p["regles"]["points"]


def test_points_conversion(client, agent):
    user = _register(client, "convertisseur@test.ci")
    me = client.get("/api/me", headers=user).json()
    assert client.post("/api/wallet/convert", headers=user, json={"points": 500}).status_code == 400  # solde vide
    # gagne des points : 60 kg en point relais -> 60*10 + 20 = 620 points
    mats = _materials(client)
    relay = client.get("/api/relay-points").json()[0]
    d = client.post("/api/declarations", headers=user, json={
        "mode": "POINT_RELAIS", "relay_point_id": relay["id"],
        "items": [{"material_id": mats["CARTON"]["id"], "estimated_weight_kg": 60}]}).json()
    client.post(f"/api/admin/declarations/{d['id']}/validate", headers=agent,
                json={"items": [{"item_id": d["items"][0]["id"], "validated_weight_kg": 60}]})
    assert client.get("/api/me", headers=user).json()["points_balance"] == me["points_balance"] + 620
    assert client.post("/api/wallet/convert", headers=user, json={"points": 400}).status_code == 400  # < minimum
    pay = client.post("/api/wallet/convert", headers=user, json={"points": 600}).json()
    assert pay["kind"] == "CONVERSION_POINTS" and pay["amount_fcfa"] == 600 and pay["status"] == "EN_ATTENTE"
    assert client.get("/api/me", headers=user).json()["points_balance"] == 20


def test_route_optimizer_visits_every_stop_once():
    depot = (5.30, -4.00)
    stops = [(5.36, -3.97), (5.31, -4.01), (5.42, -4.02), (5.29, -3.95), (5.34, -4.07)]
    res = optimize_route(depot, stops)
    assert sorted(res["order"]) == list(range(len(stops)))
    naive = sum(haversine_km(a, b) for a, b in zip([depot, *stops], [*stops, depot]))
    assert res["distance_km"] <= round(naive, 2) + 1e-6
