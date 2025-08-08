# router/main.py - Simplified Router Agent

import pika, json, os, requests, time
from datetime import datetime, UTC
from typing import Dict
from dotenv import load_dotenv
load_dotenv()


# --- Configuration ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

# External systems (optional) - URLs are mocked
SYSTEMS = {
    "ERP_SYSTEM_URL": os.environ.get("ERP_SYSTEM_URL"),
    "DMS_SYSTEM_URL": os.environ.get("DMS_SYSTEM_URL"),
    "CRM_SYSTEM_URL": os.environ.get("CRM_SYSTEM_URL")
}

# --- NEW: Slack Configuration ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")

# Fallback systems
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
    """Generic system integration function with manual failure trigger."""
    system_url = SYSTEMS.get(system_key)
    system_name = system_key.replace('_SYSTEM_URL', '').replace('_', ' ')
    filename = document.get('filename', '').lower()

    # --- NEW: Manual Failure Trigger ---
    # If "fail" is in the filename, simulate a failure to test alerting.
    if 'fail' in filename:
        print(f"  -> [TEST] Manually failing route for: {filename}")
        return False

    if not system_url:
        print(f"  -> [MOCK {system_name}] Processing: {document['filename']}")
        time.sleep(0.5)
        return True
    
    # This part would contain real integration logic
    print(f"  -> [INTEGRATION] Attempting to send {document['filename']} to {system_url}")
    return False # Assume failure if URL is present but unreachable

def log_to_sheets(document: Dict, status: str) -> bool:
    """Logs the processing result of a document to Google Sheets."""
    if not GOOGLE_SHEET_ID or not GOOGLE_APPLICATION_CREDENTIALS:
        print("  -> Google Sheets logging skipped: Credentials not configured.")
        return False
        
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        
        # Prepare the row data for the sheet
        values = [
            [
                document.get('filename', 'Unknown'),
                document.get('doc_type', 'Unknown'),
                document.get('confidence', 0.0),
                status,  # "Routed" or "Routing Failed"
                datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
            ]
        ]
        
        body = {'values': values}
        
        result = service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Sheet1!A:E',  # Range now includes the new Status column
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        print(f"  -> ✅ Logged to Google Sheets successfully.")
        return True

    except Exception as e:
        print(f"  -> ❌ Failed to log to Google Sheets: {e}")
        return False
def send_alert(document: Dict, reason: str):
    """--- UPDATED: Send Slack alert for failures ---"""
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL:
        print(f"  -> [ALERT - MOCK] Reason: {reason}")
        print(f"  -> [ALERT - MOCK] Document: {document.get('filename', 'Unknown')}")
        return
    
    try:
        message = {
            "channel": SLACK_CHANNEL,
            "text": f"🚨 Document Routing Alert: {reason}",
            "attachments": [{
                "color": "#dc3545", # Red color
                "title": reason,
                "fields": [
                    {"title": "Document", "value": document.get('filename', 'Unknown'), "short": True},
                    {"title": "Type", "value": document.get('doc_type', 'Unknown'), "short": True},
                    {"title": "Document ID", "value": f"`{document.get('document_id')}`", "short": False},
                    {"title": "Time", "value": datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC'), "short": False}
                ]
            }]
        }
        
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json=message,
            timeout=10
        )
        
        response_data = response.json()
        if response_data.get('ok'):
            print(f"  -> Slack alert sent successfully to {SLACK_CHANNEL}")
        else:
            print(f"  -> Slack alert failed: {response_data.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"  -> Exception while sending Slack alert: {e}")

def route_document(document: Dict) -> bool:
    """Main routing logic. Returns True on success, False on failure."""
    doc_type = document.get('doc_type', 'UNKNOWN')
    filename = document.get('filename', 'Unknown')
    
    manual_destination = document.get('destination')
    if manual_destination:
        system_key = f"{manual_destination.upper()}_SYSTEM_URL"
    else:
        system_key = ROUTING_MAP.get(doc_type, "DMS_SYSTEM_URL")
        
    system_name = system_key.replace('_SYSTEM_URL', '').replace('_', ' ')
    
    print(f" [x] Routing {filename} ({doc_type}) -> {system_name}")
    
    if send_to_system(document, system_key):
        print(f"  -> ✅ Successfully routed to {system_name}")
        return True
    else:
        print(f"  -> ❌ Primary system '{system_name}' failed.")
        # The Slack alert for failures remains unchanged
        send_alert(document, f"Primary system '{system_name}' is unavailable or failed.")
        return False
def callback(ch, method, properties, body):
    """Process incoming document for routing and log every result."""
    document = {}
    try:
        document = json.loads(body)
        document_id = document.get('document_id', 'unknown')
        
        # This part remains the same: it processes the doc and updates the UI status
        if route_document(document):
            status = "Routed"
            destination_key = document.get('destination') or ROUTING_MAP.get(document.get('doc_type', 'UNKNOWN'), "dms_system")
            destination_display = destination_key.replace('_system', '').replace('_', ' ').upper() + " System"
            publish_status_update(document_id, status, document, details={"destination": destination_display}, routing_destination=destination_display)
            print(f"  -> Routing process for '{document.get('filename', 'Unknown')}' completed.")
        else:
            status = "Routing Failed"
            publish_status_update(document_id, status, document, details={"error": "Primary and fallback systems failed"})
            print(f"  -> Routing process for '{document.get('filename', 'Unknown')}' failed.")
        
        # --- THIS IS THE NEW STEP ---
        # Log the final status of EVERY document to Google Sheets
        log_to_sheets(document, status)
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
            
    except Exception as e:
        print(f" [!] An unexpected error occurred in callback: {e}")
        # Make sure to acknowledge the message even on error to prevent it from being re-queued
        ch.basic_ack(delivery_tag=method.delivery_tag)
def main():
    """Main application loop"""
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
    if SLACK_BOT_TOKEN and SLACK_CHANNEL:
        print(f" [*] Slack alerts configured for channel: {SLACK_CHANNEL}")
    else:
        print(" [!] Slack alerting is NOT configured. Alerts will be mocked in the console.")
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