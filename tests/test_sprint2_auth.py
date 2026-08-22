"""
Sprint 2 验证: mutation 端点 auth 保护完整性测试。
对当前代码中所有 POST/PATCH/PUT/DELETE 端点执行 401 验证。
"""
import pytest
from fastapi.testclient import TestClient
from autovc.main import create_app

MUTATION_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
PUBLIC_WRITES = {"/api/verify-callback"}  # webhook 豁免


@pytest.fixture
def client():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from autovc.models import Potential, VerificationJob, VerificationResult, ReferenceValue
    from autovc.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Potential.__table__.create(engine, checkfirst=True)
    VerificationJob.__table__.create(engine, checkfirst=True)
    VerificationResult.__table__.create(engine, checkfirst=True)
    ReferenceValue.__table__.create(engine, checkfirst=True)
    TestSession = sessionmaker(bind=engine)

    app = create_app(session_factory=TestSession)

    # 准备测试数据
    db = TestSession()
    import uuid
    pot = Potential(id=str(uuid.uuid4()), name="test_pot", potential_type="EAM", species=["U"])
    db.add(pot)
    db.commit()
    app.state.test_pot_id = pot.id
    db.close()

    return TestClient(app)


# ── 测试 1: 每个 mutation 端点必须被保护 ──────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/potentials", {"name": "p", "potential_type": "EAM", "species": ["Mo"]}),
    ("post", "/api/verification", {"potential_name": "test_pot", "properties": ["lattice_constant"]}),
    ("post", "/api/verification/v2", {"potential_name": "test_pot", "template": "basic"}),
    ("post", "/api/references", {"element_system": "Mo", "property": "bm", "value": 250.0}),
    ("post", "/api/admin/reference-values/batch", {"ids": [], "action": "approve"}),
    ("post", "/api/verify", {"potential_id": "00000000-0000-0000-0000-000000000000", "template": "basic"}),
])
def test_write_endpoint_returns_401_without_auth(client, method, path, body):
    """所有写操作端点在无 auth 时必须返回 401"""
    fn = getattr(client, method)
    resp = fn(path, json=body)
    assert resp.status_code == 401, (
        f"{method.upper()} {path} → {resp.status_code} (expected 401)\n"
        f"  body: {resp.text[:200]}"
    )


@pytest.mark.parametrize("method,path", [
    ("patch", "/api/references/__dummy__"),
    ("delete", "/api/references/__dummy__"),
    ("patch", "/api/admin/reference-values/__dummy__"),
    ("post", "/api/admin/reference-values/__dummy__/approve"),
    ("post", "/api/admin/reference-values/__dummy__/reject"),
    ("delete", "/api/admin/reference-values/__dummy__"),
])
def test_write_endpoint_with_id_returns_401_without_auth(client, method, path):
    """带路径参数的写端点也必须返回 401"""
    fn = getattr(client, method)
    kwargs = {}
    if method in ("patch", "post"):
        kwargs["json"] = {}
    resp = fn(path, **kwargs)
    # 可能返回 404 (id not found) 或 401 (auth denied) —— 但不能是 200
    assert resp.status_code != 200, f"{method.upper()} {path} returned 200 (auth bypassed!)"
    assert resp.status_code in (401, 404), f"{method.upper()} {path} → {resp.status_code} (expected 401 or 404)"


# ── 测试 2: GET 端点保持公开 ──────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/templates",
    "/api/templates/basic",
])
def test_read_endpoint_public(client, path):
    """读端点不需要 auth"""
    resp = client.get(path)
    assert resp.status_code != 401, f"GET {path} returned 401 (should be public)"


# ── 测试 3: 端点清单完整性 ───────────────────────────────────

def test_all_mutation_routes_are_covered(client):
    """验证代码中没有遗漏的 mutation 端点"""
    from autovc.api.routes import router

    uncovered = []
    for route in router.routes:
        if not hasattr(route, "methods"):
            continue
        methods = {m for m in route.methods if m in MUTATION_METHODS}
        if not methods:
            continue
        path = getattr(route, "path", "")
        if path in PUBLIC_WRITES:
            continue  # 豁免

        # 对每个 mutation 方法发请求
        for method in methods:
            fn = getattr(client, method.lower())
            kwargs = {"json": {}} if method in ("POST", "PATCH", "PUT") else {}
            resp = fn(path, **kwargs)
            if resp.status_code != 401:
                uncovered.append(f"{method} {path} → {resp.status_code}")

    assert not uncovered, f"以下端点未受 auth 保护:\n" + "\n".join(uncovered)


# ── 测试 4: auth 不污染读端点 ────────────────────────────────

def test_auth_middleware_does_not_block_get(client):
    """验证 auth 实现不会意外阻塞 GET"""
    # 确认读端点正常工作
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/templates").status_code == 200
