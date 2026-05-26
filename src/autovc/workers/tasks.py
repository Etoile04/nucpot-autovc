import logging
from datetime import datetime, timezone
from autovc.core.grading import grade_property
from autovc.core.properties import PropertyCalculator
from autovc.database import get_session_factory
from autovc.models import VerificationJob, VerificationResult
from autovc.reference.data import get_reference_value

logger = logging.getLogger(__name__)

def _execute_verification(job_id: int, session) -> None:
    job = session.query(VerificationJob).filter(VerificationJob.id == job_id).first()
    if not job:
        logger.error(f"Job {job_id} not found")
        return
    job.status = "running"
    session.commit()
    calc = PropertyCalculator()
    potential = job.potential
    species = potential.species[0] if potential.species else "U"
    structure = "BCC"
    model_id = potential.kim_model_id or potential.name
    for prop_name in job.properties_requested:
        try:
            compute_fn = {
                "lattice_constant": calc.compute_lattice_constant,
                "cohesive_energy": calc.compute_cohesive_energy,
                "elastic_constants": calc.compute_elastic_constants,
            }.get(prop_name)
            if not compute_fn:
                continue
            result_data = compute_fn(kim_model=model_id, species=species, structure=structure)
            if isinstance(result_data.get("value"), dict):
                for sub_key, sub_val in result_data["value"].items():
                    if sub_val is None: continue
                    ref = get_reference_value(species, structure, f"elastic_constants_{sub_key}")
                    ref_val = ref["value"] if ref else None
                    grade = grade_property(sub_val, ref_val) if ref_val else None
                    r = VerificationResult(job_id=job.id, property_name=f"{prop_name}_{sub_key}", computed_value=sub_val, reference_value=ref_val, unit=result_data["unit"], grade=grade)
                    if ref_val:
                        r.absolute_error = abs(sub_val - ref_val)
                        r.relative_error = abs(sub_val - ref_val) / abs(ref_val)
                    session.add(r)
            else:
                computed = result_data["value"]
                ref = get_reference_value(species, structure, prop_name)
                ref_val = ref["value"] if ref else None
                grade = grade_property(computed, ref_val) if ref_val else None
                r = VerificationResult(job_id=job.id, property_name=prop_name, computed_value=computed, reference_value=ref_val, unit=result_data["unit"], grade=grade)
                if ref_val is not None:
                    r.absolute_error = abs(computed - ref_val)
                    r.relative_error = abs(computed - ref_val) / abs(ref_val) if ref_val != 0 else None
                session.add(r)
        except Exception as e:
            logger.error(f"Property {prop_name} failed for job {job_id}: {e}")
            session.add(VerificationResult(job_id=job.id, property_name=prop_name, computed_value=0.0, unit="unknown", details={"error": str(e)}))
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
