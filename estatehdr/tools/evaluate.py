"""Quality report for a batch output directory.

Usage:
  python tools/evaluate.py OUTPUT_DIR [--synthetic-gt data/synthetic] [--pairs AUTOHDR_DIR] [--out report_dir]

Reports per series: histogram, % clipped / crushed pixels, verticality of lines (degrees),
neutrality of white walls (CIEDE2000), window brightness and detail, halo, noise, sharpness;
with references (synthetic GT or AutoHDR exports of the same series): SSIM, ΔE2000, LPIPS.
Writes quality.json and quality.md.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.quality.evaluate import evaluate_output_dir, markdown_table  # noqa: E402


def synthetic_gt_map(gt_root: str, out_dir: str) -> dict:
    """Map output series names to synthetic GT scene folders using the dataset manifest."""
    man = os.path.join(gt_root, "manifest.json")
    if not os.path.exists(man):
        return {}
    with open(man) as fh:
        manifest = json.load(fh)
    with open(os.path.join(out_dir, "report.json")) as fh:
        report = json.load(fh)
    m = {}
    for s in report["series"]:
        first = os.path.basename(s["files"][0]) if s.get("files") else ""
        for ser in manifest["series"]:
            if first in ser["files"] and os.path.isdir(os.path.join(gt_root, "gt", ser["name"])):
                m[s["name"]] = os.path.join(gt_root, "gt", ser["name"])
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output_dir")
    ap.add_argument("--synthetic-gt", default=None)
    ap.add_argument("--pairs", default=None, help="folder with reference results (e.g. AutoHDR) named like the series")
    ap.add_argument("--out", default=None)
    ap.add_argument("--size", default="full")
    a = ap.parse_args()
    gt_map = synthetic_gt_map(a.synthetic_gt, a.output_dir) if a.synthetic_gt else None
    res = evaluate_output_dir(a.output_dir, gt_map, a.pairs, a.size)
    out = a.out or a.output_dir
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "quality.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=float)
    md = markdown_table(res)
    with open(os.path.join(out, "quality.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)


if __name__ == "__main__":
    main()
