import sys, time; sys.path.insert(0,"src")
from aeb.metaculus import MetaculusClient
from aeb.folds import FoldsClient
from aeb.data import SqliteRepository
from aeb.explore import ExploreEngine
from aeb.resulting import ResultingWorker

repo=SqliteRepository("state/exploration.db")
eng=ExploreEngine(MetaculusClient(), FoldsClient(), repo, dry_run=False)  # LIVE
t0=time.time()
print("explore collector started (LIVE)", flush=True)
while time.time()-t0 < 3000:  # up to 50 min
    eng.collect()
    pend=[r for r in repo.all("model_runs") if r["status"]=="pending"]
    surf=len(repo.all("surfaced_predictions"))
    print(f"[t+{int(time.time()-t0)}s] pending={len(pend)} surfaced={surf}", flush=True)
    if not pend:
        print("ALL 60 RUNS COMPLETE", flush=True); break
    time.sleep(60)
# wait-and-map: pull resolutions (real Qs won't be resolved yet, but verifies wiring)
res=ResultingWorker(MetaculusClient(), repo).poll()
print("RESULTING mapped:", [(r.question_id, r.resolved) for r in res], flush=True)
for sp in repo.all("surfaced_predictions"):
    print("SURFACED", sp["question_id"], sp["qtype"], sp["aggregate"], "->", sp["metaculus_response"], flush=True)
