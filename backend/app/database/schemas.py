"""
Pydantic v2 schemas: request validation and response shapes (also what Swagger shows).

Allowed categories, seasons and preferences come from ml/config.py and numeric
bounds from ml/validation.py, so the API, CSV uploads and the model always
agree on what a valid record is.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from ml import config as ml
from ml.validation import BOUNDS, CUSTOMER_ID_RE

Category = Literal[tuple(ml.CATEGORIES)]          # type: ignore[valid-type]
Season = Literal[tuple(ml.SEASONS)]               # type: ignore[valid-type]
Preference = Literal[tuple(ml.PREFERENCES)]       # type: ignore[valid-type]
Role = Literal["user", "analyst", "admin"]
Stream = Literal["live", "simulation"]
Detector = Literal["DDM", "ADWIN", "PageHinkley"]
Severity = Literal["info", "warning", "critical"]
EVENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
MIN_ROLLBACK_REASON = 3          # characters; a rollback must say why (activation history + audit log)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================================================================ auth / users
class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Name must have at least 2 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(_Out):
    id: int
    name: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


# ============================================================================ predictions
class PredictionInput(BaseModel):
    """One purchase. Month and Season are derived from purchase_date unless given."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "customer_id": "C1042", "previous_category": "Tops", "purchase_frequency": 6, "recency": 21,
        "purchase_date": "2026-04-10T12:00:00", "price": 1499, "discount": 10,
        "customer_preference": "Casual"}})

    customer_id: str | None = Field(None, max_length=20, description="Letters, numbers, - and _")
    previous_category: Category
    purchase_frequency: int = Field(ge=BOUNDS["Purchase_Frequency"][0], le=BOUNDS["Purchase_Frequency"][1])
    recency: int = Field(ge=BOUNDS["Recency"][0], le=BOUNDS["Recency"][1], description="Days since last order")
    purchase_date: datetime | None = Field(None, description="Defaults to now")
    month: int | None = Field(None, ge=1, le=12, description="Defaults to purchase_date's month")
    season: Season | None = Field(None, description="Defaults to the season for the month")
    price: float = Field(gt=BOUNDS["Price"][0], le=BOUNDS["Price"][1])
    discount: float = Field(ge=BOUNDS["Discount"][0], le=BOUNDS["Discount"][1], description="Percent")
    customer_preference: Preference
    actual_category: Category | None = Field(
        None, description="Optional: the real category, if already known. Feeds the drift detector.")

    @field_validator("customer_id")
    @classmethod
    def _cid(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not CUSTOMER_ID_RE.match(v):
            raise ValueError("Customer ID may contain letters, numbers, - and _ only")
        return v

    @model_validator(mode="after")
    def _derive_time(self) -> "PredictionInput":
        now = datetime.now(timezone.utc)
        date = self.purchase_date or now
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        if date > now + timedelta(days=1):
            raise ValueError("purchase_date cannot be in the future")
        if date.year < 2000:
            raise ValueError("purchase_date must be after 2000-01-01")
        self.purchase_date = date
        if self.month is None:
            self.month = date.month
        if self.season is None:
            self.season = ml.MONTH_TO_SEASON[self.month]
        return self

    def to_record(self) -> dict[str, Any]:
        """The feature record in the dataset's column names (what the ML engine expects)."""
        rec = {
            "Purchase_Date": self.purchase_date.strftime("%Y-%m-%d %H:%M"),
            "Previous_Category": self.previous_category, "Purchase_Frequency": int(self.purchase_frequency),
            "Recency": int(self.recency), "Season": self.season, "Month": int(self.month),
            "Price": float(self.price), "Discount": float(self.discount),
            "Customer_Preference": self.customer_preference,
        }
        if self.customer_id:
            rec["Customer_ID"] = self.customer_id
        return rec


class OutcomeInput(BaseModel):
    actual_category: Category


class ContributionOut(BaseModel):
    feature: str
    label: str
    value: Any = None
    contribution: float = Field(description="Change in the predicted class's probability credited to this field")
    share: float = Field(description="This field's part of the total absolute contribution (0-1)")
    direction: Literal["supports", "opposes"]


class ExplanationOut(BaseModel):
    method: str
    predicted: str
    probability: float
    base_value: float = Field(description="Average probability of this class before looking at the inputs")
    contributions: list[ContributionOut]


class PredictionOut(_Out):
    id: int
    stream: Stream
    source: str
    user_id: int | None
    customer_id: str | None
    features: dict[str, Any]
    predicted_category: str
    confidence: float
    probabilities: dict[str, float]
    baseline_prediction: str
    model_version: str
    status_at_prediction: str
    actual_category: str | None
    is_correct: bool | None
    step: int | None
    detector_status: str | None
    scored_version: str | None
    rescored: bool
    created_at: datetime
    outcome_at: datetime | None
    event_id: str | None = None
    explanation: ExplanationOut | None = None


class OutcomeOut(BaseModel):
    prediction_id: int
    step: int
    actual_category: str
    predicted_category: str
    is_correct: bool
    scored_version: str
    rescored: bool
    status: str
    previous_status: str
    rolling_accuracy: float
    drift_detected: bool
    drift_event_id: int | None
    new_model_version: str | None
    adaptation_error: str | None


class PredictResponse(BaseModel):
    prediction: PredictionOut
    outcome: OutcomeOut | None = None
    explanation: ExplanationOut | None = None
    drift_status: str
    message: str


# ============================================================================ real-time events
class PurchaseEvent(PredictionInput):
    """A purchase event from a producer system (shop backend, POS, message consumer).

    Same fields and validation as a prediction. `event_id` makes ingestion idempotent: sending
    the same event twice returns 409 instead of predicting (and counting) it twice.
    """
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "event_id": "evt-2026-06-14-000123", "customer_id": "C1023", "previous_category": "Tops",
        "purchase_frequency": 4, "recency": 12, "season": "Summer", "month": 6, "price": 1299, "discount": 20,
        "customer_preference": "Casual"}})

    event_id: str | None = Field(None, max_length=64, pattern=EVENT_ID_PATTERN,
                                 description="Producer's unique id for this event (letters, numbers, . _ : -)")


class EventOutcomeInput(BaseModel):
    """The actual category for an earlier event, identified by event_id or prediction_id."""
    model_config = ConfigDict(extra="forbid")
    event_id: str | None = Field(None, max_length=64, pattern=EVENT_ID_PATTERN)
    prediction_id: int | None = Field(None, ge=1)
    actual_category: Category

    @model_validator(mode="after")
    def _one_id(self) -> "EventOutcomeInput":
        if (self.event_id is None) == (self.prediction_id is None):
            raise ValueError("Send exactly one of event_id or prediction_id")
        return self


class PipelineStage(BaseModel):
    stage: str
    status: Literal["done", "pending", "skipped", "failed"]
    detail: str


class EventOutcomeResponse(BaseModel):
    event_id: str | None
    prediction_id: int
    outcome: OutcomeOut
    pipeline: list[PipelineStage]
    message: str


class ValidationIssueOut(BaseModel):
    field: str | None = None
    value: str | None = None
    message: str


class EventValidationOut(BaseModel):
    passed: bool = True
    warnings: list[ValidationIssueOut] = Field(default_factory=list)


class EventIngestResponse(BaseModel):
    event_id: str | None
    prediction: PredictionOut
    explanation: ExplanationOut | None = None
    outcome: OutcomeOut | None = None
    drift_status: str
    validation: EventValidationOut | None = None
    received_at: datetime | None = None
    pipeline: list[PipelineStage]
    message: str


# ============================================================================ audit log
class AuditUserOut(BaseModel):
    id: int
    name: str | None
    email: str | None


class AuditLogOut(BaseModel):
    id: int
    created_at: datetime
    user_id: int | None
    user: AuditUserOut | None
    actor: str
    action: str
    resource: str
    resource_id: str | None
    severity: Severity
    stream: str | None
    ip_address: str | None
    details: dict[str, Any] | None


class Page(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


class PredictionPage(Page):
    items: list[PredictionOut]


# ============================================================================ drift / models
class DriftEventOut(_Out):
    id: int
    stream: Stream
    event_key: str
    detector: str
    status: str
    action: str
    error_rate: float | None
    stream_step: int
    change_point_step: int | None
    detection_delay: int | None
    window_size: int | None
    window_start: int | None
    accuracy_stable: float | None
    accuracy_degraded: float | None
    accuracy_after: float | None
    previous_model_version: str
    new_model_version: str | None
    details: dict[str, Any] | None
    detected_at: datetime | str | None
    severity: Literal["High", "Medium", "Low"] | None = None


class ProcessRequest(BaseModel):
    stream: Stream = "live"
    count: int = Field(10, ge=1, le=500, description="Records to process")
    stop_on_drift: bool = Field(True, description="Simulation only: stop the batch at the first drift")


class DetectorRequest(BaseModel):
    stream: Stream = "live"
    detector: Detector


class ModelVersionOut(_Out):
    id: int
    stream: Stream
    version: str
    parent_version: str | None
    kind: str
    model_type: str
    trigger: str
    detector: str
    accuracy: float | None = Field(description="Out-of-fold validation accuracy on the training window")
    precision: float | None
    recall: float | None
    f1_score: float | None
    train_accuracy: float | None
    training_records: int
    window_start: int | None
    window_end: int | None
    change_point_step: int | None
    created_step: int
    accuracy_before: float | None
    accuracy_after: float | None
    data_period: str | None
    model_size: int
    checksum: str
    is_active: bool
    drift_event_id: int | None
    created_at: datetime | str | None


class AdaptRequest(BaseModel):
    stream: Stream = "live"


class ActivateRequest(BaseModel):
    stream: Stream = "live"
    reason: str | None = Field(None, max_length=500, description="Why (stored in the activation history)")


class RollbackRequest(BaseModel):
    """Restore an OLDER model version. Nothing is deleted; the current version stays in the registry.
    A reason is required: it is stored in the activation history and the audit log."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "stream": "live", "to_version": "v2.0", "reason": "v3.0 misclassifies Outerwear since the festive sale"}})
    stream: Stream = "live"
    to_version: str = Field(pattern=r"^v\d{1,4}\.\d{1,4}$")
    reason: str = Field(min_length=MIN_ROLLBACK_REASON, max_length=500,
                        description="Why the rollback is needed (required; stored in the history and audit log)")

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < MIN_ROLLBACK_REASON:
            raise ValueError(f"Give a reason of at least {MIN_ROLLBACK_REASON} characters for the rollback.")
        return value


# ============================================================================ data
class UploadOut(_Out):
    id: int
    user_id: int | None
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    missing_values: dict[str, int] | None
    created_at: datetime


class UploadResponse(BaseModel):
    upload: UploadOut | None
    report: dict[str, Any]
    message: str


class DataRecordOut(_Out):
    id: int
    upload_id: int
    row_number: int
    customer_id: str
    purchase_date: datetime
    previous_category: str
    purchase_frequency: int
    recency: int
    season: str
    month: int
    price: float
    discount: float
    customer_preference: str
    target_category: str
    status: str
    prediction_id: int | None
    created_at: datetime


class DataRecordPage(Page):
    items: list[DataRecordOut]


class UploadPage(Page):
    items: list[UploadOut]


class AuditLogPage(Page):
    items: list[AuditLogOut]


# ============================================================================ simulation
class SimulationStartRequest(BaseModel):
    speed: int = Field(5, ge=1, le=50, description="Records per tick (1 tick ≈ 1 s)")
    pause_on_drift: bool = True


class SimulationStepRequest(BaseModel):
    count: int = Field(10, ge=1, le=500)
    stop_on_drift: bool = True


class SimulationResetRequest(BaseModel):
    regenerate: bool = Field(False, description="Generate a new synthetic dataset")
    seed: int | None = Field(None, ge=1, le=999_999)


def page_meta(total: int, page: int, page_size: int) -> dict:
    return {"total": total, "page": page, "page_size": page_size, "pages": max(1, -(-total // page_size))}
