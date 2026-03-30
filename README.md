# OrderRace-Lbase AWS Integration

Serverless-Architektur zur Anbindung des **OrderRace**-Auftragsportals an das lokale **Lbase TMS** einer Spedition. Realisiert mit AWS SAM (API Gateway, Lambda, DynamoDB, S3).

## Architektur

```
OrderRace  --->  API Gateway  --->  Lambda (Konverter)  --->  S3 + DynamoDB
                                                                    |
Lokaler Poller  <---  API Gateway  <---  Lambda (Pull)  <-----------+
     |
     v
  Lbase TMS
```

**Eingangsrichtung:** OrderRace sendet DFUe-Daten (JSON) und Dokumente (PDF) per HTTPS POST an den `/ingest`-Endpoint. Die Lambda konvertiert die JSON ins Lbase Fortras-Format (.sdg) und legt alles in S3 ab.

**Ausgangsrichtung:** Ein lokaler Poller holt neue Dateien per `/pull` ab und importiert sie ins TMS. Dokumente aus Lbase (PODs, Rechnungen) werden per `/upload` nach AWS hochgeladen und per FTP-CSV in OrderRace verlinkt.

## Features

- **typ-Parameter**: Unterscheidung zwischen `dfue`, `audit`, `orderauto` und `document` per URL-Parameter
- **Multi-Order-Splitting**: Eine JSON mit mehreren Auftraegen erzeugt pro `onum` eine eigene .sdg-Datei
- **Automatische Update-Erkennung**: Wurde ein Auftrag bereits abgeholt, erzeugt ein erneuter `typ=dfue`-Push automatisch eine versionierte Datei (`_v{N}.sdg`)
- **Audit-Versionierung**: `typ=audit` erzeugt immer versionierte Dateien
- **OrderAuto-Rohspeicherung**: `typ=orderauto` speichert die JSON ohne Konvertierung
- **File-Level Tracking**: DynamoDB trackt pro Datei ob sie heruntergeladen wurde (verhindert doppelte Downloads)
- **Lokaler Poller mit Routing**: Automatische Zuordnung in `SDG/`, `SDG_UPDATE/`, `DOCS/` oder `ORDERAUTO/`
- **Admin Dashboard**: Geschuetztes Web-Dashboard (Cognito + CloudFront) mit Statistiken, Auftragsdetails und Event-Log
- **Fehler-Benachrichtigung**: CloudWatch Alarms + SNS E-Mail bei Lambda-Fehlern
- **Event-Logging**: Strukturiertes Audit-Log aller API-Ereignisse in DynamoDB (90 Tage TTL)

## Projektstruktur

```
template.yaml                  # SAM/CloudFormation Template
src/
  lambda_conv/                 # Ingest & Konvertierung (ORjson -> Fortras)
  lambda_pull/                 # Datenabruf fuer den Poller
  lambda_pull_ack/             # Download-Bestaetigung
  lambda_upload/               # Upload von Belegen (POD/Rechnung)
  lambda_ftp/                  # FTP-CSV-Erstellung fuer OrderRace
  lambda_serve/                # Presigned-URL-Redirect fuer Endkunden
  lambda_admin/                # Admin Dashboard API (Cognito-geschuetzt)
  local_poller/                # Lokaler Cronjob/Poller (Python)
  dashboard/                   # Admin Dashboard Frontend (SPA)
tests/                         # Testskripte fuer alle Endpoints
docs/                          # Markdown-Dokumentation
```

## Dokumentation

| Dokument | Beschreibung |
|----------|-------------|
| [docs/architecture.md](docs/architecture.md) | Architektur-Uebersicht mit Mermaid-Diagramm |
| [docs/api_endpoints.md](docs/api_endpoints.md) | Vollstaendige API-Referenz aller Endpoints |
| [docs/deployment.md](docs/deployment.md) | Schritt-fuer-Schritt Deployment-Anleitung |
| [tests/README.md](tests/README.md) | Testanleitung mit allen Testszenarien |

## Schnellstart

### Voraussetzungen

- AWS CLI konfiguriert
- AWS SAM CLI installiert
- Python 3.12

### Deployment

```bash
sam build
sam deploy --guided --parameter-overrides ApiToken=DEIN_TOKEN FTPHost=ftp.orderrace.com FTPUser=USER FTPPassword=PASS
```

### Tests ausfuehren

```bash
cd tests
pip install -r requirements.txt

# Umgebungsvariablen setzen
export API_URL="https://DEINE_API_ID.execute-api.eu-central-1.amazonaws.com/Prod"
export API_TOKEN="DEIN_TOKEN"

python test_ingest_dfue.py
python test_ingest_document.py
python test_ingest_audit.py
python test_ingest_orderauto.py
```

### Lokaler Poller

```bash
cd src/local_poller
pip install -r requirements.txt

export API_BASE_URL="https://DEINE_API_ID.execute-api.eu-central-1.amazonaws.com/Prod"
export API_KEY="DEIN_TOKEN"

python poller.py
```

## Admin Dashboard

Nach dem Deployment ist das Dashboard unter der CloudFront-URL erreichbar (siehe `DashboardUrl` im Output).

**Ersten Admin-Account anlegen:**
```bash
aws cognito-idp admin-create-user \
  --user-pool-id POOL_ID \
  --username admin \
  --user-attributes Name=email,Value=admin@firma.de Name=email_verified,Value=true \
  --temporary-password "TempPass2026!"
```

Beim ersten Login wird ein neues Passwort erzwungen (min. 12 Zeichen).

**Fehler-Benachrichtigungen aktivieren:**

E-Mail-Adressen in `samconfig.toml` unter `AlertEmail1` / `AlertEmail2` eintragen und erneut deployen. Danach die Bestaetigungs-E-Mail von AWS SNS klicken.

**Dashboard-Dateien aktualisieren:**
```bash
aws s3 sync src/dashboard/ s3://STACK-dashboard-ACCOUNT_ID/ --delete
```

## Technologie-Stack

- **Infrastructure**: AWS SAM / CloudFormation
- **Compute**: AWS Lambda (Python 3.12, ARM64)
- **API**: AWS API Gateway (Regional)
- **Storage**: AWS S3 (Ingest + Egress + Dashboard Buckets)
- **Database**: AWS DynamoDB (Pay-per-Request) -- OrderProtocol + EventLog
- **Auth**: AWS Cognito (Admin Dashboard)
- **CDN**: AWS CloudFront (Dashboard HTTPS)
- **Monitoring**: CloudWatch Alarms + SNS E-Mail
- **Konvertierung**: ORjson -> Lbase Fortras 4.1
