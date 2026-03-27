"""
Mapping-Tabellen fuer die ORjson -> LBASE 4.1 Konvertierung.
Angepasst an die Gottardo Adresstypen und DFUe-Konfiguration.
"""

# ORjson Adresstyp (af) -> LBASE Sendungsadresstyp (Sda_satid)
# Codes gemaess Gottardo LBASE Konfiguration
ADDRESS_TYPE_MAP = {
    "a": "Abs",    # Absender / Lieferant
    "e": "Empf",   # Empfaenger
    "f": "RECH",   # Frachtzahler -> Rechnungsempfaenger
    "g": "AUFG",   # Auftraggeber
    "h": "ABH",    # Abholort / Holadresse -> Abholadresse
    "l": "SANL",   # Ladeort -> Selbstanlieferer
    "n": "NN",     # Notify -> NN-Rechnungsempfaenger
    "t": "NEC",    # Neutralempfaenger
    "u": "ZS",     # Frachtfuehrer -> Zustellspediteur
    "z": "ZUST",   # abweichende Zustelladresse
    "o": "VS",     # Zollanmelder -> Verzollungsspediteur
}

# Standard HWT-Gruppe fuer Hinweistextschluessel (SA56)
DEFAULT_HWT_GROUP = "ONLINEA"

# Standard ADR-Version fuer Gefahrgut (SA77)
DEFAULT_ADR_VERSION = "ADR2017"

# LBASE Schnittstellenversion
LBASE_VERSION = "4.1"

# Feld-Trennzeichen (Tab)
FIELD_SEP = "\t"

# Zeilenende (CR/LF)
LINE_END = "\r\n"
