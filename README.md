# 🇵🇱 Polish Energy Optimizer (PEO)

**Niestandardowa integracja Home Assistant do optymalizacji kosztów energii na polskim rynku.**

> ⚠️ **Uwaga:** Ta integracja została w całości zaprojektowana i napisana przez AI (Claude/Kiro) na podstawie specyfikacji przygotowanej wspólnie z użytkownikiem. Kod wymaga przeglądu i testowania w środowisku produkcyjnym przed wdrożeniem.

---

## Opis

Polish Energy Optimizer (PEO) to kompleksowa integracja Home Assistant (kompatybilna z HACS), zaprojektowana specjalnie dla polskiego rynku energii. Łączy w jednym narzędziu:

- 📊 **Pobieranie cen spot z RCE PSE** — aktualne i przyszłe ceny energii z Rynku Dnia Następnego
- 💰 **Pełna obsługa polskich taryf** — G11, G12, G12w, G12r, G13, C11–C23 z uwzględnieniem wszystkich składników opłat i 5 operatorów OSD
- 🚗 **Inteligentne ładowanie EV** — optymalizacja kosztów z LP solverem, obsługa wielu pojazdów, OCPP/Tesla/Wallbox/OpenEVSE
- ⚡ **Przesuwanie obciążeń (Load Shifting)** — automatyczne sterowanie odbiornikami odraczalnymi wg progów cenowych
- ☀️ **Optymalizacja PV + bateria** — strategia pracy magazynu energii, prognoza produkcji, autokonsumpcja
- 📈 **Porównywanie taryf** — rekomendacja optymalnej taryfy na podstawie rzeczywistego zużycia

## Dlaczego PEO?

Istniejące rozwiązania oferują jedynie fragmentaryczne funkcjonalności:

| Rozwiązanie | Ceny | Taryfy | Sterowanie EV | Load Shifting | PV | UI po polsku |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| RCE PSE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Energy Hub Poland | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| EMHASS | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| **PEO** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Obsługiwane taryfy

| Taryfa | Typ | Strefy |
|--------|-----|--------|
| G11 | Jednostrefowa | jednolita |
| G12 | Dwustrefowa | szczyt / pozaszczyt |
| G12w | Dwustrefowa + weekend | szczyt / pozaszczyt / weekend |
| G12r | Dynamiczna (RCE) | szczyt / pozaszczyt |
| G13 | Trzystrefowa | szczyt poranny / szczyt popołudniowy / pozaszczyt |
| C11–C23 | Biznesowe | różne konfiguracje stref |

## Obsługiwani operatorzy OSD

- Tauron Dystrybucja
- PGE Dystrybucja
- Enea Operator
- Energa Operator
- innogy Stoen Operator

## Wymagania

- Home Assistant 2024.1.0+
- Python 3.12+
- HACS (do instalacji)

## Instalacja

1. Dodaj repozytorium do HACS
2. Zainstaluj integrację "Polish Energy Optimizer"
3. Przejdź do Ustawienia → Integracje → Dodaj integrację → "Polish Energy Optimizer"
4. Postępuj zgodnie z kreatorem konfiguracji (w języku polskim)

## Konfiguracja

Cała konfiguracja odbywa się przez interfejs graficzny Home Assistant — bez edycji YAML.

### Szybka konfiguracja

Tryb "szybkiej konfiguracji" z domyślnymi wartościami: G12 + EV + bojler CWU.

### Konfiguracja krok po kroku

1. **Wybór modułów** — które funkcje chcesz aktywować
2. **Taryfa i OSD** — wybór operatora, taryfy, stawek
3. **EV** (opcjonalnie) — pojazdy, ładowarki, strategie
4. **Odbiorniki** (opcjonalnie) — bojler, pompa ciepła, klimatyzacja
5. **PV** (opcjonalnie) — prognoza solarna, bateria, inwerter

## Architektura

```
┌─────────────────────────────────────────────────────┐
│                   Home Assistant                      │
├─────────────────────────────────────────────────────┤
│  PEO Integration                                     │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │Moduł_Cen │ │Kalkulator    │ │Harmonogramownik│  │
│  │(RCE PSE) │ │Taryf         │ │EV (LP Solver)  │  │
│  └──────────┘ └──────────────┘ └────────────────┘  │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │Menedżer  │ │Optymalizator │ │Analizator      │  │
│  │Obciążeń  │ │PV + Bateria  │ │Taryf           │  │
│  └──────────┘ └──────────────┘ └────────────────┘  │
├─────────────────────────────────────────────────────┤
│  Event Bus: peo_prices_updated, peo_schedule_updated │
└─────────────────────────────────────────────────────┘
```

## Sensory i encje

### Sensory cenowe
- `sensor.peo_current_price` — bieżąca cena PLN/kWh
- `sensor.peo_daily_min_price` — minimalna cena dnia
- `sensor.peo_daily_max_price` — maksymalna cena dnia
- `sensor.peo_daily_avg_price` — średnia cena dnia

### Sensory taryfowe
- `sensor.peo_current_cost` — bieżący koszt PLN/kWh (z wszystkimi opłatami)
- `sensor.peo_current_zone` — aktywna strefa taryfowa

### Sensory EV
- `sensor.peo_ev_schedule` — harmonogram ładowania
- `sensor.peo_ev_estimated_cost` — szacowany koszt sesji

### Sensory PV
- `sensor.peo_pv_forecast_today` — prognoza produkcji PV (kWh)
- `sensor.peo_battery_mode` — rekomendowany tryb baterii
- `sensor.peo_estimated_savings` — szacowane dzienne oszczędności

### Binary sensory
- `binary_sensor.peo_cheap_window` — czy trwa tanie okno
- `binary_sensor.peo_ev_charging` — czy EV się ładuje
- `binary_sensor.peo_pv_surplus` — czy jest nadwyżka PV

## Usługi (Services)

- `peo.start_ev_charging` — rozpocznij ładowanie EV
- `peo.stop_ev_charging` — zatrzymaj ładowanie EV
- `peo.set_load_threshold` — ustaw próg cenowy odbiornika
- `peo.force_load_on` / `peo.force_load_off` — wymuś stan odbiornika
- `peo.recalculate_schedule` — przelicz harmonogramy

## Zdarzenia (Events)

- `peo_prices_updated` — nowe ceny pobrane
- `peo_charging_started` / `peo_charging_completed` — sesja ładowania
- `peo_load_shifted` — przesunięcie obciążenia
- `peo_price_threshold_crossed` — przekroczenie progu cenowego
- `peo_schedule_updated` — harmonogram zaktualizowany

## Bezpieczeństwo

- 🔒 Mechanizm failsafe (heartbeat 60s, timeout 5min)
- 🌡️ Monitoring temperatury baterii EV
- ⚡ Respektowanie limitów mocy przyłączeniowej
- 🔄 Retry logic (3 próby, 10s interwały) dla komend sterujących
- 🔐 Szyfrowanie danych uwierzytelniających (HA credentials)
- 📊 Rate limiting API (60 req/h per endpoint)

## Technologia

- Python 3.12+ z asyncio
- scipy.optimize.linprog (LP solver)
- aiohttp (klient HTTP)
- Hypothesis (property-based testing)
- Home Assistant DataUpdateCoordinator pattern
- Event-driven architecture (HA Event Bus)

## Status projektu

🚧 **W trakcie rozwoju** — integracja jest w fazie implementacji.

Zaimplementowane moduły:
- [x] Infrastruktura (modele, stałe, walidatory)
- [x] Moduł cen (RCE API, walidacja, historia, koordynator)
- [x] Kalkulator taryf (strefy, koszty, koordynator)
- [x] Harmonogramownik EV (LP solver, adaptery, sesje, bezpieczeństwo)
- [x] Menedżer obciążeń (progi, runtime, budżet mocy)
- [x] Optymalizator PV (nadwyżka, strategia baterii, koordynator)
- [x] Analizator taryf (porównanie, ranking, rekomendacje)
- [ ] Monitoring i oszczędności
- [ ] Config Flow i Options Flow
- [ ] Cykl życia integracji HA
- [ ] Usługi i zdarzenia HA
- [ ] Logowanie i diagnostyka

## Testy

Projekt wykorzystuje property-based testing (Hypothesis) do weryfikacji poprawności:

- 32 właściwości (properties) zdefiniowane w specyfikacji
- 600+ testów jednostkowych i PBT
- Pokrycie wszystkich modułów biznesowych

```bash
# Uruchomienie testów
pip install pytest pytest-asyncio hypothesis scipy aiohttp
pytest tests/ -v
```

## Licencja

MIT

## Autorzy

- Specyfikacja i nadzór: Wojciech Misiaszek
- Implementacja: AI (Claude/Kiro) — kod wygenerowany automatycznie na podstawie specyfikacji

---

*Ta integracja została stworzona jako eksperyment w AI-assisted development. Cały kod źródłowy, testy i dokumentacja zostały wygenerowane przez AI na podstawie wymagań i designu opracowanych wspólnie z użytkownikiem.*
