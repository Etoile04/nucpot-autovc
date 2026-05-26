import logging
from typing import Generator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from autovc.database import get_session_factory
from autovc.models import Potential, VerificationJob
from autovc.schemas import PotentialCreate, PotentialResponse, VerificationJobResponse, VerificationRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_session_factory = None


def _set_session_factory(factory):
    global _session_factory
    _session_factory = factory


def get_db():
    factory = _session_factory or get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/potentials", response_model=PotentialResponse, status_code=201)
def create_potential(body: PotentialCreate, db: Session = Depends(get_db)):
    if db.query(Potential).filter(Potential.name == body.name).first():
        raise HTTPException(409, f"Potential {body.name} already exists")
    pot = Potential(name=body.name, potential_type=body.potential_type, species=body.species, kim_model_id=body.kim_model_id, source_url=body.source_url, file_path=body.file_path)
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
    if not pot: raise HTTPException(404, "Not found")
    return pot

@router.post("/verification", response_model=VerificationJobResponse, status_code=202)
def submit_verification(body: VerificationRequest, db: Session = Depends(get_db)):
    pot = db.query(Potential).filter(Potential.name == body.potential_name).first()
    if not pot: raise HTTPException(404, f"Potential {body.potential_name} not found")
    job = VerificationJob(potential_id=pot.id, status="pending", properties_requested=body.properties)
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
    if not job: raise HTTPException(404, "Not found")
    return job
