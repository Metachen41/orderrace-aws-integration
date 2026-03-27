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

EGRESS_BUCKET = os.environ.get('EGRESS_BUCKET')

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
        
        return {
            'statusCode': 302,
            'headers': {
                'Location': url
            }
        }
    except Exception as e:
        print(f"Error serving document: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }
