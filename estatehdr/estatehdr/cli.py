"""Command line interface.

  python -m estatehdr process <folder> [-o out] [--preset neutral|airy|premium] [options]
  python -m estatehdr group <folder> [-o groups.json]      # grouping only (to correct manually)
  python -m estatehdr web [--port 8765]                     # local web UI
  python -m estatehdr presets
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__
from .config import ConfigError, load_config, preset_names


def _setup_logging(verbose: bool, log_file: str | None = None):
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", handlers=handlers,
                        force=True)


def _error(msg: str, code: int = 2) -> int:
    print(f"błąd: {msg}", file=sys.stderr)
    return code


def _module_overrides(a) -> list[tuple]:
    """Overrides from the CLI flags as (key, value) pairs: set as they are, never parsed as YAML
    (a sky file path may contain ' #' or ': ')."""
    o = []
    if a.sky:
        o += [("modules.sky.enabled", True), ("modules.sky.style", a.sky)]
    if a.twilight:
        o += [("modules.twilight.enabled", True), ("modules.twilight.style", a.twilight)]
    if a.remove:
        o += [("modules.remove.enabled", True)]
    if a.grass:
        o += [("modules.grass.enabled", True)]
    if a.no_verticals:
        o += [("geometry.verticals", False)]
    if a.no_windows:
        o += [("windows.enabled", False)]
    if a.workers:
        o += [("runtime.workers", a.workers)]
    if a.bracket_size:
        o += [("grouping.mode", "fixed"), ("grouping.bracket_size", a.bracket_size)]
    if a.single:
        o += [("grouping.mode", "single")]
    if a.mls_size:
        o += [("export.sizes", [{"name": "full", "long_edge": 0, "quality": 95, "sharpen": 1.0},
                                {"name": "mls", "long_edge": a.mls_size, "quality": 90, "sharpen": 0.8}])]
    return o


def _groups_error(path: str, base: str | None) -> str | None:
    """None when the --groups file can be used, else the reason (checked before anything is created)."""
    if not os.path.isfile(path):
        return f"nie ma pliku grup: {path}"
    from .grouping import load_groups
    try:
        load_groups(path, base=base)
    except Exception as exc:
        return f"nie można wczytać pliku grup {path}: {type(exc).__name__}: {exc}"
    return None


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="estatehdr", description=f"EstateHDR {__version__} - automatyczna obróbka zdjęć nieruchomości")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("process", help="przetwórz folder z seriami bracketingowymi")
    p.add_argument("input", help="folder ze zdjęciami (lub pojedynczy plik)")
    p.add_argument("-o", "--output", help="folder wyjściowy (domyślnie <input>/estatehdr_output)")
    p.add_argument("--preset", default=None, help="neutral | airy | premium")
    p.add_argument("--config", default=None, help="własny plik konfiguracji YAML")
    p.add_argument("--set", action="append", default=[], metavar="KLUCZ=WARTOŚĆ", help="nadpisanie parametru")
    p.add_argument("--groups", default=None, help="plik groups.json z ręcznie poprawionym grupowaniem")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--bracket-size", type=int, default=0, help="stała liczba klatek w serii")
    p.add_argument("--single", action="store_true", help="każde zdjęcie osobno (bez bracketingu)")
    p.add_argument("--sky", nargs="?", const="clear", default=None, help="wymiana nieba: clear | wispy | dramatic | plik")
    p.add_argument("--twilight", nargs="?", const="pink", default=None, help="wirtualny zmierzch: blue | pink | golden")
    p.add_argument("--remove", action="store_true", help="usuwanie obiektów wg masek <nazwa>.mask.png")
    p.add_argument("--grass", action="store_true", help="zazielenienie trawy")
    p.add_argument("--no-verticals", action="store_true")
    p.add_argument("--no-windows", action="store_true")
    p.add_argument("--mls-size", type=int, default=0, help="dłuższy bok wersji MLS (domyślnie 2048)")
    p.add_argument("-v", "--verbose", action="store_true")

    g = sub.add_parser("group", help="tylko grupowanie (zapis groups.json do ręcznej korekty)")
    g.add_argument("input")
    g.add_argument("-o", "--output", default=None)
    g.add_argument("--bracket-size", type=int, default=0)
    g.add_argument("-v", "--verbose", action="store_true")

    w = sub.add_parser("web", help="lokalny interfejs webowy")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--workdir", default=None, help="katalog roboczy na zadania (domyślnie <katalog EstateHDR>/work)")
    w.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("presets", help="lista presetów")
    return ap


def main(argv=None):
    a = _parser().parse_args(argv)

    if a.cmd == "presets":
        for k, v in preset_names().items():
            print(f"{k:10s} {v}")
        return 0

    from .batch import quiet_opencv
    quiet_opencv(a.verbose)  # native OpenCV / libtiff warnings, also for the worker processes

    if a.cmd == "group":
        _setup_logging(a.verbose)
        from .grouping import save_groups, scan_folder
        inp = os.path.abspath(a.input)  # absolute paths: the file works from any working directory
        if not os.path.isdir(inp):
            return _error(f"nie ma takiego folderu: {a.input}")
        cfg = load_config(overrides=[("grouping.mode", "fixed"), ("grouping.bracket_size", a.bracket_size)]
                          if a.bracket_size else [])
        out = os.path.abspath(a.output or os.path.join(inp, "groups.json"))
        skipped = []  # RAW+JPEG siblings, EstateHDR outputs (also in a custom output folder inside the input)
        groups, failures = scan_folder(inp, cfg.get("grouping", {}), bool(cfg.get("input", {}).get("recursive", True)),
                                       skipped=skipped)
        if not groups and not failures:
            print(f"brak obsługiwanych zdjęć (RAW/JPEG/TIFF/PNG) w: {a.input}", file=sys.stderr)
            return 1
        save_groups(groups, out, base=inp)
        for gr in groups:
            print(f"{gr.name:30s} {gr.size} klatek  {' '.join(f.name for f in gr.frames)}  {'; '.join(gr.warnings)}")
        for f in failures:
            print(f"POMINIĘTO {f['file']}: {f['error']}")
        for f in skipped:
            print(f"POMINIĘTO {f['file']}: {f['reason']}")
        print(f"zapisano: {out}")
        return 0

    if a.cmd == "web":
        _setup_logging(a.verbose)
        from .web.app import serve
        serve(a.host, a.port, a.workdir)
        return 0

    # process: invalid input -> one line and exit code 2, before anything is created
    inp = os.path.abspath(a.input)
    if not os.path.exists(inp):
        return _error(f"nie ma takiego pliku ani folderu: {a.input}")
    files = None
    if os.path.isfile(inp):
        files = [inp]
        base = os.path.dirname(inp)
    else:
        base = inp
    out = os.path.abspath(a.output or os.path.join(base, "estatehdr_output"))
    try:
        cfg = load_config(a.config, a.preset, _module_overrides(a) + list(a.set))
    except ConfigError as exc:
        return _error(exc.pl)
    if a.groups:
        err = _groups_error(a.groups, None if files else inp)
        if err:
            return _error(err)
    else:
        from .grouping import list_images
        from .io.metadata import SUPPORTED_EXTS
        if files:
            found = os.path.splitext(inp)[1].lower() in SUPPORTED_EXTS
        else:
            found = bool(list_images(inp, bool(cfg.get("input", {}).get("recursive", True)), exclude=[out]))
        if not found:
            print(f"brak obsługiwanych zdjęć (RAW/JPEG/TIFF/PNG) w: {a.input}", file=sys.stderr)
            return 1
    try:
        os.makedirs(out, exist_ok=True)
    except OSError as exc:
        return _error(f"nie można utworzyć folderu wyjściowego {out}: {exc.strerror or exc}")
    _setup_logging(a.verbose, os.path.join(out, "estatehdr.log"))
    from .batch import run_batch
    masks = None
    if cfg["modules"]["remove"].get("enabled"):
        masks = {}  # masks are discovered per file by the remove module
    report = run_batch(None if files else inp, out, cfg, a.groups, files=files, masks=masks)
    # "failed" (as in report.json) = failed series + unreadable files; both also given separately
    print(json.dumps({"ok": report["ok"], "failed": report["failed"],
                      "failed_series": sum(s["status"] != "ok" for s in report["series"]),
                      "unreadable": len(report["unreadable"]), "seconds": report["seconds"], "output": out},
                     ensure_ascii=False))
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
