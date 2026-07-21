import sys, time; sys.path.insert(0,"src")
from aeb.folds import FoldsClient
from aeb.metaculus import MetaculusClient
from aeb.orchestrator import Orchestrator
orch=Orchestrator(MetaculusClient(), FoldsClient(), dry_run=True)  # STAGE, don't enter yet
t0=time.time()
print("cdf collector (dry-run) started; pending:",
      [j.question_id for j in orch.store.pending()], flush=True)
while time.time()-t0 < 3000:
    orch.collect()
    if not orch.store.pending():
        print(f"[t+{int(time.time()-t0)}s] ALL CDF JOBS STAGED & VALIDATED", flush=True); break
    time.sleep(60)
else:
    print("TIMEOUT pending:", [j.question_id for j in orch.store.pending()], flush=True)
