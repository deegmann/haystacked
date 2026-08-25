# E2E Cross-Model Comparison: Mistral Small 4 (2603)

**Datum:** 2026-08-25
**Zweck:** User-Nachfrage nach einem "kleineren" Mistral-Modell — Mistral Small 4 (`mistralai/mistral-small-2603`)
schlägt auf OpenRouters eigenem Intelligence-Index das bereits getestete Mistral Large 3 (19,7
vs. 15,9), trotz "Small"-Branding (laut Hugging-Face-ID `Mistral-Small-4-119B-2603` tatsächlich
119B Parameter — kleiner als Large 3s 675B, aber nicht klein in absoluten Zahlen). Erstes
Cloud-Modell in dieser Registry mit Reasoning **standardmäßig aus** (`default_enabled: false`) —
kein Workaround-Risiko wie bei Qwen/DeepSeek.

## ⚠️ Wichtigster Befund zuerst: kein einfacher "Gewinner", sondern ein echtes Qualitätsproblem

Die Feldzahlen sind auf den ersten Blick beeindruckend — höchste Werte aller bisher getesteten
Modelle auf fast jeder Ausschreibung, und mit 13-30s pro Tender mit Abstand am schnellsten. **Aber**
bei Nordlicht hat der Top-Match einen **negativen Score (-15)** — ein klares Warnsignal, das ich
vor jeder positiven Bewertung untersucht habe.

**Ursache gefunden:** Mistral Small 4 verwechselt bei Nordlicht **Käufer-Firmendaten mit
Lieferanten-Anforderungen**. Der Dokumenteneinstieg lautet: *"Die Nordlicht Kaffeemanufaktur GmbH
ist ein 1968 gegründetes, familiengeführtes Unternehmen mit Sitz in Bremen."* — eine reine
Selbstvorstellung des Käufers. Das Modell hat daraus gemacht:
- `required_founding_year: 1968` — als ob der **Lieferant** seit 1968 existieren müsse
- `required_hq_city: "Bremen"` — als ob der **Lieferant** seinen Sitz in Bremen haben müsse
- `required_country: "DE"` und `required_service_coverage: "DE"` — ebenfalls plausibel aus
  demselben Kontext fehlgeleitet

Beide Felder haben **keine Guard-Abdeckung** (kein `_source`-Begleitfeld im Extraktionsschema,
keine Zitatpflicht) — das erklärt, warum trotz der Fehlextraktion die Guard-Nullungen niedrig
blieben (0-1 wie bei allen anderen Modellen). Der Fehler ist real, aber strukturell unsichtbar
für den bestehenden Halluzinations-Schutz, weil dieser nur auf numerische K.O.-Felder mit
Zitatpflicht wirkt.

**Nicht reproduzierbar auf den anderen geprüften Tendern:** CompanyX (dessen Dokument ebenfalls
mit einem Gründungsjahr des Käufers beginnt — "founded in 1922") und Dragonfly liefern für
dieselben drei Felder korrekt `null`. Das ist also kein systematischer Modellfehler, sondern ein
dokumentenspezifisches Muster — vermutlich getriggert durch die besonders prominente Platzierung
der Käufer-Selbstvorstellung direkt vor den technischen Anforderungen bei Nordlicht.

**Einordnung ins Backlog:** dies ist eine neue Instanz einer bereits bekannten Fehlerklasse
("echtes Zitat, falsche Frage beantwortet") — dieselbe Kategorie wie OI-118 (CompanyX: "main
track" mit "aisle width" verwechselt) und der frühere CompanyX-Fund (Transfer-Station-Höhe als
AGV-Hubhöhe). Neu ist die konkrete Ausprägung: Käufer- statt Lieferanten-Kontext.

## Ergebnis-Tabelle (Feldzahl/Guard-Nullungen, alle fünf getesteten Konfigurationen)

| Ausschreibung | lokal (7b) | Qwen 3.8 27B | DeepSeek V4 Flash | Mistral Large 3 | **Mistral Small 4** |
|---|---:|---:|---:|---:|---:|
| Nordlicht | 17/0 | 27/0 | 20/0 | 22/0 | **35**/0 ⚠️ (negativer Score) |
| CompanyX | 1/0 | 10/0 | 9/0 | 14/0 | 12/0 |
| Dragonfly | 2/0 | 10/0 | 8/0 | 11/0 | **13**/0 |
| Mama | 5/0 | 14/0 | 12/0 | **15**/0 | 12/0 |
| OeA (out-of-scope) | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| IK Cold Store | 7/1 | 10/0 | 10/0 | 11/1 | **13**/0 |
| IK Deep Freeze | 7/1 | 7/2 | 7/2 | **8**/1 | **8**/1 |
| IK Process Cooling | 5/1 | 8/1 | 8/1 | 9/1 | **11**/1 |

## Dragonfly-VNA (Referenztest)

Korrekt erkannt: `required_vna_capable=true`. Damit haben jetzt alle vier getesteten Cloud-Modelle
diesen Fall richtig gelöst.

## Geschwindigkeit und Kosten

**Mit Abstand am schnellsten:** 13-30s pro Ausschreibung (kompletter 8-Tender-Lauf in 2m46s) —
deutlich schneller als Qwen/DeepSeek (30-155s) und um ein Vielfaches schneller als Mistral Large 3
(60-220s). Auch am günstigsten: ~$0,08 für den kompletten Lauf.

## Einordnung

**Nicht als klarer Gewinner zu werten, trotz der auf den ersten Blick besten Feldzahlen.** Der
Nordlicht-Fund zeigt, dass hohe Feldzahl allein — genau wie schon beim allerersten Qwen-Vergleich
befürchtet, nur in einer anderen Form als die ursprünglich befürchtete "Layer-0"-Falle — kein
verlässlicher Qualitätsindikator ist. Schnelligkeit und niedrige Kosten sind ein echter Vorteil,
aber dieser eine Fund ist ernst genug, um Mistral Small 4 nicht ungeprüft zu empfehlen, bevor der
Käufer-vs-Lieferant-Verwechslungsfehler nicht entweder gezielt nachgetestet (mehr Tender mit
prominenter Käufer-Selbstvorstellung) oder mit einem AP0-Hint-Zusatz ("only extract requirements
about the SUPPLIER, never facts about the BUYER stated in the introduction") entschärft wurde.

---

## Session-Gesamtübersicht: LLM Provider Abstraction (2026-08-25, vollständig)

*Diese Sektion fasst den gesamten Feature-Sprint zusammen (nicht nur diesen Modelltest), damit
dieser Report als eigenständiger Wissensspeicher dient, falls der Gesprächskontext gelöscht wird.
Kanonische Quellen bleiben `docs/spec_llm_provider_abstraction_v0_1.md` (lebende Spec, alle
Nachträge) und die Memory-Datei `project_llm_provider_abstraction_20260825.md` — dieser Abschnitt
ist eine Kopie zum schnellen Wiedereinstieg, kein Ersatz.*

**Was gebaut wurde:** `src/llm_client.py` — `call_llm(system, user, label, model)` ist die EINE
Funktion, die alle 11 Pipeline-Call-Sites in `app.py` (Pass 1–4c) für LLM-Aufrufe nutzen, kein
Default für `model` (ein vergessener Call-Site ist ein `TypeError`, kein stiller Fallback auf
lokal). `LLMModelChoice`-Dataclass + `AVAILABLE_MODELS`-Registry (lokal Ollama + kuratierte
OpenRouter-Cloud-Modelle, jedes zwingend `weights_open=True`), `resolve_model()`,
`_call_ollama()`/`_call_openrouter()`, `LLMProviderError`. Frontend-Dropdown zur Modellwahl vor
jeder Analyse. Kostenschutz: `pytest tests/` löst NIE einen echten Cloud-Call aus (`conftest.py`
`cloud`-Marker, braucht `HAYSTACKED_RUN_CLOUD_TESTS=1` + `OPENROUTER_API_KEY`). Vollständiger
Review-Zyklus (senior-architect, ap0-architecture-guardian, reference-integrity-guardian) auf
Plan- und Implementierungsebene; ein SA-Pflichtfix (Provider-Fehler wurden bei 4a/4b/4c
verschluckt statt laut abzubrechen) direkt umgesetzt und verifiziert.

**Modell-Registry, Stand Ende dieser Session (`src/llm_client.py`, 5 Cloud-Modelle + 1 lokal):**
- `local-qwen2.5-7b` (Default, lokal, Ollama) — Produktions-Baseline, ~71% Ground-Truth-Trefferquote
- `openrouter-qwen3.8-27b` — erstes Cloud-Modell, ~99% Ground-Truth-Trefferquote, reasoning
  standardmäßig AN (deshalb unconditional `"reasoning": {"enabled": false}` bei JEDEM
  OpenRouter-Call, providerweit, nicht modellspezifisch)
- `openrouter-deepseek-v4-flash` — matchte/übertraf Qwen auf allen geprüften Kernfeldern; fand
  live einen echten R3-Robustheitsfall (Whitespace-only-Response `" "` wurde vom alten
  `if not content`-Check nicht erkannt — gefixt mit `.strip()`, providerweit, regressionsgetestet)
- `openrouter-mistral-large` (Mistral Large 3, EU/Apache-2.0, 675B) — trotz schwachem generischem
  Benchmark (15,9 vs. ~52) höchste Feldzahl auf 6/7 Tendern; validierte live eine echte,
  unangekündigte Netzwerkstörung (`httpx.ConnectError`) — Fehlerbehandlung griff korrekt, lauter
  Abbruch statt stillem Teilergebnis
- `openrouter-mistral-small` (Mistral Small 4, EU/Apache-2.0, 119B trotz "Small"-Namen) — dieser
  Report: schnellstes+günstigstes Cloud-Modell, höchste Feldzahl auf 6/7 Tendern, ABER echter
  Käufer/Lieferant-Halluzinationsfund bei Nordlicht (negativer Score -15)
- **Noch nie real getestet:** `openrouter-llama3.3-70b` — einziges verbleibendes registriertes
  Modell ohne Live-Vergleichslauf

**Übergreifende Lehren aus allen 5 Vergleichsläufen:**
1. Feldzahl (Fill-Rate) ist KEIN verlässlicher alleiniger Qualitätsindikator — zweimal in dieser
   Session bestätigt (Layer-0-Zitat-Abweichungs-Sorge vor dem ersten Test; Mistral Small 4s
   Käufer/Lieferant-Verwechslung danach). Jedes neue Modell muss stichprobenartig gegen die
   Rohdaten geprüft werden, insbesondere auf den Tendern, wo es die meisten Felder beansprucht.
2. Generische Benchmark-Indizes (OpenRouters Artificial-Analysis-Werte) sagen wenig über
   Performance auf dieser konkreten strukturierten Extraktionsaufgabe aus (Mistral Large 3: 15,9
   Benchmark, aber Spitzenreiter bei Feldzahl).
3. Der bestehende 3-Layer-Halluzinationsguard deckt nur numerische K.O.-Felder mit Zitatpflicht
   ab — kategoriale/textuelle Felder ohne `_source`-Zwang (wie `required_founding_year`,
   `required_hq_city`) sind strukturell ungeschützt. Das ist keine neue Erkenntnis (D4(b) im
   Backlog war bereits als "wird von größeren Modellen gelöst" geparkt) — Mistral Small 4 zeigt,
   dass größere/bessere Modelle diese Lücke NICHT automatisch schließen, sondern neue,
   plausiblere Instanzen derselben Lücke produzieren können.
4. Alle Cloud-Modelle lösen die Dragonfly-VNA-Anforderung korrekt (`required_vna_capable=true`,
   `required_min_aisle_width=1900`, `required_drive_type="VNA Turret"`) — das lokale 7B-Modell
   historisch nicht (OI-117).
5. Die SA-Pflichtkorrektur zur Provider-Fehlerbehandlung (`LLMProviderError`/`httpx.HTTPError`
   bei 4a/4b/4c) wurde live gegen eine echte Netzwerkstörung bewährt (Mistral-Large-3-Lauf) —
   kein theoretischer Fix mehr, sondern produktionsbestätigt.

**Bestehende Backlog-Punkte, auf die sich diese Session bezieht (nicht verändert, nur eingeordnet):**
OI-113 (Temperatur-Vorzeichenfehler), OI-117 (VNA-Erkennung, 7B-Limitierung), OI-118 (echtes
Zitat, falsche Frage — jetzt auch Mistral-Small-4-Käufer/Lieferant-Fund zugeordnet), OI-122
(ausgeschriebene deutsche Zahlwörter, von DeepSeek korrekt gelöst), OI-123 (Kühlleistungs-
Mehrdeutigkeit 280 vs. 340 kW), D4(b) (kein Guard für kategoriale Felder, weiterhin "geparkt").

**Was NICHT gemacht wurde (bewusst offen gelassen, nicht vergessen):**
- Llama 3.3 70B nie real getestet (wartet auf Freigabe)
- `scripts/test_pipeline.py`-Migration auf `call_llm()` (eigener, unabhängiger `httpx`-Call,
  funktioniert, aber nicht auf die neue Abstraktion migriert)
- `start.sh`/`setup.sh`-Ollama-Liveness-Hard-Gate (kosmetisch, kein Korrektheits-/Kostenproblem)
- Kein Code-Fix für den Käufer/Lieferant-Halluzinationsfund (Tech-Lead-Entscheidung: erst mehr
  Daten sammeln, dann ggf. AP0-Hint-Ergänzung "nur Lieferanten-Fakten extrahieren, nie
  Käufer-Fakten aus der Dokument-Einleitung" erwägen)

**Alle Reports dieser Session:** `REPORT.md` (Qwen 3.8 27B), `GROUND_TRUTH_ANALYSIS.md` (manuelle
Referenz, 36 kritische Felder), `REPORT_deepseek_v4_flash.md`, `REPORT_mistral_large_3.md`,
`REPORT_mistral_small_4.md` (dieser). Alle Commits: `003e567` bis `c3f6809` (siehe `git log`).
Tests: 389 grün / 1 übersprungen (Cloud-Marker) nach jedem Modelltest bestätigt.
