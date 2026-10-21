"""Data management: CSV upload with validation report, records, statistics."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ml.preprocessing import REQUIRED_COLUMNS, DatasetError
from ml.validation import (add_record_hashes, drop_previously_uploaded, read_csv_bytes, upload_decision,
                           validate_records, validation_rules)

from app.api.common import audit_async
from app.auth.dependencies import get_db, get_pipeline, require_admin, require_staff
from app.database.models import DataRecord, Upload, User
from app.database.schemas import Category, DataRecordPage, UploadPage, UploadResponse, page_meta
from app.errors import NotFoundError, PayloadTooLargeError, ValidationFailedError
from app.services import events as ev
from app.services import queries
from app.services.pipeline import PipelineService
from app.services.sql_repository import row_dict

router = APIRouter(prefix="/api/data", tags=["Data management"])
TEMPLATE_ROWS = [
    "C1001,2026-03-14 11:20,Tops,6,21,Summer,3,1499,10,Casual,Bottoms",
    "C1002,2026-03-15 18:05,Footwear,2,90,Summer,3,2899,25,Sporty,Footwear",
]


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data += chunk
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    return bytes(data)


def _store_upload(db, user_id: int, filename: str, report, accepted: bool) -> dict:
    rep = report.to_dict()
    with db.transaction() as s:
        up = Upload(user_id=user_id, filename=filename[:255], status="accepted" if accepted else "rejected",
                    total_rows=report.total_rows, valid_rows=report.valid_rows if accepted else 0,
                    invalid_rows=report.invalid_rows, duplicate_rows=report.duplicate_rows,
                    missing_values=report.missing_values, report=rep)
        s.add(up)
        s.flush()
        if accepted:
            v = report.valid
            rows = [{
                "upload_id": up.id, "user_id": user_id, "row_number": int(r.Source_Row),
                "customer_id": r.Customer_ID, "purchase_date": r.Purchase_Date.to_pydatetime(),
                "previous_category": r.Previous_Category, "purchase_frequency": int(r.Purchase_Frequency),
                "recency": int(r.Recency), "season": r.Season, "month": int(r.Month), "price": float(r.Price),
                "discount": float(r.Discount), "customer_preference": r.Customer_Preference,
                "target_category": r.Target_Category,
                "period": int(r.Period) if "Period" in v.columns else None,
                "trend": (r.Trend or None) if "Trend" in v.columns else None,
                "status": "pending", "record_hash": r.Record_Hash,
            } for r in v.itertuples(index=False)]
            for i in range(0, len(rows), 1000):
                s.execute(insert(DataRecord), rows[i:i + 1000])
        return row_dict(up)


def _skip_known_rows(db, report) -> int:
    """Rows an earlier upload already queued (same fingerprint) are skipped and reported, never queued twice."""
    hashes = add_record_hashes(report)
    known: dict[str, int] = {}
    with db.session() as s:
        for i in range(0, len(hashes), 500):
            for h, upload_id in s.execute(select(DataRecord.record_hash, DataRecord.upload_id)
                                          .where(DataRecord.record_hash.in_(hashes[i:i + 500]))).all():
                known.setdefault(h, upload_id)
    return drop_previously_uploaded(report, known)


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED,
             summary="Upload labeled purchase records (CSV) for the live stream (admin)")
async def upload(request: Request, file: UploadFile = File(..., description="UTF-8 CSV with the dataset columns"),
                 strict: bool = Query(False, description="Reject the whole file if any row is invalid"),
                 admin: User = Depends(require_admin), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    """Validates every row (columns, types, missing values, categories, duplicates, prices, discounts,
    dates) BEFORE anything reaches the ML pipeline. Rows an earlier upload already queued are skipped.
    Default: valid rows are queued for the live stream and every rejected row is listed with its reason.
    `strict=true`: one invalid row rejects the whole file. Rejected uploads return 422 with the full report.
    Process queued rows with `POST /api/drift/process`."""
    settings = request.app.state.settings
    name = (file.filename or "upload.csv").replace("\\", "/").split("/")[-1]
    if not name.lower().endswith(".csv"):
        raise ValidationFailedError("Only .csv files are accepted.")
    data = await _read_limited(file, settings.max_upload_bytes)
    try:
        raw = await asyncio.to_thread(read_csv_bytes, data, settings.max_upload_rows)
    except DatasetError as exc:
        raise ValidationFailedError(str(exc)) from exc
    report = await asyncio.to_thread(validate_records, raw)
    if not report.column_errors:
        await asyncio.to_thread(_skip_known_rows, request.app.state.db, report)
    accepted, decision = upload_decision(report, strict)
    up = await asyncio.to_thread(_store_upload, request.app.state.db, admin.id, name, report, accepted)
    rep = report.to_dict()
    await audit_async(request, "data.uploaded" if accepted else "data.upload_rejected", user=admin,
                      resource="upload", resource_id=up["id"], stream="live",
                      severity="info" if accepted else "warning",
                      details={"filename": name, "total_rows": report.total_rows, "valid_rows": report.valid_rows,
                               "invalid_rows": report.invalid_rows, "duplicate_rows": report.duplicate_rows,
                               "previously_uploaded": report.previously_uploaded, "strict": strict})
    if not accepted:
        raise ValidationFailedError(decision, details={"upload_id": up["id"], "report": rep})
    message = decision
    pipeline.notify(ev.DATA_UPLOADED, "live", message, audience="staff",
                    data={"upload_id": up["id"], "valid_rows": report.valid_rows,
                          "invalid_rows": report.invalid_rows, "filename": name})
    up.pop("report", None)
    return {"upload": up, "report": rep, "message": message}


@router.get("", response_model=DataRecordPage, summary="Uploaded records")
def list_records(db: Session = Depends(get_db), _: User = Depends(require_staff),
                 status_: str | None = Query(None, alias="status", pattern="^(pending|processed)$"),
                 upload_id: int | None = None, category: Category | None = None,
                 search: str | None = Query(None, max_length=40),
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    items, total = queries.list_records(db, page=page, page_size=page_size, status=status_, upload_id=upload_id,
                                        category=category, search=search)
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/statistics", summary="Record counts, category mix, validation totals")
def statistics(db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    return queries.data_statistics(db)


@router.get("/uploads", response_model=UploadPage, summary="Upload history")
def list_uploads(db: Session = Depends(get_db), _: User = Depends(require_staff),
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    items, total = queries.list_uploads(db, page, page_size)
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/uploads/{upload_id}", summary="One upload with its full validation report")
def get_upload(upload_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    up = queries.get_upload(db, upload_id)
    if up is None:
        raise NotFoundError("Upload not found.")
    return up


@router.get("/validation", summary="Data validation: rules, CSV and live-event acceptance, recent rejections")
def validation_summary(db: Session = Depends(get_db), _: User = Depends(require_staff)) -> dict:
    channels = queries.data_channel_counts(db)
    stats = queries.data_statistics(db)
    uploads, _total = queries.list_uploads(db, 1, 8)
    rejections, rejected_total = queries.list_rejections(db, page=1, page_size=10)
    return {
        "rules": validation_rules(),
        "csv": {**stats["uploads"], "uploads_rejected": channels["uploads_rejected"],
                "uploads_accepted": stats["uploads"]["count"] - channels["uploads_rejected"],
                "records_pending": stats["records"]["pending"], "records_processed": stats["records"]["processed"]},
        "live": {"accepted": channels["live_events"], "rejected": rejected_total,
                 "rejection_rate": channels["event_rejection_rate"], "last_rejection_at": channels["last_rejection_at"]},
        "recent_uploads": uploads, "recent_rejections": rejections,
        "top_rejection_reasons": queries.rejection_reasons(db),
    }


@router.get("/template", summary="CSV template with the required columns")
def template(_: User = Depends(require_staff)) -> Response:
    body = ",".join(REQUIRED_COLUMNS) + "\n" + "\n".join(TEMPLATE_ROWS) + "\n"
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="driftwear_template.csv"'})
