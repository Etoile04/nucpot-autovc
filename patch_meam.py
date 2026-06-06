p = "src/autovc/runners/lammps_runner.py"
c = open(p).read()

# Update __init__ to handle MEAM: use lmp-full for MEAM
old = '''        # Auto-detect DP potential and use lmp-with-dp
        ptype_init = (potential_meta.get("type") or "").lower()
        is_dp = "dp" in ptype_init or "deepmd" in ptype_init
        if is_dp:
            self.lammps_bin = lammps_bin or "/usr/local/bin/lmp-with-dp"
            self._is_dp = True
        else:
            self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")
            self._is_dp = False'''

new = '''        # Auto-detect potential type and select appropriate LAMMPS binary
        ptype_init = (potential_meta.get("type") or "").lower()
        is_dp = "dp" in ptype_init or "deepmd" in ptype_init
        is_meam = "meam" in ptype_init
        if is_dp:
            self.lammps_bin = lammps_bin or "/usr/local/bin/lmp-with-dp"
            self._is_dp = True
            self._is_meam = False
        elif is_meam:
            self.lammps_bin = lammps_bin or "/usr/local/bin/lmp-full"
            self._is_dp = False
            self._is_meam = True
        else:
            self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")
            self._is_dp = False
            self._is_meam = False'''

assert old in c, "Pattern not found"
c = c.replace(old, new, 1)

# Also update _get_pair_config for MEAM - meam needs library.meam + specific file
# The pair_coeff for MEAM is already handled by lammps_config, just need the binary

open(p, "w").write(c)
print("Patched runner for MEAM support!")
