# Architektur-Dokumentation: OrderRace Lbase Integration

## Übersicht

Die vorliegende Architektur realisiert die Anbindung des externen OrderRace Web-Portals an das lokale Lbase TMS der Spedition über eine Serverless-Zwischenschicht in der AWS Cloud. Dadurch können Aufträge sicher empfangen, konvertiert und an Lbase übergeben werden. Im Gegenzug können aus Lbase stammende Dokumente (PODs, Rechnungen) an OrderRace zurückgespielt werden.

## Architektur-Diagramm

Das folgende Diagramm veranschaulicht den Datenfluss über die drei Zonen:
1. Externes OrderRace Portal & Kunden
2. AWS Serverless Cloud
3. Lokales Speditions-Netzwerk (On-Premises)

```mermaid
flowchart TD
    %% Styling
    classDef aws fill:#FF9900,stroke:#232F3E,stroke-width:2px,color:white;
    classDef local fill:#0052cc,stroke:#003366,stroke-width:2px,color:white;
    classDef external fill:#00a859,stroke:#007733,stroke-width:2px,color:white;
    classDef db fill:#336699,stroke:#232F3E,stroke-width:2px,color:white;

    subgraph Zone1 ["1. OrderRace & Kunde (Extern)"]
        Kunde(("Kunde")):::external
        OR["OrderRace Web-Portal"]:::external
        OR_FTP["OrderRace FTP Server"]:::external
    end

    subgraph Zone2 ["2. AWS Cloud (Serverless Architektur)"]
        API_IN["API Gateway 1<br>(Empfang aus OR)"]:::aws
        LAMBDA_CONV["Lambda 1 (Python)<br>JSON zu Fortras Konv."]:::aws
        DDB[("DynamoDB<br>Protokoll & Status")]:::db
        S3_IN[("S3 Bucket 1<br>(Eingang: .sdg & Docs)")]:::db
        
        API_PULL["API Gateway 2<br>(Abruf durch Lbase)"]:::aws
        LAMBDA_PULL["Lambda 2<br>Abruf-Steuerung"]:::aws

        API_OUT["API Gateway 3<br>(Upload POD/Rechnung)"]:::aws
        LAMBDA_UPLOAD["Lambda 3<br>S3 Upload Logik"]:::aws
        S3_OUT[("S3 Bucket 2<br>(Ausgang: PODs & Rech.)")]:::db
        LAMBDA_FTP["Lambda 4 (S3 Trigger)<br>FTP-Link Erstellung"]:::aws
        
        API_SERVE["API Gateway 4<br>(Dokumenten-Freigabe)"]:::aws
        LAMBDA_SERVE["Lambda 5<br>Verifizierung & URL Generierung"]:::aws
    end

    subgraph Zone3 ["3. Lokale Spedition (On-Premises)"]
        CRON["Lokaler CronJob / Poller"]:::local
        LBASE[("Lbase TMS")]:::db
        LBASE_MOD["Lbase Überwachungs-Modul"]:::local
    end

    %% Schritt 1-5: Auftragserfassung & AWS Speicherung (Asynchron/Multipart)
    Kunde -->|"1. Auftrag erfasst"| OR
    OR -->|"2a. HTTP POST (Multipart) DFÜ"| API_IN
    OR -->|"2b. HTTP POST (Multipart) Docs"| API_IN
    API_IN --> LAMBDA_CONV
    LAMBDA_CONV -->|"3. Wandelt JSON in Lbase Fortras um"| LAMBDA_CONV
    LAMBDA_CONV -->|"4. Speichert .sdg"| S3_IN
    LAMBDA_CONV -->|"5. Speichert Dokumente"| S3_IN
    LAMBDA_CONV -.->|"Erstellt/Updated Eintrag"| DDB

    %% Schritt 6-8: Abruf in lokales TMS
    CRON -->|"6a. GET /pull"| API_PULL
    API_PULL --> LAMBDA_PULL
    LAMBDA_PULL <-->|"Prüft RECEIVED Einträge"| DDB
    LAMBDA_PULL <-->|"Holt Presigned URLs"| S3_IN
    LAMBDA_PULL -->|"Liefert .sdg & PDFs URLs"| CRON
    CRON -->|"6b. POST /pull/ack"| API_PULL
    API_PULL -->|"Update Status auf PROCESSED"| DDB
    CRON -->|"7. Importiert DFÜ inkl. O#"| LBASE
    CRON -->|"8. Importiert Docs nach Typ"| LBASE

    %% Schritt 9-11: Upload von POD/Rechnung zu OrderRace
    LBASE_MOD -->|"Überwacht Lbase"| LBASE
    LBASE_MOD -->|"9. Erkennt neues POD/Rechnung"| API_OUT
    API_OUT --> LAMBDA_UPLOAD
    LAMBDA_UPLOAD -->|"10. Speichert PDF in S3"| S3_OUT
    S3_OUT -->|"10. S3 Trigger feuert"| LAMBDA_FTP
    LAMBDA_FTP -->|"11. Loggt via FTP ein &<br>legt CSV mit Link ab"| OR_FTP

    %% Schritt 12: Kunde ruft Dokument ab
    OR_FTP -.->|"Verknüpft Link im Portal"| OR
    Kunde -->|"Klickt auf Beleg-Link"| API_SERVE
    API_SERVE -->|"12. Startet"| LAMBDA_SERVE
    LAMBDA_SERVE -->|"Prüft & generiert temporären Link"| S3_OUT
    LAMBDA_SERVE -.->|"HTTP 302 Redirect zum S3 PDF"| Kunde
```

## Ablauf-Beschreibung

### 1. Ingestion (Eingang - Multipart & Asynchron)
Sobald ein Kunde einen Auftrag im Portal erfasst, pusht der OrderRace Daemon separate HTTP POST (multipart/form-data) Requests an das zentrale API Gateway (`/ingest`). Der Query-Parameter `typ` steuert die Verarbeitung:
- **`typ=dfue`**: Auftrags-DFÜ mit Multi-Order-Support. Pro Auftrag in `orders[]` wird eine eigene `.sdg`-Datei erzeugt und ein DynamoDB-Eintrag angelegt.
- **`typ=audit`**: Audit-Update/Korrektur. Erzeugt versionierte Dateien (`sdg/{onum}_v{N}.sdg`) mit automatisch inkrementierter `AuditVersion` in DynamoDB.
- **`typ=orderauto`**: OrderAuto-Daten werden ohne Konvertierung als rohe JSON in S3 unter `orderauto/` gespeichert.
- **`typ=document`**: Nur Dokumente (PDF). Die `onum` wird aus dem strukturierten Dateinamen gelesen.

Die Lambda-Funktion `lambda_conv` parst den Multipart-Payload, routet anhand des `typ`-Parameters und legt die Dateien im `IngestBucket` ab. Ein Eintrag in DynamoDB (`FilesToDownload`) wird erstellt oder erweitert.

### 2. Polling (Abruf nach Lokal & Acknowledge)
Ein lokaler CronJob in der Spedition fragt in regelmäßigen Abständen den API-Endpunkt `/pull` ab. Die Funktion `lambda_pull` liefert für alle Datensätze mit Status `RECEIVED` Presigned-URLs für den direkten S3-Download. Nach erfolgreichem Download ins lokale Netz ruft der CronJob den Endpunkt `/pull/ack` auf. Die Funktion `lambda_pull_ack` markiert diese Bestellungen in DynamoDB als `PROCESSED`, um ein erneutes Herunterladen zu verhindern.

### 3. Egress (Ausgang)
Sobald im Lbase neue Status-Updates oder Dokumente (z.B. POD/Rechnung) verfügbar sind, werden sie per API-Aufruf an `/upload` übergeben. `lambda_upload` speichert die PDF-Datei im `EgressBucket`. Ein Event-Trigger startet daraufhin `lambda_ftp`, welche eine CSV-Datei mit Verlinkungen auf dem OrderRace-FTP-Server ablegt.

### 4. Serve (Freigabe)
Klickt ein Kunde in OrderRace auf den von der FTP-Rückmeldung erzeugten Link, ruft dies den `/serve/{document_id}` Endpunkt auf. Die Funktion `lambda_serve` prüft kurz die Gültigkeit, generiert einen temporären S3-Download-Link und führt einen HTTP 302 Redirect direkt zur PDF-Datei im Browser des Kunden aus.

### 5. Admin Dashboard & Monitoring

Das System verfuegt ueber ein geschuetztes Admin-Dashboard:

- **Hosting**: Statische SPA in S3, ausgeliefert ueber CloudFront (HTTPS)
- **Authentifizierung**: AWS Cognito User Pool (kein Self-Sign-Up, nur Admin-erstellte Accounts)
- **Admin API**: `lambda_admin` bedient `/admin/api/*`-Routen mit Cognito-Authorizer
- **Event-Logging**: Alle Lambda-Funktionen schreiben strukturierte Events in eine `EventLogTable` (DynamoDB mit TTL)
- **Fehler-Benachrichtigungen**: CloudWatch Alarms auf alle 7 Lambda-Funktionen, bei Fehlern Benachrichtigung per SNS (E-Mail)

**Dashboard-Bereiche:**
- Uebersicht mit Statistiken (Auftraege gesamt, heute, nach Typ, Fehlerquote)
- Auftragslistee mit Status-Anzeige (Offen / Teilweise / Abgeholt)
- Auftrags-Detail mit Dateistatus und Event-Verlauf
- Event-Log und Fehler-Log
- CloudWatch-Metriken (API-Aufrufe, Latenz, Fehler pro Lambda)
