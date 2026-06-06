"""Check latest MTP verification results."""
import httpx, os

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "Bearer " + key}

# Get last 10 verifications
r = httpx.get(url + "/rest/v1/verifications", headers=h, timeout=30, params={
    "select": "id,status,results,created_at",
    "order": "created_at.desc",
    "limit": "10"
})
data = r.json()

for d in data:
    res = d.get("results") or {}
    vals = []
    errs = []
    for prop, val in res.items():
        if isinstance(val, dict):
            if val.get("value") is not None:
                vals.append(f"{prop[:12]}={val['value']:.4f}({val.get('grade','?')})")
            elif val.get("error"):
                errs.append(val["error"][:80])
    s = d["status"]
    info = " | ".join(vals) if vals else "; ".join(errs[:1]) if errs else "no data"
    print(f"{d['id'][:8]} {s:10s} {info}")
