"""Bulk submit ALL verifications v4 - after EAM download."""
import httpx, os, json

API = "http://localhost:8002"
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "***" + key}

r = httpx.get(url + "/rest/v1/potentials", headers=h, timeout=30, params={
    "select": "id,name,type,file_url"
})
potentials = [p for p in r.json() if p.get("file_url")]
print(f"Found {len(potentials)} potentials with file_url")

# Group by type
by_type = {}
for p in potentials:
    t = p.get("type", "?")
    by_type.setdefault(t, []).append(p["name"])

for t, names in sorted(by_type.items()):
    print(f"  {t}: {len(names)}")

results = []
for p in potentials:
    name = p["name"]
    try:
        r2 = httpx.post(f"{API}/api/verify", json={
            "potential_id": p["id"],
            "template": "basic",
            "triggered_by": "v4_full"
        }, timeout=15)
        data = r2.json()
        job_id = data.get("job_id", "???")
        results.append({"name": name, "job_id": job_id, "status": "submitted"})
        print(f"  OK {name}")
    except Exception as e:
        results.append({"name": name, "error": str(e)})
        print(f"  ERR {name}: {e}")

with open("/tmp/bulk_v4.json", "w") as f:
    json.dump(results, f)
print(f"\nSubmitted {sum(1 for r in results if r.get('job_id'))} / {len(results)}")
