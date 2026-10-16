"""Before/after comparisons for every preset (images + metrics table).

For each input set and preset (neutral, airy, premium) the full pipeline is run, then:
  reports/comparisons/<series>.jpg  - reference frame as shot | neutral | airy | premium
  reports/comparisons/README.md     - metrics per preset (histogram, clipping, verticality,
                                      wall neutrality / brightness, windows, SSIM to GT ...)
Usage:
  python tools/make_comparisons.py [--out reports/comparisons] [--work output/comparisons]
"""
import argparse
import json
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.batch import run_batch  # noqa: E402
from estatehdr.config import load_config  # noqa: E402
from estatehdr.quality.evaluate import evaluate_image, evaluate_output_dir, load_rgb, summarize  # noqa: E402
from tools.evaluate import synthetic_gt_map  # noqa: E402

PRESETS = ["neutral", "airy", "premium"]
SETS = [  # name, folder, overrides, synthetic GT root
    ("syntetyczne", "data/synthetic/input", [], "data/synthetic"),
    ("hdrplus", "data/public/hdrplus_semi/input", [], None),
    ("opencv", "data/public/opencv/input", [], None),
    ("portfolio_single", "data/public/portfolio/input", ["grouping.mode=single"], None),
]
PORTFOLIO_PICK = ["01.BtS2Hkmp", "k007.C8MVnAJ9", "k040.wqWqsOuE"]
COLS = ["clipped_%", "clipped_excl_%", "crushed_%", "median_luma", "vert_med_deg", "wall_dE_auto", "wall_dE_gt",
        "wall_L_gt", "win_L", "win_clip_%", "win_clip_recov_%", "win_detail", "halo_dL", "ssim", "ms_ssim", "dE_ref"]
BEFORE_COLS = ["clipped_%", "crushed_%", "median_luma", "vert_med_deg", "wall_dE_auto"]


def label(img, text):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (8 + 11 * len(text), 26), (0, 0, 0), -1)
    cv2.putText(out, text, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="reports/comparisons")
    ap.add_argument("--work", default="output/comparisons")
    ap.add_argument("--width", type=int, default=560)
    ap.add_argument("--reuse", action="store_true", help="re-evaluate finished outputs in --work instead of re-running")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tables = {p: {} for p in PRESETS}
    before = {}  # series -> metrics of the reference frame as shot (same tool, no GT)
    results = {}  # (set, series) -> {preset: result dict}
    for set_name, folder, overrides, gt_root in SETS:
        if not os.path.isdir(folder):
            print("skip (missing):", folder)
            continue
        files = None
        if set_name == "portfolio_single":
            files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                     if os.path.splitext(f)[0] in PORTFOLIO_PICK]
        for preset in PRESETS:
            out = os.path.join(a.work, preset, set_name)
            rep = None
            if a.reuse and os.path.exists(os.path.join(out, "report.json")):
                with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
                    rep = json.load(fh)
                rep = rep if rep.get("complete", True) else None
            if rep is None:
                shutil.rmtree(out, ignore_errors=True)
                cfg = load_config(None, preset, overrides)
                rep = run_batch(None if files else folder, out, cfg, files=files)
            gt_map = synthetic_gt_map(gt_root, out) if gt_root else None
            q = evaluate_output_dir(out, gt_map, max_side=2048)
            for s in rep["series"]:
                if s["status"] != "ok":
                    continue
                results.setdefault((set_name, s["name"]), {})[preset] = s
                if s["name"] in q:
                    tables[preset][f"{set_name}/{s['name']}"] = q[s["name"]]["summary"]
            print(f"{preset:8s} {set_name:16s} ok={rep['ok']} failed={rep['failed']} {rep['seconds']} s")
    # composites
    names = []
    for (set_name, series), per in results.items():
        if len(per) < len(PRESETS):
            continue
        first = next(iter(per.values()))
        bpath = first["outputs"].get("preview_before", {}).get("path")
        tiles = []
        if bpath and os.path.exists(bpath):
            tiles.append(label(cv2.imread(bpath), "przed (klatka ref.)"))
            before[f"{set_name}/{series}"] = summarize(evaluate_image(load_rgb(bpath, 2048)))
        for p in PRESETS:
            tiles.append(label(cv2.imread(per[p]["outputs"]["preview_after"]["path"]), p))
        h = min(t.shape[0] * a.width // t.shape[1] for t in tiles)
        tiles = [cv2.resize(t, (a.width, h), interpolation=cv2.INTER_AREA) for t in tiles]
        fn = f"{set_name}__{series}.jpg"
        cv2.imwrite(os.path.join(a.out, fn), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 84])
        names.append(fn)
    # markdown
    md = ["# Porównania przed / po dla presetów", "",
          "Wygenerowane przez `tools/make_comparisons.py` (pełny pipeline, metryki z `estatehdr/quality`).",
          "Kolumny: klip = % pikseli z kanałem ≥ 254, klip_excl = bez obszarów przepalonych w każdej klatce, "
          "zaczernienie = % ≤ 1, pion = mediana odchylenia linii pionowych [°], ściana ΔE = neutralność bieli "
          "(CIEDE2000; _gt = maska ścian z GT), win_L = L* widoku za oknem (bez nieodzyskiwalnych pikseli), "
          "ssim/dE_ref = zgodność z idealną edycją GT.", ""]
    md += ["## Przed: klatka referencyjna jak z aparatu (podgląd, te same metryki)", "",
           "| seria | " + " | ".join(BEFORE_COLS) + " |", "|---|" + "---|" * len(BEFORE_COLS)]
    for name, sm in before.items():
        md.append(f"| {name} | " + " | ".join("—" if sm.get(c) is None else f"{sm[c]:.3f}" for c in BEFORE_COLS) + " |")
    md.append("")
    for p in PRESETS:
        md += [f"## Po: preset `{p}`", "", "| seria | " + " | ".join(COLS) + " |", "|---|" + "---|" * len(COLS)]
        for name, sm in tables[p].items():
            vals = []
            for c in COLS:
                v = sm.get(c)
                vals.append("—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v))
            md.append(f"| {name} | " + " | ".join(vals) + " |")
        md.append("")
    md += ["## Zestawienia (przed | neutral | airy | premium)", ""] + [f"![{n}]({n})" for n in sorted(names)]
    with open(os.path.join(a.out, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.join(a.out, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump({**tables, "before": before}, fh, indent=1, default=float)
    print("written:", a.out)


if __name__ == "__main__":
    main()
