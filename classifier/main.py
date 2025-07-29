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

# VIP-Specific Configurations (Add these to your .env file)
VIP_ALERT_THRESHOLD = os.getenv("VIP_ALERT_THRESHOLD", "medium").lower() # 'high', 'medium', 'low'

# Custom VIP Rules
CUSTOM_VIP_KEYWORDS = [
    'chief executive officer', 'ceo', 'director', 'vice president', 'vp',
    'senior manager', 'head of', 'board member', 'hr director', 'legal counsel'
] # Added 'hr director', 'legal counsel' as common VIP indicators

CUSTOM_VIP_DOMAINS = [
    'board@yourcompany.com', 'executives@yourcompany.com', 'leadership@yourcompany.com'
]

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("[i] Google Gemini client initialized for Classifier.")
except Exception as e:
    print(f"[e] Classifier's Gemini client failed to initialize: {e}")
    model = None

# --- HELPER & CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None, is_vip: bool = False, vip_level: str = None):
    if details is None: details = {}
    status_message = {
        "document_id": doc_id, "status": status, "timestamp": datetime.now(UTC).isoformat(),
        "details": details, "doc_type": doc_type, "confidence": confidence,
        "is_vip": is_vip, "vip_level": vip_level # Added VIP fields
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
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
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
        return {"doc_type": "LLM_ERROR", "confidence_score": 0.0}

def determine_vip_status(sender: str, extracted_text: str, priority_content: dict) -> (bool, str):
    is_vip = False
    vip_level = "NONE" # Default to NONE

    # 1. Domain-Based VIP Detection
    if sender:
        sender_email = sender.split('<')[-1].replace('>', '').strip().lower()
        for domain in CUSTOM_VIP_DOMAINS:
            if domain in sender_email:
                is_vip = True
                vip_level = "HIGH" # Domains like 'executives@' are typically high priority
                print(f"  -> Detected VIP (HIGH) based on sender domain: {domain}")
                break
        if is_vip: return True, vip_level

    # 2. Keyword Analysis (in sender, subject, or extracted text)
    lower_sender = sender.lower() if sender else ""
    lower_extracted_text = extracted_text.lower()
    
    # Check for HIGH VIP keywords first
    high_vip_keywords = ['ceo', 'chief executive officer', 'board member', 'director', 'founder']
    for keyword in high_vip_keywords:
        if keyword in lower_sender or keyword in lower_extracted_text:
            is_vip = True
            vip_level = "HIGH"
            print(f"  -> Detected VIP (HIGH) based on keyword: {keyword}")
            return True, vip_level

    # Check for MEDIUM VIP keywords
    medium_vip_keywords = ['vp', 'vice president', 'senior manager', 'department head', 'legal counsel', 'hr director']
    for keyword in medium_vip_keywords:
        if keyword in lower_sender or keyword in lower_extracted_text:
            is_vip = True
            vip_level = "MEDIUM"
            print(f"  -> Detected VIP (MEDIUM) based on keyword: {keyword}")
            return True, vip_level
            
    # 3. AI-Powered Context Analysis for Urgency (can imply VIP status for general documents)
    # This acts as a fallback or enhancement for urgency-based VIP detection
    urgency_level = priority_content.get("urgency_level", "low").lower()
    if urgency_level == "high" and not is_vip: # If not already marked VIP, and content is urgent
        is_vip = True
        vip_level = "MEDIUM" # Set to medium if only urgency triggers it
        print(f"  -> Detected VIP (MEDIUM) based on high urgency content.")

    return is_vip, vip_level

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
        sender = message.get('sender', '') # Get sender information
        extracted_text = message.get('extracted_text', '')
        priority_content = message.get('priority_content', {}) # Get priority content from Extractor
        
        print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for classification.")

        try:
            # Determine VIP status and level
            is_vip, vip_level = determine_vip_status(sender, extracted_text, priority_content)
            if is_vip:
                print(f"  -> Document identified as VIP with level: {vip_level}")
            
            # Perform document classification
            doc_type = None
            confidence = 1.0
            
            invoice_keywords = ['invoice', 'bill to', 'payment due', 'total amount']
            if priority_content.get('financial_commitments') and any(keyword in extracted_text.lower() for keyword in invoice_keywords):
                doc_type = "INVOICE"
                print("  -> Classified as INVOICE based on financial commitments and keywords.")
            
            if not doc_type:
                llm_result = classify_with_llm(extracted_text)
                doc_type = llm_result.get('doc_type', 'LLM_ERROR')
                confidence = llm_result.get('confidence_score', 0.0)

            # Apply confidence threshold
            if confidence < 0.85 and not is_vip: # Only flag for human review if not already VIP
                print(f"  -> Confidence ({confidence:.2f}) is low. Flagging for human review.")
                doc_type = "NEEDS_HUMAN_REVIEW"
            elif confidence < 0.70 and is_vip: # Even VIPs might need human review if confidence is very low
                 print(f"  -> VIP document confidence ({confidence:.2f}) is very low. Flagging for human review.")
                 doc_type = "NEEDS_HUMAN_REVIEW"

            # Publish status update with VIP info
            publish_status_update(
                doc_id=document_id,
                status="Classified",
                doc_type=doc_type,
                confidence=confidence,
                is_vip=is_vip,
                vip_level=vip_level
            )

            # Prepare message for router with VIP info
            router_message = {
                'document_id': document_id,
                'filename': filename,
                'doc_type': doc_type,
                'confidence': confidence,
                'entities': message.get('entities', {}), # Keep existing entities
                'summary': message.get('summary', 'No summary available.'), # Pass summary
                'priority_content': priority_content, # Pass priority content
                'is_vip': is_vip, # Pass VIP status
                'vip_level': vip_level # Pass VIP level
            }
            
            publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            publish_channel = publish_connection.channel()
            publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
            publish_channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, body=json.dumps(router_message))
            publish_connection.close()
            
            print(f" [>] Sent '{filename}' (Type: {doc_type}, VIP: {is_vip}) for routing.")
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