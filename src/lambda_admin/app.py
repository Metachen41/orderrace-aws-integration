import os
import json
import time
import boto3
from datetime import datetime, timedelta, timezone
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
cw_client = boto3.client('cloudwatch')

PROTOCOL_TABLE = os.environ.get('PROTOCOL_TABLE')
EVENT_LOG_TABLE = os.environ.get('EVENT_LOG_TABLE')
STACK_NAME = os.environ.get('STACK_NAME', '')


def lambda_handler(event, context):
    path = event.get('path', '')
    path_params = event.get('pathParameters') or {}

    try:
        if path == '/admin/api/stats':
            return handle_stats()
        elif path == '/admin/api/orders':
            return handle_orders(event)
        elif path.startswith('/admin/api/orders/') and path_params.get('orderId'):
            return handle_order_detail(path_params['orderId'])
        elif path == '/admin/api/events':
            return handle_events(event)
        elif path == '/admin/api/metrics':
            return handle_metrics(event)
        else:
            return _resp(404, 'Not found')
    except Exception as e:
        print(f"Admin API error: {e}")
        return _resp(500, f'Internal error: {str(e)}')


def handle_stats():
    table = dynamodb.Table(PROTOCOL_TABLE)
    event_table = dynamodb.Table(EVENT_LOG_TABLE)

    items = _scan_all(table)

    now = int(time.time())
    today_start = now - (now % 86400)

    total_orders = len(items)
    by_type = {}
    pending_downloads = 0
    fully_processed = 0
    total_files = 0
    today_orders = 0

    for item in items:
        dt = item.get('DataType', 'unknown')
        by_type[dt] = by_type.get(dt, 0) + 1

        ftd = item.get('FilesToDownload', set())
        fp = item.get('FilesProcessed', set())
        if isinstance(ftd, set):
            ftd_count = len(ftd)
        else:
            ftd_count = len(list(ftd))
        if isinstance(fp, set):
            fp_count = len(fp)
        else:
            fp_count = len(list(fp))

        total_files += ftd_count + fp_count

        if ftd_count > 0:
            pending_downloads += 1
        elif fp_count > 0:
            fully_processed += 1

        ts = item.get('Timestamp', 0)
        if isinstance(ts, (int, float)) and ts >= today_start:
            today_orders += 1

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    today_events = _query_events_by_date(event_table, today_str, limit=500)
    errors_today = sum(1 for e in today_events if 'ERROR' in e.get('EventType', ''))

    return _resp(200, {
        'total_orders': total_orders,
        'today_orders': today_orders,
        'by_type': by_type,
        'pending_downloads': pending_downloads,
        'fully_processed': fully_processed,
        'total_files': total_files,
        'errors_today': errors_today,
    })


def handle_orders(event):
    table = dynamodb.Table(PROTOCOL_TABLE)
    qs = event.get('queryStringParameters') or {}
    limit = int(qs.get('limit', '50'))

    items = _scan_all(table)

    orders = []
    for item in items:
        ftd = list(item.get('FilesToDownload', []))
        fp = list(item.get('FilesProcessed', []))

        if ftd and not fp:
            status = 'pending'
        elif ftd and fp:
            status = 'partial'
        elif not ftd and fp:
            status = 'processed'
        else:
            status = 'empty'

        orders.append({
            'order_id': item.get('OrderId', ''),
            'data_type': item.get('DataType', 'unknown'),
            'timestamp': item.get('Timestamp', 0),
            'file_count': len(ftd) + len(fp),
            'files_pending': len(ftd),
            'files_processed': len(fp),
            'audit_version': item.get('AuditVersion'),
            'data_size': item.get('DataSize', 0),
            'status': status,
        })

    orders.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    orders = orders[:limit]

    return _resp(200, {'orders': orders, 'total': len(items)})


def handle_order_detail(order_id):
    table = dynamodb.Table(PROTOCOL_TABLE)
    event_table = dynamodb.Table(EVENT_LOG_TABLE)

    resp = table.get_item(Key={'OrderId': order_id})
    item = resp.get('Item')
    if not item:
        return _resp(404, f'Order {order_id} not found')

    ftd = list(item.get('FilesToDownload', []))
    fp = list(item.get('FilesProcessed', []))

    files = []
    for f in ftd:
        files.append({'key': f, 'status': 'pending'})
    for f in fp:
        files.append({'key': f, 'status': 'processed'})

    all_events = _scan_all(event_table)
    order_events = [
        _serialize_event(e) for e in all_events
        if e.get('OrderId') == order_id
    ]
    order_events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

    detail = {
        'order_id': order_id,
        'data_type': item.get('DataType', 'unknown'),
        'timestamp': item.get('Timestamp', 0),
        'data_size': item.get('DataSize', 0),
        'audit_version': item.get('AuditVersion'),
        'files': files,
        'events': order_events[:50],
    }

    return _resp(200, detail)


def handle_events(event):
    table = dynamodb.Table(EVENT_LOG_TABLE)
    qs = event.get('queryStringParameters') or {}
    days = int(qs.get('days', '7'))
    event_type_filter = qs.get('type', '').upper()
    limit = int(qs.get('limit', '100'))

    all_events = []
    now = datetime.now(timezone.utc)
    for i in range(days):
        day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        day_events = _query_events_by_date(table, day, limit=500)
        all_events.extend(day_events)

    if event_type_filter:
        all_events = [e for e in all_events if event_type_filter in e.get('EventType', '')]

    all_events.sort(key=lambda x: x.get('Timestamp', 0), reverse=True)
    serialized = [_serialize_event(e) for e in all_events[:limit]]

    return _resp(200, {'events': serialized})


def handle_metrics(event):
    qs = event.get('queryStringParameters') or {}
    hours = int(qs.get('hours', '168'))
    period = 3600 if hours > 48 else 300

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    function_names = [
        f'{STACK_NAME}-LambdaConvFunction',
        f'{STACK_NAME}-LambdaPullFunction',
        f'{STACK_NAME}-LambdaPullAckFunction',
        f'{STACK_NAME}-LambdaUploadFunction',
        f'{STACK_NAME}-LambdaFtpFunction',
        f'{STACK_NAME}-LambdaServeFunction',
    ]

    queries = []
    for i, fn in enumerate(function_names):
        short = fn.split('-')[-1].replace('Function', '')
        queries.append({
            'Id': f'inv{i}',
            'MetricStat': {
                'Metric': {
                    'Namespace': 'AWS/Lambda',
                    'MetricName': 'Invocations',
                    'Dimensions': [{'Name': 'FunctionName', 'Value': fn}]
                },
                'Period': period,
                'Stat': 'Sum',
            },
            'Label': f'{short}_invocations',
        })
        queries.append({
            'Id': f'err{i}',
            'MetricStat': {
                'Metric': {
                    'Namespace': 'AWS/Lambda',
                    'MetricName': 'Errors',
                    'Dimensions': [{'Name': 'FunctionName', 'Value': fn}]
                },
                'Period': period,
                'Stat': 'Sum',
            },
            'Label': f'{short}_errors',
        })
        queries.append({
            'Id': f'dur{i}',
            'MetricStat': {
                'Metric': {
                    'Namespace': 'AWS/Lambda',
                    'MetricName': 'Duration',
                    'Dimensions': [{'Name': 'FunctionName', 'Value': fn}]
                },
                'Period': period,
                'Stat': 'Average',
            },
            'Label': f'{short}_duration_avg',
        })

    try:
        result = cw_client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
        )
    except Exception as e:
        print(f"CloudWatch query error: {e}")
        return _resp(200, {'metrics': {}, 'error': str(e)})

    metrics = {}
    for series in result.get('MetricDataResults', []):
        label = series['Label']
        timestamps = [t.isoformat() for t in series.get('Timestamps', [])]
        values = series.get('Values', [])
        metrics[label] = {
            'timestamps': timestamps,
            'values': values,
        }

    return _resp(200, {'metrics': metrics, 'period_seconds': period, 'hours': hours})


def _scan_all(table):
    items = []
    resp = table.scan()
    items.extend(resp.get('Items', []))
    while 'LastEvaluatedKey' in resp:
        resp = table.scan(ExclusiveStartKey=resp['LastEvaluatedKey'])
        items.extend(resp.get('Items', []))
    return items


def _query_events_by_date(table, date_str, limit=100):
    try:
        resp = table.query(
            KeyConditionExpression=Key('EventDate').eq(date_str),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get('Items', [])
    except Exception:
        return []


def _serialize_event(e):
    return {
        'event_id': e.get('EventId', ''),
        'event_date': e.get('EventDate', ''),
        'timestamp': e.get('Timestamp', 0),
        'event_type': e.get('EventType', ''),
        'order_id': e.get('OrderId', ''),
        'typ': e.get('Typ', ''),
        'http_method': e.get('HttpMethod', ''),
        'status_code': e.get('StatusCode', 0),
        'source_ip': e.get('SourceIp', ''),
        'error_message': e.get('ErrorMessage', ''),
        'details': e.get('Details', ''),
    }


def _resp(code, data):
    body = data if isinstance(data, str) else json.dumps(data, default=str)
    return {
        'statusCode': code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        },
        'body': body,
    }
