"""
Validation for purchase records entering the ML pipeline from outside
(CSV uploads, API clients).

`preprocessing.clean_dataset` (unchanged, used for the generated simulation
data) silently repairs problems: median-fills numbers, clips prices, drops bad
dates. That is fine for data we generated ourselves but wrong for user data,
because a silently "fixed" record can create or hide drift. This module does the
opposite: every problem is reported with its row and column, and only rows that
pass every check are returned (typed, normalised and time-ordered).
"""
from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ml import config
from ml.preprocessing import REQUIRED_COLUMNS, DatasetError

OPTIONAL_COLUMNS = ["Record_ID", "Period", "Trend"]
CUSTOMER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
MIN_DATE = pd.Timestamp("2000-01-01")

# Numeric bounds = the original prediction form's limits. Shared with the API
# schemas (backend/app/database/schemas.py) so uploads and single predictions
# accept exactly the same values. Price: greater than 0, at most 50,000.
BOUNDS = {
    "Purchase_Frequency": (1, 500),
    "Recency": (0, 730),
    "Month": (1, 12),
    "Price": (0, 50_000),
    "Discount": (0, 90),
}
INTEGER_COLUMNS = {"Purchase_Frequency", "Recency", "Month"}
CHOICES = {
    "Previous_Category": config.CATEGORIES,
    "Season": config.SEASONS,
    "Customer_Preference": config.PREFERENCES,
    "Target_Category": config.CATEGORIES,
}


@dataclass
class Issue:
    row: int | None          # CSV line number (header = line 1), None for file-level issues
    column: str | None
    value: str | None
    message: str

    def to_dict(self) -> dict:
        return {"row": self.row, "column": self.column, "value": self.value, "message": self.message}


@dataclass
class ValidationReport:
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    missing_values: dict[str, int] = field(default_factory=dict)
    column_errors: list[str] = field(default_factory=list)
    unexpected_columns: list[str] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    missing_columns: list[str] = field(default_factory=list)
    previously_uploaded: int = 0         # valid rows skipped because an earlier upload already holds them
    strict: bool = False                 # strict mode: any invalid row rejects the whole file
    decision: str | None = None          # the accept / reject sentence shown to people
    valid: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def ok(self) -> bool:
        return not self.column_errors and self.valid_rows > 0

    def to_dict(self, preview_rows: int = 10) -> dict:
        preview = self.valid.drop(columns=["Record_Hash"], errors="ignore").head(preview_rows).copy()
        if "Purchase_Date" in preview:
            preview["Purchase_Date"] = preview["Purchase_Date"].dt.strftime("%Y-%m-%d %H:%M")
        return {
            "ok": self.ok,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_rows": self.duplicate_rows,
            "previously_uploaded": self.previously_uploaded,
            "missing_values": self.missing_values,
            "column_errors": self.column_errors,
            "missing_columns": self.missing_columns,
            "unexpected_columns": self.unexpected_columns,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "strict": self.strict,
            "decision": self.decision,
            "preview": preview.replace({np.nan: None}).to_dict("records"),
        }


def read_csv_bytes(data: bytes, max_rows: int) -> pd.DataFrame:
    """Parse an uploaded CSV as text (no type guessing) so every value can be checked."""
    if not data or not data.strip():
        raise DatasetError("The file is empty.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError("The file is not valid UTF-8 text. Export the CSV as UTF-8 and try again.") from exc
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False,
                         skipinitialspace=True, nrows=max_rows + 1)
    except Exception as exc:  # noqa: BLE001 - pandas raises many parser error types
        raise DatasetError("The file could not be parsed as CSV. Check the delimiter and quoting.") from exc
    if len(df) > max_rows:
        raise DatasetError(f"The file has more than {max_rows:,} rows. Split it into smaller uploads.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype(str).str.strip() == "")


def _canonical(value: str, choices: list[str]) -> str | None:
    lookup = {c.lower(): c for c in choices}
    return lookup.get(str(value).strip().lower())


def validate_records(raw: pd.DataFrame, max_issues: int = 200,
                     now: datetime | None = None) -> ValidationReport:
    """Validate raw (string-typed) records and return a report plus the clean rows."""
    rep = ValidationReport(total_rows=int(len(raw)))
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_ts.tzinfo is not None:
        now_ts = now_ts.tz_convert("UTC").tz_localize(None)

    def add(kind: str, row: int | None, col: str | None, value, message: str) -> None:
        bucket = rep.errors if kind == "error" else rep.warnings
        if kind == "error":
            rep.error_count += 1
        else:
            rep.warning_count += 1
        if len(bucket) < max_issues:
            v = None if value is None else str(value)[:60]
            bucket.append(Issue(row, col, v, message))

    # ---- file-level checks -------------------------------------------------
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    rep.missing_columns = list(missing_cols)
    if missing_cols:
        rep.column_errors.append("Missing required columns: " + ", ".join(missing_cols))
    dupe_cols = sorted({c for c in raw.columns if list(raw.columns).count(c) > 1})
    if dupe_cols:
        rep.column_errors.append("Duplicate column names: " + ", ".join(dupe_cols))
    rep.unexpected_columns = [c for c in raw.columns if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
    for c in rep.unexpected_columns:
        add("warning", None, c, None, "Unexpected column ignored.")
    if raw.empty:
        rep.column_errors.append("The file has a header but no data rows.")
    if rep.column_errors:
        rep.invalid_rows = rep.total_rows
        return rep

    df = raw.reset_index(drop=True)
    line = pd.Series(np.arange(len(df)) + 2, index=df.index)   # CSV line numbers
    bad = pd.Series(False, index=df.index)
    out = pd.DataFrame(index=df.index)

    # ---- missing values ----------------------------------------------------
    for col in REQUIRED_COLUMNS:
        miss = _blank(df[col])
        rep.missing_values[col] = int(miss.sum())
        for i in df.index[miss]:
            add("error", int(line[i]), col, None, "Value is missing.")
        bad |= miss

    # ---- customer id -------------------------------------------------------
    cid = df["Customer_ID"].astype(str).str.strip()
    wrong = ~_blank(df["Customer_ID"]) & ~cid.str.match(CUSTOMER_ID_RE)
    for i in df.index[wrong]:
        add("error", int(line[i]), "Customer_ID", cid[i],
            "Use letters, numbers, - and _ only (up to 20 characters).")
    bad |= wrong
    out["Customer_ID"] = cid

    # ---- dates -------------------------------------------------------------
    dates = pd.to_datetime(df["Purchase_Date"].astype(str).str.strip(), errors="coerce", format="mixed")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    unparsed = ~_blank(df["Purchase_Date"]) & dates.isna()
    for i in df.index[unparsed]:
        add("error", int(line[i]), "Purchase_Date", df.at[i, "Purchase_Date"],
            "Not a valid date (expected e.g. 2024-05-17 14:30).")
    future = dates > now_ts + timedelta(days=1)
    for i in df.index[future.fillna(False)]:
        add("error", int(line[i]), "Purchase_Date", df.at[i, "Purchase_Date"], "Date is in the future.")
    too_old = dates < MIN_DATE
    for i in df.index[too_old.fillna(False)]:
        add("error", int(line[i]), "Purchase_Date", df.at[i, "Purchase_Date"], "Date is before 2000-01-01.")
    bad |= unparsed | future.fillna(False) | too_old.fillna(False)
    out["Purchase_Date"] = dates

    # ---- numeric columns ---------------------------------------------------
    for col, (lo, hi) in BOUNDS.items():
        text = df[col].astype(str).str.strip().str.replace(",", "", regex=False)
        num = pd.to_numeric(text, errors="coerce")
        present = ~_blank(df[col])
        not_num = present & num.isna()
        for i in df.index[not_num]:
            add("error", int(line[i]), col, df.at[i, col], "Must be a number.")
        not_int = present & num.notna() & (col in INTEGER_COLUMNS) & (num % 1 != 0)
        for i in df.index[not_int]:
            add("error", int(line[i]), col, df.at[i, col], "Must be a whole number.")
        too_low = (num <= lo) if col == "Price" else (num < lo)
        out_of_range = present & num.notna() & (too_low | (num > hi))
        if col == "Price":
            msg = f"Price must be greater than 0 and at most {hi:,}."
        else:
            msg = f"Must be between {lo:g} and {hi:g}."
        for i in df.index[out_of_range]:
            add("error", int(line[i]), col, df.at[i, col], msg)
        bad |= not_num | not_int | out_of_range
        out[col] = num

    # ---- categorical columns -----------------------------------------------
    for col, choices in CHOICES.items():
        canon = df[col].map(lambda v, ch=choices: _canonical(v, ch))
        invalid = ~_blank(df[col]) & canon.isna()
        for i in df.index[invalid]:
            add("error", int(line[i]), col, df.at[i, col], "Must be one of: " + ", ".join(choices) + ".")
        bad |= invalid
        out[col] = canon

    # ---- consistency warnings (kept, but reported) -------------------------
    ok_now = ~bad
    month_mismatch = ok_now & (out["Month"] != out["Purchase_Date"].dt.month)
    for i in df.index[month_mismatch]:
        add("warning", int(line[i]), "Month", df.at[i, "Month"],
            "Month does not match Purchase_Date; the Month column is used by the model.")
    expected_season = out["Month"].map(lambda m: config.MONTH_TO_SEASON.get(int(m)) if pd.notna(m) else None)
    season_mismatch = ok_now & (out["Season"] != expected_season)
    for i in df.index[season_mismatch]:
        add("warning", int(line[i]), "Season", df.at[i, "Season"],
            f"Season is unusual for this month (expected {expected_season[i]}).")

    # ---- optional display columns -----------------------------------------
    if "Period" in df.columns:
        out["Period"] = pd.to_numeric(df["Period"], errors="coerce")
    if "Trend" in df.columns:
        out["Trend"] = df["Trend"].astype(str).str.strip().str[:60]

    # ---- duplicates (among otherwise valid rows) ---------------------------
    candidates = out[~bad]
    dup = candidates.duplicated(subset=REQUIRED_COLUMNS, keep="first")
    rep.duplicate_rows = int(dup.sum())
    for i in candidates.index[dup]:
        add("warning", int(line[i]), None, None, "Duplicate of an earlier row; skipped.")

    valid = candidates[~dup].copy()
    for col in INTEGER_COLUMNS:
        valid[col] = valid[col].astype(int)
    for col in ("Price", "Discount"):
        valid[col] = valid[col].astype(float)
    if "Period" in valid.columns:
        valid["Period"] = valid["Period"].fillna(1).astype(int)
    valid["Source_Row"] = line[valid.index].astype(int)
    valid = valid.sort_values(["Purchase_Date", "Source_Row"], kind="stable").reset_index(drop=True)

    rep.errors.sort(key=lambda i: (i.row or 0))
    rep.warnings.sort(key=lambda i: (i.row or 0))
    rep.invalid_rows = int(bad.sum())
    rep.valid_rows = int(len(valid))
    rep.valid = valid
    return rep


# ============================================================================ record fingerprints & upload policy
def record_hash(values: dict) -> str:
    """Fingerprint of one labeled record (dataset column names → SHA-256 hex).

    Used to detect rows that an EARLIER upload already queued: re-uploading a file would otherwise feed the
    same purchases to the drift detector twice. Migration 0003 back-fills existing rows with this function.
    """
    d = values["Purchase_Date"]
    if hasattr(d, "to_pydatetime"):
        d = d.to_pydatetime()
    date = d.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(d, "strftime") else str(d)
    parts = [str(values["Customer_ID"]).strip(), date, values["Previous_Category"], int(values["Purchase_Frequency"]),
             int(values["Recency"]), values["Season"], int(values["Month"]), f"{float(values['Price']):.4f}",
             f"{float(values['Discount']):.4f}", values["Customer_Preference"], values["Target_Category"]]
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def add_record_hashes(rep: ValidationReport) -> list[str]:
    """Fingerprint every valid row (stored in the Record_Hash column); returns the fingerprints."""
    if rep.valid.empty:
        return []
    hashes = [record_hash(r) for r in rep.valid[REQUIRED_COLUMNS].to_dict("records")]
    rep.valid["Record_Hash"] = hashes
    return hashes


def drop_previously_uploaded(rep: ValidationReport, known: dict[str, int | None], max_issues: int = 200) -> int:
    """Skip valid rows whose fingerprint an earlier upload already stored. They are counted as duplicates and
    each one is reported as a warning with the upload that holds it. Returns how many rows were skipped."""
    if rep.valid.empty or not known or "Record_Hash" not in rep.valid:
        return 0
    mask = rep.valid["Record_Hash"].isin(set(known))
    n = int(mask.sum())
    if not n:
        return 0
    for r in rep.valid[mask].itertuples(index=False):
        rep.warning_count += 1
        if len(rep.warnings) < max_issues:
            upload = known.get(r.Record_Hash)
            rep.warnings.append(Issue(int(r.Source_Row), None, None, "Already uploaded earlier"
                                      + (f" (upload #{upload})" if upload else "") + "; skipped."))
    rep.warnings.sort(key=lambda i: (i.row or 0))
    rep.valid = rep.valid[~mask].reset_index(drop=True)
    rep.valid_rows = int(len(rep.valid))
    rep.duplicate_rows += n
    rep.previously_uploaded = n
    return n


def upload_decision(rep: ValidationReport, strict: bool = False) -> tuple[bool, str]:
    """Accept or reject an upload, with the sentence that explains why.

    Default (partial): valid rows are queued and every rejected row is listed with its reason.
    Strict: a single invalid row rejects the whole file, so a file is either used completely or not at all.
    Missing columns, an empty file or no new valid rows always reject the upload.
    """
    rep.strict = bool(strict)
    if rep.column_errors:
        accepted, text = False, "Upload rejected: " + "; ".join(rep.column_errors) + "."
    elif strict and rep.invalid_rows:
        accepted, text = False, (f"Upload rejected (strict mode): {rep.invalid_rows:,} of {rep.total_rows:,} rows are "
                                 "invalid, so no rows were queued. Fix them or upload without strict mode.")
    elif rep.valid_rows == 0 and rep.previously_uploaded and not rep.invalid_rows:
        accepted, text = False, "Upload rejected: every row was already uploaded earlier. Nothing new was queued."
    elif rep.valid_rows == 0:
        accepted, text = False, "Upload rejected: no valid rows were found. Fix the errors listed and upload again."
    else:
        accepted = True
        text = (f"Validation successful: {rep.valid_rows:,} of {rep.total_rows:,} records accepted and queued for the "
                "live stream" + (f"; {rep.invalid_rows:,} rows rejected" if rep.invalid_rows else "")
                + (f"; {rep.duplicate_rows:,} duplicates skipped" if rep.duplicate_rows else "") + ".")
    rep.decision = text
    return accepted, text


# ============================================================================ live events
# A live purchase event uses the API's field names. The rules are the CSV rules above (same bounds, same
# vocabulary, same messages), so an event and an uploaded row are judged identically before either reaches
# the model. Unlike a CSV, an event with an unexpected field is rejected (an API client can fix its payload).
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
EVENT_REQUIRED = ("previous_category", "purchase_frequency", "recency", "price", "discount", "customer_preference")
EVENT_OPTIONAL = ("event_id", "customer_id", "purchase_date", "month", "season", "actual_category")
EVENT_FIELDS = EVENT_REQUIRED + EVENT_OPTIONAL
_EVENT_NUMERIC = {"purchase_frequency": "Purchase_Frequency", "recency": "Recency", "month": "Month",
                  "price": "Price", "discount": "Discount"}
_EVENT_CHOICES = {"previous_category": "Previous_Category", "season": "Season",
                  "customer_preference": "Customer_Preference", "actual_category": "Target_Category"}
DATE_HELP = "Not a valid date (expected ISO 8601, e.g. 2026-04-10T12:00:00)."


@dataclass
class EventCheck:
    """Validation result for one live event (or one outcome). `values` holds clean values when ok."""
    values: dict
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @staticmethod
    def _out(issues: list[Issue]) -> list[dict]:
        return [{"field": i.column, "value": i.value, "message": i.message} for i in issues]

    def details(self) -> list[dict]:
        return self._out(self.errors)

    def warning_details(self) -> list[dict]:
        return self._out(self.warnings)


def _short(value) -> str | None:
    return None if value is None else str(value)[:60]


def _present(payload: dict, key: str) -> bool:
    v = payload.get(key)
    return v is not None and not (isinstance(v, str) and not v.strip())


def _parse_number(value) -> tuple[float | None, str | None]:
    if isinstance(value, bool):
        return None, "Must be a number."
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip().replace(",", ""))
        except ValueError:
            return None, "Must be a number."
    else:
        return None, "Must be a number."
    if not math.isfinite(num):
        return None, "Must be a number."
    return num, None


def _parse_date(value, now: datetime) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str):
        return None, DATE_HELP
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        return None, DATE_HELP
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    if d > now + timedelta(days=1):
        return None, "Date is in the future."
    if d.year < 2000:
        return None, "Date is before 2000-01-01."
    return d, None


def validate_event(payload, *, now: datetime | None = None) -> EventCheck:
    """Validate one live purchase event BEFORE it reaches feature processing and the model.

    Checks: JSON object, unexpected fields, required fields, numbers / whole numbers / ranges (no negative
    values, price > 0, discount 0-90 %), categories / seasons / preferences / target categories, safe ids,
    dates (parseable, not in the future, not before 2000). Month/season inconsistencies are warnings.
    """
    now = now or datetime.now(timezone.utc)
    chk = EventCheck({})
    values: dict = {}

    def err(key, value, message):
        chk.errors.append(Issue(None, key, _short(value), message))

    if not isinstance(payload, dict):
        err(None, None, "The event must be a JSON object.")
        return chk
    for key in payload:
        if key not in EVENT_FIELDS:
            err(str(key)[:60], payload[key], "Unexpected field.")
    for key in EVENT_REQUIRED:
        if not _present(payload, key):
            err(key, None, "Value is missing.")
    for key, col in _EVENT_NUMERIC.items():
        if not _present(payload, key):
            continue
        num, problem = _parse_number(payload[key])
        if problem is None and col in INTEGER_COLUMNS and num % 1 != 0:
            problem = "Must be a whole number."
        if problem is None:
            lo, hi = BOUNDS[col]
            if (num <= lo if col == "Price" else num < lo) or num > hi:
                problem = (f"Price must be greater than 0 and at most {hi:,}." if col == "Price"
                           else f"Must be between {lo:g} and {hi:g}.")
        if problem:
            err(key, payload[key], problem)
        else:
            values[key] = int(num) if col in INTEGER_COLUMNS else float(num)
    for key, col in _EVENT_CHOICES.items():
        if not _present(payload, key):
            continue
        v = payload[key]
        canon = _canonical(v, CHOICES[col]) if isinstance(v, str) else None
        if canon is None:
            err(key, v, "Must be one of: " + ", ".join(CHOICES[col]) + ".")
        else:
            values[key] = canon
    if _present(payload, "customer_id"):
        v = payload["customer_id"]
        if isinstance(v, str) and CUSTOMER_ID_RE.match(v.strip()):
            values["customer_id"] = v.strip()
        else:
            err("customer_id", v, "Use letters, numbers, - and _ only (up to 20 characters).")
    if _present(payload, "event_id"):
        v = payload["event_id"]
        if isinstance(v, str) and EVENT_ID_RE.match(v.strip()):
            values["event_id"] = v.strip()
        else:
            err("event_id", v, "Use letters, numbers, '.', '_', ':' and '-' (up to 64 characters, "
                               "starting with a letter or number).")
    date = None
    if _present(payload, "purchase_date"):
        date, problem = _parse_date(payload["purchase_date"], now)
        if problem:
            err("purchase_date", payload["purchase_date"], problem)
        else:
            values["purchase_date"] = date.isoformat()
    if chk.errors:
        return chk
    month = values.get("month")
    if month is not None and date is not None and month != date.month:
        chk.warnings.append(Issue(None, "month", str(month),
                                  "Month does not match purchase_date; the month field is used by the model."))
    effective = month if month is not None else (date or now).month
    expected = config.MONTH_TO_SEASON[effective]
    if "season" in values and values["season"] != expected:
        chk.warnings.append(Issue(None, "season", values["season"],
                                  f"Season is unusual for this month (expected {expected})."))
    chk.values = values
    return chk


def event_to_record(values: dict, now: datetime | None = None) -> tuple[dict, str | None, str | None]:
    """Clean event values → (feature record in dataset column names, actual category or None, event id or None).
    Month and season are derived from the purchase date when absent (the prediction form's rules)."""
    now = now or datetime.now(timezone.utc)
    date = datetime.fromisoformat(values["purchase_date"]) if values.get("purchase_date") else now
    month = int(values.get("month") or date.month)
    rec = {
        "Purchase_Date": date.strftime("%Y-%m-%d %H:%M"), "Previous_Category": values["previous_category"],
        "Purchase_Frequency": int(values["purchase_frequency"]), "Recency": int(values["recency"]),
        "Season": values.get("season") or config.MONTH_TO_SEASON[month], "Month": month,
        "Price": float(values["price"]), "Discount": float(values["discount"]),
        "Customer_Preference": values["customer_preference"],
    }
    if values.get("customer_id"):
        rec["Customer_ID"] = values["customer_id"]
    return rec, values.get("actual_category"), values.get("event_id")


def validate_outcome(payload) -> EventCheck:
    """One late outcome: exactly one of event_id / prediction_id, plus a valid actual_category."""
    chk = EventCheck({})

    def err(key, value, message):
        chk.errors.append(Issue(None, key, _short(value), message))

    if not isinstance(payload, dict):
        err(None, None, "Each outcome must be a JSON object.")
        return chk
    for key in payload:
        if key not in ("event_id", "prediction_id", "actual_category"):
            err(str(key)[:60], payload[key], "Unexpected field.")
    eid, pid = payload.get("event_id"), payload.get("prediction_id")
    if (eid is None) == (pid is None):
        err(None, None, "Send exactly one of event_id or prediction_id.")
    values: dict = {}
    if eid is not None:
        if isinstance(eid, str) and EVENT_ID_RE.match(eid):
            values["event_id"] = eid
        else:
            err("event_id", eid, "Not a valid event id.")
    if pid is not None:
        if isinstance(pid, int) and not isinstance(pid, bool) and pid >= 1:
            values["prediction_id"] = pid
        else:
            err("prediction_id", pid, "Must be a positive whole number.")
    actual = payload.get("actual_category")
    canon = _canonical(actual, config.CATEGORIES) if isinstance(actual, str) else None
    if canon is None:
        err("actual_category", actual, "Value is missing." if actual in (None, "") else
            "Must be one of: " + ", ".join(config.CATEGORIES) + ".")
    else:
        values["actual_category"] = canon
    if not chk.errors:
        chk.values = values
    return chk


def validation_rules() -> dict:
    """What is checked, for the Data validation page (generated from the rules themselves)."""
    lo, hi = BOUNDS["Price"]
    return {
        "csv_required_columns": list(REQUIRED_COLUMNS),
        "csv_optional_columns": list(OPTIONAL_COLUMNS),
        "event_required_fields": list(EVENT_REQUIRED),
        "event_optional_fields": list(EVENT_OPTIONAL),
        "numeric": [{"column": c, "min": a, "max": b, "integer": c in INTEGER_COLUMNS, "min_exclusive": c == "Price"}
                    for c, (a, b) in BOUNDS.items()],
        "choices": {c: list(v) for c, v in CHOICES.items()},
        "checks": [
            "Required columns (CSV) or fields (live events) are present",
            "No missing values in required fields",
            "Numbers are numbers; frequency, recency and month are whole numbers",
            f"Price is greater than {lo:g} and at most {hi:,}; no negative values; discount is 0-90 %",
            "Dates parse, are not in the future and not before 2000-01-01",
            "Previous category, season, customer preference and target category come from the fixed vocabulary",
            "Customer and event ids contain only safe characters",
            "Duplicate rows in a file and rows already uploaded earlier are skipped; a repeated event_id is refused",
            "Unexpected CSV columns are ignored with a warning; unexpected event fields reject the event",
            "Month / season consistency is checked and reported as a warning",
        ],
        "policy": {
            "csv_default": "Partial: valid rows are queued, every rejected row is listed with its reason.",
            "csv_strict": "Strict: any invalid row rejects the whole file.",
            "events": "An invalid event is rejected (422) and stored with its errors; it never reaches the model.",
        },
    }
