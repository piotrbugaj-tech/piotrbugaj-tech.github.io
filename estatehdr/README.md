# EstateHDR — automatyczna obróbka zdjęć nieruchomości

EstateHDR to działający lokalnie odpowiednik usług typu AutoHDR. Z serii bracketingowych (3–7 klatek
RAW/JPEG/TIFF) albo pojedynczych zdjęć robi gotowe do ogłoszenia zdjęcia wnętrz i budynków:
- naturalny merge HDR i widok za oknami (window pull);
- neutralną biel ścian przy mieszanym świetle;
- proste piony, bez dystorsji, winiety i aberracji;
- odszumianie i delikatne wyostrzenie;
- eksport sRGB JPEG w kilku rozmiarach (pełny + MLS 2048) z profilem ICC i EXIF.

Moduły opcjonalne: wymiana nieba, wirtualny zmierzch (twilight), usuwanie drobnych obiektów i zieleńsza trawa.
Interfejsy: wiersz poleceń (CLI) i lokalny interfejs webowy po polsku.

Jak powstał (analiza AutoHDR metodą skilla *reverse-engineer-anything*, wyłącznie na materiałach publicznych i
jako black-box): [REVERSE.md](REVERSE.md). Specyfikacja i kryteria akceptacji: [SPEC.md](SPEC.md). Założenia:
[DECISIONS.md](DECISIONS.md). Licencje: [LICENSES.md](LICENSES.md).

---

## 1. Instalacja i uruchomienie jedną komendą

Wymagania: Python ≥ 3.10 (testowany 3.13), Linux / macOS / Windows, ok. 3 GB RAM na serię 24–60 Mpx.
GPU jest opcjonalne.

```bash
cd estatehdr
./estatehdr.sh process /ścieżka/do/sesji        # obróbka folderu -> /ścieżka/do/sesji/estatehdr_output/
./estatehdr.sh web                              # interfejs: http://127.0.0.1:8765
./estatehdr.sh test                             # testy automatyczne
```

Przy pierwszym uruchomieniu skrypt tworzy `.venv` i instaluje [requirements.txt](requirements.txt). Na Windows
służy do tego `estatehdr.bat` z tymi samymi poleceniami. Bez skryptu:
`pip install -r requirements.txt && python -m estatehdr process <folder>`.

Wyniki dla każdej serii trafiają do folderu wyjściowego:
- `<seria>_full.jpg`: wymiary jak wejście;
- `<seria>_mls.jpg`: dłuższy bok 2048 px;
- `report.json`: parametry, ostrzeżenia, czasy i pamięć. Zapisywany po każdej serii (`"complete": false` i lista
  `pending`), a na końcu z `"complete": true`. Lista `skipped` pokazuje pliki pominięte celowo (np. JPEG obok
  RAW, poprzednie wyniki EstateHDR), a `unreadable` pliki nieczytelne;
- `groups.json`: grupowanie, do ręcznej korekty (ścieżki względem folderu sesji);
- `estatehdr.log`;
- `.previews/`: podglądy przed/po dla UI.

## 2. Wiersz poleceń

```bash
./estatehdr.sh process SESJA [-o WYJŚCIE] [--preset neutral|airy|premium]
      [--sky [clear|wispy|dramatic|PLIK|KATALOG]] [--twilight [blue|pink|golden]]
      [--remove] [--grass] [--no-verticals] [--no-windows] [--mls-size 2048]
      [--single] [--bracket-size N] [--groups groups.json] [--workers N]
      [--config moj.yaml] [--set klucz.podklucz=wartość ...] [-v]
./estatehdr.sh group SESJA -o groups.json    # samo grupowanie (do ręcznej poprawki)
./estatehdr.sh presets                       # lista presetów
```

Przykłady:

```bash
./estatehdr.sh process ~/sesje/ul_Polna_12 --preset airy
./estatehdr.sh process ~/sesje/dom --sky wispy --grass                 # exteriory z nowym niebem
./estatehdr.sh process ~/sesje/dom --twilight pink                     # wirtualny zmierzch
./estatehdr.sh process ~/sesje/salon --remove        # usuwa obiekty z masek IMG_0012.mask.png (białe = usuń)
./estatehdr.sh group ~/sesje/x -o g.json  &&  (popraw g.json)  &&  ./estatehdr.sh process ~/sesje/x --groups g.json
./estatehdr.sh process ~/zdjecia_z_telefonu --single                   # każde zdjęcie osobno (pseudo-HDR)
./estatehdr.sh process ~/sesje/x --set tonemap.target_key=0.6 --set white_balance.target_cct=6300
```

Batch nie zatrzymuje się na pojedynczym problemie z danymi:
- plik uszkodzony tak, że przy skanowaniu nie da się zdekodować nawet miniatury, trafia do `unreadable` i nie jest
  dołączany do serii. Klatka, która przejdzie skanowanie, ale nie da się jej zdekodować w całości, jest pomijana
  z ostrzeżeniem serii (`skipped undecodable frame(s)`), a reszta serii jest liczona dalej. W trybie `--single`
  skanowanie sprawdza tylko nagłówek: obcięty plik nie trafia wtedy do `unreadable`, tylko jego seria kończy się
  błędem (liczona w `failed_series`);
- niepełna seria albo brak EXIF dają ostrzeżenie tej serii;
- awaria procesu roboczego (np. brak pamięci) przy co najmniej dwóch procesach roboczych dotyczy tylko serii, która
  ją wywołała: serie niedokończone w chwili awarii są przeliczane ponownie, pojedynczo, każda w nowym procesie.
  Gdy działa tylko jeden proces (`--workers 1`, jedna seria, do 3 rdzeni CPU albo pamięć wystarcza na jedną serię),
  serie są liczone w procesie głównym i taka awaria przerywa cały batch; `report.json` zostaje wtedy z
  `"complete": false` i listą `pending`.

Kody wyjścia:
- **0**: wszystko w porządku;
- **1**: w folderze nie ma obsługiwanych zdjęć;
- **2**: nie ma takiego folderu, błędna opcja (`--preset`, `--config`, `--set`, `--groups`; jednolinijkowy komunikat
  `błąd: ...`), któraś seria się nie udała albo któryś plik był nieczytelny.

Ostatnia linia na wyjściu to JSON z liczbami `ok`, `failed` (serie z błędem + nieczytelne pliki), `failed_series` i
`unreadable`. Szczegóły i błędy są też w `estatehdr.log` w folderze wyjściowym, łącznie z logami procesów roboczych.

Fotografowanie RAW+JPEG: pliki o tej samej nazwie w jednym folderze (`IMG_1.CR2` + `IMG_1.JPG`) to jedna klatka,
używany jest RAW. Serie o tej samej nazwie (np. `IMG_0001` w dwóch podfolderach) dostają przyrostek `_2`, `_3`,
więc wyniki się nie nadpisują. Folder wyjściowy wewnątrz sesji jest pomijany przy ponownym uruchomieniu.
Zdjęcia z profilem ICC innym niż sRGB (Adobe RGB, ProPhoto, Display P3) są konwertowane do sRGB (8 bit przez
LittleCMS, 16 bit przez macierz i krzywe tonalne z profilu, a profile tablicowe przez LUT 3D próbkowaną
z LittleCMS; D-35), z ostrzeżeniem w raporcie.

## 3. Interfejs webowy

`./estatehdr.sh web` uruchamia serwer pod `http://127.0.0.1:8765` (tylko lokalnie). Zadania są w `work/jobs/`.
1. **Zdjęcia:** przeciągnij folder (rekurencyjnie) lub wybierz pliki, z paskiem postępu wysyłania.
2. **Serie:** automatyczne grupowanie z miniaturami i EV. Ręczna korekta: przenieś klatkę do innej lub nowej
   serii, połącz albo rozdziel serie, zmień nazwę. Przycisk „Maska usuwania” otwiera pędzel na środkowej
   ekspozycji serii (wg EV; przy parzystej liczbie klatek na jaśniejszej z dwóch środkowych). Pipeline jako klatkę
   referencyjną bierze środkową ekspozycję (przy parzystej liczbie klatek ciemniejszą z dwóch środkowych), a gdy
   jest ona wyraźnie gorzej naświetlona, najlepiej naświetloną klatkę. W tych przypadkach maska może być
   przesunięta o różnicę wyrównania klatek (por. D-30).
3. **Ustawienia:** preset (neutral / airy / premium), piony, okna, niebo, zmierzch, trawa, usuwanie obiektów,
   rozmiar MLS.
4. **Kolejka i wyniki:** postęp każdej serii z nazwą etapu, suwak przed/po, pobieranie pojedynczych plików
   oraz ZIP (MLS / pełne / wszystko). Zadania przetrwają restart serwera.

Zrzuty: [reports/ui/](reports/ui/).

## 4. Jak to działa (pipeline)

| Etap | Moduł | Co robi |
|---|---|---|
| Grupowanie | `grouping.py` | Reguły per para klatek: aparat, rozmiar, ogniskowa, odstęp czasu, powtórzona ekspozycja z EXIF. Bez EXIF: skok jasności ≥ 0.4 EV i podobieństwo kadru. Ręczna korekta przez `groups.json` lub UI |
| Linearyzacja | `series.py`, `io/` | RAW (LibRaw, DHT/FBDD, mapy cieniowania obiektywu GainMap z DNG), TIFF16 (liniowy vs sRGB rozstrzygany zgodnością z EXIF, a bez EXIF zgodnością klatek), JPEG (dopasowanie krzywej odpowiedzi kamery; bez EXIF z samych pikseli, D-50), konwersja profili ICC innych niż sRGB. Ekspozycje z EXIF, weryfikowane pikselami |
| Wyrównanie | `align.py` | SIFT + RANSAC, ECC, dokładny etap ECC w wyższej rozdzielczości, walidacja względem identyczności. Model ruchu wybierany per klatka: afiniczny albo homografia, gdy dopasowania SIFT potwierdzają perspektywę (D-52) |
| Merge HDR | `merge.py` | Radiancja liniowa ze wszystkich klatek (wagi SNR), wykrywanie duchów względem klatki referencyjnej, neutralizacja kolorowej czerni RAW. Praca w pasach |
| Obiektyw | `lens.py` | Aberracja chromatyczna (skala radialna R/B), winieta (symetria gradientów radialnych ze strażnikami przeciw cieniowaniu sceny, albo ręcznie) |
| Scena nocna | `pipeline.py` | Wykrywa nocny exterior (ciemne, gładkie niebo u góry kadru) i wtedy: bez window pull, niski klucz tonalny, noc zostaje nocą |
| Okna | `windows.py` | Fizyczna detekcja obszarów poza zakresem wnętrza i klasyfikacja (okno / lampa / plama słońca / niebo) |
| Balans bieli | `color.py` | Globalny (szare kandydatury → locus Plancka, cel 7400 K przy sile 0.5, czyli biel w połowie drogi; D-32) + lokalne pole mieszanego światła (komórki o pewnej estymacie korygowane w pełni, brakujące uzupełniane z otoczenia; D-51) + osobna korekta widoków. Gotowe JPEG-i: względem neutralnej bieli autora (D-49) |
| Tonemapping | `tonemap.py` | Lokalna kompresja (filtr prowadzony, bez halo), window pull rozwiązywany na krzywej, globalna krzywa PCHIP zakotwiczona na percentylach wnętrza (z limitem rozciągnięcia czerni dla scen o małym kontraście), próg szumu w logarytmie luminancji, kolor z zachowaniem nasycenia, miękkie wygaszanie świateł |
| Odszumianie | `denoise.py` | Funkcja poziomu szumu σ(jasność) (Immerkaer w przedziałach jasności), filtr prowadzony luminancji i chrominancji, dla silnego szumu NLM po stabilizacji wariancji. Pojedynczy RAW: słabsze podnoszenie cieni przy głośnych cieniach (D-39). Gotowe JPEG-i: szum mierzony tylko na najgładszych blokach, więc faktura nie jest rozmywana (D-49) |
| Moduły | `modules/` | Niebo, zmierzch, usuwanie obiektów (exemplar-based) i trawa, przed geometrią |
| Geometria | `geometry.py` | Dystorsja metodą plumb-line, piony z punktu zbiegu (LSD + RANSAC), obrót kamery, crop ≤ 15%, powrót do wymiarów wejścia. Szacowana przed modułami, stosowana po nich (D-42) |
| Eksport | `export.py`, `io/writer.py` | Wyostrzanie z progiem szumu, dithering, sRGB ICC, EXIF z klatki referencyjnej, rozmiary |

Wymagający obliczeniowo kod pełnej rozdzielczości działa w pasach wierszy. Batch używa puli procesów, a liczba
workerów wynika z budżetu RAM.

## 5. Presety i parametry

| Preset | Charakter | Najważniejsze różnice (wartości po kalibracji, D-32, D-37) |
|---|---|---|
| `neutral` (domyślny) | naturalny, jasny wygląd do ogłoszeń (MLS) | klucz tonalny 0.70, kompresja cieni 0.64, widok za oknem ≈ 0.6, biel neutralna przy mieszanym świetle |
| `airy` | jasny, lekki (high-key) | klucz 0.85, łagodniejsza kompresja cieni (0.78), a świateł nieco mocniejsza (0.59), jaśniejszy widok za oknem, mniej kontrastu i nasycenia |
| `premium` | „magazynowy” | ten sam klucz co neutral, ale słabiej podniesione cienie (0.86), więcej kontrastu, wibracji i detalu, ciemniejszy nasycony widok za oknem |

Presety są skalibrowane każdy osobno do swojego pasma jasności ścian ze SPEC (neutral L* 78–88, airy 84–92,
premium 74–86). Jedyne dodatkowe ograniczenie (D-37) dotyczy parametru, a nie wyniku: klucz tonalny premium nie może
przekroczyć klucza neutral (0.70). Dlatego premium ma praktycznie tę samą jasność co neutral (ściany L* 76.0 wobec
75.6 w `reports/calibration/full_pipeline.json`, czasem minimalnie jaśniej). Od neutral różni się kontrastem,
słabiej podniesionymi cieniami i ciemniejszym widokiem za oknem. Airy (klucz 0.85) jest wyraźnie jaśniejszy na
seriach z bracketingu i HDR+, ale na gotowych zdjęciach (portfolio) nie rozjaśnia bardziej niż neutral.

Wszystkie parametry są w jednym pliku [config.yaml](config.yaml), z komentarzami po polsku. Kolejność (późniejsze
wygrywa): `config.yaml` → ustawienia wybranego presetu → własny plik `--config` → `--set klucz=wartość`.
Z własnego pliku liczą się tylko wartości **różne od domyślnych**: można skopiować cały `config.yaml`, zmienić kilka
liczb, a presety dalej działają. Własny plik może też zmienić same presety (sekcja `presets`). Przełączniki
`auto | off` akceptują też `false`. Najczęściej używane:

| Klucz | Znaczenie |
|---|---|
| `tonemap.target_key` / `target_white` / `black_target` | jasność średnich tonów, bieli i czerni (wartości sRGB) |
| `tonemap.compress_shadows` / `compress_highlights` | siła lokalnej kompresji (1 = brak) |
| `windows.exterior_target`, `windows.strength` | jasność widoku za oknem i siła jego pullu |
| `white_balance.target_cct`, `global_strength`, `mixed_light_strength` | docelowa temperatura bieli, siła korekty globalnej i lokalnej |
| `align.model` | model ruchu klatek: `auto` (domyślnie: afiniczny albo homografia per klatka), `translation`, `similarity`, `affine`, `homography` |
| `geometry.verticals`, `max_crop`, `min_k1` | korekcja pionów, maksymalny crop, próg korekcji dystorsji |
| `denoise.luma` / `chroma`, `sharpen.amount` | odszumianie i wyostrzanie |
| `export.sizes` | rozmiary wyjściowe (nazwa, dłuższy bok, jakość JPEG) |
| `runtime.workers`, `memory_limit_gb`, `device` | równoległość, budżet pamięci, GPU (`auto` / `gpu` / `cpu`) |
| `modules.*` | moduły opcjonalne i ich parametry |

**GPU:** przy `runtime.device: auto` ciężkie operacje OpenCV idą przez OpenCL (OpenCV T-API, `cv2.UMat`), jeśli
w systemie jest sterownik OpenCL dla dowolnej karty. Dotyczy to remapu geometrii, warpów merge, filtrów prowadzonych,
rozmyć i NLM. Bez OpenCL działa CPU. Ścieżka UMat jest testowana na zgodność wyników (`tests/test_accel.py`), ale
w środowisku, w którym powstał projekt, nie było GPU, więc **przyspieszenia na GPU nie zmierzyłem**.

## 6. Jakość: pomiary

<!-- METRICS:START -->
Wszystkie liczby w tej sekcji generuje `tools/update_readme_metrics.py` z plików w [reports/](reports/)
(4 rdzenie CPU, bez GPU, finalna konfiguracja). Dane testowe opisuje §7.

### 6.1 Kalibracja: przed i po (pełny pipeline, sceny syntetyczne z GT)

Ten sam kod, różnią się tylko parametry: przed = [config_before_full.yaml](reports/calibration/config_before_full.yaml),
po = `config.yaml`. Metryki oznaczone GT oraz odzyskiwalne przepalenia okna, halo i detal widoku to średnie
z 3 wnętrz z prawdą referencyjną; jasność widoku za oknem to średnia z 5 serii z oknami (dla serii bez GT
z maski okien pipeline'u), pozostałe z 6 serii. Pełna tabela per seria:
[reports/calibration/full_pipeline.md](reports/calibration/full_pipeline.md).

| Metryka (cel ze SPEC) | neutral przed → po | airy przed → po | premium przed → po |
|---|---|---|---|
| Neutralność ścian ΔE2000, GT (≤ 3.0) | 4.96 → **1.62** | 4.91 → **1.68** | 5.02 → **1.68** |
| Jasność ścian L*, GT (neutral 78–88, airy 84–92, premium 74–86) | 62.7 → **75.6** | 67.8 → **87.1** | 61.0 → **76.0** |
| Jasność widoku za oknem L* (55–80, premium 45–70) | 74.8 → 72.0 | 79.3 → 76.5 | 71.2 → 67.2 |
| Odzyskiwalne przepalenia okna, % (< 5) | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| Przepalenia poza źródłami światła, %, GT (< 0.5) | 0.03 → 0.02 | 0.02 → 0.02 | 0.04 → 0.02 |
| Zaczernienia, % (< 0.5) | 0.00 → 0.00 | 0.00 → 0.00 | 0.01 → 0.01 |
| Halo przy oknie ΔL* (< 4) | −0.7 → −0.9 | −0.9 → −0.4 | −0.8 → −0.5 |
| Pionowość, mediana [°] (≤ 0.5) | 0.09 → 0.10 | 0.09 → 0.09 | 0.08 → 0.12 |
| Detal widoku okna / GT (≥ 0.6) | 1.06 → 1.04 | 0.94 → 1.13 | 1.22 → 1.22 |
| Neutralność jasnych powierzchni ΔE (auto) | 4.43 → 3.13 | 4.30 → 3.08 | 4.45 → 3.20 |
| Mediana jasności | 0.57 → 0.67 | 0.62 → 0.81 | 0.55 → 0.67 |

Kalibracja poprawia cele ze SPEC: neutralność i jasność ścian. Funkcja celu (`neutral`):
8.78 → 4.77 (przebieg 2) → 2.99 (przebieg 3). Przebiegi: [reports/calibration/](reports/calibration/).

**Walidacja na danych nieużytych w kalibracji** (preset `neutral`, przed → po, kod z dnia kalibracji;
[validation.json](reports/calibration/validation.json)):

| Zbiór | Mediana jasności | ΔE jasnych powierzchni (auto) | Przepalenia poza nieodzyskiwalnymi, % |
|---|---|---|---|
| HDR+ (6 serii z prawdziwą treścią wnętrz) | 0.58 → 0.71 | 6.70 → 5.96 | 0.58 → 0.61 |
| OpenCV: Memorial Church (Debevec) i St. Louis (noc) | 0.43 → 0.50 | 7.16 → 7.41 | 1.38 → 2.00 |

Gotowe zdjęcia (tryb jednej klatki) sprawdza osobno test „nie psuć” (6.5).

### 6.2 Porównania przed i po dla każdego presetu

[reports/comparisons/README.md](reports/comparisons/README.md) zawiera 17 zestawień (klatka referencyjna | neutral | airy | premium)
i tabele metryk per seria. „Przed” to klatka referencyjna prosto z aparatu, „po” to wynik presetu. Średnie:

| Zbiór | Wersja | Mediana jasności | Przepalenia*, % | Zaczernienia, % | Neutralność ΔE (auto) | Pionowość [°] | Ściany L* (GT) | Widok L** |
|---|---|---|---|---|---|---|---|---|
| syntetyczne (6) | przed | 0.28 | 9.47 | 0.02 | 8.24 | 2.09 | — | — |
| syntetyczne (6) | neutral | 0.67 | 0.35 | 0.00 | 3.13 | 0.10 | 75.6 | 72.0 |
| syntetyczne (6) | airy | 0.81 | 0.32 | 0.00 | 3.08 | 0.09 | 87.1 | 76.5 |
| syntetyczne (6) | premium | 0.67 | 0.35 | 0.01 | 3.20 | 0.12 | 76.0 | 67.2 |
| HDR+ (6) | przed | 0.33 | 6.66 | 0.00 | 9.41 | 2.44 | — | — |
| HDR+ (6) | neutral | 0.71 | 0.54 | 0.00 | 6.01 | 1.63 | — | 77.4 |
| HDR+ (6) | airy | 0.84 | 0.53 | 0.00 | 5.19 | 1.59 | — | 81.7 |
| HDR+ (6) | premium | 0.71 | 0.60 | 0.01 | 6.08 | 1.68 | — | 74.0 |
| OpenCV (2) | przed | 0.30 | 8.78 | 0.00 | 12.64 | 3.51 | — | — |
| OpenCV (2) | neutral | 0.50 | 1.74 | 0.06 | 7.69 | 3.07 | — | 61.1 |
| OpenCV (2) | airy | 0.58 | 1.94 | 0.05 | 6.97 | 2.84 | — | 64.6 |
| OpenCV (2) | premium | 0.51 | 1.83 | 0.08 | 7.65 | 1.76 | — | 58.5 |
| portfolio (3) | przed | 0.68 | 0.07 | 0.03 | 4.51 | 0.25 | — | — |
| portfolio (3) | neutral | 0.69 | 0.11 | 0.24 | 3.19 | 0.15 | — | — |
| portfolio (3) | airy | 0.68 | 0.07 | 0.10 | 3.01 | 0.18 | — | — |
| portfolio (3) | premium | 0.70 | 0.15 | 0.33 | 3.37 | 0.15 | — | — |

\* Piksele ≥ 254/255 poza obszarami przepalonymi we wszystkich klatkach (łącznie z lampami i oknami).
W wierszu „przed” liczone są wszystkie, bo pojedyncza klatka nic nie wie o pozostałych.
\** Średnie L* widoku za oknem, bez pikseli przepalonych: z maski okien GT (labels_ideal.png), gdy scena
ma GT, w pozostałych przypadkach z maski okien pipeline'u.

Pionowość na zdjęciach bez architektonicznych pionów (portret, zbliżenie, kopuła z rybiego oka) nie oznacza
krzywych ścian (§9).

![syntetyczne](reports/comparisons/syntetyczne__IMG_0000.jpg)
![HDR+](reports/comparisons/hdrplus__HDRP_0000.jpg)

### 6.3 Etapy pipeline'u względem prawdy referencyjnej

Pomiary z [tools/verify_hypotheses.py](tools/verify_hypotheses.py) ([verification.json](reports/verification.json))
i [tools/eval_modules.py](tools/eval_modules.py) ([modules_eval.json](reports/modules_eval.json)). O ile wiersz
nie mówi inaczej, są to sceny syntetyczne 2400×1600; odszumianie mierzone jest na pojedynczych
RAW z HDR+, a IoU nieba na syntetycznym exteriorze 1200×800:

| Etap | Wynik |
|---|---|
| Grupowanie | 6/6 serii dokładnie z EXIF i 6/6 bez EXIF (same piksele). Uszkodzony plik trafia do `unreadable` |
| Wyrównanie | średni błąd siatki: statyw 0.29–0.45 px, z ręki 0.22–0.27 px przy przesunięciach 4–10 px |
| Merge: 3 klatki z N | mediana błędu log2 radiancji: wszystkie klatki 0.008–0.010, 3 skrajne 0.014–0.018, 3 środkowe 0.012–0.013 |
| Okna | odzyskiwalne przepalenia 0%, L* widoku 70.7–72.1, detal 0.99–1.13× GT, halo −3.3…0.7 L*. Okna przepalone już w najciemniejszej klatce (13% i 43% powierzchni okna) zostają białe |
| Geometria | k1 0.061 / 0.040 / 0.069 przy prawdzie 0.06 / 0.04 / 0.08; błąd korekty pochylenia 0.08–0.59°, przechyłu 0.01–0.07°; mediana odchylenia pionów po korekcie 0.04–0.14° |
| Aberracja chromatyczna | prawda: skala R +0.12%, B −0.12%. Resztka w rogu kadru: dane liniowe 0.33–0.65 px, JPEG 4:2:0 0.76–1.08 px (subsampling rozmywa przesunięcie kolorów już w pliku), pełny pipeline na seriach syntetycznych 0.42–1.11 px |
| Odszumianie | 6 zaszumionych pojedynczych RAW z HDR+: σ szumu niższe w 6/6, o 36–71% |
| Niebo | IoU 0.94 (syntetyczny exterior 1200×800); wykryte na 12/14 exteriorach HDR+ i na 2/104 wnętrzach portfolio (niebo za szybą, §9) |

### 6.4 Moduły opcjonalne

| Moduł | Pomiar |
|---|---|
| Usuwanie obiektów | 26 zdjęć portfolio (co n-te z katalogu, całe zdjęcie przeskalowane do 640 px dłuższego boku); eliptyczną dziurę (16% boku) wypełnia metoda, a wynik jest porównany z oryginałem (ΔE2000 w dziurze). Jednorodne tło: 3.38 (exemplar) vs 3.69 (Telea), exemplar lepszy w 19/26. Losowe miejsce: 7.99 vs 8.73, lepszy w 18/26. Moduł nadpisuje tylko maskę poszerzoną o 0.2% dłuższego boku (`modules.remove.dilate_frac`). Po całym pipeline poza pasem 25 px wokół maski < 0.1% pikseli różni się o > 3 kody (test) |
| Wymiana nieba | detekcja: patrz 6.3; zdjęcie nieba użytkownika jest komponowane w pełnej rozdzielczości (test) |
| Twilight | syntetyczny dom (8 okien i drzwi): zapalonych 9 obszarów, wszystkie na oknach albo drzwiach, nic na trawniku (test, D-45) |
| Trawa | trawnik zieleńszy, kolory poza trawnikiem bez zmian (test) |

### 6.5 Test „nie psuć” (tryb jednej klatki, gotowe zdjęcia z portfolio)

104 z 104 zdjęć bez błędu. Wynik względem wejścia:
- SSIM: mediana **0.977**, p10 0.962, minimum 0.880;
  poniżej 0.85: 0/104 zdjęć (najniższe: 07.CKUlc6zN (0.88), 09.6CkXdaHz (0.93), 11.CHtKxZT1 (0.94));
- ΔE2000: mediana **3.02**, średnia 3.19, p90 4.19;
- przepalenia poza nieodzyskiwalnymi średnio 0.10%, zaczernienia średnio 0.06% (maksimum 0.34%);
- pionowość: mediana 0.19°.

Cel SPEC: SSIM ≥ 0.85 i średnie ΔE ≤ 6. SSIM obniżają też zmiany zamierzone (prostowanie pionów, rozjaśnienie
ciemnych ujęć), więc niski wynik nie zawsze oznacza szkodę; przyczyny dla tego zbioru opisują D-49 i D-53. Plik:
[reports/portfolio_do_no_harm.json](reports/portfolio_do_no_harm.json).

### 6.6 Wydajność i pamięć

Maszyna: 4 rdzenie CPU, bez GPU (OpenCL niedostępny), 16 GB RAM. Jedna seria na jednym workerze.

| Seria | Czas | Szczyt RAM | Najdłuższe etapy |
|---|---|---|---|
| 3x24Mpx JPEG (6000×4000) | 83 s | 2.25 GB | wyrównanie 27 s, tone mapping 23 s, merge 12 s, geometria 7 s |
| 3x60Mpx JPEG (9504×6336) | 140 s | 2.78 GB | tone mapping 39 s, merge 33 s, wyrównanie 28 s, geometria 17 s |
| 3x60Mpx TIFF 16-bit (9504×6336) | 168 s | 3.24 GB | tone mapping 43 s, merge 34 s, wyrównanie 28 s, geometria 19 s |

Batch: 104 zdjęcia portfolio w trybie jednej klatki, 2 workery, 327 s.
Szczegóły: [reports/perf.json](reports/perf.json).

### 6.7 Kryteria akceptacji ze SPEC: podsumowanie

Ta tabela też powstaje z raportów. 35 kryteriów: niespełnione 3, spełnione częściowo 5, bez pomiaru 0. Kryteria jasności ścian i te z
dopiskiem „każda scena” są sprawdzane na każdej scenie z GT osobno (wynik to zakres scen), nie na średniej.
„Tak (test)” oznacza, że kryterium sprawdza test automatyczny, a cały zestaw testów przechodzi (§6.8).
Przyczyny braków opisuje §9 (pkt 4, 6, 9, 10 i 12).

| Kryterium | Cel (SPEC) | Wynik | Spełnione |
|---|---|---|---|
| Odporność batcha | błędny plik nie zatrzymuje batcha | uszkodzony plik, niepełna seria, brak EXIF, awaria workera (`tests/test_robustness.py`) | tak (test) |
| Grupowanie | 100% z EXIF i bez | 6/6 i 6/6 | tak |
| Ekspozycje względne (z EXIF) | ±0.1 EV od GT | maks. błąd 0.00 EV | tak |
| Ekspozycje względne (bez EXIF) | ±0.1 EV od GT | maks. błąd 0.02 EV | tak |
| Wyrównanie (serie GT) | ≤ 0.6 px statyw, ≤ 0.8 px z ręki | 0.29–0.45 px i 0.22–0.27 px (przesunięcia do 10 px) | tak |
| Wyrównanie: z ręki z perspektywą | ≤ 0.8 px przy przesunięciach do 20 px | średnio 0.56 px, najgorsza klatka 1.01 px (przesunięcia 18–19 px) | **nie** |
| Duchy | < 2% maski ducha odbiega o > 0.5 EV | 0.45% (bez deghostingu 14.6%) | tak |
| Przepalenia poza światłami | < 0.5% (każda scena) | 0.01–0.04% | tak |
| Zaczernienia | < 0.5% (każda scena) | 0.00–0.03% | tak |
| Halo okno/ściana | < 4 L* | maks. 3.3 L* | tak |
| Jasność ścian `neutral` | L* 78–88 | 69.5–79.1 (w paśmie 2/3 scen) | częściowo |
| Jasność ścian `airy` | L* 84–92 | 83.3–89.0 (w paśmie 2/3 scen) | częściowo |
| Jasność ścian `premium` | L* 74–86 | 69.4–79.6 (w paśmie 2/3 scen) | częściowo |
| Okna: odzyskiwalne przepalenia | < 5% | 0.0% | tak |
| Okna: L* widoku | 55–80 (premium 45–70) | neutral 70.7–72.8, airy 75.4–77.9, premium 65.4–69.0 | tak |
| Okna: detal | ≥ 0.6× GT | 0.99–1.31× | tak |
| Okna: IoU maski | ≥ 0.8 | min. 0.99 (szyby) | tak |
| Neutralność ścian | ΔE ≤ 3.0 (każda scena) | neutral 1.30–1.87, airy 1.47–1.85, premium 1.32–1.94 | tak |
| Neutralność w strefie żarówek | ΔE ≤ 5.0 | 1.96–3.21 (3/3 scen) | tak |
| Ściana akcentowa | ΔH < 10° | 5.5° (kolor o małym nasyceniu) | tak |
| Piony | mediana ≤ 0.5° | 0.02–0.21° | tak |
| Dystorsja | \|k1 − k1_GT\| ≤ 0.02 | maks. 0.011 | tak |
| Winieta | resztka w rogu ≤ 8% | płaskie sceny ≤ 8% (test); wnętrza syntetyczne: korekta odrzucana przez strażniki (D-44) | częściowo |
| Aberracja chromatyczna | ≤ 0.3 px na brzegu | liniowe 0.33–0.65 px, pipeline 0.42–1.11 px | **nie** |
| Szum | σ niższe niż w klatce | 6/6 RAW, o 36–71% | tak |
| Ostrość krawędzi* | ≥ 0.9× wejścia | min. 0.97× (energia gradientu 0.78–2.26×) | tak |
| Jedna klatka: przepalenia | spadają | 9.39 → 5.81% (spadek na 11/11) | tak |
| Jedna klatka: zaczernienia | spadają | 0.016 → 0.018% (spadek na 5/11; maks. po 0.09%) | **nie** |
| „Nie psuć” (portfolio) | SSIM ≥ 0.85, średnie ΔE ≤ 6 | SSIM mediana 0.977, 0/104 zdjęć poniżej 0.85; ΔE średnie 3.19 | tak |
| Maska nieba | IoU ≥ 0.85 | 0.94 | tak |
| Twilight | niebo w stylu, okna świecą, fasada ciemniejsza | `test_twilight_*` | tak (test) |
| Usuwanie obiektów | poza maską bez zmian (poza otoczką 8 px) | maska poszerzana o 0.2% dłuższego boku (5 px przy 2400 px, 12 px przy 6000 px), więc przy dużych zdjęciach otoczka przekracza 8 px; `test_retouch_does_not_move_the_rest_of_the_image`: poza pasem 25 px < 0.1% pikseli zmienionych o > 3/255 (bit-identyczności test nie sprawdza) | częściowo |
| Eksport | sRGB ICC, wymiary, EXIF | `test_exports_sizes_profile_exif`, `test_jpeg_has_srgb_icc_and_exif` | tak (test) |
| Czas 3×24 Mpx | ≤ 90 s (4 rdzenie) | 83 s | tak |
| Pamięć 3×60 Mpx | ≤ 6 GB na workera | 3.24 GB | tak |

\* SPEC mierzy ostrość energią gradientu na krawędziach. Ta miara rośnie i maleje z kontrastem, który
tone mapping celowo zmienia, więc o wyniku decyduje miara niezależna od kontrastu (stromość krawędzi względem
jej wysokości, czyli odwrotność szerokości krawędzi). Rozmycie o 1 px obniża ją do ok. 0.8–0.9×. Energię
gradientu na tych samych krawędziach podajemy w nawiasie.

### 6.8 Testy automatyczne

`./estatehdr.sh test`: **141 testów** w `tests/`. Ostatni pełny przebieg (`tools/refresh_reports.sh`): 141 passed in 114.55s (0:01:54). Pokrycie:
- wejście, EXIF, profile ICC, mapy cieniowania DNG, uszkodzone pliki;
- grupowanie; ekspozycje i krzywa odpowiedzi z EXIF i bez (TIFF bez tagów);
- wyrównanie względem GT i wybór modelu ruchu, merge i duchy;
- okna, WB (strefa żarówek, ściana akcentowa), tone mapping (kolejność jasności, czerń scen o małym
  kontraście), odszumianie (faktura a szum), CA, winieta, dystorsja, piony, tryb nocny;
- tryb jednej klatki (przepalenia, szum, biel i czerń gotowych zdjęć), moduły (usuwanie lokalne, niebo,
  twilight, trawa);
- batch: izolacja błędów i awarii workera, logi, kody wyjścia;
- eksport (ICC v2, EXIF, rozmiary), CLI, web UI, ścieżka GPU (UMat) zgodna z CPU.
<!-- METRICS:END -->

## 7. Kalibracja

Nie było par referencyjnych (zdjęcie wejściowe + wynik AutoHDR), więc parametry dostroiłem do mierzalnych celów
z opisu produktu (SPEC.md, REVERSE.md §5) na scenach syntetycznych z prawdą referencyjną:
- neutralność bieli;
- jasność ścian i widoku za oknem;
- przepalenia;
- halo;
- ΔE i SSIM do „idealnej edycji” jako regularyzator.

```bash
python tools/calibrate.py --input data/synthetic/input --synthetic-gt data/synthetic --preset neutral \
    --out reports/calibration/moj_przebieg
python tools/calibrate.py --input data/synthetic/input --synthetic-gt data/synthetic --preset airy \
    --params tonemap.target_key,tonemap.compress_shadows,tonemap.compress_highlights,windows.exterior_target \
    --bound tonemap.target_key=0.5:0.85 --out reports/calibration/moj_airy   # tylko parametry tonu, własne granice
python tools/calibrate.py --input SESJE --pairs WYNIKI_AUTOHDR --out reports/calibration/pary   # pary 1:1
python tools/compare_configs.py --input data/synthetic/input --synthetic-gt data/synthetic \
    --before reports/calibration/config_before_full.yaml --preset neutral,airy,premium \
    --out reports/calibration/full_pipeline.md                 # pełny pipeline przed / po kalibracji
```

Wynik trafia do `reports/calibration/`:
- `calibrated.yaml` (do użycia z `--config`; dla airy/premium wartości trafiają do sekcji `presets`);
- `calibration.md` (tabela przed/po) i `calibration.json` (przebieg).

Przebiegi: `calibration.md` (neutral, przebieg 2), `continuation/` (neutral, przebieg 3), `preset_airy/`,
`preset_premium/` (pierwszy przebieg, odrzucony, bo dał premium jaśniejszy od neutral) i
`preset_premium_bounded/` (przyjęty). Ocena jakości dowolnego folderu wyjściowego:
`python tools/evaluate.py WYJŚCIE [--synthetic-gt data/synthetic] [--pairs WYNIKI_AUTOHDR]`.
Liczy histogram, % przepaleń i zaczernień, pionowość linii (°), neutralność ścian (ΔE), jasność i detal okien,
halo, szum i ostrość, a przy parach także SSIM, MS-SSIM, gradient-SSIM, ΔE2000 i LPIPS (jeśli zainstalowany).

Dane testowe: `python tools/make_synthetic.py` (sceny z GT) i `python tools/fetch_public_data.py` (HDR+, OpenCV,
portfolio). Porównania presetów: `python tools/make_comparisons.py`. Weryfikacja hipotez z REVERSE.md:
`python tools/verify_hypotheses.py`.

## 8. Założenia

Pełna lista z uzasadnieniami jest w [DECISIONS.md](DECISIONS.md). Najważniejsze:
- Brak par referencyjnych, więc kalibracja jest prowadzona do opisów, GT syntetycznego i testu „nie psuć” na
  gotowych zdjęciach.
- Merge w liniowej radiancji ze wszystkich klatek zamiast uczonej fuzji 3 klatek. Bez danych treningowych jest to
  podejście mierzalne i jawne.
- Wynik `full` ma wymiary wejścia (jak w AutoHDR), a obok powstaje wersja MLS 2048 px.
- Bez modeli neuronowych. Wszystko jest algorytmiczne, więc licencje są czyste, a działanie offline.

## 9. Znane ograniczenia

Uczciwie, z pomiarami. Liczby są w §6 (tabela kryteriów: §6.7), a pełne dane w `reports/`.

1. **Bez modeli AI.** Wszystkie etapy są algorytmiczne. Tam, gdzie AutoHDR ma modele uczone na ponad 1 mln par,
   EstateHDR jest słabszy:
   - **Twilight** to deterministyczny relighting: niebo zmierzchu, przyciemnienie i ochłodzenie fasady, świecące
     szyby. Okna szuka tylko na elewacji, jako prostokątnych, oprawionych obszarów powyżej gruntu (D-45). Szyby
     odbijające niebo oraz okna z roletami lub zasłonami rozpoznaje tylko wtedy, gdy mają wyraźną ramę na czterech
     bokach. Okna z ażurowymi firankami odrzuca (ukośne krawędzie wzoru są traktowane jak napisy czy ornamenty).
     Nie dodaje nowych źródeł światła (latarni, oświetlenia ogrodu).
   - **Usuwanie obiektów wymaga maski** (pędzel w UI lub `<nazwa>.mask.png`); nie ma automatycznego wykrywania
     bałaganu. Inpainting exemplar-based wypełnia jednorodne powierzchnie i faktury lepiej niż Telea (§6.4), ale
     duże dziury na styku kilku struktur mogą przedłużyć linię albo krawędź tam, gdzie jej nie było.
   - **Wymiana nieba:** detekcja opiera się na regułach (rozrost od gładkich nasion u góry kadru, walidacja koloru
     i jasności). Nie wykrywa nieba o zachodzie z silnie teksturowanymi chmurami, a w prześwitach koron drzew
     zostają drobne jasne plamki starego nieba. We wnętrzach portfolio wykrywa niebo widoczne przez szklany dach
     albo okno u góry kadru; wymiana jest opcjonalna i wtedy podmienia także to niebo.
2. **Okna przepalone w najciemniejszej klatce** są renderowane jako czysta biel z miękką krawędzią. Tych danych nie
   da się odzyskać. AutoHDR według opisu (E07) też zostawia wtedy biel i nie generuje widoku.
3. **Balans bieli:**
   - lokalne pole mieszanego światła bierze za biel powierzchnie o kolorze bliskim barwie światła: drewnianą
     podłogę w świetle lampy (wychodzi bledsza) i duże terakotowe lub pastelowe płaszczyzny przy świetle ok. 4000 K
     (D-51). Kolorem samym w sobie nie da się ich odróżnić od dominanty;
   - bardzo silne dominanty (np. 3000 K przy WB „dzień”) są korygowane globalnie tylko częściowo. Miękki limit chroni
     wnętrza pełne drewna przed zsinieniem;
   - na prawdziwych zdjęciach HDR+ neutralność jasnych powierzchni ma ΔE ok. 6, wyraźnie gorzej niż na scenach
     syntetycznych (§6.2). Część to prawdziwe kolorowe powierzchnie, które ta miara też liczy;
   - stare zdjęcia o nieznanej krzywej odpowiedzi (OpenCV Memorial Church, skany filmu) wychodzą wyprane i
     różowawe: krzywa filmu jest spoza modelu, a lokalny WB bierze ciepłe drewno całego wnętrza za kolor światła
     (§6.2, `reports/comparisons/opencv__memorial_0.jpg`).
4. **Tryb jednej klatki (pseudo-HDR)** nie ma informacji spoza zakresu jednego zdjęcia. Przepalone okna zostają
   białe, a szum cieni ograniczamy, więc cienie są podnoszone ostrożniej. Gotowe, wywołane zdjęcia są świadomie
   „oszczędzane” (D-47–D-49, D-53):
   - zostaje ich czerń, biel i większość klucza tonalnego;
   - szum jest mierzony tylko na gładkich fragmentach, więc faktura nie jest rozmywana;
   - WB poprawia wyraźną dominantę, ale nie wybiela kolorowych materiałów;
   - bez automatycznej korekcji dystorsji;
   - czerń autora zostaje (D-48), więc najciemniejsze piksele nie są podnoszone: odsetek zaczernionych pikseli
     nie spada, tylko lekko rośnie (średnio 0.016 → 0.018%, spadek tylko na 5 z 11 zdjęć, maks. 0.09%; §6.7).
     Cel SPEC „zaczernienia spadają” nie jest spełniony.

   Ciemne, nastrojowe ujęcia są rozjaśniane umiarkowanie (najwyżej do klucza 0.45). Szum gotowego JPEG-a, który
   kompresja już wygładziła, bywa brany za fakturę i zostaje (D-53). Bardzo zaszumione pojedyncze RAW (np. HDR+
   „kościół”, „schody”) zachowują po odszumianiu drobne kropki w cieniach (D-39).
5. **GPU** działa przez OpenCL (OpenCV T-API) tylko dla części operacji. Ścieżka jest testowana na zgodność wyników
   na CPU, ale przyspieszenia na prawdziwym GPU nie zmierzyłem (brak GPU w środowisku).
6. **Kalibracja bez par.** Nie było par „wejście → wynik AutoHDR”, więc presety są dostrojone do celów ze SPEC
   (opis wyglądu AutoHDR) na scenach syntetycznych z GT i sprawdzone na danych odłożonych (HDR+, OpenCV, portfolio).
   Nie są dopasowane 1:1 do AutoHDR. Jasność ścian mieści się w paśmie SPEC w 2 z 3 scen każdego presetu. W
   ciemnej sypialni jest o 1–9 L* poniżej dolnej granicy, bo klucz tonalny jest celowo ograniczony: w kalibracji
   `neutral` granica `target_key` ≤ 0.70 była aktywna i świadomie jej nie poszerzałem (D-32), a `premium` nie może
   być jaśniejszy od `neutral` (klucz ≤ 0.70, D-37). `tools/calibrate.py --pairs` jest gotowe na pary.
7. **LPIPS** nie jest liczony (brak `torch` i wag o jasnej licencji). Raport podaje SSIM, MS-SSIM, gradient-SSIM
   i ΔE2000.
8. **Wydajność** (4 rdzenie CPU, bez GPU) jest w §6.6. Wolniej niż usługa w chmurze, ale lokalnie i równolegle dla
   wielu serii.
9. **RAW i obiektyw:**
   - odczyt przez LibRaw (rawpy) obejmuje praktycznie wszystkie aparaty, ale bez bazy profili obiektywów;
   - mapy cieniowania zapisane w DNG (GainMap, np. z telefonów) są stosowane (D-43);
   - dystorsja, winieta i CA są poza tym szacowane z obrazu;
   - winieta jest korygowana automatycznie tylko wtedy, gdy gradienty radialne są spójne we wszystkich sektorach
     (D-44). We wnętrzach światło okien i lamp blisko środka kadru wygląda jak winieta, więc tam korekta zwykle się
     nie włącza (ręcznie: `lens.vignetting: 0.3`);
   - w części serii HDR+ (telefon) winieta zostaje.
10. **Aberracja chromatyczna:** korekta usuwa większość bocznej CA na danych liniowych, mniej w JPEG-ach z
    subsamplingiem 4:2:0 (przesunięcie kolorów jest rozmyte już w pliku). Resztka 0.3–1.1 px na brzegu, więc cel
    SPEC ≤ 0.3 px nie jest spełniony (§6.3).
11. **Miara pionowości** w raportach liczy odchylenie wszystkich długich, prawie pionowych linii. Na zdjęciach bez
    architektonicznych pionów (portret, zbliżenie lunety, kopuła z rybiego oka, schody) mediana wynosi kilka stopni
    i nie oznacza krzywych ścian. Na wnętrzach z GT wynosi ok. 0.04–0.2° (§6.7).
12. **Wyrównanie przy perspektywie:** model ruchu wybierany per klatka (D-52) obniża błąd przy obrocie aparatu z
    ręki, ale kryterium SPEC ≤ 0.8 px (§6.7) nie jest spełnione dla 2 z 6 klatek. Klatka prześwietlona w ok. 80% ma
    za mało dopasowań, by rozstrzygnąć model: zostaje afiniczna i ma błąd ok. 1 px. Druga klatka (sypialnia, TIFF)
    po wyborze homografii ma 0.84 px, czyli nieco powyżej celu, także przy wymuszonej homografii. Typowy bracketing
    ze statywu albo z ręki bez dużego obrotu tego nie dotyczy.
13. **Ekspozycje bez EXIF** są szacowane z pikseli razem z krzywą odpowiedzi (D-50). Wykładnika krzywej nie da się
    jednak z samych pikseli odróżnić od stosunków ekspozycji, więc przyjmowany jest jak w sRGB. Aparat o innej
    gamma i bez EXIF dostanie ekspozycje przeskalowane o ten czynnik. Odpowiedzi spoza modelu (film, skaner) wracają
    do zwykłego sRGB. 16-bitowe TIFF-y bez tagów i profilu z czystą krzywą potęgową (Adobe RGB, ProPhoto) są
    dekodowane jak sRGB, z błędem ekspozycji ok. 0.2–0.3 EV na bracket −2/0/+2. Liniowy TIFF bez niedoeksponowanej
    klatki (np. 0/+2) jest czytany jako sRGB (D-50).

## 10. Następne kroki (największy zysk)

1. **Pary „wejście → wynik AutoHDR”.** Nawet 50–100 sesji pozwoli skalibrować presety 1:1:
   `tools/calibrate.py --pairs` jest gotowe i liczy ΔE2000, SSIM, MS-SSIM, a z LPIPS, jeśli jest zainstalowany.
   Dziś kalibracja opiera się na opisach i scenach syntetycznych (D-32). Możliwe źródło to publiczny zbiór konkursu
   grupowania AutoHDR, ale wyłącznie po potwierdzeniu licencji i za zgodą właściciela projektu (D-18).
2. **Modele uczone na licencjach komercyjnych** (MIT/Apache, z wagami o jasnym pochodzeniu):
   - segmentacja nieba i okien zamiast reguł (twilight, wymiana nieba, okna z firankami);
   - rozpoznawanie materiałów (drewno, terakota, pastele), żeby lokalny balans bieli nie brał ich koloru za kolor
     światła (D-51);
   - odszumianie pojedynczych RAW, które jest dziś najsłabszym punktem trybu jednej klatki.
3. **Profile obiektywów** dla dystorsji, winiety i CA. Estymacja z obrazu jest ostrożna (winieta we wnętrzach jest
   świadomie pomijana, D-44). Warunek: baza o licencji pozwalającej na użycie komercyjne albo własna kalibracja
   z płaskiego kadru, gdzie estymator jest dokładny.
4. **Pomiar na GPU.** Ścieżka OpenCL jest zgodna z CPU (testy), ale przyspieszenia nie zmierzyłem (brak GPU).
