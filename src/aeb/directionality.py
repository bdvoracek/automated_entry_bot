"""Driver Directionality Agent — generalizable prototype.

Establishes the semantic direction of each unified-driver member so Meta Mode can
move every member of a cluster the same way (see prompts/DriverDirectionalityAgent.md).

Pipeline (engine-agnostic — the LLM step is any callable str -> str):

    prompt = build_prompt(mapping, descriptors, question)
    reply  = llm(prompt)                       # Claude API, etc.
    dirs   = parse_directions(reply)           # {(model, code): +1|-1|0}
    apply_directions(mapping, dirs)            # writes dir/mode_dir/invert (deterministic)

`apply_directions` (mode = majority sign, invert = dir != 0 and dir != mode) is
the deterministic, unit-tested core. The current Brent/Advanced mapping was
produced by running the SECTION-3 reasoning by hand (an agent) and then this same
apply step; wiring a real LLM here reproduces it for any question/tier.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "DriverDirectionalityAgent.md"

_BEGIN, _END = "===DIRECTIONS_JSON===", "===END==="


def build_prompt(
    mapping: Any, descriptors: Mapping[tuple[str, str], dict], question: str,
) -> str:
    """Render the agent prompt: the spec + the clusters (with pole descriptors)."""
    clusters = []
    for u in mapping.unified:
        members = []
        for mid, mems in u.members.items():
            for m in mems:
                d = descriptors.get((mid, m["code"]), {})
                members.append({
                    "model": mid, "code": m["code"], "name": m["name"],
                    "descriptors": {
                        "Negligible": d.get("neg", ""), "Extreme": d.get("ext", ""),
                    },
                })
        clusters.append({"uid": u.uid, "name": u.name, "members": members})
    spec = PROMPT_PATH.read_text()
    payload = {"question": question, "clusters": clusters}
    return f"{spec}\n\n===INPUT===\n{json.dumps(payload, indent=1)}\n"


def parse_directions(reply: str) -> dict[tuple[str, str], int]:
    """Pull the DIRECTIONS_JSON block from an agent reply into {(model,code): dir}."""
    body = reply
    if _BEGIN in reply:
        body = reply.split(_BEGIN, 1)[1]
        body = body.split(_END, 1)[0]
    body = body.strip().strip("`")
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array found in agent reply")
    rows = json.loads(body[start:end + 1])
    out: dict[tuple[str, str], int] = {}
    for r in rows:
        d = int(r["dir"])
        if d not in (-1, 0, 1):
            raise ValueError(f"dir must be -1/0/1, got {d}")
        out[(r["model"], r["code"])] = d
    return out


def apply_directions(mapping_doc: dict, dirs: Mapping[tuple[str, str], int]) -> dict:
    """Write per-member `dir`, per-cluster `mode_dir`, and per-member `invert`
    into a mapping doc (the parsed JSON dict). Deterministic; returns the doc.

    mode_dir = majority sign among non-zero members (tie -> +1).
    invert   = dir != 0 and dir != mode_dir  (inverted members take -delta).
    """
    for u in mapping_doc["unified"]:
        signs = []
        for mid, mems in u["members"].items():
            for m in mems:
                m["dir"] = int(dirs.get((mid, m["code"]), 0))
                signs.append(m["dir"])
        pos = sum(1 for s in signs if s > 0)
        neg = sum(1 for s in signs if s < 0)
        u["mode_dir"] = 1 if pos >= neg else -1
        for mems in u["members"].values():
            for m in mems:
                m["invert"] = bool(m["dir"] != 0 and m["dir"] != u["mode_dir"])
    return mapping_doc


def run(
    mapping: Any, descriptors: Mapping[tuple[str, str], dict], question: str,
    llm: Callable[[str], str], mapping_doc: dict,
) -> dict:
    """Full pass: prompt -> llm -> parse -> apply. Returns the updated mapping doc."""
    reply = llm(build_prompt(mapping, descriptors, question))
    return apply_directions(mapping_doc, parse_directions(reply))
