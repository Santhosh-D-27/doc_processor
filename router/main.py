# router/main.py - Enhanced with VIP handling

import pika
import json
import os
import requests
import sys
import time
from datetime import datetime, UTC

# --- Google Sheets API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue'  # Regular documents
VIP_CONSUME_QUEUE_NAME = 'vip_documents_queue'  # VIP documents
STATUS_QUEUE_NAME = 'document_status_queue'

# SECRETS (retrieved from environment variables)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
VIP_GOOGLE_SHEET_ID = os.environ.get("VIP_GOOGLE_SHEET_ID")  # Separate sheet for VIP docs
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
VIP_SLACK_WEBHOOK_URL = os.environ.get("VIP_SLACK_WEBHOOK_URL")  # Separate channel for VIP alerts

# Define the range where data will be appended
SHEET_RANGE_NAME = 'Sheet1!A:F'  # Extended for VIP info
VIP_SHEET_RANGE_NAME = 'VIPDocs!A:H'  # VIP sheet with more columns

# --- Google Sheets Service Initialization ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

sheets_service = None

def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None, is_vip: bool = False):
    """
    Enhanced status update with VIP information
    """
    if details is None:
        details = {}

    status_message = {
        "document_id": doc_id,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details,
        "doc_type": doc_type,
        "confidence": confidence,
        "is_vip": is_vip
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
        vip_status = " [VIP]" if is_vip else ""
        print(f" [->] Status update published for Doc ID {doc_id}: {status}{vip_status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def get_sheets_service():
    """Initializes and returns the Google Sheets API service."""
    global sheets_service
    if sheets_service is None:
        if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
            print("  -> ERROR: GOOGLE_APPLICATION_CREDENTIALS environment variable not set or file not found.")
            return None

        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            sheets_service = build('sheets', 'v4', credentials=creds)
            print("  -> Google Sheets service initialized.")
        except Exception as e:
            print(f"  -> ERROR: Failed to initialize Google Sheets service: {e}")
            sheets_service = None
    return sheets_service

# --- ENHANCED EXTERNAL SYSTEMS INTEGRATION ---

def log_to_google_sheet(filename: str, doc_type: str, confidence: float, is_vip: bool = False, 
                       vip_level: str = None, sender: str = None, summary: str = None) -> bool:
    """Enhanced logging with VIP support and document summaries."""
    service = get_sheets_service()
    sheet_id = VIP_GOOGLE_SHEET_ID if is_vip and VIP_GOOGLE_SHEET_ID else GOOGLE_SHEET_ID
    
    if not service or not sheet_id:
        print("  -> Google Sheets service not available or SHEET_ID not set. Skipping logging.")
        return False

    print(f"  -> Calling Google Sheets API to log '{filename}' {'[VIP]' if is_vip else ''}")
    try:
        if is_vip:
            # VIP sheet with more detailed information
            values = [
                filename,
                doc_type,
                confidence,
                vip_level or 'medium',
                sender or 'Unknown',
                (summary or 'No summary')[:100] + ('...' if len(summary or '') > 100 else ''),
                'VIP',  # Special flag
                time.strftime('%Y-%m-%d %H:%M:%S')
            ]
            range_name = VIP_SHEET_RANGE_NAME
        else:
            # Regular sheet
            values = [
                filename,
                doc_type,
                confidence,
                sender or 'Unknown',
                (summary or 'No summary')[:50] + ('...' if len(summary or '') > 50 else ''),
                time.strftime('%Y-%m-%d %H:%M:%S')
            ]
            range_name = SHEET_RANGE_NAME
        
        body = {'values': [values]}
        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        cells_updated = result.get('updates', {}).get('updatedCells', 0)
        print(f"  -> Successfully added {cells_updated} cells to {'VIP' if is_vip else 'regular'} Google Sheet.")
        return True
    except Exception as e:
        print(f"  -> ERROR: Failed to log to Google Sheet: {e}")
        return False

def send_slack_alert(filename: str, reason: str, doc_type: str = "N/A", is_vip: bool = False, 
                    vip_level: str = None, sender: str = None, priority_content: dict = None):
    """Enhanced Slack alerts with VIP information and priority content."""
    webhook_url = VIP_SLACK_WEBHOOK_URL if is_vip and VIP_SLACK_WEBHOOK_URL else SLACK_WEBHOOK_URL
    
    if not webhook_url:
        print("  -> ERROR: Slack Webhook URL not set. Skipping Slack alert.")
        return

    vip_emoji = "👑" if is_vip else "📄"
    urgency_emoji = "🚨" if is_vip and vip_level == 'high' else "⚠️"
    
    print(f"  -> Sending {'VIP ' if is_vip else ''}Slack alert for '{filename}'...")
    
    # Build enhanced message blocks
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{urgency_emoji} *{'VIP ' if is_vip else ''}Document Alert*\n{reason}"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*File:*\n`{filename}`"},
                {"type": "mrkdwn", "text": f"*Type:*\n`{doc_type}`"},
            ]
        }
    ]
    
    # Add VIP-specific information
    if is_vip:
        vip_fields = [
            {"type": "mrkdwn", "text": f"*VIP Level:*\n{vip_level.upper() if vip_level else 'UNKNOWN'}"},
            {"type": "mrkdwn", "text": f"*Sender:*\n{sender or 'Unknown'}"}
        ]
        blocks[1]["fields"].extend(vip_fields)
    
    # Add priority content if available
    if priority_content and isinstance(priority_content, dict):
        priority_text = ""
        if priority_content.get('deadlines'):
            priority_text += f"⏰ *Deadlines:* {', '.join(priority_content['deadlines'][:2])}\n"
        if priority_content.get('financial_commitments'):
            priority_text += f"💰 *Financial:* {', '.join(priority_content['financial_commitments'][:2])}\n"
        if priority_content.get('urgency_level'):
            priority_text += f"🎯 *Urgency:* {priority_content['urgency_level'].upper()}"
        
        if priority_text:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Priority Content:*\n{priority_text}"
                }
            })
    
    message = {
        "text": f"{vip_emoji} {'VIP ' if is_vip else ''}Document: `{filename}`",
        "blocks": blocks
    }
    
    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        print(f"  -> Successfully sent {'VIP ' if is_vip else ''}Slack alert.")
    except requests.exceptions.RequestException as e:
        print(f"  -> ERROR: Failed to send Slack alert: {e}")

def send_vip_priority_notification(filename: str, vip_level: str, sender: str, summary: str, priority_content: dict):
    """Send special high-priority notification for VIP documents."""
    if not VIP_SLACK_WEBHOOK_URL:
        print("  -> No VIP Slack webhook configured. Using regular channel.")
        return
    
    urgency_indicators = {
        'high': '🚨🚨🚨 URGENT VIP DOCUMENT 🚨🚨🚨',
        'medium': '⚠️ Important VIP Document',
        'low': '📋 VIP Document Received'
    }
    
    message = {
        "text": f"VIP Document Alert: {filename}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": urgency_indicators.get(vip_level, '📋 VIP Document')
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Document:*\n{filename}"},
                    {"type": "mrkdwn", "text": f"*From:*\n{sender}"},
                    {"type": "mrkdwn", "text": f"*VIP Level:*\n{vip_level.upper()}"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{time.strftime('%Y-%m-%d %H:%M:%S')}"}
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Summary:*\n{summary[:200]}{'...' if len(summary) > 200 else ''}"
                }
            }
        ]
    }
    
    # Add priority content if available
    if priority_content and any(priority_content.values()):
        priority_text = "*🎯 Priority Items:*\n"
        if priority_content.get('deadlines'):
            priority_text += f"⏰ Deadlines: {', '.join(priority_content['deadlines'][:3])}\n"
        if priority_content.get('financial_commitments'):
            priority_text += f"💰 Financial: {', '.join(priority_content['financial_commitments'][:2])}\n"
        if priority_content.get('action_items'):
            priority_text += f"✅ Actions: {', '.join(priority_content['action_items'][:3])}\n"
        
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": priority_text
            }
        })
    
    try:
        response = requests.post(VIP_SLACK_WEBHOOK_URL, json=message, timeout=10)
        response.raise_for_status()
        print(f"  -> Successfully sent VIP priority notification for {vip_level} level document.")
    except requests.exceptions.RequestException as e:
        print(f"  -> ERROR: Failed to send VIP priority notification: {e}")

# --- MAIN ROUTING LOGIC ---
def process_regular_document(message):
    """Process regular (non-VIP) documents"""
    document_id = message.get('document_id', 'unknown_id')
    doc_type = message.get('doc_type', 'UNKNOWN')
    filename = message.get('filename', 'Unknown_File')
    confidence = message.get('confidence', 0.0)
    sender = message.get('sender', '')
    summary = message.get('summary', '')
    
    print(f"\n [x] Processing regular document '{filename}' (Doc ID: {document_id})")
    
    routing_destination = "Unknown"
    try:
        if doc_type in ["INVOICE", "RECEIPT", "CONTRACT", "RESUME", "MEMO", "REPORT"]:
            log_to_google_sheet(filename, doc_type, confidence, False, None, sender, summary)
            routing_destination = "Google Sheets"
        elif doc_type == "NEEDS_HUMAN_REVIEW":
            send_slack_alert(filename, f"Low confidence score ({confidence:.2f})", doc_type, False)
            routing_destination = "Human Review (Slack)"
        else:
            send_slack_alert(filename, f"Unhandled document type: '{doc_type}'", doc_type, False)
            routing_destination = "Fallback (Slack)"

        publish_status_update(
            doc_id=document_id,
            status="Routed",
            details={"destination": routing_destination},
            doc_type=doc_type,
            confidence=confidence,
            is_vip=False
        )
        
        print(f"  -> Regular document '{filename}' routed to {routing_destination}")
        return True

    except Exception as e:
        print(f" [e] Error routing regular document '{filename}': {e}")
        publish_status_update(
            doc_id=document_id,
            status="Routing Failed",
            details={"error": str(e)},
            is_vip=False
        )
        return False

def process_vip_document(message):
    """Process VIP documents with enhanced handling"""
    document_id = message.get('document_id', 'unknown_id')
    doc_type = message.get('doc_type', 'UNKNOWN')
    filename = message.get('filename', 'Unknown_File')
    confidence = message.get('confidence', 0.0)
    sender = message.get('sender', '')
    summary = message.get('summary', '')
    priority_content = message.get('priority_content', {})
    vip_status = message.get('vip_status', {})
    vip_level = vip_status.get('vip_level', 'medium')
    
    print(f"\n [👑] Processing VIP document '{filename}' (Doc ID: {document_id}, Level: {vip_level})")
    
    routing_destination = "Unknown"
    try:
        # Always log VIP documents to sheets (both regular and VIP sheet if configured)
        log_to_google_sheet(filename, doc_type, confidence, True, vip_level, sender, summary)
        routing_destination = "VIP Google Sheets"
        
        # Send VIP priority notification
        send_vip_priority_notification(filename, vip_level, sender, summary, priority_content)
        
        # Additional routing based on document type and urgency
        if doc_type == "URGENT_VIP_NOTICE" or vip_level == 'high':
            send_slack_alert(
                filename, 
                "HIGH PRIORITY VIP DOCUMENT - Immediate attention required", 
                doc_type, 
                True, 
                vip_level, 
                sender, 
                priority_content
            )
            routing_destination += " + Urgent VIP Alert"
        elif priority_content.get('urgency_level') == 'high':
            send_slack_alert(
                filename, 
                "VIP document with high priority content detected", 
                doc_type, 
                True, 
                vip_level, 
                sender, 
                priority_content
            )
            routing_destination += " + Priority Alert"

        publish_status_update(
            doc_id=document_id,
            status="VIP Routed",
            details={
                "destination": routing_destination,
                "vip_level": vip_level,
                "priority_items": len(priority_content) if priority_content else 0
            },
            doc_type=doc_type,
            confidence=confidence,
            is_vip=True
        )
        
        print(f"  -> VIP document '{filename}' routed to {routing_destination}")
        return True

    except Exception as e:
        print(f" [e] Error routing VIP document '{filename}': {e}")
        publish_status_update(
            doc_id=document_id,
            status="VIP Routing Failed",
            details={"error": str(e)},
            is_vip=True
        )
        return False

def main():
    """Enhanced main loop handling both regular and VIP documents"""
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Successfully connected to RabbitMQ.')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    
    # Declare both queues
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    channel.queue_declare(queue=VIP_CONSUME_QUEUE_NAME, durable=True)
    
    print(' [*] Enhanced Router Agent with VIP support waiting for messages.')

    def regular_callback(ch, method, properties, body):
        """Handle regular documents"""
        message = json.loads(body)
        try:
            if process_regular_document(message):
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                # Don't acknowledge failed messages - they'll be retried
                pass
        except Exception as e:
            print(f" [e] Critical error in regular document processing: {e}")

    def vip_callback(ch, method, properties, body):
        """Handle VIP documents"""
        message = json.loads(body)
        try:
            if process_vip_document(message):
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                # Don't acknowledge failed messages - they'll be retried
                pass
        except Exception as e:
            print(f" [e] Critical error in VIP document processing: {e}")

    # Set up consumers for both queues
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=regular_callback)
    channel.basic_consume(queue=VIP_CONSUME_QUEUE_NAME, on_message_callback=vip_callback)
    
    # Set QoS to handle VIP documents with higher priority
    channel.basic_qos(prefetch_count=1)
    
    print(' [*] Router ready to handle both regular and VIP documents.')
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        exit(0)