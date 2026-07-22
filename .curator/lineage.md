# Lineage log

Append-only, dated, SHA-pinned. Never edited in place. How the current state came to be;
the Atlas holds what is true now, this holds why. Off the always-loaded surface.

## 2026-07-22 624b590 | Curator bootstrap (run 1)

decision:   First Atlas built over a clean 4-commit repo. Recorded the two-pipeline
            architecture (production + exploration over a shared config/http base) as the
            core non-discoverable structural fact, since README documents only production.
supersedes: none (first run)
why:        Establish the current-state map and the CLAUDE.md trigger stub so future agents
            in this repo load the structure without re-deriving it.

## 2026-07-22 624b590 | Two decisions parked as contested, not forced

decision:   (1) README "Setup" documents 2 tokens while config.py exposes ~8 env knobs, and
            (2) the exploration pipeline has no in-repo doc. Both recorded as contested/draft
            in the Atlas rather than auto-fixed. Authoritative source for config is config.py.
supersedes: none
why:        Curator principle "park ambiguity" and "report gaps, do not guess": closing
            either gap is a generative doc-write that belongs to the human, not a custodial
            merge. Re-attempt each run; provisionally resolve after 3 stuck runs.
