# extractor/main.py
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

# Global variable for RabbitMQ connection and channel for publishing
# This helps avoid recreating connections for every message, but requires careful handling.
publish_connection = None
publish_channel = None

# Function to establish a publishing connection
def get_publish_channel():
    global publish_connection, publish_channel
    if publish_channel and publish_channel.is_open:
        return publish_channel
    
    # Close existing broken connection if any
    if publish_connection and publish_connection.is_open:
        try:
            publish_connection.close()
        except Exception as e:
            print(f" [!] Error closing old publish connection: {e}")

    try:
        publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        publish_channel = publish_connection.channel()
        publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
        print(" [i] Re-established RabbitMQ publishing channel.")
        return publish_channel
    except pika.exceptions.AMQPConnectionError as e:
        print(f" [!!!] ERROR: Could not establish RabbitMQ publishing connection: {e}")
        return None

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Extractor.")
except Exception as e:
    print(f"[e] Extractor's Gemini client failed to initialize: {e}")
    model = None

# --- HELPER & CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None):
    if details is None: details = {}
    status_message = {
        "document_id": doc_id, "status": status, "timestamp": datetime.now(UTC).isoformat(),
        "details": details, "doc_type": doc_type, "confidence": confidence
    }
    try:
        # Use a new connection for status updates to isolate from main publishing
        status_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        status_channel = status_connection.channel()
        status_channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        status_channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, body=json.dumps(status_message))
        status_connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def extract_text_from_document(content_bytes: bytes, content_type: str, filename: str) -> str:
    text = ""
    file_extension = os.path.splitext(filename)[1].lower()
    try:
        if 'pdf' in content_type:
            # Add poppler path if needed for Windows
            poppler_path = os.getenv("POPPLER_PATH") # Ensure POPPLER_PATH is in your .env
            if poppler_path and os.path.exists(poppler_path):
                images = convert_from_bytes(content_bytes, poppler_path=poppler_path)
            else:
                images = convert_from_bytes(content_bytes) # Fallback if path not set
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
            print(f"  -> Unsupported content type: {content_type}. Attempting generic text decode.")
            text = content_bytes.decode('utf-8', errors='ignore') # Try to decode anyway
        
        print(f"  -> Successfully extracted {len(text)} characters.")
        return text
    except Exception as e:
        print(f"  -> Error during text extraction: {e}")
        return f"ERROR: Text extraction failed: {e}"

def analyze_document_content_with_llm(text: str) -> dict:
    if not model: 
        print("  -> Gemini client not available. Skipping LLM analysis.")
        return {"cleaned_text": text, "summary": "Gemini client not available.", "priority_content": {"error": "Gemini client not available."}}
    if len(text.strip()) < 10:
        print("  -> Text too short for LLM processing, skipping.")
        return {"cleaned_text": text, "summary": "Text too short for summarization.", "priority_content": {}}
    
    print("  -> Sending text to Gemini for cleanup, summarization, and entity extraction...")
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
        print("  -> Successfully processed text with Gemini.")
        return result
    except Exception as e:
        print(f"  -> Gemini Error: {e}")
        # Return a structured error response so downstream agents can handle it
        return {
            "cleaned_text": text, 
            "summary": f"LLM summarization failed: {e}", 
            "priority_content": {"error": f"LLM processing failed: {e}"}
        }

# --- MAIN AGENT LOGIC ---
def main():
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Successfully connected to RabbitMQ (Consumer).')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ (Consumer) not ready. Retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    print(' [*] AI-Powered Extractor Agent waiting for messages. To exit press CTRL+C')

    def callback(ch, method, properties, body):
        message = json.loads(body)
        filename = message['filename']
        document_id = message.get('document_id', 'unknown_id')
        
        # Ensure 'sender' is passed from ingestor to extractor message
        sender = message.get('sender', 'N/A') 
        content_type = message.get('content_type', 'application/octet-stream')

        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for extraction.")

        try:
            file_content_bytes = base64.b64decode(message['file_content'])
            raw_text = extract_text_from_document(file_content_bytes, content_type, filename)
            
            processed_data = analyze_document_content_with_llm(raw_text)
            
            # Check if LLM analysis itself resulted in an error
            if "error" in processed_data.get("priority_content", {}) and processed_data["priority_content"]["error"].startswith("LLM processing failed"):
                raise Exception(f"LLM analysis failed: {processed_data['priority_content']['error']}")

            classifier_message = {
                'document_id': document_id,
                'filename': filename,
                'context': message.get('context', ''),
                'extracted_text': processed_data.get('cleaned_text', raw_text),
                'summary': processed_data.get('summary', 'No summary available.'),
                'priority_content': processed_data.get('priority_content', {}),
                'entities': processed_data.get('entities', {}),
                'sender': sender # Pass sender to classifier
            }
            
            # Get a healthy publishing channel
            pub_channel = get_publish_channel()
            if not pub_channel:
                raise Exception("Failed to get a healthy RabbitMQ publishing channel.")

            pub_channel.basic_publish(
                exchange='', 
                routing_key=PUBLISH_QUEUE_NAME, 
                body=json.dumps(classifier_message),
                properties=pika.BasicProperties(delivery_mode=2) # Ensure persistence
            )
            print(f" [>] Sent cleaned text, summary, and entities from '{filename}' for classification.")

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

            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"  -> Successfully processed and acknowledged '{filename}'.")

        except Exception as e:
            print(f" [e] FAILED to process '{filename}': {e}")
            publish_status_update(
                doc_id=document_id, 
                status="Extraction Failed", 
                details={"error": str(e)}
            )
            # Do NOT acknowledge the message if processing failed.
            # RabbitMQ will re-queue it. Consider a dead-letter queue for production.
            # ch.basic_nack(delivery_tag=method.delivery_tag) # Use nack for explicit negative ack

    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted'); exit(0)
    except Exception as e:
        print(f" [!!!] Extractor Agent crashed: {e}")
        # Attempt to close connection if it exists
        if publish_connection and publish_connection.is_open:
            publish_connection.close()
        exit(1)
