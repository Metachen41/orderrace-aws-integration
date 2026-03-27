import os
import json
import boto3
import base64
import uuid

s3_client = boto3.client('s3')

EGRESS_BUCKET = os.environ.get('EGRESS_BUCKET')

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
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'File uploaded successfully', 'key': s3_key})
        }

    except Exception as e:
        print(f"Error uploading file: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }
