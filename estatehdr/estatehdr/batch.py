"""Batch processing of a folder: grouping, parallel workers, report."""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from .config import Config
from .grouping import Group, load_groups, save_groups, scan_folder

log = logging.getLogger(__name__)


def estimate_series_bytes(group: Group) -> int:
    """Peak memory estimate of one series (decoded frames + float buffers)."""
    px = 0
    for f in group.frames:
        if f.width and f.height:
            px = max(px, f.width * f.height)
    if not px:
        px = 24_000_000
    n = len(group.frames)
    bytes_per_frame = 6 if any(f.kind in ("raw", "tiff") for f in group.frames) else 3
    # decoded frames + radiance (12) + display image (12) + temporaries (~24)
    return int(px * (n * bytes_per_frame + 48)) + 300_000_000


def available_memory() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except Exception:
        return 8 << 30


def plan_workers(groups: list[Group], cfg: Config) -> int:
    rcfg = cfg.get("runtime", {})
    cpu = os.cpu_count() or 2
    req = rcfg.get("workers", "auto")
    mem_limit = rcfg.get("memory_limit_gb", "auto")
    budget = int(float(mem_limit) * (1 << 30)) if mem_limit not in (None, "auto") else int(available_memory() * 0.75)
    peak = max((estimate_series_bytes(g) for g in groups), default=1 << 30)
    by_mem = max(1, budget // max(peak, 1))
    if req not in (None, "auto"):
        return max(1, min(int(req), len(groups) or 1))
    # leave some cores for OpenCV's own threads inside each worker
    return max(1, min(len(groups) or 1, by_mem, max(1, cpu // 2)))


def _worker_init(threads: int, log_level: int):
    import cv2
    cv2.setNumThreads(max(1, threads))
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(processName)s %(name)s: %(message)s")


def _run_one(group: Group, cfg_dict: dict, out_dir: str, masks: dict | None, queue=None, index: int = 0):
    from .pipeline import process_group
    def report(frac, msg):
        try:
            queue.put_nowait({"series": group.name, "index": index, "frac": frac, "stage": msg})
        except Exception:
            pass
    return process_group(group, Config(cfg_dict), out_dir, progress=report if queue is not None else None,
                         extra_masks=masks)


def run_batch(input_dir: str | None, out_dir: str, cfg: Config, groups_file: str | None = None,
              files: list[str] | None = None, progress_cb=None, masks: dict | None = None) -> dict:
    """Group + process everything; returns the report dict (also written to report.json)."""
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    failures = []
    if groups_file:
        groups = load_groups(groups_file, base=input_dir)
    else:
        from .grouping import group_frames
        from .io.metadata import read_metadata
        if files:
            metas = []
            for p in files:
                try:
                    metas.append(read_metadata(p))
                except Exception as exc:
                    failures.append({"file": p, "error": str(exc)})
            groups = group_frames(metas, cfg.get("grouping", {}))
        else:
            groups, failures = scan_folder(input_dir, cfg.get("grouping", {}), bool(cfg.get("input", {}).get("recursive", True)))
    save_groups(groups, os.path.join(out_dir, "groups.json"))
    if not groups:
        log.warning("no images found")
    workers = plan_workers(groups, cfg)
    cpu = os.cpu_count() or 2
    threads = cfg.get("runtime", {}).get("opencv_threads", "auto")
    threads = int(threads) if threads not in (None, "auto") else max(1, cpu // workers)
    log.info("processing %d series with %d worker(s), %d OpenCV thread(s) each", len(groups), workers, threads)
    results = []
    done = 0
    if workers <= 1:
        import cv2
        cv2.setNumThreads(threads)
        from .pipeline import process_group
        for i, g in enumerate(groups):
            def prog(frac, msg, _i=i, _g=g):
                if progress_cb:
                    progress_cb({"series": _g.name, "index": _i, "total": len(groups), "frac": frac, "stage": msg})
            r = process_group(g, cfg, out_dir, progress=prog, extra_masks=(masks or {}).get(g.name))
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb({"series": g.name, "index": i, "total": len(groups), "frac": 1.0, "stage": "gotowe",
                             "result": r})
    else:
        ctx = mp.get_context("spawn")
        mgr = ctx.Manager() if progress_cb else None
        queue = mgr.Queue() if mgr else None

        def drain():
            while queue is not None:
                try:
                    ev = queue.get_nowait()
                except Exception:
                    return
                ev["total"] = len(groups)
                try:
                    progress_cb(ev)
                except Exception:
                    pass
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_worker_init,
                                     initargs=(threads, logging.getLogger().level or logging.INFO)) as ex:
                futs = {ex.submit(_run_one, g, dict(cfg), out_dir, (masks or {}).get(g.name), queue, i): (i, g)
                        for i, g in enumerate(groups)}
                pending = set(futs)
                while pending:
                    finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    drain()
                    for fut in finished:
                        i, g = futs[fut]
                        try:
                            r = fut.result()
                        except Exception as exc:  # worker crash (e.g. killed by the OS)
                            r = {"name": g.name, "status": "error", "error": f"worker crashed: {exc}",
                                 "files": [f.path for f in g.frames]}
                        results.append(r)
                        done += 1
                        if progress_cb:
                            progress_cb({"series": g.name, "index": i, "total": len(groups), "frac": 1.0,
                                         "stage": "gotowe", "result": r})
                drain()
        finally:
            if mgr is not None:
                mgr.shutdown()
    order = {g.name: i for i, g in enumerate(groups)}
    results.sort(key=lambda r: order.get(r["name"], 0))
    try:
        import resource
        peak = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        peak_gb = round(peak / (1 << 20), 2)  # ru_maxrss is in KiB on Linux
    except Exception:
        peak_gb = None
    report = {
        "input": input_dir, "output": out_dir, "preset": cfg.get("preset"), "peak_rss_gb": peak_gb,
        "series": results, "unreadable": failures,
        "ok": sum(r["status"] == "ok" for r in results),
        "failed": sum(r["status"] != "ok" for r in results) + len(failures),
        "seconds": round(time.time() - t0, 1), "workers": workers,
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    log.info("done: %d ok, %d failed in %.1fs -> %s", report["ok"], report["failed"], report["seconds"], out_dir)
    return report
