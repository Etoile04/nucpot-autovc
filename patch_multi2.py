"""Replace lines 119-142 in lammps_runner.py with multi-element support."""
p = "src/autovc/runners/lammps_runner.py"
lines = open(p).readlines()

# Lines 119-142 (1-indexed) -> indices 118-141
new_lines = [
    '    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else ""\n',
    '    n_types = len(elements)\n',
    '    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,\n',
    '              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,\n',
    '              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "O": 16.00, "H": 1.008,\n',
    '              "He": 4.003, "Sn": 118.71}\n',
    '    if n_types <= 1:\n',
    '        box_block = "create_box 1 box\\ncreate_atoms 1 box"\n',
    '    else:\n',
    '        mass_lines = "\\n".join(\n',
    '            f"mass {i+1} {MASSES.get(elements[i], 100.0)}" for i in range(n_types)\n',
    '        )\n',
    '        box_block = f"create_box {n_types} box\\n{mass_lines}\\ncreate_atoms 1 box"\n',
    '        # For DP multi-element: random type assignment (equiatomic approximation)\n',
    '        frac = 1.0 / n_types\n',
    '        for i in range(1, n_types):\n',
    '            remaining_frac = 1.0 - frac * i\n',
    '            box_block += f"\\nset type {i} type/fraction {i+1} {1.0/n_types:.4f} {12345+i}"\n',
    '    return f"""units metal\n',
    'dimension 3\n',
    'boundary p p p\n',
    'atom_style atomic\n',
    '\n',
    '{lattice_line}\n',
    'region box block 0 {size} 0 {size} 0 {size}\n',
    '{box_block}\n',
    '\n',
    '{plugin_load}{pair_style}\n',
    '{pair_coeff}\n',
    '\n',
    'minimize 1e-10 1e-10 1000 10000\n',
    '\n',
    'variable natom equal count(all)\n',
    'variable ecoh equal pe/v_natom\n',
    'variable a equal lx/{size}\n',
    '\n',
    'print "RESULT lattice_constant ${{a}}"\n',
    'print "RESULT cohesive_energy ${{ecoh}}"\n',
    'print "RESULT total_energy ${{pe}}"\n',
    '"""\n',
]

# Verify we're replacing the right lines
assert "plugin_load" in lines[118], f"Line 119 unexpected: {lines[118].strip()}"
assert '"""' in lines[141].strip(), f"Line 142 unexpected: {lines[141].strip()}"

# Replace
lines[118:142] = new_lines

open(p, "w").writelines(lines)
print(f"Replaced lines 119-142 ({142-118} old -> {len(new_lines)} new)")
