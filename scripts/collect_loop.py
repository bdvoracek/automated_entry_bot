import sys, time; sys.path.insert(0,"src")
from aeb.folds import FoldsClient
from aeb.metaculus import MetaculusClient
from aeb.orchestrator import Orchestrator

orch = Orchestrator(MetaculusClient(), FoldsClient(), dry_run=False)  # LIVE submit to sandbox
t0 = time.time()
print("collector started; pending:", [j.question_id for j in orch.store.pending()], flush=True)
while time.time() - t0 < 3000:  # up to 50 min
    orch.collect()
    if not orch.store.pending():
        print(f"[t+{int(time.time()-t0)}s] ALL JOBS COMPLETE", flush=True)
        break
    time.sleep(60)
else:
    print("TIMEOUT; still pending:", [j.question_id for j in orch.store.pending()], flush=True)

print("\n=== FINAL ===", flush=True)
for j in orch.store.jobs:
    agg = j.result.get("agg")
    print(f"q{j.question_id} [{j.qtype}] {j.status} midpoint={agg}", flush=True)
