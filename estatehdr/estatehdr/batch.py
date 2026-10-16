"""Batch processing of a folder: grouping, parallel workers, report."""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool

from .config import Config
from .grouping import Group, load_groups, save_groups, scan_folder, unique_names
from .io.metadata import RAW_MIN_PIXELS

log = logging.getLogger(__name__)


def frame_pixels(f) -> int:
    """Pixel count for the memory estimate (0 = unknown)."""
    px = (f.width or 0) * (f.height or 0)
    if f.kind == "raw" and px < RAW_MIN_PIXELS:
        return 24_000_000  # only a preview size is known: assume a typical sensor
    return px


def estimate_series_bytes(group: Group) -> int:
    """Peak memory estimate of one series (decoded frames + float buffers)."""
    px = max((frame_pixels(f) for f in group.frames), default=0) or 24_000_000
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


def quiet_opencv(verbose: bool = False):
    """Native OpenCV / libtiff warnings ('[ WARN:0@0.4] global grfmt_tiff.cpp:123 TIFF_Warning ...') bypass
    Python logging and flood stderr: errors only (warnings kept with -v).  The environment variable
    reaches worker processes started later; an OPENCV_LOG_LEVEL set by the user wins."""
    if os.environ.get("OPENCV_LOG_LEVEL"):
        return  # OpenCV reads it itself at import
    os.environ["OPENCV_LOG_LEVEL"] = "WARNING" if verbose else "ERROR"
    try:
        import cv2
        lg = cv2.utils.logging
        lg.setLogLevel(lg.LOG_LEVEL_WARNING if verbose else lg.LOG_LEVEL_ERROR)
    except Exception:  # builds without cv2.utils.logging: the variable covers processes started later
        pass


WORKER_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(processName)s %(name)s: %(message)s"


def _worker_init(threads: int, log_level: int, log_files: tuple = ()):
    """Worker process setup: OpenCV threads, quiet native logging and the parent's log files
    (estatehdr.log), appended to, so per-series lines and errors reach them too."""
    quiet_opencv(log_level <= logging.DEBUG)
    import cv2
    cv2.setNumThreads(max(1, threads))
    handlers = [logging.StreamHandler()]
    for p in log_files:
        try:
            handlers.append(logging.FileHandler(p, mode="a", encoding="utf-8"))
        except OSError:
            pass  # a log file that cannot be opened must not break the worker
    logging.basicConfig(level=log_level, format=WORKER_LOG_FORMAT, handlers=handlers, force=True)


CRASH_ENV = "ESTATEHDR_TEST_CRASH_SERIES"  # tests only: the named series kills its process
WORKER_CRASHED = "worker crashed (out of memory or native crash)"


def _test_crash_hook(group: Group):
    if os.environ.get(CRASH_ENV) == group.name:
        os._exit(1)


def _run_one(group: Group, cfg_dict: dict, out_dir: str, masks: dict | None, queue=None, index: int = 0):
    from .pipeline import process_group
    _test_crash_hook(group)

    def report(frac, msg):
        try:
            queue.put_nowait({"series": group.name, "index": index, "frac": frac, "stage": msg})
        except Exception:
            pass
    return process_group(group, Config(cfg_dict), out_dir, progress=report if queue is not None else None,
                         extra_masks=masks)


def _error_result(g: Group, msg: str) -> dict:
    return {"name": g.name, "status": "error", "error": msg, "files": [f.path for f in g.frames],
            "warnings": list(g.warnings), "outputs": {}}


def _write_json(path: str, data: dict):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    os.replace(tmp, path)  # never leave a half-written report behind


def run_batch(input_dir: str | None, out_dir: str, cfg: Config, groups_file: str | None = None,
              files: list[str] | None = None, progress_cb=None, masks: dict | None = None) -> dict:
    """Group + process everything; returns the report dict (also written to report.json, after
    every finished series with ``complete: false`` and at the end with ``complete: true``)."""
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    failures, skipped = [], []
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
                    log.warning("skipping %s: %s", p, exc)
            groups = group_frames(metas, cfg.get("grouping", {}))
        else:
            groups, failures = scan_folder(input_dir, cfg.get("grouping", {}),
                                           bool(cfg.get("input", {}).get("recursive", True)),
                                           exclude=[out_dir], skipped=skipped)
    unique_names(groups)  # outputs are named after the series
    save_groups(groups, os.path.join(out_dir, "groups.json"), base=input_dir)
    if not groups:
        log.warning("no images found")
    workers = plan_workers(groups, cfg)
    cpu = os.cpu_count() or 2
    threads_cfg = cfg.get("runtime", {}).get("opencv_threads", "auto")
    threads = int(threads_cfg) if threads_cfg not in (None, "auto") else max(1, cpu // workers)
    log.info("processing %d series with %d worker(s), %d OpenCV thread(s) each", len(groups), workers, threads)
    results = {}  # index -> result
    report_path = os.path.join(out_dir, "report.json")

    def build_report(complete: bool) -> dict:
        res = [results[i] for i in sorted(results)]
        try:
            import resource
            peak = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
            peak_gb = round(peak / (1 << 20), 2)  # ru_maxrss is in KiB on Linux
        except Exception:
            peak_gb = None
        return {
            "input": input_dir, "output": out_dir, "preset": cfg.get("preset"), "peak_rss_gb": peak_gb,
            "complete": complete, "series": res, "unreadable": failures, "skipped": skipped,
            "pending": [g.name for i, g in enumerate(groups) if i not in results],
            "ok": sum(r["status"] == "ok" for r in res),
            "failed": sum(r["status"] != "ok" for r in res) + len(failures),
            "seconds": round(time.time() - t0, 1), "workers": workers,
        }

    def finished(i: int, g: Group, r: dict):
        results[i] = r
        if r.get("status") != "ok":  # always in the parent's log, whatever happened in the worker
            log.error("[%s] series failed: %s", g.name, r.get("error"))
        _write_json(report_path, build_report(False))
        if progress_cb:
            progress_cb({"series": g.name, "index": i, "total": len(groups), "frac": 1.0, "stage": "gotowe",
                         "result": r})

    _write_json(report_path, build_report(False))
    if workers <= 1:
        import cv2
        cv2.setNumThreads(threads)
        from .pipeline import process_group
        for i, g in enumerate(groups):
            def prog(frac, msg, _i=i, _g=g):
                if progress_cb:
                    progress_cb({"series": _g.name, "index": _i, "total": len(groups), "frac": frac, "stage": msg})
            _test_crash_hook(g)
            finished(i, g, process_group(g, cfg, out_dir, progress=prog, extra_masks=(masks or {}).get(g.name)))
    else:
        _run_pool(groups, cfg, out_dir, masks, workers, threads, progress_cb, finished)
    report = build_report(True)
    _write_json(report_path, report)
    log.info("done: %d ok, %d failed in %.1fs -> %s", report["ok"], report["failed"], report["seconds"], out_dir)
    return report


def _run_pool(groups, cfg, out_dir, masks, workers, threads, progress_cb, finished):
    """Worker processes.  If one dies (OOM kill, native crash), the pool breaks and every
    unfinished series raises BrokenProcessPool: those are re-run one by one, each in a fresh
    single-worker pool, so only the series that really kills its worker is reported."""
    ctx = mp.get_context("spawn")
    mgr = ctx.Manager() if progress_cb else None
    queue = mgr.Queue() if mgr else None
    level = logging.getLogger().level or logging.INFO
    log_files = tuple(h.baseFilename for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler))

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

    def run(items, n_workers, n_threads) -> list:
        """Run (index, group) items in one pool; returns the items lost to a broken pool."""
        lost = []
        with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx, initializer=_worker_init,
                                 initargs=(n_threads, level, log_files)) as ex:
            futs = {ex.submit(_run_one, g, dict(cfg), out_dir, (masks or {}).get(g.name), queue, i): (i, g)
                    for i, g in items}
            pending = set(futs)
            while pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                drain()
                for fut in done:
                    i, g = futs[fut]
                    try:
                        r = fut.result()
                    except BrokenProcessPool:
                        lost.append((i, g))  # maybe not this series' fault: decided by the re-run
                        continue
                    except Exception as exc:
                        r = _error_result(g, f"{type(exc).__name__}: {exc}")
                    finished(i, g, r)
            drain()
        return lost

    try:
        lost = run(list(enumerate(groups)), workers, threads)
        if lost:
            log.warning("a worker process died; re-running %d unfinished series one at a time", len(lost))
        for i, g in sorted(lost, key=lambda x: x[0]):
            if run([(i, g)], 1, max(threads, (os.cpu_count() or 2) // 2)):
                finished(i, g, _error_result(g, WORKER_CRASHED))  # logged by finished()
    finally:
        if mgr is not None:
            mgr.shutdown()
