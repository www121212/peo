# Dokument Wymagań — Polish Energy Optimizer (PEO)

## Wprowadzenie

Polish Energy Optimizer (PEO) to niestandardowa integracja Home Assistant (kompatybilna z HACS), zaprojektowana specjalnie dla polskiego rynku energii. Integracja łączy pobieranie cen spot z RCE PSE, pełną obsługę polskich taryf dystrybucyjnych, inteligentne harmonogramowanie ładowania pojazdów elektrycznych, przesuwanie obciążeń (load shifting), optymalizację fotowoltaiki z magazynem energii oraz porównywanie taryf — wszystko w jednym rozwiązaniu z pełną konfiguracją przez interfejs użytkownika w języku polskim.

PEO wypełnia zidentyfikowane luki rynkowe: istniejące rozwiązania (RCE PSE, Energy Hub Poland, EMHASS) oferują jedynie fragmentaryczne funkcjonalności — ceny bez sterowania, koszty bez optymalizacji, lub optymalizację bez polskiego kontekstu taryfowego. PEO integruje te elementy w spójne, łatwe w konfiguracji narzędzie.

## Słownik

- **PEO**: Polish Energy Optimizer — nazwa integracji
- **Harmonogramownik_EV**: Moduł odpowiedzialny za obliczanie optymalnych okien ładowania pojazdów elektrycznych
- **Moduł_Cen**: Komponent pobierający i przetwarzający ceny energii z RCE PSE
- **Kalkulator_Taryf**: Komponent obliczający rzeczywiste koszty energii na podstawie wybranej taryfy, operatora OSD i składników regulowanych
- **Menedżer_Obciążeń**: Moduł zarządzający przesuwaniem obciążeń (load shifting) dla odbiorów odraczalnych
- **Optymalizator_PV**: Moduł optymalizujący autokonsumpcję energii z fotowoltaiki i zarządzający magazynem energii
- **Analizator_Taryf**: Moduł porównujący taryfy na podstawie historycznego zużycia i rekomendujący zmiany
- **Koordynator_Danych**: Komponent DataUpdateCoordinator odpowiedzialny za cykliczne pobieranie i aktualizację danych
- **RCE**: Rynek Cen Energii — ceny spot z Rynku Dnia Następnego (RDN) publikowane przez PSE
- **PSE**: Polskie Sieci Elektroenergetyczne — operator systemu przesyłowego
- **OSD**: Operator Systemu Dystrybucyjnego (Tauron, PGE, Enea, Energa, innogy/Stoen)
- **OZE**: Odnawialne Źródła Energii — składnik opłaty w taryfie
- **Taryfa**: Struktura cenowa energii (G11, G12, G12w, G12r, G13, C11, C12a, C12b, C21, C22a, C22b, C23)
- **Strefa_Czasowa**: Okres obowiązywania danej stawki w taryfie wielostrefowej (szczyt, pozaszczyt, noc)
- **OCPP**: Open Charge Point Protocol — otwarty protokół komunikacji z ładowarkami EV
- **Config_Flow**: Mechanizm konfiguracji integracji Home Assistant przez interfejs graficzny
- **HACS**: Home Assistant Community Store — repozytorium niestandardowych integracji
- **Okno_Ładowania**: Ciągły lub nieciągły przedział czasowy wybrany do ładowania EV
- **Próg_Cenowy**: Wartość graniczna ceny energii (PLN/kWh) definiująca moment włączenia/wyłączenia odbiornika
- **Odbiornik_Odraczalny**: Urządzenie, którego pracę można przesunąć w czasie bez utraty komfortu (bojler CWU, pompa ciepła, klimatyzacja, basen)
- **Autokonsumpcja**: Bezpośrednie zużycie energii wyprodukowanej przez instalację PV
- **SoC**: State of Charge — poziom naładowania baterii (EV lub magazynu energii) wyrażony w procentach

## Wymagania

### Wymaganie 1: Pobieranie cen RCE z PSE

**User Story:** Jako użytkownik integracji, chcę mieć dostęp do aktualnych i przyszłych cen energii z rynku spot RCE PSE, abym mógł podejmować świadome decyzje o zużyciu energii.

#### Kryteria Akceptacji

1. THE Moduł_Cen SHALL pobierać ceny energii z API RCE PSE dla Rynku Dnia Następnego co 60 minut, z limitem czasu żądania HTTP wynoszącym 30 sekund
2. WHEN dane cenowe na dzień następny zostaną opublikowane przez PSE, THE Moduł_Cen SHALL udostępnić 24 wartości cenowych (po jednej na każdą godzinę doby) w postaci sensorów Home Assistant w ciągu 60 sekund od pobrania danych
3. THE Moduł_Cen SHALL udostępniać sensory: cenę bieżącą (PLN/kWh), cenę minimalną dnia (PLN/kWh), cenę maksymalną dnia (PLN/kWh), cenę średnią dnia (PLN/kWh) oraz listę 24 cen godzinowych jako atrybut sensora
4. WHILE dane cenowe na dzień następny są niedostępne po godzinie 13:30, THE Moduł_Cen SHALL wyświetlać status "oczekiwanie" i kontynuować próby pobrania co 15 minut do godziny 23:59
5. IF połączenie z API RCE PSE nie zwróci odpowiedzi w ciągu 30 sekund lub zwróci kod błędu HTTP (4xx, 5xx), THEN THE Moduł_Cen SHALL wykorzystać ostatnio pobrane dane i oznaczyć sensor statusu jako "dane nieaktualne", a po upływie 24 godzin bez pomyślnego pobrania oznaczyć status jako "brak danych"
6. THE Moduł_Cen SHALL przechowywać historię cen z ostatnich 30 dni w pamięci trwałej integracji
7. WHEN ceny na dzień następny zostaną pobrane, THE Moduł_Cen SHALL wyzwolić zdarzenie Home Assistant `peo_prices_updated` z atrybutami daty i źródła danych
8. IF API RCE PSE zwróci dane niekompletne (mniej niż 24 wartości godzinowych) lub zawierające wartości spoza zakresu 0–5000 PLN/MWh, THEN THE Moduł_Cen SHALL odrzucić całą odpowiedź, zachować poprzednio pobrane dane i zarejestrować ostrzeżenie w logu diagnostycznym

### Wymaganie 2: Obsługa polskich taryf energetycznych

**User Story:** Jako użytkownik z polską taryfą energetyczną, chcę aby integracja obliczała rzeczywiste koszty energii uwzględniając moją taryfę, operatora OSD i wszystkie składniki opłat, abym znał prawdziwy koszt każdej kWh.

#### Kryteria Akceptacji

1. THE Kalkulator_Taryf SHALL obliczać koszt kWh dla taryf: G11, G12, G12w, G12r, G13, C11, C12a, C12b, C21, C22a, C22b, C23, uwzględniając definicje stref czasowych specyficzne dla każdego typu taryfy (G11/C11: jedna strefa, G12: szczyt/pozaszczyt, G12w: szczyt/pozaszczyt/weekend, G12r: strefy dynamiczne, G13: szczyt poranny/szczyt popołudniowy/pozaszczyt)
2. THE Kalkulator_Taryf SHALL obliczać koszt kWh z wykorzystaniem stawek dystrybucyjnych specyficznych dla operatorów OSD: Tauron Dystrybucja, PGE Dystrybucja, Enea Operator, Energa Operator, innogy Stoen Operator, w tym godzin obowiązywania stref czasowych zdefiniowanych przez każdego operatora
3. WHEN użytkownik wybierze taryfę i operatora OSD, THE Kalkulator_Taryf SHALL obliczać pełny koszt kWh z dokładnością do 4 miejsc po przecinku (PLN/kWh) uwzględniając: cenę energii (RCE lub stałą), opłatę dystrybucyjną zmienną, opłatę przejściową, opłatę OZE, opłatę mocową i opłatę kogeneracyjną
4. WHILE obowiązuje dana strefa czasowa taryfy wielostrefowej (szczyt, pozaszczyt, noc lub weekend — zależnie od typu taryfy), THE Kalkulator_Taryf SHALL stosować stawki przypisane do aktualnie obowiązującej strefy danego operatora OSD
5. THE Kalkulator_Taryf SHALL udostępniać sensor kosztu bieżącego (PLN/kWh) z dokładnością do 4 miejsc po przecinku, uwzględniający aktualną strefę czasową taryfy, oraz atrybut wskazujący nazwę bieżącej strefy
6. WHEN zmieni się strefa czasowa taryfy, THE Kalkulator_Taryf SHALL zaktualizować sensor kosztu bieżącego w ciągu 10 sekund od zmiany strefy
7. THE Kalkulator_Taryf SHALL umożliwiać aktualizację wszystkich składników stawek taryfowych (cena energii, opłata dystrybucyjna zmienna, opłata przejściowa, opłata OZE, opłata mocowa, opłata kogeneracyjna) przez użytkownika w interfejsie konfiguracji bez konieczności ponownej instalacji integracji
8. IF stawki taryfowe nie zostały skonfigurowane przez użytkownika, THEN THE Kalkulator_Taryf SHALL zastosować domyślne stawki dostarczone z bieżącą wersją integracji, odpowiadające taryfom zatwierdzonym przez URE
9. IF użytkownik wybierze nieprawidłową kombinację taryfy i operatora OSD lub nie uzupełni wymaganych stawek, THEN THE Kalkulator_Taryf SHALL wyświetlić komunikat o błędzie walidacji w języku polskim i uniemożliwić zapis konfiguracji do momentu poprawienia danych

### Wymaganie 3: Harmonogramowanie ładowania EV (MVP)

**User Story:** Jako właściciel pojazdu elektrycznego, chcę aby integracja automatycznie wybrała najtańsze godziny ładowania mojego samochodu, abym oszczędzał na kosztach energii bez ręcznego planowania.

#### Kryteria Akceptacji

1. WHEN użytkownik zdefiniuje wymagania ładowania (docelowy SoC w zakresie 10%-100%, czas zakończenia jako data i godzina w ciągu najbliższych 48 godzin, minimalna moc ładowania w zakresie 1,4 kW–22 kW) oraz skonfiguruje encję źródłową aktualnego poziomu SoC pojazdu, THE Harmonogramownik_EV SHALL obliczyć okno ładowania o najniższym łącznym koszcie energii (PLN) na podstawie godzinowych stawek z Kalkulator_Taryf w ciągu 30 sekund od zdefiniowania wymagań
2. THE Harmonogramownik_EV SHALL obsługiwać ładowarki komunikujące się przez protokoły: OCPP 1.6/2.0, Tesla Wall Connector API, Wallbox Pulsar API, OpenEVSE API
3. WHEN nadejdzie obliczone okno ładowania, THE Harmonogramownik_EV SHALL wysłać komendę rozpoczęcia ładowania do skonfigurowanej ładowarki w ciągu 60 sekund od planowanego czasu rozpoczęcia
4. WHEN okno ładowania zakończy się lub odczyt SoC z encji źródłowej osiągnie lub przekroczy docelowy SoC (sprawdzany co 60 sekund), THE Harmonogramownik_EV SHALL wysłać komendę zatrzymania ładowania
5. THE Harmonogramownik_EV SHALL zapewnić, że planowana moc ładowania EV zsumowana z bieżącym obciążeniem budynku (odczytywanym z encji sensora mocy) nie przekroczy skonfigurowanej przez użytkownika mocy przyłączeniowej budynku (kW)
6. IF ładowarka nie odpowiada na komendę sterującą w ciągu 30 sekund, THEN THE Harmonogramownik_EV SHALL ponowić próbę 3 razy w odstępach 10-sekundowych i powiadomić użytkownika o niepowodzeniu
7. WHEN prognoza PV na dzień następny przewiduje godziny, w których produkcja PV przekracza prognozowane zużycie bazowe o co najmniej wartość minimalnej mocy ładowania EV, THE Harmonogramownik_EV SHALL wysłać powiadomienie Home Assistant z propozycją przesunięcia ładowania na godziny nadwyżki PV
8. THE Harmonogramownik_EV SHALL udostępniać sensor z harmonogramem ładowania zawierający: planowane okna czasowe, szacowany koszt (PLN), szacowaną ilość energii do doładowania (kWh), aktualizowany w ciągu 30 sekund od każdego przeliczenia harmonogramu
9. WHEN użytkownik ręcznie uruchomi ładowanie poza harmonogramem, THE Harmonogramownik_EV SHALL zarejestrować sesję jako "ładowanie manualne", kontynuować odczyt SoC i energii pobranej z encji źródłowej, oraz aktualizować atrybuty sensora sesji ładowania
10. THE Harmonogramownik_EV SHALL obsługiwać scenariusz ładowania nieciągłego — wybierając wiele optymalnych okien czasowych gdy łączny koszt ładowania nieciągłego jest niższy niż koszt najtańszego ciągłego okna pokrywającego wymagany czas ładowania
11. WHEN zdarzenie `peo_prices_updated` zostanie wyzwolone przez Moduł_Cen, THE Harmonogramownik_EV SHALL przeliczyć harmonogram ładowania na podstawie zaktualizowanych danych cenowych i zaktualizować sensor harmonogramu
12. IF encja źródłowa SoC pojazdu jest niedostępna lub nie zwraca wartości liczbowej przez ponad 5 minut, THEN THE Harmonogramownik_EV SHALL oznaczyć harmonogram jako "brak danych SoC", wstrzymać automatyczne sterowanie ładowaniem i powiadomić użytkownika
13. IF planowane ładowanie nie może zostać ukończone do zdefiniowanego czasu zakończenia przy dostępnej mocy i ograniczeniach przyłączeniowych, THEN THE Harmonogramownik_EV SHALL powiadomić użytkownika o niemożliwości osiągnięcia docelowego SoC i zaproponować najlepszy osiągalny poziom naładowania

### Wymaganie 4: Przesuwanie obciążeń (Load Shifting)

**User Story:** Jako użytkownik z odbiornikami odraczalnymi (bojler CWU, pompa ciepła, klimatyzacja, basen), chcę aby integracja automatycznie uruchamiała te urządzenia w najtańszych godzinach, abym minimalizował koszty energii.

#### Kryteria Akceptacji

1. THE Menedżer_Obciążeń SHALL umożliwiać konfigurację od 1 do 16 odbiorników odraczalnych z parametrami: encja Home Assistant, próg cenowy włączenia (0.01–5.00 PLN/kWh), próg cenowy wyłączenia (0.01–5.00 PLN/kWh), minimalna dzienna praca (0.5–24 godziny), maksymalna dzienna praca (0.5–24 godziny), okno czasowe dozwolone (godzina rozpoczęcia i zakończenia w formacie HH:MM), priorytet (1–16, gdzie 1 oznacza najwyższy), pobór mocy odbiornika (W)
2. WHEN bieżący koszt energii z Kalkulator_Taryf spadnie poniżej progu cenowego włączenia skonfigurowanego odbiornika, THE Menedżer_Obciążeń SHALL wysłać komendę włączenia do encji Home Assistant tego odbiornika w ciągu 30 sekund od wykrycia zmiany ceny
3. WHEN bieżący koszt energii z Kalkulator_Taryf przekroczy próg cenowy wyłączenia skonfigurowanego odbiornika, THE Menedżer_Obciążeń SHALL wysłać komendę wyłączenia do encji Home Assistant tego odbiornika w ciągu 30 sekund od wykrycia zmiany ceny
4. WHILE odbiornik odraczalny nie osiągnął minimalnej dziennej pracy i pozostały godziny w dozwolonym oknie czasowym, THE Menedżer_Obciążeń SHALL wybrać najtańsze pozostałe godziny (na podstawie kosztu z Kalkulator_Taryf) do uruchomienia odbiornika w celu zapewnienia minimalnej dziennej pracy
5. IF odbiornik odraczalny osiągnął maksymalną dzienną pracę, THEN THE Menedżer_Obciążeń SHALL zablokować dalsze włączenia do godziny 00:00 dnia następnego
6. IF suma poboru mocy aktywnych odbiorników zarządzanych przez Menedżer_Obciążeń oraz pozostałego obciążenia budynku przekracza skonfigurowaną moc przyłączeniową (W), THEN THE Menedżer_Obciążeń SHALL wstrzymać włączenie odbiorników o niższym priorytecie (wyższa wartość liczbowa) do momentu zwolnienia mocy
7. WHEN użytkownik ręcznie włączy odbiornik zarządzany przez Menedżer_Obciążeń, THE Menedżer_Obciążeń SHALL wstrzymać automatyczne sterowanie tym odbiornikiem do momentu ręcznego wyłączenia przez użytkownika lub do końca bieżącego dozwolonego okna czasowego — w zależności co nastąpi wcześniej
8. THE Menedżer_Obciążeń SHALL udostępniać sensor z harmonogramem pracy każdego odbiornika na bieżący dzień zawierający: planowane okna czasowe (lista par godzina_start–godzina_stop), zrealizowany czas pracy (minuty), pozostały wymagany czas pracy (minuty), aktualny status (włączony/wyłączony/zablokowany/ręczny)
9. IF odbiornik odraczalny nie potwierdzi zmiany stanu (włączenie lub wyłączenie) w ciągu 60 sekund od wysłania komendy, THEN THE Menedżer_Obciążeń SHALL ponowić komendę maksymalnie 3 razy w odstępach 30-sekundowych, a po wyczerpaniu prób powiadomić użytkownika i oznaczyć odbiornik jako "wymagający weryfikacji"

### Wymaganie 5: Integracja z fotowoltaiką i magazynem energii

**User Story:** Jako właściciel instalacji PV z magazynem energii, chcę aby integracja optymalizowała autokonsumpcję i zarządzała baterią w kontekście cen energii i prognoz produkcji, abym maksymalizował korzyści z mojej instalacji.

#### Kryteria Akceptacji

1. THE Optymalizator_PV SHALL pobierać prognozę produkcji PV na 24 godziny do przodu z serwisu prognozy solarnej (Solcast, Forecast.Solar lub OpenWeatherMap Solar) co 60 minut
2. WHEN prognoza PV jest dostępna, THE Optymalizator_PV SHALL obliczać godzinowy profil nadwyżki energii (produkcja PV minus średnie godzinowe zużycie z ostatnich 7 dni jako prognozowane zużycie bazowe)
3. WHILE cena energii z sieci (z Kalkulator_Taryf) jest niższa niż koszt rozładowania baterii (skonfigurowany przez użytkownika koszt degradacji w PLN/kWh), THE Optymalizator_PV SHALL utrzymywać baterię w trybie ładowania z sieci, nie przekraczając poziomu SoC wynikającego z algorytmu kryterium 5
4. WHEN cena energii z sieci przekroczy sumę kosztu degradacji baterii (PLN/kWh) i wartości energii możliwej do zmagazynowania z PV w danej godzinie, THE Optymalizator_PV SHALL przełączyć baterię w tryb rozładowania na potrzeby domu
5. WHEN dane cenowe i prognoza PV na dzień następny są dostępne, THE Optymalizator_PV SHALL obliczać docelowy poziom naładowania baterii (SoC) na koniec okresu taniej strefy taryfowej (wg Kalkulator_Taryf), minimalizujący łączny koszt energii w horyzoncie 24h, w zakresie od skonfigurowanego minimalnego SoC (domyślnie 10%) do 100%
6. IF prognoza PV przewiduje produkcję przekraczającą dzienne zużycie bazowe, THEN THE Optymalizator_PV SHALL ograniczyć nocne ładowanie baterii z sieci do poziomu SoC zapewniającego pozostawienie co najmniej pojemności równej prognozowanej nadwyżce PV (nie mniej niż skonfigurowany minimalny SoC)
7. THE Optymalizator_PV SHALL udostępniać sensory: prognozowaną produkcję PV w kWh (dziś/jutro), prognozowaną autokonsumpcję w kWh (dziś), rekomendowany tryb baterii (ładowanie/rozładowanie/oczekiwanie), szacowane dzienne oszczędności w PLN
8. THE Optymalizator_PV SHALL obsługiwać komunikację z inwerterami przez integracje Home Assistant (SolarEdge, Huawei Solar, GoodWe, Fronius, SMA)
9. IF serwis prognozy solarnej jest niedostępny lub nie zwraca danych przez 180 minut, THEN THE Optymalizator_PV SHALL wykorzystać ostatnio pobraną prognozę, oznaczyć sensor statusu jako "prognoza nieaktualna" i powiadomić użytkownika
10. WHILE bateria jest rozładowywana, THE Optymalizator_PV SHALL nie dopuścić do spadku SoC poniżej skonfigurowanego minimalnego poziomu bezpieczeństwa (domyślnie 10%, zakres konfiguracji 5%-30%) i przełączyć baterię w tryb oczekiwania po osiągnięciu tego progu

### Wymaganie 6: Porównywanie i rekomendacja taryf

**User Story:** Jako użytkownik, chcę wiedzieć czy moja obecna taryfa jest optymalna, abym mógł podjąć decyzję o ewentualnej zmianie taryfy u mojego sprzedawcy.

#### Kryteria Akceptacji

1. THE Analizator_Taryf SHALL obliczać hipotetyczny koszt energii z ostatnich 30 dni dla każdej dostępnej taryfy (G11, G12, G12w, G12r, G13) na podstawie rzeczywistego godzinowego profilu zużycia użytkownika pobranego z sensora energii Home Assistant
2. WHEN analiza porównawcza zostanie zakończona, THE Analizator_Taryf SHALL wyświetlić ranking taryf od najtańszej do najdroższej jako atrybut sensora, z kwotą różnicy w PLN względem aktualnie wybranej taryfy użytkownika
3. THE Analizator_Taryf SHALL udostępniać sensor z rekomendowaną taryfą i szacowaną miesięczną oszczędnością w PLN względem aktualnie wybranej taryfy użytkownika
4. IF różnica kosztów między aktualną taryfą a najtańszą przekracza 10% kosztu miesięcznego, THEN THE Analizator_Taryf SHALL wygenerować powiadomienie z rekomendacją zmiany taryfy nie częściej niż raz na 7 dni
5. WHEN nastąpi godzina 01:00 czasu lokalnego, THE Analizator_Taryf SHALL zaktualizować analizę porównawczą na podstawie danych z ostatnich 30 dni
6. THE Analizator_Taryf SHALL uwzględniać w porównaniu pełne koszty (energia + opłata dystrybucyjna zmienna + opłata przejściowa + opłata OZE + opłata mocowa + opłata kogeneracyjna) dla każdej taryfy i operatora OSD
7. IF dane godzinowego zużycia obejmują mniej niż 7 dni, THEN THE Analizator_Taryf SHALL oznaczyć wyniki analizy jako "niewystarczające dane" i nie generować rekomendacji zmiany taryfy

### Wymaganie 7: Konfiguracja przez interfejs użytkownika

**User Story:** Jako użytkownik Home Assistant, chcę skonfigurować całą integrację przez interfejs graficzny w języku polskim, bez edycji plików YAML, abym mógł łatwo uruchomić i dostosować integrację.

#### Kryteria Akceptacji

1. THE Config_Flow SHALL prowadzić użytkownika przez konfigurację krok po kroku: wybór modułów, konfiguracja taryfy, konfiguracja EV, konfiguracja odbiorników, konfiguracja PV
2. THE Config_Flow SHALL wyświetlać wszystkie etykiety, opisy i komunikaty w języku polskim
3. THE Config_Flow SHALL walidować dane wejściowe przed przejściem do następnego kroku i wyświetlać komunikaty o błędach w języku polskim, w tym: wartości liczbowe poza dozwolonym zakresem pola, wymagane pola pozostawione puste, wartości SoC spoza zakresu 0–100%, wartości mocy spoza zakresu 0–100 kW, stawki taryfowe spoza zakresu 0–5 PLN/kWh
4. WHEN użytkownik wybierze operatora OSD, THE Config_Flow SHALL automatycznie załadować dostępne taryfy i domyślne stawki dla wybranego operatora w ciągu 3 sekund
5. THE Config_Flow SHALL umożliwiać dodawanie i usuwanie odbiorników odraczalnych (do maksymalnie 10 odbiorników) bez ponownej konfiguracji całej integracji
6. THE Config_Flow SHALL umożliwiać rekonfigurację dowolnego modułu (EV, taryfy, PV, odbiory) niezależnie od pozostałych poprzez mechanizm Options Flow Home Assistant
7. IF użytkownik przerwie konfigurację przed jej zakończeniem, THEN THE Config_Flow SHALL zachować dotychczas wprowadzone dane do momentu ponownego uruchomienia Home Assistant i umożliwić kontynuację od miejsca przerwania
8. THE Config_Flow SHALL oferować tryb "szybkiej konfiguracji" z domyślnymi wartościami dla typowego użytkownika (G12, EV, bojler CWU)
9. IF użytkownik nie wybierze żadnego modułu w kroku wyboru modułów, THEN THE Config_Flow SHALL wyświetlić komunikat o konieczności wybrania co najmniej jednego modułu i uniemożliwić przejście do następnego kroku


### Wymaganie 8: Architektura i zgodność z Home Assistant

**User Story:** Jako deweloper i użytkownik Home Assistant, chcę aby integracja była zgodna z wzorcami architektonicznymi HA i łatwa do zainstalowania przez HACS, abym miał pewność stabilności i kompatybilności.

#### Kryteria Akceptacji

1. THE PEO SHALL wykorzystywać wzorzec DataUpdateCoordinator do cyklicznego pobierania danych z zewnętrznych API, z osobną instancją koordynatora dla każdego modułu (Moduł_Cen, Kalkulator_Taryf, Optymalizator_PV)
2. THE PEO SHALL rejestrować encje przez mechanizm ConfigEntry i EntityPlatform, zapewniając że każda encja posiada unique_id, device_info oraz poprawną platformę (sensor, binary_sensor, switch)
3. THE PEO SHALL obsługiwać pełny cykl życia integracji poprzez implementację: async_setup_entry (rejestracja koordynatorów i platform), async_unload_entry (anulowanie listenerów, zamknięcie sesji HTTP, usunięcie referencji koordynatorów), async_remove_entry (usunięcie danych trwałych) — każda operacja musi zwrócić True w ciągu 10 sekund
4. THE PEO SHALL działać asynchronicznie z wykorzystaniem asyncio — operacje I/O trwające powyżej 100ms (zapytania HTTP, operacje plikowe) muszą być delegowane do executora przez hass.async_add_executor_job
5. THE PEO SHALL być kompatybilna z Python 3.12 lub nowszym
6. THE PEO SHALL zawierać plik manifest.json zawierający wymagane pola: domain, name, version (semver), documentation, issue_tracker, dependencies, codeowners, iot_class, homeassistant (minimalna wersja) oraz plik hacs.json z polami name, homeassistant i render_readme
7. IF integracja wykryje wersję Home Assistant niższą niż wartość zadeklarowana w polu "homeassistant" pliku manifest.json, THEN THE PEO SHALL wyświetlić komunikat wskazujący minimalną wymaganą wersję i zablokować ładowanie integracji
8. THE PEO SHALL logować zdarzenia diagnostyczne z wykorzystaniem mechanizmu logging Home Assistant: DEBUG dla szczegółów komunikacji API i obliczeń, INFO dla zmian stanu i zakończonych operacji, WARNING dla danych nieaktualnych i ponawianych operacji, ERROR dla nieudanych operacji krytycznych
9. THE PEO SHALL przechowywać w ConfigEntry.data dane wymagane do połączenia (klucze API, identyfikatory urządzeń) a w ConfigEntry.options parametry modyfikowalne w runtime (progi cenowe, interwały, preferencje użytkownika) — zmiana options nie wymaga przeładowania integracji
10. THE PEO SHALL obsługiwać migrację konfiguracji między wersjami integracji poprzez implementację async_migrate_entry z numerem wersji (VERSION) inkrementowanym przy każdej zmianie schematu — migracja musi zachować wszystkie wartości konfiguracyjne użytkownika lub przekształcić je do nowego formatu bez wymagania ponownej konfiguracji
11. WHEN integracja zostanie załadowana po aktualizacji przez HACS, THE PEO SHALL zweryfikować zgodność wersji schematu konfiguracji i wykonać migrację automatycznie przed inicjalizacją modułów
12. IF operacja async_setup_entry nie zakończy się w ciągu 30 sekund, THEN THE PEO SHALL przerwać inicjalizację, zalogować błąd i oznaczyć ConfigEntry jako wymagający ponownej konfiguracji

### Wymaganie 9: Bezpieczeństwo i niezawodność

**User Story:** Jako użytkownik sterujący urządzeniami elektrycznymi, chcę mieć pewność że integracja działa bezpiecznie i niezawodnie, abym nie narażał urządzeń na uszkodzenie ani nie powodował niebezpiecznych sytuacji.

#### Kryteria Akceptacji

1. THE PEO SHALL walidować wszystkie dane wejściowe z zewnętrznych API przed ich przetworzeniem — walidacja obejmuje sprawdzenie typu danych, obecności wymaganych pól oraz wartości w zdefiniowanych zakresach; dane niespełniające walidacji SHALL być odrzucone, a PEO SHALL zalogować ostrzeżenie na poziomie WARNING i kontynuować pracę z ostatnimi poprawnymi danymi
2. IF dane z API RCE PSE zawierają wartości spoza zakresu 0-5000 PLN/MWh, THEN THE Moduł_Cen SHALL odrzucić cały zestaw danych z danego pobrania, zalogować ostrzeżenie na poziomie WARNING zawierające zakres nieprawidłowych wartości, oraz zachować ostatnio pobrane poprawne dane jako aktywne
3. THE Harmonogramownik_EV SHALL respektować limity mocy ładowarki odczytane z API ładowarki (maksymalny prąd ładowania w amperach, maksymalna moc w kW) i nie wysyłać komend sterujących przekraczających te wartości
4. WHILE temperatura baterii EV przekracza próg bezpieczeństwa zgłaszany przez ładowarkę, THE Harmonogramownik_EV SHALL wstrzymać ładowanie i wznowić je dopiero gdy temperatura spadnie poniżej zgłaszanego progu bezpieczeństwa
5. IF PEO nie zaktualizuje sygnału heartbeat przez 5 minut, THEN THE Menedżer_Obciążeń SHALL przełączyć każde sterowane urządzenie w tryb domyślny zdefiniowany w konfiguracji bezpieczeństwa danego urządzenia (włączone lub wyłączone) i powiadomić użytkownika o aktywacji mechanizmu awaryjnego
6. IF komunikacja z ładowarką EV nie zostanie potwierdzona przez 60 sekund podczas aktywnego ładowania, THEN THE Harmonogramownik_EV SHALL uznać komunikację za utraconą, powiadomić użytkownika za pośrednictwem mechanizmu powiadomień Home Assistant i oznaczyć sesję jako "wymagająca weryfikacji"
7. THE PEO SHALL szyfrować dane uwierzytelniające (tokeny API, hasła) przechowywane w konfiguracji z wykorzystaniem mechanizmu credentials Home Assistant
8. THE PEO SHALL ograniczać częstotliwość wywołań API zewnętrznych do maksymalnie 60 żądań na godzinę na endpoint; IF limit zostanie osiągnięty, THEN THE PEO SHALL wstrzymać kolejne żądania do danego endpointu do początku następnej godziny i zalogować ostrzeżenie na poziomie WARNING
9. IF ładowarka nie udostępnia informacji o temperaturze baterii EV, THEN THE Harmonogramownik_EV SHALL kontynuować ładowanie zgodnie z harmonogramem, respektując wyłącznie limity mocy ładowarki

### Wymaganie 10: Monitorowanie i raportowanie

**User Story:** Jako użytkownik, chcę mieć wgląd w oszczędności generowane przez integrację oraz historię działań optymalizacyjnych, abym mógł ocenić skuteczność systemu.

#### Kryteria Akceptacji

1. THE PEO SHALL obliczać i udostępniać sensor dziennych oszczędności (PLN, z dokładnością do 2 miejsc po przecinku) — różnicę między kosztem bez optymalizacji a kosztem rzeczywistym — aktualizowany po każdej decyzji optymalizacyjnej oraz resetowany do 0,00 PLN codziennie o 00:00
2. THE PEO SHALL obliczać i udostępniać sensor miesięcznych skumulowanych oszczędności (PLN, z dokładnością do 2 miejsc po przecinku), resetowany do 0,00 PLN o 00:00 pierwszego dnia każdego miesiąca
3. WHEN sesja ładowania EV zostanie zakończona, THE PEO SHALL zarejestrować: czas trwania (minuty), energię pobraną (kWh, 2 miejsca po przecinku), koszt rzeczywisty (PLN, 2 miejsca po przecinku), koszt hipotetyczny bez optymalizacji (PLN, 2 miejsca po przecinku) — przechowując maksymalnie 1000 ostatnich sesji
4. THE PEO SHALL udostępniać sensor z liczbą godzin pracy każdego odbiornika odraczalnego w bieżącym dniu (z rozdzielczością 0,1 h), resetowany codziennie o 00:00
5. THE PEO SHALL generować atrybut diagnostyczny z ostatnimi 10 decyzjami optymalizacyjnymi, gdzie każda zawiera: timestamp (ISO 8601), decyzję, powód, oszczędność (PLN, 2 miejsca po przecinku)
6. IF oszczędności miesięczne przekroczą 50 PLN, THEN THE PEO SHALL wygenerować powiadomienie podsumowujące osiągniętą kwotę oszczędności — maksymalnie jedno powiadomienie na miesiąc kalendarzowy
7. IF dane cenowe wymagane do obliczenia kosztu bazowego (bez optymalizacji) są niedostępne, THEN THE PEO SHALL oznaczyć sensor oszczędności stanem „unknown" i dodać wpis w logu diagnostycznym wskazujący przyczynę braku danych
8. WHEN użytkownik otworzy panel monitorowania, THE PEO SHALL wyświetlić dane sensorów oszczędności zaktualizowane nie później niż 60 sekund od ostatniej decyzji optymalizacyjnej

### Wymaganie 11: Obsługa wielu pojazdów i ładowarek

**User Story:** Jako użytkownik z wieloma pojazdami elektrycznymi lub ładowarkami, chcę aby integracja zarządzała harmonogramami ładowania dla każdego pojazdu niezależnie, abym mógł optymalizować koszty dla całej floty domowej.

#### Kryteria Akceptacji

1. THE Harmonogramownik_EV SHALL obsługiwać konfigurację do 4 niezależnych par pojazd-ładowarka, gdzie każda para posiada odrębne parametry: pojemność baterii (kWh), maksymalna moc ładowania (kW), bieżący SoC, docelowy SoC, czas zakończenia ładowania oraz priorytet wyrażony jako ranga numeryczna od 1 (najwyższy) do 4 (najniższy)
2. WHEN wiele pojazdów wymaga ładowania jednocześnie, THE Harmonogramownik_EV SHALL przydzielić dostępną moc przyłączeniową sekwencyjnie według rangi priorytetu — pojazd o wyższym priorytecie otrzymuje pełne zapotrzebowanie mocy, a pozostała moc jest przydzielana kolejnym pojazdom, pod warunkiem że przydzielona moc nie jest niższa niż minimalna moc ładowania danego pojazdu (konfigurowalna, domyślnie 1,4 kW)
3. THE Harmonogramownik_EV SHALL umożliwiać przypisanie jednej z następujących strategii ładowania do każdego pojazdu: "najtańsze okna" (minimalizacja kosztu bez ograniczenia czasowego), "gotowy do godziny" (naładowany do docelowego SoC przed zdefiniowaną godziną zakończenia), "tylko nadwyżka PV" (ładowanie wyłącznie z nadwyżki produkcji fotowoltaicznej)
4. IF łączne zapotrzebowanie mocy ładowania przekracza dostępną moc przyłączeniową, THEN THE Harmonogramownik_EV SHALL wstrzymać ładowanie pojazdów o niższym priorytecie i sekwencjonować ich ładowanie w kolejnych dostępnych oknach czasowych, zachowując strategię kosztową przypisaną do każdego pojazdu
5. THE Harmonogramownik_EV SHALL udostępniać odrębny zestaw sensorów dla każdej skonfigurowanej pary pojazd-ładowarka, zawierający: aktualny status ładowania, planowane okna czasowe, szacowany koszt sesji (PLN), szacowany czas zakończenia ładowania oraz przydzieloną moc (kW)
6. IF ładowanie pojazdu zostanie odroczone z powodu ograniczeń mocy przyłączeniowej, THEN THE Harmonogramownik_EV SHALL powiadomić użytkownika wskazując pojazd, którego ładowanie zostało odroczone, oraz szacowany nowy czas zakończenia ładowania
7. IF przydzielona moc dla pojazdu jest niższa niż jego skonfigurowana minimalna moc ładowania, THEN THE Harmonogramownik_EV SHALL wstrzymać ładowanie tego pojazdu zamiast przydzielać niewystarczającą moc

### Wymaganie 12: Integracja z ekosystemem Home Assistant

**User Story:** Jako zaawansowany użytkownik Home Assistant, chcę aby integracja udostępniała usługi (services) i zdarzenia (events), abym mógł tworzyć własne automatyzacje wykorzystujące dane i funkcje PEO.

#### Kryteria Akceptacji

1. THE PEO SHALL rejestrować usługi Home Assistant: `peo.start_ev_charging`, `peo.stop_ev_charging`, `peo.set_load_threshold` (parametr: wartość progowa w watach, zakres 100–10000 W), `peo.force_load_on`, `peo.force_load_off`, `peo.recalculate_schedule`, przy czym każda usługa SHALL definiować schemat parametrów walidowany przy wywołaniu
2. THE PEO SHALL wyzwalać zdarzenia Home Assistant: `peo_charging_started`, `peo_charging_completed`, `peo_load_shifted`, `peo_price_threshold_crossed`, `peo_schedule_updated`, gdzie każde zdarzenie SHALL zawierać w payload co najmniej: znacznik czasu (timestamp), identyfikator encji źródłowej oraz dane kontekstowe specyficzne dla typu zdarzenia (np. dla `peo_price_threshold_crossed` — aktualną cenę i kierunek przekroczenia)
3. WHEN użytkownik wywoła usługę `peo.recalculate_schedule`, THE PEO SHALL przeliczyć harmonogramy wszystkich modułów na podstawie aktualnych danych cenowych i wyzwolić zdarzenie `peo_schedule_updated` po zakończeniu przeliczenia w czasie nie dłuższym niż 30 sekund
4. IF wywołanie usługi PEO nie powiedzie się z powodu nieprawidłowych parametrów lub niedostępności wymaganego zasobu, THEN THE PEO SHALL zwrócić błąd Home Assistant (ServiceValidationError) z komunikatem wskazującym przyczynę niepowodzenia, bez zmiany stanu systemu
5. THE PEO SHALL udostępniać encje typu `binary_sensor` wskazujące: czy aktualnie trwa tanie okno (stan ON gdy aktualna cena energii jest poniżej progu cenowego skonfigurowanego przez użytkownika), czy ładowanie EV jest aktywne, czy PV produkuje nadwyżkę (produkcja PV przekracza bieżące zużycie)
6. THE PEO SHALL udostępniać encje typu `sensor` z atrybutami zawierającymi: listę cen energii na najbliższe 24 godziny (atrybut `hourly_prices`), harmonogram zaplanowanych operacji w formacie JSON (atrybut `schedule`) oraz znacznik czasu ostatniej aktualizacji danych (atrybut `last_updated`), dostępnymi w szablonach Jinja2