"""Fix MTP pair_style: mlp -> mtp in Supabase potentials."""
import httpx, os

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "Bearer " + key,
     "Content-Type": "application/json", "Prefer": "return=representation"}

r = httpx.get(url + "/rest/v1/potentials", headers=h, timeout=30, params={
    "type": "eq.MTP", "select": "id,name,lammps_config"
})

fixed = 0
for p in r.json():
    cfg = p.get("lammps_config") or {}
    ps = cfg.get("pair_style", "")
    if "mlp" in ps:
        new_ps = ps.replace("mlp", "mtp").strip()
        # Remove duplicate
        new_ps = " ".join(dict.fromkeys(new_ps.split()))
        cfg["pair_style"] = new_ps
        r2 = httpx.patch(url + f"/rest/v1/potentials", headers=h, timeout=30, params={
            "id": f"eq.{p['id']}"
        }, json={"lammps_config": cfg})
        if r2.status_code in (200, 204):
            print(f"Fixed {p['name']}: '{ps}' -> '{new_ps}'")
            fixed += 1
        else:
            print(f"ERROR {p['name']}: {r2.status_code} {r2.text[:100]}")

print(f"\nFixed {fixed} MTP potentials")
