p = "src/autovc/runners/lammps_runner.py"
c = open(p).read()
c = c.replace("is_dp=getattr(self, _is_dp, False)", "is_dp=getattr(self, '_is_dp', False)")
open(p, "w").write(c)
print("Fixed quote issue")
