"""CSV upload, validation report, size limits and processing uploaded records."""
from ml.preprocessing import REQUIRED_COLUMNS

HEADER = ",".join(REQUIRED_COLUMNS)
GOOD = ["U{i},2026-0{m}-1{d} 10:00,Tops,3,10,{s},{m},{p},5,Sporty,Footwear".format(
    i=i, m=1 + i % 5, d=i % 9, s={1: "Winter", 2: "Winter", 3: "Summer", 4: "Summer", 5: "Summer"}[1 + i % 5],
    p=900 + i) for i in range(6)]


def _csv(*rows, header=HEADER) -> bytes:
    return (header + "\n" + "\n".join(rows) + "\n").encode()


def _upload(client, headers, content: bytes, name="records.csv"):
    return client.post("/api/data/upload", files={"file": (name, content, "text/csv")}, headers=headers)


def test_upload_validate_and_process(client, admin):
    bad = "X1,2026-01-05 10:00,Shoes,3,10,Winter,1,900,5,Sporty,Footwear"
    r = _upload(client, admin["headers"], _csv(*GOOD, bad))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["report"]["valid_rows"] == 6 and body["report"]["invalid_rows"] == 1
    assert body["report"]["errors"][0]["column"] == "Previous_Category" and body["upload"]["status"] == "accepted"
    upload_id = body["upload"]["id"]
    detail = client.get(f"/api/data/uploads/{upload_id}", headers=admin["headers"]).json()
    assert detail["report"]["total_rows"] == 7
    pending = client.get(f"/api/data?upload_id={upload_id}&status=pending", headers=admin["headers"]).json()
    assert pending["total"] == 6

    r = client.post("/api/drift/process", json={"stream": "live", "count": 500}, headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["processed"] >= 6 and r.json()["remaining"] == 0
    done = client.get(f"/api/data?upload_id={upload_id}&status=processed", headers=admin["headers"]).json()
    assert done["total"] == 6 and all(item["prediction_id"] for item in done["items"])
    uploads = client.get("/api/predictions?source=upload&page_size=100", headers=admin["headers"]).json()
    assert uploads["total"] >= 6 and all(i["actual_category"] == "Footwear" for i in uploads["items"])
    stats = client.get("/api/data/statistics", headers=admin["headers"]).json()
    assert stats["records"]["processed"] >= 6 and stats["uploads"]["invalid_rows"] >= 1


def test_upload_rejections(client, admin, make_user):
    h = admin["headers"]
    r = _upload(client, h, _csv("X1,2026-01-05,Shoes,0,10,Winter,1,-1,5,Sporty,Footwear"))
    assert r.status_code == 422 and r.json()["error"]["details"]["report"]["valid_rows"] == 0
    r = _upload(client, h, _csv("1,2", header="a,b"))
    assert r.status_code == 422 and "Missing required columns" in str(r.json()["error"]["details"])
    assert _upload(client, h, b"x", name="records.xlsx").status_code == 422
    assert _upload(client, h, b"\xff\xfe\x00garbage", name="bad.csv").status_code == 422
    big = _csv(*(GOOD * 2000))                                # > MAX_UPLOAD_MB (0.05 MB in tests)
    assert _upload(client, h, big).status_code == 413
    user = make_user()
    assert _upload(client, user["headers"], _csv(*GOOD)).status_code == 403


def test_template_download(client, make_user):
    analyst = make_user("analyst")
    r = client.get("/api/data/template", headers=analyst["headers"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0] == HEADER
