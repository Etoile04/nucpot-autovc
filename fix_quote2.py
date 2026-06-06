p = "src/autovc/runners/lammps_runner.py"
c = open(p).read()
# Fix elastic input call to also pass is_dp
old = "self.elements, pair_style, pair_coeff, guess, self.structure, size=3"
new = "self.elements, pair_style, pair_coeff, guess, self.structure, size=3, is_dp=getattr(self, '_is_dp', False)"
c = c.replace(old, new)
open(p, "w").write(c)
print("Fixed elastic input call too")
