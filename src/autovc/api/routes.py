import logging
import uuid
from typing import Any, Generator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from autovc.database import get_session_factory as _default_session_factory
from autovc.models import Potential, VerificationJob, ReferenceValue
from autovc.schemas import (
    PotentialCreate,
    PotentialResponse,
    VerificationJobResponse,
    VerificationRequest,
    ParameterizedVerificationRequest,
    TemplateResponse,
    ScoreReport,
    ReferenceValueResponse,
    AdminRefValueUpdate,
    AdminApproveBody,
    AdminRejectBody,
    AdminBatchBody,
)
from autovc.core.templates import get_template, list_templates, resolve_template_properties
from autovc.core.grading import compute_overall_grade

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_session_factory = None


def _set_session_factory(factory):
    global _session_factory
    _session_factory = factory


def _get_factory():
    if _session_factory is not None:
        return _session_factory
    return _default_session_factory()


def get_db():
    Session = _get_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()


# ── Health ──────────────────────────────────────────────────────────
@router.get("/health")
def health():
    return {"status": "ok"}


# ── Templates (Phase 2) ────────────────────────────────────────────
@router.get("/templates", response_model=list[TemplateResponse])
def get_templates():
    """List all available verification templates."""
    return list_templates()


@router.get("/templates/{template_id}", response_model=TemplateResponse)
def get_template_detail(template_id: str):
    """Get details of a specific template."""
    tmpl = get_template(template_id)
    if not tmpl:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return {"id": template_id, **tmpl}


# ── Potentials ──────────────────────────────────────────────────────
@router.post("/potentials", response_model=PotentialResponse, status_code=201)
def create_potential(body: PotentialCreate, db: Session = Depends(get_db)):
    if db.query(Potential).filter(Potential.name == body.name).first():
        raise HTTPException(409, f"Potential {body.name} already exists")
    pot = Potential(
        name=body.name,
        potential_type=body.potential_type,
        species=body.species,
        kim_model_id=body.kim_model_id,
        source_url=body.source_url,
        file_path=body.file_path,
    )
    db.add(pot)
    db.commit()
    db.refresh(pot)
    return pot


@router.get("/potentials", response_model=list[PotentialResponse])
def list_potentials(db: Session = Depends(get_db)):
    return db.query(Potential).all()


@router.get("/potentials/{pid}", response_model=PotentialResponse)
def get_potential(pid: int, db: Session = Depends(get_db)):
    pot = db.query(Potential).filter(Potential.id == pid).first()
    if not pot:
        raise HTTPException(404, "Not found")
    return pot


# ── Verification v1 (legacy, SQLite-backed) ───────────────────────
@router.post("/verification", response_model=VerificationJobResponse, status_code=202)
def submit_verification(body: VerificationRequest, db: Session = Depends(get_db)):
    pot = db.query(Potential).filter(Potential.name == body.potential_name).first()
    if not pot:
        raise HTTPException(404, f"Potential {body.potential_name} not found")
    job = VerificationJob(
        potential_id=pot.id, status="pending", properties_requested=body.properties
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        from autovc.workers.tasks import run_verification
        task = run_verification.delay(job.id)
        job.celery_task_id = task.id
        db.commit()
    except Exception as e:
        logger.warning(f"Celery dispatch failed: {e}")
    return job


@router.get("/verification/{jid}", response_model=VerificationJobResponse)
def get_verification(jid: int, db: Session = Depends(get_db)):
    job = db.query(VerificationJob).filter(VerificationJob.id == jid).first()
    if not job:
        raise HTTPException(404, "Not found")
    return job


# ── Verification v2 (Phase 2: parameterized, legacy SQLite) ──────
@router.post("/verification/v2", response_model=VerificationJobResponse, status_code=202)
def submit_verification_v2(body: ParameterizedVerificationRequest, db: Session = Depends(get_db)):
    """Submit a parameterized verification using a template."""
    try:
        properties = resolve_template_properties(body.template, body.property_overrides)
    except ValueError as e:
        raise HTTPException(400, str(e))

    pot = db.query(Potential).filter(Potential.name == body.potential_name).first()
    if not pot:
        logger.info(f"Auto-creating potential: {body.potential_name}")
        pot = Potential(
            name=body.potential_name,
            potential_type="unknown",
            species=body.species if hasattr(body, 'species') and body.species else [],
            kim_model_id=body.kim_model_id if hasattr(body, 'kim_model_id') else None,
        )
        db.add(pot)
        db.commit()
        db.refresh(pot)

    job = VerificationJob(
        potential_id=pot.id,
        status="pending",
        properties_requested=properties,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        from autovc.workers.tasks import run_verification
        task_kwargs = {"parameter_overrides": body.parameter_overrides} if body.parameter_overrides else {}
        task = run_verification.delay(job.id, **task_kwargs)
        job.celery_task_id = task.id
        db.commit()
    except Exception as e:
        logger.warning(f"Celery dispatch failed: {e}")

    return job


# ── Verification Report (Phase 2) ─────────────────────────────────
@router.get("/verification/{jid}/report", response_model=ScoreReport)
def get_verification_report(jid: int, db: Session = Depends(get_db)):
    """Get a structured scoring report for a verification job."""
    job = db.query(VerificationJob).filter(VerificationJob.id == jid).first()
    if not job:
        raise HTTPException(404, "Not found")

    property_scores = []
    grades = []
    for result in job.results:
        score_entry = {
            "property_name": result.property_name,
            "computed_value": result.computed_value,
            "reference_value": result.reference_value,
            "unit": result.unit,
            "grade": result.grade,
            "absolute_error": result.absolute_error,
            "relative_error": result.relative_error,
        }
        property_scores.append(score_entry)
        if result.grade:
            grades.append(result.grade)

    overall = compute_overall_grade(grades)

    passed = sum(1 for g in grades if g in ("A", "B"))
    total = len(grades)
    summary = f"{passed}/{total} properties passed (grade A or B). Overall grade: {overall or 'N/A'}"

    pot = db.query(Potential).filter(Potential.id == job.potential_id).first()
    potential_name = pot.name if pot else "unknown"

    return ScoreReport(
        job_id=job.id,
        potential_name=potential_name,
        overall_grade=overall,
        property_scores=property_scores,
        summary=summary,
        created_at=job.completed_at,
    )


# ══════════════════════════════════════════════════════════════════
# ── NEW: Supabase + LAMMPS Verification ───────────────────────────
# ══════════════════════════════════════════════════════════════════

import asyncio
from pydantic import BaseModel, Field
from autovc.supabase_client import get_potential, create_verification, update_verification, get_verification as get_supabase_verification


class SupabaseVerifyRequest(BaseModel):
    """Request body for Supabase+LAMMPS verification."""
    potential_id: str = Field(..., description="UUID of the potential in Supabase")
    template: str = Field(default="basic", description="Template: basic|mechanical|defect|comprehensive")
    triggered_by: str = Field(default="admin", description="Who triggered this verification")


TEMPLATE_ESTIMATED_SECONDS = {
    "basic": 30,
    "mechanical": 120,
    "defect": 180,
    "comprehensive": 300,
}


async def _run_lammps_verification(job_id: str, potential_id: str, template: str):
    """Background task: run LAMMPS verification and update Supabase."""
    try:
        from autovc.runners.lammps_runner import LAMMPSRunner

        meta = await get_potential(potential_id)

        async def progress_callback(progress: float, step: str, partial_results: dict = None):
            try:
                await update_verification(job_id, {
                    "progress": progress,
                    "current_step": step,
                    "status": "running",
                    "partial_results": partial_results or {},
                })
            except Exception as e:
                logger.warning(f"Progress update failed: {e}")

        runner = LAMMPSRunner(potential_meta=meta)
        result = await runner.run_template(template, progress_callback=progress_callback)

        await update_verification(job_id, {
            "status": "completed",
            "progress": 1.0,
            "current_step": "done",
            "results": result["results"],
            "overall_grade": result.get("overall_grade"),
        })

    except Exception as e:
        logger.error(f"LAMMPS verification failed for job {job_id}: {e}")
        try:
            await update_verification(job_id, {
                "status": "failed",
                "error_log": str(e),
                "current_step": "failed",
            })
        except Exception:
            pass


@router.post("/verify")
async def submit_supabase_verify(body: SupabaseVerifyRequest):
    """Submit a verification job using Supabase + LAMMPS backend.

    1. Fetch potential metadata from Supabase
    2. Create verification record (status=pending)
    3. Start async LAMMPS computation
    4. Return job info
    """
    from autovc.config import get_settings
    settings = get_settings()

    if not settings.SUPABASE_URL:
        raise HTTPException(500, "SUPABASE_URL not configured")

    # Validate template
    if body.template not in TEMPLATE_ESTIMATED_SECONDS:
        raise HTTPException(400, f"Invalid template: {body.template}. Use basic|mechanical|defect|comprehensive")

    # Check potential exists
    try:
        meta = await get_potential(body.potential_id)
    except ValueError:
        raise HTTPException(404, f"Potential {body.potential_id} not found in Supabase")
    except Exception as e:
        raise HTTPException(500, f"Supabase error: {e}")

    # Create verification record
    job_id = str(uuid.uuid4())
    record = {
        "id": job_id,
        "potential_id": body.potential_id,
        "template": body.template,
        "status": "pending",
        "progress": 0.0,
        "current_step": "queued",
        "triggered_by": body.triggered_by,
        "results": [],
        "overall_grade": None,
        "error_log": None,
    }

    try:
        await create_verification(record)
    except Exception as e:
        raise HTTPException(500, f"Failed to create verification record: {e}")

    # Start background LAMMPS task
    estimated = TEMPLATE_ESTIMATED_SECONDS.get(body.template, 120)
    asyncio.create_task(_run_lammps_verification(job_id, body.potential_id, body.template))

    return {
        "job_id": job_id,
        "status": "pending",
        "estimated_seconds": estimated,
    }


@router.get("/verify/{job_id}")
async def get_supabase_verify_status(job_id: str):
    """Get verification job status and results from Supabase."""
    try:
        record = await get_supabase_verification(job_id)
    except Exception as e:
        raise HTTPException(500, f"Supabase error: {e}")

    if not record:
        raise HTTPException(404, f"Verification job {job_id} not found")

    return {
        "job_id": record.get("id"),
        "status": record.get("status"),
        "progress": record.get("progress", 0.0),
        "current_step": record.get("current_step", ""),
        "estimated_remaining_seconds": None,
        "results": record.get("results", {}),
        "overall_grade": record.get("overall_grade"),
        "error_message": record.get("error_message"),
        "template": record.get("template"),
        "created_at": record.get("created_at"),
    }


# ── Reference Values ───────────────────────────────────────────────
from autovc.models import ReferenceValue
from autovc.schemas import (
    ReferenceValueResponse,
    ReferenceValueCreate,
    ReferenceValueUpdate,
)


@router.get("/references", response_model=list[ReferenceValueResponse])
def list_references(
    element_system: str | None = None,
    phase: str | None = None,
    property: str | None = None,
    db: Session = Depends(get_db),
):
    """List reference values with optional filters."""
    q = db.query(ReferenceValue)
    if element_system:
        q = q.filter(ReferenceValue.element_system == element_system)
    if phase:
        q = q.filter(ReferenceValue.phase == phase)
    if property:
        q = q.filter(ReferenceValue.property == property)
    return q.all()


@router.get("/references/{ref_id}", response_model=ReferenceValueResponse)
def get_reference(ref_id: str, db: Session = Depends(get_db)):
    """Get a single reference value by ID."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    return ref


@router.post("/references", response_model=ReferenceValueResponse, status_code=201)
def create_reference(body: ReferenceValueCreate, db: Session = Depends(get_db)):
    """Add a new reference value."""
    ref = ReferenceValue(id=str(uuid.uuid4()), **body.model_dump())
    db.add(ref)
    db.commit()
    db.refresh(ref)
    return ref


@router.patch("/references/{ref_id}", response_model=ReferenceValueResponse)
def update_reference(ref_id: str, body: ReferenceValueUpdate, db: Session = Depends(get_db)):
    """Update a reference value."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ref, k, v)
    db.commit()
    db.refresh(ref)
    return ref


@router.delete("/references/{ref_id}", status_code=204)
def delete_reference(ref_id: str, db: Session = Depends(get_db)):
    """Delete a reference value."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    db.delete(ref)
    db.commit()


# ── Admin Reference Value Routes ──────────────────────────────────
from datetime import datetime, timezone as _tz
from sqlalchemy import text as sa_text, func as sa_func

# Audit helper
def _audit_ref(db: Session, ref_id: str, action: str, old_data: dict | None, new_data: dict | None, reason: str | None = None, performed_by: str = "admin"):
    import json as _json
    db.execute(sa_text(
        "INSERT INTO reference_value_audit (id, reference_value_id, action, old_data, new_data, reason, performed_by) "
        "VALUES (gen_random_uuid(), :rid, :act, CAST(:oldj AS jsonb), CAST(:newj AS jsonb), :reason, :by)"
    ), {"rid": ref_id, "act": action, "oldj": _json.dumps(old_data, default=str), "newj": _json.dumps(new_data, default=str), "reason": reason, "by": performed_by})


def _ref_to_dict(ref) -> dict:
    """Convert ReferenceValue ORM object to dict."""
    return {
        "id": str(ref.id), "element_system": ref.element_system, "phase": ref.phase,
        "property": ref.property, "value": ref.value, "unit": ref.unit,
        "uncertainty": ref.uncertainty, "temperature": ref.temperature,
        "pressure": ref.pressure, "source": ref.source, "source_doi": ref.source_doi,
        "method": ref.method, "created_at": ref.created_at.isoformat() if ref.created_at else None,
        "updated_at": ref.updated_at.isoformat() if ref.updated_at else None,
        "confidence": ref.confidence, "needs_review": ref.needs_review,
        "cache_level": ref.cache_level, "status": ref.status, "review_notes": ref.review_notes,
    }


@router.get("/admin/reference-values")
def admin_list_ref_values(
    needs_review: bool | None = None,
    confidence: str | None = None,
    element_system: str | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List reference values with admin filters."""
    q = db.query(ReferenceValue)
    if needs_review is not None:
        q = q.filter(ReferenceValue.needs_review == needs_review)
    if confidence:
        q = q.filter(ReferenceValue.confidence == confidence)
    if element_system:
        q = q.filter(ReferenceValue.element_system == element_system)
    if status:
        q = q.filter(ReferenceValue.status == status)
    total = q.count()
    refs = q.order_by(ReferenceValue.element_system, ReferenceValue.property).offset((page - 1) * limit).limit(limit).all()
    return {"data": [ReferenceValueResponse.model_validate(r).model_dump() for r in refs], "total": total, "page": page, "limit": limit}


@router.post("/admin/reference-values/batch")
def admin_batch_ref_values(body: AdminBatchBody, db: Session = Depends(get_db)):
    """Batch approve or reject reference values."""
    results = []
    for rid in body.ids:
        ref = db.query(ReferenceValue).filter(ReferenceValue.id == rid).first()
        if not ref:
            results.append({"id": rid, "status": "not_found"})
            continue
        old = _ref_to_dict(ref)
        if body.action == "approve":
            ref.needs_review = False
            ref.status = "active"
            if body.confidence:
                ref.confidence = body.confidence
        elif body.action == "reject":
            ref.status = "rejected"
        ref.updated_at = datetime.now(_tz.utc)
        db.flush()
        new = _ref_to_dict(ref)
        _audit_ref(db, rid, body.action, old, new, reason=body.reason)
        results.append({"id": rid, "status": "ok"})
    db.commit()
    return {"results": results, "total": len(body.ids), "processed": len([r for r in results if r["status"] == "ok"])}


@router.get("/admin/reference-values/matrix")
def admin_ref_matrix(db: Session = Depends(get_db)):
    """Get reference values in matrix format for heatmap display."""
    refs = db.query(ReferenceValue).filter(ReferenceValue.status != "deleted").order_by(ReferenceValue.element_system, ReferenceValue.phase).all()
    systems: dict[tuple, dict] = {}
    for ref in refs:
        key = (ref.element_system, ref.phase or "")
        if key not in systems:
            systems[key] = {"element_system": ref.element_system, "phase": ref.phase, "properties": {}}
        systems[key]["properties"][ref.property] = {
            "value": ref.value, "unit": ref.unit,
            "confidence": ref.confidence, "needs_review": ref.needs_review,
            "status": ref.status,
        }
    return {"systems": list(systems.values())}

@router.get("/admin/reference-values/{ref_id}")
def admin_get_ref_value(ref_id: str, db: Session = Depends(get_db)):
    """Get a single reference value by ID."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    return ReferenceValueResponse.model_validate(ref).model_dump()


@router.patch("/admin/reference-values/{ref_id}")
def admin_patch_ref_value(ref_id: str, body: AdminRefValueUpdate, db: Session = Depends(get_db)):
    """Update a reference value with audit logging."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    old = _ref_to_dict(ref)
    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(ref, k, v)
    ref.updated_at = datetime.now(_tz.utc)
    db.flush()
    new = _ref_to_dict(ref)
    _audit_ref(db, ref_id, "update", old, new)
    db.commit()
    db.refresh(ref)
    return ReferenceValueResponse.model_validate(ref).model_dump()


@router.post("/admin/reference-values/{ref_id}/approve")
def admin_approve_ref_value(ref_id: str, body: AdminApproveBody | None = None, db: Session = Depends(get_db)):
    """Approve a reference value."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    old = _ref_to_dict(ref)
    ref.needs_review = False
    ref.status = "active"
    if body:
        if body.confidence:
            ref.confidence = body.confidence
        if body.review_notes:
            ref.review_notes = body.review_notes
    ref.updated_at = datetime.now(_tz.utc)
    db.flush()
    new = _ref_to_dict(ref)
    _audit_ref(db, ref_id, "approve", old, new)
    db.commit()
    db.refresh(ref)
    return ReferenceValueResponse.model_validate(ref).model_dump()


@router.post("/admin/reference-values/{ref_id}/reject")
def admin_reject_ref_value(ref_id: str, body: AdminRejectBody | None = None, db: Session = Depends(get_db)):
    """Reject a reference value."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    old = _ref_to_dict(ref)
    ref.status = "rejected"
    ref.updated_at = datetime.now(_tz.utc)
    db.flush()
    new = _ref_to_dict(ref)
    _audit_ref(db, ref_id, "reject", old, new, reason=body.reason if body else None)
    db.commit()
    db.refresh(ref)
    return ReferenceValueResponse.model_validate(ref).model_dump()


@router.delete("/admin/reference-values/{ref_id}")
def admin_delete_ref_value(ref_id: str, db: Session = Depends(get_db)):
    """Soft-delete a reference value."""
    ref = db.query(ReferenceValue).filter(ReferenceValue.id == ref_id).first()
    if not ref:
        raise HTTPException(404, "Reference value not found")
    old = _ref_to_dict(ref)
    ref.status = "deleted"
    ref.updated_at = datetime.now(_tz.utc)
    db.flush()
    new = _ref_to_dict(ref)
    _audit_ref(db, ref_id, "delete", old, new)
    db.commit()
    return {"status": "deleted", "id": ref_id}

