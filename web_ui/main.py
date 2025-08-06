# web_ui/main.py
from dotenv import load_dotenv
load_dotenv()
import pika
import json
import sqlite3
import threading
import asyncio
import time
import os
import base64
import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, UTC

# --- Configuration ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
STATUS_QUEUE_NAME = 'document_status_queue'
DB_NAME = 'web_ui/state.db'
INGESTOR_URL = 'http://127.0.0.1:8001'  # Ingestor OAuth manager URL

# --- Pydantic Models for API Data Validation ---
class VIPContactCreate(BaseModel):
    email: str
    name: Optional[str] = None
    vip_level: str # HIGH, MEDIUM, LOW
    department: Optional[str] = None
    role: Optional[str] = None

class VIPDocumentUpdate(BaseModel):
    status: str
    risk_assessment: Optional[str] = None

# Manual Override Models
class ReExtractRequest(BaseModel):
    ocr_engine: Optional[str] = "default"  # default, tesseract, easyocr
    dpi: Optional[int] = 300
    language: Optional[str] = "eng"
    manual_text: Optional[str] = None
    preprocessing: Optional[dict] = None
    reason: Optional[str] = "Manual override"

class ReClassifyRequest(BaseModel):
    manual_type_hint: Optional[str] = None
    confidence_threshold: Optional[float] = 0.75
    force_classification: Optional[bool] = False
    reason: Optional[str] = "Manual override"

class ReRouteRequest(BaseModel):
    destination: str
    test_mode: Optional[bool] = False
    schedule_delivery: Optional[str] = None  # ISO datetime string
    reason: Optional[str] = "Manual override"

# --- Database Setup ---
def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Enhanced document_status table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_status (
            document_id TEXT PRIMARY KEY,
            filename TEXT,
            status TEXT,
            doc_type TEXT,
            confidence REAL,
            last_updated TEXT,
            is_vip BOOLEAN DEFAULT 0,
            vip_level TEXT DEFAULT 'NONE',
            summary TEXT,
            priority_content TEXT,
            routing_destination TEXT,
            override_in_progress BOOLEAN DEFAULT 0,
            override_type TEXT DEFAULT NULL
        )
    ''')
    
    # Check if routing_destination column exists, if not add it
    cursor.execute("PRAGMA table_info(document_status)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'routing_destination' not in columns:
        print("[DB] Adding routing_destination column to document_status table...")
        cursor.execute('ALTER TABLE document_status ADD COLUMN routing_destination TEXT')
        print("[DB] routing_destination column added successfully.")
    
    # Add override tracking columns if they don't exist
    if 'override_in_progress' not in columns:
        print("[DB] Adding override_in_progress column to document_status table...")
        cursor.execute('ALTER TABLE document_status ADD COLUMN override_in_progress BOOLEAN DEFAULT 0')
        print("[DB] override_in_progress column added successfully.")
    
    if 'override_type' not in columns:
        print("[DB] Adding override_type column to document_status table...")
        cursor.execute('ALTER TABLE document_status ADD COLUMN override_type TEXT DEFAULT NULL')
        print("[DB] override_type column added successfully.")
    
    # Enhanced document_history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            status TEXT,
            timestamp TEXT,
            details TEXT,
            doc_type TEXT,
            confidence REAL,
            file_content_encoded TEXT,
            is_vip BOOLEAN DEFAULT 0,
            vip_level TEXT DEFAULT 'NONE',
            summary TEXT,
            priority_content TEXT,
            FOREIGN KEY (document_id) REFERENCES document_status (document_id)
        )
    ''')
    
    # Manual Override Audit Trail Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS override_audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            override_type TEXT NOT NULL,  -- re-extract, re-classify, re-route
            user_id TEXT DEFAULT 'operator',
            timestamp TEXT NOT NULL,
            reason TEXT,
            parameters TEXT,  -- JSON string of override parameters
            original_state TEXT,  -- JSON string of original document state
            new_state TEXT,  -- JSON string of new document state
            success BOOLEAN DEFAULT 1,
            error_message TEXT,
            FOREIGN KEY (document_id) REFERENCES document_status (document_id)
        )
    ''')
    
    # Override Options Table for storing available options
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS override_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_type TEXT NOT NULL,  -- ocr_engine, doc_type, routing_destination
            option_value TEXT NOT NULL,
            display_name TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    ''')
    
    # OAuth tables (keep these for OAuth functionality)
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
            email TEXT NOT NULL,
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
    
    # VIP Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            vip_level TEXT NOT NULL,
            sender TEXT,
            summary TEXT,
            priority_content TEXT,
            status TEXT DEFAULT 'Pending Review',
            risk_assessment TEXT,
            last_updated TEXT,
            FOREIGN KEY (document_id) REFERENCES document_status (document_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            vip_level TEXT NOT NULL,
            department TEXT,
            role TEXT,
            added_at TEXT
        )
    ''')

    # Insert default override options
    cursor.execute('''
        INSERT OR IGNORE INTO override_options (option_type, option_value, display_name, priority, created_at)
        VALUES 
        ('ocr_engine', 'default', 'Default OCR Engine', 1, ?),
        ('ocr_engine', 'tesseract', 'Tesseract OCR', 2, ?),
        ('ocr_engine', 'easyocr', 'EasyOCR Engine', 3, ?),
        ('doc_type', 'INVOICE', 'Invoice', 1, ?),
        ('doc_type', 'RESUME', 'Resume', 2, ?),
        ('doc_type', 'CONTRACT', 'Contract', 3, ?),
        ('doc_type', 'REPORT', 'Report', 4, ?),
        ('doc_type', 'MEMO', 'Memo', 5, ?),
        ('doc_type', 'AGREEMENT', 'Agreement', 6, ?),
        ('doc_type', 'GRIEVANCE', 'Grievance', 7, ?),
        ('doc_type', 'ID_PROOF', 'ID Proof', 8, ?),
        ('routing_destination', 'erp_system', 'ERP System', 1, ?),
        ('routing_destination', 'dms_system', 'Document Management System', 2, ?),
        ('routing_destination', 'crm_system', 'CRM System', 3, ?)
    ''', [datetime.now(UTC).isoformat()] * 14)

    conn.commit()
    conn.close()
    print("[DB] Database tables checked/created with override support.")

def run_database_migrations():
    """Run database migrations to ensure all required columns exist"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        # Check if document_status table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_status'")
        if cursor.fetchone():
            # Check if routing_destination column exists
            cursor.execute("PRAGMA table_info(document_status)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'routing_destination' not in columns:
                print("[DB Migration] Adding routing_destination column to document_status table...")
                cursor.execute('ALTER TABLE document_status ADD COLUMN routing_destination TEXT')
                print("[DB Migration] routing_destination column added successfully.")
            
            if 'override_in_progress' not in columns:
                print("[DB Migration] Adding override_in_progress column to document_status table...")
                cursor.execute('ALTER TABLE document_status ADD COLUMN override_in_progress BOOLEAN DEFAULT 0')
                print("[DB Migration] override_in_progress column added successfully.")
            
            if 'override_type' not in columns:
                print("[DB Migration] Adding override_type column to document_status table...")
                cursor.execute('ALTER TABLE document_status ADD COLUMN override_type TEXT DEFAULT NULL')
                print("[DB Migration] override_type column added successfully.")
        
        # Create override audit trail table if it doesn't exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='override_audit_trail'")
        if not cursor.fetchone():
            print("[DB Migration] Creating override_audit_trail table...")
            cursor.execute('''
                CREATE TABLE override_audit_trail (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    override_type TEXT NOT NULL,
                    user_id TEXT DEFAULT 'operator',
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    parameters TEXT,
                    original_state TEXT,
                    new_state TEXT,
                    success BOOLEAN DEFAULT 1,
                    error_message TEXT,
                    FOREIGN KEY (document_id) REFERENCES document_status (document_id)
                )
            ''')
            print("[DB Migration] override_audit_trail table created successfully.")
        
        # Create override options table if it doesn't exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='override_options'")
        if not cursor.fetchone():
            print("[DB Migration] Creating override_options table...")
            cursor.execute('''
                CREATE TABLE override_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    option_type TEXT NOT NULL,
                    option_value TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    priority INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # Insert default override options
            cursor.execute('''
                INSERT INTO override_options (option_type, option_value, display_name, priority, created_at)
                VALUES 
                ('ocr_engine', 'default', 'Default OCR Engine', 1, ?),
                ('ocr_engine', 'tesseract', 'Tesseract OCR', 2, ?),
                ('ocr_engine', 'easyocr', 'EasyOCR Engine', 3, ?),
                ('doc_type', 'INVOICE', 'Invoice', 1, ?),
                ('doc_type', 'RESUME', 'Resume', 2, ?),
                ('doc_type', 'CONTRACT', 'Contract', 3, ?),
                ('doc_type', 'REPORT', 'Report', 4, ?),
                ('doc_type', 'MEMO', 'Memo', 5, ?),
                ('doc_type', 'AGREEMENT', 'Agreement', 6, ?),
                ('doc_type', 'GRIEVANCE', 'Grievance', 7, ?),
                ('doc_type', 'ID_PROOF', 'ID Proof', 8, ?),
                ('routing_destination', 'erp_system', 'ERP System', 1, ?),
                ('routing_destination', 'dms_system', 'Document Management System', 2, ?),
                ('routing_destination', 'crm_system', 'CRM System', 3, ?)
            ''', [datetime.now(UTC).isoformat()] * 14)
            print("[DB Migration] override_options table created with default options.")
        
        conn.commit()
    except Exception as e:
        print(f"[DB Migration] Error during migration: {e}")
    finally:
        conn.close()

# --- Helper Functions for Override Management ---
def log_override_audit(document_id: str, override_type: str, parameters: dict, 
                      original_state: dict, new_state: dict = None, 
                      success: bool = True, error_message: str = None, user_id: str = "operator"):
    """Log override actions to audit trail"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO override_audit_trail 
            (document_id, override_type, user_id, timestamp, reason, parameters, 
             original_state, new_state, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            document_id, override_type, user_id, datetime.now(UTC).isoformat(),
            parameters.get('reason', 'Manual override'),
            json.dumps(parameters),
            json.dumps(original_state),
            json.dumps(new_state) if new_state else None,
            success,
            error_message
        ))
        
        conn.commit()
        conn.close()
        print(f"[Audit] Logged {override_type} override for {document_id}")
    except Exception as e:
        print(f"[Audit Error] Failed to log override: {e}")

def set_override_status(document_id: str, override_type: str, in_progress: bool = True):
    """Set override status for a document"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE document_status 
            SET override_in_progress = ?, override_type = ?
            WHERE document_id = ?
        ''', (in_progress, override_type if in_progress else None, document_id))
        
        conn.commit()
        conn.close()
        print(f"[Override] Set {override_type} status to {in_progress} for {document_id}")
    except Exception as e:
        print(f"[Override Error] Failed to set override status: {e}")

def get_override_options(option_type: str = None):
    """Get available override options"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if option_type:
            cursor.execute('''
                SELECT option_type, option_value, display_name, priority 
                FROM override_options 
                WHERE option_type = ? AND is_active = 1 
                ORDER BY priority ASC
            ''', (option_type,))
        else:
            cursor.execute('''
                SELECT option_type, option_value, display_name, priority 
                FROM override_options 
                WHERE is_active = 1 
                ORDER BY option_type, priority ASC
            ''')
        
        options = cursor.fetchall()
        conn.close()
        
        if option_type:
            return [{"value": row['option_value'], "label": row['display_name']} for row in options]
        else:
            # Group by option_type
            grouped = {}
            for row in options:
                if row['option_type'] not in grouped:
                    grouped[row['option_type']] = []
                grouped[row['option_type']].append({
                    "value": row['option_value'], 
                    "label": row['display_name']
                })
            return grouped
    except Exception as e:
        print(f"[Override Error] Failed to get override options: {e}")
        return {}

def get_override_audit_trail(document_id: str, limit: int = 10):
    """Get audit trail for a document"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM override_audit_trail 
            WHERE document_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (document_id, limit))
        
        audit_entries = cursor.fetchall()
        conn.close()
        
        # Parse JSON fields
        parsed_entries = []
        for entry in audit_entries:
            entry_dict = dict(entry)
            if entry_dict.get('parameters'):
                try:
                    entry_dict['parameters'] = json.loads(entry_dict['parameters'])
                except:
                    entry_dict['parameters'] = {}
            if entry_dict.get('original_state'):
                try:
                    entry_dict['original_state'] = json.loads(entry_dict['original_state'])
                except:
                    entry_dict['original_state'] = {}
            if entry_dict.get('new_state'):
                try:
                    entry_dict['new_state'] = json.loads(entry_dict['new_state'])
                except:
                    entry_dict['new_state'] = {}
            parsed_entries.append(entry_dict)
        
        return parsed_entries
    except Exception as e:
        print(f"[Audit Error] Failed to get audit trail: {e}")
        return []

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.message_queue = []
        self.broadcast_task = None
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"[WebSocket] Client disconnected. Total connections: {len(self.active_connections)}")
    
    def queue_broadcast(self, message: str):
        """Queue a message for broadcast (thread-safe)"""
        self.message_queue.append(message)
        print(f"[WebSocket] Queued message for broadcast. Queue size: {len(self.message_queue)}")
    
    async def broadcast(self, message: str):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            print("[WebSocket] No active connections to broadcast to")
            return
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"[WebSocket] Error sending to client: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.active_connections.remove(connection)
        
        print(f"[WebSocket] Broadcasted to {len(self.active_connections)} clients")
    
    async def process_queue(self):
        """Process queued messages (runs in main event loop)"""
        while True:
            if self.message_queue:
                message = self.message_queue.pop(0)
                await self.broadcast(message)
            await asyncio.sleep(0.1)  # Small delay to prevent busy waiting

manager = ConnectionManager()

# --- RabbitMQ Status Consumer ---
def consume_status_updates():
    print("[Consumer] Starting status consumer thread...")
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
            print("[Consumer] Waiting for status messages.")

            def callback(ch, method, properties, body):
                try:
                    message = json.loads(body)
                    
                    # Add timestamp to message if it's missing to ensure history is always time-stamped
                    if 'timestamp' not in message or not message['timestamp']:
                        message['timestamp'] = datetime.now(UTC).isoformat()

                    doc_id = message.get("document_id")

                    if not doc_id:
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    conn = sqlite3.connect(DB_NAME)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # 1. Fetch the current state of the document
                    cursor.execute("SELECT * FROM document_status WHERE document_id = ?", (doc_id,))
                    current_doc_data = cursor.fetchone()
                    doc_data = dict(current_doc_data) if current_doc_data else {}
                    
                    # 2. Smartly update the dictionary with new, non-null values from the message
                    for key, value in message.items():
                        if value is not None:
                            if key == "details" and isinstance(value, dict):
                                doc_data[key] = {**(doc_data.get(key) or {}), **value}
                            else:
                                doc_data[key] = value

                    doc_data.setdefault('document_id', doc_id)
                    doc_data.setdefault('filename', 'Unknown File')
                    doc_data['last_updated'] = message.get("timestamp", datetime.now(UTC).isoformat())

                    # 3. Write the merged data back to the main status table
                    cursor.execute("""
                        INSERT OR REPLACE INTO document_status 
                        (document_id, filename, status, doc_type, confidence, last_updated, is_vip, vip_level, summary, priority_content, routing_destination, override_in_progress, override_type)
                        VALUES (:document_id, :filename, :status, :doc_type, :confidence, :last_updated, :is_vip, :vip_level, :summary, :priority_content, :routing_destination, :override_in_progress, :override_type)
                    """, {
                        "document_id": doc_data.get('document_id'),
                        "filename": doc_data.get('filename'),
                        "status": doc_data.get('status'),
                        "doc_type": doc_data.get('doc_type'),
                        "confidence": doc_data.get('confidence'),
                        "last_updated": doc_data.get('last_updated'),
                        "is_vip": doc_data.get('is_vip', False),
                        "vip_level": doc_data.get('vip_level', "NONE"),
                        "summary": doc_data.get('summary'),
                        "priority_content": json.dumps(doc_data.get('priority_content')) if doc_data.get('priority_content') else None,
                        "routing_destination": message.get('routing_destination') or doc_data.get('routing_destination'),
                        "override_in_progress": False,  # Clear override flag when processing is complete
                        "override_type": None  # Clear override type when processing is complete
                    })

                    # 4. **[THE FIX]** Insert the COMPLETE record into the history table
                    cursor.execute("""
                        INSERT INTO document_history
                        (document_id, status, timestamp, details, doc_type, confidence, summary, is_vip, vip_level, priority_content, file_content_encoded)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        message.get('status'),
                        message.get('timestamp'),
                        json.dumps(message.get('details', {})),
                        message.get('doc_type'),
                        message.get('confidence'),
                        message.get('summary'),
                        message.get('is_vip', False),
                        message.get('vip_level', "NONE"),
                        json.dumps(message.get('priority_content')) if message.get('priority_content') else None,
                        message.get('details', {}).get('file_content_encoded') # This line is critical
                    ))

                    conn.commit()
                    
                    # Broadcast the fully updated document state
                    cursor.execute("SELECT * FROM document_status WHERE document_id = ?", (doc_id,))
                    updated_doc_for_broadcast = dict(cursor.fetchone())
                    
                    conn.close()
                    
                    # Queue the message for WebSocket broadcast (thread-safe)
                    manager.queue_broadcast(json.dumps(updated_doc_for_broadcast))
                    
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except Exception as e:
                    print(f"[Consumer DB Error] Failed to process message: {e}")
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=STATUS_QUEUE_NAME, on_message_callback=callback)
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[Consumer Error] Could not connect to RabbitMQ: {e}. Retrying in 10s.")
            time.sleep(10)
        except Exception as e:
            print(f"[Consumer Error] An unexpected error occurred: {e}. Retrying in 10s.")
            time.sleep(10)

# --- FastAPI Application ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_database()
    run_database_migrations()  # Run migrations to ensure all columns exist
    
    # Start the RabbitMQ consumer thread
    consumer_thread = threading.Thread(target=consume_status_updates, daemon=True)
    consumer_thread.start()
    
    # Start the WebSocket message queue processor
    manager.broadcast_task = asyncio.create_task(manager.process_queue())
    
    yield
    
    # Cleanup
    if manager.broadcast_task:
        manager.broadcast_task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---
@app.get("/documents")
def get_all_documents():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM document_status ORDER BY last_updated DESC LIMIT 100")
    docs = cursor.fetchall()
    conn.close()
    return [dict(doc) for doc in docs]

@app.get("/history/{document_id}")
def get_document_history(document_id: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM document_history WHERE document_id = ? ORDER BY timestamp ASC", (document_id,))
    history = cursor.fetchall()
    conn.close()
    
    # Return empty array instead of raising exception when no history found
    if not history:
        return []
    
    # Parse JSON strings back to dicts for details and priority_content
    parsed_history = []
    for row in history:
        row_dict = dict(row)
        if row_dict.get('details'):
            try:
                row_dict['details'] = json.loads(row_dict['details'])
            except json.JSONDecodeError:
                row_dict['details'] = {}
        if row_dict.get('priority_content'):
            try:
                row_dict['priority_content'] = json.loads(row_dict['priority_content'])
            except json.JSONDecodeError:
                row_dict['priority_content'] = {}
        parsed_history.append(row_dict)
    return parsed_history

def get_doc_for_reprocessing(document_id: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM document_status WHERE document_id = ?", (document_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(doc)

@app.post("/re-classify/{document_id}")
def re_classify_document(document_id: str, request: ReClassifyRequest = None):
    print(f"[API] Received request to re-classify document: {document_id}")
    
    if request is None:
        request = ReClassifyRequest()
    
    try:
        # Get current document state
        doc = get_doc_for_reprocessing(document_id)
        history_events = get_document_history(document_id)
        
        # Store original state for audit trail
        original_state = {
            'doc_type': doc.get('doc_type'),
            'confidence': doc.get('confidence'),
            'status': doc.get('status')
        }
        
        # Set override status
        set_override_status(document_id, 're-classify', True)
        
        # Find the most recent 'Extracted' event to get the extracted text
        extracted_event = None
        for event in reversed(history_events):
            if event['status'] == 'Extracted':
                extracted_event = event
                break
        
        if not extracted_event:
            error_msg = "No extraction record found for this document."
            log_override_audit(document_id, 're-classify', request.dict(), original_state, 
                             success=False, error_message=error_msg)
            set_override_status(document_id, 're-classify', False)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Get extracted text from the details
        extracted_details = extracted_event.get('details', {})
        extracted_text = extracted_details.get('extracted_text', '')
        
        if not extracted_text:
            error_msg = "No extracted text found for this document."
            log_override_audit(document_id, 're-classify', request.dict(), original_state, 
                             success=False, error_message=error_msg)
            set_override_status(document_id, 're-classify', False)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Get sender information from the original ingestion event
        sender = 'N/A'
        for event in history_events:
            if event['status'] == 'Ingested':
                ingested_details = event.get('details', {})
                sender = ingested_details.get('sender', 'N/A')
                break
        
        # Get priority content and summary from the extracted event
        priority_content = extracted_event.get('priority_content', {})
        summary = extracted_event.get('summary', '')
        
        # Get entities if available
        entities = extracted_details.get('entities', {})
        
        # Prepare the message for the classification queue with override parameters
        message = {
            'document_id': doc['document_id'],
            'filename': doc['filename'],
            'extracted_text': extracted_text,
            'sender': sender,
            'summary': summary,
            'priority_content': priority_content,
            'entities': entities,
            'priority_score': 100,  # High priority for manual overrides
            'priority_reason': 'Manual re-classification override',
            # Override-specific parameters
            'manual_type_hint': request.manual_type_hint,
            'confidence_threshold': request.confidence_threshold,
            'force_classification': request.force_classification,
            'override_parameters': request.dict()
        }
        
        print(f"[API] Sending enhanced re-classification message: {message['document_id']}")
        
        # Publish to classification queue with override event type
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue='classification_queue', durable=True)
        
        # Add override metadata to message
        override_metadata = {
            'event_type': 'doc.reclassify.requested',
            'override_timestamp': datetime.now(UTC).isoformat(),
            'user_id': 'operator',
            'reason': request.reason
        }
        message.update(override_metadata)
        
        channel.basic_publish(exchange='', routing_key='classification_queue', body=json.dumps(message))
        connection.close()
        
        # Log successful override request
        log_override_audit(document_id, 're-classify', request.dict(), original_state)
        
        print(f"[API] Successfully queued {document_id} for re-classification with override parameters.")
        return {
            "status": "success", 
            "detail": f"Document {document_id} sent for re-classification with override parameters.",
            "override_id": f"reclassify_{document_id}_{int(time.time())}"
        }
        
    except HTTPException as http_exc:
        set_override_status(document_id, 're-classify', False)
        raise http_exc
    except Exception as e:
        set_override_status(document_id, 're-classify', False)
        error_msg = f"Failed to re-classify {document_id}: {str(e)}"
        log_override_audit(document_id, 're-classify', request.dict(), original_state, 
                         success=False, error_message=error_msg)
        print(f"[API Error] {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/re-extract/{document_id}")
def re_extract_document(document_id: str, request: ReExtractRequest = None):
    print(f"[API] Received request to re-extract document: {document_id}")
    
    if request is None:
        request = ReExtractRequest()
    
    try:
        # Get current document state
        doc = get_doc_for_reprocessing(document_id)
        history_events = get_document_history(document_id)
        
        # Store original state for audit trail
        original_state = {
            'status': doc.get('status'),
            'doc_type': doc.get('doc_type'),
            'confidence': doc.get('confidence')
        }
        
        # Set override status
        set_override_status(document_id, 're-extract', True)
        
        # Get the document's full history
        history_events = get_document_history(document_id)
        
        # Find the original 'Ingested' event which contains the file content
        ingested_event = next((event for event in history_events if event['status'] == 'Ingested'), None)

        if not ingested_event:
            error_msg = "Original ingestion record not found."
            log_override_audit(document_id, 're-extract', request.dict(), original_state, 
                             success=False, error_message=error_msg)
            set_override_status(document_id, 're-extract', False)
            raise HTTPException(status_code=404, detail=error_msg)

        # Get the encoded file content directly from the database record
        file_content_b64 = ingested_event.get('file_content_encoded')
        if not file_content_b64:
            error_msg = "Encoded file content not found in ingestion history."
            log_override_audit(document_id, 're-extract', request.dict(), original_state, 
                             success=False, error_message=error_msg)
            set_override_status(document_id, 're-extract', False)
            raise HTTPException(status_code=404, detail=error_msg)

        # Get the original filename and sender from the 'details' JSON
        ingested_details = ingested_event.get('details', {})
        original_filename = ingested_details.get('filename')
        sender = ingested_details.get('sender')
        if not original_filename:
            error_msg = "Original filename not found in ingestion history."
            log_override_audit(document_id, 're-extract', request.dict(), original_state, 
                             success=False, error_message=error_msg)
            set_override_status(document_id, 're-extract', False)
            raise HTTPException(status_code=404, detail=error_msg)

        # Prepare the message for the extraction queue with override parameters
        message_to_extractor = {
            'document_id': document_id,
            'filename': original_filename,
            'file_content': file_content_b64, 
            'priority': 'critical',  # High priority for manual overrides
            'source': 'manual_re-extract_override',
            'content_type': ingested_details.get('content_type', 'application/octet-stream'),
            'sender': sender,
            # Override-specific parameters
            'ocr_engine': request.ocr_engine,
            'dpi': request.dpi,
            'language': request.language,
            'manual_text': request.manual_text,
            'preprocessing': request.preprocessing,
            'override_parameters': request.dict()
        }

        # Publish the message to RabbitMQ with override event type
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue='doc_received_medium', durable=True)
        
        # Add override metadata to message
        override_metadata = {
            'event_type': 'doc.reextract.requested',
            'override_timestamp': datetime.now(UTC).isoformat(),
            'user_id': 'operator',
            'reason': request.reason
        }
        message_to_extractor.update(override_metadata)
        
        channel.basic_publish(
            exchange='', 
            routing_key='doc_received_medium',
            body=json.dumps(message_to_extractor)
        )
        connection.close()
        
        # Log successful override request
        log_override_audit(document_id, 're-extract', request.dict(), original_state)
        
        print(f"[API] Successfully queued {document_id} for re-extraction with override parameters.")
        return {
            "status": "success", 
            "detail": f"Document {document_id} sent for re-extraction with override parameters.",
            "override_id": f"reextract_{document_id}_{int(time.time())}"
        }

    except HTTPException as http_exc:
        set_override_status(document_id, 're-extract', False)
        raise http_exc
    except Exception as e:
        set_override_status(document_id, 're-extract', False)
        error_msg = f"Failed to re-extract {document_id}: {str(e)}"
        log_override_audit(document_id, 're-extract', request.dict(), original_state, 
                         success=False, error_message=error_msg)
        print(f"[API Error] {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Manual Override API Endpoints ---
@app.post("/re-route/{document_id}")
def re_route_document(document_id: str, request: ReRouteRequest):
    print(f"[API] Received request to re-route document: {document_id}")
    
    try:
        # Get current document state
        doc = get_doc_for_reprocessing(document_id)
        
        # Store original state for audit trail
        original_state = {
            'routing_destination': doc.get('routing_destination'),
            'status': doc.get('status')
        }
        
        # Set override status
        set_override_status(document_id, 're-route', True)
        
        # Prepare routing message with override parameters
        routing_message = {
            'document_id': document_id,
            'filename': doc.get('filename'),
            'doc_type': doc.get('doc_type'),
            'confidence': doc.get('confidence'),
            'entities': {},  # Will be populated from history if available
            'summary': doc.get('summary', ''),
            'priority_content': doc.get('priority_content', {}),
            'is_vip': doc.get('is_vip', False),
            'vip_level': doc.get('vip_level', 'NONE'),
            'priority_score': 100,  # High priority for manual overrides
            'priority_reason': 'Manual re-routing override',
            'sender': 'N/A',
            # Override-specific parameters
            'destination': request.destination,
            'test_mode': request.test_mode,
            'schedule_delivery': request.schedule_delivery,
            'override_parameters': request.dict()
        }
        
        # Get entities from history if available
        history_events = get_document_history(document_id)
        for event in reversed(history_events):
            if event['status'] == 'Extracted':
                extracted_details = event.get('details', {})
                routing_message['entities'] = extracted_details.get('entities', {})
                break
        
        print(f"[API] Sending re-routing message: {routing_message['document_id']}")
        
        # Publish to routing queue with override event type
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue='routing_queue', durable=True)
        
        # Add override metadata to message
        override_metadata = {
            'event_type': 'doc.reroute.requested',
            'override_timestamp': datetime.now(UTC).isoformat(),
            'user_id': 'operator',
            'reason': request.reason
        }
        routing_message.update(override_metadata)
        
        channel.basic_publish(exchange='', routing_key='routing_queue', body=json.dumps(routing_message))
        connection.close()
        
        # Log successful override request
        log_override_audit(document_id, 're-route', request.dict(), original_state)
        
        print(f"[API] Successfully queued {document_id} for re-routing to {request.destination}.")
        return {
            "status": "success", 
            "detail": f"Document {document_id} sent for re-routing to {request.destination}.",
            "override_id": f"reroute_{document_id}_{int(time.time())}"
        }
        
    except HTTPException as http_exc:
        set_override_status(document_id, 're-route', False)
        raise http_exc
    except Exception as e:
        set_override_status(document_id, 're-route', False)
        error_msg = f"Failed to re-route {document_id}: {str(e)}"
        log_override_audit(document_id, 're-route', request.dict(), original_state, 
                         success=False, error_message=error_msg)
        print(f"[API Error] {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/override-options")
def get_override_options_endpoint(option_type: str = None):
    """Get available override options for the UI"""
    try:
        options = get_override_options(option_type)
        return {"status": "success", "options": options}
    except Exception as e:
        print(f"[API Error] Failed to get override options: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{document_id}/override-options")
def get_document_override_options(document_id: str):
    """Get override options specific to a document"""
    try:
        # Get document state
        doc = get_doc_for_reprocessing(document_id)
        
        # Get all override options
        all_options = get_override_options()
        
        # Get document-specific recommendations
        recommendations = {
            'ocr_engines': all_options.get('ocr_engine', []),
            'doc_types': all_options.get('doc_type', []),
            'routing_destinations': all_options.get('routing_destination', []),
            'current_state': {
                'doc_type': doc.get('doc_type'),
                'confidence': doc.get('confidence'),
                'routing_destination': doc.get('routing_destination'),
                'status': doc.get('status')
            }
        }
        
        return {"status": "success", "recommendations": recommendations}
    except Exception as e:
        print(f"[API Error] Failed to get document override options: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{document_id}/override-audit")
def get_document_override_audit(document_id: str, limit: int = 10):
    """Get audit trail for a document's override actions"""
    try:
        audit_trail = get_override_audit_trail(document_id, limit)
        return {"status": "success", "audit_trail": audit_trail}
    except Exception as e:
        print(f"[API Error] Failed to get override audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- OAuth Mailbox Status Endpoint (for monitoring) ---
@app.get("/oauth-mailboxes")
def get_oauth_mailboxes():
    """Get OAuth connected mailboxes status from ingestor service"""
    try:
        # First try to get from local database
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.email, m.status, m.connected_at, t.expires_at
            FROM mailboxes m
            JOIN oauth_tokens t ON m.email = t.email
            WHERE m.status = 'connected' AND t.status = 'active'
        """)
        mailboxes = cursor.fetchall()
        conn.close()
        
        # If no local data, try to get from ingestor service
        if not mailboxes:
            try:
                response = requests.get(f"{INGESTOR_URL}/oauth-status", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    return data.get('mailboxes', [])
            except Exception as e:
                print(f"[OAuth] Could not reach ingestor service: {e}")
        
        return [dict(row) for row in mailboxes]
    except Exception as e:
        print(f"[OAuth] Error fetching OAuth mailboxes: {e}")
        return []

@app.get("/oauth-status") 
def get_oauth_status():
    """Get comprehensive OAuth status"""
    try:
        # Get mailboxes
        mailboxes = get_oauth_mailboxes()
        
        # Try to get status from ingestor service
        ingestor_status = None
        try:
            response = requests.get(f"{INGESTOR_URL}/oauth-status", timeout=5)
            if response.status_code == 200:
                ingestor_status = response.json()
        except Exception as e:
            print(f"[OAuth] Could not reach ingestor service: {e}")
        
        return {
            "connected_count": len(mailboxes),
            "mailboxes": mailboxes,
            "oauth_manager_url": INGESTOR_URL,
            "ingestor_service_status": "connected" if ingestor_status else "disconnected",
            "ingestor_data": ingestor_status
        }
    except Exception as e:
        print(f"[OAuth] Error getting OAuth status: {e}")
        return {
            "connected_count": 0,
            "mailboxes": [],
            "oauth_manager_url": INGESTOR_URL,
            "ingestor_service_status": "error",
            "error": str(e)
        }

# --- VIP Management API Endpoints ---
@app.get("/vip-documents")
def get_vip_documents():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vip_documents ORDER BY last_updated DESC LIMIT 100")
    vip_docs = cursor.fetchall()
    conn.close()
    parsed_vip_docs = []
    for doc in vip_docs:
        doc_dict = dict(doc)
        if doc_dict.get('priority_content'):
            doc_dict['priority_content'] = json.loads(doc_dict['priority_content'])
        parsed_vip_docs.append(doc_dict)
    return parsed_vip_docs

@app.get("/vip-contacts")
def get_vip_contacts():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vip_contacts ORDER BY added_at DESC")
    contacts = cursor.fetchall()
    conn.close()
    return [dict(contact) for contact in contacts]

@app.post("/vip-contacts")
def add_vip_contact(contact: VIPContactCreate):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO vip_contacts (email, name, vip_level, department, role, added_at) VALUES (?, ?, ?, ?, ?, ?)",
            (contact.email, contact.name, contact.vip_level, contact.department, contact.role, datetime.now(UTC).isoformat())
        )
        conn.commit()
        conn.close()
        return {"status": "success", "email": contact.email}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="VIP contact with this email already exists.")

@app.delete("/vip-contacts/{contact_id}")
def delete_vip_contact(contact_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vip_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "id": contact_id}

@app.put("/vip-documents/{document_id}")
def update_vip_document_status(document_id: str, update: VIPDocumentUpdate):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE vip_documents SET status = ?, risk_assessment = ?, last_updated = ? WHERE document_id = ?",
        (update.status, update.risk_assessment, datetime.now(UTC).isoformat(), document_id)
    )
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="VIP document not found.")
    conn.close()
    return {"status": "success", "document_id": document_id, "new_status": update.status}

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- Test endpoint for WebSocket debugging ---
@app.post("/test-websocket")
async def test_websocket():
    """Test endpoint to manually trigger a WebSocket message"""
    test_message = {
        "document_id": "test-websocket",
        "filename": "test-file.pdf",
        "status": "Test Status",
        "last_updated": datetime.now(UTC).isoformat()
    }
    manager.queue_broadcast(json.dumps(test_message))
    return {"status": "success", "message": "Test message queued for broadcast"}

# --- Test endpoint for override system ---
@app.post("/test-override-system")
async def test_override_system():
    """Test endpoint to verify override system is working"""
    try:
        # Test override options
        options = get_override_options()
        
        # Test database tables
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Check if override tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='override_audit_trail'")
        audit_table_exists = cursor.fetchone() is not None
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='override_options'")
        options_table_exists = cursor.fetchone() is not None
        
        # Check if override columns exist in document_status
        cursor.execute("PRAGMA table_info(document_status)")
        columns = [column[1] for column in cursor.fetchall()]
        override_columns_exist = 'override_in_progress' in columns and 'override_type' in columns
        
        conn.close()
        
        return {
            "status": "success",
            "override_system": {
                "audit_table_exists": audit_table_exists,
                "options_table_exists": options_table_exists,
                "override_columns_exist": override_columns_exist,
                "available_options": options
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"Override system test failed: {str(e)}"}

# --- Database migration endpoint ---
@app.post("/migrate-database")
async def migrate_database():
    """Manually run database migrations"""
    try:
        run_database_migrations()
        return {"status": "success", "message": "Database migrations completed successfully"}
    except Exception as e:
        return {"status": "error", "message": f"Migration failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="[::]", port=8000)