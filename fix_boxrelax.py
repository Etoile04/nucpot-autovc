"""Fix lattice_constant: add fix box/relax before minimize."""
p = "src/autovc/runners/lammps_runner.py"
lines = open(p).readlines()

# Find "minimize 1e-10 1e-10 1000 10000" in _generate_lattice_input and add fix before it
# This is line 149 (0-indexed 148) based on grep
fixed = 0
new_lines = []
in_lattice_func = False
for i, line in enumerate(lines):
    if "def _generate_lattice_input" in line:
        in_lattice_func = True
    elif in_lattice_func and line.strip().startswith("def "):
        in_lattice_func = False

    if in_lattice_func and line.strip() == "minimize 1e-10 1e-10 1000 10000":
        # Add fix box/relax before minimize, unfix after
        indent = "    " if line.startswith(" ") else ""
        # Check if fix box/relax already present (avoid double-add)
        if i > 0 and "box/relax" not in lines[i-1]:
            new_lines.append(f"{indent}fix 1 all box/relax iso 0.0\n")
            new_lines.append(line)
            new_lines.append(f"{indent}unfix 1\n")
            fixed += 1
            continue
    new_lines.append(line)

open(p, "w").writelines(new_lines)
print(f"Added fix box/relax to {fixed} minimize blocks in _generate_lattice_input")
