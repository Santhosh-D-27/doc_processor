# router/main.py

import pika
import json
import os
import requests
import sys
import time
from datetime import datetime, UTC # ADD THIS

# --- Google Sheets API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue' # Must match Classifier's publish queue
STATUS_QUEUE_NAME = 'document_status_queue'

# SECRETS (retrieved from environment variables)
# Google Sheets API credentials will be picked up automatically via GOOGLE_APPLICATION_CREDENTIALS env var
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID") # The ID of your Google Sheet
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Define the range where data will be appended (e.g., 'Sheet1!A:D' for columns A,B,C,D)
SHEET_RANGE_NAME = 'Sheet1!A:D' # Adjust 'Sheet1' if your sheet has a different name

# --- Google Sheets Service Initialization ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') # Path to your JSON key file

sheets_service = None # Global variable for the Sheets API service

def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None):
    """
    Publishes a status update for a document to the status queue.
    """
    if details is None:
        details = {}

    status_message = {
        "document_id": doc_id,
        "status": status,
       "timestamp": datetime.now(UTC).isoformat(), # Add "Z" for UTC, # Use datetime.utcnow() from datetime import datetime
        "details": details,
        "doc_type": doc_type, # Include classified type if available
        "confidence": confidence # Include confidence if available
    }
    
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=STATUS_QUEUE_NAME,
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2) # Make message persistent
        )
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except pika.exceptions.AMQPConnectionError as e:
        print(f" [!!!] WARNING: Could not publish status update for {doc_id} to {STATUS_QUEUE_NAME}. RabbitMQ connection error: {e}")
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
            sheets_service = None # Reset to ensure re-attempt
    return sheets_service

# --- EXTERNAL SYSTEMS INTEGRATION FUNCTIONS ---

def log_to_google_sheet(filename: str, doc_type: str, confidence: float) -> bool:
    """Logs a processed document to Google Sheets."""
    service = get_sheets_service()
    if not service or not GOOGLE_SHEET_ID:
        print("  -> Google Sheets service not available or SHEET_ID not set. Skipping logging.")
        return False

    print(f"  -> Calling Google Sheets API to log '{filename}'...")
    try:
        # Data to append (make sure the order matches your sheet columns: Filename, DocType, Confidence, ProcessedAt)
        values = [
            filename,
            doc_type,
            confidence,
            time.strftime('%Y-%m-%d %H:%M:%S') # Current timestamp
        ]
        body = {
            'values': [values]
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=SHEET_RANGE_NAME,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        print(f"  -> Successfully added {result.get('updates').get('updatedCells')} cells to Google Sheet.")
        return True
    except Exception as e:
        print(f"  -> ERROR: Failed to log to Google Sheet: {e}")
        return False

def send_slack_alert(filename: str, reason: str, doc_type: str = "N/A"):
    """Sends a notification to a Slack channel."""
    if not SLACK_WEBHOOK_URL:
        print("  -> ERROR: Slack Webhook URL not set. Skipping Slack alert.")
        return

    print(f"  -> Sending Slack alert for '{filename}'...")
    message = {
        "text": f":warning: Document Needs Review: `{filename}`",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Document Needs Review*\n A document has been flagged for manual processing."
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*File:*\n`{filename}`"},
                    {"type": "mrkdwn", "text": f"*Type:*\n`{doc_type}`"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"}
                ]
            }
        ]
    }
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)
        response.raise_for_status()
        print("  -> Successfully sent Slack alert.")
    except requests.exceptions.RequestException as e:
        print(f"  -> ERROR: Failed to send Slack alert: {e}")

# --- MAIN AGENT LOGIC ---
# In router/main.py, replace the entire main() function

def main():
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Successfully connected to RabbitMQ.')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    print(' [*] REAL Router Agent waiting for messages. To exit press CTRL+C')


    def callback(ch, method, properties, body):
        message = json.loads(body)
        document_id = message.get('document_id', 'unknown_id')
        doc_type = message.get('doc_type', 'UNKNOWN')
        filename = message.get('filename', 'Unknown_File')
        confidence = message.get('confidence', 0.0)
        
        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for final routing.")
        
        routing_destination = "Unknown"
        try:
            if doc_type in ["INVOICE", "RECEIPT", "CONTRACT", "RESUME", "MEMO"]:
                log_to_google_sheet(filename, doc_type, confidence) 
                routing_destination = "Google Sheets"
            elif doc_type == "NEEDS_HUMAN_REVIEW":
                send_slack_alert(filename, f"Low confidence score ({confidence:.2f})", doc_type)
                routing_destination = "Human Review (Slack)"
            else:
                send_slack_alert(filename, f"Unhandled document type: '{doc_type}'", doc_type)
                routing_destination = "Fallback (Slack)"

            # --- CORRECTED STATUS UPDATE ---
            # Now, we pass along the doc_type and confidence
            publish_status_update(
                doc_id=document_id,
                status="Routed",
                details={"destination": routing_destination},
                doc_type=doc_type,
                confidence=confidence
            )

            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"  -> Finished routing process for '{filename}'.")

        except Exception as e:
            print(f" [e] A critical error occurred during routing: {e}")
            publish_status_update(
                doc_id=document_id,
                status="Routing Failed",
                details={"error": str(e)}
            )
    
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    main()