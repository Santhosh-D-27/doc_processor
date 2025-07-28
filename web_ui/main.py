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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import List
from fastapi.middleware.cors import CORSMiddleware
import imaplib
from datetime import datetime

# --- Configuration ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
STATUS_QUEUE_NAME = 'document_status_queue'
DB_NAME = 'web_ui/state.db'

# --- Pydantic Models for API Data Validation ---
class Mailbox(BaseModel):
    email: str
    app_password: str
    folder: str = 'inbox'

# --- Database Setup ---
def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Main table for current state
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_status (
            document_id TEXT PRIMARY KEY, filename TEXT, status TEXT, doc_type TEXT,
            confidence REAL, last_updated TEXT
        )
    ''')
    # History table with original file content
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT, status TEXT,
            timestamp TEXT, details TEXT, doc_type TEXT, confidence REAL,
            file_content_encoded TEXT, -- To store the raw file on ingest
            FOREIGN KEY (document_id) REFERENCES document_status (document_id)
        )
    ''')
    # Mailbox Configurations Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mailboxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            app_password_encoded TEXT NOT NULL,
            folder TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            status_timestamp TEXT
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
                
                try:
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()

                    # Insert into history table, including file content if present
                    cursor.execute("""
                        INSERT INTO document_history (document_id, status, timestamp, details, doc_type, confidence, file_content_encoded)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id, status, timestamp,
                        json.dumps(message.get("details", {})),
                        message.get("doc_type"), message.get("confidence"),
                        message.get("details", {}).get("file_content_encoded")
                    ))
                    
                    # Get existing data before updating
                    cursor.execute("SELECT filename, doc_type, confidence FROM document_status WHERE document_id = ?", (doc_id,))
                    existing_data = cursor.fetchone() or (None, None, None)
                    
                    # Update (or insert) the main status table
                    cursor.execute("""
                        INSERT OR REPLACE INTO document_status 
                        (document_id, filename, status, doc_type, confidence, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        message.get("details", {}).get("filename", existing_data[0]),
                        status,
                        message.get("doc_type", existing_data[1]),
                        message.get("confidence", existing_data[2]),
                        timestamp
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

# --- Helper function to test mailbox credentials ---
def test_mailbox_connection(email: str, app_password: str) -> bool:
    try:
        print(f"  -> Testing connection for {email}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email, app_password)
        mail.logout()
        print(f"  -> Connection successful for {email}.")
        return True
    except imaplib.IMAP4.error as e:
        print(f"  -> Connection failed for {email}: {e}")
        return False

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
    return [dict(row) for row in history]

def get_doc_for_reprocessing(document_id: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM document_status WHERE document_id = ?", (document_id,))
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@app.post("/re-classify/{document_id}")
def re_classify_document(document_id: str):
    doc = get_doc_for_reprocessing(document_id)
    history_events = get_document_history(document_id)
    
    extracted_details = {}
    for event in reversed(history_events):
        if event['status'] == 'Extracted':
            extracted_details = json.loads(event['details'])
            break

    message = {
        'document_id': doc['document_id'],
        'filename': doc['filename'],
        'extracted_text': extracted_details.get('extracted_text', ''),
        'entities': extracted_details.get('entities', {})
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
        history_events = get_document_history(document_id)
        ingested_event = next((event for event in history_events if event['status'] == 'Ingested'), None)

        if not ingested_event:
            raise HTTPException(status_code=404, detail="Original ingestion record not found.")

        details = json.loads(ingested_event['details'])
        storage_path = details.get('storage_path')

        if not storage_path or not os.path.exists(storage_path):
            raise HTTPException(status_code=404, detail=f"Stored file not found at path: {storage_path}")

        with open(storage_path, 'rb') as f:
            file_content = f.read()
        
        original_filename = details.get('filename')
        
        message_to_extractor = {
            'document_id': document_id,
            'filename': original_filename,
            'storage_path': storage_path,
            'content_type': 'application/octet-stream',
            'file_content': base64.b64encode(file_content).decode('utf-8'),
            'priority': 'high',
            'source': 'manual_re-extract'
        }

        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue='doc_received_queue', durable=True)
        channel.basic_publish(exchange='', routing_key='doc_received_queue', body=json.dumps(message_to_extractor))
        connection.close()
        
        return {"status": "success"}

    except Exception as e:
        print(f"[API Error] Failed to re-extract {document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Mailbox Management API Endpoints ---
@app.get("/mailboxes")
def get_mailboxes():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, folder, status FROM mailboxes")
    mailboxes = cursor.fetchall()
    conn.close()
    return [dict(row) for row in mailboxes]

@app.post("/mailboxes")
def add_mailbox(mailbox: Mailbox):
    is_valid = test_mailbox_connection(mailbox.email, mailbox.app_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Authentication failed. Please check the email and App Password.")

    encoded_password = base64.b64encode(mailbox.app_password.encode()).decode()
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO mailboxes (email, app_password_encoded, folder, status, status_timestamp) VALUES (?, ?, ?, ?, ?)",
            (mailbox.email, encoded_password, mailbox.folder, "Connected", datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return {"status": "success", "email": mailbox.email}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email address already configured.")

@app.delete("/mailboxes/{mailbox_id}")
def delete_mailbox(mailbox_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "id": mailbox_id}

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