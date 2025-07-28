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
from datetime import datetime

# --- CONFIGURATION ---
RABBITMQ_HOST = '127.0.0.1'
CONSUME_QUEUE_NAME = 'doc_received_queue'
PUBLISH_QUEUE_NAME = 'classification_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Extractor.")
except Exception as e:
    print(f"[e] Extractor's Gemini client failed to initialize: {e}")
    model = None

# --- HELPER & CORE FUNCTIONS (Unchanged) ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None):
    if details is None: details = {}
    status_message = {
        "document_id": doc_id, "status": status, "timestamp": datetime.utcnow().isoformat() + "Z", # Add "Z" for UTC,
        "details": details, "doc_type": doc_type, "confidence": confidence
    }
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, body=json.dumps(status_message))
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def extract_text_from_document(content_bytes: bytes, content_type: str) -> str:
    # ... (This function is unchanged)
    text = ""
    try:
        if 'pdf' in content_type:
            images = convert_from_bytes(content_bytes)
            for i, image in enumerate(images):
                print(f"  -> Processing page {i+1} of PDF...")
                text += pytesseract.image_to_string(image) + '\n'
        elif 'image' in content_type:
            image = Image.open(io.BytesIO(content_bytes))
            text = pytesseract.image_to_string(image)
        elif 'text' in content_type:
            text = content_bytes.decode('utf-8', errors='ignore')
        else:
            return f"Unsupported content type: {content_type}"
        print(f"  -> Successfully extracted {len(text)} characters via OCR.")
        return text
    except Exception as e:
        return f"Error during OCR: {e}"

def cleanup_and_extract_entities_with_llm(text: str) -> dict:
    # ... (This function is unchanged)
    if not model: return {"cleaned_text": text, "entities": {"error": "Gemini client not available."}}
    if len(text.strip()) < 10: return {"cleaned_text": text, "entities": {}}
    print("  -> Sending text to Gemini for cleanup and entity extraction...")
    try:
        prompt = f"""
        Analyze the following text... (rest of prompt is the same)
        """
        response = model.generate_content(prompt)
        try:
            json_response_text = response.text.strip().replace('```json', '').replace('```', '')
            result = json.loads(json_response_text)
        except json.JSONDecodeError:
            return {"cleaned_text": text, "entities": {"error": "LLM did not return valid JSON."}}
        print("  -> Successfully processed text with Gemini.")
        return result
    except Exception as e:
        return {"cleaned_text": text, "entities": {"error": f"LLM processing failed: {e}"}}

# --- MAIN AGENT LOGIC ---
def main():
    connection = None
    # Loop until a connection is successfully established
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Successfully connected to RabbitMQ.')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    print(' [*] AI-Powered Extractor Agent waiting for messages. To exit press CTRL+C')


    def callback(ch, method, properties, body):
        message = json.loads(body)
        filename = message['filename']
        document_id = message.get('document_id', 'unknown_id')
        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for extraction.")

        try:
            file_content_bytes = base64.b64decode(message['file_content'])
            raw_text = extract_text_from_document(file_content_bytes, message['content_type'])
            processed_data = cleanup_and_extract_entities_with_llm(raw_text)
            
            classifier_message = {
                'document_id': document_id, 'filename': filename,
                'context': message.get('context', ''),
                'extracted_text': processed_data.get('cleaned_text', raw_text),
                'entities': processed_data.get('entities', {})
            }
            
            publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            publish_channel = publish_connection.channel()
            publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
            publish_channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, body=json.dumps(classifier_message))
            publish_connection.close()
            print(f" [>] Sent cleaned text and entities from '{filename}' for classification.")

            # --- BUG FIX: Include extracted_text and entities in the status update ---
            publish_status_update(
                doc_id=document_id,
                status="Extracted",
                details={
                    "chars_extracted": len(raw_text),
                    "extracted_text": processed_data.get('cleaned_text', raw_text),
                    "entities": processed_data.get('entities', {})
                }
            )

            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"  -> Successfully processed and acknowledged '{filename}'.")

        except Exception as e:
            print(f" [e] FAILED to process '{filename}': {e}")
            publish_status_update(doc_id=document_id, status="Extraction Failed", details={"error": str(e)})
    
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted'); exit(0)