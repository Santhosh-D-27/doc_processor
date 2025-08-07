# ingestor/main.py - OAuth-based Ingestor Agent with Priority Queue Router

import uuid, time, pika, json, base64, os, shutil, uvicorn, sqlite3, threading, secrets
import google.generativeai as genai, requests
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

load_dotenv()

# Configuration
class Priority(IntEnum):
    CRITICAL = 100
    HIGH = 80
    MEDIUM = 50
    LOW = 20
    BULK = 10

PRIORITY_QUEUES = {Priority.CRITICAL: 'doc_received_critical', Priority.HIGH: 'doc_received_high', 
                   Priority.MEDIUM: 'doc_received_medium', Priority.LOW: 'doc_received_low', Priority.BULK: 'doc_received_bulk'}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Environment Variables
DB_NAME, RABBITMQ_HOST, STATUS_QUEUE_NAME = 'web_ui/state.db', os.getenv('RABBITMQ_HOST', '127.0.0.1'), 'document_status_queue'
STORAGE_PATH, MONITORED_PATH = 'document_storage', './monitored_folder'
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/userinfo.email']
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REDIRECT_URI = os.getenv('GOOGLE_CLIENT_ID'), os.getenv('GOOGLE_CLIENT_SECRET'), os.getenv('OAUTH_REDIRECT_URI')

# Initialize Google AI
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
except Exception:
    model = None

# Utility Functions
def create_html_response(title, content, is_success=False):
    """Create standardized HTML responses"""
    color = "green" if is_success else "red"
    icon = "✅" if is_success else "❌"
    return HTMLResponse(f"""
    <html><head><title>{title}</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-gray-100 flex items-center justify-center min-h-screen">
        <div class="bg-white p-8 rounded-lg shadow-md text-center max-w-md">
            <h1 class="text-2xl font-bold mb-4" style="color: {color};">{icon} {title}</h1>
            {content}
            <div class="mt-6">
                <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded mr-2">Dashboard</a>
                <button onclick="window.close();" class="bg-gray-600 hover:bg-gray-700 text-white px-6 py-2 rounded">Close</button>
            </div>
        </div>
    </body></html>
    """)

def setup_oauth_database():
    """Setup OAuth database with all required tables"""
    os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
    with sqlite3.connect(DB_NAME) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                email TEXT PRIMARY KEY, access_token TEXT NOT NULL, refresh_token TEXT,
                expires_at TEXT, created_at TEXT NOT NULL, status TEXT DEFAULT 'active');
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY, email TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mailboxes (
                email TEXT PRIMARY KEY, status TEXT DEFAULT 'connected', connected_at TEXT NOT NULL);
        ''')

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

def summarize_with_llm(body: str) -> str:
    if not model or not body.strip():
        return "Could not summarize: Gemini unavailable or empty body."
    try:
        return model.generate_content(f"Summarize the following email body in one sentence:\n\n---\n{body}\n---").text.strip()
    except Exception as e:
        return f"Could not summarize: {e}"

def decide_priority(file_size: int, sender: str = None, subject: str = None, is_email: bool = False) -> Tuple[int, str]:
    """Unified priority decision for files and emails"""
    if sender:
        sender_lower = sender.lower()
        if any(title in sender_lower for title in ["ceo", "director", "vp", "president"]):
            return Priority.CRITICAL, f"Executive sender: {sender}"
        elif any(title in sender_lower for title in ["manager", "lead", "supervisor"]):
            return Priority.HIGH, f"Management sender: {sender}"
    
    if subject and is_email:
        subject_lower = subject.lower()
        if any(keyword in subject_lower for keyword in ['urgent', 'asap', 'critical', 'emergency', 'immediate']):
            return Priority.HIGH, f"Urgent email: {subject[:30]}..."
    
    if file_size > 5_000_000:
        return Priority.HIGH, f"Large {'email' if is_email else 'file'}: {file_size} {'chars' if is_email else 'bytes'}"
    elif file_size > 1_000_000:
        return Priority.MEDIUM, f"Medium {'email' if is_email else 'file'}: {file_size} {'chars' if is_email else 'bytes'}"
    else:
        return Priority.LOW, f"Standard priority: {file_size} {'chars' if is_email else 'bytes'}"

def get_oauth_mailboxes_from_db():
    setup_oauth_database()
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT m.email, m.connected_at, t.expires_at FROM mailboxes m JOIN oauth_tokens t ON m.email = t.email WHERE m.status = 'connected' AND t.status = 'active'")
            mailboxes = [dict(row) for row in cursor.fetchall()]
            print(f"[OAuth] Found {len(mailboxes)} connected mailboxes: {[m['email'] for m in mailboxes] if mailboxes else 'None'}")
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
        processed_ids = {row[0] for row in conn.execute("SELECT uid FROM processed_emails").fetchall()}
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
            cursor.execute('SELECT access_token FROM oauth_tokens WHERE email = ? AND status = "active"', (email,))
            result = cursor.fetchone()
            
            if result:
                try:
                    response = requests.post(f'https://oauth2.googleapis.com/revoke?token={result[0]}')
                    print(f"[OAuth] Token revocation status for {email}: {response.status_code}")
                except Exception as e:
                    print(f"[OAuth] Token revocation error for {email}: {e}")
            
            cursor.execute('UPDATE oauth_tokens SET status = "revoked" WHERE email = ?', (email,))
            cursor.execute('UPDATE mailboxes SET status = "disconnected" WHERE email = ?', (email,))
            conn.commit()
            print(f"[OAuth] ✅ Disconnected mailbox: {email}")
            return True
    except Exception as e:
        print(f"[OAuth] ❌ Error disconnecting mailbox {email}: {e}")
        return False

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
            credentials = Credentials(token=access_token, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
                                    client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET, scopes=SCOPES)
            
            if expires_at:
                try:
                    expiry_dt = datetime.fromisoformat(expires_at)
                    if expiry_dt.tzinfo is not None:
                        expiry_dt = expiry_dt.astimezone(UTC).replace(tzinfo=None)
                    credentials.expiry = expiry_dt
                except Exception:
                    credentials.expiry = None
            
            service = build('gmail', 'v1', credentials=credentials)
            
            # Update token if refreshed
            if credentials.token != access_token:
                new_expiry = credentials.expiry.replace(tzinfo=UTC).isoformat() if credentials.expiry else None
                cursor.execute('UPDATE oauth_tokens SET access_token = ?, expires_at = ? WHERE email = ?', (credentials.token, new_expiry, email))
                conn.commit()
            
            return service
    except Exception as e:
        print(f"[OAuth] Error getting Gmail service for {email}: {e}")
        return None

def extract_email_body(payload) -> str:
    """Extract text from email payload recursively"""
    def extract_text(part):
        if 'parts' in part:
            for subpart in part['parts']:
                text = extract_text(subpart)
                if text: return text
        elif part['mimeType'] in ['text/plain', 'text/html'] and 'data' in part['body']:
            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
        return ""
    
    if 'parts' in payload:
        for part in payload['parts']:
            text = extract_text(part)
            if text: return text
    elif payload['body'].get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return ""

def download_attachment(service, message_id: str, attachment_id: str) -> Optional[bytes]:
    try:
        attachment = service.users().messages().attachments().get(userId='me', messageId=message_id, id=attachment_id).execute()
        return base64.urlsafe_b64decode(attachment['data'])
    except Exception as e:
        print(f"[OAuth] ❌ Error downloading attachment {attachment_id}: {e}")
        return None

def create_and_publish_document(document_id, filename, storage_path, content_type, file_content, 
                                priority_score, priority_reason, source, sender, **kwargs):
    """Unified document creation and publishing"""
    encoded_content = base64.b64encode(file_content if isinstance(file_content, bytes) else file_content.encode('utf-8')).decode('utf-8')
    
    message_data = {
        'document_id': document_id, 'filename': filename, 'storage_path': storage_path,
        'content_type': content_type, 'file_content': encoded_content,
        'priority_score': priority_score, 'priority_reason': priority_reason,
        'source': source, 'sender': sender, **kwargs
    }
    
    publish_message(message_data)
    publish_status_update(document_id, "Ingested", {
        "filename": filename, "source": source.replace('_', ' ').title(),
        "storage_path": storage_path, "file_content_encoded": encoded_content,
        "content_type": content_type, "sender": sender,
        "priority_score": priority_score, "priority_reason": priority_reason, **kwargs
    })

def process_attachment(service, message_id, part, sender, subject, summary):
    try:
        filename = part.get('filename', '')
        attachment_id = part['body'].get('attachmentId')
        if not filename or not attachment_id: return False
        
        document_id = str(uuid.uuid4())
        file_content = download_attachment(service, message_id, attachment_id)
        if not file_content: return False
        
        file_size = len(file_content)
        priority_score, priority_reason = decide_priority(file_size, sender, subject)
        
        file_extension = os.path.splitext(filename)[1]
        storage_filename = f"{document_id}{file_extension}"
        storage_file_path = os.path.join(STORAGE_PATH, storage_filename)
        
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(storage_file_path, "wb") as f:
            f.write(file_content)
        
        create_and_publish_document(document_id, filename, storage_file_path, part.get('mimeType', 'application/octet-stream'),
                                  file_content, priority_score, priority_reason, 'email_attachment', sender,
                                  context=summary, email_subject=subject, document_source_type='email_with_attachment',
                                  email_context=summary[:200] + "..." if len(summary) > 200 else summary)
        
        print(f"[OAuth] ✅ Processed attachment: {filename} (ID: {document_id})")
        return True
    except Exception as e:
        print(f"[OAuth] ❌ Error processing attachment {part.get('filename', 'unknown')}: {e}")
        return False

def process_email_body_as_document(service, message_id, sender, subject, email_body):
    try:
        document_id = str(uuid.uuid4())
        email_content = f"Subject: {subject}\nFrom: {sender}\nDate: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n{email_body}"
        
        safe_subject = "".join(c for c in subject if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
        storage_filename = f"{document_id}_Email_{safe_subject}.txt"
        storage_file_path = os.path.join(STORAGE_PATH, storage_filename)
        
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(storage_file_path, "w", encoding='utf-8') as f:
            f.write(email_content)
        
        body_length = len(email_body)
        priority_score, priority_reason = decide_priority(body_length, sender, subject, is_email=True)
        
        create_and_publish_document(document_id, f"Email: {safe_subject}", storage_file_path, 'text/plain',
                                  email_content, priority_score, priority_reason, 'email_body', sender,
                                  email_subject=subject, email_body_length=body_length, 
                                  document_source_type='email_only', source_type='email_only', body_length=body_length)
        
        print(f"[OAuth] ✅ Email body processed: {subject[:50]}... (ID: {document_id})")
        return True
    except Exception as e:
        print(f"[OAuth] ❌ Error processing email body: {e}")
        return False

def process_oauth_mailbox(email_address):
    print(f"[OAuth] 📧 Checking mailbox: {email_address}")
    service = get_gmail_service(email_address)
    if not service: return
    
    state_db_path, processed_ids = setup_and_load_state_db(email_address)
    
    try:
        search_date = (datetime.now(UTC).date() - timedelta(days=7)).strftime("%Y/%m/%d")
        results = service.users().messages().list(userId='me', q=f'after:{search_date}', maxResults=100).execute()
        messages = results.get('messages', [])
        
        processed_attachments_count = processed_bodies_count = 0
        
        for message_info in messages:
            message_id = message_info['id']
            if message_id in processed_ids: continue

            try:
                msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
                payload = msg['payload']
                headers = {h['name']: h['value'] for h in payload.get('headers', [])}
                sender, subject = headers.get('From', 'Unknown'), headers.get('Subject', 'No Subject')
                
                # Process attachments
                email_body_for_summary = extract_email_body(payload)
                summary = summarize_with_llm(email_body_for_summary[:1000]) if email_body_for_summary else "No email body content found"
                
                def find_and_process_attachments(part):
                    nonlocal processed_attachments_count
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        if process_attachment(service, message_id, part, sender, subject, summary):
                            processed_attachments_count += 1
                    if 'parts' in part:
                        for subpart in part['parts']:
                            find_and_process_attachments(subpart)

                find_and_process_attachments(payload)
                
                # Process email body
                if email_body_for_summary and len(email_body_for_summary.strip()) > 50:
                    if process_email_body_as_document(service, message_id, sender, subject, email_body_for_summary):
                        processed_bodies_count += 1
                
                save_processed_id(state_db_path, message_id)
            except Exception as e:
                print(f"[OAuth] ❌ Error processing email {message_id}: {e}")
                continue
        
        total_ingested = processed_attachments_count + processed_bodies_count
        if total_ingested > 0:
            print(f"[OAuth] 📈 Processed {processed_attachments_count} attachments, {processed_bodies_count} email bodies for {email_address}")
        else:
            print(f"[OAuth] ℹ️ No new documents from {email_address}")
    except Exception as e:
        print(f"[OAuth] ❌ Critical error processing {email_address}: {e}")

def email_monitor_loop():
    print("[OAuth Monitor] 🚀 Starting OAuth email monitor...")
    while True:
        try:
            mailbox_configs = get_oauth_mailboxes_from_db()
            if mailbox_configs:
                for config in mailbox_configs:
                    try:
                        process_oauth_mailbox(config['email'])
                    except Exception as e:
                        print(f"[OAuth Monitor] ❌ Error processing {config['email']}: {e}")
            time.sleep(30)
        except Exception as e:
            print(f"[OAuth Monitor] ❌ Monitor loop error: {e}")
            time.sleep(10)

# File Monitoring
class DocumentHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or event.src_path.endswith('.tmp'): return
        
        document_id = str(uuid.uuid4())
        original_filename = os.path.basename(event.src_path)
        file_extension = os.path.splitext(original_filename)[1]
        storage_file_path = os.path.join(STORAGE_PATH, f"{document_id}{file_extension}")
        
        try:
            time.sleep(1)
            os.makedirs(STORAGE_PATH, exist_ok=True)
            shutil.copy(event.src_path, storage_file_path)
            
            with open(storage_file_path, 'rb') as file:
                file_content = file.read()
            
            priority_score, priority_reason = decide_priority(len(file_content), os.path.dirname(event.src_path))
            
            create_and_publish_document(document_id, original_filename, storage_file_path, 'application/octet-stream',
                                      file_content, priority_score, priority_reason, 'file_share', 'system_fileshare_monitor')
        except Exception as e:
            publish_status_update(document_id, "Ingestion Failed", {"filename": original_filename, "error": str(e)})

def start_file_monitor():
    os.makedirs(MONITORED_PATH, exist_ok=True)
    observer = Observer()
    observer.schedule(DocumentHandler(), MONITORED_PATH, recursive=True)
    observer.start()
    try:
        while True: time.sleep(1)
    except: observer.stop()
    observer.join()

# OAuth Endpoints
@app.post("/oauth/disconnect/{email:path}")
async def oauth_disconnect(email: str):
    return {"success": disconnect_mailbox(email), "email": email}

@app.get("/", response_class=HTMLResponse)
async def oauth_home():
    mailboxes = get_oauth_mailboxes_from_db()
    mailbox_rows = "".join([f"""
    <tr class="border-b">
        <td class="p-4">{m['email']}</td>
        <td class="p-4 text-green-600">Connected</td>
        <td class="p-4">{m['connected_at']}</td>
        <td class="p-4"><button onclick="disconnectMailbox('{m['email']}')" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded">Disconnect</button></td>
    </tr>""" for m in mailboxes]) or '<tr><td colspan="4" class="p-4 text-center text-gray-500">No connected mailboxes</td></tr>'
    
    return HTMLResponse(f"""
    <html><head><title>OAuth Gmail Manager</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-gray-100"><div class="container mx-auto p-8">
        <div class="bg-white rounded-lg shadow p-6">
            <h1 class="text-3xl font-bold mb-6">Gmail OAuth Manager</h1>
            <button onclick="window.location.href='/oauth/connect'" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded mb-6">🔗 Connect New Mailbox</button>
            <table class="w-full border"><thead class="bg-gray-50"><tr><th class="p-4 text-left">Email</th><th class="p-4 text-left">Status</th><th class="p-4 text-left">Connected At</th><th class="p-4 text-left">Actions</th></tr></thead><tbody>{mailbox_rows}</tbody></table>
        </div></div>
        <script>
            async function disconnectMailbox(email) {{
                if (confirm(`Disconnect ${{email}}?`)) {{
                    const response = await fetch(`/oauth/disconnect/${{encodeURIComponent(email)}}`, {{method: 'POST'}});
                    const result = await response.json();
                    result.success ? (alert('Disconnected!'), window.location.reload()) : alert('Error: ' + result.error);
                }}
            }}
        </script>
    </body></html>""")

@app.get("/oauth/connect")
async def oauth_connect():
    try:
        setup_oauth_database()
        if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REDIRECT_URI]):
            missing = [var for var, val in [("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID), ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET), ("OAUTH_REDIRECT_URI", REDIRECT_URI)] if not val]
            return create_html_response("Configuration Error", f"<p>Missing: {', '.join(missing)}</p>")
        
        state = secrets.token_urlsafe(32)
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute('INSERT OR REPLACE INTO oauth_states (state, email, created_at, expires_at) VALUES (?, ?, ?, ?)', 
                        (state, '', datetime.now(UTC).isoformat(), (datetime.now(UTC) + timedelta(minutes=10)).isoformat()))
        
        auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urlencode({
            'client_id': GOOGLE_CLIENT_ID, 'redirect_uri': REDIRECT_URI, 'scope': ' '.join(SCOPES),
            'response_type': 'code', 'access_type': 'offline', 'prompt': 'consent', 'state': state
        })
        
        return RedirectResponse(url=auth_url)
    except Exception as e:
        return create_html_response("Connection Error", f"<p>Could not start OAuth: {str(e)}</p>")

@app.get("/oauth/gmail/callback")
async def oauth_callback(request: Request):
    try:
        code, state, error = request.query_params.get('code'), request.query_params.get('state'), request.query_params.get('error')
        
        if error: return create_html_response("OAuth Error", f"<p>Error: {error}</p>")
        if not code or not state: return create_html_response("OAuth Error", "<p>Missing parameters from Google</p>")
        
        # Verify state
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM oauth_states WHERE state = ?', (state,))
            if not cursor.fetchone(): return create_html_response("OAuth Error", "<p>Invalid or expired state</p>")
            cursor.execute('DELETE FROM oauth_states WHERE state = ?', (state,))
        
        # Exchange code for tokens
        token_data = {'client_id': GOOGLE_CLIENT_ID, 'client_secret': GOOGLE_CLIENT_SECRET, 'code': code, 
                     'grant_type': 'authorization_code', 'redirect_uri': REDIRECT_URI}
        
        response = requests.post('https://oauth2.googleapis.com/token', data=token_data, timeout=30)
        if response.status_code != 200: return create_html_response("Token Error", f"<p>Status: {response.status_code}</p>")
        
        tokens = response.json()
        if 'error' in tokens: return create_html_response("Token Error", f"<p>Error: {tokens.get('error')}</p>")
        
        # Get user email
        user_response = requests.get(f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={tokens['access_token']}", timeout=30)
        if user_response.status_code != 200: return create_html_response("User Info Error", "<p>Could not retrieve user info</p>")
        
        email = user_response.json().get('email')
        if not email: return create_html_response("Email Error", "<p>Could not retrieve email</p>")
        
        # Store tokens
        expires_at = (datetime.now(UTC) + timedelta(seconds=tokens['expires_in'])).isoformat() if 'expires_in' in tokens else None
        
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO oauth_tokens (email, access_token, refresh_token, expires_at, created_at, status) VALUES (?, ?, ?, ?, ?, ?)',
                          (email, tokens.get('access_token'), tokens.get('refresh_token'), expires_at, datetime.now(UTC).isoformat(), 'active'))
            cursor.execute('INSERT OR REPLACE INTO mailboxes (email, status, connected_at) VALUES (?, ?, ?)',
                          (email, 'connected', datetime.now(UTC).isoformat()))
        
        return create_html_response("Success", f"<p>Mailbox <strong>{email}</strong> connected successfully!</p>", True)
        
    except Exception as e:
        return create_html_response("Critical Error", f"<p>Error: {str(e)}</p>")

# API Endpoints
@app.post("/upload")
async def upload_document(sender: str = Form(None), file: UploadFile = File(...)):
    document_id = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]
    file_path = os.path.join(STORAGE_PATH, f"{document_id}{file_extension}")
    
    try:
        file_content = await file.read()
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        priority_score, priority_reason = decide_priority(len(file_content), sender)
        
        create_and_publish_document(document_id, file.filename, file_path, file.content_type,
                                  file_content, priority_score, priority_reason, 'api_upload', sender)
        
        return {"document_id": document_id, "filename": file.filename, "status": "published"}
    except Exception as e:
        publish_status_update(document_id, "Ingestion Failed", {"filename": file.filename, "error": str(e)})
        return {"error": str(e), "status": "failed_to_publish"}

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