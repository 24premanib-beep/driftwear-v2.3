"""Per-prediction explanation (ml/explain.py): exact, folded back to the input fields, deterministic."""
import pytest

from ml.explain import explain_prediction
from ml.feature_engineering import RAW_FEATURES, record_to_frame
from ml.model import predict_record, train_model
from ml.simulation import SimulationFeed
from ml.stream_engine import DriftEngine


@pytest.fixture(scope="module")
def trained():
    feed = SimulationFeed.from_seed()
    return train_model(feed.training_rows()), feed


def test_contributions_add_up_to_the_reported_confidence(trained):
    model, feed = trained
    for _ in range(15):
        rec, _ = feed.next_record()
        X = record_to_frame(rec)
        predicted, confidence, _ = predict_record(model, X)
        e = explain_prediction(model, X)
        assert e["predicted"] == predicted
        assert abs(e["probability"] - confidence) < 1e-4
        total = e["base_value"] + sum(c["contribution"] for c in e["contributions"])
        assert abs(total - confidence) < 1e-3          # exact decomposition (rounding only)


def test_one_entry_per_input_field_with_shares(trained):
    model, feed = trained
    rec, _ = feed.next_record()
    e = explain_prediction(model, record_to_frame(rec))
    assert sorted(c["feature"] for c in e["contributions"]) == sorted(RAW_FEATURES)
    assert abs(sum(c["share"] for c in e["contributions"]) - 1) < 0.01
    sizes = [abs(c["contribution"]) for c in e["contributions"]]
    assert sizes == sorted(sizes, reverse=True)
    assert all(c["direction"] in ("supports", "opposes") for c in e["contributions"])
    assert explain_prediction(model, record_to_frame(rec)) == e        # deterministic


def test_engine_explains_only_on_request(trained):
    _, feed = trained
    eng, _ = DriftEngine.bootstrap("live", feed.training_rows())
    rec, _ = feed.next_record()
    assert eng.predict(rec).explanation is None
    p = eng.predict(rec, explain=True)
    assert p.explanation["predicted"] == p.predicted and abs(p.explanation["probability"] - p.confidence) < 1e-4
