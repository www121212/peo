# Instalacja Polish Energy Optimizer (PEO)

## Wymagania systemowe

- **Home Assistant** w wersji 2024.1.0 lub nowszej
- **HACS** (Home Assistant Community Store) zainstalowany i skonfigurowany
- **Python 3.12+** (dostarczany z HA)
- Połączenie z internetem (do pobierania cen RCE PSE i prognoz solarnych)

## Metoda 1: Instalacja przez HACS (zalecana)

### Krok 1: Dodaj repozytorium niestandardowe

1. Otwórz Home Assistant → **HACS** → **Integracje**
2. Kliknij menu (⋮) w prawym górnym rogu → **Repozytoria niestandardowe**
3. Wklej URL repozytorium:
   ```
   https://github.com/www121212/peo
   ```
4. Kategoria: **Integracja**
5. Kliknij **Dodaj**

### Krok 2: Zainstaluj integrację

1. W HACS → Integracje wyszukaj **"Polish Energy Optimizer"**
2. Kliknij **Pobierz**
3. Wybierz najnowszą wersję → **Pobierz**
4. **Uruchom ponownie Home Assistant** (wymagane po instalacji)

### Krok 3: Dodaj integrację

1. Po restarcie przejdź do: **Ustawienia** → **Urządzenia i usługi** → **Integracje**
2. Kliknij **+ Dodaj integrację**
3. Wyszukaj **"Polish Energy Optimizer"**
4. Postępuj zgodnie z kreatorem konfiguracji (opisanym w [CONFIGURATION.md](CONFIGURATION.md))

## Metoda 2: Instalacja ręczna

### Krok 1: Pobierz pliki

```bash
cd /config/custom_components/
git clone https://github.com/www121212/peo.git peo_temp
mv peo_temp/custom_components/peo ./peo
rm -rf peo_temp
```

Lub pobierz ZIP z GitHub i rozpakuj folder `custom_components/peo/` do `/config/custom_components/peo/`.

### Krok 2: Sprawdź strukturę plików

Po instalacji powinna istnieć następująca struktura:
```
/config/custom_components/peo/
├── __init__.py
├── manifest.json
├── hacs.json
├── const.py
├── config_flow.py
├── options_flow.py
├── services.py
├── binary_sensors.py
├── ...
├── data/
│   ├── tariffs/
│   ├── osd/
│   └── defaults/
└── translations/
    └── pl.json
```

### Krok 3: Uruchom ponownie Home Assistant

```bash
ha core restart
```

### Krok 4: Dodaj integrację

Jak w Metodzie 1, Krok 3.

## Weryfikacja instalacji

Po dodaniu integracji sprawdź:

1. **Ustawienia → Urządzenia i usługi → PEO** — powinno pokazywać urządzenie "Polish Energy Optimizer"
2. **Narzędzia deweloperskie → Stany** — wyszukaj `sensor.peo_` — powinny pojawić się sensory
3. **Narzędzia deweloperskie → Usługi** — wyszukaj `peo.` — powinno być 6 usług
4. **Logi** (Ustawienia → System → Logi) — sprawdź czy nie ma błędów z `custom_components.peo`

## Rozwiązywanie problemów

### Integracja nie pojawia się po instalacji

- Upewnij się, że uruchomiłeś ponownie Home Assistant
- Sprawdź logi: `Ustawienia → System → Logi` → szukaj `peo`
- Sprawdź czy folder `/config/custom_components/peo/manifest.json` istnieje

### Błąd "Wymagana nowsza wersja Home Assistant"

- PEO wymaga HA 2024.1.0+. Zaktualizuj Home Assistant.

### Błąd "Nie można połączyć z API RCE PSE"

- Sprawdź połączenie internetowe
- API PSE może być chwilowo niedostępne — integracja ponowi próbę automatycznie
- Sprawdź logi na poziomie WARNING

### HACS nie widzi repozytorium

- Upewnij się, że wkleiłeś poprawny URL
- Wyczyść cache HACS: HACS → menu (⋮) → Przeładuj
- Sprawdź czy repozytorium jest publiczne

## Aktualizacja

### Przez HACS
1. HACS → Integracje → Polish Energy Optimizer
2. Kliknij **Aktualizuj**
3. Uruchom ponownie Home Assistant

### Ręcznie
1. Pobierz nową wersję z GitHub
2. Zastąp pliki w `/config/custom_components/peo/`
3. Uruchom ponownie Home Assistant

Migracja konfiguracji odbywa się automatycznie — PEO zachowa wszystkie Twoje ustawienia.

## Odinstalowanie

1. **Ustawienia** → **Urządzenia i usługi** → **PEO** → **Usuń**
2. Usuń folder `/config/custom_components/peo/`
3. Uruchom ponownie Home Assistant
