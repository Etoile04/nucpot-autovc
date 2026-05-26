from autovc.core.grading import grade_property, compute_overall_grade


def test_grade_a(): assert grade_property(3.42, 3.40) == "A"       # rel_err≈0.006
def test_grade_b(): assert grade_property(3.46, 3.40) == "B"       # rel_err≈0.018
def test_grade_c(): assert grade_property(3.54, 3.40) == "C"       # rel_err≈0.041
def test_grade_d(): assert grade_property(3.67, 3.40) == "D"       # rel_err≈0.079
def test_grade_f(): assert grade_property(3.91, 3.40) == "F"       # rel_err≈0.15
def test_grade_zero_ref(): assert grade_property(0.5, 0.0) == "F"
def test_grade_negative_ref(): assert grade_property(-4.02, -4.0) == "A"  # rel_err=0.005
def test_overall_b(): assert compute_overall_grade(["A", "A", "B", "C"]) == "C"
def test_overall_all_a(): assert compute_overall_grade(["A", "A"]) == "A"
def test_overall_empty(): assert compute_overall_grade([]) is None
