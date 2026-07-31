"""Build the consensus causal artifact for a question: driver CI/role + ranked
causal fragments (subgraphs). Writes state/causal_<qid>_<tier>.json, consumed by
the meta UI. Fetches each model's `edges` from 51Folds, unifies via the cluster
map, then uses aeb.causal for the metrics/selection. Prose is authored per focal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb import causal, config  # noqa: E402
from aeb.http import request  # noqa: E402
from aeb.meta import load_mapping  # noqa: E402

# default question is Brent; pass another mapping path as argv[1]
MAPPING = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "state" / "unified_drivers_44704_advanced.json"

# accessible, 51Folds-voice prose per focal unified-driver id. Other questions
# keep theirs in state/prose_<qid>_<tier>.json ({uid: [title, insight]}).
PROSE = {
    2: ("The reserve is the world's shock absorber",
        "When conflict flares or OPEC moves, governments reach for their strategic reserves — and that "
        "decision ripples straight into how full the world's storage tanks are, and into how traders bet. "
        "Almost every model wires it this way, which is why the reserve sits at the busy centre of the map: "
        "it's the lever policymakers actually pull when something goes wrong."),
    4: ("Where the trouble starts",
        "Middle-East and US–Iran tension is a true root cause — nothing feeds into it, but it feeds almost "
        "everything else: reserve releases, the dollar, trader positioning, and the price directly. When this "
        "lights up it sets off several chains at once, which is why a single flare-up can move the forecast so much."),
    1: ("The chokepoint the conflict runs through",
        "Rising tension points straight at the Strait of Hormuz — the narrow waterway that carries about a "
        "fifth of the world's seaborne oil. From there it flows into both trader nerves and the price itself. "
        "It's the physical bottleneck that turns a diplomatic crisis into a real supply scare."),
    3: ("The barrels that fill the gap",
        "Russian and other non-OPEC oil is the swing that offsets — or amplifies — OPEC and geopolitics. "
        "Conflict and OPEC decisions push on it, and it lands on both the price and the world's storage tanks. "
        "This is the 'who actually ships the oil' part of the story once the politics are set."),
    5: ("A wildcard from the weather",
        "Hurricane season is a genuine wildcard — nothing causes it, but a big storm hits the price directly "
        "and knocks out US Gulf output. It's disconnected from the wars-and-rates machinery, so it doesn't "
        "move the everyday view; it just adds the odd chance of a sudden jolt."),
    6: ("China sets the demand temperature",
        "A strong world economy shows up first in China's factories, and China's appetite lands on both the "
        "price and trader positioning. This is the demand pulse of the whole system — hot China, warmer market; "
        "cooling China, and the air comes out."),
}


def main():
    mp = load_mapping(MAPPING)
    prose = PROSE
    pf = ROOT / "state" / f"prose_{mp.question_id}_{mp.tier.lower()}.json"
    if pf.exists():
        raw = json.loads(pf.read_text())
        prose = {int(k): tuple(v) for k, v in raw.get("prose", {}).items()}
        dv_name = raw.get("dv_name", "outcome")
    else:
        dv_name = "Brent price"
    uids = [u.uid for u in mp.unified]
    name = {u.uid: u.name for u in mp.unified}
    name[causal.DV] = dv_name
    code2uid = {(mid, m["code"]): u.uid for u in mp.unified
                for mid, mems in u.members.items() for m in mems}
    maxip = max(u.influence_points() for u in mp.unified) or 1
    w = {u.uid: u.influence_points() / maxip for u in mp.unified}
    w[causal.DV] = 1.0

    def edges_of(mid):
        _, d = request("GET", config.FOLDS_BASE + f"/models/{mid}",
                       headers={"Authorization": f"Bearer {config.FIFTYONEFOLDS_TOKEN}"})
        return d["data"].get("edges") or []

    print("fetching graphs ...")
    model_edges = {mid: edges_of(mid) for mid in mp.models}
    support = causal.build_consensus(model_edges, code2uid, len(mp.models))
    reach = causal.reach_to_dv(support, uids)
    inw, outw = causal.degrees(support)
    btw = causal.betweenness(support, uids)
    g = {u: w[u] * reach[u] for u in uids}
    roles = {u: causal.role(u, inw, outw, btw) for u in uids}

    frags = causal.select_fragments(support, g, uids, k=6)
    mx = frags[0]["importance"] if frags else 1

    def node(uid, sup=None):
        d = {"uid": uid, "label": name[uid], "influence": round(w[uid], 3),
             "outcome": uid == causal.DV}
        if sup is not None:
            d["support"] = round(sup, 3)
        return d

    fragments = []
    for f in frags:
        F = f["focal"]
        title, insight = prose.get(F, (name[F], ""))
        fragments.append({
            "id": f"frag-{F}", "focal_uid": F, "title": title, "insight": insight,
            "role": roles[F], "importance": round(100 * f["importance"] / mx),
            "aci": round(f["importance"], 3),
            "focal": node(F),
            "parents": [node(a, support[(a, F)]) for a in f["parents"]],
            "children": [node(b, support[(F, b)]) for b in f["children"]],
        })

    drivers = {u: {"ci": round(g[u], 3), "reach": round(reach[u], 3),
                   "role": roles[u], "betweenness": round(btw[u], 2)} for u in uids}

    out = {"question_id": mp.question_id, "tier": mp.tier,
           "drivers": drivers, "fragments": fragments}
    path = ROOT / "state" / f"causal_{mp.question_id}_{mp.tier.lower()}.json"
    path.write_text(json.dumps(out, indent=2))
    print("wrote", path)
    for f in fragments:
        print(f"  [{f['importance']:>3}] {f['title']}  ({f['role']})  "
              f"←{[p['label'] for p in f['parents']]} →{[c['label'] for c in f['children']]}")


if __name__ == "__main__":
    main()
