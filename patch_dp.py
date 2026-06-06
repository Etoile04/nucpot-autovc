"""Patch lammps_runner.py to support DP potentials."""
import re

path = "src/autovc/runners/lammps_runner.py"
with open(path) as f:
    content = f.read()

# 1. Patch _pair_style_config to add DP support
old1 = '    # Auto-detect from type\n    ptype = (potential_type or "").lower()\n    if "meam" in ptype:'
new1 = '    # Auto-detect from type\n    ptype = (potential_type or "").lower()\n    if "deepmd" in ptype or "dp" in ptype:\n        return "pair_style deepmd " + (pot_file or "model.pb"), "pair_coeff * *"\n    elif "meam" in ptype:'
assert old1 in content, "Pattern 1 not found"
content = content.replace(old1, new1)

# 2. Patch LAMMPSRunner.__init__ to auto-detect DP
old2 = '        self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")'
new2 = '''        # Auto-detect DP potential and use lmp-with-dp
        ptype_init = (potential_meta.get("type") or "").lower()
        is_dp = "dp" in ptype_init or "deepmd" in ptype_init
        if is_dp:
            self.lammps_bin = lammps_bin or "/usr/local/bin/lmp-with-dp"
            self._is_dp = True
        else:
            self.lammps_bin = lammps_bin or getattr(self.settings, "LAMMPS_BIN", "lmp_serial")
            self._is_dp = False'''
assert old2 in content, "Pattern 2 not found"
content = content.replace(old2, new2)

# 3. Add plugin_load to _generate_lattice_input template
# Find the template string in the lattice input function
old3 = '''{pair_style}
{pair_coeff}

minimize'''

new3 = '''{plugin_load}{pair_style}
{pair_coeff}

minimize'''

if old3 in content:
    content = content.replace(old3, new3)
    print("Patched template (minimize variant)")
else:
    # Try alternate template
    old3b = '{pair_style}\n{pair_coeff}\n\nminimize'
    if old3b in content:
        content = content.replace(old3b, '{plugin_load}' + old3b)
        print("Patched template (alternate)")
    else:
        print("WARNING: Could not find template to patch for plugin_load")

# 4. Find all .format() calls in _generate_lattice_input and add plugin_load
# Look for the return statement in _generate_lattice_input
old4_match = re.search(
    r'(def _generate_lattice_input.*?return .*?\.format\()',
    content, re.DOTALL
)
if old4_match:
    print("Found _generate_lattice_input format call")
    # Add plugin_load to the format kwargs
    # Find the specific format call and add plugin_load parameter
    old_fmt = 'pair_coeff=pair_coeff,'
    # Only replace first occurrence (in _generate_lattice_input)
    idx = content.find('def _generate_lattice_input')
    if idx >= 0:
        # Find the format call after this function
        fmt_idx = content.find('pair_coeff=pair_coeff,', idx)
        if fmt_idx >= 0:
            # Check if within the function
            next_def = content.find('\ndef ', fmt_idx)
            # Just add plugin_load before pair_coeff
            content = content[:fmt_idx] + 'plugin_load="plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else "",\n            ' + content[fmt_idx:]
            print("Added plugin_load to format kwargs")
else:
    print("WARNING: Could not find format call in _generate_lattice_input")

with open(path, "w") as f:
    f.write(content)

print("Done! Patched successfully.")
