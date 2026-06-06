path = "src/autovc/runners/lammps_runner.py"
with open(path) as f:
    content = f.read()

# Fix 1: The f-string has {plugin_load} which Python will try to evaluate
# Replace the f-string return with a concatenation approach
# Find the template with {plugin_load} and fix it

# The current broken template has literal {plugin_load} in an f-string
# We need to make plugin_load a real variable in the function

# Add is_dp parameter to _generate_lattice_input
content = content.replace(
    "    size: int = 4,\n) -> str:",
    "    size: int = 4,\n    is_dp: bool = False,\n) -> str:"
)

# Add plugin_load variable before the return statement in _generate_lattice_input
# Find the line: return f"""units metal
# and insert plugin_load assignment before it
old_return = '    return f"""units metal'
new_return = '    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else ""\n    return f"""units metal'

# Only replace in _generate_lattice_input context (after line ~103)
idx = content.find("def _generate_lattice_input")
if idx >= 0:
    search_from = idx
    pos = content.find(old_return, search_from)
    if pos >= 0 and pos < content.find("\ndef ", pos + 10):
        content = content[:pos] + new_return + content[pos + len(old_return):]
        print("Added plugin_load variable in _generate_lattice_input")

# Now {plugin_load} in the f-string will be resolved by Python
# But wait - this is an f-string with {} for LAMMPS vars too!
# The LAMMPS ${} vars are double-escaped as {{}} so they're fine
# But {size}, {lattice_line}, {pair_style}, {pair_coeff} are f-string vars
# {plugin_load} will also work as f-string var now

# Same for _generate_elastic_input - needs is_dp support
content = content.replace(
    "def _generate_elastic_input(\n    elements: list[str],\n    pair_style: str,\n    pair_coeff: str,",
    "def _generate_elastic_input(\n    elements: list[str],\n    pair_style: str,\n    pair_coeff: str,\n    is_dp: bool = False,"
)

# Find elastic template and add plugin_load
idx2 = content.find("def _generate_elastic_input")
if idx2 >= 0:
    # Find the first f-string return after this
    pos2 = content.find('return f"""', idx2)
    if pos2 >= 0:
        content = content[:pos2] + '    plugin_load = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so\\n" if is_dp else ""\n    ' + content[pos2:]
        print("Added plugin_load in _generate_elastic_input")

# Find elastic template pair_style line and add plugin_load
# Look for {pair_style}\n{pair_coeff} in elastic section
elastic_section = content[idx2:] if idx2 >= 0 else ""
if "{plugin_load}" not in elastic_section:
    # Need to add {plugin_load} before pair_style in elastic template
    # Find pair_style in elastic templates
    pass  # Already handled by the template replacement

# Also patch the callers to pass is_dp
# In run_template method, find calls to _generate_lattice_input and _generate_elastic_input
content = content.replace(
    "_generate_lattice_input(\n                    elements=self.elements,",
    "_generate_lattice_input(\n                    elements=self.elements,\n                    is_dp=getattr(self, '_is_dp', False),"
)

content = content.replace(
    "_generate_elastic_input(\n                    elements=self.elements,",
    "_generate_elastic_input(\n                    elements=self.elements,\n                    is_dp=getattr(self, '_is_dp', False),"
)

with open(path, "w") as f:
    f.write(content)
print("All patches applied!")
