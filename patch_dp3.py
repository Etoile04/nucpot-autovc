path = "src/autovc/runners/lammps_runner.py"
with open(path) as f:
    content = f.read()

# Patch _get_pair_config to handle DP/deepmd properly
old = '''        pair_style = cfg.get("pair_style", "eam/alloy")
        if "eam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        elif "meam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements} {all_elements}"
        else:
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        return f"pair_style {pair_style}", pair_coeff'''

new = '''        pair_style = cfg.get("pair_style", "eam/alloy")
        if "deepmd" in pair_style.lower():
            # DP: pair_style deepmd /path/to/model.pb
            return f"pair_style {pair_style} {pot_file}", "pair_coeff * *"
        elif "mtp" in pair_style.lower():
            # MTP: pair_style mtp /path/to/model.mtp
            return f"pair_style {pair_style} {pot_file}", "pair_coeff * *"
        elif "eam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        elif "meam" in pair_style.lower():
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements} {all_elements}"
        else:
            pair_coeff = f"pair_coeff * * {pot_file} {all_elements}"
        return f"pair_style {pair_style}", pair_coeff'''

assert old in content, "Pattern not found in _get_pair_config"
content = content.replace(old, new, 1)

with open(path, "w") as f:
    f.write(content)
print("Patched _get_pair_config for DP/MTP support!")
