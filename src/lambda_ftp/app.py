import os
import json
import boto3
import uuid
from ftplib import FTP

dynamodb = boto3.resource('dynamodb')

EGRESS_BUCKET = os.environ.get('EGRESS_BUCKET')
EVENT_LOG_TABLE = os.environ.get('EVENT_LOG_TABLE')
FTP_HOST = os.environ.get('FTP_HOST')
FTP_USER = os.environ.get('FTP_USER')
FTP_PASSWORD = os.environ.get('FTP_PASSWORD')


def _log_event(event_type, status_code, order_id='', details='', error_msg=''):
    if not EVENT_LOG_TABLE:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        table = dynamodb.Table(EVENT_LOG_TABLE)
        table.put_item(Item={
            'EventDate': now.strftime('%Y-%m-%d'),
            'Timestamp': int(now.timestamp() * 1000),
            'EventId': uuid.uuid4().hex,
            'EventType': event_type,
            'OrderId': order_id,
            'StatusCode': status_code,
            'ErrorMessage': error_msg,
            'Details': details,
            'TTL': int(now.timestamp()) + 90 * 86400,
        })
    except Exception as ex:
        print(f"EventLog write failed: {ex}")

def lambda_handler(event, context):
    """
    Lambda 4: FTP Upload / Link-Erstellung.
    S3 Trigger feuert, wenn neues POD oder Rechnung im EgressBucket abgelegt wird.
    Generiert CSV mit einem Referenz-Link für das OrderRace-Portal und lädt
    diese per FTP hoch.
    """
    try:
        # Event verarbeiten (ObjectCreated)
        for record in event.get('Records', []):
            bucket_name = record['s3']['bucket']['name']
            object_key = record['s3']['object']['key']
            
            base_url = os.environ.get("API_BASE_URL", "https://YOUR_API_ID.execute-api.eu-central-1.amazonaws.com/Prod/serve")
            download_link = f"{base_url}/{object_key}"
            
            # Extrahiere onum (z.B. aus dem Key `pod/11000445_abc.pdf` -> 11000445)
            filename = object_key.split('/')[-1]
            onum = filename.split('_')[0]
            doc_type_code = object_key.split('/')[0] # z.B. "pod" oder "invoice"
            
            # Mappe unseren internen Typ auf den OrderRace Dok-Typ (.77 für Rechnung, etc. gem. S34 Tracking)
            or_doc_type = "Dokument"
            if doc_type_code.lower() == "invoice":
                or_doc_type = ".77" # OrderRace Code für Rechnung
            elif doc_type_code.lower() == "pod":
                or_doc_type = ".POD" # Beispielcode für POD, muss ggf. angepasst werden
            
            # CSV Inhalt generieren nach OrderRace Vorgabe S34:
            # Spalten: onum ; url-link ; Linktext ; Sichtbarkeit
            # Trennzeichen: Semikolon (oder je nach Abstimmung), ohne Überschriften
            csv_content = f"{onum};{download_link};{or_doc_type};1\n"
            
            # FTP Upload (Mock - legt Datei im Ordner /olinks ab)
            if FTP_HOST and FTP_USER:
                print(f"Connecting to FTP {FTP_HOST} as {FTP_USER}")
                # with FTP(FTP_HOST) as ftp:
                #    ftp.login(user=FTP_USER, passwd=FTP_PASSWORD)
                #    ftp.cwd('/olinks') # Spezielles Verzeichnis gem. S34 Doku
                #    tmp_file_path = f"/tmp/doclink_{onum}_{uuid.uuid4().hex[:4]}.csv"
                #    with open(tmp_file_path, 'w') as f:
                #        f.write(csv_content)
                #    with open(tmp_file_path, 'rb') as f:
                #        ftp.storbinary(f"STOR doclink_{onum}.csv", f)
                print(f"FTP Upload for onum {onum} simulated: {csv_content.strip()}")
        
        _log_event('FTP_TRIGGER', 200, details=f"Processed {len(event.get('Records', []))} records")
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'FTP Upload logic triggered'})
        }
    except Exception as e:
        print(f"Error in FTP Trigger: {str(e)}")
        _log_event('FTP_ERROR', 500, error_msg=str(e))
        raise e
