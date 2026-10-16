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

Batch nigdy się nie zatrzymuje na pojedynczym problemie:
- uszkodzony plik trafia do `unreadable` i nie jest dołączany do serii (z serii odpada tylko nieczytelna klatka);
- niepełna seria albo brak EXIF dają ostrzeżenie tej serii;
- awaria procesu roboczego (np. brak pamięci) dotyczy tylko serii, która ją wywołała. Pozostałe serie są
  przeliczane ponownie, pojedynczo.

Kody wyjścia: 0 – wszystko w porządku; 1 – w folderze nie ma obsługiwanych zdjęć; 2 – nie ma takiego folderu albo
któraś seria się nie udała.

Fotografowanie RAW+JPEG: pliki o tej samej nazwie w jednym folderze (`IMG_1.CR2` + `IMG_1.JPG`) to jedna klatka,
używany jest RAW. Serie o tej samej nazwie (np. `IMG_0001` w dwóch podfolderach) dostają przyrostek `_2`, `_3`,
więc wyniki się nie nadpisują. Folder wyjściowy wewnątrz sesji jest pomijany przy ponownym uruchomieniu.
Zdjęcia z profilem ICC innym niż sRGB (Adobe RGB, ProPhoto, Display P3) są konwertowane do sRGB (LittleCMS),
z ostrzeżeniem w raporcie.

## 3. Interfejs webowy

`./estatehdr.sh web` uruchamia serwer pod `http://127.0.0.1:8765` (tylko lokalnie). Zadania są w `work/jobs/`.
1. **Zdjęcia:** przeciągnij folder (rekurencyjnie) lub wybierz pliki, z paskiem postępu wysyłania.
2. **Serie:** automatyczne grupowanie z miniaturami i EV. Ręczna korekta: przenieś klatkę do innej lub nowej
   serii, połącz albo rozdziel serie, zmień nazwę. Przycisk „Maska usuwania” otwiera pędzel na klatce
   referencyjnej.
3. **Ustawienia:** preset (neutral / airy / premium), piony, okna, niebo, zmierzch, trawa, usuwanie obiektów,
   rozmiar MLS.
4. **Kolejka i wyniki:** postęp każdej serii z nazwą etapu, suwak przed/po, pobieranie pojedynczych plików
   oraz ZIP (MLS / pełne / wszystko). Zadania przetrwają restart serwera.

Zrzuty: [reports/ui/](reports/ui/).

## 4. Jak to działa (pipeline)

| Etap | Moduł | Co robi |
|---|---|---|
| Grupowanie | `grouping.py` | Reguły per para klatek: aparat, rozmiar, ogniskowa, odstęp czasu, powtórzona ekspozycja z EXIF. Bez EXIF: skok jasności ≥ 0.4 EV i podobieństwo kadru. Ręczna korekta przez `groups.json` lub UI |
| Linearyzacja | `series.py`, `io/` | RAW (LibRaw, DHT/FBDD), TIFF16 (liniowy vs sRGB rozstrzygany zgodnością z EXIF), JPEG (dopasowanie krzywej odpowiedzi kamery). Ekspozycje z EXIF, weryfikowane pikselami |
| Wyrównanie | `align.py` | SIFT + RANSAC, ECC, dokładny etap ECC w wyższej rozdzielczości, walidacja względem identyczności |
| Merge HDR | `merge.py` | Radiancja liniowa ze wszystkich klatek (wagi SNR), wykrywanie duchów względem klatki referencyjnej, neutralizacja kolorowej czerni RAW. Praca w pasach |
| Obiektyw | `lens.py` | Aberracja chromatyczna (skala radialna R/B), winieta (tylko przy spójnym profilu albo ręcznie) |
| Scena nocna | `pipeline.py` | Wykrywa nocny exterior (ciemne, gładkie niebo u góry kadru) i wtedy: bez window pull, niski klucz tonalny, noc zostaje nocą |
| Okna | `windows.py` | Fizyczna detekcja obszarów poza zakresem wnętrza i klasyfikacja (okno / lampa / plama słońca / niebo) |
| Balans bieli | `color.py` | Globalny (szare kandydatury → locus Plancka, cel 6000 K) + lokalne pole mieszanego światła + osobna korekta widoków |
| Tonemapping | `tonemap.py` | Lokalna kompresja (filtr prowadzony, bez halo), window pull rozwiązywany na krzywej, globalna krzywa PCHIP zakotwiczona na percentylach wnętrza, kolor z zachowaniem nasycenia, miękkie wygaszanie świateł |
| Odszumianie | `denoise.py` | Estymacja szumu (Immerkaer), filtr prowadzony luminancji i chrominancji, NLM dla silnego szumu |
| Moduły | `modules/` | Niebo, zmierzch, usuwanie obiektów (exemplar-based) i trawa, przed geometrią |
| Geometria | `geometry.py` | Dystorsja metodą plumb-line, piony z punktu zbiegu (LSD + RANSAC), obrót kamery, crop ≤ 15%, powrót do wymiarów wejścia |
| Eksport | `export.py`, `io/writer.py` | Wyostrzanie z progiem szumu, dithering, sRGB ICC, EXIF z klatki referencyjnej, rozmiary |

Wymagający obliczeniowo kod pełnej rozdzielczości działa w pasach wierszy. Batch używa puli procesów, a liczba
workerów wynika z budżetu RAM.

## 5. Presety i parametry

| Preset | Charakter | Najważniejsze różnice (wartości po kalibracji, D-32) |
|---|---|---|
| `neutral` (domyślny) | naturalny, jasny wygląd do ogłoszeń (MLS) | klucz tonalny 0.70, kompresja cieni 0.64, widok za oknem ≈ 0.6, biel neutralna przy mieszanym świetle |
| `airy` | jasny, lekki (high-key) | klucz 0.85, łagodniejsza kompresja lokalna (0.78), jaśniejszy widok za oknem, mniej kontrastu i nasycenia |
| `premium` | „magazynowy” | ten sam klucz co neutral, ale słabiej podniesione cienie (0.86), więcej kontrastu, wibracji i detalu, ciemniejszy nasycony widok za oknem |

Presety są skalibrowane każdy do swojego pasma jasności ścian ze SPEC (neutral L* 78–88, airy 84–92, premium
74–86), z ograniczeniem kolejności: premium nie jest jaśniejszy od neutral, a neutral od airy.

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

<!--METRICS-->

## 7. Kalibracja

Nie było par referencyjnych (zdjęcie wejściowe + wynik AutoHDR), więc parametry dostroiłem do mierzalnych celów
z opisu produktu (SPEC.md, REVERSE.md §5) na scenach syntetycznych z prawdą referencyjną:
- neutralność bieli;
- jasność ścian i widoku za oknem;
- przepalenia;
- halo;
- ΔE i SSIM do „idealnej edycji” jako regularyzator.

```bash
python tools/calibrate.py --input data/synthetic/input --synthetic-gt data/synthetic --preset neutral
python tools/calibrate.py --input data/synthetic/input --synthetic-gt data/synthetic --preset airy \
    --params tonemap.target_key,tonemap.compress_shadows,tonemap.compress_highlights,windows.exterior_target \
    --bound tonemap.target_key=0.5:0.85                          # preset: tylko parametry tonu, własne granice
python tools/calibrate.py --input SESJE --pairs WYNIKI_AUTOHDR      # gdy będą pary: 1:1 (ΔE2000, SSIM, LPIPS)
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

Uczciwie, z pomiarami (szczegóły w `reports/`):

1. **Bez modeli AI.** Wszystkie etapy są algorytmiczne. Tam, gdzie AutoHDR ma modele uczone na ponad 1 mln par,
   EstateHDR jest słabszy:
   - **Twilight** to deterministyczny relighting: niebo zmierzchu, przyciemnienie i ochłodzenie fasady, świecące
     szyby. Wygląda wiarygodnie na prostych fasadach. Okna wykrywa jednak jako ciemne prostokąty, więc czasem
     „zapala” ciemny cień (np. pod schodami) albo pomija okno odbijające niebo. Nie generuje nowych źródeł światła
     (latarnie, oświetlenie ogrodu).
   - **Usuwanie obiektów wymaga maski** (pędzel w UI lub `<nazwa>.mask.png`); nie ma automatycznego wykrywania
     bałaganu. Inpainting exemplar-based dobrze wypełnia jednorodne powierzchnie i faktury (ściana, podłoga,
     trawa, liście): ΔE 1.12 do oryginału przy dziurach na jednorodnym tle, wobec 1.43 dla Telea. Duże dziury na
     styku kilku struktur mogą jednak przedłużyć linię albo krawędź tam, gdzie nie powinna być (np. fuga deski o
     jedną deskę za daleko).
   - **Wymiana nieba:** detekcja opiera się na regułach (rozrost od gładkich nasion u góry kadru i walidacja
     kolor/jasność). Na 14 exteriorach z HDR+ niebo wykryte w 12. Nie wykrywa nieba na zachodzie słońca z silnie
     teksturowanymi chmurami. Chmury o mocnej teksturze, które leżą tuż nad dachem, mogą zostać w obrazie obok nowego
     nieba. W prześwitach koron drzew zdarzają się drobne jasne plamki starego nieba. Na 104 wnętrzach jedna
     fałszywa detekcja (prześwietlone okno u góry kadru).
2. **Okna przepalone w najciemniejszej klatce** są renderowane jako czysta biel z miękką krawędzią. Danych nie
   da się odzyskać (pomiar: przepalone w wyniku = przepalone w ciemnej klatce, a odzyskiwalne przepalenia 0%).
   AutoHDR w takiej sytuacji może „dorysować” widok, my nie.
3. **Balans bieli:**
   - bardzo silne dominanty (np. 3000 K przy WB „dzień”) są korygowane tylko częściowo, przez celowy miękki limit,
     który chroni wnętrza pełne drewna przed zsinieniem. Od ok. 4000 K korekta jest pełna;
   - neutralność ścian w scenach mieszanego światła (żarówki + okno): ΔE ok. 3–4 przy celu SPEC ≤ 3 (≤ 5 w strefie
     żarówek jest spełnione).
4. **Tryb jednej klatki (pseudo-HDR)** nie ma informacji spoza zakresu jednego zdjęcia. Przepalone okna zostają
   białe, a szum cieni ograniczamy, więc cienie są podnoszone ostrożniej. Dla już wywołanych JPEG-ów pipeline
   świadomie „nie przerabia” zdjęcia: na 104 gotowych zdjęciach portfolio SSIM ma medianę 0.96, a ΔE ok. 4.
5. **GPU** działa przez OpenCL (OpenCV T-API) tylko dla części operacji. Ścieżka jest testowana na zgodność
   wyników na CPU, ale przyspieszenie na prawdziwym GPU nie zostało zmierzone (brak GPU w środowisku).
6. **Kalibracja bez par.** Nie było par „wejście → wynik AutoHDR”, więc presety są dostrojone do opisów produktu
   i do „idealnej edycji” scen syntetycznych, a nie 1:1 do AutoHDR. `tools/calibrate.py --pairs` jest gotowe na pary.
7. **LPIPS** nie jest liczony (brak `torch` i wag o jasnej licencji). Raport podaje SSIM, MS-SSIM, gradient-SSIM
   (zgodność krawędzi) i ΔE2000.
8. **Wydajność** (4 rdzenie CPU, bez GPU): seria 3×24 Mpx ok. 80 s, 3×60 Mpx ok. 130 s; szczyt pamięci
   2.4 GB i 2.9 GB. Wolniej niż usługa w chmurze, ale lokalnie i równolegle dla wielu serii.
9. **RAW**: odczyt przez LibRaw (rawpy) obejmuje praktycznie wszystkie aparaty, ale bez profili obiektywów
   (korekcja dystorsji, winiety i CA jest estymowana z obrazu, a winieta automatycznie tylko przy spójnym
   profilu).

