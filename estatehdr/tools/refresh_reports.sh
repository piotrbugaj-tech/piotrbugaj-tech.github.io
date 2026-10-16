#!/bin/bash
# Recompute every report in reports/ with the current code and configuration, then regenerate
# README section 6.  Sequential (about 1.5 h on 4 cores); performance runs last, alone.  Stops at the
# first failing step, so README is never regenerated from a stale or partial report.
# Needs the test data: python tools/make_synthetic.py && python tools/fetch_public_data.py
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
LOG=output/refresh_logs
mkdir -p "$LOG"
run() {  # run NAME COMMAND...: log to $LOG/NAME.log, stop the whole refresh on failure
    local name=$1; shift
    echo "=== $(date +%H:%M:%S) $name"
    if ! "$@" > "$LOG/$name.log" 2>&1; then
        echo "step '$name' failed, see $LOG/$name.log"; tail -5 "$LOG/$name.log"; exit 1
    fi
    tail -1 "$LOG/$name.log"
}
run tests       $PY -m pytest -q tests
rm -rf output/verify_final
run verify      $PY tools/verify_hypotheses.py output/verify_final
run calibration $PY tools/compare_configs.py --input data/synthetic/input --synthetic-gt data/synthetic \
                    --before reports/calibration/config_before_full.yaml --after config.yaml \
                    --preset neutral,airy,premium --out reports/calibration/full_pipeline.md
run comparisons $PY tools/make_comparisons.py
run modules     $PY tools/eval_modules.py
run portfolio   $PY tools/do_no_harm.py
run perf        $PY tools/measure_perf.py
run readme      $PY tools/update_readme_metrics.py
echo "=== $(date +%H:%M:%S) done"
