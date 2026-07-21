import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.data import ModelRun, Question, Resolution, SqliteRepository, SurfacedPrediction  # noqa: E402


def _repo():
    return SqliteRepository(Path(tempfile.mkdtemp()) / "db.sqlite")


def test_entity_roundtrip_via_repo():
    repo = _repo()
    q = Question(question_id=42, post_id=7, type="numeric", title="X?", scaling={"range_min": 0})
    repo.save(q)
    got = repo.load(Question, "q:42")
    assert got is not None and got.question_id == 42 and got.scaling == {"range_min": 0}


def test_upsert_overwrites():
    repo = _repo()
    r = ModelRun(question_id=1, tier="Overview", run_index=0, folds_model_id="m1", status="pending")
    repo.save(r)
    r.status = "succeeded"; r.outcomes = {"Yes": 0.7, "No": 0.3}
    repo.save(r)
    got = repo.load(ModelRun, "run:m1")
    assert got.status == "succeeded" and got.outcomes["Yes"] == 0.7
    assert len(repo.all(ModelRun.COLLECTION)) == 1  # not duplicated


def test_query_and_partition():
    repo = _repo()
    for i in range(10):
        repo.save(ModelRun(question_id=100, tier="Advanced", run_index=i, folds_model_id=f"a{i}"))
    for i in range(10):
        repo.save(ModelRun(question_id=100, tier="Insight", run_index=i, folds_model_id=f"i{i}"))
    adv = repo.load_all(ModelRun, tier="Advanced")
    assert len(adv) == 10 and all(m.tier == "Advanced" for m in adv)
    # partition key is question_id for all
    docs = repo.all(ModelRun.COLLECTION)
    assert {d["_pk"] for d in docs} == {"100"}


def test_multiple_collections_isolated():
    repo = _repo()
    repo.save(Question(question_id=1, post_id=1, type="binary", title="q"))
    repo.save(SurfacedPrediction(question_id=1, post_id=1, qtype="binary", tier_used="Advanced",
                                 method="(mean+median)/2", aggregate={"Yes": 0.6}))
    repo.save(Resolution(question_id=1, post_id=1, resolved=True, resolution_value="yes"))
    assert len(repo.all("questions")) == 1
    assert len(repo.all("surfaced_predictions")) == 1
    assert repo.load(Resolution, "res:1").resolution_value == "yes"
