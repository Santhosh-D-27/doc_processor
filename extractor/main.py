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
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, body=json.dumps(status_message))
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def extract_text_from_document(content_bytes: bytes, content_type: str, filename: str) -> str:
    text = ""
    file_extension = os.path.splitext(filename)[1].lower()
    try:
        if 'pdf' in content_type:
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
            return f"Unsupported content type: {content_type}"
        print(f"  -> Successfully extracted {len(text)} characters.")
        return text
    except Exception as e:
        return f"Error during text extraction: {e}"

def cleanup_and_extract_entities_with_llm(text: str) -> dict:
    if not model: return {"cleaned_text": text, "entities": {"error": "Gemini client not available."}}
    if len(text.strip()) < 10:
        print("  -> Text too short for LLM processing, skipping.")
        return {"cleaned_text": text, "entities": {}}
    print("  -> Sending text to Gemini for cleanup and entity extraction...")
    try:
        prompt = f"""
        Analyze the following text extracted from a document.
        1. Clean up any OCR errors, fix formatting, and return the corrected text.
        2. Extract key entities from the text. The entities to extract are: dates, names of people or companies, and invoice amounts or totals.
        3. Return the result as a single, valid JSON object with two keys: "cleaned_text" and "entities".
        4. If the text is nonsensical, garbled, or contains no extractable entities, return the "cleaned_text" as an empty string and the "entities" as an empty JSON object.

        Example output format:
        {{
          "cleaned_text": "The corrected and formatted text goes here...",
          "entities": {{
            "dates": ["2024-05-15"],
            "names": ["John Doe", "Acme Corp"],
            "amounts": ["$1,250.75"]
          }}
        }}

        Here is the text to process:
        ---
        {text}
        ---
        """
        response = model.generate_content(prompt)
        try:
            json_response_text = response.text.strip().replace('```json', '').replace('```', '')
            result = json.loads(json_response_text)
        except json.JSONDecodeError:
            print("  -> Gemini Warning: Model did not return valid JSON. Returning raw text.")
            return {"cleaned_text": text, "entities": {"error": "LLM did not return valid JSON."}}
        print("  -> Successfully processed text with Gemini.")
        return result
    except Exception as e:
        print(f"  -> Gemini Error: {e}")
        return {"cleaned_text": text, "entities": {"error": f"LLM processing failed: {e}"}}

# --- MAIN AGENT LOGIC ---
def main():
    connection = None
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
            # --- Perform all slow processing first ---
            file_content_bytes = base64.b64decode(message['file_content'])
            raw_text = extract_text_from_document(file_content_bytes, message['content_type'], filename)
            processed_data = cleanup_and_extract_entities_with_llm(raw_text)
            
            classifier_message = {
                'document_id': document_id, 'filename': filename,
                'context': message.get('context', ''),
                'extracted_text': processed_data.get('cleaned_text', raw_text),
                'entities': processed_data.get('entities', {})
            }
            
            # --- Use a fresh connection to publish results ---
            publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            publish_channel = publish_connection.channel()
            publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
            publish_channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, body=json.dumps(classifier_message))
            publish_connection.close()
            print(f" [>] Sent cleaned text and entities from '{filename}' for classification.")

            # --- Publish status update ---
            publish_status_update(
                doc_id=document_id,
                status="Extracted",
                details={
                    "chars_extracted": len(raw_text),
                    "extracted_text": processed_data.get('cleaned_text', raw_text),
                    "entities": processed_data.get('entities', {})
                }
            )

            # --- Acknowledge the original message ONLY after all work is complete ---
            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"  -> Successfully processed and acknowledged '{filename}'.")

        except Exception as e:
            print(f" [e] FAILED to process '{filename}': {e}")
            publish_status_update(doc_id=document_id, status="Extraction Failed", details={"error": str(e)})
            # We do not acknowledge the message, so it will be retried by RabbitMQ.
            # In a production system, we would add a dead-letter queue here.
    
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted'); exit(0)
