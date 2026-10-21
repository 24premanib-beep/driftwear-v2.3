"""CSV upload validation (ml/validation.py)."""
import pytest

from ml import config
from ml.preprocessing import DatasetError
from ml.validation import read_csv_bytes, validate_records

HEADER = ("Customer_ID,Purchase_Date,Previous_Category,Purchase_Frequency,Recency,Season,Month,Price,Discount,"
          "Customer_Preference,Target_Category")


def _report(*rows: str, header: str = HEADER):
    return validate_records(read_csv_bytes((header + "\n" + "\n".join(rows) + "\n").encode(), 1000))


def test_shipped_dataset_is_valid():
    rep = validate_records(read_csv_bytes(config.DATASET_PATH.read_bytes(), 50_000))
    assert (rep.valid_rows, rep.invalid_rows, rep.duplicate_rows, rep.error_count) == (2100, 0, 0, 0)


def test_valid_rows_are_typed_normalised_and_time_ordered():
    rep = _report("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Casual,Bottoms",
                  "C2,2024-03-01 09:00,tops,2,5,summer,3,800,0,casual,dresses")
    assert rep.ok and rep.valid_rows == 2
    first = rep.valid.iloc[0]
    assert first["Customer_ID"] == "C2" and first["Previous_Category"] == "Tops" and first["Season"] == "Summer"
    assert first["Target_Category"] == "Dresses" and first["Month"] == 3 and first["Source_Row"] == 3


@pytest.mark.parametrize("row,column,fragment", [
    ("C1,2024-03-02,Shoes,3,10,Summer,3,1200,10,Casual,Tops", "Previous_Category", "Must be one of"),
    ("C1,2024-03-02,Tops,3,10,Summer,3,0,10,Casual,Tops", "Price", "greater than 0"),
    ("C1,2024-03-02,Tops,3,10,Summer,3,-5,10,Casual,Tops", "Price", "greater than 0"),
    ("C1,2024-03-02,Tops,3,10,Summer,3,1200,95,Casual,Tops", "Discount", "between 0 and 90"),
    ("C1,2024-13-40,Tops,3,10,Summer,3,1200,10,Casual,Tops", "Purchase_Date", "Not a valid date"),
    ("C1,2099-01-01,Tops,3,10,Summer,3,1200,10,Casual,Tops", "Purchase_Date", "future"),
    ("C1,2024-03-02,Tops,2.5,10,Summer,3,1200,10,Casual,Tops", "Purchase_Frequency", "whole number"),
    ("C1,2024-03-02,Tops,3,abc,Summer,3,1200,10,Casual,Tops", "Recency", "number"),
    ("C1,2024-03-02,Tops,3,10,Summer,13,1200,10,Casual,Tops", "Month", "between 1 and 12"),
    ("C1,2024-03-02,Tops,3,10,Spring,3,1200,10,Casual,Tops", "Season", "Must be one of"),
    ("C1,2024-03-02,Tops,3,10,Summer,3,1200,10,Casual,", "Target_Category", "missing"),
    ("bad id!,2024-03-02,Tops,3,10,Summer,3,1200,10,Casual,Tops", "Customer_ID", "letters"),
])
def test_invalid_values_are_reported_with_row_and_column(row, column, fragment):
    rep = _report(row)
    assert rep.valid_rows == 0 and rep.invalid_rows == 1 and not rep.ok
    hits = [e for e in rep.errors if e.column == column]
    assert hits and fragment.lower() in hits[0].message.lower() and hits[0].row == 2


def test_duplicates_missing_values_and_warnings():
    rep = _report("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Casual,Bottoms",
                  "C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Casual,Bottoms",
                  ",2024-03-02,Tops,3,10,Summer,3,1200,10,Casual,Bottoms",
                  "C5,2024-07-01,Tops,4,3,Winter,6,1000,10,Formal,Tops")
    assert rep.duplicate_rows == 1 and rep.missing_values["Customer_ID"] == 1
    assert rep.valid_rows == 2 and rep.invalid_rows == 1
    messages = " ".join(w.message for w in rep.warnings)
    assert "Duplicate" in messages and "does not match" in messages and "unusual" in messages


def test_file_level_problems():
    rep = _report("1,2", header="a,b")
    assert rep.column_errors and "Missing required columns" in rep.column_errors[0] and not rep.ok
    rep = _report("C1,2024-03-02,Tops,3,10,Summer,3,1200,10,Casual,Tops,x", header=HEADER + ",Extra")
    assert rep.ok and rep.unexpected_columns == ["Extra"]
    with pytest.raises(DatasetError):
        read_csv_bytes(b"", 10)
    with pytest.raises(DatasetError):
        read_csv_bytes("Customer_ID\n\xff\xfe".encode("latin-1"), 10)
    with pytest.raises(DatasetError, match="more than"):
        read_csv_bytes((HEADER + "\n" + "C1,2024-03-02,Tops,3,10,Summer,3,1200,10,Casual,Tops\n" * 6).encode(), 5)


def test_report_serialises():
    d = _report("C1,2024-03-02 10:00,Tops,3,10,Summer,3,1200,10,Casual,Bottoms").to_dict()
    assert d["ok"] and d["preview"][0]["Purchase_Date"] == "2024-03-02 10:00"
