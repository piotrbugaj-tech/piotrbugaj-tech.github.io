#!/bin/bash
# Recompute every report in reports/ with the current code and configuration, then regenerate
# README section 6.  Sequential (about 1.5 h on 4 cores); performance runs last, alone.
# Needs the test data: python tools/make_synthetic.py && python tools/fetch_public_data.py
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
LOG=output/refresh_logs
mkdir -p "$LOG"
step() { echo "=== $(date +%H:%M:%S) $1"; }
step tests;       $PY -m pytest -q tests > "$LOG/tests.log" 2>&1; tail -1 "$LOG/tests.log"
step verify;      rm -rf output/verify_final; $PY tools/verify_hypotheses.py output/verify_final > "$LOG/verify.log" 2>&1; tail -1 "$LOG/verify.log"
step calibration; $PY tools/compare_configs.py --input data/synthetic/input --synthetic-gt data/synthetic \
                      --before reports/calibration/config_before_full.yaml --after config.yaml \
                      --preset neutral,airy,premium --out reports/calibration/full_pipeline.md > "$LOG/compare.log" 2>&1
                  tail -1 "$LOG/compare.log"
step comparisons; rm -f reports/comparisons/*.jpg; $PY tools/make_comparisons.py > "$LOG/comparisons.log" 2>&1; tail -1 "$LOG/comparisons.log"
step modules;     $PY tools/eval_modules.py > "$LOG/modules.log" 2>&1; tail -1 "$LOG/modules.log"
step portfolio;   $PY tools/do_no_harm.py > "$LOG/portfolio.log" 2>&1; tail -1 "$LOG/portfolio.log"
step perf;        $PY tools/measure_perf.py > "$LOG/perf.log" 2>&1; tail -3 "$LOG/perf.log"
step readme;      $PY tools/update_readme_metrics.py
step done
