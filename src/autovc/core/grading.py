_GRADE_VALUES = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


def grade_property(computed: float, reference: float, thresholds: tuple = (0.01, 0.03, 0.05, 0.10)) -> str:
    if reference == 0.0:
        return "A" if computed == 0.0 else "F"
    rel_error = abs(computed - reference) / abs(reference)
    for grade, threshold in zip(["A", "B", "C", "D"], thresholds):
        if rel_error <= threshold:
            return grade
    return "F"


def compute_overall_grade(grades: list[str]) -> str | None:
    if not grades:
        return None
    return max(grades, key=lambda g: _GRADE_VALUES.get(g, 4))
