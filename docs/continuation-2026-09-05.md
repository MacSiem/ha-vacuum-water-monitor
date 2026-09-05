# Replacement APP SPRINT checkpoint — 2026-09-05

Stan: lokalny etap aplikacji zweryfikowany; globalny sprint In progress, nie ukończony.
Cwd: /Users/maciej/repos/ha-vacuum-water-monitor; profil hub-eng, klasa implement. Astra/medium zadeklarowana, brak live readbacku. needs_local_models=false; dzieci=0. Zastany dirty patch zachowany; baseline w work/replacement-intake. Bez commit/push/deploy/release oraz zmian produkcyjnego HA. Dataset nie był edytowany.

Wykonano: dokładny resolver physical > personal > approved shared > unknown; historyczny kontekst i firmware/settings rebaseline; prywatne pomiary i kalibracje per device/context, trzy cykle treningowe i oddzielny holdout; pełny cykl rozliczany raz; wash wymaga licznika wykonanych akcji. Pięć fizycznych zbiorników ma osobne wartości. Utrata ciągłości i brak stawki unieważniają bilans. UI pokazuje źródło, domain/error i brakujące dane, rozdziela prywatny zapis od eksportu allowlist. Nie eksportuje swobodnego historycznego kontekstu.

Dowody: work/final-checks.json — 238 Python PASS; smoke12/12; sprint obu kart, katalog, generator, compile, JS i diff PASS. scripts/check_sprint_ledger.py PASS: wszystkie1023 brakujące kryteria mają disposition/owner/evidence/next_step; CI egzekwuje bramkę. Coverage --require-complete nadal exit2 (133 modele, goal_complete=false). Browser syntetyczny390px light/dark success/failure/keyboard i końcowy1280px bez overflow. Prywatny backend osobno objęty testami; stub przeglądarki nie jest testem HA.32 testy datasetu są dowodem poprzedniej sesji przy49c9077, nie świeżym uruchomieniem.

Ograniczenia i next owner: pełny indeks/SKU oraz mapowania13ustawień, pełny bilans segmentów/transferów, standalone wash/tray i hybrid wymagają dataset schema2 oraz zatwierdzonych bindingów i fixtures. Nadal0 approved profiles; empiryczna dokładność wymaga niezależnych pomiarów. Prywatna area whole-cycle nie jest przenośnym profilem v1. Kalibracja nie uzupełnia nieznanego historycznego kontekstu dzisiejszymi ustawieniami. Nie redukuj celu do naturalnego cyklu Roborocka.

Supervisor ma uruchomić osobną kanoniczną sesję /Users/maciej/repos/vacuum-consumption-data po świeżym odczycie wolnego globalnego slotu. Nie uruchomiono jej przy zajętym limicie. Frozen handoff: docs/dataset-handoff-2026-09-05.md; SHA256 3589049c8f1c391146589970e6c7c9e911fbb30314bafd31b997c478b964474a. Powrót: odczytać ten checkpoint, docs/app-sprint-ledger.json, docs/consumption-roadmap.json i receipt datasetu. Kod APP ma czekać na versioned kontrakt zamiast dopasowywać zgadywane stawki.

Notion: 3d1926a21f08813e88dce1f3e673e31c In progress; replacement update zapisany. communication_trace nowej sesji będzie odczytany z work/replacement-final-receipt.json i ledgeru. Poprzedni count1 zachowany w communication_history; nowa sesja przed wysyłką count0.

Final communication_trace: count=1, sent=true, exit=0, status=WAITING_FOR_PLATFORM, notify_type=question. Notion replacement content + In progress readback PASS.

## V3 app integration closeout

Frozen V3 was consumed read-only and its hashes are recorded in
`dataset-v3-integration-2026-09-05.md`. Portable import, epoch-ms segment replay,
five-reservoir conservation, immutable identity, physical source evidence and
exact HA entity binding are implemented fail closed. Both live registries remain
empty; zero approved profiles or real streams exist. Fresh result: 266 Python and
all eight local checks PASS. Coverage remains goal=false with 1023 unresolved
criteria. Resume only on new frozen hardware/measurement evidence; do not replace
it with synthetic fixtures or current settings for missing historical context.
