# Użytkowanie Polish Energy Optimizer (PEO)

## Codzienne działanie

Po konfiguracji PEO działa w pełni automatycznie. Nie wymaga codziennej interakcji — optymalizuje koszty energii w tle.

---

## Moduł cen energii

### Co robi automatycznie:
- Pobiera ceny z RCE PSE co 60 minut
- Po 13:30 próbuje pobrać ceny na jutro (co 15 min do sukcesu)
- Przechowuje historię 30 dni
- Wyzwala zdarzenie `peo_prices_updated` po pobraniu nowych cen

### Sensory:
| Sensor | Opis | Jednostka |
|--------|------|-----------|
| `sensor.peo_current_price` | Bieżąca cena RCE | PLN/kWh |
| Atrybut `hourly_prices` | 24 ceny godzinowe | lista |
| Atrybut `min_price` | Minimum dnia | PLN/kWh |
| Atrybut `max_price` | Maksimum dnia | PLN/kWh |
| Atrybut `avg_price` | Średnia dnia | PLN/kWh |

### Statusy danych:
| Status | Znaczenie |
|--------|-----------|
| `ok` | Dane aktualne |
| `oczekiwanie` | Po 13:30, czeka na ceny jutrzejsze |
| `dane_nieaktualne` | Nie udało się pobrać, używa starych danych |
| `brak_danych` | >24h bez sukcesu |

---

## Kalkulator taryf

### Co robi automatycznie:
- Oblicza pełny koszt kWh co 15 minut
- Wykrywa zmiany stref taryfowych (w ciągu 10s)
- Uwzględnia wszystkie 6 składników opłat

### Sensory:
| Sensor | Opis | Precyzja |
|--------|------|----------|
| `sensor.peo_current_cost` | Pełny koszt kWh | 4 miejsca po przecinku |
| Atrybut `current_zone` | Aktywna strefa | tekst |
| Atrybut `hourly_costs` | Koszty na 24h | lista |

### Przykład użycia w automatyzacji:
```yaml
trigger:
  - platform: numeric_state
    entity_id: sensor.peo_current_cost
    below: 0.40
action:
  - service: switch.turn_on
    target:
      entity_id: switch.bojler
```

---

## Harmonogramownik EV

### Co robi automatycznie:
- Oblicza optymalny harmonogram ładowania po każdej aktualizacji cen
- Wysyła komendy start/stop do ładowarki w zaplanowanych oknach
- Monitoruje SoC co 60 sekund
- Zatrzymuje ładowanie gdy SoC ≥ cel lub okno się skończyło
- Nie przekracza mocy przyłączeniowej

### Sensory per pojazd:
| Atrybut | Opis |
|---------|------|
| `charging_status` | idle / scheduled / charging / completed / deferred |
| `planned_windows` | Lista okien ładowania (JSON) |
| `estimated_cost_pln` | Szacowany koszt sesji |
| `estimated_completion` | Szacowany czas zakończenia |
| `allocated_power_kw` | Przydzielona moc |

### Usługi:
```yaml
# Rozpocznij ładowanie ręcznie
service: peo.start_ev_charging
data:
  vehicle_id: "ev_1"
  power_kw: 11.0
  target_soc: 90

# Zatrzymaj ładowanie
service: peo.stop_ev_charging
data:
  vehicle_id: "ev_1"
```

### Wiele pojazdów:
- Do 4 par pojazd-ładowarka
- Priorytetyzacja mocy (priorytet 1 = najwyższy)
- Jeśli brak mocy dla niższego priorytetu → ładowanie odroczone + powiadomienie

---

## Menedżer obciążeń (Load Shifting)

### Co robi automatycznie:
- Porównuje bieżący koszt z progami co zmianę ceny
- Włącza/wyłącza odbiorniki w ciągu 30s od zmiany ceny
- Zapewnia minimalny czas pracy (wybiera najtańsze godziny)
- Blokuje po osiągnięciu maksymalnego czasu pracy (do 00:00)
- Respektuje budżet mocy (priorytetyzacja)
- Wykrywa sterowanie ręczne (wstrzymuje automatykę)

### Sensory per odbiornik:
| Atrybut | Opis |
|---------|------|
| `status` | włączony / wyłączony / zablokowany / ręczny |
| `realized_runtime` | Zrealizowany czas pracy (h) |
| `remaining_required_runtime` | Pozostały wymagany czas (h) |
| `planned_windows` | Planowane okna pracy |

### Usługi:
```yaml
# Zmień próg cenowy
service: peo.set_load_threshold
data:
  load_id: "load_cwu"
  threshold_on: 0.30
  threshold_off: 0.50

# Wymuś włączenie na 60 minut
service: peo.force_load_on
data:
  load_id: "load_cwu"
  duration_minutes: 60

# Wymuś wyłączenie
service: peo.force_load_off
data:
  load_id: "load_cwu"
```

### Logika progów cenowych:
```
Koszt < próg_włączenia  →  WŁĄCZ
Koszt > próg_wyłączenia →  WYŁĄCZ
Pomiędzy progami        →  Utrzymaj bieżący stan (histereza)
```

---

## Optymalizator PV

### Co robi automatycznie:
- Pobiera prognozę PV co 60 minut
- Oblicza profil nadwyżki (PV - zużycie)
- Określa tryb baterii (ładowanie/rozładowanie/oczekiwanie)
- Ogranicza nocne ładowanie gdy PV > dzienne zużycie
- Nie dopuszcza do spadku SoC poniżej minimum bezpieczeństwa
- Wysyła komendy do inwertera (jeśli skonfigurowany)

### Sensory:
| Sensor | Opis |
|--------|------|
| `sensor.peo_pv_forecast_today` | Prognoza produkcji PV dziś (kWh) |
| `sensor.peo_pv_forecast_tomorrow` | Prognoza produkcji PV jutro (kWh) |
| `sensor.peo_battery_mode` | Rekomendowany tryb baterii |
| `sensor.peo_estimated_savings` | Szacowane dzienne oszczędności (PLN) |
| `sensor.peo_autoconsumption` | Prognozowana autokonsumpcja (kWh) |

### Tryby baterii:
| Tryb | Warunek | Działanie |
|------|---------|-----------|
| **Ładowanie** | Cena sieci < koszt degradacji | Ładuj z sieci |
| **Rozładowanie** | Cena sieci > koszt degradacji + PV | Rozładuj na dom |
| **Oczekiwanie** | SoC ≤ minimum LUB pomiędzy progami | Nie rób nic |

---

## Analizator taryf

### Co robi automatycznie:
- Codziennie o 01:00 analizuje ostatnie 30 dni zużycia
- Porównuje koszty dla G11, G12, G12w, G12r, G13
- Rankinguje taryfy od najtańszej
- Powiadamia gdy różnica > 10% (max raz na 7 dni)

### Sensory:
| Sensor | Opis |
|--------|------|
| `sensor.peo_recommended_tariff` | Rekomendowana taryfa |
| Atrybut `monthly_savings_pln` | Szacowana miesięczna oszczędność |
| Atrybut `rankings` | Ranking taryf (JSON) |
| Atrybut `data_days` | Ile dni danych użyto |

### Wymagania:
- Minimum 7 dni danych godzinowego zużycia
- Sensor energii w HA (np. z licznika smart)

---

## Monitoring i oszczędności

### Sensory oszczędności:
| Sensor | Opis | Reset |
|--------|------|-------|
| `sensor.peo_daily_savings` | Dzienne oszczędności | 00:00 |
| `sensor.peo_monthly_savings` | Miesięczne oszczędności | 1. dnia miesiąca |

### Powiadomienia:
- Miesięczne oszczędności > 50 PLN → powiadomienie (max raz/miesiąc)

### Diagnostyka:
- Atrybut `last_10_decisions` — ostatnie 10 decyzji optymalizacyjnych
- Każda decyzja: timestamp, opis, powód, oszczędność (PLN)

---

## Bezpieczeństwo

### Mechanizm failsafe:
- Heartbeat co 60 sekund
- Jeśli brak heartbeat przez 5 minut → przełączenie urządzeń w tryb domyślny
- Powiadomienie użytkownika o aktywacji failsafe

### Bezpieczeństwo EV:
- Monitoring temperatury baterii (pauza przy przekroczeniu progu)
- Wykrywanie utraty komunikacji z ładowarką (60s timeout)
- Nigdy nie przekracza limitów mocy ładowarki

### Rate limiting:
- Max 60 żądań/godzinę per endpoint API
- Automatyczne wstrzymanie po osiągnięciu limitu

---

## Zdarzenia (Events)

PEO wyzwala zdarzenia HA, które możesz wykorzystać w automatyzacjach:

| Zdarzenie | Kiedy | Dane |
|-----------|-------|------|
| `peo_prices_updated` | Nowe ceny pobrane | date, source |
| `peo_charging_started` | Rozpoczęto ładowanie EV | vehicle_id, power_kw |
| `peo_charging_completed` | Zakończono ładowanie EV | vehicle_id, energy_kwh, cost_pln |
| `peo_load_shifted` | Przesunięto obciążenie | load_id, action, reason |
| `peo_price_threshold_crossed` | Przekroczono próg cenowy | price, threshold, direction |
| `peo_schedule_updated` | Harmonogram przeliczony | modules |

### Przykład automatyzacji na zdarzenie:
```yaml
trigger:
  - platform: event
    event_type: peo_price_threshold_crossed
    event_data:
      direction: "below"
action:
  - service: notify.mobile_app
    data:
      message: "Tanie okno cenowe! Cena spadła poniżej progu."
```

---

## Przykładowe karty Lovelace

### Karta z bieżącą ceną:
```yaml
type: entities
entities:
  - entity: sensor.peo_current_price
    name: Cena RCE
  - entity: sensor.peo_current_cost
    name: Pełny koszt kWh
  - entity: binary_sensor.peo_cheap_window
    name: Tanie okno
  - entity: sensor.peo_daily_savings
    name: Dzienne oszczędności
```

### Karta EV:
```yaml
type: entities
entities:
  - entity: binary_sensor.peo_ev_charging_active
    name: Ładowanie aktywne
  - entity: sensor.peo_ev_schedule
    name: Harmonogram
```

### Karta PV:
```yaml
type: entities
entities:
  - entity: sensor.peo_pv_forecast_today
    name: Prognoza PV dziś
  - entity: sensor.peo_battery_mode
    name: Tryb baterii
  - entity: binary_sensor.peo_pv_surplus_active
    name: Nadwyżka PV
  - entity: sensor.peo_estimated_savings
    name: Szacowane oszczędności
```

---

## FAQ

### Jak często aktualizują się ceny?
Co 60 minut. Po 13:30 co 15 minut (czeka na ceny jutrzejsze).

### Czy mogę ręcznie włączyć urządzenie?
Tak. PEO wykryje sterowanie ręczne i wstrzyma automatykę do momentu ręcznego wyłączenia lub końca okna czasowego.

### Co się stanie gdy internet padnie?
PEO użyje ostatnich pobranych danych. Po 24h bez sukcesu oznaczy status jako "brak danych". Mechanizm failsafe przełączy urządzenia w tryb domyślny po 5 min bez heartbeat.

### Czy PEO może uszkodzić moje urządzenia?
Nie. PEO nigdy nie przekracza limitów mocy (przyłączeniowej ani ładowarki). Mechanizm failsafe zapewnia bezpieczny stan w razie awarii. Monitoring temperatury baterii EV wstrzymuje ładowanie przy przegrzaniu.

### Jak zmienić stawki po podwyżce?
Ustawienia → Urządzenia i usługi → PEO → Konfiguruj → Stawki taryfowe. Zmiana jest natychmiastowa, bez restartu.

### Czy muszę mieć fotowoltaikę?
Nie. Moduł PV jest opcjonalny. PEO działa z samymi cenami i taryfami.

### Ile mogę zaoszczędzić?
Zależy od profilu zużycia, taryfy i wyposażenia. Typowe oszczędności:
- Samo przesuwanie bojlera CWU: 30–80 PLN/miesiąc
- Optymalizacja ładowania EV: 50–200 PLN/miesiąc
- Pełna optymalizacja z PV: 100–400 PLN/miesiąc
