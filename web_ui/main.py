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
            priority_content TEXT
        )
    ''')
    
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

    conn.commit()
    conn.close()
    print("[DB] Database tables checked/created.")

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

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
                message = json.loads(body)
                doc_id = message.get("document_id")
                status = message.get("status")
                timestamp = message.get("timestamp")
                
                doc_type = message.get("doc_type")
                confidence = message.get("confidence")
                is_vip = message.get("is_vip", False)
                vip_level = message.get("vip_level", "NONE")
                summary = message.get("summary")
                priority_content = message.get("priority_content")

                try:
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()

                    # Insert into history table
                    cursor.execute("""
                        INSERT INTO document_history 
                        (document_id, status, timestamp, details, doc_type, confidence, file_content_encoded, is_vip, vip_level, summary, priority_content)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id, status, timestamp,
                        json.dumps(message.get("details", {})),
                        doc_type, confidence,
                        message.get("details", {}).get("file_content_encoded"),
                        is_vip, vip_level, summary, json.dumps(priority_content)
                    ))
                    
                    # Get existing data for filename to prevent it from becoming NULL
                    cursor.execute("SELECT filename FROM document_status WHERE document_id = ?", (doc_id,))
                    existing_filename = cursor.fetchone()
                    filename_to_use = message.get("details", {}).get("filename", existing_filename[0] if existing_filename else "Unknown_File")

                    # Update (or insert) the main document_status table
                    cursor.execute("""
                        INSERT OR REPLACE INTO document_status 
                        (document_id, filename, status, doc_type, confidence, last_updated, is_vip, vip_level, summary, priority_content)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        filename_to_use,
                        status,
                        doc_type,
                        confidence,
                        timestamp,
                        is_vip,
                        vip_level,
                        summary,
                        json.dumps(priority_content)
                    ))

                    # If it's a VIP document and Routed, add/update vip_documents table
                    if is_vip and status == "Routed":
                        sender = message.get("details", {}).get("sender", "N/A")
                        cursor.execute("""
                            INSERT OR REPLACE INTO vip_documents
                            (document_id, filename, vip_level, sender, summary, priority_content, status, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            doc_id,
                            filename_to_use,
                            vip_level,
                            sender,
                            summary,
                            json.dumps(priority_content),
                            "Routed",
                            datetime.now(UTC).isoformat()
                        ))
                    
                    conn.commit()
                    
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM document_status WHERE document_id = ?", (doc_id,))
                    updated_doc = dict(cursor.fetchone())
                    
                    conn.close()
                    
                    asyncio.run(manager.broadcast(json.dumps(updated_doc)))
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                except Exception as e:
                    print(f"[Consumer DB Error] Failed to save status for {doc_id}: {e}")

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
    consumer_thread = threading.Thread(target=consume_status_updates, daemon=True)
    consumer_thread.start()
    yield

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
    if not history:
        raise HTTPException(status_code=404, detail="History not found")
    # Parse JSON strings back to dicts for details and priority_content
    parsed_history = []
    for row in history:
        row_dict = dict(row)
        if row_dict.get('details'):
            row_dict['details'] = json.loads(row_dict['details'])
        if row_dict.get('priority_content'):
            row_dict['priority_content'] = json.loads(row_dict['priority_content'])
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
def re_classify_document(document_id: str):
    doc = get_doc_for_reprocessing(document_id)
    history_events = get_document_history(document_id)
    
    extracted_details = {}
    extracted_summary = ""
    extracted_priority_content = {}
    extracted_entities = {}

    for event in reversed(history_events):
        if event['status'] == 'Extracted':
            extracted_details = event.get('details', {})
            extracted_summary = event.get('summary', '')
            extracted_priority_content = event.get('priority_content', {})
            extracted_entities = extracted_details.get('entities', {})
            break

    message = {
        'document_id': doc['document_id'],
        'filename': doc['filename'],
        'extracted_text': extracted_details.get('extracted_text', ''),
        'summary': extracted_summary,
        'priority_content': extracted_priority_content,
        'entities': extracted_entities
    }
    
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue='classification_queue', durable=True)
    channel.basic_publish(exchange='', routing_key='classification_queue', body=json.dumps(message))
    connection.close()
    return {"status": "success"}

@app.post("/re-extract/{document_id}")
def re_extract_document(document_id: str):
    print(f"[API] Received request to re-extract document: {document_id}")
    try:
        # Get the document's full history
        history_events = get_document_history(document_id)
        
        # Find the original 'Ingested' event which contains the file content
        ingested_event = next((event for event in history_events if event['status'] == 'Ingested'), None)

        if not ingested_event:
            raise HTTPException(status_code=404, detail="Original ingestion record not found.")

        # Get the encoded file content directly from the database record
        file_content_b64 = ingested_event.get('file_content_encoded')
        if not file_content_b64:
            raise HTTPException(status_code=404, detail="Encoded file content not found in ingestion history.")

        # Get the original filename and sender from the 'details' JSON
        ingested_details = ingested_event.get('details', {})
        original_filename = ingested_details.get('filename')
        sender = ingested_details.get('sender')
        if not original_filename:
             raise HTTPException(status_code=404, detail="Original filename not found in ingestion history.")

        # Prepare the message for the extraction queue
        message_to_extractor = {
            'document_id': document_id,
            'filename': original_filename,
            'file_content': file_content_b64, 
            'priority': 'high',
            'source': 'manual_re-extract',
            'content_type': ingested_details.get('content_type', 'application/octet-stream'),
            'sender': sender
        }

        # Publish the message to RabbitMQ
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue='doc_received_medium', durable=True)
        channel.basic_publish(
            exchange='', 
            routing_key='doc_received_medium',  # ✅ CORRECT QUEUE
            body=json.dumps(message_to_extractor)
        )
        connection.close()
        
        print(f"[API] Successfully queued {document_id} for re-extraction.")
        return {"status": "success", "detail": f"Document {document_id} sent for re-extraction."}

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"[API Error] Failed to re-extract {document_id}: {e}")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="[::]", port=8000)