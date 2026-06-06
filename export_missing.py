"""Export missing potentials list for subagent processing."""
import httpx, os, json

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
h = {"apikey": key, "Authorization": "Bearer " + key}

r = httpx.get(url + "/rest/v1/potentials", headers=h, params={
    "select": "id,name,type,elements,system_name,file_url,lammps_config",
    "order": "type.asc,name.asc"
})
potentials = r.json()

container_files = [
    "Ag2S_MTP.mtp", "FeCrAl_FS.eam.fs", "FeHHe-DP.pb", "InSe_MTP.mtp",
    "Ta-Ce-pot.mtp-v1.7.1", "TaNbWMoV_DP.pth", "Ti-Ce-pot.mtp-v6.0.4.5",
    "U_MTP.mtp", "W-Mo_FS_2020.eam.fs", "W-Re-Ta_FS.eam.fs",
    "W-Re_FS_2018.eam.fs", "W-Re_FS_2019.eam.fs", "W-Ta-He_FS_2021.eam.fs",
    "W-Ta-V-Cr-He_FS_2025.eam.fs", "W-Ta-V-Cr_FS_2023.eam.fs",
    "W-Ta_FS_2019.eam.fs", "W-V_FS_2020.eam.fs", "WNiFe_FS.eam.fs"
]

no_file = []
for p in potentials:
    file_url = p.get("file_url") or ""
    if file_url:
        continue
    no_file.append(p)

with open("/tmp/missing_potentials.json", "w") as f:
    json.dump(no_file, f, indent=2, ensure_ascii=False)

print(json.dumps({
    "total": len(no_file),
    "by_type": {t: sum(1 for p in no_file if p.get("type") == t)
                for t in sorted(set(p.get("type", "?") for p in no_file))}
}, indent=2))
