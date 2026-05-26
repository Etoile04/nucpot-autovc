from autovc.core.grading import grade_property, compute_overall_grade


def test_grade_a():
    assert grade_property(3.42, 3.40) == "A"


def test_grade_b():
    # rel_error = |3.48 - 3.38| / 3.38 ≈ 0.0296 → B (≤0.03)
    assert grade_property(3.48, 3.38) == "B"


def test_grade_c():
    # rel_error = |3.53 - 3.38| / 3.38 ≈ 0.0444 → C (≤0.05, >0.03)
    assert grade_property(3.53, 3.38) == "C"


def test_grade_d():
    # rel_error = |3.70 - 3.38| / 3.38 ≈ 0.0947 → D (≤0.10, >0.05)
    assert grade_property(3.70, 3.38) == "D"


def test_grade_f():
    assert grade_property(4.00, 3.38) == "F"


def test_grade_zero_ref():
    assert grade_property(0.5, 0.0) == "F"


def test_grade_negative_ref():
    # rel_error = |(-4.05) - (-4.0)| / 4.0 = 0.0125 → B (≤0.03, >0.01)
    assert grade_property(-4.05, -4.0) == "B"


def test_overall_b():
    assert compute_overall_grade(["A", "A", "B", "C"]) == "C"


def test_overall_all_a():
    assert compute_overall_grade(["A", "A"]) == "A"


def test_overall_empty():
    assert compute_overall_grade([]) is None
