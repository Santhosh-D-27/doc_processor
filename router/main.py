# router/main.py - Simplified Router Agent

import pika, json, os, requests, time
from datetime import datetime, UTC
from typing import Dict

# Configuration
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

# External systems (optional)
SYSTEMS = {
    "ERP_SYSTEM_URL": os.environ.get("ERP_SYSTEM_URL"),
    "DMS_SYSTEM_URL": os.environ.get("DMS_SYSTEM_URL"), 
    "CRM_SYSTEM_URL": os.environ.get("CRM_SYSTEM_URL")
}
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#document-alerts")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# Routing rules
ROUTING_MAP = {
    "INVOICE": "ERP_SYSTEM_URL", "RECEIPT": "ERP_SYSTEM_URL",
    "CONTRACT": "DMS_SYSTEM_URL", "AGREEMENT": "DMS_SYSTEM_URL", 
    "REPORT": "DMS_SYSTEM_URL", "MEMO": "DMS_SYSTEM_URL", "GRIEVANCE": "DMS_SYSTEM_URL",
    "RESUME": "CRM_SYSTEM_URL", "ID_PROOF": "CRM_SYSTEM_URL"
}

def publish_status_update(doc_id: str, status: str, document: Dict = None, **kwargs):
    """Publish status update to message bus"""
    message = {
        "document_id": doc_id, "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "filename": document.get('filename') if document else None,
        "doc_type": document.get('doc_type') if document else None,
        "confidence": document.get('confidence') if document else None,
        "summary": document.get('summary') if document else None,
        "details": kwargs.get('details', {}),
        "routing_destination": kwargs.get('routing_destination')
    }
    
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, 
                            body=json.dumps(message), properties=pika.BasicProperties(delivery_mode=2))
        connection.close()
        print(f" [->] Status: {doc_id} -> {status}")
    except Exception as e:
        print(f" [!] Status update failed: {e}")

def send_to_system(document: Dict, system_key: str) -> bool:
    """Generic system integration function"""
    system_url = SYSTEMS[system_key]
    system_name = system_key.replace('_SYSTEM_URL', '').replace('_', ' ')
    
    if not system_url:
        print(f"  -> [MOCK {system_name}] Processing: {document['filename']}")
        time.sleep(0.5)
        return True
    
    try:
        # Build payload based on system type
        if 'ERP' in system_key:
            payload = {"document_id": document["document_id"], "filename": document["filename"],
                      "doc_type": document["doc_type"], "extracted_data": document.get("entities", {})}
            endpoint = "/api/documents"
        elif 'CRM' in system_key:
            payload = {"document_id": document["document_id"], "filename": document["filename"],
                      "candidate_data": document.get("entities", {}), "sender": document.get("sender", "")}
            endpoint = "/api/candidates"
        else:  # DMS
            payload = {"document_id": document["document_id"], "filename": document["filename"],
                      "doc_type": document["doc_type"], "content": document.get("file_content", "")}
            endpoint = "/api/upload"
        
        response = requests.post(f"{system_url}{endpoint}", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> {system_name}: Successfully processed {document['filename']}")
        return True
    except Exception as e:
        print(f"  -> {system_name}: Failed - {e}")
        return False

def fallback_to_sheets(document: Dict, destination: str) -> bool:
    """Log to Google Sheets when primary system fails"""
    if not GOOGLE_SHEET_ID or not GOOGLE_APPLICATION_CREDENTIALS:
        return False
        
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        service = build('sheets', 'v4', credentials=creds)
        
        values = [[document.get('filename', 'Unknown'), document.get('doc_type', 'Unknown'), 
                  document.get('confidence', 0.0), destination, 'FALLBACK',
                  datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'), 
                  document.get('summary', '')[:100]]]
        
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID, range='Documents!A:G',
            valueInputOption='RAW', insertDataOption='INSERT_ROWS',
            body={'values': values}).execute()
        
        print(f"  -> Fallback: Logged to Google Sheets")
        return True
    except Exception as e:
        print(f"  -> Fallback failed: {e}")
        return False

def send_alert(document: Dict, reason: str):
    """Send Slack alert for failures"""
    if not SLACK_BOT_TOKEN:
        print(f"  -> [ALERT] {reason}: {document['filename']}")
        return
    
    try:
        message = {
            "channel": SLACK_CHANNEL, "text": f"🚨 Document Router Alert",
            "attachments": [{
                "color": "danger", "title": reason,
                "fields": [
                    {"title": "Document", "value": document['filename'], "short": True},
                    {"title": "Type", "value": document.get('doc_type', 'Unknown'), "short": True},
                    {"title": "Time", "value": datetime.now(UTC).strftime('%H:%M:%S'), "short": True}
                ]
            }]
        }
        
        response = requests.post("https://slack.com/api/chat.postMessage", 
                               headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
                               json=message, timeout=5)
        
        print(f"  -> Slack alert: {'sent' if response.json().get('ok') else 'failed'}")
    except Exception as e:
        print(f"  -> Slack alert failed: {e}")

def route_document(document: Dict) -> bool:
    """Main routing logic with fallback"""
    doc_type = document.get('doc_type', 'UNKNOWN')
    filename = document.get('filename', 'Unknown')
    
    # Get destination system
    system_key = document.get('destination') or ROUTING_MAP.get(doc_type, "DMS_SYSTEM_URL")
    system_name = system_key.replace('_SYSTEM_URL', '').replace('_', ' ')
    
    print(f" [x] Routing {filename} ({doc_type}) -> {system_name}")
    
    # Try primary system
    if send_to_system(document, system_key):
        print(f"  -> ✅ Successfully routed to {system_name}")
        return True
    else:
        print(f"  -> ❌ {system_name} failed, executing fallback")
        fallback_success = fallback_to_sheets(document, system_name)
        send_alert(document, f"{system_name} unavailable")
        return fallback_success

def callback(ch, method, properties, body):
    """Process incoming document for routing"""
    try:
        document = json.loads(body)
        document_id = document.get('document_id', 'unknown')
        
        # Route the document
        if route_document(document):
            # Success
            destination = document.get('destination') or ROUTING_MAP.get(document.get('doc_type', 'UNKNOWN'), "DMS_SYSTEM_URL")
            publish_status_update(document_id, "Routed", document, 
                                details={"destination": destination.replace('_SYSTEM_URL', '').replace('_', ' ')},
                                routing_destination=destination.replace('_SYSTEM_URL', '').replace('_', ' '))
            print(f"  -> ✅ {document.get('filename', 'Unknown')} routing completed")
        else:
            # Failure
            publish_status_update(document_id, "Routing Failed", document,
                                details={"error": "Primary and fallback systems failed"})
            print(f"  -> ❌ {document.get('filename', 'Unknown')} routing failed")
            
        ch.basic_ack(delivery_tag=method.delivery_tag)
            
    except json.JSONDecodeError as e:
        print(f" [!] Invalid JSON: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print(f" [!] Error: {e}")
        if 'document' in locals():
            publish_status_update(document.get('document_id', 'unknown'), "Routing Error", document,
                                details={"error": str(e)})
        ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    """Main application loop"""
    # Connect to RabbitMQ with retry
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Connected to RabbitMQ')
            break
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready, retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    
    print(' [*] 🚀 Simple Router Agent Ready!')
    print(f' [*] Routing Rules: {ROUTING_MAP}')
    print(' [*] Waiting for classified documents...')
    
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print('\n [*] Stopping router...')
        channel.stop_consuming()
        connection.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f' [!] Critical error: {e}')
        exit(1)