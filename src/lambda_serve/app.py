import os
import json
import uuid
import boto3
from botocore.config import Config

region = os.environ.get('AWS_REGION', 'eu-central-1')
s3_client = boto3.client(
    's3', 
    region_name=region,
    endpoint_url=f"https://s3.{region}.amazonaws.com",
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)

dynamodb = boto3.resource('dynamodb')

EGRESS_BUCKET = os.environ.get('EGRESS_BUCKET')
EVENT_LOG_TABLE = os.environ.get('EVENT_LOG_TABLE')


def _log_event(event_type, status_code, details='', error_msg=''):
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
            'HttpMethod': 'GET',
            'StatusCode': status_code,
            'ErrorMessage': error_msg,
            'Details': details,
            'TTL': int(now.timestamp()) + 90 * 86400,
        })
    except Exception as ex:
        print(f"EventLog write failed: {ex}")

def lambda_handler(event, context):
    """
    Lambda 5: Dokumenten-Freigabe (Serve)
    Wird vom Kunden über OrderRace Portal aufgerufen.
    Prüft (Dummy-Verifizierung) und generiert temporären S3 Link,
    um direkt auf S3 weiterzuleiten (HTTP 302).
    """
    try:
        path_params = event.get('pathParameters', {})
        document_id = path_params.get('document_id')
        
        if not document_id:
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'Missing document_id in path'})
            }
            
        # Optional: Security Checks (z.B. Authorization Header, Session Token)
        # Wenn autorisiert:
        s3_key = f"{document_id}"  # Angenommen, der Document ID ist der S3 Key
        
        # Generiere eine Presigned-URL für den EgressBucket
        url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': EGRESS_BUCKET, 'Key': s3_key},
            ExpiresIn=3600 # 1 Stunde gültig
        )
        
        _log_event('SERVE', 302, details=f"Redirected to {s3_key}")
        return {
            'statusCode': 302,
            'headers': {
                'Location': url
            }
        }
    except Exception as e:
        print(f"Error serving document: {str(e)}")
        _log_event('SERVE_ERROR', 500, error_msg=str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }
