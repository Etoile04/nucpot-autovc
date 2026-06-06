"""Check bulk v2 verification results."""
import httpx, os, json
from datetime import datetime, timedelta

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "Bearer " + key}

# Get verifications from last 10 minutes
since = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
r = httpx.get(url + "/rest/v1/verifications", headers=h, params={
    "select": "id,status,results,created_at",
    "created_at": f"gte.{since}",
    "order": "created_at.desc",
    "limit": "30"
})
data = r.json()
if isinstance(data, dict) and "error" in data:
    print("Error:", data)
    # Try without filter
    r = httpx.get(url + "/rest/v1/verifications", headers=h, params={
        "select": "id,status,results",
        "order": "created_at.desc",
        "limit": "25"
    })
    data = r.json()

success = 0
failed = 0
pending = 0
running = 0
errors = {}

for d in data:
    if not isinstance(d, dict):
        continue
    s = d.get("status", "?")
    if s == "completed":
        res = d.get("results") or {}
        has_value = False
        for prop, val in res.items():
            if isinstance(val, dict) and val.get("value") is not None:
                has_value = True
                break
        if has_value:
            success += 1
        else:
            failed += 1
            for prop, val in res.items():
                if isinstance(val, dict) and val.get("error"):
                    err = val["error"][:120]
                    errors[err] = errors.get(err, 0) + 1
                    break
    elif s == "failed":
        failed += 1
    elif s == "running":
        running += 1
    else:
        pending += 1

print(f"Results: {success} success, {failed} failed, {running} running, {pending} pending (of {len(data)} total)")
if errors:
    print("\nError breakdown:")
    for err, cnt in sorted(errors.items(), key=lambda x: -x[1]):
        print(f"  [{cnt}x] {err}")

# Show successful ones
if success:
    print(f"\nSuccessful verifications:")
    for d in data:
        if not isinstance(d, dict):
            continue
        res = d.get("results") or {}
        for prop, val in res.items():
            if isinstance(val, dict) and val.get("value") is not None:
                print(f"  {d['id'][:8]}: {prop} = {val['value']} ({val.get('grade', '?')})")
