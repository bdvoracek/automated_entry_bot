import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.metaculus import Question  # noqa: E402
from aeb.scan import classify  # noqa: E402


def _q(type, options=None):
    return Question(post_id=1, question_id=1, type=type, title="t",
                    user_permission="forecaster", status="open", options=options)


def test_binary_answerable_now():
    assert classify(_q("binary")) == "answerable_now"


def test_mc_small_answerable_now():
    assert classify(_q("multiple_choice", ["A", "B", "C"])) == "answerable_now"


def test_mc_large_needs_grouping():
    assert classify(_q("multiple_choice", [f"o{i}" for i in range(8)])) == "needs_grouping"


def test_numeric_and_discrete_need_bin_designer():
    assert classify(_q("numeric")) == "needs_bin_designer"
    assert classify(_q("discrete")) == "needs_bin_designer"
