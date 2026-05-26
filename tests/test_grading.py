from autovc.core.grading import grade_property, compute_overall_grade


def test_grade_a(): assert grade_property(3.42, 3.40) == "A"       # rel=0.006 → ≤0.01
def test_grade_b(): assert grade_property(3.468, 3.40) == "B"     # rel=0.02  → ≤0.03
def test_grade_c(): assert grade_property(3.536, 3.40) == "C"     # rel=0.04  → ≤0.05
def test_grade_d(): assert grade_property(3.638, 3.40) == "D"     # rel=0.07  → ≤0.10
def test_grade_f(): assert grade_property(4.00, 3.38) == "F"      # rel=0.183 → >0.10
def test_grade_zero_ref(): assert grade_property(0.5, 0.0) == "F"
def test_grade_negative_ref(): assert grade_property(-4.02, -4.0) == "A"  # rel=0.005 → ≤0.01
def test_overall_b(): assert compute_overall_grade(["A", "A", "B", "C"]) == "C"
def test_overall_all_a(): assert compute_overall_grade(["A", "A"]) == "A"
def test_overall_empty(): assert compute_overall_grade([]) is None
