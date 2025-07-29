# ingestor/main.py

import uvicorn
import pika
import json
import base64
import os
from fastapi import FastAPI, UploadFile, File, Form
from datetime import datetime, UTC
import uuid
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
QUEUE_NAME = 'doc_received_queue'
STATUS_QUEUE_NAME = 'document_status_queue'
STORAGE_PATH = 'document_storage' # Our new storage folder

# --- Helper Functions ---
def publish_status_update(doc_id: str, status: str, details: dict = None):
    """Publishes a status update for a document to the status queue."""
    if details is None:
        details = {}
    status_message = {
        "document_id": doc_id,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details
    }
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=STATUS_QUEUE_NAME,
            body=json.dumps(status_message)
        )
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def decide_priority(file_size: int, sender: str = None) -> str:
    """Decides priority based on sender or file size."""
    if sender and ("ceo" in sender.lower() or "director" in sender.lower() or "vp" in sender.lower()): # Added more keywords
        return "high"
    if file_size > 1_000_000:  # More than 1MB
        return "high"
    return "medium"

@app.post("/upload")
async def upload_document(
    sender: str = Form(None),
    file: UploadFile = File(...)
):
    document_id = str(uuid.uuid4())
    original_filename = file.filename
    
    # Get the file extension to preserve it
    file_extension = os.path.splitext(original_filename)[1]
    storage_filename = f"{document_id}{file_extension}"
    file_path = os.path.join(STORAGE_PATH, storage_filename)

    try:
        file_content = await file.read()
        
        # --- NEW: Save the original file to local storage ---
        os.makedirs(STORAGE_PATH, exist_ok=True) # Ensure directory exists
        with open(file_path, "wb") as f:
            f.write(file_content)
        print(f"  -> Saved original file to: {file_path}")

        # --- Continue with existing logic ---
        file_size = len(file_content)
        priority = decide_priority(file_size, sender)
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')
        
        message = {
            'document_id': document_id,
            'filename': original_filename,
            'storage_path': file_path, # Pass the path for future reference
            'content_type': file.content_type,
            'file_content': encoded_file_content,
            'priority': priority,
            'source': 'api_upload',
            'sender': sender
        }
        
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(exchange='', routing_key=QUEUE_NAME, body=json.dumps(message))
        connection.close()
        print(f" [x] Sent '{original_filename}' to the queue (Doc ID: {document_id}).")
        
        publish_status_update(
            doc_id=document_id,
            status="Ingested",
            details={"filename": original_filename, "source": "API Upload", "storage_path": file_path, "file_content_encoded": encoded_file_content, "content_type": file.content_type, "sender": sender} # Pass content for re-extract
        )
        
        return {"document_id": document_id, "filename": original_filename, "status": "published"}
    except Exception as e:
        print(f" [e] Ingestion failed for {original_filename}: {e}")
        publish_status_update(
            doc_id=document_id,
            status="Ingestion Failed",
            details={"filename": original_filename, "error": str(e)}
        )
        return {"error": str(e), "status": "failed_to_publish"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)