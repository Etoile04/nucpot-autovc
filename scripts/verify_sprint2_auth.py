#!/usr/bin/env python3
"""
Sprint 2 手动验证脚本 — 对实际运行的 FastAPI 服务做冒烟测试。

用法:
  python scripts/verify_sprint2_auth.py           # 默认 http://localhost:8002
  python scripts/verify_sprint2_auth.py http://localhost:8000
"""
import sys
import urllib.request
import urllib.error
import json

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8002"
results = {"pass": 0, "fail": 0, "skip": 0}
details = []


def req(method, path, body=None, headers=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def check(label, expected, actual_status, extra=""):
    status, body = actual_status
    if isinstance(expected, int):
        ok = status == expected
    elif isinstance(expected, tuple):
        ok = status in expected
    if ok:
        results["pass"] += 1
        details.append(f"  ✅ {label} → {status}")
    else:
        results["fail"] += 1
        details.append(f"  ❌ {label} → {status} (expected {expected}) {extra}")
        if body:
            details.append(f"      body: {body}")


def section(title):
    details.append(f"\n── {title} ─{'─' * max(0, 60 - len(title))}")


# ════════════════════════════════════════════════════════════

section("1. 健康检查（无 auth）")
check("GET /api/health", 200, req("GET", "/api/health"))

section("2. 读端点（应公开）")
check("GET /api/templates", 200, req("GET", "/api/templates"))
check("GET /api/templates/basic", 200, req("GET", "/api/templates/basic"))
check("GET /api/potentials", 200, req("GET", "/api/potentials"))
check("GET /api/references", 200, req("GET", "/api/references"))

section("3. 写端点 — 无 auth（应返回 401）")
check("POST /api/potentials (无 auth)", 401,
      req("POST", "/api/potentials",
          {"name": "test", "potential_type": "EAM", "species": ["U"]}))
check("POST /api/verification (无 auth)", 401,
      req("POST", "/api/verification",
          {"potential_name": "test", "properties": ["lattice_constant"]}))
check("POST /api/verification/v2 (无 auth)", 401,
      req("POST", "/api/verification/v2",
          {"potential_name": "test", "template": "basic"}))
check("POST /api/verify (无 auth)", 401,
      req("POST", "/api/verify",
          {"potential_id": "00000000-0000-0000-0000-000000000000",
           "template": "basic"}))
check("POST /api/references (无 auth)", 401,
      req("POST", "/api/references",
          {"element_system": "Mo", "property": "bm", "value": 250.0}))
check("PATCH /api/references/x (无 auth)", 401,
      req("PATCH", "/api/references/x", {"value": 3.5}))
check("DELETE /api/references/x (无 auth)", 401,
      req("DELETE", "/api/references/x"))
check("POST /api/admin/reference-values/batch (无 auth)", 401,
      req("POST", "/api/admin/reference-values/batch",
          {"ids": [], "action": "approve"}))
check("PATCH /api/admin/reference-values/x (无 auth)", 401,
      req("PATCH", "/api/admin/reference-values/x", {}))
check("POST /api/admin/.../approve (无 auth)", 401,
      req("POST", "/api/admin/reference-values/x/approve", {}))
check("POST /api/admin/.../reject (无 auth)", 401,
      req("POST", "/api/admin/reference-values/x/reject", {}))
check("DELETE /api/admin/reference-values/x (无 auth)", 401,
      req("DELETE", "/api/admin/reference-values/x"))

section("4. 写端点 — 带无效 token（应返回 401）")
h = {"Authorization": "Bearer invalid_token"}
check("POST /api/potentials (bad token)", 401,
      req("POST", "/api/potentials",
          {"name": "test", "potential_type": "EAM", "species": ["U"]}, headers=h))

section("5. 写端点 — 带有效 auth（应 2xx）")
h = {"Authorization": "Bearer <VALID_TOKEN>"}
# 替换为实际有效 token 后取消注释
details.append("  ⏭️  需要有效 token 后才能测试 — 手动步骤见下方")

section("6. 豁免端点")
check("POST /api/verify-callback (无 auth)", (200, 404, 422),
      req("POST", "/api/verify-callback", {"status": "test"}))

# ════════════════════════════════════════════════════════════

print("=" * 65)
print(f"Sprint 2 验证报告 — {BASE_URL}")
print("=" * 65)
for d in details:
    print(d)
print("\n" + "=" * 65)
print(f"  通过: {results['pass']}  |  失败: {results['fail']}  |  跳过: {results['skip']}")
print("=" * 65)

if results["fail"] > 0:
    sys.exit(1)
