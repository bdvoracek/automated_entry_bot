"""Consensus causal graph + fragment selection (generalizable).

Each 51Folds model exposes a causal DAG (`edges`: parent->child, child "DV" = the
outcome). This module unifies the N per-model graphs into one consensus graph
(via the unification cluster-map), scores nodes, and selects the most important
causal *fragments* (ego-motifs with real fan-in/out) to present.

Metrics
  support(a->b)  fraction of models that wire the unified edge  (commonality)
  reach(n)       noisy-OR probability n propagates to the DV     (does it matter?)
  w(n)           normalised driver influence (rank-points x coverage)
  g(n)=w*reach   node causal influence
  role(n)        source | mediator | integrator | sink | driver  (from degree/betweenness)

Fragment importance = g(focal) x mean(edge commonality)  — focal-centered and
size-neutral, so a sink can't inherit its influential parents' weight.
"""
from __future__ import annotations

import collections
from typing import Any, Iterable, Mapping

EDGE_THRESH = 1 / 3          # keep unified edges present in >= 1/3 of models
DV = "DV"


def build_consensus(model_edges: Mapping[str, list[dict]], code2uid: Mapping[tuple, int],
                    n_models: int) -> dict[tuple, float]:
    """{(a,b): support} over unified nodes (ints) and the DV sentinel."""
    pm: dict[tuple, set] = collections.defaultdict(set)
    for mid, edges in model_edges.items():
        seen = set()
        for e in edges:
            p = code2uid.get((mid, e["parent"]))
            c = DV if e["child"] == DV else code2uid.get((mid, e["child"]))
            if p is not None and c is not None and p != c:
                seen.add((p, c))
        for pair in seen:
            pm[pair].add(mid)
    return {pair: len(ms) / n_models for pair, ms in pm.items()}


def _edges(support, thresh=EDGE_THRESH):
    return {e: s for e, s in support.items() if s >= thresh}


def reach_to_dv(support, uids, thresh=EDGE_THRESH, iters=80) -> dict:
    """Noisy-OR probability each node's influence reaches the DV."""
    E = _edges(support, thresh)
    childs = collections.defaultdict(list)
    for (a, b), s in E.items():
        childs[a].append((b, s))
    reach = {n: 0.0 for n in list(uids) + [DV]}
    reach[DV] = 1.0
    for _ in range(iters):
        for n in uids:
            prod = 1.0
            for c, s in childs[n]:
                prod *= (1 - s * reach[c])
            reach[n] = 1 - prod
    return reach


def degrees(support, thresh=EDGE_THRESH):
    inw, outw = collections.defaultdict(float), collections.defaultdict(float)
    for (a, b), s in _edges(support, thresh).items():
        outw[a] += s
        inw[b] += s
    return inw, outw


def betweenness(support, uids, thresh=EDGE_THRESH) -> dict:
    """Brandes betweenness on the thresholded consensus DAG (unweighted)."""
    E = _edges(support, thresh)
    adj = collections.defaultdict(list)
    for (a, b) in E:
        adj[a].append(b)
    alln = set(uids) | {DV}
    btw = {n: 0.0 for n in alln}
    for src in alln:
        S, P = [], {x: [] for x in alln}
        sig = dict.fromkeys(alln, 0.0); sig[src] = 1.0
        dist = dict.fromkeys(alln, -1); dist[src] = 0
        Q = collections.deque([src])
        while Q:
            v = Q.popleft(); S.append(v)
            for wn in adj[v]:
                if dist[wn] < 0:
                    dist[wn] = dist[v] + 1; Q.append(wn)
                if dist[wn] == dist[v] + 1:
                    sig[wn] += sig[v]; P[wn].append(v)
        d = dict.fromkeys(alln, 0.0)
        while S:
            wn = S.pop()
            for v in P[wn]:
                d[v] += (sig[v] / sig[wn]) * (1 + d[wn])
            if wn != src:
                btw[wn] += d[wn]
    return btw


def role(uid, inw, outw, btw) -> str:
    if inw[uid] < 0.5:
        return "source"
    if outw[uid] <= 1.2 and inw[uid] >= 3 and btw[uid] < 1:
        return "sink"
    if btw[uid] >= 5:
        return "mediator"
    if inw[uid] >= 3:
        return "integrator"
    return "driver"


def select_fragments(support, g, uids, k=6, thresh=EDGE_THRESH, max_wing=2) -> list[dict]:
    """Ego-motifs, focal-centered importance g(focal) x mean(edge support),
    greedily diversified (skip motifs that overlap a chosen one by Jaccard>0.6)."""
    E = _edges(support, thresh)
    cand = []
    for F in uids:
        par = sorted([a for a in uids if (a, F) in E], key=lambda a: -support[(a, F)])[:max_wing]
        ch = sorted([b for b in list(uids) + [DV] if (F, b) in E], key=lambda b: -support[(F, b)])[:max_wing]
        ed = [(a, F) for a in par] + [(F, b) for b in ch]
        if not ed:
            continue
        imp = g[F] * (sum(support[e] for e in ed) / len(ed))
        cand.append({"focal": F, "parents": par, "children": ch, "importance": imp,
                     "nodes": set([F] + par + ch)})
    cand.sort(key=lambda c: -c["importance"])
    chosen: list[dict] = []
    for c in cand:
        if any(len(c["nodes"] & o["nodes"]) / len(c["nodes"] | o["nodes"]) > 0.6 for o in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= k:
            break
    return chosen
