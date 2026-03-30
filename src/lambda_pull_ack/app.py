import os
import json
import uuid
import boto3
import time

dynamodb = boto3.resource('dynamodb')

PROTOCOL_TABLE = os.environ.get('PROTOCOL_TABLE')
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
    Lambda 2b: Acknowledge (POST /pull/ack).
    Bestätigt den erfolgreichen Download von Dateien durch den lokalen Cronjob.
    Verschiebt die bestätigten Dateien in DynamoDB von "FilesToDownload" zu "FilesProcessed".
    """
    try:
        if not event.get('body'):
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'Missing request body'})
            }

        body_str = event.get('body', '{}')
        if event.get('isBase64Encoded', False):
            import base64
            body_str = base64.b64decode(body_str).decode('utf-8')
            
        body = json.loads(body_str)
        # Wir erwarten nun ein Dictionary: { "order_id": ["file1_key", "file2_key"] }
        processed_files_map = body.get('processed_files', {})

        if not processed_files_map:
            # Fallback für Abwärtskompatibilität, falls noch alte Struktur gesendet wird
            processed_orders = body.get('processed_orders', [])
            if processed_orders:
                return acknowledge_orders_legacy(processed_orders)
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'No processed_files provided'})
            }

        table = dynamodb.Table(PROTOCOL_TABLE)
        updated_count = 0

        for order_id, files in processed_files_map.items():
            if not files:
                continue
                
            try:
                # Hole den aktuellen Datensatz
                response = table.get_item(Key={'OrderId': order_id})
                item = response.get('Item')
                if not item:
                    continue
                    
                current_to_download = set(item.get('FilesToDownload', []))
                current_processed = set(item.get('FilesProcessed', []))
                
                # Dateien aktualisieren
                files_set = set(files)
                new_to_download = current_to_download - files_set
                new_processed = current_processed | files_set
                
                # DynamoDB verbietet es, explizit leere Sets zu schreiben.
                # Wenn new_to_download oder new_processed leer ist, 
                # müssen wir das Attribut mit REMOVE löschen, anstatt ein Set() zu setzen.
                
                update_expr_parts = []
                expr_vals = {}
                
                if new_to_download:
                    update_expr_parts.append("FilesToDownload = :to_down")
                    expr_vals[':to_down'] = new_to_download
                
                if new_processed:
                    update_expr_parts.append("FilesProcessed = :proc")
                    expr_vals[':proc'] = new_processed
                    
                set_expr = "SET " + ", ".join(update_expr_parts) if update_expr_parts else ""
                
                remove_expr_parts = []
                if not new_to_download:
                    remove_expr_parts.append("FilesToDownload")
                if not new_processed:
                    remove_expr_parts.append("FilesProcessed")
                    
                remove_expr = "REMOVE " + ", ".join(remove_expr_parts) if remove_expr_parts else ""
                
                final_expr = f"{set_expr} {remove_expr}".strip()
                
                if final_expr:
                    # Update schreiben
                    table.update_item(
                        Key={'OrderId': order_id},
                        UpdateExpression=final_expr,
                        ExpressionAttributeValues=expr_vals if expr_vals else None
                    )
                updated_count += len(files_set)
            except Exception as e:
                print(f"Failed to acknowledge files for order_id {order_id}: {e}")
        
        _log_event('PULL_ACK', 200, details=f"Acknowledged {updated_count} files")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Acknowledged {updated_count} files',
                'updated_count': updated_count
            })
        }
    except Exception as e:
        print(f"Error in pull/ack: {str(e)}")
        _log_event('PULL_ACK_ERROR', 500, error_msg=str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal server error'})
        }

def acknowledge_orders_legacy(processed_orders):
    """Legacy Methode, falls nur Order IDs geschickt werden."""
    table = dynamodb.Table(PROTOCOL_TABLE)
    for order_id in processed_orders:
        try:
            # Wenn nur OrderID kommt, verschieben wir einfach alles
            response = table.get_item(Key={'OrderId': order_id})
            item = response.get('Item')
            if not item: continue
            
            all_files = set(item.get('FilesToDownload', [])) | set(item.get('FilesProcessed', []))
            table.update_item(
                Key={'OrderId': order_id},
                UpdateExpression="SET FilesToDownload = :empty, FilesProcessed = :all",
                ExpressionAttributeValues={
                    ':empty': set(),
                    ':all': all_files
                }
            )
        except Exception as e:
            pass
    return {'statusCode': 200, 'body': json.dumps({'message': 'Legacy ack successful'})}
