# Polish Energy Optimizer (PEO)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/www121212/Polish-Energy-Optimizer?include_prereleases)](https://github.com/www121212/Polish-Energy-Optimizer/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![HA 2024.1+](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)

> ⚠️ **Projekt eksperymentalny** — integracja zaprojektowana i napisana przez AI (Claude/Kiro). Wymaga testowania w środowisku produkcyjnym.

Kompleksowa integracja Home Assistant do **optymalizacji kosztów energii** na polskim rynku. Łączy ceny spot RCE PSE, polskie taryfy, ładowanie EV, load shifting, optymalizację PV i porównywanie taryf w jednym narzędziu.

---

## ✨ Funkcje

| Moduł | Opis |
|-------|------|
| 📊 **Ceny RCE PSE** | Aktualne i przyszłe ceny spot z Rynku Dnia Następnego |
| 💰 **Kalkulator taryf** | Pełny koszt kWh z 6 składnikami opłat (G11–G13, C11–C23) |
| 🚗 **Ładowanie EV** | Optymalizacja kosztów z LP solverem, do 4 pojazdów |
| ⚡ **Load Shifting** | Automatyczne sterowanie odbiornikami wg progów cenowych |
| ☀️ **Optymalizator PV** | Strategia baterii, prognoza produkcji, autokonsumpcja |
| 📈 **Porównanie taryf** | Rekomendacja optymalnej taryfy na podstawie zużycia |

---

## 📦 Instalacja

### HACS (zalecana)

1. Otwórz **HACS** → **Integracje** → menu ⋮ → **Repozytoria niestandardowe**
2. Dodaj URL: `https://github.com/www121212/Polish-Energy-Optimizer`
3. Zainstaluj **"Polish Energy Optimizer"**
4. Uruchom ponownie Home Assistant
5. **Ustawienia** → **Integracje** → **+ Dodaj** → szukaj "Polish Energy Optimizer"

### Ręcznie

Skopiuj folder `custom_components/peo/` do `/config/custom_components/peo/` i zrestartuj HA.

📖 [Szczegółowa instrukcja instalacji](docs/INSTALLATION.md)

---

## ⚙️ Konfiguracja

Cała konfiguracja przez interfejs graficzny — **bez YAML**. Kreator prowadzi krok po kroku:

1. **Wybór modułów** — co chcesz optymalizować
2. **Taryfa** — operator OSD + typ taryfy (stawki ładowane automatycznie z URE)
3. **EV** *(opcjonalnie)* — pojazd, ładowarka, strategia
4. **Odbiorniki** *(opcjonalnie)* — bojler, pompa ciepła, klimatyzacja
5. **PV** *(opcjonalnie)* — prognoza solarna, bateria, inwerter

Dostępny **tryb szybkiej konfiguracji** (G12 + EV + bojler CWU) — wystarczy podać encję SoC pojazdu.

📖 [Szczegółowa dokumentacja konfiguracji](docs/CONFIGURATION.md)

---

## 🔌 Obsługiwane urządzenia

### Operatorzy OSD
Tauron · PGE · Enea · Energa · innogy Stoen

### Taryfy
G11 · G12 · G12w · G12r · **G13** · C11 · C12a · C12b · C21 · C22a · C22b · C23

### Ładowarki EV
OCPP 1.6/2.0 · Tesla Wall Connector · Wallbox Pulsar · OpenEVSE

### Inwertery PV
SolarEdge · Huawei Solar · GoodWe · Fronius · SMA

### Prognozy solarne
Solcast · Forecast.Solar · OpenWeatherMap Solar

---

## 📊 Encje

### Sensory
| Encja | Opis |
|-------|------|
| `sensor.peo_current_price` | Bieżąca cena RCE (PLN/kWh) |
| `sensor.peo_current_cost` | Pełny koszt z opłatami (PLN/kWh) |
| `sensor.peo_daily_savings` | Dzienne oszczędności (PLN) |
| `sensor.peo_monthly_savings` | Miesięczne oszczędności (PLN) |
| `sensor.peo_pv_forecast_today` | Prognoza PV na dziś (kWh) |
| `sensor.peo_recommended_tariff` | Rekomendowana taryfa |

### Binary sensory
| Encja | ON gdy... |
|-------|-----------|
| `binary_sensor.peo_cheap_window` | Cena < skonfigurowany próg |
| `binary_sensor.peo_ev_charging_active` | Trwa ładowanie EV |
| `binary_sensor.peo_pv_surplus_active` | Produkcja PV > zużycie |

### Usługi
```yaml
peo.start_ev_charging      # Rozpocznij ładowanie EV
peo.stop_ev_charging       # Zatrzymaj ładowanie EV
peo.set_load_threshold     # Zmień próg cenowy odbiornika
peo.force_load_on          # Wymuś włączenie odbiornika
peo.force_load_off         # Wymuś wyłączenie odbiornika
peo.recalculate_schedule   # Przelicz wszystkie harmonogramy
```

📖 [Pełna dokumentacja użytkowania](docs/USAGE.md)

---

## 🔒 Bezpieczeństwo

- **Failsafe** — heartbeat co 60s, przełączenie w tryb domyślny po 5 min bez odpowiedzi
- **Limity mocy** — nigdy nie przekracza mocy przyłączeniowej ani limitów ładowarki
- **Temperatura EV** — pauza ładowania przy przegrzaniu baterii
- **Rate limiting** — max 60 żądań/h per endpoint API
- **Szyfrowanie** — dane uwierzytelniające przez mechanizm HA credentials

---

## 🏗️ Architektura

```
┌─────────────────────────────────────────────────┐
│              Home Assistant Event Bus             │
├─────────────────────────────────────────────────┤
│  Moduł Cen  │ Kalkulator │ Harmonogramownik EV  │
│  (RCE PSE)  │   Taryf    │   (LP Solver)        │
├─────────────┼────────────┼──────────────────────┤
│  Menedżer   │Optymalizator│   Analizator        │
│  Obciążeń   │  PV+Bateria │    Taryf           │
└─────────────────────────────────────────────────┘
```

- Modularna architektura z niezależnymi `DataUpdateCoordinator`
- Komunikacja event-driven (brak zależności cyklicznych)
- LP solver (`scipy.optimize.linprog`) do optymalizacji harmonogramów
- Property-based testing (Hypothesis) — 32 właściwości, 800+ testów

---

## 📖 Dokumentacja

| Dokument | Opis |
|----------|------|
| [Instalacja](docs/INSTALLATION.md) | Krok po kroku: HACS, ręcznie, weryfikacja |
| [Konfiguracja](docs/CONFIGURATION.md) | Każdy parametr Config Flow z przykładami |
| [Użytkowanie](docs/USAGE.md) | Codzienne działanie, automatyzacje, FAQ |

---

## 🤝 Wkład

Projekt jest w fazie eksperymentalnej. Zgłaszaj problemy przez [Issues](https://github.com/www121212/Polish-Energy-Optimizer/issues).

---

## 📄 Licencja

[MIT](LICENSE)

---

## 👤 Autorzy

- **Specyfikacja i nadzór:** Wojciech Misiaszek
- **Implementacja:** AI (Claude/Kiro)

*Cały kod, testy i dokumentacja wygenerowane przez AI na podstawie specyfikacji opracowanej wspólnie z użytkownikiem.*
