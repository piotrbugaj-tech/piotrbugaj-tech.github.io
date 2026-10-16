"""Calibration of the look parameters.

Without reference pairs (default) the parameters are tuned against the measurable targets
derived from the product descriptions (SPEC.md, REVERSE.md section 5), measured on the synthetic
scenes with ground truth:
  white-wall neutrality (CIEDE2000 <= 2.5), wall brightness (L* 78-88 for neutral),
  window view brightness (L* 55-80), recoverable window clipping, clipping outside lights,
  halos at window frames; plus CIEDE2000 / SSIM to the "ideal edit" as a weak regulariser.
With --pairs DIR (e.g. AutoHDR exports named like the series) the objective is the 1:1
distance to those references after registration: mean CIEDE2000 + 10 x (1 - SSIM)
(+ 5 x LPIPS when torch/lpips are installed).

The expensive stages (load, align, merge, lens) run once per series; every evaluation re-runs
the real pipeline from window detection to geometry (pipeline.finish) with the candidate
parameters.  Optimiser: coordinate search with step halving (deterministic).

Usage:
  python tools/calibrate.py --input data/synthetic/input --synthetic-gt data/synthetic \\
      [--preset neutral] [--pairs DIR] [--rounds 3] [--out reports/calibration]
Writes calibration.json (trajectory), calibrated.yaml (parameters that differ from config.yaml, usable with
`--config`) and calibration.md (metrics before / after).
"""
import argparse
import copy
import json
import logging
import os
import sys
import time

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.config import load_config  # noqa: E402
from estatehdr.grouping import scan_folder  # noqa: E402
from estatehdr.imgutil import resize_max  # noqa: E402
from estatehdr.pipeline import finish, prepare  # noqa: E402
from estatehdr.quality.evaluate import evaluate_image, load_rgb, summarize, window_unrecoverable  # noqa: E402

log = logging.getLogger("calibrate")

# name, lower, upper, initial step
PARAMS = [
    ("white_balance.target_cct", 5000.0, 7500.0, 400.0),
    ("white_balance.global_strength", 0.5, 1.0, 0.1),
    ("white_balance.mixed_light_strength", 0.0, 1.0, 0.2),
    ("white_balance.tint_strength", 0.2, 1.0, 0.2),
    ("white_balance.max_local_shift", 0.5, 2.0, 0.3),
    ("tonemap.target_key", 0.45, 0.70, 0.04),
    ("tonemap.compress_shadows", 0.5, 0.95, 0.08),
    ("tonemap.compress_highlights", 0.4, 0.9, 0.08),
    ("windows.exterior_target", 0.45, 0.75, 0.05),
]
WALL_L = {"neutral": (78, 88), "airy": (84, 92), "premium": (74, 86)}
WIN_L = {"neutral": (55, 80), "airy": (55, 80), "premium": (45, 70)}


def get(cfg, key):
    d = cfg
    for k in key.split("."):
        d = d[k]
    return d


def put(cfg, key, value):
    d = cfg
    ks = key.split(".")
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    d[ks[-1]] = value


def band(x, lo, hi):
    if x is None:
        return 0.0
    return max(0.0, lo - x) + max(0.0, x - hi)


class Series:
    def __init__(self, group, cfg, ref, labels, win_unrec):
        self.group = group
        self.result = {"name": group.name, "warnings": []}
        self.prep = prepare(group, cfg, self.result)
        self.ref, self.labels, self.win_unrec = ref, labels, win_unrec


def run_one(s: Series, cfg) -> dict:
    res = {"name": s.group.name, "warnings": []}
    img = finish(s.prep.copy(), s.group, cfg, res, export=False)
    img, _ = resize_max(img, 1400)
    ev = evaluate_image(img, s.ref, s.labels, 0.0, s.win_unrec)
    ev["summary"] = summarize(ev)
    return ev


def objective(evals: dict, preset: str, pairs: bool) -> tuple[float, dict]:
    terms = {}
    for name, ev in evals.items():
        sm = ev["summary"]
        if pairs:
            t = {"dE_ref": sm.get("dE_ref") or 0.0, "ssim": 10 * (1 - (sm.get("ssim") or 0.0))}
            if sm.get("lpips") is not None:
                t["lpips"] = 5 * sm["lpips"]
        else:
            wl = WALL_L.get(preset, WALL_L["neutral"])
            vl = WIN_L.get(preset, WIN_L["neutral"])
            t = {
                "wall_dE": 1.0 * max(0.0, (sm.get("wall_dE_gt") or 0.0) - 2.5),
                "wall_L": 0.3 * band(sm.get("wall_L_gt"), *wl),
                "win_L": 0.3 * band(sm.get("win_L"), *vl),
                "win_clip": 0.5 * max(0.0, (sm.get("win_clip_recov_%") or 0.0) - 2.0),
                "clip": 2.0 * max(0.0, (sm.get("clipped_nonlight_%") or 0.0) - 0.3),
                "halo": 0.5 * max(0.0, (sm.get("halo_dL") or 0.0) - 3.0),
                "dE_ref": 0.1 * (sm.get("dE_ref") or 0.0),
                "ssim": 2.0 * (1 - (sm.get("ssim") or 0.0)),
            }
        terms[name] = t
    total = float(np.mean([sum(t.values()) for t in terms.values()]))
    return total, terms


def evaluate_all(series, cfg, preset, pairs):
    evals = {s.group.name: run_one(s, cfg) for s in series}
    loss, terms = objective(evals, preset, pairs)
    return loss, terms, evals


def table(before: dict, after: dict, cols) -> str:
    lines = ["| seria | metryka | przed | po |", "|---|---|---|---|"]
    for name in before:
        for c in cols:
            b = before[name]["summary"].get(c)
            a = after[name]["summary"].get(c)
            f = (lambda v: "—" if v is None else f"{v:.3f}")
            lines.append(f"| {name} | {c} | {f(b)} | {f(a)} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="folder with the bracket series")
    ap.add_argument("--synthetic-gt", default=None, help="synthetic dataset root (manifest.json + gt/)")
    ap.add_argument("--pairs", default=None, help="reference results named like the series (e.g. AutoHDR)")
    ap.add_argument("--preset", default="neutral")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--base-config", default=None,
                    help="YAML with the starting (\"before\") values; default: config.yaml as it is")
    ap.add_argument("--out", default="reports/calibration")
    ap.add_argument("--params", default=None,
                    help="comma-separated subset of the tuned keys (default: all), e.g. tonemap.target_key,windows.exterior_target")
    ap.add_argument("--bound", action="append", default=[], metavar="KEY=LO:HI",
                    help="override the search interval of a key, e.g. tonemap.target_key=0.5:0.85")
    a = ap.parse_args()
    global PARAMS
    bounds = {}
    for b in a.bound:
        k, _, rng = b.partition("=")
        lo, _, hi = rng.partition(":")
        bounds[k.strip()] = (float(lo), float(hi))
    keep = [k.strip() for k in a.params.split(",") if k.strip()] if a.params else None
    unknown = (set(keep or []) | set(bounds)) - {p[0] for p in PARAMS}
    if unknown:
        ap.error(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    PARAMS = [(k, *bounds.get(k, (lo, hi)), st) for k, lo, hi, st in PARAMS if keep is None or k in keep]
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)
    if not a.synthetic_gt and not a.pairs:
        ap.error("need --synthetic-gt or --pairs")
    cfg0 = load_config(a.base_config, a.preset)
    groups, _ = scan_folder(a.input, cfg0.get("grouping", {}))
    manifest = {}
    if a.synthetic_gt:
        with open(os.path.join(a.synthetic_gt, "manifest.json")) as fh:
            manifest = json.load(fh)
    series = []
    for g in groups:
        ref = labels = win_unrec = None
        if a.pairs:
            cand = sorted(f for f in os.listdir(a.pairs) if os.path.splitext(f)[0].startswith(g.name))
            if cand:
                ref = load_rgb(os.path.join(a.pairs, cand[0]), 1400)
        elif manifest:
            first = os.path.basename(g.frames[0].path)
            for ser in manifest["series"]:
                gdir = os.path.join(a.synthetic_gt, "gt", ser["name"])
                if first in ser["files"] and os.path.exists(os.path.join(gdir, "reference_ideal.png")):
                    import cv2
                    ref = load_rgb(os.path.join(gdir, "reference_ideal.png"), 1400)
                    labels = cv2.imread(os.path.join(gdir, "labels_ideal.png"), cv2.IMREAD_GRAYSCALE)
                    win_unrec = window_unrecoverable(gdir, [f.path for f in g.frames])
        if ref is None:
            continue
        log.info("preparing %s (%d frames)", g.name, len(g.frames))
        series.append(Series(g, cfg0, ref, labels, win_unrec))
    if not series:
        sys.exit("no series with a reference / ground truth")
    pairs = bool(a.pairs)
    t0 = time.time()
    cfg = copy.deepcopy(dict(cfg0))
    best, terms, evals0 = evaluate_all(series, cfg, a.preset, pairs)
    log.info("start: loss %.4f", best)
    traj = [{"step": 0, "loss": best, "params": {k: get(cfg, k) for k, *_ in PARAMS}, "terms": terms}]
    steps = {k: s for k, _, _, s in PARAMS}
    for rnd in range(a.rounds):
        improved = False
        for key, lo, hi, _ in PARAMS:
            cur = float(get(cfg, key))
            trial_best = None
            for sign in (+1, -1):
                v = float(np.clip(cur + sign * steps[key], lo, hi))
                if abs(v - cur) < 1e-9:
                    continue
                c2 = copy.deepcopy(cfg)
                put(c2, key, round(v, 4))
                loss, t2, _ = evaluate_all(series, c2, a.preset, pairs)
                log.info("round %d  %-36s %.4g -> %.4g : loss %.4f (best %.4f)", rnd + 1, key, cur, v, loss, best)
                if loss < best - 1e-4 and (trial_best is None or loss < trial_best[0]):
                    trial_best = (loss, c2, t2, v)
            if trial_best:
                best, cfg, terms = trial_best[0], trial_best[1], trial_best[2]
                improved = True
                traj.append({"step": len(traj), "round": rnd + 1, "param": key, "value": trial_best[3],
                             "loss": best, "terms": terms})
                # pattern search: keep going in the successful direction while it improves
                direction = 1.0 if trial_best[3] > cur else -1.0
                for _ in range(4):
                    v0 = float(get(cfg, key))
                    v = float(np.clip(v0 + direction * steps[key], lo, hi))
                    if abs(v - v0) < 1e-9:
                        break
                    c2 = copy.deepcopy(cfg)
                    put(c2, key, round(v, 4))
                    loss, t2, _ = evaluate_all(series, c2, a.preset, pairs)
                    log.info("round %d  %-36s %.4g -> %.4g : loss %.4f (best %.4f) [continue]", rnd + 1, key, v0, v,
                             loss, best)
                    if loss < best - 1e-4:
                        best, cfg, terms = loss, c2, t2
                        traj.append({"step": len(traj), "round": rnd + 1, "param": key, "value": v,
                                     "loss": best, "terms": terms})
                    else:
                        break
        for k in steps:
            steps[k] /= 2.0
        if not improved and rnd > 0:
            break
    _, _, evals1 = evaluate_all(series, cfg, a.preset, pairs)
    os.makedirs(a.out, exist_ok=True)
    # every calibrated value that differs from the built-in config (so a run continued from
    # --base-config still yields one self-contained file usable with --config)
    builtin = load_config(None, a.preset)
    changed = {}
    for key, *_ in PARAMS:
        v0, v1 = get(builtin, key), get(cfg, key)
        if abs(float(v0) - float(v1)) > 1e-9:
            put(changed, key, v1)
    with open(os.path.join(a.out, "calibrated.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"# tools/calibrate.py ({'pairs' if pairs else 'synthetic GT + targets'}), preset {a.preset}\n")
        default = load_config(None, None)["preset"]
        if a.preset != default:
            # a preset's own values go to its section: the user file's 'presets' are merged before
            # the preset is applied, so they win even where they equal a base default (D-33)
            changed = {"presets": {a.preset: {"overrides": changed}}}
        yaml.safe_dump(changed, fh, allow_unicode=True, sort_keys=False)
    with open(os.path.join(a.out, "calibration.json"), "w", encoding="utf-8") as fh:
        json.dump({"preset": a.preset, "mode": "pairs" if pairs else "synthetic", "seconds": round(time.time() - t0, 1),
                   "loss_before": traj[0]["loss"], "loss_after": best, "trajectory": traj,
                   "params_before": {k: get(cfg0, k) for k, *_ in PARAMS},
                   "params_after": {k: get(cfg, k) for k, *_ in PARAMS}}, fh, indent=1, default=float)
    cols = ["wall_dE_gt", "wall_L_gt", "win_L", "win_clip_recov_%", "clipped_nonlight_%", "halo_dL", "ssim", "dE_ref"] \
        if not pairs else ["ssim", "dE_ref", "lpips"]
    md = [f"# Kalibracja ({'pary referencyjne' if pairs else 'cele z opisu + GT syntetyczne'}), preset `{a.preset}`\n",
          f"Funkcja celu: {traj[0]['loss']:.4f} -> {best:.4f} ({len(traj) - 1} zaakceptowanych kroków, "
          f"{time.time() - t0:.0f} s).\n", "| parametr | przed | po |", "|---|---|---|"]
    for key, *_ in PARAMS:
        md.append(f"| {key} | {get(cfg0, key)} | {get(cfg, key)} |")
    md += ["", table(evals0, evals1, cols)]
    with open(os.path.join(a.out, "calibration.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
