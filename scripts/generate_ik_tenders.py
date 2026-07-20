#!/usr/bin/env python3
"""
Generate 3 realistic IK tender PDFs that challenge LLM extraction.
Each document mimics a human-authored procurement inquiry with specs buried
in narrative prose, different formatting styles, and realistic noise.

Output: tests/tenders/
  - tender_ik_process_cooling.pdf
  - tender_ik_cold_store.pdf
  - tender_ik_deep_freeze.pdf
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "tenders"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = A4


# ── Tender 1: Process Cooling — Molkerei Nordrhein eG ──────────────────────
# Style: German business letter / informal RFQ from a dairy cooperative.
# Specs buried in project description paragraphs.
# LLM traps: "22. März 2025" in header, old system capacity (280 kW) mentioned,
#             COP phrased as "Leistungszahl", kW written out in words for one value.

def build_tender_process_cooling():
    path = OUTPUT_DIR / "tender_ik_process_cooling.pdf"
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=3.0*cm,
        rightMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm,
    )

    base = getSampleStyleSheet()

    body = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10.5, leading=15, spaceAfter=8,
        alignment=TA_JUSTIFY,
    )
    body_tight = ParagraphStyle(
        "body_tight", parent=body, spaceAfter=4,
    )
    heading = ParagraphStyle(
        "heading", parent=base["Normal"],
        fontSize=11, leading=14, spaceBefore=14, spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    small = ParagraphStyle(
        "small", parent=base["Normal"],
        fontSize=9, leading=12, textColor=colors.HexColor("#444444"),
    )
    sender = ParagraphStyle(
        "sender", parent=base["Normal"],
        fontSize=9, leading=12, alignment=TA_RIGHT,
    )

    story = []

    # Sender block (top right, typical German letter)
    story.append(Paragraph("Molkerei Nordrhein eG", sender))
    story.append(Paragraph("Einkauf / Technische Beschaffung", sender))
    story.append(Paragraph("Industriestraße 14–16", sender))
    story.append(Paragraph("41363 Jüchen", sender))
    story.append(Paragraph("Telefon: +49 2165 94870-0", sender))
    story.append(Paragraph("E-Mail: einkauf@molkerei-nordrhein.de", sender))
    story.append(Spacer(1, 0.7*cm))

    story.append(Paragraph("Datum: 22. März 2025", small))
    story.append(Paragraph("Aktenzeichen: ENT-25-0118-KLT", small))
    story.append(Spacer(1, 0.8*cm))

    story.append(Paragraph(
        "<b>Anfrage zur Angebotsabgabe – Prozesskühlung Molkereianlage Jüchen (Erweiterung)</b>",
        ParagraphStyle("subj", parent=base["Normal"], fontSize=11.5, leading=15, fontName="Helvetica-Bold")
    ))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Sehr geehrte Damen und Herren,", body))
    story.append(Paragraph(
        "wir planen die Erweiterung unserer bestehenden Prozesskühlung am Standort Jüchen im Rahmen eines "
        "Kapazitätsausbaus der Milchverarbeitung. Für dieses Vorhaben suchen wir qualifizierte Anbieter "
        "für die Lieferung und Inbetriebnahme einer neuen Kälteanlage. Wir bitten Sie, uns auf Basis der "
        "nachfolgenden Beschreibung ein Angebot zu unterbreiten.",
        body
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("1. Ausgangslage und Bedarf", heading))
    story.append(Paragraph(
        "Unser Standort in Jüchen betreibt seit 2011 eine Prozesskühlung auf Basis einer Ammoniak-Anlage "
        "(R717) mit einer installierten Kälteleistung von 280 kW. Diese Anlage wurde im Jahr 2019 bereits "
        "einmal ertüchtigt. Aufgrund steigender Produktionsmengen – insbesondere im Bereich der "
        "Frischmilchabfüllung und der Joghurtfermentation – reicht die vorhandene Kapazität ab dem vierten "
        "Quartal 2025 voraussichtlich nicht mehr aus.",
        body
    ))
    story.append(Paragraph(
        "Wir benötigen daher eine neue Kälteanlage, die eine Nettokälteleistung von mindestens "
        "vierhundertzwanzig Kilowatt bereitstellt. Die Anlage soll die bestehende Kälteversorgung "
        "ergänzen und im Verbund betrieben werden können; eine vollständige Ablösung der Bestandsanlage "
        "ist nicht vorgesehen.",
        body
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph("2. Technische Anforderungen", heading))
    story.append(Paragraph(
        "Die neue Anlage muss für den Einsatz in einem Molkereiumfeld ausgelegt sein. Folgende Parameter "
        "sind verbindlich einzuhalten:",
        body
    ))
    story.append(Paragraph(
        "Das Kühlmedium auf Sekundärseite ist Propylenglykol/Wasser (ca. 30 % Vol.), da das Glykol-Netz "
        "bereits besteht. Der Kältespeicher wird vom Glykol durchströmt; direktverdampfende Systeme "
        "scheiden aus. Als Kältemittel bevorzugen wir ausdrücklich Ammoniak (R717) aufgrund unserer "
        "jahrelangen Betriebserfahrung und der vorhandenen Infrastruktur (Maschinenraum, Druckbehälter-"
        "Zulassung). Alternativangebote mit anderen Kältemitteln sind willkommen, müssen jedoch begründet "
        "werden.",
        body
    ))
    story.append(Paragraph(
        "Der Vorlauftemperatur auf der Primärseite muss bis auf +4 °C abgesenkt werden können, da die "
        "Pasteurisierungsstrecke eine stabile Eingangstemperatur von +6 °C verlangt und Verluste in der "
        "Leitung eingerechnet werden müssen. Eine Unterschreitung von +2 °C ist nicht zulässig, da sonst "
        "Vereisung im Glykol-Wärmetauscher auftreten kann.",
        body
    ))
    story.append(Paragraph(
        "Hinsichtlich der Energieeffizienz erwarten wir eine Leistungszahl (COP) von mindestens 4,2 bei "
        "den oben genannten Betriebspunkten und einer Außentemperatur von +32 °C (Auslegungssommer). "
        "Bitte legen Sie im Angebot auch den COP für einen typischen Wintertag (+5 °C Außentemperatur) "
        "dar – erfahrungsgemäß liegt dieser deutlich höher, was für unsere Vollkostenrechnung relevant ist.",
        body
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph("3. Umgebungsbedingungen und Installation", heading))
    story.append(Paragraph(
        "Der vorgesehene Aufstellort ist das bestehende Maschinenhaus (Gebäude MH-2) mit einer lichten "
        "Raumhöhe von 6,5 m. Die maximale Grundfläche für die neue Anlage beträgt 8 m × 5 m. Ein "
        "Außenaufsteller (Luftkühler) kann auf dem Dach des Gebäudes nachgerüstet werden. Alle "
        "Komponenten müssen für den dauerhaften Betrieb in einer Umgebung mit typischen Molkerei-"
        "Reinigungszyklen (CIP, Dampfstöße) ausgelegt sein.",
        body
    ))
    story.append(Paragraph(
        "Die elektrische Einspeisung erfolgt über eine vorhandene 630-A-Unterverteiler-Einheit; eine "
        "Neuinstallation der Einspeisung ist nicht im Lieferumfang. Frequenzumrichter für die Kompressoren "
        "sind gewünscht, aber nicht zwingend. Alle sicherheitsrelevanten Komponenten müssen nach "
        "EN 378 zertifiziert sein; ein CE-Kennzeichen und die Druckgeräte-Richtlinie (PED) sind "
        "Grundvoraussetzungen.",
        body
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph("4. Angebotsinhalt", heading))
    story.append(Paragraph(
        "Bitte unterbreiten Sie uns ein vollständiges Angebot inklusive Planungsleistung, Lieferung, "
        "Montage und Inbetriebnahme. Das Angebot soll folgende Punkte umfassen:",
        body
    ))
    items = [
        "Technisches Datenblatt der Anlage (Kälteleistung, Kältemittel, COP bei Auslegungspunkt)",
        "Anlagenschema (R&amp;I-Fließbild) in Vorabversion",
        "Lieferumfang und Systemgrenzen",
        "Projektterminplan (voraussichtlicher Liefertermin: 4. Quartal 2025)",
        "Referenzliste vergleichbarer Molkerei-Projekte (mind. 2 Referenzen)",
        "Festpreisangebot inkl. Montage, exkl. MwSt.",
        "Angaben zu Gewährleistung und Wartungsvertrag",
    ]
    for item in items:
        story.append(Paragraph(f"– {item}", body_tight))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "Angebote bitten wir bis spätestens <b>30. April 2025</b> per E-Mail an "
        "einkauf@molkerei-nordrhein.de zu senden. Für Rückfragen steht Ihnen Herr Dipl.-Ing. "
        "Ralf Heckmann (Tel.: +49 2165 94870-23) zur Verfügung.",
        body
    ))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Mit freundlichen Grüßen", body))
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph("Petra Schönfeld", body_tight))
    story.append(Paragraph("Leiterin Einkauf, Molkerei Nordrhein eG", small))
    story.append(Spacer(1, 1.0*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "Molkerei Nordrhein eG · Industriestraße 14–16 · 41363 Jüchen · Amtsgericht Neuss HRB 5812 · "
        "USt-IdNr.: DE 198 764 432 · Geschäftsführer: Dr. Thomas Beckmann, Sabine Kropp",
        ParagraphStyle("footer", parent=base["Normal"], fontSize=7.5, leading=10,
                       textColor=colors.grey, alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"  Written: {path}")


# ── Tender 2: Cold Store — Frischlogistik Rhein-Ruhr GmbH ──────────────────
# Style: More corporate but imperfect; mix of German/English; sections in odd order.
# LLM traps: two rooms with different temps (must extract minimum = +2°C);
#             COP not stated; competitor system specs mentioned for context;
#             Projekt-Nr. "2025-CS-047" looks like a spec value; English mixed in.

def build_tender_cold_store():
    path = OUTPUT_DIR / "tender_ik_cold_store.pdf"
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=2.5*cm,
        rightMargin=2.5*cm,
        topMargin=2.0*cm,
        bottomMargin=2.5*cm,
    )

    base = getSampleStyleSheet()

    body = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10, leading=14.5, spaceAfter=7,
        alignment=TA_JUSTIFY,
    )
    body_tight = ParagraphStyle("body_tight", parent=body, spaceAfter=3)
    h1 = ParagraphStyle(
        "h1", parent=base["Normal"],
        fontSize=13, leading=17, spaceBefore=0, spaceAfter=6,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1B3A5E"),
    )
    h2 = ParagraphStyle(
        "h2", parent=base["Normal"],
        fontSize=10.5, leading=14, spaceBefore=10, spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    meta_style = ParagraphStyle(
        "meta", parent=base["Normal"],
        fontSize=9, leading=12,
        textColor=colors.HexColor("#555555"),
    )

    story = []

    # Header table: company name + contact info
    header_data = [
        [
            Paragraph("<b>FRISCHLOGISTIK<br/>RHEIN-RUHR GmbH</b>",
                      ParagraphStyle("logo", parent=base["Normal"], fontSize=13,
                                     fontName="Helvetica-Bold", textColor=colors.HexColor("#1B3A5E"))),
            Paragraph(
                "Frischlogistik Rhein-Ruhr GmbH<br/>Lagerstraße 88 · 45472 Mülheim an der Ruhr<br/>"
                "Tel +49 208 309 44-0 · www.fr-rheinruhr.de<br/>Einkauf: tender@fr-rheinruhr.de",
                ParagraphStyle("hdr_r", parent=base["Normal"], fontSize=8.5, leading=12,
                               alignment=TA_RIGHT, textColor=colors.HexColor("#333333"))
            ),
        ]
    ]
    header_tbl = Table(header_data, colWidths=[9*cm, 7*cm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#1B3A5E")),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.6*cm))

    story.append(Paragraph(
        "Procurement Inquiry – Refrigeration System for New Cold Store DC-North",
        h1
    ))

    meta_rows = [
        ["Project No.", "2025-CS-047"],
        ["Revision", "Rev. 1.2  (replaced Rev. 1.0 dated 2025-01-14)"],
        ["Issued by", "Markus Findeisen, Head of Procurement"],
        ["Deadline for offers", "15 April 2025"],
    ]
    mt = Table(meta_rows, colWidths=[4.5*cm, 12*cm])
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#333333")),
    ]))
    story.append(mt)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("1  Background &amp; Scope", h2))
    story.append(Paragraph(
        "Frischlogistik Rhein-Ruhr GmbH is building a new distribution centre (DC-North) in Mülheim an der "
        "Ruhr for the chilled distribution of fresh produce, dairy, and convenience food. DC-North will "
        "replace the leased interim facility at Duisburg-Wanheim which runs on a third-party refrigeration "
        "contract. The new facility is planned for commissioning in Q3 2026.",
        body
    ))
    story.append(Paragraph(
        "This inquiry covers the supply, installation, and commissioning of the complete refrigeration plant "
        "for DC-North. The successful vendor will also be expected to provide a maintenance contract for "
        "at least five years post-commissioning (proposal to be included, but priced separately).",
        body
    ))

    story.append(Paragraph("2  Facility Description", h2))
    story.append(Paragraph(
        "DC-North umfasst zwei Temperaturzonen, die separat geregelt werden müssen:",
        body
    ))
    story.append(Paragraph(
        "<b>Zone A – Frischebereich (Hauptlager):</b> Nettoraumvolumen ca. 3.800 m³ "
        "(LxBxH: 58 m × 32 m × 7 m lichte Höhe). Betriebstemperatur +2 °C bis +6 °C, Sollwert +4 °C. "
        "Relative Luftfeuchte im Raum soll zwischen 80 % und 90 % gehalten werden; eine aktive "
        "Feuchtesteuerung ist daher zwingend erforderlich.",
        body_tight
    ))
    story.append(Paragraph(
        "<b>Zone B – Obst &amp; Gemüse (separate Kammer):</b> Nettoraumvolumen ca. 820 m³. "
        "Betriebstemperatur +2 °C, da ein Teil der Ware eine sehr enge Temperaturtoleranz (z. B. "
        "Beeren, Salate) aufweist. Diese Zone muss von Zone A thermisch entkoppelt sein.",
        body_tight
    ))
    story.append(Paragraph(
        "Die Gesamtkälteleistung für beide Zonen zusammen beläuft sich nach Vorabschätzung unseres "
        "Ingenieurbüros (Planungsstand Dezember 2024) auf rund 110 kW. Dieser Wert ist als Richtwert "
        "anzusehen; wir erwarten von den Bietern eine eigene Auslegungsberechnung.",
        body
    ))

    story.append(Paragraph("3  Refrigerant Requirements", h2))
    story.append(Paragraph(
        "We are aware of the current F-Gas Regulation (EU 517/2014) and the tightening HFC phase-down "
        "schedule. Accordingly, we explicitly request offers based on low-GWP refrigerants. Acceptable "
        "refrigerants are CO2 (R744), propane (R290), or ammonia (R717). Offers using HFC blends such "
        "as R404A or R507 will not be considered. Offers using R134a will only be accepted if accompanied "
        "by a compelling lifecycle analysis demonstrating regulatory compliance through 2040.",
        body
    ))
    story.append(Paragraph(
        "Note: our current Duisburg facility uses R404A (legacy). We do not require compatibility with "
        "that system. Vendors are free to propose whichever low-GWP technology best suits the load profile.",
        body
    ))

    story.append(Paragraph("4  Technical Specifications (Zone A, Auslegungspunkt)", h2))
    story.append(Paragraph(
        "Nachfolgende Werte sind verbindliche Auslegungsparameter. Abweichungen müssen technisch "
        "begründet und genehmigt werden.",
        body
    ))

    spec_rows = [
        ["Parameter", "Wert / Anforderung"],
        ["Raumtemperatur Sollwert", "+4 °C (Zone A) / +2 °C (Zone B)"],
        ["Zulässige Temperaturschwankung", "±0,5 K"],
        ["Relative Luftfeuchte (Zone A)", "80–90 % (aktiv geregelt)"],
        ["Feuchtesteuerung", "erforderlich"],
        ["Betriebszeit", "24 h / Tag, 365 Tage"],
        ["Kältemittel", "R744, R290 oder R717 (HFC nicht akzeptiert)"],
        ["Zertifizierungen", "PED, EN 378, F-Gas-konform"],
    ]
    st = Table(spec_rows, colWidths=[7*cm, 9.5*cm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A5E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F4F8")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("5  Submission Requirements", h2))
    story.append(Paragraph(
        "Bitte senden Sie Ihr Angebot bis zum <b>15. April 2025</b> an tender@fr-rheinruhr.de. Das Angebot "
        "muss folgende Unterlagen enthalten: technisches Datenblatt, R&amp;I-Vorentwurf, Auslegungsberechnung, "
        "Referenzliste (mind. 3 vergleichbare Objekte in Betrieb seit mind. 2 Jahren), Festpreis ohne MwSt.",
        body
    ))
    story.append(Paragraph(
        "Rückfragen: Markus Findeisen, +49 208 309 44-17, m.findeisen@fr-rheinruhr.de",
        body
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "Hinweis: Dieses Dokument enthält vertrauliche Angaben der Frischlogistik Rhein-Ruhr GmbH. "
        "Eine Weitergabe an Dritte ist ohne ausdrückliche schriftliche Zustimmung nicht gestattet.",
        ParagraphStyle("conf", parent=base["Normal"], fontSize=8, textColor=colors.grey,
                       leading=11, leftIndent=0.3*cm)
    ))

    doc.build(story)
    print(f"  Written: {path}")


# ── Tender 3: Deep Freeze — Tiefkühlkost Franken AG ───────────────────────
# Style: Dense technical German from a process engineer, not procurement.
# LLM traps: capacity stated as "0,65 t/h" → must convert to 650 kg/h;
#             -18°C for storage mentioned before the actual -22°C blast target;
#             pulldown_time stated as "Absenkzeit von vier Stunden";
#             R744 mentioned in parenthetical, not as primary subject;
#             norm references scattered throughout.

def build_tender_deep_freeze():
    path = OUTPUT_DIR / "tender_ik_deep_freeze.pdf"
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=2.8*cm,
        rightMargin=2.5*cm,
        topMargin=3.0*cm,
        bottomMargin=2.5*cm,
    )

    base = getSampleStyleSheet()

    body = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10, leading=15, spaceAfter=8,
        alignment=TA_JUSTIFY,
    )
    body_tight = ParagraphStyle("body_tight", parent=body, spaceAfter=3)
    h1 = ParagraphStyle(
        "h1", parent=base["Normal"],
        fontSize=12, leading=16, spaceBefore=0, spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    h2 = ParagraphStyle(
        "h2", parent=base["Normal"],
        fontSize=10.5, leading=14, spaceBefore=12, spaceAfter=5,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#222222"),
    )
    footnote = ParagraphStyle(
        "footnote", parent=base["Normal"],
        fontSize=8.5, leading=12, leftIndent=0.4*cm,
        textColor=colors.HexColor("#555555"),
    )
    letterhead_name = ParagraphStyle(
        "lname", parent=base["Normal"],
        fontSize=14, leading=18,
        fontName="Helvetica-Bold",
    )

    story = []

    # Minimalist letterhead
    story.append(Paragraph("Tiefkühlkost Franken AG", letterhead_name))
    story.append(Paragraph(
        "Werk Erlangen-Süd  ·  Zirkelstraße 4  ·  91058 Erlangen",
        ParagraphStyle("lsub", parent=base["Normal"], fontSize=9, textColor=colors.grey, leading=12)
    ))
    story.append(HRFlowable(width="100%", thickness=1.0, color=colors.black, spaceAfter=6))
    story.append(Spacer(1, 0.3*cm))

    meta_rows = [
        ["Dokumentnummer:", "TKF-TECH-2025-0031"],
        ["Verfasser:", "Dipl.-Ing. Bernd Raupach, Betriebstechnik"],
        ["Datum:", "17. Februar 2025"],
        ["Status:", "Freigegeben zur Angebotsanfrage"],
        ["Gültigkeit:", "bis 31. Mai 2025"],
    ]
    mt = Table(meta_rows, colWidths=[4.5*cm, 11.5*cm])
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#333333")),
    ]))
    story.append(mt)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph(
        "Leistungsbeschreibung und Anforderungsprofil: Schockfroster und Tiefkühlanlage "
        "Werkserweiterung Erlangen-Süd, Produktionslinie PL-7",
        h1
    ))

    story.append(Paragraph("1  Anlass und Projektziel", h2))
    story.append(Paragraph(
        "Die Tiefkühlkost Franken AG plant die Inbetriebnahme einer neuen Produktionslinie (PL-7) für "
        "die Herstellung tiefgekühlter Fertiggerichte am Werk Erlangen-Süd. Kernstück der Anlage ist ein "
        "Schockfroster, der frisch produzierte Gerichte von einer Eintrittstemperatur von ca. +70 °C auf "
        "eine Kerntemperatur von mindestens −18 °C abkühlen muss, bevor die Ware in das bestehende "
        "Tiefkühllager (−18 °C Lagerhaltung) überführt wird. Diese Anforderung ergibt sich aus den "
        "Vorgaben der VO (EU) 1169/2011 und den betriebsinternen Qualitätsstandards.",
        body
    ))
    story.append(Paragraph(
        "Der vorliegende Dokument beschreibt die technischen Mindestanforderungen für die Ausschreibung "
        "der Kälteanlagentechnik. Angebote, die diese Anforderungen nicht vollständig erfüllen, können "
        "nicht berücksichtigt werden. Fragen können bis zum 31. März 2025 an b.raupach@tkf-ag.de "
        "gerichtet werden.",
        body
    ))

    story.append(Paragraph("2  Prozessanforderungen Schockfroster", h2))
    story.append(Paragraph(
        "Der Schockfroster muss einen Durchsatz von <b>0,65 t/h</b> (sechshundertfünfzig Kilogramm "
        "pro Stunde) bei einem Produktgewicht von 350–600 g je Portion gewährleisten. Der Froster ist "
        "als Spiralfroster oder Tunnelfroster auszuführen; ein Plattenfroster scheidet aufgrund der "
        "Produktgeometrie aus.",
        body
    ))
    story.append(Paragraph(
        "Die Kerntemperatur der Produkte muss innerhalb einer Absenkzeit von vier Stunden ab "
        "Einlauf sicher auf −18 °C oder kälter gebracht werden. Als Auslegungstemperatur für den "
        "Verdampfer ist −22 °C zu verwenden, um ausreichende Sicherheitsreserven gegenüber der "
        "Kerntemperaturanforderung zu gewährleisten. Die gewählte Auslegungstemperatur −22 °C ist "
        "damit der verbindliche Temperatursollwert der Kälteanlage auf der Niederdruckseite.",
        body
    ))
    story.append(Paragraph(
        "Hinweis zur Kälteleistung: Eine Vorauslegung unseres externen Ingenieurbüros (Büro für "
        "Kältetechnik Dr. Vogt, Nürnberg) hat eine erforderliche installierte Kälteleistung von "
        "ca. 280 kW für den Schockfroster ergeben. Diese Zahl gilt nur für den Schockfroster. "
        "Die Gesamtanlage einschließlich Verlustkälte und Systemreserven wird auf ca. 340 kW "
        "geschätzt. Wir bitten die Bieter, auf Basis eigener Auslegung zu kalkulieren und "
        "Abweichungen zu begründen.",
        body
    ))

    story.append(Paragraph("3  Kältemittelauswahl und Anlagensicherheit", h2))
    story.append(Paragraph(
        "Aufgrund der Standortbedingungen (Lebensmittelproduktion, geschlossene Gebäude, "
        "Personenbelegung) ist der Einsatz von Ammoniak (R717) ohne besondere Zusatzmaßnahmen "
        "nicht genehmigungsfähig. Wir bevorzugen daher transkritisches CO₂ (R744) als Kältemittel, "
        "das für Tiefkühlanwendungen in der Lebensmittelindustrie sehr gut etabliert ist. "
        "Alternativ ist ein HKW-System mit R290 (Propan) akzeptabel, sofern der Bieter die "
        "ATEX-Zoneneinteilung und die erforderlichen Sicherheitsabstände detailliert darstellt.",
        body
    ))
    story.append(Paragraph(
        "Alle sicherheitsrelevanten Komponenten müssen die Anforderungen der Norm EN 378-2 erfüllen. "
        "Der Nachweis ist mit dem Angebot zu erbringen. Weiterhin sind die Vorschriften der "
        "Betriebssicherheitsverordnung (BetrSichV) sowie die Druckgeräterichtlinie PED 2014/68/EU "
        "einzuhalten. Systeme, für die keine CE-Kennzeichnung vorliegt, werden ausgeschlossen.",
        body
    ))

    story.append(Paragraph("4  Energieeffizienz und Betriebskosten", h2))
    story.append(Paragraph(
        "Die Energiekosten am Standort Erlangen-Süd machen einen wesentlichen Teil der "
        "Betriebskosten aus. Wir erwarten daher die Angabe der Leistungszahl (COP) der Anlage "
        "am Auslegungspunkt und fordern eine Mindest-Leistungszahl von 2,3 im Schockfrosterbetrieb "
        "bei −22 °C Verdampfungstemperatur und +35 °C Verflüssigungstemperatur. "
        "Angebote mit einem COP unter diesem Mindestwert werden nicht gewertet.",
        body
    ))
    story.append(Paragraph(
        "Die Anlage soll über ein GLT-fähiges Steuerungssystem verfügen, das eine Einbindung in "
        "unser bestehendes Siemens Desigo-Gebäudeleitsystem ermöglicht. Die Datenübertragung "
        "kann über Modbus TCP oder BACnet IP erfolgen.",
        body
    ))

    story.append(Paragraph("5  Lieferumfang und Abgrenzung", h2))
    story.append(Paragraph(
        "Der Lieferumfang des Auftragnehmers umfasst Kältemaschine (Verdichter, Verflüssiger, "
        "Regeleinheit), Schockfroster-Kühlaggregat, Rohrleitungen innerhalb der Systemgrenzen, "
        "E-Anschluss ab Verteiler (nicht im Lieferumfang: Zuleitung zum Verteiler), "
        "Inbetriebnahme, Schulung des Bedienpersonals sowie Übergabedokumentation. "
        "Das Fördersystem innerhalb des Schockfrosters (Band, Spirale) kann im Angebot enthalten "
        "sein, ist aber als separater Teilpreis auszuweisen.",
        body
    ))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "¹) Die Angabe 0,65 t/h bezieht sich auf das Nettogewicht der Endprodukte ohne Verpackung. "
        "Bei Abfüllung in Kartons (Bruttogewicht ca. +12 %) ist die Kälteleistung entsprechend anzupassen.",
        footnote
    ))
    story.append(Spacer(1, 0.05*cm))
    story.append(Paragraph(
        "Tiefkühlkost Franken AG  ·  Zirkelstraße 4  ·  91058 Erlangen  ·  AG Fürth HRB 9341  ·  "
        "Vorstand: Ulrich Gaffert (Vors.), Hannelore Strobel",
        ParagraphStyle("ftr", parent=base["Normal"], fontSize=7.5, textColor=colors.grey,
                       alignment=TA_CENTER, leading=10)
    ))

    doc.build(story)
    print(f"  Written: {path}")


def main():
    print("Generating realistic IK tender PDFs...")
    build_tender_process_cooling()
    build_tender_cold_store()
    build_tender_deep_freeze()
    print("Done.")


if __name__ == "__main__":
    main()
