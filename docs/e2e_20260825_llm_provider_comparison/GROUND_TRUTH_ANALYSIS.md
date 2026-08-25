# Ground-Truth-Analyse: lokal 7b vs. Cloud Qwen 3.8 27B

**Datum:** 2026-08-25
**Methode:** Alle 8 Original-PDFs manuell gelesen (nicht die Extraktionen, sondern die
Quelldokumente selbst), Referenzwerte per Hand bestimmt, dann gegen die tatsächlichen Rohdaten
beider Modelle geprüft — inklusive der rohen (nicht geparsten) LLM-Antworten, nicht nur der
finalen, vom Guard bereits gefilterten Ergebnisse. Lokaler Lauf wurde für diese Analyse ein
zweites Mal ausgeführt, diesmal mit aktiviertem Raw-Output-Log (`local_7b_raw_output.txt`,
1021 Zeilen), damit ein echter Rohdaten-Vergleich möglich ist — beim ersten Lauf
(`docs/e2e_20260825_llm_provider_comparison/REPORT.md`) war das noch nicht aktiv.

Diese Analyse ergänzt den ersten Bericht um die Frage, die reine Feldzahlen nicht beantworten
können: **war das, was beide Modelle extrahiert haben, tatsächlich richtig?**

## Kurzfassung

- Bei manueller Prüfung von 36 kritischen (K.O.-relevanten) Feld-Extraktionen über alle 7
  relevanten Ausschreibungen: **Cloud (Qwen 3.8 27B) traf ~35,5/36 (≈99%)**, **lokal (7b) traf
  ~25,5/36 (≈71%)** — inklusive zweier vom Guard aufgefangener Halluzinationen und mehrerer
  echter Auslassungen.
- **Überraschung:** bei gut strukturierten Dokumenten mit klaren Tabellen (Nordlicht, Mama) ist
  das lokale Modell auf den kritischen Feldern nahezu gleichauf mit Cloud — der Unterschied in
  der Gesamt-Feldzahl (17 vs. 27, 5 vs. 14) kommt dort vor allem aus zusätzlichen weichen/
  Kontextfeldern, die Cloud extrahiert und lokal gar nicht erst versucht — nicht aus falschen
  lokalen Werten.
- Bei textlastigen Dokumenten ohne klare Tabellen (CompanyX, Dragonfly) bricht die lokale
  Extraktion auf den kritischen Feldern fast komplett weg (0/3 bzw. 1/4 gefunden).
- **Zwei echte lokale Halluzinationen gefunden**, eine davon vom Source-Span-Guard live
  abgefangen — ein konkreter Beleg, dass der Guard funktioniert, nicht nur in der Theorie.
- **Korrektur (nach Doku-Review, 2026-08-25):** die folgenden drei Muster waren **keine
  Neuentdeckungen** — alle drei stehen bereits im bestehenden Backlog (`docs/architecture.md`
  §5.4/§5.6 bzw. `OI-123`), datiert 31.07. bzw. 01.08., einen knappen Monat vor dieser Analyse.
  Was hier tatsächlich neu ist: eine frische, konkrete Bestätigung an zusätzlichen Feldern/
  Tendern, plus der direkte Cloud-Vergleich, den es vorher nicht gab.
  - **Pass-4c-Vergessens-Muster** (§5.4 in architecture.md, dort bereits für `max_payload`
    dokumentiert): heute bestätigt an mehreren weiteren Feldern (Hubhöhe, Gassenbreite, Gefälle,
    Temperatur) auf Nordlicht — und neu: bei Cloud tritt das Muster **nicht** auf, was vorher
    nicht verglichen werden konnte, da es kein zweites Modell gab.
  - **Temperatur-Vorzeichenfehler** (§5.6 in architecture.md, dort bereits für zwei
    IK-Tender dokumentiert, exakt dasselbe Beispiel +2°C→-2°C): heute zwei weitere Instanzen
    gefunden, davon eine mit einer neuen Nuance — komplett ohne Quellenangabe (statt einer
    falschen-aber-begründeten Zitation wie in den ursprünglich dokumentierten Fällen), wodurch
    der Guard sie diesmal tatsächlich abfangen konnte.
  - **Kälteleistung: falsche Zahl von mehreren echten gewählt** (`OI-123`, dort bereits exakt
    für IK Deep Freeze mit denselben 280/340-kW-Werten dokumentiert): heute erstmals im direkten
    Cloud-Vergleich — lokal wählt weiterhin falsch (280), Cloud wählt richtig (340).

## Pro-Ausschreibung-Detailbefunde

### Nordlicht — 12/12 kritische Felder korrekt bei BEIDEN Modellen
Bestdokumentierte Ausschreibung (klare Tabelle mit allen Fahrzeug-Anforderungen). Traglast,
Hubhöhe, Gassenbreite, VNA-Status (korrekt negativ), Navigation, Temperatur, Gefälle,
Batterietyp, Sicherheitsnorm, VDA5050, Integration — alles bei beiden Modellen richtig.
Lokal sogar geringfügig vollständiger bei zwei Feldern (Navigation: beide zulässigen Methoden
statt nur einer; Sicherheitsnorm: zwei Normen statt einer). **Dies ist der Beweis, dass das
lokale Modell bei guter Dokumentstruktur durchaus mit Cloud mithalten kann.**

### CompanyX — 0/3 kritisch bei lokal, 3/3 bei Cloud
Traglast (1000 kg, expliziter Fließtext-Satz), Gefälle (1,5%) und VNA-Status: lokal liefert bei
allen dreien `null` — auch der gezielte 4c-Nachfass scheitert. Cloud extrahiert alle drei korrekt
mit exaktem Zitat. Dies ist ein reiner Prosa-Text ohne Tabellen — genau das Format, bei dem
lokal am schwächsten ist.

### Dragonfly — 1/4 kritisch bei lokal, 3,5/4 bei Cloud
Das bereits besprochene VNA-Beispiel: lokal verpasst VNA-Pflicht, Gassenbreite UND Antriebstyp
komplett (`null` bei allen dreien, trotz des Dokumenttitels "Firefly AGV **and VNA** User
Requirement Specification"). Traglast wird immerhin über den 4c-Nachfass mit 1000 kg
teilweise wiederhergestellt (plausibel, wenn auch die Quelle — eine Palettenspezifikationstabelle
statt eines expliziten Anforderungssatzes — schwächer ist als bei anderen Ausschreibungen).
Cloud trifft Traglast und Gassenbreite exakt mit Zitat, Antriebstyp nur ungefähr ("VNA Turret"
statt der im Dokument genannten "VNA reach truck").

### Mama — ~5/5 kritisch bei lokal, 5/5 bei Cloud
Überraschend gut bei lokal: Traglast (2000 kg) und Temperaturbereich (10–30°C) korrekt aus
Pass 4b, korrekterweise `null` bei Hubhöhe/Gassenbreite/VNA (keine dieser Angaben steht im
Dokument — kein Halluzinieren). Cloud ebenso korrekt. **Auch hier: der Gesamt-Feldzahl-
Unterschied (5 vs. 14) liegt an zusätzlichen Kontextfeldern bei Cloud, nicht an falschen
lokalen Werten.**

### IK Cold Store — 3/4 im Endergebnis bei lokal (1 Halluzination vom Guard abgefangen), 4/4 bei Cloud
Kühlleistung (110 kW), Kältemittel-Liste und Temperaturschwankung (±0,5K) korrekt bei beiden.
**Aber:** lokal halluziniert bei der Mindesttemperatur **-2°C** (falsches Vorzeichen; korrekt wäre
+2°C für Zone B) — **ohne jede Quellenangabe** (`"required_temperature_min_source": null`).
Das ist exakt der Fall, für den Layer 1 des Halluzinations-Guards existiert ("keine Zitation = 
Vermutung → nullen") — und er hat ihn auch tatsächlich gegriffen: der Layer-Zähler dieses Laufs
zeigt L1=1, passend zu diesem Fund. Der halluzinierte Wert hat es nie bis zum Endergebnis
geschafft. Cloud extrahiert +2°C korrekt mit echtem Zitat. Der Vorzeichenfehler selbst ist kein
neuer Bug — `docs/architecture.md` §5.6 dokumentiert ihn bereits seit 31.07. an zwei anderen
IK-Tendern; neu ist hier die Variante ganz ohne Zitation, wodurch der Guard ihn diesmal fangen
konnte (die ursprünglich dokumentierten Fälle hatten eine falsche, aber begründete Zitation und
kamen am Guard vorbei).

### IK Deep Freeze — die härteste Ausschreibung: zwei bewusste Mehrdeutigkeits-Fallen
Das Dokument nennt drei Kälteleistungswerte (280 kW nur für den Schockfroster, 340 kW für die
Gesamtanlage) und zwei Temperaturwerte (-18°C Kerntemperatur-Ziel vs. -22°C, explizit als
"verbindlicher Temperatursollwert" markiert). **Korrektur:** die Kälteleistungs-Falle ist keine
Neuentdeckung — sie ist **OI-123** im Open-Items-Backlog (dokumentiert seit 01.08., exakt
dieselbe Ausschreibung, exakter derselbe Mechanismus: "MAXIMUM-Richtungsregel nicht angewendet
bei mehreren echten Kandidaten-Zitaten"). Neu ist hier nur der direkte Cloud-Vergleich.
- **Cloud löst beide Fallen korrekt:** 340 kW (Gesamtanlage) und -22°C (verbindlicher Wert).
- **Lokal löst nur die Temperatur-Falle korrekt** (-22°C), **wählt bei der Kälteleistung aber die
  falsche der beiden Zahlen** (280 kW — nur der Schockfroster-Teilwert, nicht die Gesamtanlage).
  Dieser Fehler wurde vom Guard **nicht** abgefangen, weil 280 kW wörtlich im Dokument steht
  (der Guard prüft nur, ob eine Zahl im Dokument vorkommt — nicht, ob es die *richtige* von
  mehreren echten Zahlen ist). Kältemittel-Liste nur teilweise (R744 statt R744+R290), COP-Wert
  korrekt, aber mit falsch zugeordnetem Zitat (ein Textblock über Siemens Desigo/Modbus statt
  der eigentlichen COP-Anforderung).

### IK Process Cooling — noch eine Falle, plus ein Vorzeichenfehler
280 kW ist hier die Bestandsanlage (2011), die neue Anlage soll mindestens 420 kW liefern
("vierhundertzwanzig Kilowatt", ausgeschrieben). **Beide Modelle vermeiden diese Falle korrekt**
(420, nicht 280). Kältemittel R717 (hier explizit bevorzugt, im Gegensatz zum Deep-Freeze-Tender)
korrekt bei beiden, COP 4,2 korrekt bei beiden. **Aber:** lokal liefert bei der Temperatur
**-4°C statt +4°C** — ein Vorzeichenfehler, obwohl das mitgelieferte Zitat selbst korrekt "+4°C"
sagt. Das Modell hat also richtig zitiert, aber beim Umwandeln in eine Zahl das Vorzeichen
verdreht. Cloud liefert korrekt +4°C.

## Das 4c-Vergessens-Muster (bereits bekannt — §5.4 in architecture.md; heute erweitert bestätigt)

Bei Nordlicht lieferte Pass 4b für lokal korrekt: Hubhöhe 10000, Gassenbreite 3400,
Gefälle 1,5, Temperatur 10/30. Die anschließenden gezielten 4c-Einzelabfragen für exakt
dieselben Felder lieferten **alle `null`** — trotz identischem Modell, identischem Dokument,
nur Sekunden später. `docs/architecture.md` §5.4 dokumentiert dieses Muster bereits seit dem
31.07. für `max_payload`; neu ist heute die Bestätigung an mehreren weiteren Feldern in einem
Lauf sowie der direkte Vergleich mit Cloud. Da im Pipeline-Design ein `null`-Ergebnis von 4c den
4b-Wert nicht überschreibt (nur "abstained"), hat dies das Endergebnis hier nicht beschädigt —
aber es zeigt, dass das lokale 7B-Modell bei der fokussierten Einzelfeld-Frage deutlich
unzuverlässiger ist als im Batch-Modus. Bei Cloud tritt dieses Muster nicht auf: Cloud lieferte
in praktisch jedem beobachteten 4c-Aufruf denselben Wert wie in 4b — das ist der neue Datenpunkt,
den es vor dem heutigen Vergleich noch nicht geben konnte. **Nicht weiter untersucht, aber als
konkreter Hinweis für eine mögliche zukünftige Prompt-Überarbeitung von Pass 4c wert** (bereits
so in architecture.md §5.4 vermerkt).

## Gesamt-Score (36 manuell verifizierte kritische Feld-Extraktionen, 7 Ausschreibungen)

| | Cloud (Qwen 3.8 27B) | Lokal (7b) |
|---|---:|---:|
| Korrekt | ~35,5 / 36 (≈99%) | ~25,5 / 36 (≈71%) |
| Echte Halluzinationen (falscher Wert erzeugt) | 0 | 3 (1 falsches Vorzeichen bei ColdStore — vom Guard abgefangen; 1 falsche Zahlenwahl bei DeepFreeze — NICHT abgefangen; 1 falsches Vorzeichen bei ProcessCooling) |
| Echte Auslassungen (Wert vorhanden, aber `null` geliefert) | ~1 (Antriebstyp Dragonfly, nur ungefähr) | ~7 (v.a. CompanyX, Dragonfly) |
| Fehlende Werte korrekt als `null` erkannt (keine Fantasiewerte) | durchweg korrekt | durchweg korrekt |

**Wichtige Einschränkung:** Dies ist eine gezielte Stichprobe der wichtigsten (K.O.-relevanten)
Felder, nicht eine erschöpfende Prüfung aller ~130 möglichen AP0-Felder pro Ausschreibung — die
meisten Felder kommen in keinem realen Dokument überhaupt vor. Die Prozentzahl bildet also die
Genauigkeit bei den Feldern ab, die tatsächlich im Dokument stehen und für das Matching zählen,
nicht eine Vollständigkeits-Quote über das gesamte Schema.

## Einordnung

Kein Beweis für die befürchtete "stärkeres Modell = mehr Guard-Nullungen"-Falle — im Gegenteil:
Cloud löst durchweg schwierigere, bewusst mehrdeutige Fälle korrekt, während die einzige vom
Guard abgefangene Halluzination diese Runde vom lokalen Modell kam (und der Guard sie korrekt
gefangen hat). Der größte praktische Unterschied ist nicht "Cloud halluziniert weniger" (beide
halluzinieren kaum bis gar nicht, wenn sie einen Wert liefern), sondern **Cloud gibt bei
mehrdeutigen oder textlastigen Dokumenten seltener auf** — es liefert einen (meist richtigen)
Wert, wo lokal `null` zurückgibt. Das lokale Modell ist vorsichtiger, aber dadurch auch
unvollständiger.
