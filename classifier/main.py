# classifier/main.py
import time
import pika
import json
import os
import google.generativeai as genai
from datetime import datetime, UTC
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'classification_queue'
PUBLISH_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Classifier.")
except Exception as e:
    print(f"[e] Classifier's Gemini client failed to initialize: {e}")
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

def classify_with_llm(text: str) -> dict:
    if not model or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence": 0.0}
    print("  -> Using Gemini for zero-shot classification...")
    try:
        prompt = f"""
        Analyze the following document text and classify it into ONE of the following categories: INVOICE, CONTRACT, RECEIPT, RESUME, REPORT, MEMO, or OTHER.
        Return the result as a single, valid JSON object with two keys: "doc_type" and "confidence_score".
        The confidence_score should be a float between 0.0 and 1.0.

        Example output:
        {{
            "doc_type": "INVOICE",
            "confidence_score": 0.98
        }}

        Here is the text to classify:
        ---
        {text}
        ---
        """
        response = model.generate_content(prompt)
        json_response_text = response.text.strip().replace('```json', '').replace('```', '')
        result = json.loads(json_response_text)
        print(f"  -> Gemini classified as '{result.get('doc_type')}' with confidence {result.get('confidence_score')}")
        return result
    except Exception as e:
        print(f"  -> Gemini Classification Error: {e}")
        return {"doc_type": "LLM_ERROR", "confidence": 0.0}

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

    # Declare the main queue without any special arguments
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)

    print(' [*] AI-Powered Classifier Agent waiting for messages. To exit press CTRL+C')

    def callback(ch, method, properties, body):
        message = json.loads(body)
        filename = message['filename']
        document_id = message.get('document_id', 'unknown_id')
        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for classification.")

        try:
            entities = message.get('entities', {})
            text = message.get('extracted_text', '').lower()
            
            doc_type = None
            confidence = 1.0
            
            invoice_keywords = ['invoice', 'bill to', 'payment due', 'total amount']
            if entities.get('amounts') and any(keyword in text for keyword in invoice_keywords):
                doc_type = "INVOICE"
                print("  -> Classified as INVOICE based on amount entities and keywords.")
            
            if not doc_type:
                llm_result = classify_with_llm(text)
                doc_type = llm_result.get('doc_type', 'LLM_ERROR')
                confidence = llm_result.get('confidence_score', 0.0)

            if confidence < 0.85:
                print(f"  -> Confidence ({confidence:.2f}) is low. Flagging for human review.")
                doc_type = "NEEDS_HUMAN_REVIEW"

            publish_status_update(
                doc_id=document_id, status="Classified",
                doc_type=doc_type, confidence=confidence
            )

            router_message = {
                'document_id': document_id, 'filename': filename,
                'doc_type': doc_type, 'confidence': confidence, 'entities': entities
            }
            
            publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            publish_channel = publish_connection.channel()
            publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
            publish_channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, body=json.dumps(router_message))
            publish_connection.close()
            
            print(f" [>] Sent '{filename}' (Type: {doc_type}) for routing.")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            print(f" [e] FAILED to process '{filename}': {e}")
            publish_status_update(
                doc_id=document_id, status="Classification Failed",
                details={"error": str(e)}
            )
            # On failure, we simply don't acknowledge the message.
            # RabbitMQ will automatically re-queue it for a retry.

    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted'); exit(0)
