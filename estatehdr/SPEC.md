# SPEC.md — EstateHDR

Specyfikacja wynika z REVERSE.md. Punkty 1–12 mają kryterium akceptacji, a punkt 15 limity wydajności; punkty
13, 14 i 16 są opisowe. Kryteria sprawdzają testy (`tests/`) oraz skrypty w `tools/`: `evaluate.py` (metryki
jakości), `verify_hypotheses.py` (`reports/verification.json`, m.in. `spec_extras`), `do_no_harm.py`
(`reports/portfolio_do_no_harm.json`), `measure_perf.py` (`reports/perf.json`) i `eval_modules.py`
(`reports/modules_eval.json`).

## 1. Wejście
- Pliki: JPEG, PNG, TIFF (8/16-bit, float), RAW (wszystkie formaty LibRaw: CR2/CR3/NEF/ARW/RAF/DNG/RW2/ORF/PEF/SRW/…).
- Folder (rekurencyjnie) albo lista plików. Serie mają 1–10 klatek, typowo 3, 5 lub 7.
- **Akceptacja:** uszkodzony plik, seria niepełna albo brak EXIF nie zatrzymują batcha. Błąd trafia do logu i raportu `report.json`.

## 2. Grupowanie (R-GROUP)
- Sygnały: zmiana aparatu/rozmiaru/ogniskowej, przerwa czasowa (EXIF), powtórzenie ekspozycji, podobieństwo treści (niezmiennicze względem ekspozycji), opcjonalnie stała liczba klatek.
- Ręczna korekta: plik `groups.json` (CLI `--groups`) albo przeciąganie w UI.
- **Akceptacja:** 100% dokładnych dopasowań grup na zbiorze syntetycznym, z EXIF i bez EXIF (tylko obraz).

## 3. Linearyzacja i ekspozycje (R-LIN)
- RAW → liniowe sRGB (LibRaw). JPEG → odwrotna krzywa aparatu (sRGB + dopasowany S-curve). 16-bit TIFF → automatyczny wybór liniowy/sRGB.
- **Akceptacja:** względne ekspozycje w ±0.1 EV od GT; odzyskana krzywa daje spójność między klatkami lepszą niż samo sRGB.

## 4. Wyrównanie i ghosting (R-ALIGN)
- SIFT + RANSAC i ECC na obrazach znormalizowanych ekspozycyjnie; model ruchu wybierany per klatka (`align.model: auto`, D-52): domyślnie afiniczny, homografia tylko gdy dopasowania SIFT ją potwierdzają (iloraz wiarygodności > `auto_llr`, różnica modeli > `auto_min_px` w rogu kadru, dowód w siatce `auto_grid`×`auto_grid`). Fallback MTB. Odrzucanie ruchomych obiektów względem klatki referencyjnej (środkowej).
- **Akceptacja:** średni błąd siatki ≤ 0.6 px (statyw) i ≤ 0.8 px (z ręki, przesunięcia do 20 px) na 2400×1600. Obiekt ruchomy nie zostawia „przezroczystego” śladu: < 2% pikseli maski ducha odbiega o > 0.5 EV od referencji.

## 5. Merge HDR i tone mapping (R-TONE)
- Merge do radiancji (wszystkie klatki, wagi SNR). Lokalny tone mapping z filtrem krawędziowym (bez halo), krzywa filmowa, presety.
- **Akceptacja:** prześwietlenia (≥ 254/255) < 0.5% i zaczernienia (≤ 1/255) < 0.5% pikseli poza źródłami światła. Halo przy krawędzi okno/ściana: przestrzelenie luminancji < 4 L* w paśmie 2–40 px. Mediana L* ścian: neutral 78–88, airy 84–92, premium 74–86.

## 6. Window pull (R-WIN)
- Okna = obszary poza zakresem wnętrza w radiancji, sklasyfikowane geometrycznie i kolorystycznie. Widok jest renderowany osobną ekspozycją (z danych ciemnych klatek) i wtapiany maską dopasowaną do krawędzi.
- **Akceptacja (GT):** < 5% przepalonych pikseli okna (gdy najciemniejsza klatka nie jest przepalona). Średnie L* widoku 55–80 (premium 45–70). Detal (energia gradientu) ≥ 0.6× GT. IoU maski okna z GT ≥ 0.8.

## 7. Balans bieli i mieszane światło (R-WB)
- Globalny WB z neutralnych, gładkich powierzchni. Lokalna korekta temperatury wzdłuż locus Plancka (żarówka ↔ dzień), bez neutralizowania kolorowych ścian.
- **Akceptacja (GT):** średnie ΔE2000 bieli ścian od neutralnej szarości tej samej jasności ≤ 3.0 globalnie i ≤ 5.0 w strefie żarówek. Ściana kolorowa (akcent) zachowuje odcień (ΔH < 10°).

## 8. Geometria i obiektyw (R-GEO)
- Dystorsja: automatyczna estymacja k1 (plumb-line), korekcja przed perspektywą. Piony: punkt zbiegu, homografia, crop w proporcjach oryginału, skalowanie z powrotem do wymiarów wejścia. Winieta: estymacja z gradientów radialnych. CA: dopasowanie skali kanałów R/B.
- **Akceptacja (GT):** mediana |odchylenia| długich pionów ≤ 0.5°. |k1 − k1_GT| ≤ 0.02. Resztkowa winieta w rogu ≤ 8%. Resztkowe CA ≤ 0.3 px na brzegu.

## 9. Odszumianie i wyostrzanie (R-DETAIL)
- Odszumianie luminancji (wielo-skalowe) i chrominancji. Wyostrzanie USM z ograniczeniem halo, osobne dla każdego rozmiaru eksportu.
- **Akceptacja:** szum na płaskiej ścianie (σ w L*) niższy niż w klatce środkowej. Ostrość (energia gradientu na krawędziach) ≥ 0.9× wejścia.

## 10. Tryb pojedynczego zdjęcia (R-SINGLE)
- Pseudo-HDR: odzysk świateł i cieni z jednej klatki. Te same etapy co wyżej, bez merge.
- **Akceptacja:** spada liczba przepalonych i zaczernionych pikseli. Zdjęcie już poprawnie wywołane (portfolio) nie jest psute: SSIM ≥ 0.85 względem wejścia, ΔE średnie ≤ 6.

## 11. Moduły opcjonalne (flagi)
- `sky` (wymiana nieba: 3 style proceduralne albo własne pliki), `twilight` (3 style: blue, pink, golden), `remove` (usuwanie obiektów z maski: PNG albo pędzel w UI), `grass` (zazielenienie trawy).
- **Akceptacja:** maska nieba IoU ≥ 0.85 na scenie zewnętrznej GT. Twilight: niebo w stylu, okna świecą, fasada przyciemniona. Usuwanie: w masce brak obiektu, poza maską bez zmian (bit-identyczne poza otoczką 8 px).

## 12. Eksport (R-EXPORT)
- JPEG sRGB z osadzonym profilem ICC i EXIF skopiowanym z klatki referencyjnej (Orientation=1, Software, wymiary). Rozmiary: `full` (wymiary wejścia) i `mls` (2048 px dłuższy bok). Lista rozmiarów jest konfigurowalna.
- **Akceptacja:** pliki otwierają się, mają profil sRGB, poprawne wymiary i EXIF (Make/Model/DateTimeOriginal).

## 13. Presety
- `neutral` (≈ AutoHDR Classic), `airy` (jasny, miękki kontrast), `premium` (≈ Lisa: pop, głębszy window pull). Wartości są w `config.yaml`.

## 14. Interfejsy
- CLI: `./estatehdr.sh process <folder> [-o out] [--preset …] [--sky] [--twilight pink] …`, `./estatehdr.sh web`.
- Web (lokalnie, po polsku): drag & drop folderu, grupy z ręczną korektą, wybór presetu i modułów, kolejka z postępem, podgląd przed/po z suwakiem, pobieranie (pojedynczo i ZIP).

## 15. Wydajność i zasoby
- CPU (4 rdzenie): seria 3×24 Mpx ≤ 90 s, 3×60 Mpx działa w ≤ 6 GB RAM na workera. Batch jest równoległy, liczba workerów wynika z budżetu pamięci. GPU przez OpenCL (OpenCV T-API) jest używane, gdy jest dostępne; w przeciwnym razie CPU (D-13).

## 16. Ocena jakości (`tools/evaluate.py`)
Raportuje: histogram, % prześwietleń i zaczernień, pionowość linii (°), neutralność bieli ścian (ΔE), jasność i detal okien. Przy parach referencyjnych dodatkowo SSIM, MS-SSIM, gradient-SSIM, ΔE2000 i LPIPS (jeśli dostępny). Wynik: `quality.json` + `quality.md`. Obrazy porównawcze przed/po z tabelą metryk tworzy `tools/make_comparisons.py`.
