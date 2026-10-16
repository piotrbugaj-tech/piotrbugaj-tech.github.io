"""Command line: estatehdr.log with worker processes, quiet native OpenCV logging, one-line errors
(exit code 2) for bad options, raw CLI flag values, the final JSON line."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from estatehdr import cli
from estatehdr.config import load_config

from .conftest import ROOT


def _env(**extra):
    env = {**os.environ, "PYTHONPATH": ROOT, **extra}
    env.pop("OPENCV_LOG_LEVEL", None)
    return env


def test_worker_lines_and_failures_reach_log_file(synth, tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    shutil.copy(os.path.join(synth["input"], "IMG_0011.jpg"), inp / "a.jpg")
    for n in ("IMG_0005.tif", "IMG_0006.tif", "IMG_0007.tif", "IMG_9999.jpg"):  # TIFF series + truncated JPEG
        shutil.copy(os.path.join(synth["input"], n), inp / n)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "estatehdr", "process", str(inp), "-o", str(out), "--workers", "2",
                        "--set", "tonemap.target_key=abc", "--set", "export.save_previews=false"],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 2, r.stderr[-2000:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert (res["ok"], res["failed"], res["failed_series"], res["unreadable"]) == (0, 3, 2, 1)
    log = (out / "estatehdr.log").read_text(encoding="utf-8")
    assert "2 worker(s)" in log
    worker = [ln for ln in log.splitlines() if "SpawnProcess" in ln]
    assert any("[a] 1 frame(s)" in ln for ln in worker)  # per-series lines written by the workers
    assert any("[a] failed" in ln and "abc" in ln for ln in worker)  # the worker's own error line
    assert "[a] series failed: ValueError" in log and "[IMG_0005] series failed" in log  # parent summary
    assert "IMG_9999.jpg" in log  # unreadable file
    with open(out / "report.json") as fh:
        rep = json.load(fh)
    assert (rep["ok"], rep["failed"]) == (0, 3)  # report.json keeps its meaning
    # native libtiff warnings (the test TIFFs carry EXIF tags libtiff does not know) stay off stderr
    assert "TIFF_Warning" not in r.stderr and "[ WARN:" not in r.stderr


def test_quiet_opencv_keeps_warnings_with_verbose(synth):
    code = ("import sys, numpy as np; from estatehdr.batch import quiet_opencv; quiet_opencv(sys.argv[2] == 'v'); "
            "import cv2; cv2.imdecode(np.fromfile(sys.argv[1], np.uint8), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_ANYDEPTH)")
    tif = os.path.join(synth["input"], "IMG_0005.tif")
    loud = subprocess.run([sys.executable, "-c", code, tif, "v"], capture_output=True, text=True, env=_env())
    quiet = subprocess.run([sys.executable, "-c", code, tif, "-"], capture_output=True, text=True, env=_env())
    assert loud.returncode == 0 and quiet.returncode == 0, quiet.stderr
    if "TIFF_Warning" not in loud.stderr:
        pytest.skip("this OpenCV build does not report libtiff warnings")
    assert "TIFF_Warning" not in quiet.stderr


@pytest.mark.parametrize("args, message", [
    (["--preset", "nope"], "nieznany preset 'nope'"),
    (["--config", "nie_ma.yaml"], "nie ma pliku konfiguracji"),
    (["--config", "{bad}"], "błędny YAML"),
    (["--config", "{list}"], "nie jest słownikiem"),
    (["--set", "tonemap.target_key"], "--set wymaga postaci"),
    (["--set", "=0.5"], "--set wymaga postaci"),
    (["--groups", "nie_ma.json"], "nie ma pliku grup"),
    (["--groups", "{bad}"], "nie można wczytać pliku grup"),
])
def test_bad_options_exit_2_with_one_line(synth, tmp_path, monkeypatch, capsys, args, message):
    monkeypatch.setenv("OPENCV_LOG_LEVEL", "ERROR")  # quiet_opencv must not touch this process
    monkeypatch.chdir(tmp_path)
    (tmp_path / "in").mkdir()
    shutil.copy(os.path.join(synth["input"], "IMG_0011.jpg"), tmp_path / "in" / "a.jpg")
    (tmp_path / "bad").write_text("tonemap:\n  target_key: [0.5,\n")
    (tmp_path / "list").write_text("- a\n- b\n")
    args = [x.format(bad=tmp_path / "bad", list=tmp_path / "list") for x in args]
    code = cli.main(["process", "in", "-o", "out"] + args)
    err = capsys.readouterr().err.strip()
    assert code == 2 and err.startswith("błąd: ") and message in err and len(err.splitlines()) == 1, err
    assert not (tmp_path / "out").exists()  # nothing created


def test_flag_values_are_not_parsed_as_yaml():
    for path in ("/tmp/niebo #2.jpg", "C:/sesja: dom/niebo.jpg", "yes", "[1]"):
        a = cli._parser().parse_args(["process", "x", "--sky", path, "--twilight", "golden", "--mls-size", "1600"])
        c = load_config(None, None, cli._module_overrides(a))
        assert c["modules"]["sky"]["style"] == path and c["modules"]["sky"]["enabled"] is True
        assert c["modules"]["twilight"]["style"] == "golden"
        assert [s["long_edge"] for s in c["export"]["sizes"]] == [0, 1600]
    c = load_config(None, None, ["modules.sky.style=/tmp/a #b", "tonemap.target_key=0.6", "export.icc=off"])
    assert c["modules"]["sky"]["style"] == "/tmp/a" and c["tonemap"]["target_key"] == 0.6  # --set: YAML, as documented
    assert c["export"]["icc"] is False


def test_web_help_names_real_default_workdir(capsys):
    with pytest.raises(SystemExit):
        cli.main(["web", "--help"])
    assert "domyślnie <katalog EstateHDR>/work" in " ".join(capsys.readouterr().out.split())
