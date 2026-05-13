# Konfiguracja Polish Energy Optimizer (PEO)

## Kreator konfiguracji (Config Flow)

Cała konfiguracja odbywa się przez interfejs graficzny Home Assistant w języku polskim. Nie wymaga edycji plików YAML.

---

## Krok 1: Wybór modułów

Po dodaniu integracji pojawi się ekran wyboru modułów:

| Moduł | Opis | Wymagany |
|-------|------|----------|
| **Ceny energii** | Pobieranie cen spot z RCE PSE | Tak (domyślnie włączony) |
| **Kalkulator taryf** | Obliczanie rzeczywistego kosztu kWh | Tak (domyślnie włączony) |
| **Harmonogramownik EV** | Optymalizacja ładowania pojazdów elektrycznych | Nie |
| **Menedżer obciążeń** | Przesuwanie obciążeń (load shifting) | Nie |
| **Optymalizator PV** | Zarządzanie fotowoltaiką i baterią | Nie |
| **Analizator taryf** | Porównywanie i rekomendacja taryf | Nie |

**Musisz wybrać co najmniej jeden moduł.**

### Szybka konfiguracja

Zaznacz opcję **"Szybka konfiguracja"** aby użyć domyślnych wartości:
- Taryfa: G12 (Tauron)
- EV: podstawowa konfiguracja
- Odbiornik: bojler CWU (22:00–06:00)

Wystarczy podać tylko encję SoC pojazdu — resztę można zmienić później.

---

## Krok 2: Konfiguracja taryfy

### Operator OSD

Wybierz swojego operatora sieci dystrybucyjnej:

| Operator | Region |
|----------|--------|
| **Tauron Dystrybucja** | Małopolska, Śląsk, Dolny Śląsk, Opolszczyzna |
| **PGE Dystrybucja** | Mazowsze, Lubelszczyzna, Podlasie, Łódzkie |
| **Enea Operator** | Wielkopolska, Zachodniopomorskie, Kujawsko-Pomorskie |
| **Energa Operator** | Pomorze, Warmia i Mazury |
| **innogy Stoen Operator** | Warszawa |

### Typ taryfy

| Taryfa | Opis | Strefy |
|--------|------|--------|
| **G11** | Jednostrefowa | Jedna stawka 24/7 |
| **G12** | Dwustrefowa | Szczyt (dzień) / Pozaszczyt (noc) |
| **G12w** | Weekendowa | Szczyt / Pozaszczyt / Weekend (cały dzień) |
| **G12r** | Dynamiczna (RCE) | Cena zmienna wg rynku spot |
| **G13** | Trzystrefowa | Szczyt poranny / Szczyt popołudniowy / Pozaszczyt |
| **C11–C23** | Biznesowe | Różne konfiguracje stref |

### Stawki taryfowe

Po wyborze operatora i taryfy, stawki zostaną automatycznie załadowane z domyślnych wartości URE. Możesz je zmienić ręcznie:

| Składnik | Opis | Zakres |
|----------|------|--------|
| Cena energii | Stawka za energię elektryczną | 0–5 PLN/kWh |
| Opłata dystrybucyjna zmienna | Stawka OSD za przesył | 0–5 PLN/kWh |
| Opłata przejściowa | Opłata regulowana | 0–5 PLN/kWh |
| Opłata OZE | Opłata za odnawialne źródła | 0–5 PLN/kWh |
| Opłata mocowa | Opłata za moc | 0–5 PLN/kWh |
| Opłata kogeneracyjna | Opłata za kogenerację | 0–5 PLN/kWh |

**Skąd wziąć aktualne stawki?** Z faktury za energię elektryczną lub ze strony Twojego sprzedawcy energii.

---

## Krok 3: Konfiguracja EV (opcjonalnie)

Jeśli wybrałeś moduł EV:

### Parametry pojazdu

| Parametr | Opis | Zakres | Przykład |
|----------|------|--------|----------|
| Nazwa pojazdu | Dowolna nazwa | tekst | "Tesla Model 3" |
| Pojemność baterii | Pojemność akumulatora | 1–200 kWh | 60 |
| Maks. moc ładowania | Limit mocy ładowarki/pojazdu | 0–100 kW | 11 |
| Min. moc ładowania | Minimalna moc (poniżej nie ładuje) | 0–100 kW | 1.4 |
| Encja SoC | Sensor HA z poziomem naładowania | entity_id | `sensor.tesla_soc` |
| Docelowy SoC | Do jakiego poziomu ładować | 10–100% | 80 |
| Strategia | Sposób planowania ładowania | wybór | "Gotowy do godziny" |

### Strategie ładowania

| Strategia | Opis | Kiedy używać |
|-----------|------|--------------|
| **Najtańsze okna** | Minimalizacja kosztu bez limitu czasu | Gdy nie zależy Ci na czasie |
| **Gotowy do godziny** | Naładowany przed deadline | Gdy musisz wyjechać o konkretnej godzinie |
| **Tylko nadwyżka PV** | Ładowanie wyłącznie z fotowoltaiki | Gdy masz PV i chcesz ładować za darmo |

### Parametry ładowarki

| Parametr | Opis | Przykład |
|----------|------|----------|
| Protokół | Typ komunikacji z ładowarką | OCPP 1.6, Tesla, Wallbox, OpenEVSE |
| Adres IP | Adres sieciowy ładowarki | 192.168.1.100 |
| Klucz API | Token uwierzytelniający (jeśli wymagany) | — |

### Moc przyłączeniowa

| Parametr | Opis | Przykład |
|----------|------|----------|
| Moc przyłączeniowa budynku | Limit mocy z sieci | 12 kW |

**Ważne:** PEO nigdy nie przekroczy tego limitu — suma ładowania EV + obciążenie budynku ≤ moc przyłączeniowa.

---

## Krok 4: Konfiguracja odbiorników (opcjonalnie)

Jeśli wybrałeś moduł Load Shifting:

### Parametry odbiornika

| Parametr | Opis | Zakres | Przykład |
|----------|------|--------|----------|
| Nazwa | Nazwa odbiornika | tekst | "Bojler CWU" |
| Encja HA | Switch/climate do sterowania | entity_id | `switch.bojler` |
| Próg włączenia | Cena poniżej której włączyć | 0.01–5 PLN/kWh | 0.35 |
| Próg wyłączenia | Cena powyżej której wyłączyć | 0.01–5 PLN/kWh | 0.55 |
| Min. dzienna praca | Ile godzin minimum musi pracować | 0.5–24 h | 2.0 |
| Maks. dzienna praca | Ile godzin maksymalnie może pracować | 0.5–24 h | 6.0 |
| Dozwolony start | Od której godziny może pracować | HH:MM | 22:00 |
| Dozwolony koniec | Do której godziny może pracować | HH:MM | 06:00 |
| Priorytet | Kolejność przy ograniczeniu mocy (1=najwyższy) | 1–16 | 1 |
| Pobór mocy | Moc odbiornika w watach | 1–100000 W | 2000 |
| Stan awaryjny | Czy włączyć w trybie failsafe | tak/nie | tak |

### Przykładowe konfiguracje odbiorników

**Bojler CWU (2 kW):**
- Próg włączenia: 0.35 PLN/kWh
- Próg wyłączenia: 0.55 PLN/kWh
- Min. praca: 2h, Maks: 6h
- Okno: 22:00–06:00
- Priorytet: 1

**Pompa ciepła (3 kW):**
- Próg włączenia: 0.40 PLN/kWh
- Próg wyłączenia: 0.60 PLN/kWh
- Min. praca: 4h, Maks: 10h
- Okno: 06:00–22:00
- Priorytet: 2

**Klimatyzacja (1.5 kW):**
- Próg włączenia: 0.30 PLN/kWh
- Próg wyłączenia: 0.50 PLN/kWh
- Min. praca: 0h, Maks: 8h
- Okno: 00:00–23:59
- Priorytet: 3

Możesz dodać do **10 odbiorników** w Config Flow (do 16 w Options Flow).

---

## Krok 5: Konfiguracja PV (opcjonalnie)

Jeśli wybrałeś moduł Optymalizator PV:

### Dostawca prognoz solarnych

| Dostawca | Opis | Wymagany klucz API |
|----------|------|-------------------|
| **Solcast** | Najdokładniejszy, wymaga rejestracji | Tak (darmowy plan: 10 req/dzień) |
| **Forecast.Solar** | Dobry, prosty w konfiguracji | Opcjonalny (lepsze limity z kluczem) |
| **OpenWeatherMap Solar** | Podstawowy, wymaga konta OWM | Tak |

### Parametry instalacji PV

| Parametr | Opis | Przykład |
|----------|------|----------|
| Moc instalacji (kWp) | Moc szczytowa paneli | 10 |
| Klucz API | Token dostawcy prognoz | (z rejestracji) |

### Parametry baterii (opcjonalne)

| Parametr | Opis | Zakres | Przykład |
|----------|------|--------|----------|
| Pojemność baterii | Pojemność magazynu energii | 0–500 kWh | 10 |
| Min. SoC bezpieczeństwa | Poniżej tego nie rozładowuje | 5–30% | 10 |
| Koszt degradacji | Koszt zużycia baterii per kWh | 0–5 PLN/kWh | 0.15 |
| Encja inwertera | Sensor mocy inwertera | entity_id | `sensor.inverter_power` |
| Encja SoC baterii | Sensor poziomu baterii | entity_id | `sensor.battery_soc` |

### Obsługiwane inwertery

PEO komunikuje się z inwerterami przez integracje HA:
- SolarEdge (przez solaredge_modbus)
- Huawei Solar
- GoodWe
- Fronius
- SMA

---

## Rekonfiguracja (Options Flow)

Po instalacji możesz zmienić dowolne ustawienia bez ponownej konfiguracji:

1. **Ustawienia** → **Urządzenia i usługi** → **PEO** → **Konfiguruj**
2. Wybierz moduł do rekonfiguracji:
   - Stawki taryfowe
   - Konfiguracja EV
   - Odbiorniki odraczalne (dodaj/usuń)
   - Konfiguracja PV

**Zmiany są stosowane natychmiast** — bez restartu Home Assistant.

---

## Encje po konfiguracji

Po zakończeniu konfiguracji PEO utworzy następujące encje:

### Sensory (sensor.*)
- `sensor.peo_current_price` — bieżąca cena RCE (PLN/kWh)
- `sensor.peo_current_cost` — bieżący pełny koszt (PLN/kWh, 4 miejsca)
- `sensor.peo_current_zone` — aktywna strefa taryfowa
- `sensor.peo_daily_savings` — dzienne oszczędności (PLN)
- `sensor.peo_monthly_savings` — miesięczne oszczędności (PLN)
- `sensor.peo_ev_schedule` — harmonogram ładowania EV
- `sensor.peo_pv_forecast_today` — prognoza PV na dziś (kWh)
- `sensor.peo_battery_mode` — rekomendowany tryb baterii
- `sensor.peo_recommended_tariff` — rekomendowana taryfa

### Binary sensory (binary_sensor.*)
- `binary_sensor.peo_cheap_window` — ON gdy tanie okno cenowe
- `binary_sensor.peo_ev_charging_active` — ON gdy EV się ładuje
- `binary_sensor.peo_pv_surplus_active` — ON gdy nadwyżka PV

### Usługi (peo.*)
- `peo.start_ev_charging` — rozpocznij ładowanie
- `peo.stop_ev_charging` — zatrzymaj ładowanie
- `peo.set_load_threshold` — zmień próg cenowy
- `peo.force_load_on` — wymuś włączenie
- `peo.force_load_off` — wymuś wyłączenie
- `peo.recalculate_schedule` — przelicz harmonogramy
