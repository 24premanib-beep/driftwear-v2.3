"""Audit log: sanitising, event mapping, and the SQL writer/query (when SQLAlchemy is installed)."""
import asyncio

import pytest

from app.services import events as ev
from app.services.audit import AuditEventRecorder, sanitize
from app.services.events import make_event


def test_sanitize_removes_secrets_and_bounds_values():
    clean = sanitize({"password": "x", "Token": "y", "api_key": "z", "nested": {"secret": 1, "ok": 2},
                      "long": "a" * 1000, "items": list(range(200)), "fine": "value"})
    assert "password" not in clean and "Token" not in clean and "api_key" not in clean
    assert clean["nested"] == {"ok": 2} and len(clean["long"]) <= 301 and len(clean["items"]) == 50
    assert clean["fine"] == "value"


def test_only_system_events_are_mapped():
    drift = make_event(ev.DRIFT_DETECTED, "live", "Concept drift detected", detector="DDM", model_version="v1.0",
                       data={"event_id": "Drift 1", "step": 40, "severity": "High", "from_version": "v1.0",
                             "to_version": "v2.0", "noise": "dropped"})
    e = AuditEventRecorder.entry(drift)
    assert e["action"] == "drift.detected" and e["severity"] == "critical" and e["resource_id"] == "Drift 1"
    assert e["details"]["severity"] == "High" and "noise" not in e["details"] and e["stream"] == "live"
    created = AuditEventRecorder.entry(make_event(ev.MODEL_VERSION_CREATED, "simulation", "New model",
                                                  model_version="v2.0", data={"version": "v2.0"}))
    assert created["action"] == "model.created" and created["resource_id"] == "v2.0"
    assert AuditEventRecorder.entry(make_event(ev.PREDICTION_RESULT, "live", "x")) is None
    assert AuditEventRecorder.entry(make_event(ev.SIMULATION_STATE, "simulation", "x")) is None


def test_recorder_writes_through_sink():
    rows = []

    class Sink:
        def record(self, action, **kw):
            rows.append((action, kw))
    asyncio.run(AuditEventRecorder(Sink())(make_event(ev.ADAPTATION_FAILED, "live", "failed",
                                                      model_version="v1.0", data={"step": 3})))
    assert rows[0][0] == "model.adaptation_failed" and rows[0][1]["severity"] == "critical"


def test_sql_audit_service_and_filters(tmp_path):
    pytest.importorskip("sqlalchemy")
    from app.database.database import Database
    from app.database.models import User
    from app.services import queries
    from app.services.audit import AuditService

    db = Database(f"sqlite:///{tmp_path / 'a.db'}")
    db.create_all()
    with db.transaction() as s:
        s.add(User(name="Ana", email="ana@example.com", password_hash="x", role="admin"))
    svc = AuditService(db)
    svc.record("auth.login", resource="user", resource_id=1, user_id=1, ip="10.0.0.1", details={"password": "no"})
    svc.record("drift.detected", resource="drift_event", resource_id="Drift 1", severity="critical", stream="live")
    svc.record("bad.severity", resource="x", severity="nonsense")
    with db.session() as s:
        items, total = queries.list_audit_logs(s, page=1, page_size=10, action=None, user_id=None, resource=None,
                                               severity=None, stream=None, date_from=None, date_to=None, system=None)
        assert total == 3 and items[0]["action"] == "bad.severity" and items[0]["severity"] == "info"
        login = next(i for i in items if i["action"] == "auth.login")
        assert login["actor"] == "Ana" and login["details"] == {} and login["ip_address"] == "10.0.0.1"
        crit, n = queries.list_audit_logs(s, page=1, page_size=10, action="drift.*", user_id=None, resource=None,
                                          severity="critical", stream="live", date_from=None, date_to=None, system=True)
        assert n == 1 and crit[0]["actor"] == "System"
        facets = queries.audit_facets(s)
        assert "auth.login" in facets["actions"] and facets["users"][0]["email"] == "ana@example.com"
    db.dispose()
