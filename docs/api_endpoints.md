# API Dokumentation: OrderRace Lbase

Diese API wird über das AWS API Gateway als zentraler Einstiegspunkt für die gesamte Serverless-Architektur betrieben. Die Basis-URL (Endpoint) wird nach dem erfolgreichen SAM Deployment ausgegeben.

---

## 1. POST `/ingest`
**Verantwortliche Lambda:** `lambda_conv`

Nimmt neue Aufträge, Audit-Updates, OrderAuto-Daten und Dokumente vom externen OrderRace-Portal entgegen. Der Typ der Daten wird über den Query-Parameter `typ` gesteuert.

### Authentifizierung
Unterstützt drei Varianten:
- Querystring: `/ingest?token=SECRET`
- Header: `Authorization: Bearer SECRET`
- Header: `X-Api-Key: SECRET`

### Query-Parameter `typ`

| Wert | Beschreibung |
|------|-------------|
| `dfue` | Auftrags-DFÜ. Multi-Order: pro Auftrag in `orders[]` wird eine eigene `.sdg`-Datei erzeugt. |
| `audit` | Audit-Update. Wie `dfue`, aber mit Versionierung: `sdg/{onum}_v{N}.sdg`. |
| `orderauto` | OrderAuto-Daten. JSON wird ohne Konvertierung roh in S3 gespeichert. |
| `document` | Nur Dokument(e). Keine DFÜ-Verarbeitung. |

**Rückwärtskompatibilität:** Fehlt `typ`, wird auto-detected:
- `dfue_file` vorhanden -> `dfue`
- Nur `document_file_*` vorhanden -> `document`

### Request Body (`multipart/form-data`)
- `file`: Die Datei (JSON oder PDF). Der `typ`-Parameter bestimmt die Interpretation:
  - `typ=dfue/audit/orderauto` -> JSON-Auftragsdatei
  - `typ=document` -> Dokument (PDF)
- `doc_type_N`: Zuordnungscode (z.B. LS, RE) für das Dokument N (String)

**Rückwärtskompatibel** werden auch `dfue_file` und `document_file_N` weiterhin akzeptiert.

### Ableitung der Auftragsnummer (`onum`)
- **DFÜ/Audit**: Pro Auftrag aus `orders[].onum` in der JSON
- **Dokumente**: Aus dem Multipart-Dateinamen:
  `login#LKZ-PLZ-Ort#Dokumentname#onum#Dateiname`
  Beispiel: `muku#DE-74078-Heilbronn#NEU#00058#Beispiel-Datei.pdf`
- **OrderAuto**: Identifier wird aus `header.custlogin` + Timestamp generiert

### Speicherlogik nach `typ`

#### `typ=dfue` (Multi-Order, automatische Update-Erkennung)
- Über `orders[]` iterieren, pro Auftrag:
  - **Neuer Auftrag** (noch nie abgeholt): Fortras-Konvertierung -> `sdg/{onum}.sdg`
  - **Update** (Poller hat die ursprüngliche `.sdg` bereits abgeholt): Automatische Versionierung -> `sdg/{onum}_v{N}.sdg`. Der Poller erkennt anhand des `_v`-Suffixes, dass es ein Update ist, und speichert die Datei in `SDG_UPDATE/` statt `SDG/`.
  - DynamoDB-Eintrag mit `OrderId = onum`, ggf. `AuditVersion` inkrementiert

#### `typ=audit` (Versionierung)
- Über `orders[]` iterieren, pro Auftrag:
  - `AuditVersion` aus DynamoDB lesen (default 0), inkrementieren
  - Fortras-Konvertierung -> `sdg/{onum}_v{N}.sdg`
  - DynamoDB: `AuditVersion` hochsetzen, Datei in `FilesToDownload`

#### `typ=orderauto` (Rohspeicherung)
- JSON wird ohne Konvertierung unter `orderauto/{login}_{timestamp}.json` gespeichert
- DynamoDB-Eintrag mit `OrderId = OAUTO_{login}_{timestamp}`

#### `typ=document`
- PDF unter `docs/{onum}/{doctype}_{filename}` gespeichert
- DynamoDB `FilesToDownload` wird um den Key erweitert

### Responses

* **200 OK**
  ```json
  {
    "message": "Successfully processed payload",
    "typ": "dfue",
    "orders": {
      "11000446": ["sdg/11000446.sdg"],
      "11000447": ["sdg/11000447.sdg"]
    },
    "saved_files": ["sdg/11000446.sdg", "sdg/11000447.sdg"],
    "order_id": "11000446"
  }
  ```
  (`order_id` nur bei Single-Order-Responses)

* **200 OK** (Audit)
  ```json
  {
    "message": "Successfully processed payload",
    "typ": "audit",
    "orders": {"11000446": ["sdg/11000446_v2.sdg"]},
    "saved_files": ["sdg/11000446_v2.sdg"],
    "order_id": "11000446"
  }
  ```

* **200 OK** (OrderAuto)
  ```json
  {
    "message": "Successfully processed payload",
    "typ": "orderauto",
    "orders": {"OAUTO_Hepco_1711440000": ["orderauto/Hepco_1711440000.json"]},
    "saved_files": ["orderauto/Hepco_1711440000.json"],
    "order_id": "OAUTO_Hepco_1711440000"
  }
  ```

* **401 Unauthorized**
  ```json
  {"message": "Unauthorized. Provide the token via ?token=... or Authorization: Bearer ..."}
  ```

* **400 Bad Request**
  ```json
  {"message": "Unknown typ 'invalid'. Valid values: audit, dfue, document, orderauto"}
  ```

### Beispiel-Requests (cURL)

**DFÜ (Single oder Multi-Order):**
```bash
curl -X POST "https://API_URL/ingest?token=TOKEN&typ=dfue" \
  -F "file=@auftrag.json;type=application/json"
```

**Audit-Update:**
```bash
curl -X POST "https://API_URL/ingest?token=TOKEN&typ=audit" \
  -F "file=@audit_update.json;type=application/json"
```

**OrderAuto:**
```bash
curl -X POST "https://API_URL/ingest?token=TOKEN&typ=orderauto" \
  -F "file=@orderauto_data.json;type=application/json"
```

**Dokument (mit strukturiertem Dateinamen):**
```bash
curl -X POST "https://API_URL/ingest?token=TOKEN&typ=document" \
  -F "file=@/tmp/xyz123.pdf;filename=muku#DE-74078-Heilbronn#NEU#00058#Rechnung.pdf;type=application/pdf" \
  -F "doc_type_1=RE"
```

---

## 2. GET `/pull`
**Verantwortliche Lambda:** `lambda_pull`

Schnittstelle für den internen Poller/CronJob (Spedition) zum Abruf offener und neu eingegangener Datensätze aus DynamoDB und S3.

### Response
* **200 OK**
  ```json
  {
    "items": [
      {
        "order_id": "11000446",
        "downloads": [
          {
            "file_key": "sdg/11000446.sdg",
            "url": "https://s3.eu-central-1.amazonaws.com/... (Presigned URL)"
          },
          {
            "file_key": "sdg/11000446_v1.sdg",
            "url": "https://s3.eu-central-1.amazonaws.com/... (Presigned URL)"
          },
          {
            "file_key": "docs/11000446/LS_Lieferschein.pdf",
            "url": "https://s3.eu-central-1.amazonaws.com/... (Presigned URL)"
          }
        ]
      },
      {
        "order_id": "OAUTO_Hepco_1711440000",
        "downloads": [
          {
            "file_key": "orderauto/Hepco_1711440000.json",
            "url": "https://s3.eu-central-1.amazonaws.com/... (Presigned URL)"
          }
        ]
      }
    ]
  }
  ```

---

## 3. POST `/pull/ack`
**Verantwortliche Lambda:** `lambda_pull_ack`

Schnittstelle für den internen Poller/CronJob, um erfolgreiche Downloads zu bestätigen. Verschiebt Dateien von `FilesToDownload` nach `FilesProcessed` in DynamoDB.

### Request Body (JSON)
```json
{
  "processed_files": {
    "11000446": [
      "sdg/11000446.sdg",
      "docs/11000446/ZOLL_Beispiel-Datei.pdf"
    ]
  }
}
```

### Response
* **200 OK**
  ```json
  {"message": "Acknowledged 2 files", "updated_count": 2}
  ```

---

## 4. POST `/upload`
**Verantwortliche Lambda:** `lambda_upload`

API zum Hochladen von Belegen (POD, Rechnung) durch die lokale Spedition / das Lbase-Überwachungsmodul.

### Request Body (JSON)
```json
{
  "order_id": "11000446",
  "doc_type": "pod",
  "file_data": "JVBERi0xLjMKJcTl8uXrp/Og0MTGCjQgMCBvYmoKPDwg... (Base64)"
}
```

### Response
* **200 OK**
  ```json
  {"message": "File uploaded successfully", "key": "pod/11000446_a1b2c3d4.pdf"}
  ```
* **400 Bad Request**
  ```json
  {"message": "Missing order_id or file_data"}
  ```

---

## 5. GET `/serve/{document_id}`
**Verantwortliche Lambda:** `lambda_serve`

Wird von Endkunden über den in OrderRace hinterlegten Link aufgerufen. Erzeugt eine temporäre S3-Presigned-URL und leitet per HTTP 302 weiter.

### Path Parameters
* `document_id`: S3-Schlüssel des Dokuments im `EgressBucket`

### Response
* **302 Found (Redirect)** zum S3-Presigned-URL
* **400 Bad Request**: `{"message": "Missing document_id in path"}`

---

## Poller-Routing (Lokaler CronJob)

Der lokale Poller (`src/local_poller/poller.py`) routet heruntergeladene Dateien automatisch:

| S3-Prefix | Pattern | Lokales Verzeichnis |
|-----------|---------|-------------------|
| `sdg/` | `{onum}.sdg` (ohne `_v`) | `C:\Lbase\Import\SDG\` |
| `sdg/` | `{onum}_v{N}.sdg` (mit `_v`) | `C:\Lbase\Import\SDG_UPDATE\` |
| `docs/` | beliebig | `C:\Lbase\Import\DOCS\` |
| `orderauto/` | beliebig | `C:\Lbase\Import\ORDERAUTO\` |
