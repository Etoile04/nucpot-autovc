"""Patch _generate_lattice_input for multi-element DP support."""
p = "src/autovc/runners/lammps_runner.py"
c = open(p).read()

# Replace the entire _generate_lattice_input function body
# Key changes:
# 1. Multi-element: create_box N, mass lines, set type randomly or as type 1
# 2. For single element: keep create_box 1 as before

old_block = '''    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else ""
    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size}
create_box 1 box
create_atoms 1 box

{plugin_load}{pair_style}
{pair_coeff}

minimize 1e-10 1e-10 1000 10000

variable natom equal count(all)
variable ecoh equal pe/v_natom
variable a equal lx/{size}

print "RESULT lattice_constant ${{{a}}}"
print "RESULT cohesive_energy ${{{ecoh}}}"
print "RESULT total_energy ${{{pe}}}"
"""'''

# Build new block with multi-element support
new_block = '''    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else ""
    n_types = len(elements)
    # Mass table for common elements
    MASSES = {"U": 238.03, "Mo": 95.95, "Zr": 91.22, "Nb": 92.91, "Fe": 55.85,
              "Cr": 52.00, "W": 183.84, "Ta": 180.95, "V": 50.94, "Ti": 47.87,
              "Ni": 58.69, "Cu": 63.55, "Al": 26.98, "Si": 28.09, "O": 16.00,
              "H": 1.008, "He": 4.003, "Sn": 118.71, "Mn": 54.94, "Co": 58.93}
    if n_types <= 1:
        # Single element: simple box
        box_block = "create_box 1 box\\ncreate_atoms 1 box"
    else:
        # Multi-element: create N types, assign randomly (RCS approximation)
        mass_lines = "\\n".join(
            f"mass {i+1} {MASSES.get(elements[i], 100.0)}" for i in range(n_types)
        )
        box_block = f"create_box {n_types} box\\n{mass_lines}\\ncreate_atoms 1 box\\nset type 1 type/fraction 1 0.5 12345"
        # Actually for DP we need all types present. Use set type/atom for random distribution
        frac = 1.0 / n_types
        type_cmds = []
        # Assign atoms sequentially to types for equal distribution
        for i in range(1, n_types):
            type_cmds.append(f"set type {i} type/fraction {i+1} {frac * (n_types - i + 1):.4f} {12345 + i}")
        if type_cmds:
            box_block = f"create_box {n_types} box\\n{mass_lines}\\ncreate_atoms 1 box\\n" + "\\n".join(type_cmds)

    return f"""units metal
dimension 3
boundary p p p
atom_style atomic

{lattice_line}
region box block 0 {size} 0 {size} 0 {size}
{box_block}

{plugin_load}{pair_style}
{pair_coeff}

minimize 1e-10 1e-10 1000 10000

variable natom equal count(all)
variable ecoh equal pe/v_natom
variable a equal lx/{size}

print "RESULT lattice_constant ${{{a}}}"
print "RESULT cohesive_energy ${{{ecoh}}}"
print "RESULT total_energy ${{{pe}}}"
"""'''

assert old_block in c, f"Old block not found! Looking for first line: {old_block[:80]}"
c = c.replace(old_block, new_block, 1)

open(p, "w").write(c)
print("Patched _generate_lattice_input for multi-element support!")
