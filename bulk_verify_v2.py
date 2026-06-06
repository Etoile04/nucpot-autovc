"""Bulk submit verifications for all potentials with files."""
import httpx, os, json, sys, time

API = "http://localhost:8002"
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}

# Get all potentials with file_url
r = httpx.get(f"{SUPABASE_URL}/rest/v1/potentials", headers=h, params={
    "select": "id,name,type,file_url"
})
potentials = [p for p in r.json() if p.get("file_url")]

print(f"Found {len(potentials)} potentials with file_url")

results = []
for p in potentials:
    try:
        r = httpx.post(f"{API}/api/verify", json={
            "potential_id": p["id"],
            "template": "basic",
            "triggered_by": "bulk_v2"
        }, timeout=10)
        data = r.json()
        job_id = data.get("job_id", "???")
        status = data.get("status", "???")
        est = data.get("estimated_seconds", "?")
        results.append((p["name"], job_id, status))
        print(f"  {p['name']}: job={job_id[:8]} status={status} est={est}s")
    except Exception as e:
        print(f"  {p['name']}: ERROR {e}")
        results.append((p["name"], "FAILED", str(e)))

print(f"\nSubmitted {len(results)} verification jobs")

# Save job IDs for later checking
with open("/tmp/bulk_jobs.json", "w") as f:
    json.dump([{"name": n, "job_id": j} for n, j, s in results if j != "FAILED"], f)
