# classifier/main.py - Simplified Document Classifier

import time, pika, json, os, threading, logging, signal, sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Tuple
from enum import IntEnum
import google.generativeai as genai
from datetime import datetime, UTC
from dotenv import load_dotenv
import re, groq

load_dotenv()

class Priority(IntEnum):
    CRITICAL = 100
    HIGH = 80
    MEDIUM = 50
    LOW = 20
    BULK = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger("pika").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Configuration
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'classification_queue'
PUBLISH_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'
MAX_WORKERS = int(os.getenv('CLASSIFIER_MAX_WORKERS', '8'))
PREFETCH_COUNT = int(os.getenv('CLASSIFIER_PREFETCH_COUNT', '2'))

# VIP Configuration
VIP_DOMAINS = ['board@', 'executives@', 'leadership@', 'c-suite@']
VIP_KEYWORDS = ['ceo', 'director', 'vice president', 'vp', 'senior manager', 'head of', 
               'board member', 'hr director', 'legal counsel', 'president', 'founder', 
               'partner', 'owner', 'chairman', 'chairwoman']

@dataclass
class ClassificationTask:
    message: dict
    document_id: str
    filename: str
    priority_score: int
    priority_reason: str
    delivery_tag: int
    channel: object

@dataclass
class ClassificationResult:
    success: bool
    document_id: str
    filename: str
    doc_type: str = "UNKNOWN"
    confidence: float = 0.0
    is_vip: bool = False
    vip_level: str = "NONE"
    reasoning: str = ""
    processing_time: float = 0.0
    error: str = ""

# Initialize LLM clients
groq_client = None
gemini_model = None

try:
    groq_client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    logger.info("✓ Groq client initialized")
except: pass

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    logger.info("✓ Gemini client initialized")
except: pass

if not groq_client and not gemini_model:
    logger.warning("⚠ No LLM clients available")

def get_rabbitmq_connection():
    """Get a RabbitMQ connection with retry"""
    try:
        return pika.BlockingConnection(pika.ConnectionParameters(
            host=RABBITMQ_HOST, heartbeat=600, blocked_connection_timeout=300, socket_timeout=10
        ))
    except:
        return None

def publish_message(queue_name: str, message: dict):
    """Publish message to RabbitMQ queue"""
    connection = get_rabbitmq_connection()
    if connection:
        try:
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_publish(
                exchange='', routing_key=queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
        except: pass
        finally:
            try: connection.close()
            except: pass

def publish_status_update(doc_id: str, status: str, filename: str = None, **kwargs):
    """Publish status update"""
    message = {
        "document_id": doc_id,
        "filename": filename,
        "status": status,
        "last_updated": datetime.now(UTC).isoformat(),
        **kwargs
    }
    publish_message(STATUS_QUEUE_NAME, message)

def publish_doc_type_event(doc_id: str, filename: str, doc_type: str, confidence: float, 
                          reasoning: str, is_vip: bool, vip_level: str):
    """Publish doc.type event"""
    message = {
        "event_type": "doc.type",
        "document_id": doc_id,
        "filename": filename,
        "doc_type": doc_type,
        "confidence": confidence,
        "reasoning": reasoning,
        "is_vip": is_vip,
        "vip_level": vip_level,
        "timestamp": datetime.now(UTC).isoformat()
    }
    publish_message('doc_type_events', message)

def classify_document(text: str) -> dict:
    """LLM zero-shot classification"""
    if not groq_client and not gemini_model:
        return {"doc_type": "HUMAN_REVIEW_NEEDED", "confidence_score": 0.0, "reasoning": "No LLM available"}
    
    if not text or not text.strip():
        return {"doc_type": "HUMAN_REVIEW_NEEDED", "confidence_score": 0.0, "reasoning": "Empty text"}
    
    processing_text = text[:6000]
    if len(text) > 6000:
        processing_text += "\n[... text truncated for classification ...]"
    
    prompt = f"""You are a document classification expert. Classify this document into ONE of these categories:

**RESUME**: CV, curriculum vitae, job applications with work experience, education, skills
**INVOICE**: Bills, payment requests, invoices with amounts, billing addresses  
**CONTRACT**: Legal agreements, terms & conditions, binding contracts with parties
**AGREEMENT**: MOUs, service agreements, partnership agreements, NDAs
**MEMO**: Internal memos, company communications, announcements
**REPORT**: Business reports, analysis documents, quarterly reports, research
**GRIEVANCE**: Complaints, disputes, incident reports, HR grievances
**ID_PROOF**: Government IDs, passports, driver licenses, official identification

INSTRUCTIONS:
1. Look for clear document indicators and structure
2. Be conservative with confidence - only give high confidence if you're very certain
3. Use these confidence ranges:
   - 0.95-1.0: Extremely clear indicators (like "INVOICE #12345" or "CURRICULUM VITAE")
   - 0.85-0.94: Strong indicators but some ambiguity
   - 0.75-0.84: Moderate confidence with some uncertainty
   - Below 0.75: Unclear - will be sent for human review
4. If document has mixed characteristics or unclear type, use lower confidence

Return ONLY valid JSON:
{{"doc_type": "CATEGORY_NAME", "confidence_score": 0.XX, "reasoning": "Brief explanation of key indicators found"}}

Document:
---
{processing_text}
---"""

    def parse_response(response_text: str) -> dict:
        if not response_text:
            return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "reasoning": "Empty response"}
        
        try:
            # Clean response
            cleaned = re.sub(r'^```(?:json)?\s*|```$', '', response_text.strip(), flags=re.IGNORECASE)
            start, end = cleaned.find('{'), cleaned.rfind('}')
            if start == -1 or end == -1:
                return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "reasoning": "Invalid JSON format"}
            
            result = json.loads(cleaned[start:end + 1])
            
            # Validate doc_type
            valid_types = ['RESUME', 'INVOICE', 'CONTRACT', 'AGREEMENT', 'MEMO', 'REPORT', 'GRIEVANCE', 'ID_PROOF']
            if result.get('doc_type') not in valid_types:
                return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "reasoning": "Invalid document type"}
            
            # Validate confidence
            confidence = min(max(float(result.get('confidence_score', 0.0)), 0.0), 0.95)
            
            return {
                "doc_type": result.get('doc_type', 'UNKNOWN'),
                "confidence_score": confidence,
                "reasoning": result.get('reasoning', 'LLM classification')
            }
            
        except:
            return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "reasoning": "Parse error"}
    
    # Try Groq first
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.1,
                max_tokens=300,
                top_p=0.9
            )
            result = parse_response(response.choices[0].message.content)
            if result['doc_type'] != 'UNKNOWN':
                return result
        except Exception as e:
            logger.warning(f"Groq classification failed: {e}")
    
    # Try Gemini fallback
    if gemini_model:
        try:
            response = gemini_model.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,
                    'top_p': 0.9,
                    'max_output_tokens': 300,
                }
            )
            result = parse_response(response.text)
            if result['doc_type'] != 'UNKNOWN':
                return result
        except Exception as e:
            logger.warning(f"Gemini classification failed: {e}")
    
    return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "reasoning": "All LLM attempts failed"}

def determine_vip_status(sender: str, priority_score: int) -> Tuple[bool, str]:
    """Determine VIP status based on priority and sender"""
    try:
        # Priority-based VIP
        if priority_score >= Priority.CRITICAL:
            return True, "HIGH"
        elif priority_score >= Priority.HIGH:
            return True, "MEDIUM"
        
        # Sender-based VIP detection
        if sender:
            sender_lower = sender.lower()
            
            # Check domains and keywords
            for domain in VIP_DOMAINS:
                if domain in sender_lower:
                    return True, "HIGH"
            
            high_keywords = ['ceo', 'chief executive officer', 'board member', 'director', 
                           'founder', 'president', 'chairman', 'chairwoman']
            for keyword in high_keywords:
                if keyword in sender_lower:
                    return True, "HIGH"
            
            medium_keywords = ['vp', 'vice president', 'senior manager', 'department head', 
                             'legal counsel', 'hr director', 'partner', 'owner']
            for keyword in medium_keywords:
                if keyword in sender_lower:
                    return True, "MEDIUM"
        
        return False, "NONE"
    except:
        return False, "NONE"

class PriorityClassificationProcessor:
    def __init__(self):
        self.stats = {'total_processed': 0, 'vip_processed': 0, 'errors': 0}
    
    def process_document(self, task: ClassificationTask) -> ClassificationResult:
        start_time = time.time()
        
        try:
            message = task.message
            extracted_text = message.get('extracted_text', '')
            sender = message.get('sender', 'N/A')
            
            # Check for override parameters
            override_params = message.get('override_parameters', {})
            force_classification = override_params.get('force_classification', False)
            manual_type_hint = override_params.get('manual_type_hint')
            custom_threshold = override_params.get('confidence_threshold')
            
            # Determine VIP status
            is_vip, vip_level = determine_vip_status(sender, task.priority_score)
            
            # Classify document
            classification_result = classify_document(extracted_text)
            doc_type = classification_result.get('doc_type', 'UNKNOWN')
            confidence = classification_result.get('confidence_score', 0.0)
            reasoning = classification_result.get('reasoning', 'Classification completed')
            
            VALID_TYPES = ['REPORT', 'RESUME', 'MEMO', 'INVOICE', 'AGREEMENT', 'CONTRACT', 'GRIEVANCE', 'ID_PROOF']
            
            # Use 75% threshold (or custom if provided)
            min_confidence = custom_threshold if custom_threshold is not None else 0.75
            
            # Handle manual type hint
            if manual_type_hint and manual_type_hint in VALID_TYPES:
                doc_type = manual_type_hint
                confidence = 1.0
                reasoning = f"Manual override: {manual_type_hint}"
            
            # Check confidence threshold
            if not force_classification and confidence < min_confidence:
                doc_type = "HUMAN_REVIEW_NEEDED"
                confidence = 0.0
                reasoning = f"Low confidence ({classification_result.get('confidence_score', 0.0):.2f}) - needs human review"
            
            processing_time = time.time() - start_time
            
            # Update stats
            self.stats['total_processed'] += 1
            if is_vip:
                self.stats['vip_processed'] += 1
            
            return ClassificationResult(
                success=True,
                document_id=task.document_id,
                filename=task.filename,
                doc_type=doc_type,
                confidence=confidence,
                is_vip=is_vip,
                vip_level=vip_level,
                reasoning=reasoning,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            self.stats['errors'] += 1
            
            return ClassificationResult(
                success=False,
                document_id=task.document_id,
                filename=task.filename,
                processing_time=processing_time,
                error=str(e)
            )

class PriorityClassificationService:
    def __init__(self):
        self.processor = PriorityClassificationProcessor()
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="Classifier")
        self.is_running = False
        self.connection = None
        self.channel = None
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down...")
        self.stop()
        sys.exit(0)
    
    def connect(self):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self.connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600, blocked_connection_timeout=300)
                )
                self.channel = self.connection.channel()
                self.channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
                self.channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                self.channel.basic_qos(prefetch_count=PREFETCH_COUNT)
                logger.info("✓ Connected to RabbitMQ")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    logger.error(f"Failed to connect after {max_retries} attempts: {e}")
                    return False
        return False
    
    def process_message_callback(self, ch, method, properties, body):
        try:
            message = json.loads(body)
            task = ClassificationTask(
                message=message,
                document_id=message.get('document_id', 'unknown_id'),
                filename=message.get('filename', 'unknown_file'),
                priority_score=message.get('priority_score', Priority.LOW),
                priority_reason=message.get('priority_reason', 'Unknown'),
                delivery_tag=method.delivery_tag,
                channel=ch
            )
            
            # Process document
            result = self.processor.process_document(task)
            
            if result.success:
                # Publish doc.type event
                publish_doc_type_event(
                    doc_id=result.document_id,
                    filename=result.filename,
                    doc_type=result.doc_type,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    is_vip=result.is_vip,
                    vip_level=result.vip_level
                )
                
                # Send to router
                router_message = {
                    'document_id': result.document_id,
                    'filename': result.filename,
                    'doc_type': result.doc_type,
                    'confidence': result.confidence,
                    'entities': task.message.get('entities', {}),
                    'summary': task.message.get('summary', 'No summary available.'),
                    'priority_content': task.message.get('priority_content', {}),
                    'is_vip': result.is_vip,
                    'vip_level': result.vip_level,
                    'priority_score': task.priority_score,
                    'priority_reason': task.priority_reason,
                    'sender': task.message.get('sender', 'N/A'),
                    'extracted_text': task.message.get('extracted_text', ''),
                    'reasoning': result.reasoning
                }
                
                # Try to send to router
                if self.send_to_router_with_retry(router_message):
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    
                    # Send status update
                    publish_status_update(
                        doc_id=result.document_id,
                        status="Classified",
                        filename=result.filename,
                        doc_type=result.doc_type,
                        confidence=result.confidence,
                        is_vip=result.is_vip,
                        vip_level=result.vip_level,
                        priority_score=task.priority_score,
                        priority_reason=task.priority_reason,
                        summary=task.message.get('summary', 'No summary available'),
                        details={"processing_time": result.processing_time, "reasoning": result.reasoning}
                    )
                else:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                publish_status_update(
                    doc_id=result.document_id,
                    status="Classification Failed",
                    filename=result.filename,
                    priority_score=task.priority_score,
                    priority_reason=task.priority_reason,
                    summary=task.message.get('summary', 'No summary available'),
                    details={"error": result.error, "processing_time": result.processing_time}
                )
                    
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    def send_to_router_with_retry(self, message: dict, max_retries: int = 3) -> bool:
        """Send message to router with retry logic"""
        for attempt in range(max_retries):
            connection = get_rabbitmq_connection()
            if connection:
                try:
                    channel = connection.channel()
                    channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                    channel.basic_publish(
                        exchange='',
                        routing_key=PUBLISH_QUEUE_NAME,
                        body=json.dumps(message),
                        properties=pika.BasicProperties(delivery_mode=2)
                    )
                    connection.close()
                    return True
                except Exception as e:
                    logger.warning(f"Router send attempt {attempt + 1} failed: {e}")
                    try: connection.close()
                    except: pass
            
            if attempt < max_retries - 1:
                time.sleep(1)
        
        return False
    
    def start(self):
        model_name = "Groq+Gemini" if groq_client and gemini_model else ("Groq" if groq_client else ("Gemini" if gemini_model else "No Models"))
        logger.info(f"🚀 Starting Classification Service | Workers: {MAX_WORKERS} | Model: {model_name}")
        
        if not self.connect():
            logger.error("Failed to establish connection. Exiting.")
            return False
        
        self.is_running = True
        threading.Thread(target=self.stats_reporter, daemon=True).start()
        
        try:
            logger.info("✓ Classification service ready - waiting for tasks...")
            self.channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=self.process_message_callback)
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.error(f"Service error: {e}")
        finally:
            self.cleanup()
        return True
    
    def stats_reporter(self):
        while self.is_running:
            try:
                time.sleep(60)
                if self.is_running:
                    stats = self.processor.stats
                    logger.info(f"📊 Processed: {stats['total_processed']} | VIP: {stats['vip_processed']} | Errors: {stats['errors']}")
            except: pass
    
    def stop(self):
        logger.info("🛑 Stopping Classification Service...")
        self.is_running = False
        if self.channel and hasattr(self.channel, 'stop_consuming'):
            self.channel.stop_consuming()
        self.executor.shutdown(wait=True, timeout=30)
        logger.info("✓ Classification Service stopped")
    
    def cleanup(self):
        if self.connection and hasattr(self.connection, 'is_open') and self.connection.is_open:
            try: self.connection.close()
            except: pass

def main():
    try:
        service = PriorityClassificationService()
        service.start()
    except Exception as e:
        logger.error(f"Service failed to start: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()