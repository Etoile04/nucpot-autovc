import logging
import uuid
from typing import Any, Generator
from fastapi import APIRouter, Depends, HTTPException, Request
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


# ── Auth Dependency (Sprint 2) ──────────────────────────────────
async def require_auth(request: Request):
    """Verify authentication via Authorization header or HttpOnly cookie.

    Token can be passed as:
      - Authorization: Bearer <token>
      - Cookie: access_token=<token>

    Returns user payload on success, raises 401 on failure.
    """
    token = request.headers.get("Authorization")
    if token and token.startswith("Bearer "):
        token = token[7:]
    else:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # TODO: validate JWT / session token against user store
    # For now, any non-empty token is accepted (placeholder for Sprint 2 wiring)
    return {"user": "authenticated", "token": token}

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
def create_potential(body: PotentialCreate, db: Session = Depends(get_db), auth=Depends(require_auth)):
    if db.query(Potential).filter(Potential.name == body.name).first():
        raise HTTPException(409, f"Potential {body.name} already exists")
    pot = Potential(
        id=str(uuid.uuid4()),
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
def get_potential(pid: str, db: Session = Depends(get_db)):
    pot = db.query(Potential).filter(Potential.id == pid).first()
    if not pot:
        raise HTTPException(404, "Not found")
    return pot


# ── Verification v1 (legacy, SQLite-backed) ───────────────────────
@router.post("/verification", response_model=VerificationJobResponse, status_code=202)
def submit_verification(body: VerificationRequest, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def submit_verification_v2(body: ParameterizedVerificationRequest, db: Session = Depends(get_db), auth=Depends(require_auth)):
    """Submit a parameterized verification using a template."""
    try:
        properties = resolve_template_properties(body.template, body.property_overrides)
    except ValueError as e:
        raise HTTPException(400, str(e))

    pot = db.query(Potential).filter(Potential.name == body.potential_name).first()
    if not pot:
        logger.info(f"Auto-creating potential: {body.potential_name}")
        pot = Potential(
            id=str(uuid.uuid4()),
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
        structure=body.structure.lower() if body.structure else "bcc",
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
    """Get a structured scoring report for a verification job.
    
    Tries local SQLite first, falls back to Supabase (async → sync via run).
    """
    # Try local DB
    try:
        job = db.query(VerificationJob).filter(VerificationJob.id == jid).first()
    except Exception:
        job = None

    if job:
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
        pot = db.query(Potential).filter(Potential.id == job.potential_id).first()
        potential_name = pot.name if pot else "unknown"
        passed = sum(1 for g in grades if g in ("A", "B"))
        summary = f"{passed}/{len(grades)} properties passed (grade A or B). Overall grade: {overall or 'N/A'}"
        return ScoreReport(
            job_id=job.id,
            potential_name=potential_name,
            overall_grade=overall,
            property_scores=property_scores,
            summary=summary,
            created_at=job.completed_at,
        )

    # Fallback: try Supabase by string UUID
    import asyncio as _aio
    record = None
    try:
        try:
            loop = _aio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    record = pool.submit(
                        _aio.run, get_supabase_verification(str(jid))
                    ).result()
            else:
                record = loop.run_until_complete(get_supabase_verification(str(jid)))
        except RuntimeError:
            record = _aio.new_event_loop().run_until_complete(get_supabase_verification(str(jid)))
    except Exception:
        record = None
    if not record:
        raise HTTPException(404, "Not found")

    # Parse Supabase results (stored as JSONB)
    results_data = record.get("results", {})
    if isinstance(results_data, str):
        import json
        results_data = json.loads(results_data)

    property_scores = []
    grades = []
    if isinstance(results_data, dict):
        for prop_name, prop_data in results_data.items():
            if isinstance(prop_data, dict):
                score_entry = {
                    "property_name": prop_name,
                    "computed_value": prop_data.get("value"),
                    "reference_value": prop_data.get("reference"),
                    "unit": prop_data.get("unit", ""),
                    "grade": prop_data.get("grade"),
                    "absolute_error": prop_data.get("absolute_error"),
                    "relative_error": prop_data.get("relative_error"),
                }
                property_scores.append(score_entry)
                if prop_data.get("grade"):
                    grades.append(prop_data["grade"])

    overall = record.get("overall_grade") or compute_overall_grade(grades)
    if not overall and grades:
        overall = compute_overall_grade(grades)

    passed = sum(1 for g in grades if g in ("A", "B"))
    total = len(grades)
    summary = record.get("summary") or f"{passed}/{total} properties passed (grade A or B). Overall grade: {overall or 'N/A'}"

    return ScoreReport(
        job_id=0,
        potential_name=record.get("potential_id", "unknown")[:12],
        overall_grade=overall,
        property_scores=property_scores,
        summary=summary,
        created_at=record.get("completed_at"),
    )



# ── Export ────────────────────────────────────────────────────────

import io

@router.get("/verification/{jid}/export")
def export_verification_report(jid: int, format: str = "json", db: Session = Depends(get_db)):
    """Export verification report as JSON or PDF.
    
    Supports both local SQLite (by numeric ID) and Supabase (by UUID string).
    """
    # Try local DB first
    try:
        job = db.query(VerificationJob).filter(VerificationJob.id == jid).first()
    except Exception:
        job = None

    if job:
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
        pot = db.query(Potential).filter(Potential.id == job.potential_id).first()
        potential_name = pot.name if pot else "unknown"
        completed_at = job.completed_at
    else:
        # Fallback to Supabase
        import asyncio as _aio
        record = None
        try:
            try:
                loop = _aio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        record = pool.submit(
                            _aio.run, get_supabase_verification(str(jid))
                        ).result()
                else:
                    record = loop.run_until_complete(get_supabase_verification(str(jid)))
            except RuntimeError:
                record = _aio.new_event_loop().run_until_complete(get_supabase_verification(str(jid)))
        except Exception:
            record = None
        if not record:
            raise HTTPException(404, f"Verification job {jid} not found")
        # Parse results
        results_data = record.get("results", {})
        if isinstance(results_data, str):
            import json
            results_data = json.loads(results_data)
        property_scores = []
        grades = []
        if isinstance(results_data, dict):
            for prop_name, prop_data in results_data.items():
                if isinstance(prop_data, dict):
                    score_entry = {
                        "property_name": prop_name,
                        "computed_value": prop_data.get("value"),
                        "reference_value": prop_data.get("reference"),
                        "unit": prop_data.get("unit", ""),
                        "grade": prop_data.get("grade"),
                        "absolute_error": prop_data.get("absolute_error"),
                        "relative_error": prop_data.get("relative_error"),
                    }
                    property_scores.append(score_entry)
                    if prop_data.get("grade"):
                        grades.append(prop_data["grade"])
        overall = record.get("overall_grade") or compute_overall_grade(grades)
        potential_name = record.get("potential_id", "unknown")[:12]
        completed_at_str = record.get("completed_at")
        from datetime import datetime as _dt
        completed_at = _dt.fromisoformat(completed_at_str.replace("Z", "+00:00")) if completed_at_str else None

    if format == "pdf":
        return _generate_pdf(jid, potential_name, overall, property_scores, grades, completed_at)
    else:
        # JSON export with full metadata
        from datetime import datetime
        report = {
            "job_id": jid,
            "potential_name": potential_name,
            "potential_id": job.potential_id if job else None,
            "overall_grade": overall,
            "property_scores": property_scores,
            "summary": f"{sum(1 for g in grades if g in ('A','B'))}/{len(grades)} passed (A/B)",
            "created_at": completed_at.isoformat() if completed_at else None,
            "exported_at": datetime.utcnow().isoformat(),
        }
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=report,
            headers={"Content-Disposition": f"attachment; filename=report_{jid}.json"},
        )


def _grade_color(grade: str | None) -> tuple:
    """Return RGB color tuple for grade."""
    colors = {
        "A": (34, 197, 94),    # green
        "B": (59, 130, 246),   # blue
        "C": (234, 179, 8),    # yellow
        "D": (249, 115, 22),   # orange
        "F": (239, 68, 68),    # red
    }
    return colors.get(grade, (156, 163, 175))  # gray for None


def _generate_pdf(jid, potential_name, overall, property_scores, grades, completed_at):
    """Generate PDF report using fpdf2."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Verification Report", ln=True, align="C")
    pdf.ln(4)

    # Metadata
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Job ID: {jid}", ln=True)
    pdf.cell(0, 6, f"Potential: {potential_name}", ln=True)
    pdf.cell(0, 6, f"Overall Grade: {overall or 'N/A'}", ln=True)
    if completed_at:
        pdf.cell(0, 6, f"Completed: {completed_at.strftime('%Y-%m-%d %H:%M UTC')}", ln=True)
    pdf.ln(6)

    # Summary
    passed = sum(1 for g in grades if g in ("A", "B"))
    total = len(grades)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Summary: {passed}/{total} properties passed (grade A or B)", ln=True)
    pdf.ln(4)

    # Property scores table
    if not property_scores:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, "No property scores available.", ln=True)
    else:
        # Table header
        col_widths = [45, 30, 30, 20, 20, 22]
        headers = ["Property", "Computed", "Reference", "Unit", "Grade", "Rel.Error"]
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(55, 65, 81)  # dark header
        pdf.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        pdf.ln()

        # Table rows
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 9)
        for idx, s in enumerate(property_scores):
            if idx % 2 == 0:
                pdf.set_fill_color(243, 244, 246)
            else:
                pdf.set_fill_color(255, 255, 255)

            row_data = [
                str(s.get("property_name", ""))[:20],
                f'{s.get("computed_value", "-"):.4f}' if isinstance(s.get("computed_value"), (int, float)) else str(s.get("computed_value", "-"))[:12],
                f'{s.get("reference_value", "-"):.4f}' if isinstance(s.get("reference_value"), (int, float)) else str(s.get("reference_value", "-"))[:12],
                str(s.get("unit", ""))[:8],
                str(s.get("grade", "-"))[:3],
                f'{s.get("relative_error", 0)*100:.1f}%' if isinstance(s.get("relative_error"), (int, float)) else "-",
            ]
            for i, val in enumerate(row_data):
                pdf.cell(col_widths[i], 6, val, border=1, fill=True, align="C")
            pdf.ln()

    # Footer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 6, "Generated by nucpot-autovc", ln=True, align="C")

    buf = io.BytesIO(pdf.output())
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{jid}.pdf"},
    )

# ══════════════════════════════════════════════════════════════════
# ── NEW: Supabase + LAMMPS Verification ───────────────────────────
# ══════════════════════════════════════════════════════════════════

import asyncio
from pydantic import BaseModel, Field
# fpdf imported lazily in _generate_pdf
from autovc.supabase_client import get_potential, create_verification, update_verification, update_potential, get_verification as get_supabase_verification


class SupabaseVerifyRequest(BaseModel):
    """Request body for Supabase+LAMMPS verification."""
    potential_id: str = Field(..., description="UUID of the potential in Supabase")
    template: str = Field(default="basic", description="Template: basic|mechanical|defect|comprehensive")
    triggered_by: str = Field(default="admin", description="Who triggered this verification")
    structure: str | None = Field(default=None, description="Crystal structure: bcc/fcc/hcp/diamond. Auto-detected if omitted.")


TEMPLATE_ESTIMATED_SECONDS = {
    "basic": 30,
    "mechanical": 120,
    "defect": 180,
    "comprehensive": 300,
}


async def _run_lammps_verification(job_id: str, potential_id: str, template: str, structure: str | None = None):
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
                    
                })
            except Exception as e:
                logger.warning(f"Progress update failed: {e}")

        runner = LAMMPSRunner(potential_meta=meta, structure=structure)
        result = await runner.run_template(template, progress_callback=progress_callback)

        await update_verification(job_id, {
            "status": "completed",
            "progress": 1.0,
            "current_step": "done",
            "results": result["results"],
            "overall_grade": result.get("overall_grade"),
        })

        # Write back verified_props to potential record
        try:
            await update_potential(potential_id, {
                "verified_props": result["results"],
            })
        except Exception as e:
            logger.warning(f"Failed to update potential verified_props: {e}")

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
async def submit_supabase_verify(body: SupabaseVerifyRequest, auth=Depends(require_auth)):
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
    asyncio.create_task(_run_lammps_verification(job_id, body.potential_id, body.template, body.structure))

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
def create_reference(body: ReferenceValueCreate, db: Session = Depends(get_db), auth=Depends(require_auth)):
    """Add a new reference value."""
    ref = ReferenceValue(id=str(uuid.uuid4()), **body.model_dump())
    db.add(ref)
    db.commit()
    db.refresh(ref)
    return ref


@router.patch("/references/{ref_id}", response_model=ReferenceValueResponse)
def update_reference(ref_id: str, body: ReferenceValueUpdate, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def delete_reference(ref_id: str, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def admin_batch_ref_values(body: AdminBatchBody, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def admin_patch_ref_value(ref_id: str, body: AdminRefValueUpdate, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def admin_approve_ref_value(ref_id: str, body: AdminApproveBody | None = None, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def admin_reject_ref_value(ref_id: str, body: AdminRejectBody | None = None, db: Session = Depends(get_db), auth=Depends(require_auth)):
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
def admin_delete_ref_value(ref_id: str, db: Session = Depends(get_db), auth=Depends(require_auth)):
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

