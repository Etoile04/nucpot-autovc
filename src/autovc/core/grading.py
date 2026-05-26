_GRADE_VALUES = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


def grade_property(c, r, t=(0.01, 0.03, 0.05, 0.10)):
    if r == 0:
        return "A" if c == 0 else "F"
    e = abs(c - r) / abs(r)
    for g, th in zip(["A", "B", "C", "D"], t):
        if e <= th:
            return g
    return "F"


def compute_overall_grade(grades):
    if not grades:
        return None
    return max(grades, key=lambda g: _GRADE_VALUES.get(g, 4))
