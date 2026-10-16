# REVERSE.md — analiza black-box AutoHDR (autohdr.com)

Dokument jest wynikiem fazy 0. Analizę prowadziłem metodą skilla **reverse-engineer-anything**
(REA, repozytorium `morluto/rea`, wersja skilla 42, licencja MIT). Skill pobrałem z GitHuba,
zainstalowałem w `~/.claude/skills/reverse-engineer-anything/` i przeczytałem w całości: `SKILL.md`
oraz wszystkie sześć referencji (`evidence-workflows.md`, `runtime-observation.md`,
`connection-and-recovery.md`, `javascript-applications.md`, `android-applications.md`,
`native-and-artifacts.md`).

Na końcu dokumentu jest sekcja **Weryfikacja hipotez**. Wpisuję tam wyniki eksperymentów na
naszych danych z prawdą referencyjną (fazy 3–7).

---

## 1. Jak zastosowałem skill (które etapy i co z nich wynikło)

| Etap skilla | Co zrobiłem | Wynik |
|---|---|---|
| **Connect only when needed** | Skill nie rejestruje sam serwera MCP REA. Narzędzi REA nie było w sesji. Zgodnie z `connection-and-recovery.md` zdiagnozowałem blokadę i nie zmieniałem konfiguracji klienta. | Serwera MCP nie rejestrowałem. Wszystkie trasy narzędziowe REA, które pasowałyby do celu (patrz niżej), są poza granicami zadania albo zablokowane przez sieć. Zgodnie z zasadą „Do not substitute another target” nie podstawiłem innego celu. |
| **Route the target first** | Cel to usługa webowa (SaaS). Nie ma tu binarki, APK ani ASAR. Trasy REA dla takiego celu to `capture_browser_scenario` / `list_browser_targets` (obserwacja strony), `analyze_javascript_application` (bundle JS) i `inspect_web_network_capture` (HAR). | Analiza bundla JS i ruchu sieciowego aplikacji to analiza kodu i nieudokumentowanych endpointów, czyli coś, czego zadanie zabrania. Obserwacja publicznych stron była dozwolona, ale proxy kontenera zwraca 403 dla autohdr.com. Zastąpiłem to **analizą black-box materiałów publicznych** (FAQ, baza wiedzy, blog, cennik, publiczne repozytoria hackathonów AutoHDR, recenzje). |
| **Plan broader investigations: krok 1** | Zamieniłem zadanie na listę 18 pytań (Q1–Q18) i dla każdego określiłem, jakiego dowodu wymaga. | Lista jest w sekcji 3. |
| **Krok 2** (stan i wcześniejsze dowody) | Przejrzałem katalog roboczy: repo strony piotrbugaj.com zawiera wyłącznie gotowe zdjęcia portfolio (webp/avif). | **Nie ma par referencyjnych** (serie + wyniki AutoHDR). Kalibracja 1:1 nie jest możliwa (patrz DECISIONS.md, D-03). |
| **Krok 3** (najmniejszy przegląd najpierw) | Najpierw strona produktu i FAQ, potem szczegóły ustawień, integracji i literatury. | — |
| **Krok 4** (zasoby i konfiguracja obok kodu) | Odpowiednikiem konfiguracji są publicznie opisane ustawienia: Style Settings oraz przykładowa konfiguracja AutoHDR w przewodniku Spiro. | Pełna lista nazw parametrów jest w sekcji 4. |
| **Krok 5** (potwierdzaj dowodem właściwego typu) | Każde twierdzenie ma typ: `vendor` (AutoHDR), `third-party`, `literature` albo `inference`. Twierdzenia o jakości obrazu weryfikuję **pomiarem na naszych danych** (sekcja 7), nie deklaracją. | — |
| **Krok 6** (niezależne pytania → równoległe workery) | 8 równoległych agentów z rozłącznymi zakresami (produkt, help center, ustawienia, blog/prasa, recenzje, integracje, techniki, przykłady), potem krytyk kompletności (wzorzec „completeness critic”), potem synteza ledgera. | Ok. 280 ustaleń. Ledger jest w sekcjach 4–6. |
| **Krok 7** (ledger ustaleń) | Każde ustalenie ma ID dowodu (E-xx), typ, pewność, granicę wyszukiwania i niewiadome. | Sekcje 4 i 8. |
| **Every conclusion: observation / inference / unknown** | Ledger rozdziela te trzy kategorie. Nie twierdzę, że analiza statyczna „zaobserwowała” wykonanie. | — |
| **evidence-workflows: `record_unknown`** | Każdą niewiadomą zapisuję razem z tym, czego potrzeba do jej rozstrzygnięcia (np. pary referencyjne użytkownika). | Sekcja 8. |
| **evidence-workflows: `verify_reconstruction`** („pass covers only declared comparable claims”) | Rekonstrukcję weryfikuję na skończonej, jawnej liście twierdzeń (SPEC.md → testy). Nie twierdzę, że jest globalnie równoważna z AutoHDR. | Sekcja 7 i testy w `tests/`. |
| **Before finishing: revisit the checklist** | Każde pytanie ma status answered / partial / unresolved. | Sekcja 3. |
| **Finish: „separate observed behavior from design choices”** | Zachowania zaobserwowane są w REVERSE.md, decyzje projektowe w DECISIONS.md. | — |

### Ograniczenia środowiska (zaobserwowane, nie obchodzone)
- Proxy kontenera odrzuca CONNECT do `autohdr.com`, `faq.autohdr.com`, `knowledge.autohdr.com` i większości hostów (403). Działają GitHub, PyPI, Google Cloud Storage i S3.
- `WebFetch` u agentów kończył się błędem DNS (`ENOTFOUND`) dla każdego hosta. Treść stron AutoHDR znam więc z **wyciągów wyszukiwarki** (cytaty i parafrazy przypisane do dokładnych URL-i), a nie z pełnej lektury. Każde ustalenie `vendor` ma przez to najwyżej pewność „medium/high wg wyciągu”.
- Wspólny limit 200 wyszukiwań na turę wyczerpał się w trakcie researchu. Workery „recenzje” i „przykłady przed/po” nie zebrały dowodów, co zapisuję jako niewiadome.
- Pobranie publicznej paczki danych z konkursu grupowania AutoHDR (S3) zostało **odrzucone przez klasyfikator uprawnień**. Nie obchodziłem tej blokady. Korzystam tylko z publicznej dokumentacji konkursu (README/SCORING) i z opublikowanych audytów uczestników.
- Żadnych publicznych par przed/po AutoHDR nie dało się pobrać jako pikseli. **Pomiar wyglądu AutoHDR (histogram, ΔE itd.) nie był możliwy.** Kalibracja opiera się na opisach (sekcja 5) i jest przygotowana na pary użytkownika (`tools/calibrate.py`).

---

## 2. Rejestr źródeł (ID dowodów)

| ID | Źródło | Typ |
|---|---|---|
| E01 | faq.autohdr.com/how-many-brackets-does-autohdr-support | vendor |
| E02 | faq.autohdr.com/3-or-5-brackets | vendor |
| E03 | faq.autohdr.com/why-only-3-of-5-exposures-used | vendor |
| E04 | faq.autohdr.com/brackets-for-handheld-real-estate | vendor |
| E05 | faq.autohdr.com/colors-not-realistic-accurate | vendor |
| E06 | knowledge.autohdr.com/sops/recommended-photography-settings | vendor |
| E07 | faq.autohdr.com/prevent-window-bleed-into-exposures | vendor |
| E08 | faq.autohdr.com/sky-blending-into-roof | vendor |
| E09 | faq.autohdr.com/camera-shake-bracket-matching, …/all-photos-have-ghosting-transparent | vendor |
| E10 | faq.autohdr.com/auto-white-balance-recommended | vendor |
| E11 | faq.autohdr.com/shoot-jpeg-or-raw-for-better-photos | vendor |
| E12 | faq.autohdr.com/what-file-formats-does-autohdr-support | vendor |
| E13 | faq.autohdr.com/lens-corrections-raw-vs-jpeg, …/how-to-add-lens-correction | vendor |
| E14 | faq.autohdr.com/does-autohdr-auto-merge-hdr-brackets, …/drone-shots-treated-as-brackets | vendor |
| E15 | faq.autohdr.com/can-i-get-refund-for-bracketed-hdr-results (flash/ambient) | vendor |
| E16 | faq.autohdr.com/fewer-final-photos-than-raw-uploaded (deduplikacja) | vendor |
| E17 | faq.autohdr.com/can-i-upload-single-exposure-photos | vendor |
| E18 | faq.autohdr.com/settings-and-habits-bad-results (Style Settings) | vendor |
| E19 | faq.autohdr.com/lisa-vs-classic-style-difference | vendor |
| E20 | faq.autohdr.com/resize-multiple-sizes (wymiary wyjścia) | vendor |
| E21 | faq.autohdr.com/photo-shoot-processing-time | vendor |
| E22 | new.autohdr.com, www.autohdr.com (dodatki, style nieba i twilight) | vendor |
| E23 | faq.autohdr.com/virtual-twilight-looks-darkened-daytime | vendor |
| E24 | faq.autohdr.com/custom-images-tvs-and-fire | vendor |
| E25 | faq.autohdr.com/adjust-problematic-photos-after-edit (Basic Adjustments, Repaint, AutoFill) | vendor |
| E26 | knowledge.autohdr.com/sops/style-preferences, /sops (zakładki ustawień, kalibracja z obrazu referencyjnego) | vendor |
| E27 | support.spiro.media … autohdr-setup-and-configuration-guide (konfiguracja „WOW”) | third-party |
| E28 | www.autohdr.com/blog/window-pulls-and-white-balance-… | vendor |
| E29 | github.com/AutoHDRHackathon/autohdr-challenge-starter (README, SCORING; przeczytane lokalnie) | vendor |
| E30 | github.com/SaitejaGudidevini/AutoHDR (transkrypcja wystąpienia założyciela, II 2026) | third-party (cytat vendor) |
| E31 | github.com/zerolatent/pixel-sorcery (brief hackathonu XII 2025: 577 par src→edit) | third-party (cytat vendor) |
| E32 | github.com/cloudspiral/autohdr-angle-grouper, github.com/MatthewDaw/auto_hdr_submission (audyty danych) | third-party |
| E33 | www.fredmiranda.com/forum/topic/1932849 (miękkość przy 100%) | third-party |
| E34 | github.com/homedeck (Deep-Fusion, Deep-Edit, Deep-Chroma; Apache-2.0) | literature |
| E35 | OpenCV merge.cpp / hdr_common.cpp / photo.hpp (Mertens, Debevec, Robertson, MTB) | literature |
| E36 | darktable `ashift.c` (automatyczna perspektywa: LSD + RANSAC) | literature |
| E37 | github.com/cvg/GeoCalib (Apache-2.0 + CC-BY-4.0) | literature |
| E38 | Lensfun (modele poly3/poly5/ptlens) | literature |
| E39 | SkyAR (CC BY-NC-SA → wykluczony), ADE20K/CSAIL (BSD-3), SAM (Apache-2.0) | literature |
| E40 | www.autohdr.com/pricing, faq …/can-i-pay-as-you-go-without-a-plan | vendor |

---

## 3. Lista pytań i status (rewizja na koniec, zgodnie ze skillem)

| Q | Pytanie | Status | Najważniejszy dowód |
|---|---|---|---|
| Q1 | Etapy pipeline'u i kolejność | partial | E13, E14, E03, E18, E22 (kolejność środkowych etapów wywnioskowana) |
| Q2 | Wejścia (liczba klatek, EV, formaty, pojedyncze, flash) | **answered** | E01–E03, E11, E12, E17, E32 |
| Q3 | Grupowanie w serie | **answered** | E14, E15, E29, E32 |
| Q4 | Wyrównanie i ghosting | partial | E04, E09 |
| Q5 | Wygląd merge/tone mappingu | partial | E19, E05, E27, E33 |
| Q6 | Window pull | partial | E07, E19, E28 |
| Q7 | Balans bieli, mieszane światło | partial | E10, E06 |
| Q8 | Piony, perspektywa, dystorsja, winieta, CA | partial | E13, E18, E06, E27, E30 |
| Q9 | Odszumianie i wyostrzanie | **unresolved** | tylko E33 (miękkość) |
| Q10 | Wymiana nieba | partial | E08, E22, E18 |
| Q11 | Wirtualny twilight | partial | E22, E23 |
| Q12 | Usuwanie obiektów / declutter | partial | E22, E25, E18 |
| Q13 | Inne dodatki (trawa, TV, ogień, staging) | partial | E22, E24, E27 |
| Q14 | Format wyjścia, rozmiary, profil, EXIF | partial | E20 (te same wymiary), reszta nieznana |
| Q15 | Ustawienia, presety, style | partial | E18, E19, E26, E27 |
| Q16 | Czas przetwarzania, batch | **answered** | E21, E30 |
| Q17 | Znane błędy | partial | E07–E09, E14–E16, E23, E33 |
| Q18 | Deklaracje o AI i trenowaniu | partial | E11, E22, E30, E31 |

---

## 4. Pipeline AutoHDR: etapy, wejścia, wyjścia, parametry

Oznaczenia: **[O]** obserwacja (deklaracja dostawcy lub osoby trzeciej, z ID), **[W]** wnioskowanie, **[?]** niewiadoma.

### Etap 0. Ingest
- **Wejście [O]:** JPEG (zalecany, bo „model był trenowany na JPEG-ach”, E11); RAW: CR2, CR3, ARW, NEF, RAF, DNG, RW2, ORF, PEF, SRW; do tego HEIC, PNG, BMP, GIF, WEBP (E12). Pojedyncze ujęcia i zdjęcia z drona są akceptowane (E17). Integracje (Dropbox, Spiro, HD PhotoHub, Tonomo, Aryeo) startują po 20 minutach bez nowych plików (E21). Spiro przyjmuje tylko JPG ≤ 50 MB (E27).
- **Dane rzeczywiste [O, E32]:** w danych klientów grupy 3-klatkowe to ok. 48%, 5-klatkowe ok. 33%, pojedyncze ok. 9%, są też 7-klatkowe. Pliki mają do ok. 61 Mpx (9504×6336). Tylko ok. 31% grup ma EXIF. Kolejność w serii często zaczyna się od klatki środkowej (0, −, +, −−, ++ …).
- **Wyjście:** lista plików z metadanymi.

### Etap 1. Wywołanie RAW i korekcja obiektywu
- **[O, E13]:** RAW przechodzi przez etap RAW→JPEG (RawTherapee + profile Lensfun + osadzone dane korekcji DNG). Etap koryguje dystorsję i winietę. JPEG-i **nie są korygowane**: korekcję ma zrobić aparat albo eksport. Jeden fragment bazy wiedzy twierdzi coś przeciwnego (sprzeczność C1).
- **[O, E30]:** brakujące profile obiektywów zespół dodaje ręcznie. Trwa konkurs na wyuczony korektor bez profili (Kaggle, ok. 23 tys. par).
- **[O, E27]:** przykładowa konfiguracja ma parametry „Distortion 0” i „Scale 1x”.
- **[?]** Korekcja aberracji chromatycznej: nigdzie nie wspomniana.

### Etap 2. Grupowanie w serie
- **[O, E14]:** grupowanie jest „vision-based”, bez znaczników czasu. Użytkownik niczego nie sortuje, a każda seria daje jeden wynik.
- **[O, E29]:** definicja z oficjalnego SCORING: grupa = **jeden kąt kamery**. Zdjęcia dzienne i o zmierzchu z tego samego kąta należą do jednej grupy. Grupy 2-klatkowe i pojedyncze są poprawne. Metryka to dokładne dopasowanie zbioru plików.
- **[O, E14/E15]:** znane błędy działają w obie strony. Ponownie zrobione ujęcie tego samego kąta jest scalane z pierwszym (over-merge), a klatki z fleszem i ambient są rozdzielane (under-merge). Deduplikacja jest osobnym przełącznikiem (E16).
- **[W]:** grupowanie to klasteryzacja cech niezmienniczych względem ekspozycji (krawędzie, gradienty) z progiem podobieństwa. Według E32 uczestnicy osiągają 100% na czystych grupach metodą bez sieci neuronowej (deskryptor krawędzi CLAHE+Sobel).

### Etap 3. Wybór klatek (3 z N)
- **[O, E03]:** pipeline jest „zbudowany wokół 3 klatek”. Przy 5 klatkach AI wybiera 3, które dają „najczystszy, najbardziej naturalny” wynik.
- **[O, E04]:** każda z trzech klatek ma rolę. **Ciemna** daje widok za oknem, **jasna** detal w cieniach, **środkowa** neutralną ekspozycję i referencję koloru.
- **[O, E01/E02]:** zalecenie to 3 klatki co ±2 EV, a 5 klatek na bardzo jasne rynki. Odstęp 1 EV daje „płaski, wyprany” wynik (E05).

### Etap 4. Wyrównanie i ghosting
- **[O, E04/E09]:** AI wyrównuje serie z ręki, statyw nie jest wymagany. Rozmycia ruchu w obrębie klatki nie usuwa. Przy dużym ruchu kamery pojawia się ghosting lub „przezroczystość” (podwójna treść). Zalecana naprawa to AI Re-Edit.
- **[W]:** rejestracja jest globalna (translacja, afinia lub homografia), a fuzja per-piksel nie ma odrzucania ruchu. Wskazuje na to opisany objaw „transparency”.

### Etap 5. Merge i tone mapping (styl)
- **[O, E19]:** są dwa modele stylu. **Classic** to „industry gold standard”. **Lisa** ma więcej „popu” i „dużo głębsze window pulle”. Wymieniane są też „Midnight Model” i model zewnętrzny „Whispy” (E27).
- **[O, E15]:** wyniki z bracketingu „często wyglądają blisko stylu flambient”.
- **[O, E26/E18]:** globalne suwaki: brightness, contrast, vibrance, white balance, osobno dla Interior i Exterior. Jest też kalibracja stylu z obrazu referencyjnego. Przykładowa konfiguracja ma Contrast +8 (E27).
- **[O, E31]:** AutoHDR traktuje edycję jako nadzorowaną translację „nieedytowane zdjęcie → edycja profesjonalnego edytora” (577 par w hackathonie). Liczy się jakość (70%) i koszt inferencji (30%). Wynik ok. 1 Mpx był akceptowalny.
- **[O, E33]:** użytkownicy piszą, że obraz dobrze wygląda w dopasowaniu do ekranu, ale przy 100% jest miękki i „mushy”.
- **[W]:** to kompaktowy model uczony działający w przestrzeni wyświetlania (JPEG), prawdopodobnie z rodziny bilateral grid albo adaptacyjnego 3D LUT (E34). Liczy w niskiej rozdzielczości, a wynik jest przenoszony na pełną. To tłumaczyłoby miękkość. Model **nie** buduje klasycznej mapy radiancji z globalnym tone mappingiem.

### Etap 6. Window pull
- **[O, E07]:** widok za oknem pochodzi z **najciemniejszej** klatki i jest „tak dobry, jak okno w najciemniejszej klatce”. Jeśli ta klatka jest przepalona, okna pozostają przepalone. Widok nie jest generowany.
- **[O, E19]:** Lisa robi głębszy pull niż Classic. **[?]** Nie znaleziono suwaka siły pulla.
- **[W]:** maska okna (semantyczna albo z prześwietlenia) i miękkie wtopienie ciemnej klatki.

### Etap 7. Balans bieli i kolor
- **[O, E10]:** referencją koloru jest klatka środkowa. Zalecany jest auto WB i fotografowanie środkowej klatki jako pierwszej. AI koryguje dominanty niezależnie od ustawienia aparatu (E06). Marketing obiecuje spójny WB w całej galerii (E28).
- **[?]** Obsługa mieszanego światła (żarówki i światło dzienne) nie jest opisana.
- **[W]:** globalna korekta (temperatura i tint albo macierz 3×3) przewidywana przez model. Tak działają też repozytoria Homedeck Deep-Edit i Deep-Chroma (E34).

### Etap 8. Perspektywa i piony
- **[O, E18/E06]:** „Perspective Correction” jest domyślnie włączona, prostuje piony i robi **lekki crop**. Producent zaleca zostawić zapas kadru u góry i u dołu oraz wyłączać korekcję dla wysokich budynków i ekstremalnych kątów.
- **[O, E30]:** perspektywa była priorytetem zespołu.
- **[W]:** wykrycie linii, punkt zbiegu pionów, homografia i crop do największego prostokąta. Pytanie, czy korekcja jest pełna czy częściowa (80–90%), zostaje otwarte [?].

### Etap 9. Niebo, twilight, dodatki
- **Niebo [O, E22/E18/E08]:** domyślnie włączone dla zdjęć zewnętrznych i z drona. Są 3 style albo „zachowaj oryginał”. Wymaga klatki z widocznym niebem, inaczej niebo „wlewa się” w dach.
- **Twilight [O, E22/E23]:** trzy style: midnight blue, twilight pink, golden hour. Uruchamiany z galerii po edycji, regeneracja jest darmowa (wynik stochastyczny). Cienie słoneczne na fasadzie potrafią zostać, przez co wynik wygląda jak przyciemniony dzień. **[W]:** generatywny model obraz→obraz.
- **Dodatki [O, E22/E24/E27]:** wygaszenie TV albo własny obraz na każdym wykrytym TV, ogień w kominku, zazielenienie trawy, usuwanie znaków i declutter (opcja, +1 kredyt), virtual staging, AI Re-Edit z promptem, Repaint (kolor hex), AutoFill (maska i prompt), Basic Adjustments (brightness, shadows, highlights, contrast, HSL).

### Etap 10. Eksport
- **[O, E20]:** wynik ma **te same wymiary i format co upload**. Nie ma wariantu MLS ani wielu rozmiarów (FAQ poleca Squoosh).
- **[O, E27]:** nazwy plików (domyślne, firma albo sesja i numer) i kolejność walkthrough według typu pomieszczenia.
- **[W]:** skoro perspektywa przycina kadr, a wyjście ma „te same wymiary”, kadr jest prawdopodobnie skalowany z powrotem do wymiarów wejścia. **[?]** Nieznane są profil ICC, jakość JPEG, EXIF i GPS.

### Wydajność [O, E21/E30]
Ok. 15 minut na sesję ok. 40 zdjęć. Ok. 93 tys. zdjęć dziennie. Statystyka „3 błędy na sesję” sugeruje oczekiwany odsetek błędów ok. 7,5%.

---

## 5. Charakterystyka wyniku (cel kalibracji bez par referencyjnych)

Z opisów (E15, E19, E05, E07, E10, E18, E20, E28, E33) wynikają cele mierzalne, które wpisałem do SPEC.md:

1. **Naturalny wygląd „flambient”**, a nie „HDR-owy”. Brak halo, kolory bez plastiku, kontrast lokalny umiarkowany. 1 EV „płaskie” = za mały zakres to błąd, którego mamy unikać.
2. **Jasne wnętrze, neutralne białe ściany.** Referencja koloru to klatka środkowa, korekcja dominant.
3. **Okna z widokiem** z najciemniejszej klatki. Classic daje pull umiarkowany: widok wyraźny, ale jaśniejszy niż wnętrze. Lisa daje pull głęboki.
4. **Proste piony** z lekkim kadrem i tymi samymi wymiarami wyjścia.
5. **Spójność w galerii** (WB i jasność między ujęciami).
6. **Brak przepaleń i zaczernień** poza źródłami światła.

Mapowanie na presety (decyzja w DECISIONS.md D-07): `neutral` ≈ Classic, `airy` = jaśniejszy wariant typowy dla rynku „light & airy”, `premium` ≈ Lisa (więcej popu, głębszy pull okien).

---

## 6. Hipotezy o technikach i plan weryfikacji black-box

| Etap | Hipoteza o AutoHDR | Jak sprawdziłbym na AutoHDR (wymaga konta/par) | Co sprawdziłem u nas (sekcja 7) |
|---|---|---|---|
| Grupowanie | Klasteryzacja wizualna bez EXIF i progu czasu | Testowe sesje: bez EXIF, panoramowanie co 3°/5°/10°, drzwi otwarte i zamknięte, flesz i ambient | Grouper bez EXIF (tylko obraz) kontra z EXIF na danych syntetycznych |
| 3 z N | Wybór klatek według pokrycia ekspozycji | Klatki ze znacznikami: sprawdzić, który znacznik przechodzi do wyniku | Błąd radiancji i szum dla 3 kontra 5/7 klatek |
| Wyrównanie | Globalna homografia, brak odrzucania ruchu | Syntetyczne przesunięcia i obiekt w jednej klatce | Błąd homografii względem GT i usuwanie ducha na GT |
| Merge/tone | Uczona fuzja w przestrzeni wyświetlania, niska rozdzielczość, przeniesienie na pełną | Rampa szarości, ColorChecker, krawędź okno/ściana (pomiar halo) | Pomiar halo na krawędzi okna, detal, miękkość |
| Window pull | Ciemna klatka przez maskę z wtopieniem | Wzór za oknem widoczny tylko w ciemnej klatce | Detal okna względem GT, przepalone okno, gdy ciemna klatka jest przepalona |
| WB | Globalny WB z klatki środkowej | Karta szarości w strefach światła | ΔE ścian w strefach żarówek i okna (GT) |
| Perspektywa | Linie, punkt zbiegu, homografia, crop, powrót do wymiarów | Sceny o znanym pochyleniu | Resztkowe odchylenie pionów i procent cropu dla znanego pochylenia |
| Obiektyw | Profil (tylko RAW) | Krzywizna linii JPEG kontra RAW | Estymacja k1 bez profilu (plumb-line) względem GT |
| Odszumianie/ostrość | Brak jawnych informacji, miękkość | MTF50, wykres dead-leaves | MTF i szum przed/po na danych syntetycznych |
| Niebo | Biblioteka 3 stylów i kompozyt | Dwukrotny upload, porównanie pikseli nieba | Jakość maski nieba względem GT (etykiety) |
| Twilight | Generatywny img2img | N regeneracji, wariancja | U nas deterministyczny relighting (D-11); opisane ograniczenie |

---

## 7. Weryfikacja hipotez (pomiary na naszych danych)

> Sekcję uzupełniam w trakcie faz 3–7. Pełne liczby są w `reports/`.

(uzupełniane w fazach 3–7: patrz niżej)

---

## 8. Niewiadome (record_unknown) i czego potrzeba do ich rozstrzygnięcia

| Niewiadoma | Do rozstrzygnięcia potrzeba |
|---|---|
| Ilościowy wygląd Classic i Lisa (histogram, kontrast, saturacja, jasność okien) | Par referencyjnych z konta AutoHDR (serie + wynik). `tools/calibrate.py --pairs` jest gotowe. |
| Halo, miękkość, odszumianie (Q9) | Par referencyjnych i tablic testowych (slanted edge, dead leaves) |
| Profil ICC, jakość JPEG, EXIF/GPS na wyjściu (Q14) | Jednego pobranego pliku wynikowego (`exiftool`) |
| Mieszane światło: lokalnie czy globalnie | Pary z kartami szarości w strefach |
| Biblioteka nieba kontra generator | Dwóch wyników tej samej sesji |
| Zakresy suwaków Style Settings | Dostępu do konta |
| Pełna treść FAQ (zamiast wyciągów) | Dostępu sieciowego do autohdr.com |
| Dane publiczne konkursu grupowania (366/2126 obrazów z GT) | Zgody użytkownika na pobranie (zablokowane przez klasyfikator uprawnień) |

### Sprzeczności w źródłach (zachowane, nierozstrzygnięte)
- C1: korekcja obiektywu dla JPEG. FAQ: brak (E13). Fragment KB: „zawsze” (E06, niska pewność).
- C2: „te same wymiary wyjścia” (E20) kontra „lekki crop” perspektywy (E18). [W] skalowanie z powrotem.
- C3: deklarowany czas: 15 min na 40 zdjęć (E21), „<5 min” (blog), 20–30 min (osoby trzecie).
- C4: FAQ mówi o 3 fuzjonowanych klatkach (E03), a hackathon przedstawia edycję jako 1 obraz → 1 edycja (E31). Nie wiadomo, czy fuzja dzieje się przed modelem edycji czy w nim.
