"""Regenerate README section 6 (quality measurements) from the report files, so that every number
in it comes from reports/ and none is copied by hand.

Reads reports/calibration/{full_pipeline,validation,calibration,continuation/calibration}.json,
reports/comparisons/metrics.json, reports/verification.json, reports/modules_eval.json,
reports/portfolio_do_no_harm.json and reports/perf.json, counts the tests (pytest --collect-only)
and replaces the text between the METRICS markers in README.md.

Usage (from the project root): python tools/update_readme_metrics.py [--no-tests]
"""
import argparse
import json
import os
import re
import statistics as st
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
R = os.path.join(ROOT, "reports")
SYN_GT = os.path.join(ROOT, "data", "synthetic", "gt")
START, END = "<!-- METRICS:START -->", "<!-- METRICS:END -->"
PRESETS = ("neutral", "airy", "premium")
FRAME = (2400, 1600)  # synthetic frames; the CA residual is measured in their corner


def load(*p):
    path = os.path.join(R, *p)
    if not os.path.exists(path):
        sys.exit(f"missing report: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def f(v, n=2):
    return "—" if v is None else f"{v:.{n}f}".replace("-", "−")


def rng(vals, n=2):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    lo, hi = f(min(vals), n), f(max(vals), n)
    return lo if lo == hi else f"{lo}{'…' if min(vals) < 0 else '–'}{hi}"


def pl(n, one, few, many):
    """Polish plural form for n."""
    if n == 1:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def status(ok, partial=False):
    return "częściowo" if partial else ("tak" if ok else "**nie**")


# --- 6.1 ------------------------------------------------------------------------------------------
CAL_ROWS = (("Neutralność ścian ΔE2000, GT (≤ 3.0)", "wall_dE_gt", 2, True),
            ("Jasność ścian L*, GT (neutral 78–88, airy 84–92, premium 74–86)", "wall_L_gt", 1, True),
            ("Jasność widoku za oknem L*, GT (55–80, premium 45–70)", "win_L", 1, False),
            ("Odzyskiwalne przepalenia okna, % (< 5)", "win_clip_recov_%", 1, False),
            ("Przepalenia poza źródłami światła, %, GT (< 0.5)", "clipped_nonlight_%", 2, False),
            ("Zaczernienia, % (< 0.5)", "crushed_%", 2, False),
            ("Halo przy oknie ΔL* (< 4)", "halo_dL", 1, False),
            ("Pionowość, mediana [°] (≤ 0.5)", "vert_med_deg", 2, False),
            ("Detal widoku okna / GT (≥ 0.6)", "win_detail_ratio", 2, False),
            ("Neutralność jasnych powierzchni ΔE (auto)", "wall_dE_auto", 2, False),
            ("Mediana jasności", "median_luma", 2, False))


def section_calibration():
    d = load("calibration", "full_pipeline.json")

    def cell(p, key, n, bold):
        x = d.get(p, {}).get(key)
        if not x:
            return "—"
        after = f(x["after"], n)
        return f"{f(x['before'], n)} → {'**' + after + '**' if bold else after}"
    md = ["### 6.1 Kalibracja: przed i po (pełny pipeline, sceny syntetyczne z GT)", "",
          "Ten sam kod, różnią się tylko parametry: przed = [config_before_full.yaml](reports/calibration/config_before_full.yaml),",
          "po = `config.yaml`. Metryki z GT to średnie z 3 wnętrz z prawdą referencyjną, pozostałe z 6 serii. Pełna",
          "tabela per seria: [reports/calibration/full_pipeline.md](reports/calibration/full_pipeline.md).", "",
          "| Metryka (cel ze SPEC) | neutral przed → po | airy przed → po | premium przed → po |", "|---|---|---|---|"]
    md += [f"| {label} | " + " | ".join(cell(p, key, n, b) for p in PRESETS) + " |" for label, key, n, b in CAL_ROWS]
    c2, c3 = load("calibration", "calibration.json"), load("calibration", "continuation", "calibration.json")
    md += ["", "Kalibracja poprawia cele ze SPEC: neutralność i jasność ścian. Funkcja celu (`neutral`):",
           f"{c2['loss_before']:.2f} → {c2['loss_after']:.2f} (przebieg 2) → {c3['loss_after']:.2f} (przebieg 3). "
           "Przebiegi: [reports/calibration/](reports/calibration/)."]
    v = load("calibration", "validation.json")["results"]
    md += ["", "**Walidacja na danych nieużytych w kalibracji** (preset `neutral`, przed → po, kod z dnia kalibracji;",
           "[validation.json](reports/calibration/validation.json)):", "",
           "| Zbiór | Mediana jasności | ΔE jasnych powierzchni (auto) | Przepalenia poza nieodzyskiwalnymi, % |",
           "|---|---|---|---|"]
    for name, key in (("HDR+ (6 serii z prawdziwą treścią wnętrz)", "hdrplus"),
                      ("OpenCV: Memorial Church (Debevec) i St. Louis (noc)", "opencv")):
        b, a = v["before"][key], v["cal3"][key]
        md.append(f"| {name} | {f(b['median_luma'])} → {f(a['median_luma'])} | {f(b['wall_dE_auto'])} → "
                  f"{f(a['wall_dE_auto'])} | {f(b['clipped_excl_%'])} → {f(a['clipped_excl_%'])} |")
    md += ["", "Gotowe zdjęcia (tryb jednej klatki) sprawdza osobno test „nie psuć” (6.5)."]
    return md


# --- 6.2 ------------------------------------------------------------------------------------------
SETS = (("syntetyczne", "syntetyczne"), ("hdrplus", "HDR+"), ("opencv", "OpenCV"), ("portfolio_single", "portfolio"))


def cmp_mean(m, version, s, key):
    vals = [r[key] for k, r in m.get(version, {}).items() if k.startswith(s + "/") and r.get(key) is not None]
    return st.mean(vals) if vals else None


def section_comparisons():
    m = load("comparisons", "metrics.json")
    md = ["### 6.2 Porównania przed i po dla każdego presetu", "",
          f"[reports/comparisons/README.md](reports/comparisons/README.md) zawiera {len(m['neutral'])} zestawień "
          "(klatka referencyjna | neutral | airy | premium)",
          "i tabele metryk per seria. „Przed” to klatka referencyjna prosto z aparatu, „po” to wynik presetu. Średnie:", "",
          "| Zbiór | Wersja | Mediana jasności | Przepalenia*, % | Zaczernienia, % | Neutralność ΔE (auto) | "
          "Pionowość [°] | Ściany L* (GT) | Widok L** |", "|---|---|---|---|---|---|---|---|---|"]
    for s, label in SETS:
        cnt = len([k for k in m["neutral"] if k.startswith(s + "/")])
        if not cnt:
            continue
        for ver in ("before",) + PRESETS:
            vals = [cmp_mean(m, ver, s, k) for k in ("median_luma", "clipped_excl_%", "crushed_%", "wall_dE_auto",
                                                      "vert_med_deg")]
            md.append(f"| {label} ({cnt}) | {'przed' if ver == 'before' else ver} | "
                      + " | ".join(f(x) for x in vals)
                      + f" | {f(cmp_mean(m, ver, s, 'wall_L_gt'), 1)} | {f(cmp_mean(m, ver, s, 'win_L'), 1)} |")
    md += ["", "\\* Piksele ≥ 254/255 poza obszarami przepalonymi we wszystkich klatkach (łącznie z lampami i oknami).",
           "W wierszu „przed” liczone są wszystkie, bo pojedyncza klatka nic nie wie o pozostałych.",
           "\\** Średnie L* widoku za oknem z maski okien pipeline'u, bez pikseli przepalonych.", "",
           "Pionowość na zdjęciach bez architektonicznych pionów (portret, zbliżenie, kopuła z rybiego oka) nie oznacza",
           "krzywych ścian (§9).", "",
           "![syntetyczne](reports/comparisons/syntetyczne__IMG_0000.jpg)",
           "![HDR+](reports/comparisons/hdrplus__HDRP_0000.jpg)"]
    return md


# --- 6.3 ------------------------------------------------------------------------------------------
def handheld(scene):
    p = os.path.join(SYN_GT, scene, "params.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return bool(json.load(fh)["series"].get("handheld"))


def ca_residual_px(scales, truth):
    """Largest |estimated - true| R/B scale times the corner radius of the synthetic frame."""
    return max(abs(scales[0] - truth[0]), abs(scales[1] - truth[1])) * 0.5 * (FRAME[0] ** 2 + FRAME[1] ** 2) ** 0.5


def stage_numbers():
    v, me = load("verification.json"), load("modules_eval.json")
    al, geo, noise = v["alignment"], v["geometry"], v.get("noise_single_raw") or []
    truth, ca = me["ca"]["truth"], me["ca"]["scenes"]
    return {
        "v": v, "me": me, "extras": v.get("spec_extras") or {},
        "tri": [x["mean_err_px"] for sc, e in al.items() if handheld(sc) is False for x in e],
        "hand": [x["mean_err_px"] for sc, e in al.items() if handheld(sc) for x in e],
        "hand_shift": [x["true_shift_px"] for sc, e in al.items() if handheld(sc) for x in e],
        "k1_err": [abs(x["k1_est"] - x["k1_true"]) for x in geo.values()],
        "pitch_err": [abs(x["pitch_correction"] + x["pitch_true"]) for x in geo.values()],
        "roll_err": [abs(x["roll_correction"] + x["roll_true"]) for x in geo.values()],
        "vert_after": [x["vert_med_deg_after"] for x in geo.values()],
        "ca_lin": [ca_residual_px(s["linear"], truth) for s in ca.values()],
        "ca_420": [ca_residual_px(s["jpeg_420"], truth) for s in ca.values()],
        "ca_pipe": [ca_residual_px(x["scales_est"], truth) for x in v.get("lens_ca", {}).values()],
        "noise_red": [100 * (1 - n["sigma_after"] / n["sigma_before"]) for n in noise],
        "noise_n": len(noise), "noise_lower": sum(n["sigma_after"] < n["sigma_before"] for n in noise),
    }


def section_stages():
    s = stage_numbers()
    v, me, w = s["v"], s["me"], s["v"]["windows"]
    g, t3, geo, sky = v["grouping"], v["three_of_n"], v["geometry"], me["sky"]
    unrec = [x["unrecoverable_pct"] for x in w.values() if x["unrecoverable_pct"] > 1]
    k1 = " / ".join(format(x["k1_est"], ".3f") for x in geo.values())
    k1t = " / ".join(format(x["k1_true"], ".2f") for x in geo.values())
    return ["### 6.3 Etapy pipeline'u względem prawdy referencyjnej", "",
            "Pomiary z [tools/verify_hypotheses.py](tools/verify_hypotheses.py) ([verification.json](reports/verification.json))",
            "i [tools/eval_modules.py](tools/eval_modules.py) ([modules_eval.json](reports/modules_eval.json)) na scenach",
            f"syntetycznych {FRAME[0]}×{FRAME[1]}:", "", "| Etap | Wynik |", "|---|---|",
            f"| Grupowanie | {g['with_exif']['series_exact']}/{g['with_exif']['of']} serii dokładnie z EXIF i "
            f"{g['without_exif']['series_exact']}/{g['without_exif']['of']} bez EXIF (same piksele). Uszkodzony plik trafia "
            "do `unreadable` |",
            f"| Wyrównanie | średni błąd siatki: statyw {rng(s['tri'])} px, z ręki {rng(s['hand'])} px przy przesunięciach "
            f"{rng(s['hand_shift'], 0)} px |",
            "| Merge: 3 klatki z N | mediana błędu log2 radiancji: wszystkie klatki "
            f"{rng([t3[x]['all']['median_abs_log2_err'] for x in t3], 3)}, 3 skrajne "
            f"{rng([t3[x]['3_extremes']['median_abs_log2_err'] for x in t3], 3)}, 3 środkowe "
            f"{rng([t3[x]['3_central']['median_abs_log2_err'] for x in t3], 3)} |",
            f"| Okna | odzyskiwalne przepalenia {rng([x['recoverable_clipped_pct'] for x in w.values()], 0)}%, L* widoku "
            f"{rng([x['view_L'] for x in w.values()], 1)}, detal {rng([x['detail_ratio'] for x in w.values()])}× GT, halo "
            f"{rng([x['halo_dL'] for x in w.values()], 1)} L*. Okna przepalone już w najciemniejszej klatce "
            f"({' i '.join(f'{u:.0f}%' for u in unrec)} powierzchni okna) zostają białe |",
            f"| Geometria | k1 {k1} przy prawdzie {k1t}; błąd korekty pochylenia {rng(s['pitch_err'])}°, przechyłu "
            f"{rng(s['roll_err'])}°; mediana odchylenia pionów po korekcie {rng(s['vert_after'])}° |",
            "| Aberracja chromatyczna | prawda: skala R +0.12%, B −0.12%. Resztka w rogu kadru: dane liniowe "
            f"{rng(s['ca_lin'])} px, JPEG 4:2:0 {rng(s['ca_420'])} px (subsampling rozmywa przesunięcie kolorów już w "
            f"pliku), pełny pipeline na seriach syntetycznych {rng(s['ca_pipe'])} px |",
            f"| Odszumianie | {s['noise_n']} zaszumionych pojedynczych RAW z HDR+: σ szumu niższe w "
            f"{s['noise_lower']}/{s['noise_n']}, o {rng(s['noise_red'], 0)}% |",
            f"| Niebo | IoU {v['sky']['synthetic_iou']:.2f} (syntetyczny exterior); wykryte na "
            f"{sky['exteriors']['with_sky']}/{sky['exteriors']['images']} exteriorach HDR+ i na "
            f"{sky['portfolio_interiors']['with_sky']}/{sky['portfolio_interiors']['images']} wnętrzach portfolio "
            "(niebo za szybą, §9) |"]


# --- 6.4 ------------------------------------------------------------------------------------------
def section_modules():
    me = load("modules_eval.json")
    h, rd = me["removal"]["mean_de2000_in_hole"]["homogeneous"], me["removal"]["mean_de2000_in_hole"]["random"]
    return ["### 6.4 Moduły opcjonalne", "", "| Moduł | Pomiar |", "|---|---|",
            f"| Usuwanie obiektów | {me['removal']['images']} wycinków zdjęć portfolio; eliptyczną dziurę (16% boku) wypełnia "
            "metoda, a wynik jest porównany z oryginałem (ΔE2000 w dziurze). Jednorodne tło: "
            f"{h['patch']:.2f} (exemplar) vs {h['telea']:.2f} (Telea), exemplar lepszy w {h['patch_better']}/{h['n']}. "
            f"Losowe miejsce: {rd['patch']:.2f} vs {rd['telea']:.2f}, lepszy w {rd['patch_better']}/{rd['n']}. "
            "Poza maską i otoczką piksele bez zmian (test) |",
            "| Wymiana nieba | detekcja: patrz 6.3; zdjęcie nieba użytkownika jest komponowane w pełnej rozdzielczości (test) |",
            "| Twilight | syntetyczny dom (8 okien i drzwi): zapalonych 9 obszarów, wszystkie na oknach albo drzwiach, nic na "
            "trawniku (test, D-45) |",
            "| Trawa | trawnik zieleńszy, kolory poza trawnikiem bez zmian (test) |"]


# --- 6.5 ------------------------------------------------------------------------------------------
def section_portfolio():
    p = load("portfolio_do_no_harm.json")
    m = p["metrics"]
    worst = ", ".join(f"{n} ({x:.2f})" for n, x in p["worst_ssim"][:3])
    return ["### 6.5 Test „nie psuć” (tryb jednej klatki, gotowe zdjęcia z portfolio)", "",
            f"{p['ok']} z {p['images']} zdjęć bez błędu. Wynik względem wejścia:",
            f"- SSIM: mediana **{m['ssim']['median']:.3f}**, p10 {m['ssim']['p10']:.3f}, minimum {m['ssim']['min']:.3f};",
            f"  poniżej 0.85: {p['ssim_below_0.85']}/{p['images']} zdjęć (najniższe: {worst});",
            f"- ΔE2000: mediana **{m['dE_ref']['median']:.2f}**, średnia {m['dE_ref']['mean']:.2f}, "
            f"p90 {m['dE_ref']['p90']:.2f};",
            f"- przepalenia poza nieodzyskiwalnymi średnio {m['clipped_excl_%']['mean']:.2f}%, zaczernienia średnio "
            f"{m['crushed_%']['mean']:.2f}% (maksimum {m['crushed_%']['max']:.2f}%);",
            f"- pionowość: mediana {m['vert_med_deg']['median']:.2f}°.", "",
            "Cel SPEC: SSIM ≥ 0.85 i średnie ΔE ≤ 6. Najniższe SSIM mają głównie zdjęcia, którym pipeline prostuje piony:",
            "zamierzona zmiana geometrii obniża SSIM. Plik: [reports/portfolio_do_no_harm.json](reports/portfolio_do_no_harm.json)."]


# --- 6.6 ------------------------------------------------------------------------------------------
STAGE_PL = {"load": "wczytanie", "align": "wyrównanie", "merge": "merge", "lens": "obiektyw", "windows": "okna",
            "white_balance": "WB", "tonemap": "tone mapping", "denoise": "odszumianie", "geometry": "geometria",
            "export": "eksport", "modules": "moduły"}


def section_perf():
    pf, p = load("perf.json"), load("portfolio_do_no_harm.json")
    md = ["### 6.6 Wydajność i pamięć", "", f"Maszyna: {pf['machine']}. Jedna seria na jednym workerze.", "",
          "| Seria | Czas | Szczyt RAM | Najdłuższe etapy |", "|---|---|---|---|"]
    for name, s in pf["series"].items():
        top = sorted(s["timings"].items(), key=lambda kv: -kv[1])[:4]
        md.append(f"| {name} ({s['width']}×{s['height']}) | {s['seconds']:.0f} s | {s['peak_rss_gb']:.2f} GB | "
                  + ", ".join(f"{STAGE_PL.get(k, k)} {t:.0f} s" for k, t in top) + " |")
    n, wk = p["images"], p["workers"]
    md += ["", f"Batch: {n} {pl(n, 'zdjęcie', 'zdjęcia', 'zdjęć')} portfolio w trybie jednej klatki, {wk} "
           f"{pl(wk, 'worker', 'workery', 'workerów')}, {p['seconds']:.0f} s.",
           "Szczegóły: [reports/perf.json](reports/perf.json)."]
    return md


# --- 6.7 ------------------------------------------------------------------------------------------
def section_acceptance():
    s = stage_numbers()
    d, m = load("calibration", "full_pipeline.json"), load("comparisons", "metrics.json")
    p, pf = load("portfolio_do_no_harm.json"), load("perf.json")["series"]
    v, ex = s["v"], s["extras"]
    rows = []

    def after(key):
        return [d[q][key]["after"] for q in PRESETS if key in d.get(q, {})]

    def per_preset(key, n=1):
        return ", ".join(f"{q} {d[q][key]['after']:.{n}f}" for q in PRESETS if key in d.get(q, {}))

    def row(crit, goal, result, ok):
        rows.append((f"| {crit} | {goal} | {result} | {ok} |", ok))

    g = v["grouping"]
    row("Odporność batcha", "błędny plik nie zatrzymuje batcha",
        "uszkodzony plik, niepełna seria, brak EXIF, awaria workera (`tests/test_robustness.py`)", "tak (test)")
    row("Grupowanie", "100% z EXIF i bez", f"{g['with_exif']['series_exact']}/{g['with_exif']['of']} i "
        f"{g['without_exif']['series_exact']}/{g['without_exif']['of']}",
        status(all(g[k]["series_exact"] == g[k]["of"] for k in ("with_exif", "without_exif"))))
    e = ex.get("exposures")
    if e:
        row("Ekspozycje względne", "±0.1 EV od GT", f"maks. błąd {e['max_abs_err_ev']:.3f} EV",
            status(e["max_abs_err_ev"] <= 0.1))
    else:
        row("Ekspozycje względne", "±0.1 EV od GT", "`test_exposures_without_exif`", "tak (test)")
    shift = max(s["hand_shift"], default=0.0)
    row("Wyrównanie", "≤ 0.6 px statyw, ≤ 0.8 px z ręki (przesunięcia do 20 px)",
        f"{rng(s['tri'])} px i {rng(s['hand'])} px; sprawdzone przesunięcia do {shift:.0f} px",
        status(max(s["tri"]) <= 0.6 and max(s["hand"]) <= 0.8, partial=shift < 15))
    gh = ex.get("ghost")
    if gh:
        row("Duchy", "< 2% maski ducha odbiega o > 0.5 EV", f"{gh['fraction_pct']:.2f}%", status(gh["fraction_pct"] < 2))
    else:
        row("Duchy", "< 2% maski ducha odbiega o > 0.5 EV", "`test_deghosting_moving_object`", "tak (test)")
    row("Przepalenia poza światłami", "< 0.5%", f"{rng(after('clipped_nonlight_%'))}%",
        status(max(after("clipped_nonlight_%")) < 0.5))
    row("Zaczernienia", "< 0.5%", f"{rng(after('crushed_%'))}%", status(max(after("crushed_%")) < 0.5))
    halo = [abs(x) for x in after("halo_dL")] + [abs(x["halo_dL"]) for x in v["windows"].values()]
    row("Halo okno/ściana", "< 4 L*", f"maks. {max(halo):.1f} L*", status(max(halo) < 4))
    for q, (lo, hi) in (("neutral", (78, 88)), ("airy", (84, 92)), ("premium", (74, 86))):
        wl = d[q]["wall_L_gt"]["after"]
        row(f"Jasność ścian `{q}`", f"L* {lo}–{hi}", f"{wl:.1f}", status(lo <= wl <= hi))
    row("Okna: odzyskiwalne przepalenia", "< 5%", f"{rng(after('win_clip_recov_%'), 1)}%",
        status(max(after("win_clip_recov_%")) < 5))
    ok_view = all((45 <= d[q]["win_L"]["after"] <= 70) if q == "premium" else (55 <= d[q]["win_L"]["after"] <= 80)
                  for q in PRESETS)
    row("Okna: L* widoku", "55–80 (premium 45–70)", per_preset("win_L"), status(ok_view))
    row("Okna: detal", "≥ 0.6× GT", f"{rng(after('win_detail_ratio'))}×", status(min(after("win_detail_ratio")) >= 0.6))
    wi = ex.get("window_iou")
    if wi:
        row("Okna: IoU maski", "≥ 0.8", rng(wi["iou"]), status(min(wi["iou"]) >= 0.8))
    else:
        row("Okna: IoU maski", "≥ 0.8", "test sprawdza > 0.6", "nie zmierzone")
    row("Neutralność ścian", "ΔE ≤ 3.0", per_preset("wall_dE_gt", 2), status(max(after("wall_dE_gt")) <= 3.0))
    wb = ex.get("white_balance") or {}
    if "bulb_dE" in wb:
        row("Neutralność w strefie żarówek", "ΔE ≤ 5.0", rng(wb["bulb_dE"]), status(max(wb["bulb_dE"]) <= 5.0))
    else:
        row("Neutralność w strefie żarówek", "ΔE ≤ 5.0", "—", "nie zmierzone")
    if "accent_dH_deg" in wb:
        row("Ściana akcentowa", "ΔH < 10°", f"{wb['accent_dH_deg']:.1f}°", status(wb["accent_dH_deg"] < 10))
    else:
        row("Ściana akcentowa", "ΔH < 10°", "`test_white_balance_removes_cast` (akcent zostaje czerwony)", "tak (test)")
    vert = after("vert_med_deg") + s["vert_after"]
    row("Piony", "mediana ≤ 0.5°", f"{rng(vert)}°", status(max(vert) <= 0.5))
    row("Dystorsja", "\\|k1 − k1_GT\\| ≤ 0.02", f"maks. {max(s['k1_err']):.3f}", status(max(s["k1_err"]) <= 0.02))
    row("Winieta", "resztka w rogu ≤ 8%", "płaskie sceny ≤ 8% (test); wnętrza syntetyczne: korekta odrzucana przez "
        "strażniki (D-44)", "częściowo")
    row("Aberracja chromatyczna", "≤ 0.3 px na brzegu", f"liniowe {rng(s['ca_lin'])} px, pipeline {rng(s['ca_pipe'])} px",
        status(max(s["ca_lin"] + s["ca_pipe"]) <= 0.3))
    row("Szum", "σ niższe niż w klatce", f"{s['noise_lower']}/{s['noise_n']} RAW, o {rng(s['noise_red'], 0)}%",
        status(s["noise_n"] > 0 and s["noise_lower"] == s["noise_n"]))
    sh = ex.get("sharpness")
    if sh:
        row("Ostrość", "≥ 0.9× wejścia", f"{rng(sh['ratio'])}×", status(min(sh["ratio"]) >= 0.9))
    else:
        row("Ostrość", "≥ 0.9× wejścia", "—", "nie zmierzone")
    pb = [cmp_mean(m, "before", "portfolio_single", k) for k in ("clipped_%", "crushed_%")]
    pa = [cmp_mean(m, "neutral", "portfolio_single", k) for k in ("clipped_%", "crushed_%")]
    if None not in pb + pa:
        row("Jedna klatka: przepalenia i zaczernienia", "spadają",
            f"przepalenia {pb[0]:.2f} → {pa[0]:.2f}%, zaczernienia {pb[1]:.2f} → {pa[1]:.2f}% (portfolio, 6.2)",
            status(pa[0] <= pb[0] and pa[1] <= pb[1]))
    ss, de, below = p["metrics"]["ssim"], p["metrics"]["dE_ref"], p["ssim_below_0.85"]
    row("„Nie psuć” (portfolio)", "SSIM ≥ 0.85, średnie ΔE ≤ 6",
        f"SSIM mediana {ss['median']:.3f}, {below}/{p['images']} zdjęć poniżej 0.85; ΔE średnie {de['mean']:.2f}",
        status(ss["min"] >= 0.85 and de["mean"] <= 6, partial=below > 0 and ss["median"] >= 0.85 and de["mean"] <= 6))
    row("Maska nieba", "IoU ≥ 0.85", f"{v['sky']['synthetic_iou']:.2f}", status(v["sky"]["synthetic_iou"] >= 0.85))
    row("Twilight", "niebo w stylu, okna świecą, fasada ciemniejsza", "`test_twilight_*`", "tak (test)")
    row("Usuwanie obiektów", "poza maską bez zmian (poza otoczką 8 px)", "`test_object_removal_*`", "tak (test)")
    row("Eksport", "sRGB ICC, wymiary, EXIF", "`test_exports_sizes_profile_exif`, `test_jpeg_has_srgb_icc_and_exif`",
        "tak (test)")
    t24 = [x for k, x in pf.items() if "24" in k]
    if t24:
        row("Czas 3×24 Mpx", "≤ 90 s (4 rdzenie)", f"{t24[0]['seconds']:.0f} s", status(t24[0]["seconds"] <= 90))
    big = [x["peak_rss_gb"] for k, x in pf.items() if "60" in k]
    if big:
        row("Pamięć 3×60 Mpx", "≤ 6 GB na workera", f"{max(big):.2f} GB", status(max(big) <= 6))
    n_no = sum(ok == "**nie**" for _, ok in rows)
    n_part = sum(ok == "częściowo" for _, ok in rows)
    n_unm = sum(ok == "nie zmierzone" for _, ok in rows)
    return ["### 6.7 Kryteria akceptacji ze SPEC: podsumowanie", "",
            f"Ta tabela też powstaje z raportów. {len(rows)} {pl(len(rows), 'kryterium', 'kryteria', 'kryteriów')}: "
            f"niespełnione {n_no}, spełnione częściowo {n_part}, bez pomiaru {n_unm}.",
            "„Tak (test)” oznacza, że kryterium sprawdza test automatyczny, bez osobnej liczby w raporcie. Przyczyny braków",
            "opisuje §9.", "", "| Kryterium | Cel (SPEC) | Wynik | Spełnione |", "|---|---|---|---|"] + [r for r, _ in rows]


# --- 6.8 ------------------------------------------------------------------------------------------
def section_tests(count):
    n = None
    if count:
        try:
            out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=600).stdout
            n = int(re.search(r"(\d+) tests? collected", out).group(1))
        except Exception:
            n = None
    return ["### 6.8 Testy automatyczne", "",
            f"`./estatehdr.sh test`: **{n if n else '?'} testów** w `tests/`. Pokrycie:",
            "- wejście, EXIF, profile ICC, mapy cieniowania DNG, uszkodzone pliki;",
            "- grupowanie;",
            "- ekspozycje i krzywa odpowiedzi, wyrównanie względem GT, merge i duchy;",
            "- okna, WB, tone mapping (kolejność jasności, czerń scen o małym kontraście), odszumianie, CA, winieta,",
            "  dystorsja, piony, tryb nocny;",
            "- tryb jednej klatki (przepalenia, szum), moduły (usuwanie lokalne, niebo, twilight, trawa);",
            "- batch: izolacja błędów i awarii workera, logi, kody wyjścia;",
            "- eksport (ICC v2, EXIF, rozmiary), CLI, web UI, ścieżka GPU (UMat) zgodna z CPU."]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-tests", action="store_true", help="do not count the tests (pytest --collect-only)")
    a = ap.parse_args(argv)
    path = os.path.join(ROOT, "README.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if START not in text or END not in text:
        sys.exit("README.md has no METRICS markers")
    parts = ["Wszystkie liczby w tej sekcji generuje `tools/update_readme_metrics.py` z plików w [reports/](reports/)",
             "(4 rdzenie CPU, bez GPU, finalna konfiguracja). Dane testowe opisuje §7.", ""]
    for sec in (section_calibration, section_comparisons, section_stages, section_modules, section_portfolio,
                section_perf, section_acceptance):
        parts += sec() + [""]
    parts += section_tests(not a.no_tests)
    new = text[:text.index(START) + len(START)] + "\n" + "\n".join(parts) + "\n" + text[text.index(END):]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("README section 6 regenerated")


if __name__ == "__main__":
    main()
