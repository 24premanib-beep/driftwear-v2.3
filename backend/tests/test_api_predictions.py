"""Live predictions, outcomes and prediction history."""
import re

from tests.conftest import VALID_INPUT


def test_prediction_is_stored(client, make_user):
    u = make_user()
    r = client.post("/api/predict", json=VALID_INPUT, headers=u["headers"])
    assert r.status_code == 201, r.text
    body = r.json()
    p = body["prediction"]
    assert re.match(r"^v\d+\.\d+$", p["model_version"]) and p["stream"] == "live" and p["source"] == "api"
    assert p["predicted_category"] in ("Tops", "Bottoms", "Dresses", "Footwear", "Outerwear", "Accessories")
    assert 0 < p["confidence"] <= 1 and p["actual_category"] is None and body["outcome"] is None
    assert body["drift_status"] in ("STABLE", "WARNING", "DRIFT")
    stored = client.get(f"/api/predictions/{p['id']}", headers=u["headers"]).json()
    assert stored["features"]["Price"] == 1499 and stored["user_id"] == u["id"]


def test_month_and_season_are_derived_from_the_date(client, make_user):
    u = make_user()
    payload = {k: v for k, v in VALID_INPUT.items()}
    payload["purchase_date"] = "2025-07-15T10:00:00"
    f = client.post("/api/predict", json=payload, headers=u["headers"]).json()["prediction"]["features"]
    assert f["Month"] == 7 and f["Season"] == "Monsoon" and f["Purchase_Date"] == "2025-07-15 10:00"


def test_invalid_input_is_rejected_with_field_errors(client, make_user):
    u = make_user()
    cases = [({"price": 0}, "price"), ({"discount": 95}, "discount"), ({"recency": 9999}, "recency"),
             ({"previous_category": "Shoes"}, "previous_category"), ({"purchase_date": "2099-01-01T00:00:00"}, None),
             ({"customer_id": "bad id!"}, "customer_id"), ({"unexpected": 1}, "unexpected")]
    for patch, field in cases:
        r = client.post("/api/predict", json={**VALID_INPUT, **patch}, headers=u["headers"])
        assert r.status_code == 422, (patch, r.text)
        err = r.json()["error"]
        assert err["code"] == "validation_failed" and err["details"]
        if field:
            assert any(d["field"] == field for d in err["details"]), (patch, err)
        assert "Traceback" not in r.text


def test_prediction_with_actual_updates_drift_monitoring(client, make_user, admin):
    u = make_user()
    before = client.get("/api/drift/status", headers=admin["headers"]).json()["records_processed"]
    r = client.post("/api/predict", json={**VALID_INPUT, "actual_category": "Tops"}, headers=u["headers"])
    assert r.status_code == 201
    out, p = r.json()["outcome"], r.json()["prediction"]
    assert out["actual_category"] == "Tops" and out["is_correct"] == (p["predicted_category"] == "Tops")
    assert p["actual_category"] == "Tops" and p["step"] == out["step"]
    after = client.get("/api/drift/status", headers=admin["headers"]).json()["records_processed"]
    assert after == before + 1


def test_late_outcome_and_conflict(client, make_user):
    u = make_user()
    p = client.post("/api/predict", json=VALID_INPUT, headers=u["headers"]).json()["prediction"]
    r = client.post(f"/api/predictions/{p['id']}/outcome", json={"actual_category": p["predicted_category"]},
                    headers=u["headers"])
    assert r.status_code == 200 and r.json()["is_correct"] is True
    again = client.post(f"/api/predictions/{p['id']}/outcome", json={"actual_category": "Tops"}, headers=u["headers"])
    assert again.status_code == 409
    bad = client.post(f"/api/predictions/{p['id']}/outcome", json={"actual_category": "Hats"}, headers=u["headers"])
    assert bad.status_code == 422


def test_history_is_private_to_its_owner(client, make_user):
    alice, bob, analyst = make_user(), make_user(), make_user("analyst")
    p = client.post("/api/predict", json=VALID_INPUT, headers=alice["headers"]).json()["prediction"]
    assert client.get(f"/api/predictions/{p['id']}", headers=bob["headers"]).status_code == 404
    assert client.post(f"/api/predictions/{p['id']}/outcome", json={"actual_category": "Tops"},
                       headers=bob["headers"]).status_code == 404
    ids = [i["id"] for i in client.get("/api/predictions?page_size=100", headers=bob["headers"]).json()["items"]]
    assert p["id"] not in ids
    assert client.get(f"/api/predictions/{p['id']}", headers=analyst["headers"]).status_code == 200
    assert client.get("/api/predictions?stream=simulation", headers=bob["headers"]).status_code == 403


def test_history_filters_and_pagination(client, make_user):
    u = make_user()
    for i in range(3):
        client.post("/api/predict", json={**VALID_INPUT, "customer_id": f"PG{i}"}, headers=u["headers"])
    page = client.get("/api/predictions?page_size=2&page=1", headers=u["headers"]).json()
    assert page["total"] == 3 and page["pages"] == 2 and len(page["items"]) == 2
    found = client.get("/api/predictions?search=PG1", headers=u["headers"]).json()
    assert [i["customer_id"] for i in found["items"]] == ["PG1"]
    assert client.get("/api/predictions?labeled=false", headers=u["headers"]).json()["total"] == 3
    assert client.get("/api/predictions?page_size=1000", headers=u["headers"]).status_code == 422
