"""Upload policy on top of the CSV validator: missing columns, invalid values, strict mode, re-uploaded rows."""
from datetime import datetime

import pandas as pd

from ml import config
from ml.validation import (add_record_hashes, drop_previously_uploaded, read_csv_bytes, record_hash, upload_decision,
                           validate_records, validation_rules)

HEADER = ("Customer_ID,Purchase_Date,Previous_Category,Purchase_Frequency,Recency,Season,Month,Price,Discount,"
          "Customer_Preference,Target_Category")
ROWS = ("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Casual,Bottoms",
        "C2,2024-03-02 11:00,Tops,3,10,Summer,3,900,10,Casual,Dresses")


def _report(*rows, header=HEADER):
    return validate_records(read_csv_bytes((header + "\n" + "\n".join(rows) + "\n").encode(), 1000))


def test_missing_column_rejects_the_upload_and_names_it():
    rep = _report("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Bottoms",
                  header=HEADER.replace(",Customer_Preference", ""))
    accepted, msg = upload_decision(rep)
    assert not accepted and msg.startswith("Upload rejected") and "Customer_Preference" in msg
    assert rep.missing_columns == ["Customer_Preference"] and rep.to_dict()["missing_columns"] == ["Customer_Preference"]
    assert rep.to_dict()["decision"] == msg


def test_invalid_values_are_reported_and_partial_vs_strict():
    rep = _report("C1,2024-03-02 10:00,Tops,3,10,XYZ,3,1200,10,Casual,Bottoms",
                  "C2,2024-03-02 11:00,Tops,3,10,Summer,3,-500,10,Casual,Bottoms",
                  "C3,2024-03-02 12:00,Tops,3,10,Summer,3,900,10,Casual,Dresses")
    assert {("Season", "XYZ"), ("Price", "-500")} <= {(e.column, e.value) for e in rep.errors}
    accepted, msg = upload_decision(rep)
    assert accepted and msg.startswith("Validation successful: 1 of 3 records accepted") and "2 rows rejected" in msg
    accepted, msg = upload_decision(rep, strict=True)
    assert not accepted and "strict mode" in msg and rep.strict and rep.to_dict()["strict"] is True


def test_shipped_dataset_validates_successfully():
    rep = validate_records(read_csv_bytes(config.DATASET_PATH.read_bytes(), 50_000))
    accepted, msg = upload_decision(rep, strict=True)
    assert accepted and msg.startswith("Validation successful: 2,100 of 2,100 records accepted")


def test_record_hash_is_stable_and_sensitive():
    base = {"Customer_ID": "C1", "Purchase_Date": datetime(2024, 3, 2, 10, 0), "Previous_Category": "Tops",
            "Purchase_Frequency": 3, "Recency": 10, "Season": "Summer", "Month": 3, "Price": 1200, "Discount": 10,
            "Customer_Preference": "Casual", "Target_Category": "Bottoms"}
    same = {**base, "Price": 1200.0, "Purchase_Date": pd.Timestamp("2024-03-02 10:00")}
    assert record_hash(base) == record_hash(same) and len(record_hash(base)) == 64
    assert record_hash(base) != record_hash({**base, "Target_Category": "Tops"})


def test_rows_uploaded_earlier_are_skipped_not_queued_twice():
    hashes = add_record_hashes(_report(*ROWS))
    again = _report(*ROWS)
    add_record_hashes(again)
    assert drop_previously_uploaded(again, {h: 4 for h in hashes}) == 2
    assert (again.valid_rows, again.duplicate_rows, again.previously_uploaded) == (0, 2, 2)
    assert "upload #4" in again.warnings[0].message
    accepted, msg = upload_decision(again)
    assert not accepted and "already uploaded" in msg
    partial = _report(*ROWS, "C3,2024-03-02 12:00,Tops,3,10,Summer,3,700,10,Casual,Tops")
    add_record_hashes(partial)
    drop_previously_uploaded(partial, {hashes[0]: 4})
    assert partial.valid_rows == 2 and upload_decision(partial)[0]
    assert "Record_Hash" not in partial.to_dict()["preview"][0]


def test_rules_summary_is_generated_from_the_rules():
    r = validation_rules()
    assert "Customer_Preference" in r["csv_required_columns"] and r["choices"]["Season"] == config.SEASONS
    price = next(n for n in r["numeric"] if n["column"] == "Price")
    assert price["min_exclusive"] and price["max"] == 50_000 and "price" in r["event_required_fields"]
