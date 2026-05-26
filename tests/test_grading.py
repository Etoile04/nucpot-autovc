from autovc.core.grading import grade_property, compute_overall_grade

def test_grade_a():
    # 0.6% error
    assert grade_property(3.42, 3.40) == "A"

def test_grade_b():
    # 2.0% error
    assert grade_property(3.448, 3.38) == "B"

def test_grade_c():
    # 3.6% error
    assert grade_property(3.502, 3.38) == "C"

def test_grade_d():
    # 7.1% error
    assert grade_property(3.62, 3.38) == "D"

def test_grade_f():
    # 18.3% error
    assert grade_property(4.00, 3.38) == "F"

def test_grade_zero_ref():
    assert grade_property(0.5, 0.0) == "F"

def test_grade_negative_ref():
    # 0.5% error
    assert grade_property(-4.02, -4.0) == "A"

def test_overall():
    assert compute_overall_grade(["A", "B", "C"]) == "C"

def test_overall_all_a():
    assert compute_overall_grade(["A", "A"]) == "A"

def test_overall_empty():
    assert compute_overall_grade([]) is None
