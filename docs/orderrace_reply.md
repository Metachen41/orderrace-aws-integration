Hallo Herr Daum,

vielen Dank für den Vorschlag mit dem `typ`-Parameter -- das ist eine exzellente Idee und wir haben es genau so umgesetzt. Unsere Gegenstelle unterscheidet nun sauber zwischen Aufträgen, Audits, OrderAutos und Dokumenten.

---

### 1. URL-Syntax & Authentifizierung

**Basis-URL:**
```text
https://YOUR_API_ID.execute-api.eu-central-1.amazonaws.com/Prod/ingest
```

**Authentifizierung** (eine der drei Varianten):
- Query-Token: `?token=YOUR_SECRET_TOKEN`
- Header: `Authorization: Bearer YOUR_SECRET_TOKEN`
- Header: `X-Api-Key: YOUR_SECRET_TOKEN`

### 2. Der `typ`-Parameter

Der Typ wird als Query-Parameter an die URL angehängt:

```text
/ingest?token=TOKEN&typ=dfue
/ingest?token=TOKEN&typ=audit
/ingest?token=TOKEN&typ=orderauto
/ingest?token=TOKEN&typ=document
```

| `typ` | Verwendung |
|-------|-----------|
| `dfue` | Reguläre Auftragsdaten. Kann mehrere Aufträge in einem JSON enthalten (`orders[]`). Pro Auftrag wird eine eigene `.sdg`-Datei erzeugt. **Wird derselbe Auftrag erneut gesendet nachdem er bereits abgeholt wurde, wird automatisch eine versionierte Update-Datei erzeugt.** |
| `audit` | Explizite Korrektur/Update eines bestehenden Auftrags. Erzeugt immer versionierte Dateien (`_v1.sdg`, `_v2.sdg`, ...). |
| `orderauto` | OrderAuto-Daten. Werden ohne Konvertierung als rohe JSON gespeichert. |
| `document` | Nur Dokumente (PDF). Keine DFÜ-Verarbeitung. |

Falls `typ` nicht angegeben wird, erkennt unser System automatisch anhand des Inhalts ob es sich um eine DFÜ oder ein Dokument handelt (Rückwärtskompatibilität).

### 3. Aufbau der Requests

Alle Requests verwenden `multipart/form-data` als Content-Type.

#### Fall A: DFÜ mit Aufträgen (ein oder mehrere)

```bash
curl -X POST "https://...Prod/ingest?token=TOKEN&typ=dfue" \
  -F "dfue_file=@auftrag.json;type=application/json"
```

Die JSON-Datei enthält ein `orders[]`-Array. Jeder Auftrag darin muss ein Feld `onum` haben. Unser System splittet automatisch und erzeugt pro Auftrag eine eigene Datei.

#### Fall B: Audit-Update

```bash
curl -X POST "https://...Prod/ingest?token=TOKEN&typ=audit" \
  -F "dfue_file=@audit_update.json;type=application/json"
```

Gleiches JSON-Format wie DFÜ. Unser System erkennt anhand von `typ=audit`, dass es sich um eine Korrektur handelt, und erzeugt eine neue Version.

#### Fall C: OrderAuto

```bash
curl -X POST "https://...Prod/ingest?token=TOKEN&typ=orderauto" \
  -F "dfue_file=@orderauto_data.json;type=application/json"
```

Die JSON wird unverändert gespeichert.

#### Fall D: Dokument nachsenden

```bash
curl -X POST "https://...Prod/ingest?token=TOKEN&typ=document" \
  -F "document_file_1=@muku#DE-74078-Heilbronn#NEU#00058#Rechnung.pdf;type=application/pdf" \
  -F "doc_type_1=RE"
```

Die Auftragsnummer wird aus dem Dateinamen gelesen (4. Segment, getrennt durch `#`):
```text
[Login]#[LKZ-PLZ-Ort]#[Dokumentname]#[onum]#[Dateiname]
```

### 4. Rückmeldungen & Fehlerbehandlung

| Status | Bedeutung |
|--------|-----------|
| `200 OK` | Erfolgreich empfangen und gespeichert. Die Antwort enthält die erzeugten Dateien. |
| `401 Unauthorized` | Token fehlt oder ungültig. |
| `400 Bad Request` | Problem mit dem Request: ungültiger `typ`, fehlendes `dfue_file`, keine `onum` in JSON oder Dateiname, etc. Die Fehlermeldung gibt Aufschluss. |
| `500 Internal Server Error` | Unerwarteter Fehler. Retry-Mechanismus greift. |

### 5. Zusammenfassung

- Aufträge (DFÜ): `?typ=dfue` -- Multi-Order-fähig
- Audit-Korrekturen: `?typ=audit` -- automatische Versionierung
- OrderAuto: `?typ=orderauto` -- Rohspeicherung
- Dokumente: `?typ=document` -- `onum` aus Dateiname

Die Schnittstelle ist ab sofort live und bereit. Geben Sie Signal, sobald Sie die ersten Test-Nachrichten pushen möchten!

Mit besten Grüßen,
[Ihr Name / Gottardo]
