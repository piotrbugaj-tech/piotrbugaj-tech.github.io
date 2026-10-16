"""Full-pipeline comparison of two configurations (e.g. before / after calibration).

Runs the complete pipeline on the same input with both configurations, evaluates every output
with the quality metrics (synthetic ground truth when available) and writes a Markdown table.

A configuration file that contains a ``presets`` section is a complete configuration and replaces
the built-in config.yaml for that run (so its own preset definitions are used); a partial file is
applied on top of config.yaml like ``--config``.

Usage:
  python tools/compare_configs.py --input data/synthetic/input --synthetic-gt data/synthetic \\
      --before reports/calibration/config_before_full.yaml --after config.yaml \\
      --out reports/calibration/full_pipeline.md [--preset neutral,airy,premium]
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.batch import run_batch  # noqa: E402
import estatehdr.config as C  # noqa: E402
from estatehdr.quality.evaluate import evaluate_output_dir  # noqa: E402
from tools.evaluate import synthetic_gt_map  # noqa: E402

COLS = [("clipped_excl_%", "przepalenia poza nieodzyskiwalnymi [%]", "min"),
        ("crushed_%", "zaczernienia [%]", "min"),
        ("median_luma", "mediana jasności", None),
        ("vert_med_deg", "pionowość, mediana [°]", "min"),
        ("wall_dE_auto", "neutralność jasnych powierzchni ΔE (auto)", "min"),
        ("wall_dE_gt", "neutralność ścian ΔE (GT)", "min"),
        ("wall_L_gt", "jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86)", None),
        ("win_L", "jasność widoku okna L* (cel 55-80)", None),
        ("win_clip_recov_%", "przepalenia okna odzyskiwalne [%]", "min"),
        ("win_detail_ratio", "detal okna / GT", None),
        ("halo_dL", "halo przy oknie ΔL* (cel < 4)", None),
        ("clipped_nonlight_%", "przepalenia poza światłami (GT) [%]", "min"),
        ("ssim", "SSIM do idealnej edycji", "max"),
        ("ms_ssim", "MS-SSIM do idealnej edycji", "max"),
        ("grad_ssim", "gradient-SSIM (krawędzie) do idealnej edycji", "max"),
        ("dE_ref", "ΔE2000 do idealnej edycji", "min")]


def load(cfg_path, preset):
    if cfg_path:
        with open(cfg_path, encoding="utf-8") as fh:
            full = "presets" in (yaml.safe_load(fh) or {})
        if full:  # complete configuration: use it as the built-in one
            old = C.DEFAULT_CONFIG_PATH
            C.DEFAULT_CONFIG_PATH = os.path.abspath(cfg_path)
            try:
                return C.load_config(None, preset)
            finally:
                C.DEFAULT_CONFIG_PATH = old
    return C.load_config(cfg_path, preset)


def run(cfg_path, preset, inp, out, gt_root):
    shutil.rmtree(out, ignore_errors=True)
    cfg = load(cfg_path, preset)
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
    md = ["# Pełny pipeline przed / po kalibracji", "",
          f"Wejście: `{a.input}`. Konfiguracja przed: `{a.before}`, po: `{a.after or 'config.yaml'}`. "
          "Ten sam kod, różnią się tylko parametry.", ""]
    summary = {}
    for preset in [p.strip() for p in a.preset.split(",") if p.strip()]:
        qb = run(a.before, preset, a.input, os.path.join(a.work, preset, "before"), a.synthetic_gt)
        qa = run(a.after, preset, a.input, os.path.join(a.work, preset, "after"), a.synthetic_gt)
        md += section(preset, qb, qa, summary)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    print("\n".join(md[:40]))


def section(preset, qb, qa, summary):
    names = [n for n in qb if n in qa]
    summary[preset] = {}
    md = [f"## Preset `{preset}`: średnie (serie z GT dla metryk GT)", "",
          "| metryka | przed | po | zmiana |", "|---|---|---|---|"]
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
        summary[preset][key] = {"before": mb, "after": mf}
    md += ["", f"### Preset `{preset}`: serie", "", "| seria | metryka | przed | po |", "|---|---|---|---|"]
    for n in names:
        for key, label, _ in COLS:
            b, f = qb[n]["summary"].get(key), qa[n]["summary"].get(key)
            if b is None and f is None:
                continue
            fmt = (lambda v: "—" if v is None else f"{v:.3f}")
            md.append(f"| {n} | {key} | {fmt(b)} | {fmt(f)} |")
    return md + [""]


if __name__ == "__main__":
    main()
