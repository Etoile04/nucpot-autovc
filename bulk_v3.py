"""Bulk submit verifications v3 (with box/relax fix)."""
import httpx, os, json

API = "http://localhost:8002"
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "Bearer " + key}

r = httpx.get(url + "/rest/v1/potentials", headers=h, timeout=30, params={
    "select": "id,name,type,file_url"
})
potentials = [p for p in r.json() if p.get("file_url")]
print(f"Found {len(potentials)} potentials with file_url")

results = []
for p in potentials:
    name = p["name"]
    try:
        r2 = httpx.post(f"{API}/api/verify", json={
            "potential_id": p["id"],
            "template": "basic",
            "triggered_by": "boxrelax_bulk"
        }, timeout=10)
        data = r2.json()
        job_id = data.get("job_id", "???")
        print(f"  {name}: {job_id[:8]}")
        results.append({"name": name, "job_id": job_id})
    except Exception as e:
        print(f"  {name}: ERROR {e}")

with open("/tmp/bulk_jobs_v3.json", "w") as f:
    json.dump(results, f)
print(f"\nSubmitted {len(results)} jobs")
