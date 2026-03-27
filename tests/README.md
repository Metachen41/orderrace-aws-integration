# Test-Phase: AWS Deployment prüfen

Nachdem der `sam deploy --guided` Befehl (wie in [deployment.md](../docs/deployment.md) beschrieben) erfolgreich durchgeführt wurde, erhält man eine `ApiUrl`. Diese URL ist der Eintritt in die Cloud.

## 1. Vorbereitung

```bash
cd tests
pip install -r requirements.txt
```

Die Skripte haben die URL und das Token bereits eingetragen. Bei Bedarf kann man `API_URL` und `TOKEN` oben in jedem Skript anpassen.

## 2. Testdurchlauf

### Schritt 1: DFÜ einsenden (mit Multi-Order-Test)

Sendet `docs/test.json` als `?typ=dfue`. Enthält zusätzlich einen Multi-Order-Test, der zwei Aufträge gleichzeitig schickt.

```bash
python test_ingest_dfue.py
```

**Erwartetes Ergebnis:** Status 200. Pro Auftrag eine eigene `.sdg`-Datei und DynamoDB-Eintrag.

### Schritt 2: Dokument nachsenden

OrderRace pusht nachträglich ein PDF für denselben Auftrag.

```bash
python test_ingest_document.py
```

**Erwartetes Ergebnis:** Status 200. PDF wird unter `docs/{onum}/` in S3 abgelegt. DynamoDB `FilesToDownload` wird um den Dokumenten-Key erweitert.

### Schritt 3: Audit-Update senden

Sendet denselben Auftrag zweimal mit `?typ=audit`. Beim ersten Lauf entsteht `_v1.sdg`, beim zweiten `_v2.sdg`.

```bash
python test_ingest_audit.py
```

**Erwartetes Ergebnis:** Status 200. `AuditVersion` in DynamoDB wird inkrementiert. Die versionierten Dateien erscheinen in `FilesToDownload`.

### Schritt 4: OrderAuto senden

Sendet eine JSON als `?typ=orderauto`. Keine Fortras-Konvertierung, die Datei wird roh in S3 unter `orderauto/` gespeichert.

```bash
python test_ingest_orderauto.py
```

**Erwartetes Ergebnis:** Status 200. DynamoDB-Eintrag mit `OAUTO_`-Prefix.

### Schritt 5: Poller ausführen

Der lokale Poller holt alle neuen Dateien ab und routet sie in die richtigen Verzeichnisse:
- `sdg/{onum}.sdg` -> `C:\Lbase\Import\SDG\`
- `sdg/{onum}_v{N}.sdg` -> `C:\Lbase\Import\SDG_UPDATE\`
- `docs/...` -> `C:\Lbase\Import\DOCS\`
- `orderauto/...` -> `C:\Lbase\Import\ORDERAUTO\`

```bash
cd ../src/local_poller
python poller.py
```

## 3. Nächste Schritte

Wenn alle Tests erfolgreich sind, ist die AWS-Architektur bereit für den Produktiveinsatz mit OrderRace.
