# 02 - Polish company-registry API sources: integration spec

Research date: 2026-10-10. Compiled WITHOUT network access to the gov.pl APIs (sandbox proxy blocks `*.gov.pl`, `ec.europa.eu`, `stat.gov.pl`). Everything below comes from open-source clients, their committed fixtures and vendor docs fetched through GitHub. Each section ends with a confidence note; fixtures under `test/fixtures/` carry a `_note` / XML comment saying whether they are verbatim or reconstructed.

Legend: **[V]** verified from a real fixture/source code, **[D]** documented by 2+ independent clients/docs, **[R]** recalled / inferred - verify against a live call before depending on it.

---------------------------------------------------------------------------

## 1. GUS REGON BIR 1.1 (SOAP 1.2, WS-Addressing, MTOM)

### 1.1 Endpoints / auth [V]

| env | service URL | key |
|---|---|---|
| test | `https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc` | public key `abcde12345abcde12345` (confirmed: rolzwy7/RegonAPI `API_KEY_TEST_ENV`). Test DB = old anonymised data (e.g. REGON 000331501 GUS, `ul. Test-Krucza`). Has quotas. |
| prod | `https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc` | personal key; request by mail to `regon_bir@stat.gov.pl` (entity name, a REGON, contact person, the egress IPs). **Cloudflare Workers egress IPs are not static - ask GUS up-front whether an IP allow-list is enforced.** |
| WSDL | test `https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/wsdl/UslugaBIRzewnPubl-ver11-test.wsdl`, prod `https://wyszukiwarkaregon.stat.gov.pl/wsBIR/wsdl/UslugaBIRzewnPubl-ver11-prod.wsdl` | |

Transport: one HTTP `POST` to the `.svc` URL per call.
- Request headers: `Content-Type: application/soap+xml; charset=utf-8` (bir1 sends `application/soap+xml`). **After login every call except Zaloguj must carry an HTTP header `sid: <session id>`** (not a SOAP header). Missing/expired sid => empty/err result, `GetValue('KomunikatKod')` = `7` (or empty).
- SOAP 1.2 envelope with WS-Addressing `wsa:To` (= the service URL being called; use the prod URL for prod) and `wsa:Action` (below). Mismatched To/Action => SOAP fault from WCF. [D]
- Session: from Zaloguj until `Wyloguj` or idle timeout (~60 min per GUS docs [R]). A Worker should log in lazily, cache `sid` (KV/Durable Object) ~50 min, and re-login on `KomunikatKod` `7`/empty or empty result. Only one session per key is the safe assumption [R].

### 1.2 Envelopes (exact; from orkanap/regonapi gusdoc/Envelops.txt + bir1 templates) [V]

Namespaces: `soap=http://www.w3.org/2003/05/soap-envelope`, `ns=http://CIS/BIR/PUBL/2014/07`, `dat=http://CIS/BIR/PUBL/2014/07/DataContract`, `wsa=http://www.w3.org/2005/08/addressing` (declared on `soap:Header`). **GetValue uses a different `ns`: `http://CIS/BIR/2014/07`.**

Zaloguj (no `sid` header):
```xml
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">
  <soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">
    <wsa:To>https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc</wsa:To>
    <wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>
  </soap:Header>
  <soap:Body><ns:Zaloguj><ns:pKluczUzytkownika>KEY</ns:pKluczUzytkownika></ns:Zaloguj></soap:Body>
</soap:Envelope>
```
DaneSzukajPodmioty (header `sid`; all `dat:` children optional - include only those used; XML-escape values):
```xml
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07" xmlns:dat="http://CIS/BIR/PUBL/2014/07/DataContract">
  <soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">
    <wsa:To>SERVICE_URL</wsa:To>
    <wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>
  </soap:Header>
  <soap:Body><ns:DaneSzukajPodmioty><ns:pParametryWyszukiwania>
    <dat:Nip>5261040828</dat:Nip>   <!-- or dat:Regon (9|14 digits) | dat:Krs (10) | dat:Nipy | dat:Regony9zn | dat:Regony14zn | dat:Krsy -->
  </ns:pParametryWyszukiwania></ns:DaneSzukajPodmioty></soap:Body>
</soap:Envelope>
```
DanePobierzPelnyRaport (header `sid`): body `<ns:DanePobierzPelnyRaport><ns:pRegon>000331501</ns:pRegon><ns:pNazwaRaportu>BIR11OsPrawna</ns:pNazwaRaportu></ns:DanePobierzPelnyRaport>`, Action `.../IUslugaBIRzewnPubl/DanePobierzPelnyRaport` (same ns/header as above, no `dat`).
DanePobierzRaportZbiorczy: `<ns:pDataRaportu>2026-10-07</ns:pDataRaportu><ns:pNazwaRaportu>BIR11NowePodmiotyPrawneOrazDzialalnosciOsFizycznych</ns:pNazwaRaportu>` (date YYYY-MM-DD, at most ~1 week back; **no leading space in the name** - the GUS doc sample has one by mistake). Action `.../DanePobierzRaportZbiorczy`.
GetValue (header `sid`, **ns = `http://CIS/BIR/2014/07`**): `<ns:GetValue><ns:pNazwaParametru>KomunikatKod</ns:pNazwaParametru></ns:GetValue>`, Action `http://CIS/BIR/2014/07/IUslugaBIR/GetValue`.
Wyloguj (header `sid` is not required by the template; param carries it): `<ns:Wyloguj><ns:pIdentyfikatorSesji>SID</ns:pIdentyfikatorSesji></ns:Wyloguj>`, Action `.../IUslugaBIRzewnPubl/Wyloguj`. Result is boolean.

GetValue `pNazwaParametru` values: `StatusSesji` (1 alive / 0 none), `StatusUslugi` (0 unavailable, 1 available, 2 technical break), `KomunikatUslugi`, `StanDanych` (data date, `dd-mm-yyyy`), `KomunikatKod`, `KomunikatTresc`.

### 1.3 Response framing and parsing [V framing, D parsing]

HTTP response header: `Content-Type: multipart/related; type="application/xop+xml"; boundary="uuid:...+id=N"; start="<http://tempuri.org/0>"; start-info="application/soap+xml"`. Body = one MIME part (no real attachments), see `fixtures/regon/zaloguj-response.xml` (verbatim):
```
--uuid:...+id=N
Content-ID: <http://tempuri.org/0>
Content-Transfer-Encoding: 8bit
Content-Type: application/xop+xml;charset=utf-8;type="application/soap+xml"

<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://www.w3.org/2005/08/addressing"><s:Header><a:Action s:mustUnderstand="1">.../ZalogujResponse</a:Action></s:Header><s:Body><ZalogujResponse xmlns="http://CIS/BIR/PUBL/2014/07"><ZalogujResult>c47xb5n78ppgc9hks85f</ZalogujResult></ZalogujResponse></s:Body></s:Envelope>
--uuid:...+id=N--
```
Do NOT use a MIME library. All three reference clients just regex the text:
1. `const text = await res.text()`.
2. `m = text.match(/<(?:\w+:)?(DaneSzukajPodmiotyResult|DanePobierzPelnyRaportResult|ZalogujResult|GetValueResult|WylogujResult)[^>]*>([\s\S]*?)<\/(?:\w+:)?\1>/)`; self-closing `<XResult/>` (or `i:nil`) = empty (Zaloguj with a bad key returns empty string).
3. For the data operations the inner string is **XML-escaped XML** (`&lt;root&gt;&lt;dane&gt;...`) [R: real traffic; GUS docs show CDATA - accept both]: strip `<![CDATA[...]]>` if present else decode `&lt; &gt; &quot; &apos; &amp; &#xD; &#xA; &#NNN;` (decode `&amp;` last).
4. Parse `<root><dane>...</dane>...</root>` with a tiny flat parser (every `dane` is a flat list of leaf elements; empty = `<x />` => null). Values are strings; keep leading zeros (REGON, postal codes, symbols). 0..n `<dane>` per answer.
5. Errors live INSIDE the payload: a `<dane>` containing `ErrorCode`, `ErrorMessagePl`, `ErrorMessageEn` (+ echoed `Nip`/`Regon`). Check `ErrorCode` first (bir1 `BirError.assert`). HTTP status stays 200. Wrong-key login => empty `ZalogujResult`.
6. SOAP-level failures (bad Action/To, malformed XML) come as HTTP 400/500 with a `<s:Fault>`.

Error / status codes:
- `ErrorCode` in payload: `4` no entity found (`Nie znaleziono podmiotu dla podanych kryteriów wyszukiwania.` / `No data found for the specified search criteria.`; for reports "Nie znaleziono wpisu..." and a frequent cause is **using a P report for an F entity or vice versa**); `5` invalid or empty report name (`Nieprawidłowa lub pusta nazwa raportu.`); `11` PKD not available for entities struck off before 2014-11-08; `21` entity is not a civil partnership; `22` no partners recorded; `105` invalid summary-report name.
- `GetValue('KomunikatKod')`: empty or `7` no session / expired / bad `sid`; `0` previous op OK; `1` captcha required (obsolete); `2` too many identifiers in DaneSzukaj; `4` no entities; `5` no privileges for the report / bad report name.
- Limits: batch search (`Nipy`, `Regony9zn`, `Regony14zn`, `Krsy`) is documented **max 20** by GUS-derived clients (GusApi throws on >20; gus_bir1 "up to 20"); one PHP client claims 100 - use <=20. Separator: any non-digit (comma or space; RegonAPI joins with comma). **Only one identifier type per call** (bir1 notes), a mix returns code 2. Production request quotas are not publicly documented [R]; ask GUS. The test environment has quotas.

### 1.4 DaneSzukajPodmioty result fields [V]
`Regon` (9 digits for P/F, 14 for LP/LF; very old fixtures show 14 for P too), `Nip`, `StatusNip` (empty | `Uchylony` | `Unieważniony`), `Nazwa`, `Wojewodztwo`, `Powiat`, `Gmina`, `Miejscowosc`, `KodPocztowy` (`00-925`), `Ulica` (`ul. Test-Krucza`; may be absent), `NrNieruchomosci`, `NrLokalu`, `Typ`, `SilosID`, `DataZakonczeniaDzialalnosci`, and (newer) `MiejscowoscPoczty`.
- `Typ`: `P` legal person, `F` natural person (sole trader), `LP` local unit of P, `LF` local unit of F.
- `SilosID`: 1 CEIDG, 2 agricultural, 3 other, 4 deleted under old KRUPGN (up to 2014-11-08), 6 legal person's activity (P/LP only). A sole trader yields **one `<dane>` per silos** (see `szukaj-osfizyczna-response.xml`), same `Regon`.
- No name search exists (only Nip/Regon/Krs + batch variants).

### 1.5 Which report to call [V]
Reports require the REGON **as returned by search**; most reports want the **9-digit** REGON (P/F), local-unit reports (`BIR11JednLokalna*`, `*ListaJednLokalnych` take 9, their PKD/detail take 14) want the **14-digit** one (GusApi `REGON_9_REPORTS`). Pad/truncate defensively and retry with the other form on code 4.

Routing: `Typ=P` -> `BIR11OsPrawna` (+ `BIR11OsPrawnaPkd`); `Typ=F` -> `BIR11OsFizycznaDaneOgolne` (person) + by `SilosID`: 1 `BIR11OsFizycznaDzialalnoscCeidg`, 2 `...DzialalnoscRolnicza`, 3 `...DzialalnoscPozostala`, 4 `...DzialalnoscSkreslonaDo20141108`, + `BIR11OsFizycznaPkd`; `LP` -> `BIR11JednLokalnaOsPrawnej`/`...Pkd`; `LF` -> `BIR11JednLokalnaOsFizycznej`/`...Pkd`.

All BIR 1.1 full-report names: `BIR11OsFizycznaDaneOgolne, BIR11OsFizycznaDzialalnoscCeidg, BIR11OsFizycznaDzialalnoscRolnicza, BIR11OsFizycznaDzialalnoscPozostala, BIR11OsFizycznaDzialalnoscSkreslonaDo20141108, BIR11OsFizycznaPkd, BIR11OsFizycznaListaJednLokalnych, BIR11JednLokalnaOsFizycznej, BIR11JednLokalnaOsFizycznejPkd, BIR11OsPrawna, BIR11OsPrawnaPkd, BIR11OsPrawnaListaJednLokalnych, BIR11JednLokalnaOsPrawnej, BIR11JednLokalnaOsPrawnejPkd, BIR11OsPrawnaSpCywilnaWspolnicy, BIR11TypPodmiotu`. (BIR 1.0 names `PublDaneRaport...` and BIR12 names also accepted by the same endpoint; BIR12 adds fields, e.g. `BIR12OsPrawna`, `BIR121JednLokalnaOsPrawnej`. Note GusApi constants now point to BIR12.) Bulk (DanePobierzRaportZbiorczy) returns lists of `<regon>`: `BIR11NowePodmiotyPrawneOrazDzialalnosciOsFizycznych, BIR11AktualizowanePodmiotyPrawneOrazDzialalnosciOsFizycznych, BIR11SkreslonePodmiotyPrawneOrazDzialalnosciOsFizycznych, BIR11NoweJednostkiLokalne, BIR11AktualizowaneJednostkiLokalne, BIR11SkresloneJednostkiLokalne`.

### 1.6 Field lists (element order as documented) [V from GUS doc sample]

**BIR11OsPrawna** (`praw_*`): `praw_regon9, praw_nip, praw_statusNip, praw_nazwa, praw_nazwaSkrocona, praw_numerWRejestrzeEwidencji, praw_dataWpisuDoRejestruEwidencji, praw_dataPowstania, praw_dataRozpoczeciaDzialalnosci, praw_dataWpisuDoRegon, praw_dataZawieszeniaDzialalnosci, praw_dataWznowieniaDzialalnosci, praw_dataZaistnieniaZmiany, praw_dataZakonczeniaDzialalnosci, praw_dataSkresleniaZRegon, praw_dataOrzeczeniaOUpadlosci, praw_dataZakonczeniaPostepowaniaUpadlosciowego, praw_adSiedzKraj_Symbol, praw_adSiedzWojewodztwo_Symbol, praw_adSiedzPowiat_Symbol, praw_adSiedzGmina_Symbol, praw_adSiedzKodPocztowy, praw_adSiedzMiejscowoscPoczty_Symbol, praw_adSiedzMiejscowosc_Symbol, praw_adSiedzUlica_Symbol, praw_adSiedzNumerNieruchomosci, praw_adSiedzNumerLokalu, praw_adSiedzNietypoweMiejsceLokalizacji, praw_numerTelefonu, praw_numerWewnetrznyTelefonu, praw_numerFaksu, praw_adresEmail, praw_adresStronyinternetowej, praw_adSiedzKraj_Nazwa, praw_adSiedzWojewodztwo_Nazwa, praw_adSiedzPowiat_Nazwa, praw_adSiedzGmina_Nazwa, praw_adSiedzMiejscowosc_Nazwa, praw_adSiedzMiejscowoscPoczty_Nazwa, praw_adSiedzUlica_Nazwa, praw_podstawowaFormaPrawna_Symbol, praw_szczegolnaFormaPrawna_Symbol, praw_formaFinansowania_Symbol, praw_formaWlasnosci_Symbol, praw_organZalozycielski_Symbol, praw_organRejestrowy_Symbol, praw_rodzajRejestruEwidencji_Symbol, praw_podstawowaFormaPrawna_Nazwa, praw_szczegolnaFormaPrawna_Nazwa, praw_formaFinansowania_Nazwa, praw_formaWlasnosci_Nazwa, praw_organZalozycielski_Nazwa, praw_organRejestrowy_Nazwa, praw_rodzajRejestruEwidencji_Nazwa, praw_liczbaJednLokalnych`. (BIR 1.0 `PublDaneRaportPrawna` additionally has `praw_regon14`, `praw_adresEmail2`, `praw_adKor*` correspondence-address block; BIR12 adds more.) Casing drifts between docs/reports (`praw_dataSkresleniazRegon` vs `...ZRegon`, `praw_dataWpisuDoREGON` vs `...DoRegon`, `praw_numerWrejestrze...`): **look keys up case-insensitively**.

**BIR11OsFizycznaDaneOgolne**: `fiz_regon9, fiz_nip, fiz_statusNip, fiz_nazwisko, fiz_imie1, fiz_imie2, fiz_dataWpisuPodmiotuDoRegon, fiz_dataZaistnieniaZmiany, fiz_dataSkresleniaPodmiotuZRegon, fiz_podstawowaFormaPrawna_Symbol, fiz_szczegolnaFormaPrawna_Symbol, fiz_formaFinansowania_Symbol, fiz_formaWlasnosci_Symbol, fiz_podstawowaFormaPrawna_Nazwa, fiz_szczegolnaFormaPrawna_Nazwa, fiz_formaFinansowania_Nazwa, fiz_formaWlasnosci_Nazwa, fiz_dzialalnoscCeidg, fiz_dzialalnoscRolnicza, fiz_dzialalnoscPozostala, fiz_dzialalnoscSkreslonaDo20141108, fiz_liczbaJednLokalnych` (flags 0/1 say which silos reports have data).

**BIR11OsFizycznaDzialalnoscCeidg**: `fiz_regon9, fiz_nazwa, fiz_nazwaSkrocona, fiz_dataPowstania, fiz_dataRozpoczeciaDzialalnosci, fiz_dataWpisuDzialalnosciDoRegon, fiz_dataZawieszeniaDzialalnosci, fiz_dataWznowieniaDzialalnosci, fiz_dataZaistnieniaZmianyDzialalnosci, fiz_dataZakonczeniaDzialalnosci, fiz_dataSkresleniaDzialalnosciZRegon, fiz_dataOrzeczeniaOUpadlosci, fiz_dataZakonczeniaPostepowaniaUpadlosciowego,` the same `fiz_adSiedz*` block (Symbol set, KodPocztowy, MiejscowoscPoczty_Symbol, Miejscowosc_Symbol, Ulica_Symbol, NumerNieruchomosci, NumerLokalu, NietypoweMiejsceLokalizacji), `fiz_numerTelefonu, fiz_numerWewnetrznyTelefonu, fiz_numerFaksu, fiz_adresEmail, fiz_adresStronyinternetowej,` the `fiz_adSiedz*_Nazwa` block (Kraj, Wojewodztwo, Powiat, Gmina, Miejscowosc, MiejscowoscPoczty, Ulica), `fizC_dataWpisuDoRejestruEwidencji, fizC_dataSkresleniaZRejestruEwidencji, fizC_numerWRejestrzeEwidencji, fizC_OrganRejestrowy_Symbol, fizC_OrganRejestrowy_Nazwa, fizC_RodzajRejestru_Symbol, fizC_RodzajRejestru_Nazwa, fizC_NiePodjetoDzialalnosci`. Rolnicza/Pozostala/Skreslona share the `fiz_*` core (Pozostala uses `fizP_*` registry block; Skreslona adds `fiz_adresEmail2` and has no registry block). Note the user-specified `fiz_dataSkresleniazRegon` does not exist in 1.1; use `fiz_dataSkresleniaDzialalnosciZRegon` (activity) / `fiz_dataSkresleniaPodmiotuZRegon` (person).

**PKD**: `BIR11OsPrawnaPkd` -> `praw_pkdKod, praw_pkdNazwa, praw_pkdPrzewazajace` (+ optional `praw_pkdWersja`); `BIR11OsFizycznaPkd` -> `fiz_pkd_Kod, fiz_pkd_Nazwa, fiz_pkd_Przewazajace, fiz_SilosID, fiz_Silos_Symbol, fiz_dataSkresleniaDzialalnosciZRegon`; local unit: `lokpraw_pkdKod/_pkdNazwa/_pkdPrzewazajace`, `lokfiz_*`. Codes without dots (`4773Z`); `Przewazajace` 1 = primary. `BIR11OsPrawnaSpCywilnaWspolnicy`: `wspolsc_regonWspolnikSpolki, wspolsc_imiePierwsze, wspolsc_imieDrugie, wspolsc_nazwisko, wspolsc_firmaNazwa`.

Status derivation: `praw_dataZakonczeniaDzialalnosci`/`fiz_dataZakonczeniaDzialalnosci` set = activity ended; `*_dataSkresleniaZRegon` = removed from REGON; `*_dataZawieszeniaDzialalnosci` without later `*_dataWznowieniaDzialalnosci` = suspended; search result `DataZakonczeniaDzialalnosci` is the cheap early signal.

Fixtures: `zaloguj-response.xml` verbatim (GusApi); the others reconstructed from GUS-documented samples (names/order exact, entity data anonymised/synthetic).

---------------------------------------------------------------------------

## 2. KRS Open API (Ministry of Justice)

Base `https://api-krs.ms.gov.pl`, docs `https://prs.ms.gov.pl/krs/openApi`. No key/token, CORS enabled, JSON. [D]

| endpoint | notes |
|---|---|
| `GET /api/krs/OdpisAktualny/{krs}?rejestr=P\|S&format=json` | current extract. `{krs}` 10 digits (zero-pad). `rejestr` P = entrepreneurs, S = associations/foundations/public institutions (wrong register => 404). `format` is always JSON. |
| `GET /api/krs/OdpisPelny/{krs}?rejestr=P&format=json` | full history: `odpis.rodzaj="Pełny"`, header is `naglowekP` with `wpis[]` (dataWpisu, numerWpisu, opis, oznaczenieSaduDokonujacegoWpisu, sygnaturaAktSprawyDotyczacejWpisu); EVERY data property is an array of `{value, nrWpisuWprow, nrWpisuWykr?}` - current value = item without `nrWpisuWykr`. Real sample: kordybordy/KRS `data/latest/0000078664.json`. |
| `GET /api/Krs/Biuletyn/{yyyy-MM-dd}` | daily change bulletin (KRS numbers changed that day), only for days after 2021-12-08. Hourly variant `BiuletynGodzinowy` (day + from/to hour 00-23). Response schema not verified [R]. |

Status codes: 200, 404 (no such entity in that register), 5xx; 400 for malformed number [D]. 204 seen by one client. No documented rate limit; clients pace ~500 ms and retry 429/5xx twice (250/750 ms). **Personal data in the open API is masked** (given names/surnames reduced to first letter + `*`, PESEL only first digit, e.g. `"imie":"T******"`), so representation can show roles and initials only.

### OdpisAktualny JSON paths [D; fixture reconstructed]
Top: `odpis.rodzaj` ("Aktualny"), `odpis.naglowekA`, `odpis.dane`.
- `odpis.naglowekA`: `rejestr` ("RejP"/"RejS"), `numerKRS`, `dataCzasOdpisu` (`dd.MM.yyyy HH:mm:ss`), `stanZDnia`, `dataRejestracjiWKRS`, `numerOstatniegoWpisu`, `dataOstatniegoWpisu`, `sygnaturaAktSprawyDotyczacejOstatniegoWpisu`, `oznaczenieSaduDokonujacegoOstatniegoWpisu`, `stanPozycji`; deregistered entities add `dataWykreslenia` (read by krs-verify; exact position [R]). Dates are `dd.MM.yyyy` strings.
- **name / form**: `odpis.dane.dzial1.danePodmiotu.nazwa`, `.formaPrawna`.
- **NIP / REGON**: `odpis.dane.dzial1.danePodmiotu.identyfikatory.nip|regon` (REGON usually 14 digits - truncate to 9 if the first 9 + checksum are valid).
- **seat**: `dzial1.siedzibaIAdres.siedziba.{kraj,wojewodztwo,powiat,gmina,miejscowosc}`; **address**: `dzial1.siedzibaIAdres.adres.{ulica,nrDomu,nrLokalu,miejscowosc,kodPocztowy,poczta,kraj}`; `dzial1.siedzibaIAdres.adresPocztyElektronicznej`, `.adresStronyInternetowej`, `.adresDoDoreczenElektronicznychWpisanyDoBAE` (may be arrays of such objects in Pełny; absent when empty).
- **capital**: `dzial1.kapital.wysokoscKapitaluZakladowego.{waluta,wartosc}` (`"1565420000,00"`, comma decimal; formats may include spaces), also `czescKapitaluWplaconegoPokrytego`; partners of sp. z o.o. in `dzial1.wspolnicySpzoo[]`.
- **representation**: `odpis.dane.dzial2.reprezentacja.{nazwaOrganu, sposobReprezentacji, sklad[]}`; member: `nazwisko.nazwiskoICzlon` (+`nazwiskoIICzlon`), `imiona.{imie,imieDrugie}`, `identyfikator.pesel`, `funkcjaWOrganie`, `czyZawieszona`, (`dataZawieszeniaDo`); `dzial2.prokurenci[]` (+`rodzajProkury`); supervisory board `dzial2.organNadzoru[]`. Simple entities may have `wspolnicy`/other organ names [R].
- **PKD**: `odpis.dane.dzial3.przedmiotDzialalnosci.przedmiotPrzewazajacejDzialalnosci[]` and `.przedmiotPozostalejDzialalnosci[]`, items `{opis, kodDzial, kodKlasa, kodPodklasa}` -> PKD = `${kodDzial}.${kodKlasa}.${kodPodklasa}` (e.g. 19.20.Z).
- **status / wind-up**: `dzial6` (połączenie/podział/przekształcenie `polaczeniePodzialPrzeksztalcenie[]`, `rozwiazanieUniewaznienie`), liquidation/bankruptcy markers in `dzial6`/`dzial4`-`dzial5` (names not verified [R]); `naglowekA.dataWykreslenia` for struck-off; "W LIKWIDACJI"/"W UPADŁOŚCI" is also appended to `nazwa`. `dzial3.wzmiankiOZlozonychDokumentach` lists filed financial statements.
- Failure modes: 404 body undocumented; always verify `naglowekA.numerKRS`.

### Search by name [D]
**No official name search in the Open API** (lookup only by KRS number). Unofficial: the public search website's backend `POST https://wyszukiwarka-krs-api.ms.gov.pl/api/wyszukiwarka/krs` (JSON body `{rejestr:["P","S"], podmiot:{krs,nip,regon,nazwa,wojewodztwo,powiat,gmina,miejscowosc,dokladnaNazwa}, status:{...}, paginacja:{liczbaElementowNaStronie<=100,maksymalnaLiczbaWynikow:100,numerStrony}}`; response `{liczbaPodmiotow, listaPodmiotow:[{numer,nazwa,miejscowosc,typRejestru,czyOPP,czyUpadlosc}]}`) used by soba-labs/krs-mcp. It needs browser-mimicking headers (`origin/referer: https://wyszukiwarka-krs.ms.gov.pl`, `x-api-key`, and a generated `apikey` token, see that repo's `src/key-generator.ts`), is undocumented, may answer 403, and its reuse is legally grey - **do not build a paid product on it**; use NIP/REGON/KRS lookups (NIP->KRS via GUS `Nipy`/search `Nip`, or Biała Lista `result.subject.krs`).

Fixtures: `krs/odpis-aktualny-P.json` and `-wykreslony.json` RECONSTRUCTED (the real API was unreachable; ORLEN ids real, the rest illustrative); `krs/notfound.txt` describes status behaviour.

---------------------------------------------------------------------------

## 3. CEIDG API v3 (Hurtownia Danych CEIDG)

- Prod `https://dane.biznes.gov.pl/api/ceidg/v3/`; test `https://test-dane.biznes.gov.pl/api/ceidg/v3/` (per v3 integrator docs; separate, needs its own token [R]). v2 (`.../v2/`) still exists (v2 integrator PDF v3.0, v3 PDF v1.0/1.4); old SOAP/"DataStore" API is legacy. Docs: pliki.biznes.gov.pl/akademia (HD CEIDG - API v3 ...), akademia.biznes.gov.pl/portal/004856.
- Auth: `Authorization: Bearer <JWT>`; get it by logging in to biznes.gov.pl, then dane.biznes.gov.pl -> "Dane po API" -> apply for integrator access / generate key (token e-mailed / shown in the portal). Token is long-lived but can be revoked; 401 => regenerate. Anonymous access not possible.
- Limits (v1.4 docs, via tadek24/firmy-crm): **1000 requests / 60 min per token**, clients keep >=3.6 s spacing; 429 (also 403 seen) with `Retry-After`; maintenance windows return a non-JSON "Przerwa..." HTML body. `limit` max 25 (docs example 50, prod validates 25), `page` is 0-based; `/firma?ids=` max 25 ids per call in v3 (hidden limit of 5 observed by one scraper - halve the batch on a validation error). `links.next/first/last/self` for paging, `count` = total.
- Endpoints: `GET /firmy` (short list: filters `nip, regon, nazwa, miasto, wojewodztwo, powiat, gmina, ulica, budynek, lokal, kod, nazwisko, imie, pkd, status, nip_sc, regon_sc, dataod, datado` - parameters repeatable arrays), `GET /firma?nip=|regon=|ids=` and `GET /firma/{id}` (full record), `GET /zmiana?dataod&datado` (ids changed), `GET /raporty`, `/raport/{id}` (ZIP).
- Response: list `{firmy:[...], count, links{first,last,next,prev,self}, properties{...}}`; detail `{firma:[ {...} ], properties}` (array even for one). **Note:** NIP lookups of non-existent firms return `firma` missing/empty (204 is possible: treat as not found).
- Record fields (v2 OpenAPI, v3 additions marked): `id, nazwa, link, status, numerStatusu, wlasciciel{imie,nazwisko,nip,regon,nipUchylony,nipUniewaznienie}, adresDzialalnosci{ulica,budynek,lokal,miasto,wojewodztwo,powiat,gmina,kod,kraj,terc,simc,ulic,skrytkaPocztowa,adresat,opisNietypowegoMiejsca}, adresKorespondencyjny, adresyDzialalnosciDodatkowe[], dataRozpoczecia, dataZawieszenia, dataWznowienia, dataZakonczenia, dataWykreslenia, dataZgonu, podstawyPrawneWykreslenia[], pkd[], pkdGlowny, email, telefon, www, adresDoreczenElektronicznych, wspolnoscMajatkowa, spolki[{nip,regon,dataZawieszenia}], obywatelstwa[{kraj,symbol}], kwalifikacjeZawodowe[], ograniczenia[], ograniczeniaZdolnosciPrawnej[], upadlosci[], uprawnienia[], zakazy[], zarzadcaSukcesyjny, zarzadSukcesyjnyDataUstanowienia/Wygasniecia`. v3: `pkdGlowny` is an object `{kod,nazwa}` (v2: string); the code of `pkd[]` items in v3 and a `rokPkd` field are [R]. Dates ISO `yyyy-MM-dd`.
- `status` enum: `AKTYWNY, WYKRESLONY, ZAWIESZONY, OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI, WYLACZNIE_W_FORMIE_SPOLKI`. Errors: JSON `{code, message}` with `code` e.g. `NIEPOPRAWNY_NUMER_NIP, NIEPOPRAWNY_NUMER_REGON, BRAK_PARAMETROW_ZAPYTANIA, NIEPOPRAWNY_NUMER_STRONY, NIEPOPRAWNY_ROZMIAR_STRONY, NIEPOPRAWNA_ILOSC_IDENTYFIKATOROW, NIEPOPRAWNY_STATUS, NIEPOPRAWNY_ZAKRES_DAT, ...` (HTTP 400; 403 forbidden; 503 maintenance; 204 empty).
- Only natural-person businesses (JDG, sp. cywilna partners) - companies (sp. z o.o., S.A.) are NOT in CEIDG.
- Swagger/OpenAPI: the official file is published with the integrator package (not retrievable here); community-corrected v2 spec: github.com/krj29b/CEIDGv2-OpenAPI `openAPIv2.yml`.
Fixtures `ceidg/*.json` are RECONSTRUCTED (synthetic data, v2-schema + v3 evidence).

---------------------------------------------------------------------------

## 4. MF Biała Lista VAT (Rejestr Podatników VAT, API spec v1.3.0)

- Prod `https://wl-api.mf.gov.pl`, test `https://wl-test.mf.gov.pl` (port 9091 path `/wykaz-podatnikow/` seen in C# client). No auth, GET only, JSON.
- Endpoints (`date=YYYY-MM-DD` required in practice, default today, may be in the past <=5 working days [R]): `/api/search/nip/{nip}`, `/api/search/nips/{nip1,nip2,...}` (<=30), `/api/search/regon/{regon}`, `/api/search/regons/{...}`, `/api/search/bank-account/{nrb}`, `/api/search/bank-accounts/{...}`, `/api/check/nip/{nip}/bank-account/{nrb}`, `/api/check/regon/{regon}/bank-account/{nrb}`.
- Response (search single): `{result:{subject:{...}, requestId, requestDateTime("dd-MM-yyyy HH:mm:ss")}}`; multi: `result.subjects[]` + `requestId`/`requestDateTime`; bank-account search returns `subjects[]` holding the account; check returns `{result:{accountAssigned:"TAK"|"NIE", requestId, requestDateTime}}`.
- `subject` fields [V names]: `name, nip, statusVat, regon, pesel, krs, residenceAddress, workingAddress, representatives[], authorizedClerks[], partners[] (items: companyName, firstName, lastName, pesel, nip), registrationLegalDate, registrationDenialDate, registrationDenialBasis, restorationDate, restorationBasis, removalDate, removalBasis, accountNumbers[], hasVirtualAccounts`. `statusVat` strings: `Czynny`, `Zwolniony`, `Niezarejestrowany` (+ `Wykreślony`-type states are expressed through removalDate [R]). No match => `subject: null` (HTTP 200) [R]. `pesel` etc. are masked/omitted for companies.
- Errors: HTTP 400 `{code,message}` (C# client models `exception:{code,message}`; handle both). Known: `WL-100` unexpected server error, `WL-111` invalid bank account (26 digits but bad NRB checksum), `WL-112` NIP empty, `WL-115` invalid NIP, `WL-117` (name too short, other API version), `WL-190` bad request, `WL-191` request limit for this IP exhausted for today (text: "Limit żądań dla tego adresu IP został na dziś wyczerpany").
- **Limits (since 2025-01-01) [D, mcp-wl-vat]: `search`: 100 requests/day per IP, <=30 entities per request; `check`: 5000 entities/day; over the limit the IP is blocked until midnight** (also for the podatki.gov.pl UI). Cloudflare egress IPs are shared => throttle hard, prefer `check` where possible, cache (statuses change rarely), and consider the daily "plik płaski" (flat file, SHA-hashed NIP+account) from MF for bulk. Validate NIP/NRB checksums locally before calling.
Fixtures `whitelist/*.json` RECONSTRUCTED (ORLEN identifiers real).

---------------------------------------------------------------------------

## 5. EU VIES REST

- Base `https://ec.europa.eu/taxation_customs/vies/rest-api/`; swagger `https://ec.europa.eu/assets/taxud/vow-information/swagger_publicVAT.yaml`. No auth. Test service `.../check-vat-test-service` (POST).
- `GET /ms/{CC}/vat/{number}` (CC = ISO code, `EL` for Greece, `XI` for N. Ireland; number without country prefix, no spaces/dots/hyphens) -> `{isValid, requestDate, userError, name, address, requestIdentifier, originalVatNumber, vatNumber, viesApproximate{name,street,postalCode,city,companyType,matchName,matchStreet,matchPostalCode,matchCity,matchCompanyType}}`.
- `POST /check-vat-number` JSON `{countryCode, vatNumber, requesterMemberStateCode, requesterNumber, traderName, traderStreet, traderPostalCode, traderCity, traderCompanyType}` -> `{countryCode, vatNumber, requestDate, valid, requestIdentifier, name, address, trader*...}`; `requestIdentifier` (consultation number, proof for tax authorities) only if requester supplied. Error body in this variant: `{"actionSucceed":false,"errorWrappers":[{"error":"INVALID_INPUT","message":"..."}]}`.
- `userError`/`error` values: `VALID`, `INVALID`, `INVALID_INPUT`, `INVALID_REQUESTER_INFO`, `SERVICE_UNAVAILABLE`, `MS_UNAVAILABLE`, `TIMEOUT`, `VAT_BLOCKED`, `IP_BLOCKED`, `GLOBAL_MAX_CONCURRENT_REQ`(`_TIME`), `MS_MAX_CONCURRENT_REQ`(`_TIME`). Transient (do not cache, retry later): SERVICE_UNAVAILABLE, MS_UNAVAILABLE, TIMEOUT, *_MAX_CONCURRENT_REQ. They arrive as HTTP 200 + `isValid:false`, so treat only `userError==="INVALID"` as a real negative.
- Quirks: PL (like DE) returns `---` for name/address; PL downtime windows are frequent; per-member-state concurrency throttling; no published numeric rate limit (be polite: <=1-2 rps, retry once after 1 s); dates are ISO UTC.
Fixtures `vies/*.json` RECONSTRUCTED from swagger names + client test data.

---------------------------------------------------------------------------

## 6. Sources
GUS: github.com/pawel-id/bir1 (src/templates, src/error.ts, src/types.ts, test/bir.ts), github.com/orkanap/regonapi (gusdoc/*.txt, reports.go), github.com/rolzwy7/RegonAPI (consts), github.com/johnzuk/GusApi (tests/resources/*, ReportTypes.php), github.com/espago/gus_bir1 README. KRS: github.com/kordybordy/KRS, soba-labs/krs-mcp, apiotrowski-afk/krs-verify, tadek24/firmy-crm. CEIDG: krj29b/CEIDGv2-OpenAPI, OGGEE61/CEIDG_sawmills, B2Trust-Infrastructure/registry-api-examples, tadek24/firmy-crm. WL: m4rcelpl/WykazPodatnikow, pwasniowski/mcp-wl-vat, M8T-Jacob/polish-registry. VIES: rocketfellows/vies-vat-validation-php-sdk-rest, itaibo/vies-checker, omisai-tech/*vies-rest.

## 7. Open items to verify with a live call (outside the sandbox)
1. REGON: exact HTTP Content-Type/Accept needs, and whether Result is entity-escaped (assumed) vs CDATA; prod quota and IP allow-list; sid idle timeout.
2. KRS: real OdpisAktualny sample incl. wykreślony placement of `dataWykreslenia`, 404 body, Biuletyn response schema.
3. CEIDG v3: `pkd[]` item shape, short-view field list of `/firmy`, test-environment token.
4. WL: exact not-found response and error JSON nesting.
5. VIES: precise POST response key list.
