from datetime import datetime, timezone
from sqlalchemy import Float, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from autovc.database import Base

class Potential(Base):
    __tablename__ = "potentials"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    potential_type: Mapped[str] = mapped_column(String(32), nullable=False)
    species: Mapped[list] = mapped_column(JSON, nullable=False)
    kim_model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    jobs: Mapped[list["VerificationJob"]] = relationship(back_populates="potential")

class VerificationJob(Base):
    __tablename__ = "verification_jobs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    potential_id: Mapped[int] = mapped_column(ForeignKey("potentials.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    properties_requested: Mapped[list] = mapped_column(JSON, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    potential: Mapped["Potential"] = relationship(back_populates="jobs")
    results: Mapped[list["VerificationResult"]] = relationship(back_populates="job")

class VerificationResult(Base):
    __tablename__ = "verification_results"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("verification_jobs.id"), nullable=False)
    property_name: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_value: Mapped[float] = mapped_column(Float, nullable=False)
    reference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job: Mapped["VerificationJob"] = relationship(back_populates="results")
