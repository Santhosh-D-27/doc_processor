# router/main.py - Simplified Router Agent per Document Requirements

import pika
import json
import os
import requests
import time
from datetime import datetime, UTC
from typing import Dict, Optional

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

# Optional external systems (mock if not available)
ERP_SYSTEM_URL = os.environ.get("ERP_SYSTEM_URL")
DMS_SYSTEM_URL = os.environ.get("DMS_SYSTEM_URL") 
CRM_SYSTEM_URL = os.environ.get("CRM_SYSTEM_URL")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#document-alerts")

# Google Sheets fallback
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# Simple routing rules as per document requirements
ROUTING_MAP = {
    "INVOICE": "erp_system",
    "RECEIPT": "erp_system",
    "CONTRACT": "dms_system", 
    "AGREEMENT": "dms_system",
    "REPORT": "dms_system",
    "MEMO": "dms_system",
    "GRIEVANCE": "dms_system",
    "RESUME": "crm_system",
    "ID_PROOF": "crm_system"
}

def publish_status_update(doc_id: str, status: str, details: dict = None, routing_destination: str = None, 
                         doc_type: str = None, confidence: float = None, summary: str = None):
    """Publish status update to message bus"""
    status_message = {
        "document_id": doc_id,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details or {},
        "routing_destination": routing_destination,
        # Add the missing fields
        "doc_type": doc_type,
        "confidence": confidence,
        "summary": summary
    }
    
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=STATUS_QUEUE_NAME,
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        print(f" [->] Status: {doc_id} -> {status}")
    except Exception as e:
        print(f" [!] Status update failed: {e}")

def send_to_erp_system(document: Dict) -> bool:
    """Send document to ERP system (or mock)"""
    if not ERP_SYSTEM_URL:
        # Mock ERP system for demo
        print(f"  -> [MOCK ERP] Processing financial document: {document['filename']}")
        time.sleep(0.5)  # Simulate processing time
        return True
    
    try:
        payload = {
            "document_id": document["document_id"],
            "filename": document["filename"],
            "doc_type": document["doc_type"],
            "extracted_data": document.get("entities", {})
        }
        response = requests.post(f"{ERP_SYSTEM_URL}/api/documents", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> ERP: Successfully processed {document['filename']}")
        return True
    except Exception as e:
        print(f"  -> ERP: Failed to process {document['filename']}: {e}")
        return False

def send_to_dms_system(document: Dict) -> bool:
    """Send document to DMS system (or mock)"""
    if not DMS_SYSTEM_URL:
        # Mock DMS system for demo
        print(f"  -> [MOCK DMS] Storing document: {document['filename']}")
        time.sleep(0.5)  # Simulate processing time
        return True
    
    try:
        payload = {
            "document_id": document["document_id"],
            "filename": document["filename"],
            "doc_type": document["doc_type"],
            "content": document.get("file_content", "")
        }
        response = requests.post(f"{DMS_SYSTEM_URL}/api/upload", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> DMS: Successfully stored {document['filename']}")
        return True
    except Exception as e:
        print(f"  -> DMS: Failed to store {document['filename']}: {e}")
        return False

def send_to_crm_system(document: Dict) -> bool:
    """Send document to CRM system (or mock)"""
    if not CRM_SYSTEM_URL:
        # Mock CRM system for demo  
        print(f"  -> [MOCK CRM] Processing people document: {document['filename']}")
        time.sleep(0.5)  # Simulate processing time
        return True
    
    try:
        payload = {
            "document_id": document["document_id"],
            "filename": document["filename"],
            "candidate_data": document.get("entities", {}),
            "sender": document.get("sender", "")
        }
        response = requests.post(f"{CRM_SYSTEM_URL}/api/candidates", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> CRM: Successfully processed {document['filename']}")
        return True
    except Exception as e:
        print(f"  -> CRM: Failed to process {document['filename']}: {e}")
        return False

def log_to_google_sheets_fallback(document: Dict, destination: str) -> bool:
    """Fallback: Log to Google Sheets when primary system fails"""
    if not GOOGLE_SHEET_ID or not GOOGLE_APPLICATION_CREDENTIALS:
        print("  -> Google Sheets fallback not configured")
        return False
        
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS, 
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        
        values = [
            document.get('filename', 'Unknown'),
            document.get('doc_type', 'Unknown'), 
            document.get('confidence', 0.0),
            destination,
            'FALLBACK',
            datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
            document.get('summary', '')[:100]
        ]
        
        body = {'values': [values]}
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Documents!A:G',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        print(f"  -> Fallback: Logged {document['filename']} to Google Sheets")
        return True
    except Exception as e:
        print(f"  -> Fallback failed: {e}")
        return False

def send_slack_alert(document: Dict, reason: str):
    """Send Slack alert for failures using Slack API"""
    if not SLACK_BOT_TOKEN:
        print(f"  -> [ALERT] {reason}: {document['filename']}")
        return
    
    try:
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        
        message = {
            "channel": SLACK_CHANNEL,
            "text": f"🚨 Document Router Alert",
            "attachments": [
                {
                    "color": "danger",
                    "title": reason,
                    "fields": [
                        {"title": "Document", "value": document['filename'], "short": True},
                        {"title": "Type", "value": document.get('doc_type', 'Unknown'), "short": True},
                        {"title": "Time", "value": datetime.now(UTC).strftime('%H:%M:%S'), "short": True}
                    ]
                }
            ]
        }
        
        response = requests.post(
            "https://slack.com/api/chat.postMessage", 
            headers=headers,
            json=message, 
            timeout=5
        )
        
        if response.json().get("ok"):
            print(f"  -> Slack alert sent: {reason}")
        else:
            print(f"  -> Slack API error: {response.json()}")
            
    except Exception as e:
        print(f"  -> Slack alert failed: {e}")

def route_document(document: Dict) -> bool:
    """Main routing logic as per document requirements"""
    doc_type = document.get('doc_type', 'UNKNOWN')
    filename = document.get('filename', 'Unknown')
    
    # Get destination system based on document type
    destination_system = ROUTING_MAP.get(doc_type, "dms_system")  # Default to DMS
    
    print(f" [x] Routing {filename} ({doc_type}) -> {destination_system}")
    
    # Try to send to primary system
    success = False
    
    if destination_system == "erp_system":
        success = send_to_erp_system(document)
    elif destination_system == "dms_system":
        success = send_to_dms_system(document)
    elif destination_system == "crm_system":
        success = send_to_crm_system(document)
    
    if success:
        print(f"  -> ✅ Successfully routed to {destination_system}")
        return True
    else:
        # Fallback reasoning as per document requirements
        print(f"  -> ❌ {destination_system} failed, executing fallback")
        
        # Try Google Sheets fallback
        fallback_success = log_to_google_sheets_fallback(document, destination_system)
        
        # Send alert regardless
        send_slack_alert(document, f"{destination_system} unavailable")
        
        return fallback_success

# --- In the process_document function ---
def process_document(message):
    """Process a single document"""
    document_id = message.get('document_id', 'unknown')
    filename = message.get('filename', 'Unknown')
    
    try:
        # Route the document
        routing_success = route_document(message)
        
        if routing_success:
            # Success - update status to Routed
            publish_status_update(
                doc_id=document_id,
                status="Routed",
                details={"destination": ROUTING_MAP.get(message.get('doc_type', 'UNKNOWN'), "dms_system")},
                routing_destination=ROUTING_MAP.get(message.get('doc_type', 'UNKNOWN'), "dms_system"),
                # --- ADD THESE LINES ---
                doc_type=message.get('doc_type'),
                confidence=message.get('confidence'),
                summary=message.get('summary')
            )
            print(f"  -> ✅ {filename} routing completed")
            return True
        else:
            # Failure - update status
            publish_status_update(
                doc_id=document_id,
                status="Routing Failed",
                details={"error": "Primary and fallback systems failed"},
                # --- ADD THESE LINES ---
                doc_type=message.get('doc_type'),
                confidence=message.get('confidence'),
                summary=message.get('summary')
            )
            print(f"  -> ❌ {filename} routing failed")
            return False
            
    except Exception as e:
        print(f" [!] Error processing {filename}: {e}")
        publish_status_update(
            doc_id=document_id,
            status="Routing Error", 
            details={"error": str(e)},
            # --- ADD THESE LINES ---
            doc_type=message.get('doc_type'),
            confidence=message.get('confidence'),
            summary=message.get('summary')
        )
        return False

def callback(ch, method, properties, body):
    """RabbitMQ message handler"""
    try:
        message = json.loads(body)
        
        if process_document(message):
            # Acknowledge successful processing
            ch.basic_ack(delivery_tag=method.delivery_tag)
        else:
            # For demo purposes, still acknowledge to prevent requeue loops
            # In production, you might want to implement retry logic
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
    except json.JSONDecodeError as e:
        print(f" [!] Invalid JSON message: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print(f" [!] Unexpected error: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    """Main application loop"""
    # Connect to RabbitMQ with retry
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Connected to RabbitMQ')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready, retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    
    # Set QoS to process one message at a time
    channel.basic_qos(prefetch_count=1)
    
    print(' [*] 🚀 Simple Router Agent Ready!')
    print(f' [*] Routing Rules: {ROUTING_MAP}')
    print(' [*] Waiting for classified documents...')
    
    # Set up consumer
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