import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.cdf import Scaling, bins_to_cdf, validate_cdf  # noqa: E402

# A symmetric-ish 5-bin PMF spanning [0, 100].
EDGES = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
MASSES = [0.1, 0.2, 0.4, 0.2, 0.1]


def _assert_valid(cdf, scaling):
    validate_cdf(cdf, scaling)  # raises if bad
    assert len(cdf) == scaling.cdf_size
    assert all(0.0 <= x <= 1.0 for x in cdf)
    assert all(cdf[i] >= cdf[i - 1] for i in range(1, len(cdf)))


def test_closed_bounds_pin_endpoints():
    s = Scaling(0, 100, None, open_lower_bound=False, open_upper_bound=False)
    cdf = bins_to_cdf(EDGES, MASSES, s)
    _assert_valid(cdf, s)
    assert cdf[0] == 0.0
    assert abs(cdf[-1] - 1.0) < 1e-9


def test_open_bounds_leave_tail_mass():
    s = Scaling(0, 100, None, open_lower_bound=True, open_upper_bound=True)
    cdf = bins_to_cdf(EDGES, MASSES, s)
    _assert_valid(cdf, s)
    assert cdf[0] > 0.0          # mass below range_min
    assert cdf[-1] < 1.0         # mass above range_max


def test_monotonic_and_min_step_hold():
    for lo in (True, False):
        for hi in (True, False):
            s = Scaling(0, 100, None, open_lower_bound=lo, open_upper_bound=hi)
            _assert_valid(bins_to_cdf(EDGES, MASSES, s), s)


def test_log_scaling_runs():
    s = Scaling(1, 1000, zero_point=0.0, open_lower_bound=False, open_upper_bound=False)
    edges = [1.0, 10.0, 100.0, 300.0, 600.0, 1000.0]
    cdf = bins_to_cdf(edges, [0.15, 0.25, 0.3, 0.2, 0.1], s)
    _assert_valid(cdf, s)


def test_discrete_cdf_size():
    s = Scaling(0, 100, None, open_lower_bound=False, open_upper_bound=False, cdf_size=51)
    cdf = bins_to_cdf(EDGES, MASSES, s)
    assert len(cdf) == 51
    _assert_valid(cdf, s)


def test_rejects_bad_edges():
    s = Scaling(0, 100, None)
    for bad in ([0.0, 20.0, 20.0, 60.0, 80.0, 100.0], [0.0, 60.0, 40.0, 80.0, 90.0, 100.0]):
        try:
            bins_to_cdf(bad, MASSES, s)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for edges {bad}")
