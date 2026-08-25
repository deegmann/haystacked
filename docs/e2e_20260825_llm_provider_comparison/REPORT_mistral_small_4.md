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
