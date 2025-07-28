# classifier/main.py
import time
import pika
import json
import os
import google.generativeai as genai
from datetime import datetime # ADD THIS

# --- CONFIGURATION ---
RABBITMQ_HOST = '127.0.0.1'
CONSUME_QUEUE_NAME = 'classification_queue'
PUBLISH_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

try:
    # Ensure the API key is set in the environment
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Classifier.")
except Exception as e:
    print(f"[e] Classifier's Gemini client failed to initialize: {e}")
    model = None

# --- CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None):
    """
    Publishes a status update for a document to the status queue.
    """
    if details is None:
        details = {}

    status_message = {
        "document_id": doc_id,
        "status": status,
        "timestamp": datetime.utcnow().isoformat() + "Z", # Add "Z" for UTC, # Use datetime.utcnow() from datetime import datetime
        "details": details,
        "doc_type": doc_type, # Include classified type if available
        "confidence": confidence # Include confidence if available
    }
    
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=STATUS_QUEUE_NAME,
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2) # Make message persistent
        )
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except pika.exceptions.AMQPConnectionError as e:
        print(f" [!!!] WARNING: Could not publish status update for {doc_id} to {STATUS_QUEUE_NAME}. RabbitMQ connection error: {e}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def classify_with_llm(text: str) -> dict:
    """Uses Gemini for zero-shot classification with a confidence score."""
    if not model or not text.strip():
        # Handle cases with no text or unavailable model
        return {"doc_type": "UNKNOWN", "confidence": 0.0}

    print("  -> No clear entities found. Using Gemini for zero-shot classification...")
    try:
        prompt = f"""
        Analyze the following document text and classify it into ONE of the following categories: INVOICE, CONTRACT, RECEIPT, RESUME, MEMO, or OTHER.
        Return the result as a single, valid JSON object with two keys: "doc_type" and "confidence_score".
        The confidence_score should be a float between 0.0 and 1.0, representing how confident you are in the classification.

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
        # Clean up potential markdown formatting
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
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
    print(' [*] AI-Powered Classifier Agent waiting for messages. To exit press CTRL+C')


    def callback(ch, method, properties, body):
        message = json.loads(body)
        filename = message['filename']
        document_id = message.get('document_id', 'unknown_id')
        entities = message.get('entities', {})
        text = message.get('extracted_text', '')

        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for classification.")
        
        doc_type = None
        confidence = 1.0
        
        if entities and entities.get('amounts'):
            doc_type = "INVOICE"
            print("  -> Classified as INVOICE based on found amount entities.")
        
        if not doc_type:
            llm_result = classify_with_llm(text)
            doc_type = llm_result.get('doc_type', 'LLM_ERROR')
            confidence = llm_result.get('confidence_score', 0.0)

        if confidence < 0.85:
            print(f"  -> Confidence ({confidence:.2f}) is low. Flagging for human review.")
            doc_type = "NEEDS_HUMAN_REVIEW"

        # --- Publish status update AFTER successful classification ---
        publish_status_update(
            doc_id=document_id,
            status="Classified",
            doc_type=doc_type,
            confidence=confidence
        )

        # --- Pass document_id to the Router ---
        router_message = {
            'document_id': document_id, # PASS THE ID FORWARD
            'filename': filename,
            'doc_type': doc_type,
            'confidence': confidence,
            'entities': entities
        }

        channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, body=json.dumps(router_message))
        print(f" [>] Sent '{filename}' (Type: {doc_type}) for routing.")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted'); exit(0)