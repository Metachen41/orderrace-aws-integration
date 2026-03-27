#!/usr/bin/env python3
"""
ORjson -> LBASE 4.1 Konverter

Konvertiert OrderRace ORjson-Dateien in das LBASE Fahrt- und
Sendungsschnittstellen-Format (Version 4.1, Tab-getrennt).
Angepasst an die Gottardo DFUe-Konfiguration.
"""

import argparse
import json
import sys
import os
from datetime import datetime

from config import (
    ADDRESS_TYPE_MAP,
    DEFAULT_HWT_GROUP,
    DEFAULT_ADR_VERSION,
    LBASE_VERSION,
    FIELD_SEP,
    LINE_END,
)


# ---------------------------------------------------------------------------
# Hilfs-Funktionen
# ---------------------------------------------------------------------------

def fmt_counter(n):
    """4-stelliger Zaehler mit fuehrenden Nullen."""
    return f"{n:04d}"


def fmt_sa(n):
    """2-stellige Satzart mit fuehrender Null."""
    return f"{n:02d}"


def fmt_num(value, total, decimals):
    """
    NUM-Feld: total = Gesamtbreite inkl. Dezimalpunkt.
    Bsp: fmt_num(1.2, 6, 3) -> '01.200'   (Spec 6,3)
         fmt_num(750, 11, 3) -> '0000750.000' (Spec 11,3)
    """
    if value is None:
        return ""
    fmt = f"{{:0{total}.{decimals}f}}"
    return fmt.format(float(value))


def fmt_num_int(value, width):
    """NUM-Feld ganzzahlig mit fuehrenden Nullen."""
    if value is None:
        return ""
    return f"{int(value):0{width}d}"


def parse_orjson_datetime(date_str, time_str=None):
    """
    Konvertiert ORjson Datum/Zeit in LBASE DATETIME (YYYYMMDDHHMM).
    date_str: 'YYYY-MM-DD'
    time_str: 'HH:MM:SS' (optional)
    """
    if not date_str:
        return ""
    d = date_str.replace("-", "")
    if time_str:
        parts = time_str.split(":")
        d += parts[0] + parts[1]
    return d


def parse_orjson_date(date_str):
    """Konvertiert 'YYYY-MM-DD' in 'YYYYMMDD'."""
    if not date_str:
        return ""
    return date_str.replace("-", "")


def parse_created_datetime(created_str):
    """
    Konvertiert header.created 'YYYY-MM-DD HH:MM:SS' in LBASE DATETIME.
    """
    if not created_str:
        now = datetime.now()
        return now.strftime("%Y%m%d%H%M")
    try:
        dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y%m%d%H%M")
    except ValueError:
        return created_str.replace("-", "").replace(":", "").replace(" ", "")[:12]


def grams_to_kg(grams):
    """Gramm -> Kilogramm als float (akzeptiert int/float/str)."""
    if grams is None:
        return None
    try:
        g = float(grams)
    except (TypeError, ValueError):
        return None
    return g / 1000.0


def mm_to_m(mm):
    """Millimeter -> Meter als float (akzeptiert int/float/str)."""
    if mm is None:
        return None
    try:
        m = float(mm)
    except (TypeError, ValueError):
        return None
    return m / 1000.0


def liter_to_cbm(liter):
    """Liter -> Kubikmeter als float (akzeptiert int/float/str)."""
    if liter is None:
        return None
    try:
        l = float(liter)
    except (TypeError, ValueError):
        return None
    return l / 1000.0


def safe_get(d, key, default=""):
    """Sicherer Zugriff auf dict-Werte."""
    val = d.get(key)
    if val is None:
        return default
    return str(val)


def build_line(far_zl, sdg_zl, bz_zl, sa, fields, keep_trailing_tabs=True):
    """
    Baut eine LBASE-Zeile zusammen.
    Identification: FarZl + SdgZl + BzZl + SA (je Tab-getrennt)
    gefolgt von den Datenfeldern (Tab-getrennt), CR/LF am Ende.

    - keep_trailing_tabs=True: trailing-leere Felder werden NICHT entfernt
      (Zeile endet mit abschliessendem Tab), wie in eurer bisherigen DFUE.
    - keep_trailing_tabs=False: trailing-leere Felder werden entfernt
      (keine abschliessenden Tabs).
    """
    if not keep_trailing_tabs:
        while fields and fields[-1] == "":
            fields.pop()
    parts = [
        fmt_counter(far_zl),
        fmt_counter(sdg_zl),
        fmt_counter(bz_zl),
        fmt_sa(sa),
    ] + fields
    return FIELD_SEP.join(parts) + LINE_END


def parse_cidlist(cidlist_str):
    """
    Parst ORjson cidlist in eine Liste von Barcodes.
    Format: 'barcode1:qty1 barcode2:qty2 ...' (Leerzeichen-getrennt)
    Gibt Liste von barcode-Strings zurueck (ggf. mit Wiederholung bei qty>1).
    """
    if not cidlist_str:
        return []
    barcodes = []
    for part in cidlist_str.split():
        if not part:
            continue
        if ":" in part:
            barcode, qty_str = part.rsplit(":", 1)
            try:
                qty = int(qty_str)
            except ValueError:
                qty = 1
            for _ in range(qty):
                barcodes.append(barcode)
        else:
            barcodes.append(part)
    return barcodes


# ---------------------------------------------------------------------------
# Satzart-Generatoren
# ---------------------------------------------------------------------------

def generate_sa01(header, partner_id="", partner_key="", test_mode=False):
    """SA01 - Header (1x pro Datei)."""
    created = parse_created_datetime(header.get("created", ""))
    flag = "T" if test_mode else "P"

    adr_adrid = ""
    suchkey = ""
    if partner_id:
        adr_adrid = partner_id.rjust(10, "0")
    if partner_key:
        suchkey = partner_key

    # Letztes Feld zusaetzlich leer, damit ein abschliessendes Tab
    # wie in eurer bestehenden DFUE-Loesung geschrieben wird.
    fields = [
        created,       # Erstell-Dat
        adr_adrid,     # Interne Adr_adrid
        flag,          # Flag
        suchkey,       # SUCHKEY / externe Adr_adrid
        LBASE_VERSION, # VERSION
        "",            # Dummy-Feld fuer abschliessendes Tab
    ]
    return [build_line(0, 0, 0, 1, fields)]


def generate_sa30(order, far_zl, sdg_zl):
    """SA30 - Sendung (1x pro Order)."""
    orgidkz = "P"
    orgid = safe_get(order, "depe")
    styid = safe_get(order, "servid")
    fraid = safe_get(order, "inco")
    fratext = safe_get(order, "incoarg")

    gval = order.get("gval")
    wert = fmt_num(0, 12, 2)
    if gval is not None and gval != "":
        try:
            gval_num = float(gval)
            wert = fmt_num(gval_num / 100.0, 12, 2)
        except (TypeError, ValueError):
            # Falls gval nicht numerisch ist, bleibt Standardwert 0.00
            pass

    wrgid = safe_get(order, "gvalcurr")

    loadday = order.get("loadday", "")
    pckt1 = order.get("pckt1", "")
    pckt2 = order.get("pckt2", "")
    termabvon = parse_orjson_datetime(loadday, pckt1) if pckt1 else ""
    termabbis = parse_orjson_datetime(loadday, pckt2) if pckt2 else ""

    delvday = order.get("delvday", "")
    delvt1 = order.get("delvt1", "")
    delvt2 = order.get("delvt2", "")
    termzuvon = parse_orjson_datetime(delvday, delvt1) if delvday else ""
    termzubis = parse_orjson_datetime(delvday, delvt2) if (delvday and delvt2) else ""

    uebid = ""
    welid = ""
    lasid = ""
    vekid = ""
    relid = ""
    vsg = ""
    such = safe_get(order, "oref1")
    zolleint = ""
    zolid = ""
    sperrig = ""
    ladeliste = ""
    stpid = safe_get(order, "stpl")
    lfnr = ""
    vsnr = ""
    datum = parse_orjson_date(order.get("oday", ""))
    stpid_lang = ""

    # Produkt-Code (Sdg_proid) gemäss LBASE 4.1 SA30.
    # Mapping nach Vorgabe über ORjson-Feld "delvc":
    # 82 -> OEC10, 83 -> OEC12, 86 -> OPC, sonst/leer -> OSC
    delvc = safe_get(order, "delvc").strip()
    if delvc == "82":
        proid = "OEC10"
    elif delvc == "83":
        proid = "OEC12"
    elif delvc == "86":
        proid = "OPC"
    else:
        proid = "OSC"

    blnummer = ""
    bldatum = ""
    termart = ""
    termzur = ""

    fields = [
        orgidkz,     # Sdg_orgidkz
        orgid,       # Sdg_orgid
        styid,       # Sdg_styid
        fraid,       # Sdg_fraid
        fratext,     # Sdg_fratext
        wert,        # Sdg_wert
        wrgid,       # Sdg_wrgid
        termabvon,   # Sdg_termabvon
        termabbis,   # Sdg_termabbis
        termzuvon,   # Sdg_termzuvon
        termzubis,   # Sdg_termzubis
        uebid,       # Sdg_uebid
        welid,       # Sdg_welid
        lasid,       # Sdg_lasid
        vekid,       # Sdg_vekid
        relid,       # Sdg_relid
        vsg,         # Sdg_vsg
        such,        # Sdg_such
        zolleint,    # Sdg_zolleint
        zolid,       # Sdg_zolid
        sperrig,     # Sdg_sperrig
        ladeliste,   # Sdg_ladeliste
        stpid,       # Sdg_stpid
        lfnr,        # Sdg_lfnr
        vsnr,        # Sdg_vsnr
        datum,       # Sdg_datum
        stpid_lang,  # Sdg_stpid (lang)
        blnummer,    # Sdg_blnummer
        bldatum,     # Sdg_bldatum
        proid,       # Sdg_proid (Produkt-Code)
        termart,     # Sdg_termart
        termzur,     # Sdg_termzur
    ]
    return [build_line(far_zl, sdg_zl, 0, 30, fields)]


def generate_sa35(order, far_zl, sdg_zl):
    """SA35 - Adressen zur Sendung (0-n pro Order)."""
    lines = []
    for addr in order.get("addr", []):
        af = addr.get("af", "")
        satid = ADDRESS_TYPE_MAP.get(af, af.upper())

        # Interne LBASE-Adress-ID: direkt aus id3 ohne Zero-Padding,
        # da eure bestehende DFUE 102692 etc. unveraendert schreibt.
        adrid = addr.get("id3") or ""

        # Externe Adress-ID (Adr_idextern) schreibt eure bestehende DFUE nicht,
        # daher hier immer leer lassen, damit kein numerischer Wert am Ende erscheint.
        idextern = ""

        ref = ""
        anrid = ""
        name1 = safe_get(addr, "name1")
        name2 = safe_get(addr, "name2")
        street = safe_get(addr, "street1")
        street2 = safe_get(addr, "street2")
        plz = safe_get(addr, "pc")
        ort = safe_get(addr, "city1")
        staid = safe_get(addr, "cc")
        sprache = ""
        uidnr = ""

        fields = [
            satid,     # Sda_satid
            adrid,     # Sda_adrid
            ref,       # Sda_ref
            anrid,     # Adr_anrid
            name1,     # Adr_name1
            name2,     # Adr_name2
            street,    # Adr_str
            street2,   # Adr_str2
            plz,       # Adr_plz
            ort,       # Adr_ort
            staid,     # Adr_staid
            sprache,   # Adr_sprache
            uidnr,     # Adr_Uidnr
            idextern,  # Adr_idextern
        ]
        lines.append(build_line(far_zl, sdg_zl, 0, 35, fields))
    return lines


def generate_sa40(order, far_zl, sdg_zl):
    """SA40 - Sendungstext (0-n pro Order)."""
    # In ORjson steht der Freitext typischerweise in "remarks".
    # Wir schreiben ihn als ZU-Text (wie in eurer bestehenden DFUE).
    txt = safe_get(order, "remarks")
    # Leeres letztes Feld erzwingt abschliessendes Tab am Zeilenende.
    fields = ["ZU", txt, ""]
    return [build_line(far_zl, sdg_zl, 0, 40, fields)]


def generate_sa56(order, far_zl, sdg_zl):
    """SA56 - Hinweistextschluessel (0-n pro Order)."""
    lines = []

    # Lieferterminart/-code aus ORjson (z.B. "delvc":"83") soll als HWT mitgegeben werden.
    # Ausgabe wie normale Hinweise: Gruppe ONLINEA, Code = delvc, ohne Zusatz.
    delvc = safe_get(order, "delvc")
    if delvc:
        lines.append(build_line(far_zl, sdg_zl, 0, 56, [DEFAULT_HWT_GROUP, delvc, "", "", ""]))

    for hi in order.get("hi", []):
        grp = DEFAULT_HWT_GROUP
        code = safe_get(hi, "key")
        zusatz = safe_get(hi, "arg")

        fields = [grp, code, "", "", zusatz]
        lines.append(build_line(far_zl, sdg_zl, 0, 56, fields))
    return lines


def generate_shipment_lines(order, far_zl, sdg_zl):
    """
    SA70 + SA72 + SA74 - Beschreibungszeilen (0-n pro Order).
    Inklusive Ebene-3-Zeilen fuer einzelne Barcodes aus cidlist.
    Gibt (lines, next_bz_zl) zurueck.
    """
    lines = []
    bz_zl = 1

    # Ebene 1/2: Sammelzeile pro sl-Eintrag
    for sl in order.get("sl", []):
        anz = fmt_num_int(sl.get("q"), 8)
        vepid = safe_get(sl, "pc")

        bgew_kg = grams_to_kg(sl.get("gweight"))
        bgew = fmt_num(bgew_kg, 11, 3) if bgew_kg is not None else ""

        ngew = ""

        wert_val = sl.get("gval")
        wert = fmt_num(wert_val / 100.0, 12, 2) if wert_val is not None else ""

        wrgid = ""
        ztarif = ""
        barcd = ""

        laenge_m = mm_to_m(sl.get("dlength"))
        laenge = fmt_num(laenge_m, 6, 3) if laenge_m is not None else ""

        breite_m = mm_to_m(sl.get("dwidth"))
        breite = fmt_num(breite_m, 6, 3) if breite_m is not None else ""

        hoehe_m = mm_to_m(sl.get("dheight"))
        hoehe = fmt_num(hoehe_m, 6, 3) if hoehe_m is not None else ""

        cbm_val = liter_to_cbm(sl.get("liter"))
        cbm = fmt_num(cbm_val, 8, 3) if cbm_val is not None else ""

        ldm = ""
        beid = "1"  # Ebene 1: Sendungsebene / Sammelzeile

        sa70_fields = [
            anz, vepid, bgew, ngew, wert, wrgid,
            ztarif, barcd, laenge, breite, hoehe,
            cbm, ldm, beid,
        ]
        lines.append(build_line(far_zl, sdg_zl, bz_zl, 70, sa70_fields))

        mark = safe_get(sl, "mark")
        if mark:
            lines.append(build_line(far_zl, sdg_zl, bz_zl, 72, [mark]))

        cont = safe_get(sl, "cont")
        if cont:
            lines.append(build_line(far_zl, sdg_zl, bz_zl, 74, [cont]))

        bz_zl += 1

    # Ebene 3: einzelne Packstuecke aus cidlist
    barcodes = parse_cidlist(order.get("cidlist", ""))
    if barcodes:
        # Standard-Nullwerte wie in eurer bisherigen DFUE-Loesung
        zero_bgew = fmt_num(0, 11, 3)
        zero_wert = fmt_num(0, 12, 2)
        zero_len = fmt_num(0, 6, 3)
        zero_cbm = fmt_num(0, 8, 3)

        for bc in barcodes:
            anz = ""          # Einzelpackstueck -> Menge leer
            vepid = ""        # Verpackungsart optional leer auf Ebene 3
            bgew = zero_bgew
            ngew = ""
            wert = zero_wert
            wrgid = ""
            ztarif = ""
            barcd = bc
            laenge = zero_len
            breite = zero_len
            hoehe = zero_len
            cbm = zero_cbm
            ldm = ""
            beid = "3"  # Ebene 3: Packstueckebene mit NVE

            sa70_fields_3 = [
                anz, vepid, bgew, ngew, wert, wrgid,
                ztarif, barcd, laenge, breite, hoehe,
                cbm, ldm, beid,
            ]
            # Barcode-Zeilen (Ebene 3) sollen ohne abschliessende Tabs enden
            lines.append(build_line(far_zl, sdg_zl, bz_zl, 70, sa70_fields_3, keep_trailing_tabs=False))
            bz_zl += 1

    return lines, bz_zl


def generate_sa77(order, far_zl, sdg_zl, start_bz_zl):
    """SA77 - Gefahrgut (0-n pro Order)."""
    lines = []
    bz_zl = start_bz_zl
    for dg in order.get("dg", []):
        if not dg:
            continue

        gefid = ""
        klasse = safe_get(dg, "gz1")
        ziffer = safe_get(dg, "unnr2")
        buchstabe = ""
        unnr = safe_get(dg, "unnr")
        code = safe_get(dg, "tcat")
        handelsname = ""

        unit = "LIT"
        bgew_kg = grams_to_kg(dg.get("gweight"))
        bgew = fmt_num(bgew_kg, 11, 2) if bgew_kg is not None else ""
        ngew = ""

        nem = dg.get("nem")
        ngewe = fmt_num(grams_to_kg(nem), 11, 2) if nem is not None else ""

        ltr = dg.get("ltr")
        cbm = fmt_num(ltr / 1000.0, 8, 3) if ltr is not None else ""

        lq_val = safe_get(dg, "lq")
        bmenge = "1" if lq_val in ("1", "LQ", "Y", "y", "J", "j") else "0"

        envh_val = safe_get(dg, "envh")
        umwelt = "1" if envh_val in ("1", "Y", "y", "J", "j") else "0"

        ausnahme = ""
        leer = ""
        typ = "ADR"
        stoffname = safe_get(dg, "tn")
        faktor = ""
        punkte = ""
        veptext = ""
        version = DEFAULT_ADR_VERSION
        vgruppe = safe_get(dg, "pcg").replace("'", "")
        klasscode = safe_get(dg, "classcode")

        nag = safe_get(dg, "nag")

        zettel_parts = [klasse]
        for gz_key in ("gz2", "gz3", "gz4"):
            gz = safe_get(dg, gz_key)
            if gz:
                zettel_parts.append(gz)
        zettel = "+".join(zettel_parts) if zettel_parts else ""

        sondervor = safe_get(dg, "sv1")
        sprache = ""
        zusatz2 = ""
        fmenge = ""
        tunnel = safe_get(dg, "trc")
        abfall = ""

        sa77_fields = [
            gefid, klasse, ziffer, buchstabe, unnr, code,
            handelsname, unit, bgew, ngew, ngewe, cbm,
            bmenge, umwelt, ausnahme, leer, typ, stoffname,
            faktor, punkte, veptext, version, vgruppe,
            klasscode, nag, "", zettel, sondervor,
            sprache, zusatz2, fmenge, tunnel, abfall,
        ]
        lines.append(build_line(far_zl, sdg_zl, bz_zl, 77, sa77_fields))
        bz_zl += 1

    return lines


def generate_sa99(total_lines):
    """SA99 - Trailer (1x pro Datei)."""
    # In eurer bestehenden DFUE ist die Zeilenanzahl nicht zero-padded (z.B. "14" statt "0000000014").
    total = str(int(total_lines))
    return [build_line(9999, 9999, 9999, 99, [total])]


# ---------------------------------------------------------------------------
# Hauptkonvertierung
# ---------------------------------------------------------------------------

def convert_orjson_to_lbase(data, partner_id="", partner_key="", test_mode=False):
    """
    Konvertiert ein ORjson-dict in eine Liste von LBASE-Zeilen.
    Reihenfolge pro Sendung: SA30 -> SA35 -> SA40 -> SA56 -> SA70/72/74 -> SA77
    """
    header = data.get("header", {})
    orders = data.get("orders", [])

    all_lines = []

    all_lines.extend(generate_sa01(header, partner_id, partner_key, test_mode))

    far_zl = 1
    for idx, order in enumerate(orders, start=1):
        sdg_zl = idx

        all_lines.extend(generate_sa30(order, far_zl, sdg_zl))
        all_lines.extend(generate_sa35(order, far_zl, sdg_zl))
        all_lines.extend(generate_sa40(order, far_zl, sdg_zl))
        all_lines.extend(generate_sa56(order, far_zl, sdg_zl))

        sl_lines, next_bz = generate_shipment_lines(order, far_zl, sdg_zl)
        all_lines.extend(sl_lines)

        dg_lines = generate_sa77(order, far_zl, sdg_zl, next_bz)
        all_lines.extend(dg_lines)

    total_before_trailer = len(all_lines)
    all_lines.extend(generate_sa99(total_before_trailer))

    return all_lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ORjson -> LBASE 4.1 Konverter (Gottardo)",
        epilog="Beispiel: python converter.py input.json -o output.txt --partner-key 102692",
    )
    parser.add_argument(
        "input",
        help="Pfad zur ORjson-Eingabedatei (JSON)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Pfad zur LBASE-Ausgabedatei (Standard: <input>.lbase.txt)",
    )
    parser.add_argument(
        "--partner-id",
        default="",
        help="Interne LBASE Adress-ID des DFUe-Partners (z.B. 0000100375)",
    )
    parser.add_argument(
        "--partner-key",
        default="",
        help="Externer Suchschluessel des DFUe-Partners (z.B. Kundennummer)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test-Modus (Flag=T statt P im Header)",
    )
    args = parser.parse_args()

    if not args.partner_id and not args.partner_key:
        print("WARNUNG: Weder --partner-id noch --partner-key angegeben. "
              "SA01 Header wird ohne Partner-Identifikation erzeugt.",
              file=sys.stderr)

    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"FEHLER: Eingabedatei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output
    if not output_path:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".lbase.txt"

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = convert_orjson_to_lbase(
        data,
        partner_id=args.partner_id,
        partner_key=args.partner_key,
        test_mode=args.test,
    )

    with open(output_path, "w", encoding="iso-8859-1", newline="") as f:
        f.writelines(lines)

    order_count = len(data.get("orders", []))
    line_count = len(lines)
    print(f"Konvertierung erfolgreich: {order_count} Sendung(en), {line_count} Zeilen")
    print(f"Ausgabedatei: {output_path}")


if __name__ == "__main__":
    main()
