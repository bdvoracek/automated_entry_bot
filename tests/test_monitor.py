import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.metaculus import Question       # noqa: E402
from aeb.monitor import Monitor, WatermarkStore  # noqa: E402


def _q(post_id, open_time, *, perm="forecaster", status="open",
       already=False, qtype="binary"):
    return Question(post_id=post_id, question_id=post_id, type=qtype, title=f"q{post_id}",
                    user_permission=perm, status=status, open_time=open_time,
                    already_forecast=already)


class FakeClient:
    """Stands in for MetaculusClient.iter_open_questions.

    `pages` is the newest-first list the API would return; the fake honours the
    early-stop by simply handing the monitor the whole ordered list.
    """
    def __init__(self, questions):
        self.questions = questions
        self.calls = 0

    def iter_open_questions(self, tournaments=None, *, order_by=None,
                            forecastable_only=True, skip_already_forecast=True,
                            page_size=100, max_questions=None):
        self.calls += 1
        for q in self.questions:
            yield q


def _monitor(tmp_path, questions):
    store = WatermarkStore(path=tmp_path / "monitor.json")
    return Monitor(FakeClient(questions), store, log=lambda m: None)


def test_cold_start_returns_nothing_but_sets_frontier(tmp_path):
    qs = [_q(3, "2026-07-22T12:00:00Z"), _q(2, "2026-07-22T11:00:00Z")]
    mon = _monitor(tmp_path, qs)
    assert mon.poll("t") == []                       # do not flood the backlog
    assert mon.store.get("t").high_open_time == "2026-07-22T12:00:00Z"


def test_cold_start_backfill_returns_open_questions(tmp_path):
    qs = [_q(3, "2026-07-22T12:00:00Z"), _q(2, "2026-07-22T11:00:00Z")]
    mon = _monitor(tmp_path, qs)
    got = mon.poll("t", backfill=True)
    assert {q.post_id for q in got} == {2, 3}


def test_only_newer_than_watermark_is_new(tmp_path):
    mon = _monitor(tmp_path, [_q(2, "2026-07-22T11:00:00Z")])
    mon.poll("t")                                     # frontier = 11:00
    # next tick: a genuinely newer question plus the already-seen one
    mon.mc = FakeClient([_q(5, "2026-07-22T12:30:00Z"), _q(2, "2026-07-22T11:00:00Z")])
    got = mon.poll("t")
    assert [q.post_id for q in got] == [5]
    assert mon.store.get("t").high_open_time == "2026-07-22T12:30:00Z"


def test_non_forecastable_and_already_forecast_are_excluded(tmp_path):
    mon = _monitor(tmp_path, [_q(1, "2026-07-22T10:00:00Z")])
    mon.poll("t")
    mon.mc = FakeClient([
        _q(10, "2026-07-22T13:00:00Z", perm="viewer"),      # cannot forecast
        _q(11, "2026-07-22T13:01:00Z", already=True),       # already forecast
        _q(12, "2026-07-22T13:02:00Z"),                     # the keeper
    ])
    got = mon.poll("t")
    assert [q.post_id for q in got] == [12]


def test_watermark_persists_across_store_reload(tmp_path):
    path = tmp_path / "monitor.json"
    Monitor(FakeClient([_q(2, "2026-07-22T11:00:00Z")]),
            WatermarkStore(path), log=lambda m: None).poll("t")
    # a fresh store reads the same file back
    reloaded = WatermarkStore(path)
    assert reloaded.get("t").high_open_time == "2026-07-22T11:00:00Z"


def test_missing_open_time_falls_back_to_seen_ids(tmp_path):
    mon = _monitor(tmp_path, [_q(7, None)])
    first = mon.poll("t", backfill=True)              # no open_time -> use id ring
    assert [q.post_id for q in first] == [7]
    mon.mc = FakeClient([_q(7, None)])                # same question again
    assert mon.poll("t", backfill=True) == []          # not re-detected
