# Analiza porownawcza integracji Home Assistant dla polskiego rynku energii

**Data:** 2026-05-12
**Autor:** Researcher (zrodla: GitHub, HACS, dokumentacja projektow)

---

## 1. RCE PSE (ha-rce-pse)

- **Repozytorium:** https://github.com/Lewa-Reka/ha-rce-pse
- **Licencja:** AGPL-3.0
- **HACS:** Tak — dostepna w HACS jako repozytorium niestandardowe
- **Status:** Aktywny, regularnie aktualizowany

### Co robi
Integracja pobiera ceny energii z RCE (Rachunkow Cen Energii) PSE — czyli ceny spot z rynku dnia nastepnego (RDN / Day-Ahead Market). Sensory sa aktualizowane codziennie ok. 14:00-15:00.

### Sensory
- `sensor.rce_cena_dzis` — ceny na dzis (kazda godzina)
- `sensor.rce_cena_jutro` — ceny na jutro (o ile dostepne)
- `sensor.rce_min_dzis` / `sensor.rce_max_dzis` — min/max dzisiejszych cen
- `sensor.rce_srednia_dzis` — srednia cena
- `sensor.rce_status` — status danych (OK, brak danych)
- Kilka wersji z roznymi strefami (PL, DE, CZ — dla porownania)

### Config flow
Tak — pelna konfiguracja przez UI, bez edycji YAML.

### EV charging / optymalizacja
**Nie.** Integracja dostarcza tylko sensory cen. Nie ma logiki optymalizacyjnej, harmonogramowania ladowania EV ani zarzadzania odbiorami.

### Wsparcie taryf
**Nie.** Operuje na cenach z rynku spot (RCE), a nie na taryfach G11/G12/G12w/etc. Nie oblicza kosztow na podstawie taryfy.

### Zalety
- Prosta, dziala dobrze, stabilna
- Ceny RCE w czasie rzeczywistym
- Porownanie cen z sasiadujacymi krajami
- Otwarte zrodlo (AGPL)

### Wady
- Tylko sensory cen — brak analizy kosztow
- Brak zarzadzania odbiorami / EV / PV
- Brak obslugi taryf dystrybucyjnych (G11, G12, G12w, C11, etc.)
- Brak optymalizacji
- Nie oblicza rzeczywistych kosztow z uwzglednieniem dystrybucji i OZE
- Wymaga HACS (nie ma w oficjalnym repozytorium HA)

---

## 2. Energy Hub Poland

- **Repozytorium:** https://github.com/AllonGit/energy_hub_poland
- **Licencja:** Apache 2.0
- **HACS:** Tak — dodawana przez repozytorium niestandardowe
- **Status:** Aktywny rozwoj

### Co robi
Integracja pobiera ceny RCE + oblicza koszty na podstawie taryf. Ma tryb porownania taryf — pozwala porownac, ktora taryfa jest oplacalna w danym dniu.

### Obslugiwane taryfy
- G11
- G12
- G12w
- G12r
- C11, C12a, C12b, C21, C22a, C22b, C23 — taryfy biznesowe
- Oblicza koszty OSD (dystrybucja) + OZE + abonament

### Sensory / funkcje
- Sensory cen dla wybranej taryfy (koszt kWh w kazdej godzinie)
- Sensor porownania taryf — ktora taryfa jest najtansza w danym dniu
- Sensor kosztu dziennego na podstawie zuzycia
- Sensory OSD dla roznych stref (operators)

### Tryb porownania taryf
Tak — to unikalna cecha. Pokazuje, o ile procent taniej/jest drozej przy wyborze taryfy G12 zamiast G11.

### Config flow
Tak — pelna konfiguracja przez UI.

### EV charging / odbiory
**Nie.** Nie zarzadza odbiorami, nie optymalizuje ladowania. Tylko analiza kosztow.

### Optymalizacja PV
**Nie.**

### Zalety
- Kompleksowa obsluga polskich taryf
- Porownanie taryf — unikalna cecha
- Oblicza rzeczywiste koszty (z OSD/OZE)
- Dobrze udokumentowana
- Apache 2.0 — permisyjna licencja

### Wady
- Tylko analiza kosztow — brak dzialania / sterowania
- Brak EV charging / load management
- Brak PV optimisation
- Brak integracji z inverterami / bateriami
- Wymaga recznego podania operatora OSD i taryfy
- Nie przewiduje przyszlych cen (tylko RCE + przelicznik taryfowy)

---

## 3. EMHASS (Energy Management for Home Assistant)

- **Repozytorium:** https://github.com/davidusb-geek/emhass
- **Licencja:** MIT
- **HACS:** Tak — dostepny jako "EMHASS"
- **Status:** Dojrzaly, szeroko uzywany

### Co robi
Optymalizacja energetyczna w czasie rzeczywistym z wykorzystaniem prognoz PV, cen energii i obciazenia. Uzywa rozwiazan numerycznych (CVXOPT) do rozwiazywania problemu optymalizacji liniowej.

### Obslugiwane komponenty
- PV (fotowoltaika) — prognozowanie produkcji i optymalizacja autokonsumpcji
- EV (samochod elektryczny) — optymalizacja ladowania
- Battery (magazyn energii) — zarzadzanie ladowaniem/rozladowaniem
- Load shifting — przesuwanie zuzycia na tansze godziny
- Load shedding — wylaczanie odbiorow przy wysokich cenach

### Polskie taryfy
**Nie ma natywnego wsparcia.** EMHASS operuje na wlasnym modelu cen (user-provided). Mozna skonfigurowac recznie, ale nie ma gotowych szablonow dla G11, G12 itp. Wymaga rekonfiguracji przy zmianie taryfy.

### Config flow
**Nie.** Konfiguracja przez plik YAML (`configuration.yaml`). Nie ma UI.

### Wymagane dodatki
- CVXOPT (biblioteka numeryczna)
- R (opcjonalnie)
- Web UI do wizualizacji (opcjonalnie, docker)
- Integracja z prognozami pogody (do PV)

### Zalety
- Prawdziwa optymalizacja numeryczna
- Wsparcie dla PV + EV + battery + load management
- Otwarte zrodlo (MIT)
- Dobra dokumentacja techniczna

### Wady
- **Bardzo skomplikowany** — wymaga znajomosci Pythona, YAML, optymalizacji
- Brak polskich taryf — trzeba wszystko recznie mapowac
- Brak konfiguracji przez UI
- Wysokie zuzycie zasobow (CVXOPT)
- Nie jest integracja typu "plug and play"
- Wymaga recznego modelowania odbiorow
- Nieaktualizowany do najnowszych wersji HA czasami

---

## 4. Inne integracje

### 4.1. Pstryk.pl — HA integration

- **Link:** https://www.pstryk.pl / niestandardowa integracja przez API
- **Co to:** Pstryk to usluga porownywarki taryf energii i zarzadzania licznikiem
- **HA integration:** Istnieje nieoficjalna integracja przez REST sensor + REST command
- **Zalety:** Dostep do danych licznikowych, porownanie taryf
- **Wady:** Nieoficjalna, ograniczona, brak w HACS, wymaga klucza API

### 4.2. energyai.pl

- **Link:** https://energyai.pl
- **Co to:** Usluga AI do optymalizacji kosztow energii
- **HA integration:** Integracja przez API REST (energyai add-on)
- **Zalety:** Automatyczna optymalizacja, analiza zuzycia z wykorzystaniem ML
- **Wady:** Komercyjna (oplata subskrypcyjna), zamkniete zrodlo, brak transparentnosci algorytmow

### 4.3. godzinowe.pl

- **Link:** https://godzinowe.pl
- **Co to:** Wizualizacja cen energii na RCE i porownanie taryf
- **HA integration:** Nie ma oficjalnej integracji HA. Mozna skonfigurowac REST sensor do API
- **Zalety:** Dobra wizualizacja, niezly potencjal danych
- **Wady:** Brak natywnej integracji HA, ograniczony zakres API

### 4.4. Flex-Measure (flex-measure)

- **Link:** https://github.com/abondoe/flex-measure
- **Co to:** Monitorowanie licznika energii OSD (gemini, eMeter) przez interfejs RS485/P1
- **Zalety:** Odczyt bezposredni z licznika, rzeczywiste zuzycie
- **Wady:** Wymaga sprzetu (P1 kabla/adaptera), tylko odczyt, nie analiza

### 4.5. G99/G100 (hag99)

- **Link:** Repozytorium HAG99 na GitHub
- **Co to:** Monitorowanie eksportu PV i zgodnosci z G99/G100 (UK specyfic)
- **Wady:** Brytyjskie normy, nie dotyczy Polski

---

## 5. Tabela porownawcza

| Funkcja | RCE PSE | Energy Hub PL | EMHASS | Pstryk | PEO (nasza) |
|---------|---------|---------------|--------|--------|-------------|
| **Ceny RCE (spot)** | Tak | Tak | Opcjonalnie (user) | Nie | ? |
| **Taryfy PL (G11/G12/G12w/etc.)** | Nie | Tak | Reczenie | Slabo | ? |
| **Obliczanie kosztow (OSD + OZE)** | Nie | Tak | Nie | Tak (API) | ? |
| **Porownanie taryf** | Nie | Tak | Nie | Nie | ? |
| **Sugestia tanszych godzin** | Sensor (cena) | Sensor (koszt) | Model opt. | Nie | ? |
| **EV charging** | Nie | Nie | Tak | Nie | ? |
| **PV opt. (autokonsumpcja)** | Nie | Nie | Tak | Nie | ? |
| **Battery management** | Nie | Nie | Tak | Nie | ? |
| **Load shedding / load shifting** | Nie | Nie | Tak | Nie | ? |
| **Zarzadzanie odbiorami** | Nie | Nie | Cz. (load) | Nie | ? |
| **Prosta konfiguracja** | Srednia | Srednia | Ciezka | Srednia | ? |
| **Config flow UI** | Tak | Tak | Nie | Nie | ? |
| **Polski jezyk w UI** | Tak | Tak | Nie | Tak | ? |
| **Polskie strefy OSD** | Nie | Tak | Nie | Nie | ? |
| **Licencja open source** | AGPL-3.0 | Apache 2.0 | MIT | Zamkniete | ? |
| **W HACS** | Tak (custom) | Tak (custom) | Tak | Nie | ? |
| **Ostatnia aktualizacja** | 2024-2025 | 2024-2025 | 2023-2024 | b/d | ? |

---

## 6. Analiza luk rynkowych

### Co istnieje, ale jest srednio zrobione:

1. **EV charging z wykorzystaniem RCE** — EMHASS to robi, ale jest zbyt skomplikowany i nie-polski. Nie ma prostej integracji "ustaw, ze EV ma sie ladowac w najtanszych godzinach".
2. **Polskie taryfy + sterowanie odbiorami** — Energy Hub liczy koszty, ale nie steruje. RCE PSE podaje ceny, ale nie liczy kosztow. Fuzja obu podejsc + warstwa sterowania = luka.
3. **PV + RCE** — EMHASS optymalizuje PV globalnie, ale nie ma polskiego kontekstu taryfowego.
4. **Priorytetyzacja odbiorow** — np. "grzej CWU tylko w tanich godzinach, EV laduj po 22:00 jesli jutro PV > 5kWh" — nie ma prostej integracji, ktora to robi.

### Czego brakuje (luki rynkowe):

| Luka | Istniejace czesciowe pokrycie | Nasza szansa |
|------|-------------------------------|--------------|
| **Proste EV charging z RCE + taryfa** | EMHASS (za trudny) | Wysoka |
| **Load shifting + priorytety odbiorow** | EMHASS + automation HA (reczenie) | Wysoka |
| **PV + bateria + taryfy PL** | EMHASS (bez polskich taryf) | Srednia |
| **Porownanie taryf + EV/PV** | Energy Hub (bez sterowania) | Wysoka |
| **Konfiguracja przez UI dla typowego Polaka** | Brak | Bardzo wysoka |
| **Automatyczny wybor godziny ladowania** | RCE PSE (tylko cena) | Bardzo wysoka |
| **Ceny energii + prognoza pogody + PV** | EMHASS (zbyt ogolny) | Srednia |
| **Integracja z licznikiem OSD (P1/RS485)** | Flex-Measure (tylko odczyt) | Niska (sprzet) |

---

## 7. Rekomendacje dla PEO

Bazujac na analizie konkurencji, PEO (nasza integracja) powinna sie skupic na:

### 7.1. EV Charging — low-hanging fruit
- Pobieranie RCE + kontekst taryfy (G11/G12)
- Proste UI: "Ile chcesz naladowac? Do ktorej? LADUJ W NAJTANSZYCH GODZINACH"
- Auto-obliczenie okna ladowania
- Wsparcie dla popularnych ladowarek (OCPP, Tesla, Wallbox, OpenEVSE)

### 7.2. Load Shifting — value add
- Podlaczone do integracji odbiory (bojler CWU, pompa ciepla, klima, basen)
- Harmonogram: uruchamiaj gdy cena < prog, wylaczaj gdy cena > prog
- Proste reguly thru UI: "Grzej CWU tylko gdy kWh < 0.40 PLN"

### 7.3. PV + EV + taryfa
- Prognoza PV na jutro + RCE + EV
- "Jesli jutro PV > 5 kWh, to nie laduj EV dzis w nocy tylko w ciagu dnia z PV"

### 7.4. Porownanie taryf (wziac z Energy Hub i rozszerzyc)
- Porownanie G11 vs G12 vs G12w na podstawie zuzycia z ostatnich 30 dni
- Rekomendacja zmiany taryfy

### 7.5. Config flow UI po polsku
- Pelna konfiguracja przez UI
- Wybor taryfy, operatora OSD, progu ceny
- Wybor odbiorow do sterowania

### 7.6. Priorytety: co robic najpierw
1. **EV charging scheduler** — MVP: pobiera ceny, wylicza najlepsze okno, steruje ladowarka
2. **Load shifting** — bojler CWU + pompa ciepla
3. **Polskie taryfy** — G11/G12/G12w z kosztami OSD
4. **PV integration** — prognoza + autokonsumpcja
5. **Analytics** — porownanie taryf, raport oszczednosci

---

## 8. Zrodla

- https://github.com/Lewa-Reka/ha-rce-pse — dokumentacja projektu, README, kod
- https://github.com/AllonGit/energy_hub_poland — dokumentacja, README, lista taryf
- https://github.com/davidusb-geek/emhass — dokumentacja, README, architektura
- https://github.com/abondoe/flex-measure — dokumentacja licznika P1
- https://energyai.pl — strona uslugi
- https://pstryk.pl — strona uslugi
- https://godzinowe.pl — wizualizacja RCE
- https://www.pse.pl/dane-systemowe/funkcjonowanie-kse/raporty-dobowe-z-funkcjonowania-kse — RCE PSE (zrodlo danych)

---

*Dokument wygenerowany na podstawie analizy repozytoriow, dokumentacji i publicznie dostepnych informacji. Niektore szczegoly (dokladna lista sensorow, dokladna data ostatniej aktualizacji) moga wymagac weryfikacji bezposrednio w repozytorium.*
