import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.meta import UnifiedDriver, UnifiedMapping, resolve_states  # noqa: E402


def _mapping():
    # 2 unified drivers over 2 models. Model A has TWO members in U1 at different
    # baselines (the "ragged coverage" case); model B has none in U1.
    return UnifiedMapping(
        question_id=1, tier="Advanced", models=["A", "B"],
        unified=[
            UnifiedDriver(uid=1, name="Geo Risk", members={
                "A": [{"code": "X1", "name": "x1", "baseline": "Medium"},
                      {"code": "X2", "name": "x2", "baseline": "High"}],
                "B": [],
            }),
            UnifiedDriver(uid=2, name="Demand", members={
                "A": [{"code": "Y1", "name": "y1", "baseline": "Low"}],
                "B": [{"code": "Z1", "name": "z1", "baseline": "Extreme"}],
            }),
        ],
    )


def test_zero_delta_reproduces_baseline_for_all_drivers():
    m = _mapping()
    resolved, changes = resolve_states(m, {})
    assert resolved["A"] == {"X1": "Medium", "X2": "High", "Y1": "Low"}
    assert resolved["B"] == {"Z1": "Extreme"}
    assert changes == []  # nothing moved


def test_relative_shift_moves_each_member_from_its_own_baseline():
    m = _mapping()
    resolved, changes = resolve_states(m, {1: +1})  # nudge Geo Risk up one notch
    # Medium->High and High->Extreme (each shifts from ITS baseline)
    assert resolved["A"]["X1"] == "High"
    assert resolved["A"]["X2"] == "Extreme"
    assert resolved["A"]["Y1"] == "Low"        # untouched driver stays put
    assert resolved["B"] == {"Z1": "Extreme"}  # model B has no Geo Risk member
    assert len(changes) == 2


def test_clamping_at_both_ends():
    m = _mapping()
    up = resolve_states(m, {1: +5})[0]      # High + 5 clamps at Extreme
    assert up["A"]["X2"] == "Extreme"
    down = resolve_states(m, {2: -9})[0]    # Extreme - 9 clamps at Negligible
    assert down["B"]["Z1"] == "Negligible"
    assert down["A"]["Y1"] == "Negligible"  # Low - 9 -> Negligible


def test_full_driver_set_always_present():
    # PUT requires ALL drivers; a partial delta must still return every code.
    m = _mapping()
    resolved, _ = resolve_states(m, {2: +1})
    assert set(resolved["A"]) == {"X1", "X2", "Y1"}
    assert set(resolved["B"]) == {"Z1"}


def test_unified_baseline_index_is_mean_ordinal():
    m = _mapping()
    # U1 members at Medium(2) and High(3) -> mean 2.5
    assert m.unified_baseline_index(1) == 2.5


def _weighted_mapping():
    return UnifiedMapping(
        question_id=1, tier="Advanced", models=["A", "B", "C"], unified=[
            UnifiedDriver(uid=1, name="Wide+high", members={  # pts 12, in 3 models -> 36
                "A": [{"code": "a", "name": "", "baseline": "Low", "points": 5}],
                "B": [{"code": "b", "name": "", "baseline": "Low", "points": 4}],
                "C": [{"code": "c", "name": "", "baseline": "Low", "points": 3}]}),
            UnifiedDriver(uid=2, name="Deep+narrow", members={  # pts 10, in 1 model -> 10
                "A": [{"code": "d", "name": "", "baseline": "Low", "points": 5},
                      {"code": "e", "name": "", "baseline": "Low", "points": 5}], "B": [], "C": []}),
        ])


def test_weight_is_influence_points_times_model_coverage():
    m = _weighted_mapping()
    assert m.by_uid(1).influence_points() == 12
    assert m.by_uid(1).weight() == 36        # 12 points x 3 models
    assert m.by_uid(2).weight() == 10        # 10 points x 1 model


def test_sort_both_directions():
    m = _weighted_mapping()
    assert [u.uid for u in m.sorted_by_weight(descending=True)] == [1, 2]
    assert [u.uid for u in m.sorted_by_weight(descending=False)] == [2, 1]


def test_inverted_member_shifts_opposite():
    # One cluster, two members: aligned (invert=False) and inverted (invert=True).
    m = UnifiedMapping(
        question_id=1, tier="Advanced", models=["A", "B"], unified=[
            UnifiedDriver(uid=1, name="Supply tightness", members={
                "A": [{"code": "x", "name": "", "baseline": "Medium", "invert": False}],
                "B": [{"code": "y", "name": "", "baseline": "Medium", "invert": True}]}),
        ])
    resolved, _ = resolve_states(m, {1: +1})
    assert resolved["A"]["x"] == "High"   # aligned goes up
    assert resolved["B"]["y"] == "Low"    # inverted goes down (same semantic direction)


def test_apply_directions_sets_mode_and_invert():
    from aeb.directionality import apply_directions
    doc = {"unified": [{"uid": 1, "name": "c", "members": {
        "A": [{"code": "x"}], "B": [{"code": "y"}], "C": [{"code": "z"}]}}]}
    # two +1, one -1  -> mode +1, the -1 member is inverted
    apply_directions(doc, {("A", "x"): 1, ("B", "y"): 1, ("C", "z"): -1})
    u = doc["unified"][0]
    assert u["mode_dir"] == 1
    flags = {m["code"]: m["invert"] for mems in u["members"].values() for m in mems}
    assert flags == {"x": False, "y": False, "z": True}
