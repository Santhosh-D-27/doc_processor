# ingestor/file_monitor.py

import uuid
import time
import pika
import json
import base64
import os
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
QUEUE_NAME = 'doc_received_queue'
STATUS_QUEUE_NAME = 'document_status_queue'
MONITORED_PATH = './monitored_folder'
STORAGE_PATH = 'document_storage' # Our new storage folder

# --- Helper Functions ---
def publish_status_update(doc_id: str, status: str, details: dict = None):
    """Publishes a status update for a document to the status queue."""
    if details is None:
        details = {}
    status_message = {
        "document_id": doc_id,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
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

def decide_priority(file_size: int, folder: str = None) -> str:
    """Determines priority based on file size or source folder."""
    if folder and "high_priority" in folder:
        return "high"
    if file_size > 1_000_000:  # More than 1MB
        return "high"
    return "medium"

def publish_message(message: dict):
    """Publishes a message to the RabbitMQ queue."""
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
    print(f" [x] Sent '{message['filename']}' from file-share to the queue (Doc ID: {doc_id}).")

class DocumentHandler(FileSystemEventHandler):
    """Handles file system events for new documents."""
    def on_created(self, event):
        if event.is_directory or event.src_path.endswith('.tmp'):
            return

        print(f" [!] New file detected: {event.src_path}")
        document_id = str(uuid.uuid4())
        original_filename = os.path.basename(event.src_path)
        
        file_extension = os.path.splitext(original_filename)[1]
        storage_filename = f"{document_id}{file_extension}"
        storage_file_path = os.path.join(STORAGE_PATH, storage_filename)

        try:
            time.sleep(1) # Wait for the file to be fully written
            
            # --- NEW: Copy the file to our persistent storage ---
            os.makedirs(STORAGE_PATH, exist_ok=True)
            shutil.copy(event.src_path, storage_file_path)
            print(f"  -> Copied original file to: {storage_file_path}")

            with open(storage_file_path, 'rb') as file:
                file_content = file.read()

            file_size = len(file_content)
            priority = decide_priority(file_size, os.path.dirname(event.src_path))
            encoded_content = base64.b64encode(file_content).decode('utf-8')

            message = {
                'document_id': document_id,
                'filename': original_filename,
                'storage_path': storage_file_path, # Pass the new path
                'content_type': 'application/octet-stream',
                'file_content': encoded_content,
                'priority': priority,
                'source': 'file_share',
                'sender': 'system_fileshare_monitor'
            }
            publish_message(message)

            publish_status_update(
                doc_id=document_id,
                status="Ingested",
                details={"filename": original_filename, "source": "File Share", "storage_path": storage_file_path}
            )

        except Exception as e:
            print(f" [e] Error processing file {event.src_path}: {e}")
            publish_status_update(
                doc_id=document_id,
                status="Ingestion Failed",
                details={"filename": original_filename, "error": str(e)}
            )

if __name__ == "__main__":
    print(f"[*] Starting file-share monitor on folder: {MONITORED_PATH}")
    event_handler = DocumentHandler()
    observer = Observer()
    observer.schedule(event_handler, MONITORED_PATH, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
