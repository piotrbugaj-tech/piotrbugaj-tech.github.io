"""Local web UI (FastAPI): upload a folder, check / correct the grouping, choose a preset and
optional modules, paint removal masks, follow the queue, compare before/after, download.

Everything stays on this machine: the server listens on 127.0.0.1 by default and keeps every
job in ``<workdir>/jobs/<id>/`` (input, output, thumbnails, masks, job.json).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from urllib.parse import quote, unquote

import cv2
import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from ..config import load_config, preset_names
from ..io.metadata import SUPPORTED_EXTS

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")
SAFE = re.compile(r"[^A-Za-z0-9._\- ]+")  # uploaded paths and mask file names (series names: _series_name)
SKY_STYLES = ["clear", "wispy", "dramatic"]
TWILIGHT_STYLES = ["blue", "pink", "golden"]


def _safe_rel(rel: str) -> str:
    """Sanitise an uploaded relative path (no absolute paths, no '..', safe characters)."""
    parts = [SAFE.sub("_", p) for p in re.split(r"[\\\\/]+", rel or "") if p not in ("", ".", "..")]
    if not parts:
        raise HTTPException(400, "pusta ścieżka pliku")
    return os.path.join(*parts)


def _inside(base: str, path: str) -> str:
    full = os.path.realpath(os.path.join(base, path))
    if not (full == os.path.realpath(base) or full.startswith(os.path.realpath(base) + os.sep)):
        raise HTTPException(400, "niedozwolona ścieżka")
    return full


# ---------------------------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------------------------

class Job:
    def __init__(self, root: str, jid: str | None = None):
        self.id = jid or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = os.path.join(root, self.id)
        self.input_dir = os.path.join(self.dir, "input")
        self.output_dir = os.path.join(self.dir, "output")
        self.state = "new"           # new | grouped | queued | running | done | error
        self.created = time.time()
        self.groups: list[dict] = []
        self.unreadable: list[dict] = []
        self.skipped: list[dict] = []   # left out on purpose (JPEG next to its RAW, EstateHDR outputs)
        self.groups_edited = False
        self.settings: dict = {}
        self.progress: dict = {}     # series -> {frac, stage, status}
        self.results: dict = {}      # series -> result summary
        self.report: dict | None = None
        self.error: str | None = None
        self.masks: dict = {}        # series -> mask path
        self.group_opts: dict = {}   # options used for the current automatic grouping
        self.run_id = 0              # incremented on every submit; a stale run never finishes a newer one
        self.lock = threading.RLock()
        self._save_lock = threading.Lock()

    # -- persistence -----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "state", "created", "groups", "unreadable", "skipped", "groups_edited",
                                              "settings", "progress", "results", "report", "error", "masks",
                                              "group_opts", "run_id")}

    def snapshot(self) -> dict:
        """Deep copy of the state, taken under the lock (the queue thread mutates it while running)."""
        with self.lock:
            return json.loads(json.dumps(self.to_dict(), ensure_ascii=False, default=str))

    def save(self):
        data = self.snapshot()
        with self._save_lock:
            os.makedirs(self.dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="job.", suffix=".part", dir=self.dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False)
                os.replace(tmp, os.path.join(self.dir, "job.json"))
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise

    @classmethod
    def load(cls, root: str, jid: str) -> "Job | None":
        p = os.path.join(root, jid, "job.json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        j = cls(root, jid)
        for k, v in d.items():
            if k != "id":
                setattr(j, k, v)
        if j.state in ("queued", "running"):  # server was stopped while processing
            j.state, j.error = "error", "przerwano (serwer został zatrzymany) - uruchom ponownie"
        return j

    # -- helpers ---------------------------------------------------------------------------
    def input_files(self) -> list[str]:
        out = []
        for root, _, files in os.walk(self.input_dir):
            for f in files:
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS and not f.lower().endswith(".mask.png"):
                    out.append(os.path.relpath(os.path.join(root, f), self.input_dir))
        return sorted(out)

    def on_progress(self, ev: dict):
        with self.lock:
            name = ev.get("series")
            p = self.progress.setdefault(name, {})
            p.update(frac=float(ev.get("frac", 0)), stage=ev.get("stage", ""))
            if "result" in ev:
                self.results[name] = _summary(self, ev["result"])
                p["status"] = ev["result"].get("status")
            else:
                p.setdefault("status", "running")


def _summary(job: Job, r: dict) -> dict:
    outs = {}
    for k, v in (r.get("outputs") or {}).items():
        path = v.get("path") if isinstance(v, dict) else None
        if path and os.path.exists(path):
            rel = os.path.relpath(path, job.output_dir).replace(os.sep, "/")
            # file names follow the series name (Unicode letters, '#', '%' ...): percent-encode the URL
            outs[k] = {"url": f"/api/jobs/{job.id}/out/{quote(rel)}", "name": os.path.basename(path),
                       "width": v.get("width"), "height": v.get("height")}
    mods = r.get("modules") or {}
    return {"status": r.get("status"), "error": r.get("error"), "warnings": r.get("warnings", []),
            "seconds": r.get("seconds"), "frames": len(r.get("files", []) or []), "outputs": outs,
            "modules": {k: {kk: vv for kk, vv in v.items() if kk in ("applied", "reason", "error", "style",
                                                                    "windows_lit", "components")}
                        for k, v in mods.items() if isinstance(v, dict)}}


class JobManager:
    def __init__(self, workdir: str):
        self.root = os.path.join(workdir, "jobs")
        os.makedirs(self.root, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        for jid in sorted(os.listdir(self.root)):
            try:
                j = Job.load(self.root, jid)
            except Exception as exc:  # a damaged job folder must not stop the server
                log.warning("skipping job %s: unreadable job.json (%s)", jid, exc)
                continue
            if j:
                self.jobs[jid] = j
        self.q: queue.Queue = queue.Queue()
        self.worker = threading.Thread(target=self._loop, name="estatehdr-queue", daemon=True)
        self.worker.start()

    def new(self) -> Job:
        j = Job(self.root)
        os.makedirs(j.input_dir, exist_ok=True)
        self.jobs[j.id] = j
        j.save()
        return j

    def get(self, jid: str) -> Job:
        j = self.jobs.get(jid)
        if j is None:
            raise HTTPException(404, "nie ma takiego zadania")
        return j

    def queue_position(self, job: Job) -> int:
        return sum(1 for j in self.jobs.values() if j.state == "queued" and j.created < job.created)

    def submit(self, job: Job):
        with job.lock:
            job.state = "queued"
            job.run_id = int(job.run_id or 0) + 1
            job.progress, job.results, job.report, job.error = {}, {}, None, None
        job.save()
        self.q.put((job.id, job.run_id))

    def _loop(self):
        while True:  # the only consumer of the queue: nothing may end this loop
            jid, run_id = self.q.get()
            job = self.jobs.get(jid)
            if job is None or job.state != "queued" or job.run_id != run_id:
                continue
            try:
                self._run(job)
            except Exception as exc:
                job.state, job.error = "error", f"{type(exc).__name__}: {exc}"
                log.error("job %s failed: %s\n%s", job.id, exc, traceback.format_exc())
            try:
                job.save()
            except Exception as exc:
                log.error("job %s: cannot save job.json: %s", job.id, exc)

    def _run(self, job: Job):
        from ..batch import run_batch
        job.state = "running"
        job.save()
        st = job.settings
        cfg = load_config(None, st.get("preset") or None, _overrides(st))
        groups_file = None
        if job.groups:  # always process exactly the grouping the user saw (and maybe corrected)
            groups_file = os.path.join(job.dir, "groups.json")
            with open(groups_file, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "groups": [{"name": g["name"], "warnings": g.get("warnings", []),
                                                     "files": [os.path.join(job.input_dir, f) for f in g["files"]]}
                                                    for g in job.groups if g["files"]]}, fh)
        masks = {name: {"remove": p} for name, p in job.masks.items() if os.path.exists(p)}
        last = [0.0]

        def cb(ev):
            job.on_progress(ev)
            if time.time() - last[0] > 1.0 or "result" in ev:
                last[0] = time.time()
                try:
                    job.save()
                except Exception as exc:  # progress persistence must never fail a series
                    log.warning("job %s: progress not saved: %s", job.id, exc)
        os.makedirs(job.output_dir, exist_ok=True)
        rep = run_batch(job.input_dir, job.output_dir, cfg, groups_file, progress_cb=cb, masks=masks)
        with job.lock:
            job.report = {k: rep.get(k) for k in ("ok", "failed", "seconds", "workers", "peak_rss_gb", "unreadable",
                                                  "skipped")}
            for r in rep.get("series", []):
                job.results[r["name"]] = _summary(job, r)
                job.progress.setdefault(r["name"], {}).update(frac=1.0, stage="gotowe", status=r.get("status"))
            job.state = "done"


def _overrides(st: dict) -> list[str]:
    o = []
    sky = st.get("sky")
    if sky in SKY_STYLES:
        o += ["modules.sky.enabled=true", f"modules.sky.style={sky}"]
    tw = st.get("twilight")
    if tw in TWILIGHT_STYLES:
        o += ["modules.twilight.enabled=true", f"modules.twilight.style={tw}"]
    if st.get("grass"):
        o.append("modules.grass.enabled=true")
    if st.get("remove"):
        o.append("modules.remove.enabled=true")
    if st.get("verticals") is False:
        o.append("geometry.verticals=false")
    if st.get("windows") is False:
        o.append("windows.enabled=false")
    if st.get("single"):
        o.append("grouping.mode=single")
    mls = int(st.get("mls_size") or 0)
    if 256 <= mls <= 8000:
        o.append(f"export.sizes=[{{name: full, long_edge: 0, quality: 95, sharpen: 1.0}}, "
                 f"{{name: mls, long_edge: {mls}, quality: 90, sharpen: 0.8}}]")
    return o


def _series_name(raw: str) -> str:
    """grouping.safe_name (only path-reserved / control characters replaced, Unicode letters kept)
    on at most 80 characters: a fixed point of safe_name, so run_batch keeps it unchanged."""
    from ..grouping import safe_name
    return safe_name(str(raw)[:80])


def _unique_names(groups: list[dict]) -> list[dict]:
    """Same rules as grouping.unique_names (safe_name, case-insensitive), so the batch keeps
    exactly these names and masks / results stay keyed by what the user sees."""
    names: set = set()
    for g in groups:
        base = _series_name(g["name"])
        name, k = base, 2
        while name.casefold() in names:
            name = f"{base}_{k}"
            k += 1
        names.add(name.casefold())
        g["name"] = name
    return groups


def _rekey_masks(job: Job, old_groups: list[dict], new_groups: list[dict]):
    """Masks are keyed by series name: follow each masked series to the new group holding most
    of its files (rename, merge, split, regroup); drop masks whose files left every series."""
    old_files = {g["name"]: set(g["files"]) for g in old_groups}
    target: dict = {}  # new series -> mask files that follow it
    for name, path in job.masks.items():
        files = old_files.get(name, set())
        best = max(new_groups, key=lambda g: len(files & set(g["files"])), default=None)
        if best is not None and files & set(best["files"]) and path and os.path.exists(path):
            target.setdefault(best["name"], []).append(path)
        elif path and os.path.exists(path):
            os.remove(path)
    masks = {}
    for name, paths in target.items():
        if len(paths) > 1:  # merged series: union of the painted masks (frames of one series share a size)
            ms = [cv2.imread(p, cv2.IMREAD_GRAYSCALE) for p in paths]
            ms = [m for m in ms if m is not None]
            if ms:
                h, w = ms[0].shape
                m = np.max([cv2.resize(x, (w, h), interpolation=cv2.INTER_NEAREST) for x in ms], axis=0)
                cv2.imwrite(paths[0], m)
            for p in paths[1:]:
                os.remove(p)
        masks[name] = paths[0]
    job.masks = masks


def _busy(job: Job):
    if job.state in ("queued", "running"):
        raise HTTPException(409, "zadanie jest w trakcie przetwarzania - poczekaj na koniec")


# ---------------------------------------------------------------------------------------------
# previews of input files
# ---------------------------------------------------------------------------------------------

def render_preview(path: str, max_side: int) -> bytes:
    """Display JPEG of an input frame (any supported format), EXIF orientation applied."""
    ext = os.path.splitext(path)[1].lower()
    img8 = None
    if ext in (".jpg", ".jpeg", ".png"):
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im.draft("RGB", (max_side, max_side))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_side, max_side))
            img8 = np.asarray(im)
    if img8 is None:
        from ..imgutil import LUMA, linear_to_srgb
        from ..io.metadata import read_metadata
        from ..io.reader import decode
        meta = read_metadata(path)
        d = decode(path, meta.orientation, half=True)
        img = d.as_float()
        if d.encoding == "linear":
            k = 0.18 / max(float(np.median(img @ LUMA)), 1e-4)
            img = linear_to_srgb(np.clip(img * k, 0, 1))
        s = min(1.0, max_side / max(img.shape[:2]))
        if s < 1:
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        img8 = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img8, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


# ---------------------------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------------------------

def create_app(workdir: str | None = None) -> FastAPI:
    from ..config import DEFAULT_CONFIG_PATH
    workdir = os.path.abspath(workdir or os.path.join(os.path.dirname(DEFAULT_CONFIG_PATH), "work"))
    mgr = JobManager(workdir)
    app = FastAPI(title="EstateHDR", docs_url=None, redoc_url=None)
    app.state.manager = mgr
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
            return fh.read()

    @app.get("/api/options")
    def options():
        return {"presets": preset_names(), "sky": SKY_STYLES, "twilight": TWILIGHT_STYLES,
                "extensions": sorted(SUPPORTED_EXTS)}

    @app.get("/api/jobs")
    def list_jobs():
        js = sorted(mgr.jobs.values(), key=lambda j: -j.created)[:30]
        return [{"id": j.id, "state": j.state, "created": j.created, "series": len(j.groups),
                 "files": sum(len(g["files"]) for g in j.groups)} for j in js]

    @app.post("/api/jobs")
    def create_job():
        j = mgr.new()
        return {"id": j.id}

    @app.get("/api/jobs/{jid}")
    def job_status(jid: str):
        j = mgr.get(jid)
        d = j.snapshot()
        d["queue_position"] = mgr.queue_position(j) if j.state == "queued" else 0
        d["files"] = j.input_files()
        return d

    @app.delete("/api/jobs/{jid}")
    def delete_job(jid: str):
        j = mgr.get(jid)
        if j.state in ("queued", "running"):
            raise HTTPException(409, "zadanie jest w trakcie przetwarzania")
        shutil.rmtree(j.dir, ignore_errors=True)
        mgr.jobs.pop(jid, None)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/files")
    async def upload(jid: str, files: list[UploadFile] = File(...), paths: list[str] = Form(default=[])):
        j = mgr.get(jid)
        if j.state in ("queued", "running"):
            raise HTTPException(409, "zadanie jest w trakcie przetwarzania")
        saved, skipped = [], []
        for i, f in enumerate(files):
            rel = _safe_rel(paths[i] if i < len(paths) and paths[i] else f.filename)
            ext = os.path.splitext(rel)[1].lower()
            if ext not in SUPPORTED_EXTS:
                skipped.append(rel)
                continue
            dst = _inside(j.input_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst + ".part", "wb") as out:
                shutil.copyfileobj(f.file, out, 1 << 20)
            os.replace(dst + ".part", dst)
            saved.append(rel)
        j.state = "new"
        j.save()
        return {"saved": saved, "skipped": skipped}

    @app.post("/api/jobs/{jid}/group")
    def group(jid: str, body: dict = Body(default={})):
        from ..grouping import scan_folder
        j = mgr.get(jid)
        _busy(j)
        overrides = []
        if body.get("bracket_size"):
            overrides += ["grouping.mode=fixed", f"grouping.bracket_size={int(body['bracket_size'])}"]
        if body.get("single"):
            overrides += ["grouping.mode=single"]
        cfg = load_config(None, None, overrides)
        skipped: list = []
        groups, failures = scan_folder(j.input_dir, cfg.get("grouping", {}), skipped=skipped)
        new = _unique_names([{"name": g.name,
                              "files": [os.path.relpath(f.path, j.input_dir) for f in g.frames],
                              "warnings": g.warnings,
                              "ev": [None if f.exposure_value is None else round(f.exposure_value, 2)
                                     for f in g.frames]} for g in groups])
        _rekey_masks(j, j.groups, new)
        j.groups = new
        j.unreadable = [{"file": os.path.relpath(f["file"], j.input_dir), "error": f["error"]} for f in failures]
        j.skipped = [{"file": os.path.relpath(f["file"], j.input_dir), "reason": f["reason"]} for f in skipped]
        j.group_opts = {"single": bool(body.get("single")), "bracket_size": int(body.get("bracket_size") or 0)}
        j.groups_edited = False
        j.state = "grouped"
        j.save()
        return {"groups": j.groups, "unreadable": j.unreadable, "skipped": j.skipped, "masks": j.masks}

    @app.put("/api/jobs/{jid}/groups")
    def set_groups(jid: str, body: dict = Body(...)):
        j = mgr.get(jid)
        _busy(j)
        files = set(j.input_files())
        out, used = [], set()
        for g in body.get("groups", []):
            fl = [f for f in g.get("files", []) if f in files and f not in used]
            used.update(fl)
            if fl:
                name = str(g.get("name") or os.path.splitext(os.path.basename(fl[0]))[0])
                out.append({"name": name, "files": fl, "warnings": [], "ev": []})
        _unique_names(out)
        _rekey_masks(j, j.groups, out)
        j.groups, j.groups_edited = out, True
        j.save()
        return {"groups": j.groups, "masks": j.masks}

    @app.get("/api/jobs/{jid}/thumb")
    def thumb(jid: str, f: str = Query(...), s: int = Query(320, ge=64, le=2400)):
        j = mgr.get(jid)
        src = _inside(j.input_dir, f)
        if not os.path.exists(src):
            raise HTTPException(404, "brak pliku")
        cache = os.path.join(j.dir, "thumbs", f"{s}", _safe_rel(f) + ".jpg")
        if not os.path.exists(cache):
            try:
                data = render_preview(src, s)
            except Exception as exc:
                raise HTTPException(422, f"nie można odczytać pliku: {exc}")
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "wb") as fh:
                fh.write(data)
        return FileResponse(cache, media_type="image/jpeg")

    @app.post("/api/jobs/{jid}/masks/{series}")
    async def put_mask(jid: str, series: str, file: UploadFile = File(...)):
        j = mgr.get(jid)
        _busy(j)
        data = np.frombuffer(await file.read(), np.uint8)
        m = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if m is None:
            raise HTTPException(400, "nieprawidłowy obraz maski")
        if m.dtype != np.uint8:
            m = (m / 257).astype(np.uint8) if m.dtype == np.uint16 else np.clip(m, 0, 255).astype(np.uint8)
        if m.ndim == 3:
            # browsers send an opaque RGBA PNG (white strokes on black): use alpha only if it varies
            if m.shape[2] == 4 and m[..., 3].min() < 255:
                m = m[..., 3]
            else:
                m = cv2.cvtColor(m[..., :3], cv2.COLOR_BGR2GRAY)
        m = ((m > 20) * 255).astype(np.uint8)
        d = os.path.join(j.dir, "masks")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{SAFE.sub('_', series)[:60]}-{uuid.uuid4().hex[:6]}.png")
        cv2.imwrite(p, m)
        old = j.masks.get(series)
        if old and old != p and os.path.exists(old):
            os.remove(old)
        j.masks[series] = p
        j.save()
        return {"ok": True, "pixels": int((m > 0).sum())}

    @app.delete("/api/jobs/{jid}/masks/{series}")
    def del_mask(jid: str, series: str):
        j = mgr.get(jid)
        _busy(j)
        p = j.masks.pop(series, None)
        if p and os.path.exists(p):
            os.remove(p)
        j.save()
        return {"ok": True}

    @app.get("/api/jobs/{jid}/masks/{series}")
    def get_mask(jid: str, series: str):
        j = mgr.get(jid)
        p = j.masks.get(series)
        if not p or not os.path.exists(p):
            raise HTTPException(404, "brak maski")
        return FileResponse(p, media_type="image/png")

    @app.post("/api/jobs/{jid}/start")
    def start(jid: str, body: dict = Body(default={})):
        j = mgr.get(jid)
        if j.state in ("queued", "running"):
            raise HTTPException(409, "zadanie już jest w kolejce")
        if not j.input_files():
            raise HTTPException(400, "brak zdjęć - najpierw wgraj pliki")
        preset = body.get("preset") or "neutral"
        if preset not in preset_names():
            raise HTTPException(400, "nieznany preset")
        j.settings = {k: body.get(k) for k in ("preset", "sky", "twilight", "grass", "remove", "verticals",
                                               "windows", "mls_size", "single")}
        j.settings["preset"] = preset
        single = bool(body.get("single"))
        if j.state == "new" or not j.groups or (not j.groups_edited and bool(j.group_opts.get("single")) != single):
            group(jid, {"single": single, "bracket_size": 0 if single else j.group_opts.get("bracket_size", 0)})
        mgr.submit(j)
        return {"ok": True, "queue_position": mgr.queue_position(j)}

    @app.get("/api/jobs/{jid}/out/{path:path}")
    def out_file(jid: str, path: str, download: int = 0):
        j = mgr.get(jid)
        full = _inside(j.output_dir, path)
        if not os.path.isfile(full):
            raise HTTPException(404, "brak pliku")
        return FileResponse(full, filename=os.path.basename(full) if download else None)

    @app.get("/api/jobs/{jid}/zip")
    def zip_all(jid: str, which: str = Query("all", pattern="^(all|full|mls)$")):
        j = mgr.get(jid)
        if j.state in ("queued", "running"):  # results of the previous run are being replaced
            raise HTTPException(409, "zadanie jest w trakcie przetwarzania - pobierz ZIP po zakończeniu")
        files = []
        for name, r in j.results.items():
            for k, v in (r.get("outputs") or {}).items():
                if k.startswith("preview"):
                    continue
                if which != "all" and k != which:
                    continue
                f = _inside(j.output_dir, unquote(v["url"].split("/out/", 1)[1]))
                if os.path.isfile(f):
                    files.append(f)
        if not files:
            raise HTTPException(404, "brak wyników do pobrania")
        tmp = tempfile.NamedTemporaryFile(prefix="estatehdr_", suffix=".zip", delete=False)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for f in files:
                z.write(f, os.path.relpath(f, j.output_dir))
        tmp.close()
        return FileResponse(tmp.name, filename=f"estatehdr_{j.id}_{which}.zip", media_type="application/zip",
                            background=BackgroundTask(os.remove, tmp.name))

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, workdir: str | None = None):
    import uvicorn
    app = create_app(workdir)
    print(f"EstateHDR: otwórz http://{host}:{port}  (katalog roboczy: {app.state.manager.root})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
