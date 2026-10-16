# LICENSES.md — licencje bibliotek, wag i danych

Wymóg zadania: wyłącznie biblioteki i wagi z licencjami pozwalającymi na użycie komercyjne
(MIT, Apache, BSD i podobne). Stan został odczytany z metadanych zainstalowanych pakietów
(`importlib.metadata`) oraz plików licencji dołączonych do kół (*wheels*), 2026-10-16.

**Modele i wagi:** EstateHDR **nie używa żadnych wag sieci neuronowych**. Wszystkie etapy są
algorytmiczne: merge HDR, tonemapping, okna, balans bieli, geometria, odszumianie, niebo, twilight i
inpainting. Nie ma niczego do licencjonowania w tym zakresie.

## Zależności uruchomieniowe (`requirements.txt`)

| Pakiet | Wersja testowana | Licencja | Do czego |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause (+ 0BSD, MIT, Zlib, CC0 dla części dołączonych) | obliczenia |
| scipy | 1.18.1 | BSD-3-Clause | interpolacja PCHIP krzywej tonalnej |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 | przetwarzanie obrazu, SIFT, ECC, LSD, inpainting Telea |
| Pillow | 12.3.0 | MIT-CMU (HPND) | zapis JPEG z ICC i EXIF, profil sRGB (LittleCMS) |
| rawpy | 0.27.1 | MIT | odczyt RAW (dołączony LibRaw - patrz niżej) |
| tifffile | 2026.10.15 | BSD-3-Clause | TIFF 16-bit |
| piexif | 1.1.3 | MIT | budowa EXIF wyniku |
| ExifRead | 3.5.1 | BSD-3-Clause | odczyt EXIF (także RAW) |
| PyYAML | 6.0.3 | MIT | config.yaml |
| psutil | 7.2.2 | BSD-3-Clause | budżet pamięci dla workerów |
| fastapi | 0.143.2 | MIT | serwer web UI |
| starlette (zależność fastapi) | 1.8.0 | BSD-3-Clause | |
| pydantic, pydantic_core, annotated-types, typing-inspection | 2.14 / 2.50 / 0.8 / 0.4 | MIT | |
| anyio, h11, annotated-doc | 4.15 / 0.16 / 0.0.5 | MIT | |
| uvicorn | 0.54.0 | BSD-3-Clause | serwer HTTP |
| click, websockets, python-dotenv | — | BSD-3-Clause | zależności uvicorn |
| httptools, uvloop, watchfiles | — | MIT (uvloop: MIT/Apache-2.0) | zależności uvicorn[standard], jeśli zainstalowane |
| python-multipart | 0.0.32 | Apache-2.0 | upload plików |
| typing_extensions | 4.16.0 | PSF-2.0 | |
| idna | 3.20 | BSD-3-Clause | |
| certifi | 2026.7.22 | MPL-2.0 (dane certyfikatów, plik niemodyfikowany) | zależność httpx |

**Testy:** pytest 9.1.1 (MIT), pluggy (MIT), iniconfig (MIT), packaging (Apache-2.0 / BSD-2), Pygments (BSD-2),
httpx 0.28.1 (BSD-3), httpcore (BSD-3).

**Narzędzie użyte tylko przeze mnie do testów UI, nie jest zależnością projektu:** Playwright (Apache-2.0) z
przeglądarką Chromium (BSD) preinstalowaną w środowisku.

### Biblioteki natywne dołączone do kół (linkowane dynamicznie)

| Koło | Biblioteka | Licencja | Uwagi o użyciu komercyjnym |
|---|---|---|---|
| opencv-python-headless | OpenCV | Apache-2.0 | bez ograniczeń |
| opencv-python-headless | FFmpeg (libavcodec, libavformat, libavutil, libswscale, libswresample) | LGPL-2.1+ | używane tylko przez wideo-I/O OpenCV (EstateHDR z niego nie korzysta). Biblioteki dzielone (`.so`), więc LGPL pozwala na użycie komercyjne przy dołączeniu licencji i możliwości podmiany bibliotek |
| opencv-python-headless | libvpx, libaom, libavif, libpng, libjpeg, OpenBLAS, OpenSSL 1.1 | BSD / BSD-2 / libpng / IJG / BSD-3 / OpenSSL | permisywne |
| rawpy | LibRaw | LGPL-2.1 **lub** CDDL-1.0 (podwójna licencja LibRaw; koło zawiera tekst LGPL-2.1) | biblioteka dzielona, więc wolno jej używać komercyjnie (LGPL, dynamiczne linkowanie) |
| rawpy | lcms2, libjpeg, JasPer, libgomp | MIT / IJG / JasPer 2.0 / GPL-3 z GCC Runtime Library Exception | permisywne (wyjątek GCC pozwala na użycie w dowolnym programie) |

Pełne teksty: `site-packages/opencv_python_headless-*.dist-info/LICENSE-3RD-PARTY.txt`,
`site-packages/rawpy-*.dist-info/licenses/LICENSE.LibRaw`.

### Opcjonalne (niezainstalowane, wyłączone domyślnie)

| Pakiet | Licencja | Uwagi |
|---|---|---|
| torch + lpips (metryka LPIPS w `tools/evaluate.py`) | BSD-3 / BSD-2 | Wagi AlexNet z torchvision pochodzą z ImageNet o niejasnym statusie komercyjnym. Dlatego LPIPS nie jest instalowany (D-16), a raport pokazuje SSIM i ΔE2000, a w polu LPIPS `—`. |

### Zainstalowane w środowisku deweloperskim, ale nieużywane przez kod

scikit-image (BSD-3), onnxruntime (MIT), imageio (BSD-2), networkx (BSD-3), protobuf (BSD-3), flatbuffers
(Apache-2.0), opentelemetry-api (Apache-2.0) zostały po wcześniejszych próbach. Nie ma ich w
`requirements.txt` i kod ich nie importuje.

## Algorytmy z literatury (zaimplementowane od zera)

Wszystkie poniższe metody zostały zaimplementowane we własnym kodzie (MIT-zgodne użycie idei z publikacji, bez
kopiowania kodu): filtr prowadzony (He i in. 2010/2015), estymator szumu Immerkaera (1996), granica/niebo
inspirowane Shen i Wang (2013, zastąpione rozrostem regionu), inpainting Criminisi i in. (2004), korekcja
dystorsji metodą plumb-line, punkt zbiegu z LSD + RANSAC, CIEDE2000, SSIM (Wang i in. 2004).

## Dane testowe (nie są dystrybuowane z kodem; katalog `data/` jest w `.gitignore`)

| Zbiór | Licencja | Użycie |
|---|---|---|
| Sceny syntetyczne (`estatehdr/synthetic.py`) | własne (MIT, jak kod) | testy z prawdą referencyjną |
| Google HDR+ Burst Photography Dataset (RAW `merged.dng`, galeria `final.jpg`) | CC-BY-SA 4.0 | testy na realnych wnętrzach i exteriorach (sky / twilight); tylko lokalnie |
| OpenCV `opencv_extra/testdata/cv/hdr`: St. Louis Arch (Wikimedia, CC-BY-SA) i Memorial Church (P. Debevec, dane badawcze z publikacji Debevec i Malik 1997) | CC-BY-SA / dane badawcze | testy realnych serii bracketingowych; tylko lokalnie, bez redystrybucji |
| Galeria HDR+ (14 zdjęć budynków z niebem, `data/public/exteriors`) | CC-BY-SA 4.0 | testy wymiany nieba i zmierzchu; tylko lokalnie |
| Portfolio użytkownika (zdjęcia z tego repozytorium `piotrbugaj-tech.github.io`) | dane użytkownika | test „nie psuć gotowego zdjęcia” (tryb jednej klatki) |

Raporty w `reports/` zawierają tylko małe podglądy wyników (skalowane, do dokumentacji jakości).
Podglądy z HDR+ (CC-BY-SA 4.0) wymagają przy publikacji podania źródła (Google HDR+ dataset) i tej samej licencji.
