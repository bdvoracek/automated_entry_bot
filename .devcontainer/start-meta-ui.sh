#!/usr/bin/env bash
# Runs on every Codespace start (postStartCommand): bring the Meta Mode UI back
# up on port 8765 and make that port public, so the forwarded URL "just works"
# after a stop/resume. Idempotent; safe to run by hand too.
cd /workspaces/automated_entry_bot || exit 0
# free the port if something's already bound (never pkill -f meta_ui.py — it
# matches this very shell and SIGTERMs it)
command -v fuser >/dev/null && fuser -k 8765/tcp 2>/dev/null || true
sleep 1
nohup python3 scripts/meta_ui.py > /tmp/meta_ui.log 2>&1 &
# portsAttributes already requests public; re-assert via gh once forwarding is up
( sleep 12; gh codespace ports visibility 8765:public -c "${CODESPACE_NAME:-}" >/dev/null 2>&1 || true ) &
exit 0
