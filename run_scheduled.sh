#!/usr/bin/env bash
# Run one export script from cron / systemd, e.g.
#   ./run_scheduled.sh export_business_assets.py
#   ./run_scheduled.sh export_technical_assets_for_single_catalog.py --catalog-source "My Catalog Source"
#
# - runs from this folder, so export/ and logs/ (unless set in the config) end up here
# - uses ./.venv/bin/python if present, else python3 from PATH
# - skips the run if the same script is still running (one lock per script)
# - appends console output to logs/scheduler.log (per-run details are in logs/<export name>.log)
# - exits with the script's exit code (0 = success), so cron/systemd can report failures
set -u

cd "$(dirname "$(readlink -f "$0")")" || exit 1

if [ $# -lt 1 ] || [ ! -f "$1" ]; then
    echo "usage: $0 <export_script.py> [script options]" >&2
    exit 2
fi
script=$1

python=python3
[ -x .venv/bin/python ] && python=.venv/bin/python

mkdir -p logs
exec 9> "logs/.${script%.py}.lock"
if ! flock -n 9; then
    echo "$(date '+%F %T') SKIPPED $* (previous run still active)" >> logs/scheduler.log
    exit 0
fi

echo "$(date '+%F %T') START   $*" >> logs/scheduler.log
"$python" -u "$@" >> logs/scheduler.log 2>&1
rc=$?
echo "$(date '+%F %T') END     $* (exit $rc)" >> logs/scheduler.log
exit $rc
