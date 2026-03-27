import os
import json
import boto3
from botocore.config import Config

region = os.environ.get('AWS_REGION', 'eu-central-1')
# Forciere den regionalen S3-Endpoint und Virtual Hosting Style
s3_client = boto3.client(
    's3', 
    region_name=region,
    endpoint_url=f"https://s3.{region}.amazonaws.com",
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)

dynamodb = boto3.resource('dynamodb')

PROTOCOL_TABLE = os.environ.get('PROTOCOL_TABLE')
INGEST_BUCKET = os.environ.get('INGEST_BUCKET')

def lambda_handler(event, context):
    """
    Lambda 2: Abruf-Steuerung.
    Überprüft DynamoDB auf neue Aufträge/Dokumente und generiert S3 Presigned URLs 
    für die entsprechenden Dateien (.sdg und Docs).
    Gibt die Liste der abrufbaren Dateien an den lokalen Poller (CronJob) zurück.
    """
    try:
        table = dynamodb.Table(PROTOCOL_TABLE)
        # Scan nach allen Einträgen
        response = table.scan()
        items = response.get('Items', [])
        
        results = []
        for item in items:
            order_id = item.get('OrderId')
            
            # File-Level Tracking: Lade nur Dateien, die in FilesToDownload stehen.
            files_to_download = item.get('FilesToDownload', [])
            
            download_urls = []
            for file_key in files_to_download:
                if not file_key:
                    continue
                # Generiere Presigned URL für jede Datei
                url = s3_client.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={'Bucket': INGEST_BUCKET, 'Key': file_key},
                    ExpiresIn=3600 # 1 Stunde gültig
                )
                download_urls.append({
                    'file_key': file_key,
                    'url': url
                })

            if download_urls:
                results.append({
                    'order_id': order_id,
                    'downloads': download_urls,
                    'timestamp': str(item.get('Timestamp'))
                })
        
        return {
            'statusCode': 200,
            'body': json.dumps({'items': results})
        }
    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }
