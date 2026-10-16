"""'Do no harm' test (README section 6.5): finished photos from the public portfolio are processed in
single-image mode and compared with their inputs (SSIM, MS-SSIM, gradient-SSIM, CIEDE2000, clipping,
crushed blacks, verticality).  Writes reports/portfolio_do_no_harm.json.

Usage (from the project root, after ``python tools/fetch_public_data.py``):
  python tools/do_no_harm.py [--input data/public/portfolio/input] [--out output/portfolio_final]
                             [--workers 2] [--reuse]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from estatehdr.quality.evaluate import summarize  # noqa: E402

KEYS = ("ssim", "ms_ssim", "grad_ssim", "dE_ref", "wall_dE_auto", "median_luma", "clipped_excl_%", "crushed_%",
        "vert_med_deg")


def stats(v):
    v = np.asarray(v, float)
    return {"median": round(float(np.median(v)), 3), "mean": round(float(v.mean()), 3),
            "p10": round(float(np.percentile(v, 10)), 3), "p90": round(float(np.percentile(v, 90)), 3),
            "min": round(float(v.min()), 3), "max": round(float(v.max()), 3)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=os.path.join(ROOT, "data", "public", "portfolio", "input"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "portfolio_final"))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--reuse", action="store_true", help="evaluate an existing output folder")
    a = ap.parse_args(argv)
    py = sys.executable
    if not (a.reuse and os.path.exists(os.path.join(a.out, "report.json"))):
        shutil.rmtree(a.out, ignore_errors=True)
        # exit code 2 = some photo failed: still evaluated, and counted in "failed" / "inputs"
        r = subprocess.run([py, "-m", "estatehdr", "process", a.input, "-o", a.out, "--single", "--workers",
                            str(a.workers)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode not in (0, 2):
            sys.exit(f"estatehdr process failed with exit code {r.returncode}")
    subprocess.run([py, os.path.join(ROOT, "tools", "evaluate.py"), a.out, "--pairs", a.input], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(a.out, "report.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    if not rep.get("complete", True) or rep.get("pending"):
        sys.exit(f"{a.out}: the batch is incomplete (pending {len(rep.get('pending') or [])}); run without --reuse")
    inputs = len(rep.get("series") or []) + len(rep.get("unreadable") or [])  # every photo, failed ones too
    with open(os.path.join(a.out, "quality.json"), encoding="utf-8") as fh:
        rows = {k: summarize(v) for k, v in json.load(fh).items()}
    ssim = sorted(((n, r["ssim"]) for n, r in rows.items() if r.get("ssim") is not None), key=lambda t: t[1])
    out = {"what": f"tryb jednej klatki na {len(rows)} gotowych zdjęciach portfolio (finalna konfiguracja), "
                   "wynik porównany z wejściem",
           "ok": rep.get("ok"), "failed": rep.get("failed"), "seconds": rep.get("seconds"), "workers": a.workers,
           "metrics": {k: stats([r[k] for r in rows.values() if r.get(k) is not None]) for k in KEYS},
           "ssim_below_0.85": int(sum(s < 0.85 for _, s in ssim)), "images": len(rows), "inputs": inputs,
           "worst_ssim": [[n, round(s, 3)] for n, s in ssim[:8]]}
    path = os.path.join(ROOT, "reports", "portfolio_do_no_harm.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    m = out["metrics"]
    print(f"{out['ok']}/{inputs} ok; SSIM median {m['ssim']['median']}, below 0.85: {out['ssim_below_0.85']}; "
          f"dE mean {m['dE_ref']['mean']}")


if __name__ == "__main__":
    main()
