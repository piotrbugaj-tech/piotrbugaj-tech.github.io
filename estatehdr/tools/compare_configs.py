"""Full-pipeline comparison of two configurations (e.g. before / after calibration).

Runs the complete pipeline on the same input with both configurations, evaluates every output
with the quality metrics (synthetic ground truth when available) and writes a Markdown table.

Usage:
  python tools/compare_configs.py --input data/synthetic/input --synthetic-gt data/synthetic \\
      --before reports/calibration/config_before.yaml --after config.yaml \\
      --out reports/calibration/full_pipeline.md [--preset neutral]
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.batch import run_batch  # noqa: E402
from estatehdr.config import load_config  # noqa: E402
from estatehdr.quality.evaluate import evaluate_output_dir  # noqa: E402
from tools.evaluate import synthetic_gt_map  # noqa: E402

COLS = [("clipped_excl_%", "przepalenia poza nieodzyskiwalnymi [%]", "min"),
        ("crushed_%", "zaczernienia [%]", "min"),
        ("median_luma", "mediana jasności", None),
        ("vert_med_deg", "pionowość, mediana [°]", "min"),
        ("wall_dE_auto", "neutralność jasnych powierzchni ΔE (auto)", "min"),
        ("wall_dE_gt", "neutralność ścian ΔE (GT)", "min"),
        ("wall_L_gt", "jasność ścian L* (GT; cel 78-88)", None),
        ("win_L", "jasność widoku okna L* (cel 55-80)", None),
        ("win_clip_recov_%", "przepalenia okna odzyskiwalne [%]", "min"),
        ("win_detail_ratio", "detal okna / GT", None),
        ("halo_dL", "halo przy oknie ΔL* (cel < 4)", None),
        ("clipped_nonlight_%", "przepalenia poza światłami (GT) [%]", "min"),
        ("ssim", "SSIM do idealnej edycji", "max"),
        ("dE_ref", "ΔE2000 do idealnej edycji", "min")]


def run(cfg_path, preset, inp, out, gt_root):
    shutil.rmtree(out, ignore_errors=True)
    cfg = load_config(cfg_path, preset)
    run_batch(inp, out, cfg)
    gt_map = synthetic_gt_map(gt_root, out) if gt_root else None
    q = evaluate_output_dir(out, gt_map)
    with open(os.path.join(out, "quality.json"), "w", encoding="utf-8") as fh:
        json.dump(q, fh, indent=1, default=float)
    return q


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--synthetic-gt", default=None)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", default=None)
    ap.add_argument("--preset", default="neutral")
    ap.add_argument("--work", default="output/compare_configs")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    qb = run(a.before, a.preset, a.input, os.path.join(a.work, "before"), a.synthetic_gt)
    qa = run(a.after, a.preset, a.input, os.path.join(a.work, "after"), a.synthetic_gt)
    names = [n for n in qb if n in qa]
    md = [f"# Pełny pipeline przed / po kalibracji (preset `{a.preset}`)", "",
          f"Wejście: `{a.input}`. Konfiguracja przed: `{a.before}`, po: `{a.after or 'config.yaml'}`. "
          "Ten sam kod, różnią się tylko parametry.", "",
          "## Średnie (serie z GT dla metryk GT)", "", "| metryka | przed | po | zmiana |", "|---|---|---|---|"]
    for key, label, better in COLS:
        b = [qb[n]["summary"].get(key) for n in names]
        f = [qa[n]["summary"].get(key) for n in names]
        pairs = [(x, y) for x, y in zip(b, f) if x is not None and y is not None]
        if not pairs:
            continue
        mb, mf = float(np.mean([p[0] for p in pairs])), float(np.mean([p[1] for p in pairs]))
        mark = ""
        if better == "min":
            mark = "lepiej" if mf < mb - 1e-3 else ("gorzej" if mf > mb + 1e-3 else "=")
        elif better == "max":
            mark = "lepiej" if mf > mb + 1e-3 else ("gorzej" if mf < mb - 1e-3 else "=")
        md.append(f"| {label} | {mb:.3f} | {mf:.3f} | {mark} |")
    md += ["", "## Serie", "", "| seria | metryka | przed | po |", "|---|---|---|---|"]
    for n in names:
        for key, label, _ in COLS:
            b, f = qb[n]["summary"].get(key), qa[n]["summary"].get(key)
            if b is None and f is None:
                continue
            fmt = (lambda v: "—" if v is None else f"{v:.3f}")
            md.append(f"| {n} | {key} | {fmt(b)} | {fmt(f)} |")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md[:24]))


if __name__ == "__main__":
    main()
