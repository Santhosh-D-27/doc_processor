# ingestor/main.py - OAuth-based Ingestor Agent with Priority Queue Router

import uuid
import time
import pika
import json
import base64
import os
import shutil
import uvicorn
import sqlite3
import threading
import secrets
import google.generativeai as genai
from datetime import date, datetime, UTC, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from enum import IntEnum
from typing import Tuple, Optional
from urllib.parse import urlencode
import requests

load_dotenv()

# Priority Configuration
class Priority(IntEnum):
    CRITICAL = 100
    HIGH = 80
    MEDIUM = 50
    LOW = 20
    BULK = 10

PRIORITY_QUEUES = {
    Priority.CRITICAL: 'doc_received_critical',
    Priority.HIGH: 'doc_received_high',
    Priority.MEDIUM: 'doc_received_medium',
    Priority.LOW: 'doc_received_low',
    Priority.BULK: 'doc_received_bulk'
}

# Configuration
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DB_NAME = 'web_ui/state.db'
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
STATUS_QUEUE_NAME = 'document_status_queue'
STORAGE_PATH = 'document_storage'
MONITORED_PATH = './monitored_folder'
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/userinfo.email']

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.getenv('OAUTH_REDIRECT_URI')

# Initialize Google AI
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
except Exception:
    model = None

# Database Functions
def setup_oauth_database():
    """Ensure OAuth tables exist with proper structure"""
    os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            email TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            email TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mailboxes (
            email TEXT PRIMARY KEY,
            status TEXT DEFAULT 'connected',
            connected_at TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def get_oauth_mailboxes_from_db():
    setup_oauth_database()
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.email, m.connected_at, t.expires_at 
                FROM mailboxes m 
                JOIN oauth_tokens t ON m.email = t.email 
                WHERE m.status = 'connected' AND t.status = 'active'
            """)
            mailboxes = [dict(row) for row in cursor.fetchall()]
            
            if mailboxes:
                print(f"[OAuth] Found {len(mailboxes)} connected mailboxes: {[m['email'] for m in mailboxes]}")
            else:
                print("[OAuth] No connected mailboxes found")
                
            return mailboxes
    except Exception as e:
        print(f"[OAuth] Error fetching mailboxes: {e}")
        return []

def setup_and_load_state_db(email):
    state_db_path = f"ingestor/state_{email.replace('@', '_').replace('.', '_')}.db"
    os.makedirs(os.path.dirname(state_db_path), exist_ok=True)
    
    with sqlite3.connect(state_db_path) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS processed_emails (uid TEXT PRIMARY KEY)')
        conn.commit()
        cursor = conn.cursor()
        cursor.execute("SELECT uid FROM processed_emails")
        processed_ids = {row[0] for row in cursor.fetchall()}
    
    return state_db_path, processed_ids

def save_processed_id(state_db_path, uid):
    with sqlite3.connect(state_db_path) as conn:
        conn.execute("INSERT INTO processed_emails (uid) VALUES (?)", (uid,))
        conn.commit()

def disconnect_mailbox(email: str):
    """Disconnect and revoke OAuth for a mailbox"""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            
            # Get the access token for revocation
            cursor.execute('SELECT access_token FROM oauth_tokens WHERE email = ? AND status = "active"', (email,))
            result = cursor.fetchone()
            
            if result:
                access_token = result[0]
                
                # Revoke the token with Google
                try:
                    revoke_url = f'https://oauth2.googleapis.com/revoke?token={access_token}'
                    response = requests.post(revoke_url)
                    if response.status_code == 200:
                        print(f"[OAuth] Successfully revoked token for {email}")
                    else:
                        print(f"[OAuth] Warning: Token revocation returned status {response.status_code} for {email}")
                except Exception as revoke_error:
                    print(f"[OAuth] Error revoking token for {email}: {revoke_error}")
            
            # Update database
            cursor.execute('UPDATE oauth_tokens SET status = "revoked" WHERE email = ?', (email,))
            cursor.execute('UPDATE mailboxes SET status = "disconnected" WHERE email = ?', (email,))
            conn.commit()
            
            print(f"[OAuth] ✅ Signed out and disconnected mailbox: {email} at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            return True
            
    except Exception as e:
        print(f"[OAuth] ❌ Error disconnecting mailbox {email}: {e}")
        return False

# Messaging Functions
def publish_to_queue(queue_name, message):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        channel.basic_publish(exchange='', routing_key=queue_name, body=json.dumps(message), properties=pika.BasicProperties(delivery_mode=2))
        connection.close()
    except Exception as e:
        print(f"Failed to publish to {queue_name}: {e}")
        raise

def publish_status_update(doc_id: str, status: str, details: dict = None):
    message = {"document_id": doc_id, "status": status, "timestamp": datetime.now(UTC).isoformat(), "details": details or {}}
    publish_to_queue(STATUS_QUEUE_NAME, message)

def publish_message(message: dict):
    priority_score = message.get('priority_score', Priority.LOW)
    queue_name = PRIORITY_QUEUES.get(priority_score, PRIORITY_QUEUES[Priority.LOW])
    publish_to_queue(queue_name, message)

# Utility Functions
def summarize_with_llm(body: str) -> str:
    if not model or not body.strip():
        return "Could not summarize: Gemini unavailable or empty body."
    try:
        prompt = f"Summarize the following email body in one sentence:\n\n---\n{body}\n---"
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        return f"Could not summarize: {e}"

def decide_priority(file_size: int, sender: str = None) -> Tuple[int, str]:
    if sender:
        sender_lower = sender.lower()
        if any(title in sender_lower for title in ["ceo", "director", "vp"]):
            return Priority.CRITICAL, f"Executive sender: {sender}"
        elif any(title in sender_lower for title in ["manager", "lead"]):
            return Priority.HIGH, f"Management sender: {sender}"
    
    if file_size > 5_000_000:
        return Priority.HIGH, f"Large file: {file_size} bytes"
    elif file_size > 1_000_000:
        return Priority.MEDIUM, f"Medium file: {file_size} bytes"
    else:
        return Priority.LOW, f"Standard priority: {file_size} bytes"

# OAuth Gmail Service
# Replace the get_gmail_service function with this fixed version

def get_gmail_service(email: str):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE email = ? AND status = "active"', (email,))
            result = cursor.fetchone()
            
            if not result:
                print(f"[OAuth] No active token found for {email}")
                return None
            
            access_token, refresh_token, expires_at = result
            credentials = Credentials(
                token=access_token, 
                refresh_token=refresh_token, 
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID, 
                client_secret=GOOGLE_CLIENT_SECRET, 
                scopes=SCOPES
            )
            
            # CRITICAL FIX: Google's OAuth library expects timezone-NAIVE datetimes
            if expires_at:
                try:
                    # Parse the stored datetime string
                    expiry_dt = datetime.fromisoformat(expires_at)
                    
                    # Convert timezone-aware datetime to UTC naive datetime
                    # Google's library uses timezone-naive UTC internally
                    if expiry_dt.tzinfo is not None:
                        # Convert to UTC and make it naive
                        expiry_dt = expiry_dt.astimezone(UTC).replace(tzinfo=None)
                    
                    credentials.expiry = expiry_dt
                    print(f"[OAuth] Token expires at (UTC naive): {expiry_dt}")
                    
                except Exception as dt_error:
                    print(f"[OAuth] Warning: Could not parse expiry datetime '{expires_at}': {dt_error}")
                    # If we can't parse the expiry, set it to None and let Google handle it
                    credentials.expiry = None
            
            # Create and return the Gmail service
            try:
                service = build('gmail', 'v1', credentials=credentials)
                print(f"[OAuth] ✅ Gmail service created successfully for {email}")
                
                # After successful service creation, check if token was refreshed
                # and update the database if needed
                if credentials.token != access_token:
                    print(f"[OAuth] 🔄 Token was refreshed during service creation for {email}")
                    new_expiry = None
                    if credentials.expiry:
                        # Store as timezone-aware ISO string for consistency
                        new_expiry = credentials.expiry.replace(tzinfo=UTC).isoformat()
                    
                    cursor.execute(
                        'UPDATE oauth_tokens SET access_token = ?, expires_at = ? WHERE email = ?', 
                        (credentials.token, new_expiry, email)
                    )
                    conn.commit()
                    print(f"[OAuth] ✅ Updated refreshed token in database for {email}")
                
                return service
                
            except Exception as service_error:
                print(f"[OAuth] Error creating Gmail service for {email}: {service_error}")
                return None
                
    except Exception as e:
        print(f"[OAuth] Error getting Gmail service for {email}: {e}")
        return None

def extract_email_body(payload) -> str:
    def extract_text(part):
        if 'parts' in part:
            for subpart in part['parts']:
                text = extract_text(subpart)
                if text:
                    return text
        elif part['mimeType'] in ['text/plain', 'text/html'] and 'data' in part['body']:
            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
        return ""
    
    if 'parts' in payload:
        for part in payload['parts']:
            text = extract_text(part)
            if text:
                return text
    elif payload['body'].get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return ""

def download_attachment(service, message_id: str, attachment_id: str) -> Optional[bytes]:
    try:
        print(f"[OAuth] ⬇️  Downloading attachment {attachment_id} from message {message_id}")
        attachment = service.users().messages().attachments().get(
            userId='me', 
            messageId=message_id, 
            id=attachment_id
        ).execute()
        
        attachment_data = base64.urlsafe_b64decode(attachment['data'])
        print(f"[OAuth] ✅ Downloaded {len(attachment_data)} bytes")
        return attachment_data
        
    except Exception as e:
        print(f"[OAuth] ❌ Error downloading attachment {attachment_id}: {e}")
        return None

def process_attachment(service, message_id, part, sender, subject, summary):
    try:
        filename = part.get('filename', '')
        attachment_id = part['body'].get('attachmentId')
        
        if not filename or not attachment_id:
            return False
        
        print(f"[OAuth] 📎 Processing attachment: {filename}")
        
        document_id = str(uuid.uuid4())
        file_content = download_attachment(service, message_id, attachment_id)
        
        if not file_content:
            print(f"[OAuth] ❌ Failed to download attachment: {filename}")
            return False
        
        file_size = len(file_content)
        priority_score, priority_reason = decide_priority(file_size, sender)
        
        print(f"[OAuth] 📊 File size: {file_size} bytes, Priority: {priority_score} ({priority_reason})")
        
        # Save to storage
        file_extension = os.path.splitext(filename)[1]
        storage_filename = f"{document_id}{file_extension}"
        storage_file_path = os.path.join(STORAGE_PATH, storage_filename)
        
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(storage_file_path, "wb") as f:
            f.write(file_content)
        
        print(f"[OAuth] 💾 Saved attachment to: {storage_file_path}")
        
        # Prepare and send message
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        message_data = {
            'document_id': document_id, 
            'filename': filename, 
            'storage_path': storage_file_path,
            'content_type': part.get('mimeType', 'application/octet-stream'), 
            'file_content': encoded_content,
            'priority_score': priority_score, 
            'priority_reason': priority_reason, 
            'source': 'oauth_email',
            'sender': sender, 
            'context': summary, 
            'email_subject': subject
        }
        
        publish_message(message_data)
        publish_status_update(document_id, "Ingested", {
            "filename": filename, 
            "source": "OAuth Email", 
            "storage_path": storage_file_path,
            "file_content_encoded": encoded_content, 
            "content_type": part.get('mimeType', 'application/octet-stream'),
            "sender": sender, 
            "email_subject": subject, 
            "priority_score": priority_score, 
            "priority_reason": priority_reason
        })
        
        print(f"[OAuth] ✅ Successfully processed attachment: {filename} (ID: {document_id})")
        return True
        
    except Exception as e:
        print(f"[OAuth] ❌ Error processing attachment {part.get('filename', 'unknown')}: {e}")
        return False

# Email Processing
def process_oauth_mailbox(email_address):
    print(f"[OAuth] 📧 Checking mailbox: {email_address}")
    service = get_gmail_service(email_address)
    if not service:
        print(f"[OAuth] ❌ Failed to get Gmail service for {email_address}")
        return
    
    state_db_path, processed_ids = setup_and_load_state_db(email_address)
    
    try:
        # Fix: Use timezone-aware date calculation
        search_date = (datetime.now(UTC).date() - timedelta(days=7)).strftime("%Y/%m/%d")
        print(f"[OAuth] 🔍 Searching for emails after: {search_date}")
        
        results = service.users().messages().list(
            userId='me', 
            q=f'after:{search_date} has:attachment', 
            maxResults=50
        ).execute()
        messages = results.get('messages', [])
        
        print(f"[OAuth] 📬 Found {len(messages)} messages with attachments in {email_address} (last 7 days)")
        
        if not messages:
            print(f"[OAuth] ℹ️  No messages with attachments found in {email_address}")
            return
        
        processed_count = 0
        for message in messages:
            message_id = message['id']
            if message_id in processed_ids:
                continue
            
            try:
                msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
                headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
                sender = headers.get('From', 'Unknown')
                subject = headers.get('Subject', 'No Subject')
                
                print(f"[OAuth] 📨 Processing message from {sender}: {subject}")
                
                email_body = extract_email_body(msg['payload'])
                summary = summarize_with_llm(email_body[:1000]) if email_body else "No email body content found"
                
                attachments_processed = 0
                def process_part(part):
                    nonlocal attachments_processed
                    if 'parts' in part:
                        for subpart in part['parts']:
                            process_part(subpart)
                    elif process_attachment(service, message_id, part, sender, subject, summary):
                        attachments_processed += 1
                
                process_part(msg['payload'])
                
                if attachments_processed > 0:
                    processed_count += 1
                    print(f"[OAuth] ✅ Processed {attachments_processed} attachments from {sender} - {subject}")
                else:
                    print(f"[OAuth] ℹ️  No valid attachments found in message from {sender}")
                
                save_processed_id(state_db_path, message_id)
                
            except Exception as e:
                print(f"[OAuth] ❌ Error processing message {message_id}: {e}")
                continue
        
        if processed_count > 0:
            print(f"[OAuth] 📈 Total processed: {processed_count} emails with attachments from {email_address}")
        else:
            print(f"[OAuth] ℹ️  No new attachments processed from {email_address}")
            
    except Exception as e:
        print(f"[OAuth] ❌ Error processing mailbox {email_address}: {e}")
        import traceback
        print(f"[OAuth] ❌ Full traceback: {traceback.format_exc()}")

def email_monitor_loop():
    print("[OAuth Monitor] 🚀 Starting OAuth email monitor...")
    while True:
        try:
            mailbox_configs = get_oauth_mailboxes_from_db()
            if mailbox_configs:
                print(f"[OAuth Monitor] 🔄 Checking {len(mailbox_configs)} connected mailboxes...")
                for config in mailbox_configs:
                    try:
                        process_oauth_mailbox(config['email'])
                    except Exception as mailbox_error:
                        print(f"[OAuth Monitor] ❌ Error processing mailbox {config['email']}: {mailbox_error}")
                        continue
            else:
                print("[OAuth Monitor] ⏳ No connected mailboxes to check")
            
            print(f"[OAuth Monitor] ⏸️  Sleeping for 30 seconds... (Next check at {(datetime.now(UTC) + timedelta(seconds=30)).strftime('%H:%M:%S UTC')})")
            time.sleep(10)  # Check every 30 seconds
            
        except Exception as e:
            print(f"[OAuth Monitor] ❌ Error in monitor loop: {e}")
            import traceback
            print(f"[OAuth Monitor] ❌ Full traceback: {traceback.format_exc()}")
            time.sleep(10)

# File Monitoring
class DocumentHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or event.src_path.endswith('.tmp'):
            return
        
        document_id = str(uuid.uuid4())
        original_filename = os.path.basename(event.src_path)
        file_extension = os.path.splitext(original_filename)[1]
        storage_filename = f"{document_id}{file_extension}"
        storage_file_path = os.path.join(STORAGE_PATH, storage_filename)
        
        try:
            time.sleep(1)
            os.makedirs(STORAGE_PATH, exist_ok=True)
            shutil.copy(event.src_path, storage_file_path)
            
            with open(storage_file_path, 'rb') as file:
                file_content = file.read()
            
            file_size = len(file_content)
            priority_score, priority_reason = decide_priority(file_size, os.path.dirname(event.src_path))
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            message = {
                'document_id': document_id, 'filename': original_filename, 'storage_path': storage_file_path,
                'content_type': 'application/octet-stream', 'file_content': encoded_content,
                'priority_score': priority_score, 'priority_reason': priority_reason,
                'source': 'file_share', 'sender': 'system_fileshare_monitor'
            }
            
            publish_message(message)
            publish_status_update(document_id, "Ingested", {
                "filename": original_filename, "source": "File Share", "storage_path": storage_file_path,
                "file_content_encoded": encoded_content, "content_type": 'application/octet-stream',
                "sender": 'system_fileshare_monitor', "priority_score": priority_score, "priority_reason": priority_reason
            })
        except Exception as e:
            publish_status_update(document_id, "Ingestion Failed", {"filename": original_filename, "error": str(e)})

def start_file_monitor():
    os.makedirs(MONITORED_PATH, exist_ok=True)
    event_handler = DocumentHandler()
    observer = Observer()
    observer.schedule(event_handler, MONITORED_PATH, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except Exception:
        observer.stop()
    observer.join()

# OAuth Endpoints
@app.get("/", response_class=HTMLResponse)
async def oauth_home():
    """OAuth management home page"""
    mailboxes = get_oauth_mailboxes_from_db()
    
    mailbox_rows = ""
    for mailbox in mailboxes:
        mailbox_rows += f"""
        <tr>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{mailbox['email']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">Connected</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{mailbox['connected_at']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                <button onclick="disconnectMailbox('{mailbox['email']}')" 
                        class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded">
                    Disconnect
                </button>
            </td>
        </tr>
        """
    
    if not mailbox_rows:
        mailbox_rows = """
        <tr>
            <td colspan="4" class="px-6 py-4 text-center text-gray-500">
                No connected mailboxes. Click "Connect Mailbox" to get started.
            </td>
        </tr>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>OAuth Gmail Manager</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100">
        <div class="container mx-auto px-4 py-8">
            <div class="bg-white rounded-lg shadow-md p-6">
                <h1 class="text-3xl font-bold text-gray-900 mb-6">Gmail OAuth Manager</h1>
                
                <div class="mb-6">
                    <button onclick="connectMailbox()" 
                            class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-medium">
                        🔗 Connect New Mailbox
                    </button>
                </div>
                
                <div class="overflow-hidden shadow ring-1 ring-black ring-opacity-5 md:rounded-lg">
                    <table class="min-w-full divide-y divide-gray-300">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Connected At</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {mailbox_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <script>
            function connectMailbox() {{
                window.location.href = '/oauth/connect';
            }}
            
            async function disconnectMailbox(email) {{
                if (confirm(`Are you sure you want to disconnect ${{email}}?`)) {{
                    try {{
                        const response = await fetch(`/oauth/disconnect/${{encodeURIComponent(email)}}`, {{
                            method: 'POST'
                        }});
                        const result = await response.json();
                        if (result.success) {{
                            alert('Mailbox disconnected successfully!');
                            window.location.reload();
                        }} else {{
                            alert('Error: ' + result.error);
                        }}
                    }} catch (error) {{
                        alert('Error disconnecting mailbox: ' + error.message);
                    }}
                }}
            }}
        </script>
    </body>
    </html>
    """

@app.get("/oauth/connect")
async def oauth_connect():
    """Start OAuth flow"""
    state = secrets.token_urlsafe(32)
    
    # Store state in database
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO oauth_states (state, email, created_at, expires_at) 
            VALUES (?, ?, ?, ?)
        ''', (
            state, 
            '', 
            datetime.now(UTC).isoformat(),
            (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        ))
        conn.commit()
    
    auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urlencode({
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': ' '.join(SCOPES),
        'response_type': 'code',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state
    })
    
    print(f"[OAuth] 🔗 Starting OAuth flow with state: {state}")
    return RedirectResponse(url=auth_url)

# Fixed OAuth callback handler - Replace the existing callback function

# Fixed OAuth callback handler - Replace the existing callback function

@app.get("/oauth/gmail/callback")
async def oauth_callback(request: Request):
    """Handle OAuth callback with improved error handling"""
    try:
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        error = request.query_params.get('error')
        
        print(f"[OAuth Callback] Received - code: {bool(code)}, state: {state}, error: {error}")
        
        if error:
            print(f"[OAuth] ❌ OAuth error: {error}")
            return HTMLResponse(f"""
            <html>
            <head><title>OAuth Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ OAuth Error</h1>
                <p>Error: {error}</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        if not code or not state:
            print(f"[OAuth] ❌ Missing parameters - code: {bool(code)}, state: {bool(state)}")
            return HTMLResponse("""
            <html>
            <head><title>OAuth Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ OAuth Error</h1>
                <p>Missing required parameters from Google</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        # Verify and cleanup state
        state_valid = False
        try:
            setup_oauth_database()
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM oauth_states WHERE state = ?', (state,))
                state_record = cursor.fetchone()
                
                if state_record:
                    print(f"[OAuth] ✅ Valid state found: {state}")
                    state_valid = True
                    cursor.execute('DELETE FROM oauth_states WHERE state = ?', (state,))
                    conn.commit()
                else:
                    print(f"[OAuth] ❌ Invalid or expired state: {state}")
        
        except Exception as db_error:
            print(f"[OAuth] ❌ Database error during state validation: {db_error}")
            return HTMLResponse(f"""
            <html>
            <head><title>Database Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Database Error</h1>
                <p>Could not validate OAuth state: {str(db_error)}</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        if not state_valid:
            return HTMLResponse("""
            <html>
            <head><title>OAuth Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ OAuth Error</h1>
                <p>Invalid or expired state parameter. Please try connecting again.</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        # Exchange code for tokens
        print(f"[OAuth] 🔄 Exchanging authorization code for tokens...")
        try:
            token_data = {
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': REDIRECT_URI,
            }
            
            response = requests.post('https://oauth2.googleapis.com/token', data=token_data, timeout=30)
            
            if response.status_code != 200:
                print(f"[OAuth] ❌ Token request failed with status {response.status_code}: {response.text}")
                return HTMLResponse(f"""
                <html>
                <head><title>Token Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ Token Exchange Failed</h1>
                    <p>Status: {response.status_code}</p>
                    <p>Google returned an error when exchanging the authorization code</p>
                    <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                        Try Again
                    </a>
                </body>
                </html>
                """)
            
            tokens = response.json()
            
            if 'error' in tokens:
                print(f"[OAuth] ❌ Token exchange error: {tokens}")
                return HTMLResponse(f"""
                <html>
                <head><title>Token Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ Token Error</h1>
                    <p>Error: {tokens.get('error', 'Unknown error')}</p>
                    <p>Description: {tokens.get('error_description', 'No description')}</p>
                    <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                        Try Again
                    </a>
                </body>
                </html>
                """)
            
            print(f"[OAuth] ✅ Successfully received tokens")
            
            # Get user email
            access_token = tokens['access_token']
            user_response = requests.get(
                f'https://www.googleapis.com/oauth2/v2/userinfo?access_token={access_token}',
                timeout=30
            )
            
            if user_response.status_code != 200:
                print(f"[OAuth] ❌ User info request failed: {user_response.status_code}")
                return HTMLResponse("""
                <html>
                <head><title>User Info Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ User Info Error</h1>
                    <p>Could not retrieve user information from Google</p>
                    <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                        Try Again
                    </a>
                </body>
                </html>
                """)
            
            user_info = user_response.json()
            email = user_info.get('email')
            
            if not email:
                print(f"[OAuth] ❌ No email in user info: {user_info}")
                return HTMLResponse("""
                <html>
                <head><title>Email Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ Email Error</h1>
                    <p>Could not retrieve your email address from Google</p>
                    <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                        Try Again
                    </a>
                </body>
                </html>
                """)
            
            print(f"[OAuth] ✅ Retrieved user email: {email}")
            
            # Store tokens and mailbox info with proper timezone handling
            expires_at = None
            if 'expires_in' in tokens:
                # Create timezone-aware datetime and store as ISO string
                expires_at = (datetime.now(UTC) + timedelta(seconds=tokens['expires_in'])).isoformat()
                print(f"[OAuth] Token will expire at: {expires_at}")
            
            try:
                with sqlite3.connect(DB_NAME) as conn:
                    cursor = conn.cursor()
                    
                    # Store/update tokens
                    cursor.execute('''
                        INSERT OR REPLACE INTO oauth_tokens 
                        (email, access_token, refresh_token, expires_at, created_at, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        email,
                        tokens.get('access_token'),
                        tokens.get('refresh_token'),
                        expires_at,
                        datetime.now(UTC).isoformat(),
                        'active'
                    ))
                    
                    # Store/update mailbox
                    cursor.execute('''
                        INSERT OR REPLACE INTO mailboxes (email, status, connected_at)
                        VALUES (?, ?, ?)
                    ''', (
                        email,
                        'connected',
                        datetime.now(UTC).isoformat()
                    ))
                    
                    conn.commit()
                    print(f"[OAuth] ✅ Successfully stored tokens and mailbox info for {email}")
                
            except Exception as db_error:
                print(f"[OAuth] ❌ Database error storing tokens: {db_error}")
                return HTMLResponse(f"""
                <html>
                <head><title>Storage Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ Storage Error</h1>
                    <p>Could not save your OAuth tokens: {str(db_error)}</p>
                    <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                        Try Again
                    </a>
                </body>
                </html>
                """)
            
            print(f"[OAuth] ✅ Successfully connected mailbox: {email} at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            return HTMLResponse(f"""
            <html>
            <head><title>Success</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: green;">✅ Success!</h1>
                <p>Mailbox <strong>{email}</strong> has been connected successfully.</p>
                <p>The system will now monitor this mailbox for email attachments.</p>
                <div style="margin: 30px 0;">
                    <a href="/" style="background: #28a745; color: white; text-decoration: none; padding: 12px 24px; border-radius: 5px; margin: 0 10px;">
                        Return to Dashboard
                    </a>
                    <button onclick="window.close();" style="background: #6c757d; color: white; border: none; padding: 12px 24px; border-radius: 5px; cursor: pointer; margin: 0 10px;">
                        Close Window
                    </button>
                </div>
            </body>
            </html>
            """)
            
        except Exception as token_error:
            print(f"[OAuth] ❌ Error during token exchange: {token_error}")
            return HTMLResponse(f"""
            <html>
            <head><title>Token Exchange Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Token Exchange Error</h1>
                <p>An error occurred: {str(token_error)}</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Try Again
                </a>
            </body>
            </html>
            """)
            
    except Exception as e:
        print(f"[OAuth] ❌ Critical error in callback: {e}")
        return HTMLResponse(f"""
        <html>
        <head><title>Critical Error</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1 style="color: red;">❌ Critical Error</h1>
            <p>A critical error occurred: {str(e)}</p>
            <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                Return to Dashboard
            </a>
        </body>
        </html>
        """)
# Also add this improved connect endpoint
@app.get("/oauth/connect")
async def oauth_connect():
    """Start OAuth flow with improved error handling"""
    try:
        # Ensure database is set up
        setup_oauth_database()
        
        state = secrets.token_urlsafe(32)
        print(f"[OAuth] 🔗 Generated state: {state}")
        
        # Store state in database
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO oauth_states (state, email, created_at, expires_at) 
                    VALUES (?, ?, ?, ?)
                ''', (
                    state, 
                    '', 
                    datetime.now(UTC).isoformat(),
                    (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
                ))
                conn.commit()
                print(f"[OAuth] ✅ State stored in database")
        except Exception as db_error:
            print(f"[OAuth] ❌ Database error storing state: {db_error}")
            return HTMLResponse(f"""
            <html>
            <head><title>Database Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Database Error</h1>
                <p>Could not initialize OAuth flow: {str(db_error)}</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        # Validate required environment variables
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not REDIRECT_URI:
            missing = []
            if not GOOGLE_CLIENT_ID: missing.append("GOOGLE_CLIENT_ID")
            if not GOOGLE_CLIENT_SECRET: missing.append("GOOGLE_CLIENT_SECRET") 
            if not REDIRECT_URI: missing.append("OAUTH_REDIRECT_URI")
            
            print(f"[OAuth] ❌ Missing environment variables: {missing}")
            return HTMLResponse(f"""
            <html>
            <head><title>Configuration Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">❌ Configuration Error</h1>
                <p>Missing required environment variables: {', '.join(missing)}</p>
                <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                    Return to Dashboard
                </a>
            </body>
            </html>
            """)
        
        auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urlencode({
            'client_id': GOOGLE_CLIENT_ID,
            'redirect_uri': REDIRECT_URI,
            'scope': ' '.join(SCOPES),
            'response_type': 'code',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state
        })
        
        print(f"[OAuth] 🔗 Redirecting to: {auth_url[:100]}...")
        return RedirectResponse(url=auth_url)
        
    except Exception as e:
        print(f"[OAuth] ❌ Error in connect endpoint: {e}")
        return HTMLResponse(f"""
        <html>
        <head><title>Connection Error</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1 style="color: red;">❌ Connection Error</h1>
            <p>Could not start OAuth flow: {str(e)}</p>
            <a href="/" style="background: #007bff; color: white; text-decoration: none; padding: 10px 20px; border-radius: 5px;">
                Return to Dashboard
            </a>
        </body>
        </html>
        """)


# Add a debug endpoint to check configuration
@app.get("/debug/oauth-config")
async def debug_oauth_config():
    """Debug OAuth configuration"""
    return {
        "google_client_id": GOOGLE_CLIENT_ID[:20] + "..." if GOOGLE_CLIENT_ID else "NOT SET",
        "google_client_secret": "SET" if GOOGLE_CLIENT_SECRET else "NOT SET",
        "redirect_uri": REDIRECT_URI,
        "database_path": DB_NAME,
        "database_exists": os.path.exists(DB_NAME),
        "scopes": SCOPES
    }@app.post("/oauth/disconnect/{email}")
async def oauth_disconnect(email: str):
    """Disconnect a mailbox"""
    success = disconnect_mailbox(email)
    return {"success": success, "email": email}

# API Endpoints
@app.post("/upload")
async def upload_document(sender: str = Form(None), file: UploadFile = File(...)):
    document_id = str(uuid.uuid4())
    original_filename = file.filename
    file_extension = os.path.splitext(original_filename)[1]
    storage_filename = f"{document_id}{file_extension}"
    file_path = os.path.join(STORAGE_PATH, storage_filename)
    
    try:
        file_content = await file.read()
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        file_size = len(file_content)
        priority_score, priority_reason = decide_priority(file_size, sender)
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')
        
        message = {
            'document_id': document_id, 'filename': original_filename, 'storage_path': file_path,
            'content_type': file.content_type, 'file_content': encoded_file_content,
            'priority_score': priority_score, 'priority_reason': priority_reason,
            'source': 'api_upload', 'sender': sender
        }
        
        publish_message(message)
        publish_status_update(document_id, "Ingested", {
            "filename": original_filename, "source": "API Upload", "storage_path": file_path,
            "file_content_encoded": encoded_file_content, "content_type": file.content_type,
            "sender": sender, "priority_score": priority_score, "priority_reason": priority_reason
        })
        
        return {"document_id": document_id, "filename": original_filename, "status": "published"}
    except Exception as e:
        publish_status_update(document_id, "Ingestion Failed", {"filename": original_filename, "error": str(e)})
        return {"error": str(e), "status": "failed_to_publish"}

@app.get("/debug/mailboxes")
async def debug_mailboxes():
    try:
        mailboxes = get_oauth_mailboxes_from_db()
        return {"status": "success", "mailboxes": mailboxes, "db_path": DB_NAME, "db_exists": os.path.exists(DB_NAME)}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/debug/test-email/{email}")
async def debug_test_email(email: str):
    try:
        service = get_gmail_service(email)
        if not service:
            return {"status": "error", "error": "Could not get Gmail service"}
        
        profile = service.users().getProfile(userId='me').execute()
        search_date = (date.today() - timedelta(days=7)).strftime("%Y/%m/%d")
        results = service.users().messages().list(userId='me', q=f'after:{search_date} has:attachment', maxResults=5).execute()
        messages = results.get('messages', [])
        
        return {
            "status": "success",
            "profile": {"email": profile.get('emailAddress'), "total_messages": profile.get('messagesTotal')},
            "messages_found": len(messages), "message_ids": [msg['id'] for msg in messages]
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/health")
async def health_check():
    mailboxes = get_oauth_mailboxes_from_db()
    return {
        "status": "healthy", 
        "service": "OAuth-based Ingestor Agent with Priority Router",
        "connected_mailboxes": len(mailboxes),
        "mailbox_emails": [m['email'] for m in mailboxes],
        "components": {
            "oauth_email_monitor": "running", 
            "file_monitor": "running", 
            "api_upload": "available", 
            "priority_queues": list(PRIORITY_QUEUES.values())
        }
    }

@app.get("/oauth-status")
async def oauth_status():
    """Get OAuth connection status for frontend"""
    mailboxes = get_oauth_mailboxes_from_db()
    return {
        "connected_count": len(mailboxes),
        "mailboxes": mailboxes,
        "oauth_manager_url": "http://localhost:8001"
    }

# Startup
@app.on_event("startup")
async def startup_event():
    print("[Ingestor] 🚀 Starting OAuth-based Ingestor Agent...")
    
    # Setup database
    setup_oauth_database()
    
    # Setup RabbitMQ queues
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        for queue_name in PRIORITY_QUEUES.values():
            channel.queue_declare(queue=queue_name, durable=True)
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        connection.close()
        print("[Ingestor] ✅ RabbitMQ queues initialized")
    except Exception as e:
        print(f"[Ingestor] ❌ RabbitMQ setup failed: {e}")
    
    # Start monitoring threads
    threading.Thread(target=email_monitor_loop, daemon=True).start()
    threading.Thread(target=start_file_monitor, daemon=True).start()
    
    print("[Ingestor] ✅ All components started successfully")
    print("[Ingestor] 🌐 OAuth Manager available at: http://localhost:8001")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)