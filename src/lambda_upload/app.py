import os
import json
import boto3
import base64
import uuid

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

EGRESS_BUCKET = os.environ.get('EGRESS_BUCKET')
EVENT_LOG_TABLE = os.environ.get('EVENT_LOG_TABLE')


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
            'HttpMethod': 'POST',
            'StatusCode': status_code,
            'ErrorMessage': error_msg,
            'Details': details,
            'TTL': int(now.timestamp()) + 90 * 86400,
        })
    except Exception as ex:
        print(f"EventLog write failed: {ex}")

def lambda_handler(event, context):
    """
    Lambda 3: S3 Upload Logik.
    Nimmt PDF (POD, Rechnung) von Lbase Überwachungsmodul entgegen 
    (als Base64-codiertes JSON) und speichert es im S3_EgressBucket.
    """
    try:
        body = json.loads(event.get('body', '{}'))
        order_id = body.get('order_id')
        doc_type = body.get('doc_type', 'pod') # pod oder invoice
        file_base64 = body.get('file_data')
        
        if not order_id or not file_base64:
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'Missing order_id or file_data'})
            }

        # Decode Base64
        file_content = base64.b64decode(file_base64)
        
        # S3 Key
        s3_key = f"{doc_type}/{order_id}_{uuid.uuid4().hex[:8]}.pdf"
        
        # Upload
        s3_client.put_object(
            Bucket=EGRESS_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType='application/pdf'
        )
        
        _log_event('UPLOAD', 200, order_id=order_id, details=f"Uploaded {s3_key}")
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'File uploaded successfully', 'key': s3_key})
        }

    except Exception as e:
        print(f"Error uploading file: {str(e)}")
        _log_event('UPLOAD_ERROR', 500, error_msg=str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }
