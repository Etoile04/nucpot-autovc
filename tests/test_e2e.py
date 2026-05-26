import sys
sys.path.insert(0, "src")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import autovc.models  # noqa: F401
from autovc.database import Base
from autovc.main import create_app
from fastapi.testclient import TestClient

# StaticPool ensures all connections share the same in-memory SQLite
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)

app = create_app(session_factory=TestSession)
client = TestClient(app)

# 1. Health
r = client.get("/api/health")
print("1. Health:", r.status_code, r.json())
assert r.status_code == 200

# 2. Create potential
r = client.post("/api/potentials", json={
    "name": "EAM_U_Mo_Smirnov2014",
    "potential_type": "EAM",
    "species": ["U", "Mo"],
    "kim_model_id": "EAM_Dynamo_Smirnov2014"
})
d = r.json()
print("2. Create potential:", r.status_code, d.get("name"), "id=" + str(d.get("id")))
assert r.status_code == 201
pot_id = d["id"]

# 3. List potentials
r = client.get("/api/potentials")
print("3. List potentials:", r.status_code, "count=" + str(len(r.json())))
assert r.status_code == 200 and len(r.json()) >= 1

# 4. Get single potential
r = client.get("/api/potentials/" + str(pot_id))
d = r.json()
print("4. Get potential:", r.status_code, "species=" + str(d.get("species")))
assert r.status_code == 200

# 5. Submit verification
r = client.post("/api/verification", json={
    "potential_name": "EAM_U_Mo_Smirnov2014",
    "properties": ["lattice_constant", "cohesive_energy"]
})
d = r.json()
print("5. Submit verification:", r.status_code, "status=" + d.get("status"), "id=" + str(d.get("id")))
assert r.status_code == 202
job_id = d["id"]

# 6. Check verification status
r = client.get("/api/verification/" + str(job_id))
d = r.json()
print("6. Verification status:", r.status_code, "status=" + d.get("status"))
assert r.status_code == 200

# 7. Grading engine
from autovc.core.grading import grade_property, compute_overall_grade
ref_val = 3.47
grade = grade_property(3.50, ref_val)
print("7. Grading: computed=3.50 ref=3.47 grade=" + grade)
assert grade in ("A", "B", "C", "D", "F")

# 8. Overall grade
overall = compute_overall_grade(["A", "A", "B", "C"])
print("8. Overall grade:", overall)
assert overall == "C"

# 9. Reference data
from autovc.reference.data import get_reference_value, list_available_materials, list_available_properties
mats = list_available_materials()
props = list_available_properties()
print("9. Reference:", len(mats), "materials,", len(props), "properties")
print("   Materials:", mats)
assert "U" in mats
assert "U-Mo" in mats

print()
print("=== ALL 9 E2E STEPS PASSED ===")
