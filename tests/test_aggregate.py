import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb import aggregate  # noqa: E402


def test_midpoint_is_mean_median_average():
    # mean = 0.5, median = 0.4 -> (0.5 + 0.4)/2 = 0.45
    assert aggregate.midpoint([0.2, 0.4, 0.9]) == 0.45


def test_midpoint_even_count():
    # values [0.1,0.3,0.5,0.9]: mean=0.45, median=0.4 -> 0.425
    assert abs(aggregate.midpoint([0.1, 0.3, 0.5, 0.9]) - 0.425) < 1e-12


def test_aggregate_outcomes_normalizes():
    runs = [{"Yes": 0.6, "No": 0.4}, {"Yes": 0.8, "No": 0.2}, {"Yes": 0.7, "No": 0.3}]
    agg = aggregate.aggregate_outcomes(runs)
    assert abs(sum(agg.values()) - 1.0) < 1e-12
    assert agg["Yes"] > agg["No"]


def test_aggregate_rejects_inconsistent_labels():
    try:
        aggregate.aggregate_outcomes([{"A": 0.5, "B": 0.5}, {"A": 1.0}])
    except ValueError:
        return
    raise AssertionError("expected ValueError on inconsistent labels")
