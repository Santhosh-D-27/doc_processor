import email
import imaplib
import os
import time
import pika
import json
import base64
import sqlite3
import uuid
import google.generativeai as genai
from datetime import date, datetime, UTC
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
DB_NAME = 'web_ui/state.db'
IMAP_SERVER = "imap.gmail.com"
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
QUEUE_NAME = 'doc_received_queue'
STATUS_QUEUE_NAME = 'document_status_queue'
STORAGE_PATH = 'document_storage' # Our persistent storage folder

# Configure Google AI Client
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized.")
except Exception as e:
    print(f"[e] Google Gemini client failed to initialize: {e}")
    model = None

# --- DATABASE FUNCTIONS ---
def get_mailboxes_from_db():
    mailboxes = []
    if not os.path.exists(DB_NAME):
        # Initial database setup will be handled by web_ui/main.py lifespan
        # If DB doesn't exist yet, just return empty list.
        print("[DB] Database file not found, no mailboxes to fetch yet.")
        return []
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT email, app_password_encoded, folder FROM mailboxes WHERE status = 'Connected'")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            mailboxes.append(dict(row))
        return mailboxes
    except Exception as e:
        print(f"[DB Error] Could not fetch mailboxes: {e}")
        return []

def setup_state_db(conn):
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS processed_emails (uid TEXT PRIMARY KEY)')
    conn.commit()

def load_processed_ids(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM processed_emails")
    return {row[0] for row in cursor.fetchall()}

def save_processed_id(conn, uid):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO processed_emails (uid) VALUES (?)", (uid,))
    conn.commit()

# --- HELPER FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None):
    if details is None: details = {}
    status_message = {
        "document_id": doc_id, "status": status,
        "timestamp": datetime.now(UTC).isoformat(), "details": details
    }
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, body=json.dumps(status_message))
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def summarize_with_llm(body: str) -> str:
    if not model: return "Could not summarize: Gemini client not available."
    if not body or not body.strip(): return "Email body was empty."
    try:
        prompt = f"Summarize the following email body in one sentence to provide context for an attached document:\n\n---\n{body}\n---"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not summarize: {e}"

def publish_message(message: dict):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(message),
        properties=pika.BasicProperties(delivery_mode=2)
    )
    connection.close()
    doc_id = message.get('document_id')
    print(f" [x] Sent '{message['filename']}' from email to the queue (Doc ID: {doc_id}).")

# --- MAIN PROCESSING LOGIC ---
def process_single_mailbox(config):
    email_address = config['email']
    app_password = base64.b64decode(config['app_password_encoded']).decode()
    folder = config['folder']
    
    print(f"\n[*] Checking mailbox: {email_address} in folder: '{folder}'")
    
    state_db_path = f"ingestor/state_{email_address}.db"
    state_conn = sqlite3.connect(state_db_path)
    setup_state_db(state_conn)
    processed_ids = load_processed_ids(state_conn)
    print(f"[*] Loaded {len(processed_ids)} previously processed email UIDs for {email_address}.")

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(email_address, app_password)
        mail.select(f'"{folder}"')
        
        search_query = f'(SINCE "{date.today().strftime("%d-%b-%Y")}")'
        status, messages = mail.search(None, search_query)
        
        if status != "OK": return

        email_uids = messages[0].split()
        if not email_uids:
            print(f"[*] No new emails found for {email_address}.")
            return

        for uid_bytes in email_uids:
            uid_str = uid_bytes.decode()
            if uid_str in processed_ids:
                continue

            print(f"\n[!] Found new email to process with UID: {uid_str}")
            status, data = mail.fetch(uid_bytes, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            sender, subject, email_body = msg["From"], msg["Subject"], ""

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get_filename():
                        email_body = part.get_payload(decode=True).decode(errors='ignore'); break
            else:
                email_body = msg.get_payload(decode=True).decode(errors='ignore')
            
            summary = summarize_with_llm(email_body)
            print(f" [i] Gemini Summary: {summary}")

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart' or not part.get('Content-Disposition') or not part.get_filename():
                    continue
                
                document_id = str(uuid.uuid4())
                original_filename = part.get_filename()
                
                file_extension = os.path.splitext(original_filename)[1]
                storage_filename = f"{document_id}{file_extension}"
                storage_file_path = os.path.join(STORAGE_PATH, storage_filename)

                file_content = part.get_payload(decode=True)

                # --- NEW: Save the original attachment to local storage ---
                os.makedirs(STORAGE_PATH, exist_ok=True)
                with open(storage_file_path, "wb") as f:
                    f.write(file_content)
                print(f"  -> Saved original attachment to: {storage_file_path}")
                
                encoded_content = base64.b64encode(file_content).decode('utf-8')
                message = {
                    'document_id': document_id, 'filename': original_filename,
                    'storage_path': storage_file_path, # Pass the new path
                    'content_type': part.get_content_type(), 'file_content': encoded_content,
                    'priority': 'high', 'source': 'email_hook', 'sender': sender, 'context': summary
                }
                publish_message(message)
                publish_status_update(
                    doc_id=document_id, status="Ingested",
                    details={"filename": original_filename, "source": f"Email ({email_address})", "storage_path": storage_file_path, "file_content_encoded": encoded_content, "content_type": part.get_content_type(), "sender": sender} # Pass content for re-extract
                )

            save_processed_id(state_conn, uid_str)
            print(f"[+] Finished processing and saved email UID: {uid_str}")
            
        mail.logout()
    except Exception as e:
        print(f"[Mailbox Error] Failed to process {email_address}: {e}")
    finally:
        state_conn.close()

if __name__ == "__main__":
    print("[*] Starting Dynamic Email Ingestor Agent...")
    while True:
        mailbox_configs = get_mailboxes_from_db()
        if not mailbox_configs:
            print("[*] No mailboxes configured. Waiting...")
        else:
            print(f"[*] Found {len(mailbox_configs)} mailboxes to process.")
            for config in mailbox_configs:
                process_single_mailbox(config)

        print(f"\n[*] Cycle complete. Waiting for 10 seconds before next check...")
        time.sleep(10)