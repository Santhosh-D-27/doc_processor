# extractor/main.py - Priority-Aware Multi-Threaded Document Extractor

import time
import pika
import json
import base64
import pytesseract
import os
import threading
import queue
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Optional
from enum import IntEnum
import google.generativeai as genai
from pdf2image import convert_from_bytes
from PIL import Image
import io
from datetime import datetime, UTC
from dotenv import load_dotenv
import docx
import groq

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

PRIORITY_THREAD_ALLOCATION = {
    Priority.CRITICAL: 4, Priority.HIGH: 3, Priority.MEDIUM: 2, Priority.LOW: 1, Priority.BULK: 1
}

# Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger("pika").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CLASSIFICATION_QUEUE = 'classification_queue'
STATUS_QUEUE_NAME = 'document_status_queue'
MAX_WORKERS = int(os.getenv('EXTRACTOR_MAX_WORKERS', '11'))
PREFETCH_COUNT = int(os.getenv('EXTRACTOR_PREFETCH_COUNT', '1'))
MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '50000'))

# Initialize OCR
tesseract_path = os.getenv("TESSERACT_CMD_PATH")
if tesseract_path and os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

# Initialize LLM clients
groq_client = None
gemini_model = None

try:
    groq_client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    logger.info("Groq client initialized (Primary)")
except Exception:
    pass

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    logger.info("Gemini client initialized (Fallback)")
except Exception:
    pass

if not groq_client and not gemini_model:
    logger.warning("No LLM clients available - analysis will be limited")

# Data Classes
@dataclass
class ProcessingTask:
    message: dict
    priority: int
    document_id: str
    filename: str
    delivery_tag: int
    channel: object

@dataclass
class ExtractionResult:
    success: bool
    document_id: str
    filename: str
    extracted_text: str = ""
    summary: str = ""
    priority_content: dict = None
    error: str = ""
    processing_time: float = 0.0

# Connection Management
class SimpleConnectionManager:
    def __init__(self, host: str):
        self.host = host
        self._lock = threading.Lock()
    
    def get_connection(self):
        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host=self.host, heartbeat=600))
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return None

connection_manager = SimpleConnectionManager(RABBITMQ_HOST)

# Core Functions
def publish_status_update(doc_id: str, status: str, details: dict = None, priority_score: int = None, priority_reason: str = None):
    if details is None:
        details = {}
    if priority_score is not None:
        details['priority_score'] = priority_score
    if priority_reason is not None:
        details['priority_reason'] = priority_reason
    
    message = {
        "document_id": doc_id, "status": status, "timestamp": datetime.now(UTC).isoformat(), "details": details
    }
    
    connection = connection_manager.get_connection()
    if connection:
        try:
            channel = connection.channel()
            channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
            channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, body=json.dumps(message))
            connection.close()
        except Exception:
            pass

def extract_text_from_document(content_bytes: bytes, content_type: str, filename: str) -> str:
    if not content_bytes:
        raise ValueError("Empty document content")
    
    file_extension = os.path.splitext(filename)[1].lower()
    
    if 'pdf' in content_type or file_extension == '.pdf':
        poppler_path = os.getenv("POPPLER_PATH")
        convert_kwargs = {'poppler_path': poppler_path} if poppler_path and os.path.exists(poppler_path) else {}
        images = convert_from_bytes(content_bytes, **convert_kwargs)
        text_parts = [pytesseract.image_to_string(image, config='--psm 6') for image in images]
        text = '\n'.join(text_parts)
            
    elif 'image' in content_type or file_extension in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
        image = Image.open(io.BytesIO(content_bytes))
        text = pytesseract.image_to_string(image, config='--psm 6')
        
    elif 'vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type or file_extension == '.docx':
        doc = docx.Document(io.BytesIO(content_bytes))
        text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
        text = '\n'.join(text_parts)
        
    elif 'text' in content_type or file_extension in ['.txt', '.csv']:
        for encoding in ['utf-8', 'utf-16', 'latin-1', 'cp1252']:
            try:
                text = content_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content_bytes.decode('utf-8', errors='ignore')
    else:
        text = content_bytes.decode('utf-8', errors='ignore')
    
    text = text.strip()
    if len(text) < 10:
        raise ValueError(f"Extracted text too short: {len(text)} characters")
    
    return text

def analyze_document_content_with_llm(text: str, priority_score: int = 20) -> dict:
    if not groq_client and not gemini_model:
        return {"cleaned_text": text, "summary": "LLM analysis unavailable", "priority_content": {"urgency_level": "low"}}
    
    if len(text.strip()) < 10:
        return {"cleaned_text": text, "summary": "Document too short for analysis", "priority_content": {"urgency_level": "low"}}
    
    processing_text = text[:MAX_TEXT_LENGTH]
    if len(text) > MAX_TEXT_LENGTH:
        processing_text += "\n[... text truncated ...]"
    
    urgency_context = ""
    if priority_score >= Priority.CRITICAL:
        urgency_context = "This is a CRITICAL priority document. Pay special attention to urgent deadlines."
    elif priority_score >= Priority.HIGH:
        urgency_context = "This is a HIGH priority document. Focus on important deadlines."
    
    prompt = f"""
    {urgency_context}
    
    Analyze this document and provide JSON with:
    1. Cleaned text (fix OCR errors)
    2. 2-3 sentence summary
    3. Extract: deadlines, key_parties, financial_commitments, action_items, urgency_level
    
    Return as valid JSON:
    {{
      "cleaned_text": "corrected text",
      "summary": "brief summary",
      "priority_content": {{
        "deadlines": ["list"], "key_parties": ["list"], "financial_commitments": ["list"],
        "action_items": ["list"], "urgency_level": "high/medium/low"
      }}
    }}
    
    Document: {processing_text}
    """
    
    # Try Groq first
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant", temperature=0.1, max_tokens=2048
            )
            json_text = response.choices[0].message.content.strip().lstrip('```json').rstrip('```').strip()
            
            if '{' in json_text and '}' in json_text:
                start, end = json_text.find('{'), json_text.rfind('}') + 1
                json_text = json_text[start:end]
            
            result = json.loads(json_text)
            
            # Ensure required structure
            if all(key in result for key in ['cleaned_text', 'summary', 'priority_content']):
                priority_content = result.get('priority_content', {})
                defaults = {'deadlines': [], 'key_parties': [], 'financial_commitments': [], 'action_items': [], 'urgency_level': 'low'}
                for field, default in defaults.items():
                    if field not in priority_content:
                        priority_content[field] = default
                return result
        except Exception:
            pass
    
    # Fallback to Gemini
    if gemini_model:
        try:
            response = gemini_model.generate_content(prompt)
            json_text = response.text.strip().lstrip('```json').rstrip('```').strip()
            result = json.loads(json_text)
            
            if all(key in result for key in ['cleaned_text', 'summary', 'priority_content']):
                priority_content = result.get('priority_content', {})
                defaults = {'deadlines': [], 'key_parties': [], 'financial_commitments': [], 'action_items': [], 'urgency_level': 'low'}
                for field, default in defaults.items():
                    if field not in priority_content:
                        priority_content[field] = default
                return result
        except Exception:
            pass
    
    return {"cleaned_text": text, "summary": "LLM analysis failed", "priority_content": {"urgency_level": "low"}}

# Processing Engine
class PriorityProcessor:
    def __init__(self):
        self.stats = {'total_processed': 0, 'errors': 0}
        self.stats_lock = threading.Lock()
    
    def process_document(self, task: ProcessingTask) -> ExtractionResult:
        start_time = time.time()
        
        try:
            message = task.message
            priority_score = message.get('priority_score', Priority.LOW)
            
            file_content_bytes = base64.b64decode(message['file_content'])
            content_type = message.get('content_type', 'application/octet-stream')
            
            raw_text = extract_text_from_document(file_content_bytes, content_type, task.filename)
            processed_data = analyze_document_content_with_llm(raw_text, priority_score)
            
            processing_time = time.time() - start_time
            
            with self.stats_lock:
                self.stats['total_processed'] += 1
            
            return ExtractionResult(
                success=True, document_id=task.document_id, filename=task.filename,
                extracted_text=processed_data.get('cleaned_text', raw_text),
                summary=processed_data.get('summary', 'No summary available'),
                priority_content=processed_data.get('priority_content', {}),
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            with self.stats_lock:
                self.stats['errors'] += 1
            
            return ExtractionResult(
                success=False, document_id=task.document_id, filename=task.filename,
                error=str(e), processing_time=processing_time
            )

# Queue Consumer
class PriorityQueueConsumer:
    def __init__(self, priority: Priority, thread_count: int, processor: PriorityProcessor):
        self.priority = priority
        self.queue_name = PRIORITY_QUEUES[priority]
        self.processor = processor
        self.executor = ThreadPoolExecutor(max_workers=thread_count, thread_name_prefix=f"P{priority.value}")
        self.connection = None
        self.channel = None
        self.is_running = False
    
    def connect(self):
        try:
            self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600))
            self.channel = self.connection.channel()
            self.channel.queue_declare(queue=self.queue_name, durable=True)
            self.channel.queue_declare(queue=CLASSIFICATION_QUEUE, durable=True)
            self.channel.basic_qos(prefetch_count=PREFETCH_COUNT)
            logger.info(f"Connected to {self.queue_name}")
            return True
        except Exception as e:
            logger.error(f"Connection failed for {self.queue_name}: {e}")
            return False
    
    def process_message_callback(self, ch, method, properties, body):
        try:
            message = json.loads(body)
            task = ProcessingTask(
                message=message, priority=self.priority.value,
                document_id=message.get('document_id', 'unknown'),
                filename=message.get('filename', 'unknown'),
                delivery_tag=method.delivery_tag, channel=ch
            )
            self.executor.submit(self.process_task, task)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def process_task(self, task: ProcessingTask):
        try:
            result = self.processor.process_document(task)
            
            if result.success:
                classifier_message = {
                    'document_id': result.document_id, 'filename': result.filename,
                    'extracted_text': result.extracted_text, 'summary': result.summary,
                    'priority_content': result.priority_content, 'entities': {},
                    'sender': task.message.get('sender', 'N/A'),
                    'priority_score': task.message.get('priority_score', Priority.LOW),
                    'priority_reason': task.message.get('priority_reason', 'Unknown')
                }
                self.send_to_classifier(classifier_message)
                publish_status_update(
                    doc_id=result.document_id, status="Extracted",
                    details={"chars_extracted": len(result.extracted_text), "processing_time": result.processing_time},
                    priority_score=task.message.get('priority_score'),
                    priority_reason=task.message.get('priority_reason')
                )
            else:
                publish_status_update(
                    doc_id=result.document_id, status="Extraction Failed",
                    details={"error": result.error},
                    priority_score=task.message.get('priority_score'),
                    priority_reason=task.message.get('priority_reason')
                )
        except Exception as e:
            logger.error(f"Task processing error {task.document_id}: {e}")
    
    def send_to_classifier(self, message: dict):
        connection = connection_manager.get_connection()
        if connection:
            try:
                channel = connection.channel()
                channel.queue_declare(queue=CLASSIFICATION_QUEUE, durable=True)
                channel.basic_publish(exchange='', routing_key=CLASSIFICATION_QUEUE, body=json.dumps(message))
                connection.close()
            except Exception:
                pass
    
    def start_consuming(self):
        if not self.connect():
            return False
        
        self.is_running = True
        try:
            self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.process_message_callback)
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.error(f"Consumer error for {self.queue_name}: {e}")
        finally:
            self.cleanup()
        return True
    
    def stop(self):
        self.is_running = False
        if self.channel and hasattr(self.channel, 'stop_consuming'):
            self.channel.stop_consuming()
        self.executor.shutdown(wait=True, timeout=30)
    
    def cleanup(self):
        if self.connection and hasattr(self.connection, 'is_open') and self.connection.is_open:
            try:
                self.connection.close()
            except Exception:
                pass

# Main Service
class PriorityExtractionService:
    def __init__(self):
        self.processor = PriorityProcessor()
        self.consumers = {}
        self.consumer_threads = {}
        self.is_running = False
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down...")
        self.stop()
        sys.exit(0)
    
    def start(self):
        total_threads = sum(PRIORITY_THREAD_ALLOCATION.values())
        model_name = "Groq+Gemini" if groq_client and gemini_model else ("Groq" if groq_client else ("Gemini" if gemini_model else "No Models"))
        logger.info(f"Starting Extraction Service | Workers: {total_threads} | Model: {model_name}")
        
        self.is_running = True
        
        for priority, thread_count in PRIORITY_THREAD_ALLOCATION.items():
            consumer = PriorityQueueConsumer(priority, thread_count, self.processor)
            self.consumers[priority] = consumer
            consumer_thread = threading.Thread(target=consumer.start_consuming, name=f"Consumer-{priority.name}")
            self.consumer_threads[priority] = consumer_thread
            consumer_thread.start()
        
        # Stats reporter
        threading.Thread(target=self.stats_reporter, daemon=True).start()
        
        logger.info("All consumers started. Processing documents...")
        
        try:
            for thread in self.consumer_threads.values():
                thread.join()
        except KeyboardInterrupt:
            self.stop()
    
    def stats_reporter(self):
        while self.is_running:
            try:
                time.sleep(60)
                if self.is_running:
                    stats = self.processor.stats
                    logger.info(f"[STATS] Processed: {stats['total_processed']} | Errors: {stats['errors']}")
            except Exception:
                pass
    
    def stop(self):
        logger.info("Stopping Extraction Service...")
        self.is_running = False
        
        for consumer in self.consumers.values():
            consumer.stop()
        
        logger.info("Extraction Service stopped")

# Main Entry Point
def main():
    try:
        service = PriorityExtractionService()
        service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()