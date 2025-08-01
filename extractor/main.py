# extractor/main.py - Improved version with better connection management
import time
import pika
import json
import base64
import pytesseract
import os
import google.generativeai as genai
from pdf2image import convert_from_bytes
from PIL import Image
import io
from datetime import datetime, UTC
from dotenv import load_dotenv
import docx
import traceback

load_dotenv()

# --- ROBUST TESSERACT CONFIGURATION ---
tesseract_path = os.getenv("TESSERACT_CMD_PATH")
if tesseract_path and os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    print("[i] Tesseract path configured from .env file.")
else:
    print("[!!!] WARNING: TESSERACT_CMD_PATH not found or invalid. OCR will likely fail on Windows.")

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'doc_received_queue'
PUBLISH_QUEUE_NAME = 'classification_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

# Configure Gemini
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Extractor.")
except Exception as e:
    print(f"[e] Extractor's Gemini client failed to initialize: {e}")
    model = None

# --- IMPROVED CONNECTION MANAGEMENT ---
class RabbitMQManager:
    def __init__(self, host):
        self.host = host
        self.publish_connection = None
        self.publish_channel = None
        
    def get_fresh_connection(self):
        """Get a fresh connection for one-time operations like status updates"""
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    heartbeat=600,  # 10 minutes
                    blocked_connection_timeout=300,  # 5 minutes
                )
            )
            return connection
        except Exception as e:
            print(f"[!] Failed to create fresh connection: {e}")
            return None
    
    def get_publish_channel(self):
        """Get or create a publishing channel with better error handling"""
        # Check if current channel is healthy
        if (self.publish_channel and 
            hasattr(self.publish_channel, 'is_open') and 
            self.publish_channel.is_open and
            self.publish_connection and 
            hasattr(self.publish_connection, 'is_open') and
            self.publish_connection.is_open):
            return self.publish_channel
        
        # Clean up old connections
        self.cleanup_publish_connection()
        
        # Create new connection
        try:
            self.publish_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
            )
            self.publish_channel = self.publish_connection.channel()
            self.publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
            print("[i] Established new RabbitMQ publishing channel.")
            return self.publish_channel
        except Exception as e:
            print(f"[!!!] ERROR: Could not establish RabbitMQ publishing connection: {e}")
            return None
    
    def cleanup_publish_connection(self):
        """Safely cleanup publishing connections"""
        if self.publish_channel:
            try:
                if hasattr(self.publish_channel, 'is_open') and self.publish_channel.is_open:
                    self.publish_channel.close()
            except Exception as e:
                print(f"[!] Error closing publish channel: {e}")
            finally:
                self.publish_channel = None
        
        if self.publish_connection:
            try:
                if hasattr(self.publish_connection, 'is_open') and self.publish_connection.is_open:
                    self.publish_connection.close()
            except Exception as e:
                print(f"[!] Error closing publish connection: {e}")
            finally:
                self.publish_connection = None

# Global RabbitMQ manager
rabbitmq_manager = RabbitMQManager(RABBITMQ_HOST)

# --- HELPER & CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None):
    """Publish status update with improved error handling"""
    if details is None: 
        details = {}
    
    status_message = {
        "document_id": doc_id, 
        "status": status, 
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details, 
        "doc_type": doc_type, 
        "confidence": confidence
    }
    
    connection = None
    try:
        # Use fresh connection for status updates
        connection = rabbitmq_manager.get_fresh_connection()
        if not connection:
            raise Exception("Failed to get fresh connection for status update")
            
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='', 
            routing_key=STATUS_QUEUE_NAME, 
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        print(f"[->] Status update published for Doc ID {doc_id}: {status}")
        
    except Exception as e:
        print(f"[!!!] WARNING: Failed to publish status update for {doc_id}: {e}")
        print(f"[!!!] Status error traceback: {traceback.format_exc()}")
    finally:
        if connection:
            try:
                connection.close()
            except Exception as e:
                print(f"[!] Error closing status connection: {e}")

def extract_text_from_document(content_bytes: bytes, content_type: str, filename: str) -> str:
    """Extract text from document with better error handling"""
    text = ""
    file_extension = os.path.splitext(filename)[1].lower()
    
    try:
        if 'pdf' in content_type:
            poppler_path = os.getenv("POPPLER_PATH")
            if poppler_path and os.path.exists(poppler_path):
                images = convert_from_bytes(content_bytes, poppler_path=poppler_path)
            else:
                images = convert_from_bytes(content_bytes)
            for i, image in enumerate(images):
                text += pytesseract.image_to_string(image) + '\n'
                
        elif 'image' in content_type:
            image = Image.open(io.BytesIO(content_bytes))
            text = pytesseract.image_to_string(image)
            
        elif 'vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type or file_extension == '.docx':
            doc = docx.Document(io.BytesIO(content_bytes))
            full_text = [para.text for para in doc.paragraphs]
            text = '\n'.join(full_text)
            
        elif 'text' in content_type:
            text = content_bytes.decode('utf-8', errors='ignore')
            
        else:
            print(f"-> Unsupported content type: {content_type}. Attempting generic text decode.")
            text = content_bytes.decode('utf-8', errors='ignore')
        
        print(f"-> Successfully extracted {len(text)} characters.")
        return text
        
    except Exception as e:
        print(f"-> Error during text extraction: {e}")
        raise Exception(f"Text extraction failed: {e}")

def analyze_document_content_with_llm(text: str) -> dict:
    """Analyze document content with LLM"""
    if not model: 
        print("-> Gemini client not available. Skipping LLM analysis.")
        return {
            "cleaned_text": text, 
            "summary": "Gemini client not available.", 
            "priority_content": {"error": "Gemini client not available."}
        }
        
    if len(text.strip()) < 10:
        print("-> Text too short for LLM processing, skipping.")
        return {
            "cleaned_text": text, 
            "summary": "Text too short for summarization.", 
            "priority_content": {}
        }
    
    print("-> Sending text to Gemini for cleanup, summarization, and entity extraction...")
    try:
        prompt = f"""
        Analyze the following text extracted from a document.
        1. Clean up any OCR errors, fix formatting, and return the corrected text.
        2. Generate a concise 2-3 sentence summary of the document's content.
        3. Extract key priority content from the text. The entities to extract are:
            - "deadlines": Critical deadlines and dates (e.g., "Payment due: June 1st, 2024")
            - "key_parties": Important people or companies involved (e.g., "Acme Corp (vendor)", "Client Corp (customer)")
            - "financial_commitments": Financial amounts and commitments (e.g., "Total amount: $1,250.75", "$50,000 budget approval")
            - "action_items": Specific actions required (e.g., "Process payment", "Requires signature")
            - "urgency_level": Classify the overall urgency as "high", "medium", or "low" based on the content (e.g., presence of "urgent", short deadlines).

        4. Return the result as a single, valid JSON object with the following keys:
            - "cleaned_text": The corrected and formatted text.
            - "summary": The 2-3 sentence summary.
            - "priority_content": A JSON object containing the extracted priority content. If a category is not found, its value should be an empty list or "N/A" for urgency_level.

        Example output format:
        {{
          "cleaned_text": "The corrected and formatted text goes here...",
          "summary": "This is a concise summary of the document in 2-3 sentences.",
          "priority_content": {{
            "deadlines": ["Payment due: June 1st, 2024"],
            "key_parties": ["Acme Corp (vendor)", "Client Corp (customer)"],
            "financial_commitments": ["Total amount: $1,250.75"],
            "action_items": ["Process payment", "Update accounting records"],
            "urgency_level": "medium"
          }}
        }}

        Here is the text to process:
        ---
        {text}
        ---
        """
        
        response = model.generate_content(prompt)
        json_response_text = response.text.strip().replace('```json', '').replace('```', '')
        result = json.loads(json_response_text)
        print("-> Successfully processed text with Gemini.")
        return result
        
    except Exception as e:
        print(f"-> Gemini Error: {e}")
        return {
            "cleaned_text": text, 
            "summary": f"LLM summarization failed: {e}", 
            "priority_content": {"error": f"LLM processing failed: {e}"}
        }

# --- MAIN AGENT LOGIC ---
def process_message(ch, method, properties, body):
    """Process individual message with comprehensive error handling"""
    message = None
    document_id = 'unknown_id'
    filename = 'unknown_file'
    
    try:
        message = json.loads(body)
        filename = message['filename']
        document_id = message.get('document_id', 'unknown_id')
        sender = message.get('sender', 'N/A') 
        content_type = message.get('content_type', 'application/octet-stream')

        print(f"\n[x] Received '{filename}' (Doc ID: {document_id}) for extraction.")

        # Step 1: Extract text
        file_content_bytes = base64.b64decode(message['file_content'])
        raw_text = extract_text_from_document(file_content_bytes, content_type, filename)
        
        # Step 2: Process with LLM
        processed_data = analyze_document_content_with_llm(raw_text)
        
        # Check if LLM analysis failed
        if ("error" in processed_data.get("priority_content", {}) and 
            processed_data["priority_content"]["error"].startswith("LLM processing failed")):
            raise Exception(f"LLM analysis failed: {processed_data['priority_content']['error']}")

        # Step 3: Prepare message for classifier
        classifier_message = {
            'document_id': document_id,
            'filename': filename,
            'context': message.get('context', ''),
            'extracted_text': processed_data.get('cleaned_text', raw_text),
            'summary': processed_data.get('summary', 'No summary available.'),
            'priority_content': processed_data.get('priority_content', {}),
            'entities': processed_data.get('entities', {}),
            'sender': sender
        }
        
        # Step 4: Publish to classifier with retry logic
        max_publish_retries = 3
        publish_success = False
        
        for attempt in range(max_publish_retries):
            try:
                pub_channel = rabbitmq_manager.get_publish_channel()
                if not pub_channel:
                    raise Exception("Failed to get publishing channel")

                pub_channel.basic_publish(
                    exchange='', 
                    routing_key=PUBLISH_QUEUE_NAME, 
                    body=json.dumps(classifier_message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                
                print(f"[>] Sent cleaned text, summary, and entities from '{filename}' for classification.")
                publish_success = True
                break
                
            except Exception as pub_error:
                print(f"[!] Publish attempt {attempt + 1} failed: {pub_error}")
                if attempt < max_publish_retries - 1:
                    rabbitmq_manager.cleanup_publish_connection()
                    time.sleep(1)  # Brief delay before retry
                else:
                    raise Exception(f"Failed to publish after {max_publish_retries} attempts: {pub_error}")

        # Step 5: Update status
        publish_status_update(
            doc_id=document_id,
            status="Extracted",
            details={
                "chars_extracted": len(raw_text),
                "extracted_text": processed_data.get('cleaned_text', raw_text),
                "summary": processed_data.get('summary', 'No summary available.'),
                "priority_content": processed_data.get('priority_content', {}),
                "entities": processed_data.get('entities', {})
            }
        )

        # Step 6: Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print(f"-> Successfully processed and acknowledged '{filename}'.")

    except Exception as e:
        print(f"[e] FAILED to process '{filename}': {e}")
        print(f"[e] Error traceback: {traceback.format_exc()}")
        
        # Publish failure status
        publish_status_update(
            doc_id=document_id, 
            status="Extraction Failed", 
            details={"error": str(e), "traceback": traceback.format_exc()}
        )
        
        # Don't acknowledge failed messages - they'll be requeued
        print(f"[!] Message not acknowledged - will be requeued for retry")

def main():
    """Main function with improved connection handling"""
    connection = None
    
    # Wait for RabbitMQ to be ready
    while not connection:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
            )
            print('[*] Successfully connected to RabbitMQ (Consumer).')
        except pika.exceptions.AMQPConnectionError:
            print("[!] RabbitMQ (Consumer) not ready. Retrying in 5 seconds...")
            time.sleep(5)

    try:
        channel = connection.channel()
        channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
        channel.basic_qos(prefetch_count=1)  # Process one message at a time
        
        print('[*] AI-Powered Extractor Agent waiting for messages. To exit press CTRL+C')

        channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=process_message)
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print('[!] Interrupted by user')
        channel.stop_consuming()
    except Exception as e:
        print(f"[!!!] Consumer error: {e}")
        print(f"[!!!] Consumer error traceback: {traceback.format_exc()}")
    finally:
        if connection and connection.is_open:
            connection.close()
        rabbitmq_manager.cleanup_publish_connection()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        exit(0)
    except Exception as e:
        print(f"[!!!] Extractor Agent crashed: {e}")
        print(f"[!!!] Crash traceback: {traceback.format_exc()}")
        rabbitmq_manager.cleanup_publish_connection()
        exit(1)