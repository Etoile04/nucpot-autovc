import logging
from typing import Any, Generator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from autovc.database import get_session_factory as _default_session_factory
from autovc.models import Potential, VerificationJob
from autovc.schemas import (
    PotentialCreate,
    PotentialResponse,
    VerificationJobResponse,
    VerificationRequest,
    ParameterizedVerificationRequest,
    TemplateResponse,
    ScoreReport,
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


# ── Verification v1 ────────────────────────────────────────────────
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


# ── Verification v2 (Phase 2: parameterized) ──────────────────────
@router.post("/verification/v2", response_model=VerificationJobResponse, status_code=202)
def submit_verification_v2(body: ParameterizedVerificationRequest, db: Session = Depends(get_db)):
    """Submit a parameterized verification using a template."""
    # Validate template
    try:
        properties = resolve_template_properties(body.template, body.property_overrides)
    except ValueError as e:
        raise HTTPException(400, str(e))

    pot = db.query(Potential).filter(Potential.name == body.potential_name).first()
    if not pot:
        raise HTTPException(404, f"Potential {body.potential_name} not found")

    job = VerificationJob(
        potential_id=pot.id,
        status="pending",
        properties_requested=properties,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Store parameter overrides as job metadata (if model supports it)
    # For now, pass via Celery kwargs
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

    # Build property scores from job results
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
