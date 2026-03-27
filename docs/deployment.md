# Deployment-Dokumentation: OrderRace Lbase Integration

Dieses Projekt nutzt das AWS Serverless Application Model (SAM). Dadurch lässt sich die komplette Architektur – von S3 über DynamoDB bis hin zu Lambda und API Gateway – als "Infrastructure as Code" aufbauen.

## 1. Voraussetzungen

- **AWS CLI:** Installiert und konfiguriert mit gültigen Admin-Credentials (`aws configure`).
- **AWS SAM CLI:** Installiert ([Download-Link für AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)).
- **Python 3.12:** Installiert, da die Lambdas dieses Runtime-Environment nutzen.
- **Git:** Für Versionierung (lokal und auf GitHub).

---

## 2. Lokales Setup und Build

Clone das Repository:
```bash
git clone https://github.com/IhrUnternehmen/orderrace-aws-project.git
cd orderrace-aws-project
```

Der `sam build`-Befehl durchläuft jeden Ordner in `src/`, liest die `requirements.txt` und schnürt die Deployment-Pakete.
```bash
sam build
```
Nach erfolgreichem Durchlauf erstellt SAM den Ordner `.aws-sam/`, der die fertigen Artefakte bereithält.

---

## 3. Testphase (Lokales Testen)

AWS SAM ermöglicht es, Lambda-Funktionen lokal in Docker-Containern auszuführen. Dies ist ideal, um Logikfehler (wie Konvertierungs-Bugs in `converter.py`) vor dem AWS-Upload zu prüfen.

**Lokalen API-Gateway-Mock starten:**
```bash
sam local start-api
```
Das API-Gateway ist dann auf `http://127.0.0.1:3000` erreichbar. Man kann beispielsweise mit Postman einen Ingest-Payload an `POST http://127.0.0.1:3000/ingest` schicken. 

*Achtung: S3 und DynamoDB-Ressourcen werden standardmäßig nicht vollständig lokal simuliert (es sei denn, man nutzt LocalStack), daher greift die lokale Lambda auf die echten AWS-Ressourcen des konfigurierten Accounts zu!*

---

## 4. Deployment in die AWS Cloud (Test/Produktion)

### Schritt 4.1: Interaktives Deployment
Beim ersten Deployment empfiehlt es sich, die geführte (guided) Methode zu nutzen:
```bash
sam deploy --guided
```

Dabei werden Parameter abgefragt:
- **Stack Name:** z.B. `orderrace-lbase-integration-prod`
- **AWS Region:** z.B. `eu-central-1` (Frankfurt)
- **FTPHost:** (Adresse des OrderRace FTPs)
- **FTPUser:** (FTP Login)
- **FTPPassword:** (Wird nicht im Klartext angezeigt)
- **Confirm changes before deploy:** Yes
- **Allow SAM CLI IAM role creation:** Yes (Wichtig: Erlaubt SAM, die IAM-Policies für die Lambdas anzulegen)
- **OrderRaceApi may not have authorization defined. Is this okay?:** Yes (Zur Sicherheit im Testbetrieb; später kann ein AWS Cognito oder API-Key davorgeschaltet werden)
- **Save arguments to configuration file:** Yes (`samconfig.toml` wird erstellt)

### Schritt 4.2: Erfolgs-Output
Am Ende des Deployments generiert CloudFormation/SAM die Ausgabe (Outputs), darunter:
```
Key                 ApiUrl                                                                             
Description         API Gateway endpoint URL for Prod environment                                      
Value               https://a1b2c3d4e5.execute-api.eu-central-1.amazonaws.com/Prod/                    
```
Diese Basis-URL dient als Prefix für die vier konfigurierten API-Endpunkte.

---

## 5. Spätere Updates ausrollen

Wurden Änderungen am Code (z.B. im `converter.py`) oder an der `template.yaml` vorgenommen, genügen fortan zwei Befehle, da die Parameter in der `samconfig.toml` gesichert wurden:

```bash
sam build
sam deploy
```

## 6. Überwachung und Logs (CloudWatch)

Nach dem Deployment können Log-Dateien direkt im Terminal per SAM CLI eingesehen werden.

Logs für die Ingest-Konvertierung aufrufen:
```bash
sam logs -n LambdaConvFunction --tail
```
*(Drücke `Strg+C` zum Beenden)*
