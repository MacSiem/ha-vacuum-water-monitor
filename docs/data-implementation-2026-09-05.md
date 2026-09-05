# Vacuum Consumption Data — wykonanie 2026-09-05

Wykonano lokalną podstawę osobnego repo /Users/maciej/repos/vacuum-consumption-data, commit 7ffe3a8. Repo jest czyste, nie zostało utworzone ani opublikowane na GitHub. Publiczny kierunek zaakceptowany; publikacja pozostaje osobną bramką.

- 134 rekordy modeli,23 integracje,4 deklaracje zużycia i5 częściowych katalogów ustawień;0 approved profiles. Są to166 osobne rekordy z typem i provenance.
- Schematy,referencje,warunki ustawień,odrzucanie profili experimental/revoked,walidacja scope/units/kontekstu i rozłączności próbek/urządzeń. Single-axis fit ma zakres exposure;hybrid nadal pending.
- Pakiet deterministyczny z hash i source revision;importer aplikacji wykonuje lokalną walidację w zaufanym checkout i zapis atomowy. Snapshot ma0 aktywnych stawek;runtime resolver oraz pełne HA bindingi pozostają do implementacji.
- Główne README informuje o bazie i współtworzeniu. Dodano tabelę wszystkich134 modeli oraz poradnik LLM z zakazem wnioskowania ml z samego czasu/area.
- Tick odcina interwał przy zmianie trybu/obserwowanych ustawień;zachowuje początek cyklu i oznacza niepełną dokładność jego historii.
-32 testy repo danych PASS;182 testów aplikacji PASS;smoke12/12 i sprint UI obu kopii PASS;schema,bundle/import parity,compile,JS syntax,diff i skan wzorców prywatnych danych PASS.

Cel wszystkich modeli/ustawień/integracji nieosiągnięty. Otwarty research całego indeksu,rzeczywiste mapowania HA,pomiary per konfiguracja,pełna kalibracja/UI,hybrid i niezależna dokładność. Nie prosić teraz o naturalny cykl jako jedyną bramkę. Produkcyjnego HA nie zmieniano. Telegram count=1 z wcześniejszego etapu,bez duplikatu.

Dodatkowa regresja ustawień: jawnie przypisane sygnały task scope, suction level i carpet policy odcinają interwał przy zmianie. Automatyczne wykrywanie tych ról per integracja nadal pozostaje otwarte.
