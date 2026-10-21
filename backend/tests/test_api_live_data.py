"""HTTP: live data pathway (alias, batch, outcomes, summary, rejections) and data validation of uploads."""
import uuid

from ml.preprocessing import REQUIRED_COLUMNS

EVENT = {"customer_id": "C1023", "previous_category": "Tops", "purchase_frequency": 4, "recency": 12,
         "season": "Monsoon", "month": 6, "price": 1299, "discount": 20, "customer_preference": "Casual"}
HEADER = ",".join(REQUIRED_COLUMNS)


def _eid():
    return f"evt-{uuid.uuid4().hex[:12]}"


def _csv(*rows, header=HEADER) -> bytes:
    return (header + "\n" + "\n".join(rows) + "\n").encode()


def _upload(client, headers, content: bytes, strict: bool = False):
    return client.post("/api/data/upload" + ("?strict=true" if strict else ""),
                       files={"file": ("live.csv", content, "text/csv")}, headers=headers)


def test_single_event_validation_and_stored_rejections(client, make_user, admin):
    u = make_user()
    eid = _eid()
    r = client.post("/api/events", json={**EVENT, "event_id": eid}, headers=u["headers"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["event_id"] == eid and body["prediction"]["model_version"] and body["received_at"]
    assert body["validation"]["passed"] is True and body["pipeline"][0]["stage"] == "validated"
    bad = client.post("/api/events", json={**EVENT, "event_id": _eid(), "price": -500, "season": "XYZ"},
                      headers=u["headers"])
    assert bad.status_code == 422
    err = bad.json()["error"]
    assert err["code"] == "validation_failed" and err["message"].startswith("Event rejected")
    assert {("price", "-500"), ("season", "XYZ")} <= {(d["field"], d["value"]) for d in err["details"]}
    not_json = client.post("/api/events/purchase", content=b"{not json",
                           headers={**u["headers"], "Content-Type": "application/json"})
    assert not_json.status_code == 422
    s = client.get("/api/events/summary", headers=u["headers"]).json()
    assert (s["scope"], s["received"], s["awaiting_outcome"], s["rejected"]) == ("own", 1, 1, 2)
    rej = client.get("/api/events/rejections?page_size=50", headers=admin["headers"]).json()
    assert rej["total"] >= 2 and any(d["field"] == "season" for i in rej["items"] for d in i["errors"])
    assert client.get("/api/events/rejections", headers=u["headers"]).status_code == 403
    assert client.post("/api/events", json=EVENT).status_code == 401


def test_batch_ingestion_and_batch_outcomes(client, make_user):
    h = make_user()["headers"]
    ids = [_eid() for _ in range(3)]
    r = client.post("/api/events/batch", json={"events": [
        {**EVENT, "event_id": ids[0]}, {**EVENT, "event_id": ids[1], "discount": 150},
        {**EVENT, "event_id": ids[2], "actual_category": "Tops"}]}, headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["accepted"], b["rejected"]) == (2, 1)
    assert [x["status"] for x in b["results"]] == ["accepted", "rejected", "accepted"]
    assert b["results"][2]["outcome"]["actual_category"] == "Tops" and b["results"][0]["model_version"]
    all_bad = client.post("/api/events/batch", json={"events": [{**EVENT, "price": -1}]}, headers=h)
    assert all_bad.status_code == 422 and all_bad.json()["error"]["details"]["rejected"] == 1
    assert client.post("/api/events/batch", json=[EVENT], headers=h).status_code == 422
    ingestion = client.app.state.ingestion
    limit = ingestion.max_batch
    ingestion.max_batch = 2
    try:
        assert client.post("/api/events/batch", json={"events": [EVENT] * 3}, headers=h).status_code == 422
    finally:
        ingestion.max_batch = limit
    out = client.post("/api/events/outcomes", json={"outcomes": [
        {"event_id": ids[0], "actual_category": "Bottoms"}, {"event_id": ids[2], "actual_category": "Tops"},
        {"event_id": "nope-1", "actual_category": "Tops"}]}, headers=h)
    assert out.status_code == 200, out.text
    assert [x["status"] for x in out.json()["results"]] == ["recorded", "conflict", "not_found"]
    stored = client.get(f"/api/predictions?search={ids[0]}", headers=h).json()["items"][0]
    assert stored["actual_category"] == "Bottoms" and stored["outcome_at"] and stored["model_version"]


def test_upload_rejections_strict_mode_and_reupload(client, admin):
    h = admin["headers"]
    missing = _upload(client, h, _csv("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Bottoms",
                                      header=HEADER.replace(",Customer_Preference", "")))
    assert missing.status_code == 422
    e = missing.json()["error"]
    assert e["message"].startswith("Upload rejected") and e["details"]["report"]["missing_columns"] == [
        "Customer_Preference"]
    tag = uuid.uuid4().hex[:6]
    rows = [f"V{tag}1,2024-03-02 10:00,Tops,3,10,XYZ,3,1200,10,Casual,Bottoms",
            f"V{tag}2,2024-03-02 11:00,Tops,3,10,Summer,3,-500,10,Casual,Bottoms",
            f"V{tag}3,2024-03-02 12:00,Tops,3,10,Summer,3,900,10,Casual,Dresses"]
    strict = _upload(client, h, _csv(*rows), strict=True)
    assert strict.status_code == 422 and "strict mode" in strict.json()["error"]["message"]
    partial = _upload(client, h, _csv(*rows))
    assert partial.status_code == 201 and partial.json()["message"].startswith("Validation successful: 1 of 3")
    again = _upload(client, h, _csv(rows[2]))
    assert again.status_code == 422 and "already uploaded" in again.json()["error"]["message"]
    assert again.json()["error"]["details"]["report"]["previously_uploaded"] == 1
    v = client.get("/api/data/validation", headers=h).json()
    assert v["rules"]["csv_required_columns"] == REQUIRED_COLUMNS and v["csv"]["uploads_rejected"] >= 3
    assert {"accepted", "rejected", "rejection_rate"} <= set(v["live"]) and isinstance(v["top_rejection_reasons"], list)
