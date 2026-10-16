"""Web UI backend: upload, grouping, manual groups, mask, processing queue, downloads."""
import io
import os
import time
import zipfile

import cv2
import numpy as np
from fastapi.testclient import TestClient

from estatehdr.web.app import create_app


def test_web_flow(synth, tmp_path):
    app = create_app(str(tmp_path / "work"))
    c = TestClient(app)
    assert "EstateHDR" in c.get("/").text
    assert "neutral" in c.get("/api/options").json()["presets"]
    jid = c.post("/api/jobs").json()["id"]
    files = [f for f in synth["manifest"]["series"][0]["files"]] + ["IMG_0011.jpg"]
    up = c.post(f"/api/jobs/{jid}/files",
                files=[("files", (f, open(os.path.join(synth["input"], f), "rb"), "image/jpeg")) for f in files]
                + [("files", ("readme.txt", io.BytesIO(b"x"), "text/plain"))],
                data={"paths": [f"shoot/{f}" for f in files] + ["shoot/readme.txt"]}).json()
    assert len(up["saved"]) == len(files) and up["skipped"] == ["shoot/readme.txt"]
    g = c.post(f"/api/jobs/{jid}/group", json={}).json()["groups"]
    assert sorted(len(x["files"]) for x in g) == [1, 5]
    # path traversal is rejected
    assert c.get(f"/api/jobs/{jid}/thumb", params={"f": "../../etc/passwd"}).status_code == 400
    assert c.get(f"/api/jobs/{jid}/thumb", params={"f": g[0]["files"][0]}).headers["content-type"] == "image/jpeg"
    # manual correction: move the single photo into its own named series
    g2 = c.put(f"/api/jobs/{jid}/groups", json={"groups": [{"name": "salon", "files": g[0]["files"]},
                                                           {"name": "pojedyncze", "files": g[1]["files"]}]}).json()
    assert [x["name"] for x in g2["groups"]] == ["salon", "pojedyncze"]
    mask = np.zeros((320, 480), np.uint8)
    cv2.circle(mask, (240, 280), 12, 255, -1)
    ok, buf = cv2.imencode(".png", mask)
    assert c.post(f"/api/jobs/{jid}/masks/salon", files={"file": ("m.png", buf.tobytes(), "image/png")}).json()["ok"]
    r = c.post(f"/api/jobs/{jid}/start", json={"preset": "premium", "remove": True, "mls_size": 1024}).json()
    assert r["ok"]
    t0 = time.time()
    while time.time() - t0 < 300:
        st = c.get(f"/api/jobs/{jid}").json()
        if st["state"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert st["state"] == "done", st.get("error")
    assert st["results"]["salon"]["status"] == "ok"
    assert st["results"]["salon"]["modules"]["remove"].get("components") == 1
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/jobs/{jid}/zip", params={"which": "mls"}).content))
    assert sorted(z.namelist()) == ["pojedyncze_mls.jpg", "salon_mls.jpg"]
    url = st["results"]["salon"]["outputs"]["full"]["url"]
    assert c.get(url).status_code == 200
    assert c.get(f"/api/jobs/{jid}/out/../job.json").status_code in (400, 404)


def test_web_masks_names_and_guards(synth, tmp_path):
    """Browser-style RGBA masks, masks following renamed series, unique auto names, busy guards,
    and a damaged job.json not stopping the server."""
    work = tmp_path / "work"
    c = TestClient(create_app(str(work)))
    jid = c.post("/api/jobs").json()["id"]
    f = "IMG_0011.jpg"
    src = os.path.join(synth["input"], f)
    c.post(f"/api/jobs/{jid}/files", files=[("files", (f, open(src, "rb"), "image/jpeg")),
                                            ("files", (f, open(src, "rb"), "image/jpeg"))],
           data={"paths": [f"salon/{f}", f"kuchnia/{f}"]})
    g = c.post(f"/api/jobs/{jid}/group", json={}).json()["groups"]
    names = [x["name"] for x in g]
    assert len(names) == 2 and len(set(names)) == 2
    # canvas.toBlob: opaque RGBA, white strokes on black
    rgba = np.zeros((320, 480, 4), np.uint8)
    rgba[..., 3] = 255
    cv2.circle(rgba, (100, 100), 10, (255, 255, 255, 255), -1)
    ok, buf = cv2.imencode(".png", rgba)
    px = c.post(f"/api/jobs/{jid}/masks/{names[0]}", files={"file": ("m.png", buf.tobytes(), "image/png")}).json()["pixels"]
    assert 0 < px < 1000
    # rename: the mask follows its files
    c.put(f"/api/jobs/{jid}/groups", json={"groups": [{"name": "salon", "files": g[0]["files"]},
                                                      {"name": "kuchnia", "files": g[1]["files"]}]})
    assert c.get(f"/api/jobs/{jid}/masks/salon").status_code == 200
    assert c.get(f"/api/jobs/{jid}/masks/{names[0]}").status_code == 404
    # no edits while the job is queued / running
    mgr = c.app.state.manager
    mgr.jobs[jid].state = "running"
    assert c.post(f"/api/jobs/{jid}/group", json={}).status_code == 409
    assert c.put(f"/api/jobs/{jid}/groups", json={"groups": []}).status_code == 409
    assert c.delete(f"/api/jobs/{jid}/masks/salon").status_code == 409
    mgr.jobs[jid].state = "grouped"
    mgr.jobs[jid].save()
    # a damaged job.json is skipped, the server still starts
    bad = work / "jobs" / "broken"
    bad.mkdir(parents=True)
    (bad / "job.json").write_text("{not json")
    c2 = TestClient(create_app(str(work)))
    ids = [j["id"] for j in c2.get("/api/jobs").json()]
    assert jid in ids and "broken" not in ids
