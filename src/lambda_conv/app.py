import json
import os
import boto3
import uuid
import time
import base64
from requests_toolbelt.multipart import decoder
from converter import convert_orjson_to_lbase

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

INGEST_BUCKET = os.environ.get('INGEST_BUCKET')
PROTOCOL_TABLE = os.environ.get('PROTOCOL_TABLE')
EVENT_LOG_TABLE = os.environ.get('EVENT_LOG_TABLE')
EXPECTED_TOKEN = os.environ.get('API_TOKEN', '')
VALID_TYPES = frozenset(('dfue', 'audit', 'orderauto', 'document'))


def _log_event(event_type, status_code, event=None, order_id='', typ='', error_msg='', details=''):
    if not EVENT_LOG_TABLE:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        table = dynamodb.Table(EVENT_LOG_TABLE)
        source_ip = ''
        http_method = ''
        if event:
            rc = event.get('requestContext', {})
            identity = rc.get('identity', {})
            source_ip = identity.get('sourceIp', '')
            http_method = rc.get('httpMethod', '')
        table.put_item(Item={
            'EventDate': now.strftime('%Y-%m-%d'),
            'Timestamp': int(now.timestamp() * 1000),
            'EventId': uuid.uuid4().hex,
            'EventType': event_type,
            'OrderId': order_id,
            'Typ': typ,
            'HttpMethod': http_method,
            'SourceIp': source_ip,
            'StatusCode': status_code,
            'ErrorMessage': error_msg,
            'Details': details,
            'TTL': int(now.timestamp()) + 90 * 86400,
        })
    except Exception as ex:
        print(f"EventLog write failed: {ex}")


# ---------------------------------------------------------------------------
# Multipart helpers
# ---------------------------------------------------------------------------

def get_header(headers, key):
    key = key.lower()
    for k, v in headers.items():
        if k.decode('utf-8').lower() == key:
            return v.decode('utf-8')
    return None


def extract_filename(content_disposition):
    if not content_disposition:
        return None
    for part in content_disposition.split(';'):
        part = part.strip()
        if part.startswith('filename='):
            return part.split('=', 1)[1].strip('"\'')
    return None


def extract_name(content_disposition):
    if not content_disposition:
        return None
    for part in content_disposition.split(';'):
        part = part.strip()
        if part.startswith('name='):
            return part.split('=', 1)[1].strip('"\'')
    return None


# ---------------------------------------------------------------------------
# Auth & request helpers
# ---------------------------------------------------------------------------

def get_request_token(event):
    query_params = event.get('queryStringParameters') or {}
    token = (query_params.get('token') or '').strip()
    if token:
        return token

    headers = event.get('headers') or {}
    authorization = headers.get('authorization') or headers.get('Authorization') or ''
    if authorization.lower().startswith('bearer '):
        return authorization[7:].strip()

    api_key = headers.get('x-api-key') or headers.get('X-Api-Key') or headers.get('X-API-Key')
    if api_key:
        return api_key.strip()

    return None


def get_content_type(event):
    headers = event.get('headers') or {}
    return headers.get('content-type') or headers.get('Content-Type')


# ---------------------------------------------------------------------------
# Filename / path helpers
# ---------------------------------------------------------------------------

def sanitize_path_segment(value):
    sanitized = (value or '').strip()
    sanitized = sanitized.replace('/', '_').replace('\\', '_')
    return sanitized or 'UNSPECIFIED'


def parse_document_filename(filename):
    parsed = {
        'source_filename': filename,
        'stored_filename': filename,
        'document_label': None,
        'order_id': None,
        'login': None,
        'recipient_hint': None,
    }
    if not filename:
        return parsed

    parts = [part.strip() for part in filename.split('#', 4)]
    if len(parts) != 5:
        return parsed

    parsed['login'] = parts[0] or None
    parsed['recipient_hint'] = parts[1] or None
    parsed['document_label'] = parts[2] or None
    parsed['order_id'] = parts[3] or None
    parsed['stored_filename'] = parts[4] or filename
    return parsed


# ---------------------------------------------------------------------------
# typ resolution
# ---------------------------------------------------------------------------

def resolve_typ(event, has_dfue, has_documents):
    query_params = event.get('queryStringParameters') or {}
    typ = (query_params.get('typ') or '').strip().lower()
    if typ:
        if typ not in VALID_TYPES:
            return None, f"Unknown typ '{typ}'. Valid values: {', '.join(sorted(VALID_TYPES))}"
        return typ, None
    if has_dfue:
        return 'dfue', None
    if has_documents:
        return 'document', None
    return None, 'No typ parameter given and no processable content (file, dfue_file, or document_file_*) found'


# ---------------------------------------------------------------------------
# DynamoDB upsert (shared by all handlers)
# ---------------------------------------------------------------------------

def upsert_order(table, order_id, saved_files, data_size, data_type, audit_version=None):
    response = table.get_item(Key={'OrderId': order_id})
    item = response.get('Item')

    if item:
        current_to_download = set(item.get('FilesToDownload', []))
        current_to_download.update(saved_files)

        update_parts = [
            "#ts = :timestamp",
            "FilesToDownload = :new_files",
            "DataType = :dtype",
        ]
        expr_vals = {
            ':timestamp': int(time.time()),
            ':new_files': current_to_download,
            ':dtype': data_type,
            ':size': data_size,
        }
        if audit_version is not None:
            update_parts.append("AuditVersion = :av")
            expr_vals[':av'] = audit_version

        table.update_item(
            Key={'OrderId': order_id},
            UpdateExpression="SET " + ", ".join(update_parts) + " ADD DataSize :size",
            ExpressionAttributeNames={'#ts': 'Timestamp'},
            ExpressionAttributeValues=expr_vals,
        )
    else:
        new_item = {
            'OrderId': order_id,
            'Timestamp': int(time.time()),
            'FilesToDownload': set(saved_files),
            'DataSize': data_size,
            'DataType': data_type,
        }
        if audit_version is not None:
            new_item['AuditVersion'] = audit_version
        table.put_item(Item=new_item)


# ---------------------------------------------------------------------------
# typ handlers
# ---------------------------------------------------------------------------

def _order_sdg_already_processed(item, onum):
    """Returns True if any sdg file for this onum was already downloaded by the poller."""
    if not item:
        return False
    processed = item.get('FilesProcessed', set())
    sdg_prefix = f"sdg/{onum}"
    return any(f.startswith(sdg_prefix) and f.endswith('.sdg') for f in processed)


def handle_dfue(dfue_json, table):
    """Multi-order split: one .sdg per order in orders[].

    If the poller has already downloaded an earlier .sdg for the same onum,
    this is treated as an UPDATE: a versioned file (sdg/{onum}_v{N}.sdg)
    is created so the poller routes it to SDG_UPDATE/ instead of SDG/.
    """
    orders = dfue_json.get('orders', [])
    if not orders:
        return None, 'dfue_file JSON contains no orders array'

    header = dfue_json.get('header', {})
    results = {}

    for order in orders:
        onum = str(order.get('onum', '')).strip()
        if not onum:
            print("Warning: Skipping order without onum in dfue")
            continue

        single_json = {'header': header, 'orders': [order], 'trailer': {'count': '1'}}
        lbase_lines = convert_orjson_to_lbase(single_json)
        lbase_content = "".join(lbase_lines)

        response = table.get_item(Key={'OrderId': onum})
        item = response.get('Item')

        if _order_sdg_already_processed(item, onum):
            current_version = int(item.get('AuditVersion', 0))
            new_version = current_version + 1
            sdg_key = f"sdg/{onum}_v{new_version}.sdg"
            print(f"Order {onum} already processed -> creating update version {new_version}")
            upsert_order(table, onum, [sdg_key], len(lbase_content), 'dfue', new_version)
        else:
            sdg_key = f"sdg/{onum}.sdg"
            upsert_order(table, onum, [sdg_key], len(lbase_content), 'dfue')

        s3_client.put_object(
            Bucket=INGEST_BUCKET, Key=sdg_key,
            Body=lbase_content.encode('iso-8859-1'), ContentType='text/plain',
        )
        results.setdefault(onum, []).append(sdg_key)

    if not results:
        return None, 'No orders with valid onum found in dfue_file'
    return results, None


def handle_audit(dfue_json, table):
    """Versioned audit: sdg/{onum}_v{N}.sdg, version counter in DynamoDB."""
    orders = dfue_json.get('orders', [])
    if not orders:
        return None, 'Audit dfue_file JSON contains no orders array'

    header = dfue_json.get('header', {})
    results = {}

    for order in orders:
        onum = str(order.get('onum', '')).strip()
        if not onum:
            print("Warning: Skipping audit order without onum")
            continue

        response = table.get_item(Key={'OrderId': onum})
        item = response.get('Item')
        current_version = int(item.get('AuditVersion', 0)) if item else 0
        new_version = current_version + 1

        single_json = {'header': header, 'orders': [order], 'trailer': {'count': '1'}}
        lbase_lines = convert_orjson_to_lbase(single_json)
        lbase_content = "".join(lbase_lines)

        sdg_key = f"sdg/{onum}_v{new_version}.sdg"
        s3_client.put_object(
            Bucket=INGEST_BUCKET, Key=sdg_key,
            Body=lbase_content.encode('iso-8859-1'), ContentType='text/plain',
        )
        upsert_order(table, onum, [sdg_key], len(lbase_content), 'audit', new_version)
        results.setdefault(onum, []).append(sdg_key)

    if not results:
        return None, 'No orders with valid onum found in audit dfue_file'
    return results, None


def handle_orderauto(dfue_json, table):
    """Stores the raw OrderAuto JSON in S3 without conversion."""
    header = dfue_json.get('header', {})
    login = sanitize_path_segment(
        header.get('custlogin') or header.get('carrier') or 'unknown'
    )
    ts = int(time.time())

    s3_key = f"orderauto/{login}_{ts}.json"
    raw = json.dumps(dfue_json, ensure_ascii=False)

    s3_client.put_object(
        Bucket=INGEST_BUCKET, Key=s3_key,
        Body=raw.encode('utf-8'), ContentType='application/json',
    )

    order_id = f"OAUTO_{login}_{ts}"
    upsert_order(table, order_id, [s3_key], len(raw), 'orderauto')
    return {order_id: [s3_key]}, None


def handle_documents(documents, table):
    """Stores document files, deriving order_id from the structured filename."""
    saved_by_order = {}

    for doc in documents:
        if not doc.get('content'):
            continue

        order_id = doc.get('parsed_order_id')
        if not order_id:
            return None, (
                f"Could not determine order id from document filename "
                f"'{doc['filename']}'. Expected format: "
                f"login#recipient#document#onum#filename"
            )

        doc_type_prefix = sanitize_path_segment(
            doc.get('doc_type') or doc.get('document_label') or 'UNSPECIFIED'
        )
        stored_filename = sanitize_path_segment(
            doc.get('stored_filename') or doc['filename']
        )
        doc_key = f"docs/{order_id}/{doc_type_prefix}_{stored_filename}"

        s3_client.put_object(
            Bucket=INGEST_BUCKET, Key=doc_key, Body=doc['content'],
        )
        upsert_order(table, order_id, [doc_key], len(doc['content']), 'document')
        saved_by_order.setdefault(order_id, []).append(doc_key)

    if not saved_by_order:
        return None, 'No documents with content found in payload'
    return saved_by_order, None


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    try:
        if not event.get('body'):
            return _resp(400, 'Missing request body')

        token = get_request_token(event)
        if token != EXPECTED_TOKEN:
            return _resp(401, 'Unauthorized. Provide the token via ?token=... or Authorization: Bearer ...')

        content_type = get_content_type(event)
        if not content_type or 'multipart/form-data' not in content_type:
            return _resp(400, 'Requires multipart/form-data')

        body = event['body']
        if event.get('isBase64Encoded'):
            body = base64.b64decode(body)
        elif isinstance(body, str):
            body = body.encode('utf-8')

        multipart_data = decoder.MultipartDecoder(body, content_type)

        # -- Parse all multipart parts ----------------------------------------
        dfue_data = None
        documents = []
        pending_doc_types = {}
        generic_files = []

        for part in multipart_data.parts:
            cd = get_header(part.headers, 'Content-Disposition')
            name = extract_name(cd)

            if name == 'dfue_file':
                dfue_data = part.content
            elif name == 'file':
                generic_files.append(part)
            elif name and name.startswith('document_file_'):
                filename = extract_filename(cd) or f"doc_{uuid.uuid4().hex[:8]}.pdf"
                idx = name.replace('document_file_', '')
                parsed = parse_document_filename(filename)
                documents.append({
                    'index': idx,
                    'filename': filename,
                    'content': part.content,
                    'stored_filename': parsed['stored_filename'],
                    'document_label': parsed['document_label'],
                    'parsed_order_id': parsed['order_id'],
                    'login': parsed['login'],
                    'recipient_hint': parsed['recipient_hint'],
                })
            elif name and name.startswith('doc_type_'):
                idx = name.replace('doc_type_', '')
                pending_doc_types[idx] = part.text.strip()

        # -- Resolve generic "file" parts based on typ -------------------------
        query_params = event.get('queryStringParameters') or {}
        explicit_typ = (query_params.get('typ') or '').strip().lower()

        for i, part in enumerate(generic_files):
            cd = get_header(part.headers, 'Content-Disposition')
            if explicit_typ in ('dfue', 'audit', 'orderauto'):
                if dfue_data is None:
                    dfue_data = part.content
            else:
                filename = extract_filename(cd) or f"doc_{uuid.uuid4().hex[:8]}.pdf"
                idx = str(i + 1)
                parsed = parse_document_filename(filename)
                documents.append({
                    'index': idx,
                    'filename': filename,
                    'content': part.content,
                    'stored_filename': parsed['stored_filename'],
                    'document_label': parsed['document_label'],
                    'parsed_order_id': parsed['order_id'],
                    'login': parsed['login'],
                    'recipient_hint': parsed['recipient_hint'],
                })

        for doc in documents:
            dt = pending_doc_types.get(doc['index'])
            if dt:
                doc['doc_type'] = dt

        # -- Resolve typ -------------------------------------------------------
        typ, err = resolve_typ(event, dfue_data is not None, len(documents) > 0)
        if err:
            return _resp(400, err)

        # -- Parse DFUE JSON if needed -----------------------------------------
        dfue_json = None
        if typ in ('dfue', 'audit', 'orderauto'):
            if not dfue_data:
                return _resp(400, f"typ={typ} requires a dfue_file field in the multipart payload")
            try:
                dfue_json = json.loads(dfue_data.decode('utf-8'))
            except json.JSONDecodeError:
                return _resp(400, 'dfue_file is not valid JSON')

        # -- Route to handler --------------------------------------------------
        table = dynamodb.Table(PROTOCOL_TABLE)
        all_results = {}

        if typ == 'dfue':
            results, err = handle_dfue(dfue_json, table)
            if err:
                return _resp(400, err)
            _merge(all_results, results)

            if documents:
                doc_results, err = handle_documents(documents, table)
                if err:
                    return _resp(400, err)
                _merge(all_results, doc_results)

        elif typ == 'audit':
            results, err = handle_audit(dfue_json, table)
            if err:
                return _resp(400, err)
            _merge(all_results, results)

            if documents:
                doc_results, err = handle_documents(documents, table)
                if err:
                    return _resp(400, err)
                _merge(all_results, doc_results)

        elif typ == 'orderauto':
            results, err = handle_orderauto(dfue_json, table)
            if err:
                return _resp(400, err)
            _merge(all_results, results)

        elif typ == 'document':
            if not documents:
                return _resp(400, 'typ=document but no document_file_* fields found')
            doc_results, err = handle_documents(documents, table)
            if err:
                return _resp(400, err)
            _merge(all_results, doc_results)

        # -- Build response ----------------------------------------------------
        all_files = [f for files in all_results.values() for f in files]
        if not all_files:
            return _resp(400, 'No processable content found in payload')

        resp_body = {
            'message': 'Successfully processed payload',
            'typ': typ,
            'orders': {k: list(v) for k, v in all_results.items()},
            'saved_files': all_files,
        }
        if len(all_results) == 1:
            resp_body['order_id'] = next(iter(all_results))

        oid = resp_body.get('order_id', ','.join(all_results.keys()))
        _log_event('INGEST_SUCCESS', 200, event, order_id=oid, typ=typ,
                    details=f"{len(all_files)} files saved")

        return {
            'statusCode': 200,
            'body': json.dumps(resp_body),
        }

    except Exception as e:
        print(f"Error processing ingest: {str(e)}")
        _log_event('INGEST_ERROR', 500, event, error_msg=str(e))
        return _resp(500, 'Internal server error', str(e))


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _resp(code, message, error=None):
    body = {'message': message}
    if error:
        body['error'] = error
    return {'statusCode': code, 'body': json.dumps(body)}


def _merge(target, source):
    for k, v in source.items():
        target.setdefault(k, []).extend(v)
