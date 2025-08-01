import time
import pika
import json
import os
import google.generativeai as genai
from datetime import datetime, UTC
from dotenv import load_dotenv
import re
import traceback

load_dotenv()

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'classification_queue'
PUBLISH_QUEUE_NAME = 'routing_queue'
STATUS_QUEUE_NAME = 'document_status_queue'

# VIP-Specific Configurations
VIP_ALERT_THRESHOLD = os.getenv("VIP_ALERT_THRESHOLD", "medium").lower()

# Custom VIP Rules
CUSTOM_VIP_KEYWORDS = [
    'chief executive officer', 'ceo', 'director', 'vice president', 'vp',
    'senior manager', 'head of', 'board member', 'hr director', 'legal counsel'
]

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

# --- DOCUMENT TYPE PATTERNS ---
DOCUMENT_PATTERNS = {
    'CONTRACT': {
        'keywords': [
            'agreement', 'contract', 'terms and conditions', 'parties agree',
            'party of the first part', 'party of the second part', 'whereas',
            'hereby agree', 'effective date', 'contract period', 'termination clause',
            'breach of contract', 'legal obligations', 'binding agreement',
            'witnesseth', 'consideration', 'covenant', 'indemnify'
        ],
        'patterns': [
            r'this\s+(?:agreement|contract)',
            r'party\s+(?:of\s+the\s+)?(?:first|second)\s+part',
            r'effective\s+(?:as\s+of|date)',
            r'terms?\s+(?:and\s+)?conditions?',
            r'breach\s+of\s+(?:this\s+)?(?:agreement|contract)',
            r'hereby\s+agree'
        ],
        'structure_indicators': ['sections', 'clauses', 'definitions', 'schedule a', 'exhibit']
    },
    'INVOICE': {
        'keywords': [
            'invoice', 'bill to', 'ship to', 'payment due', 'total amount',
            'invoice number', 'invoice date', 'due date', 'amount due',
            'subtotal', 'tax', 'discount', 'payment terms', 'remit to',
            'account number', 'po number', 'purchase order'
        ],
        'patterns': [
            r'invoice\s+(?:#|number|no\.?)\s*:?\s*\d+',
            r'bill\s+to\s*:',
            r'payment\s+due\s*:',
            r'total\s+(?:amount\s+)?due\s*:?\s*\$',
            r'invoice\s+date\s*:',
            r'due\s+date\s*:'
        ],
        'structure_indicators': ['quantity', 'description', 'unit price', 'amount']
    },
    'RESUME': {
        'keywords': [
            'education', 'experience', 'skills', 'qualifications', 'employment',
            'work history', 'career objective', 'professional summary',
            'references', 'certifications', 'achievements', 'bachelor',
            'master', 'degree', 'university', 'college', 'gpa'
        ],
        'patterns': [
            r'(?:work\s+)?experience\s*:',
            r'education\s*:',
            r'skills\s*:',
            r'(?:career\s+)?objective\s*:',
            r'references\s*:',
            r'(?:bachelor|master)(?:\'?s)?\s+(?:of\s+)?(?:arts|science)',
            r'\b(?:19|20)\d{2}\s*[-–]\s*(?:present|current|\d{4})'
        ],
        'structure_indicators': ['objective', 'summary', 'experience', 'education', 'skills']
    },
    'REPORT': {
        'keywords': [
            'executive summary', 'introduction', 'methodology', 'findings',
            'conclusions', 'recommendations', 'analysis', 'results',
            'background', 'scope', 'objectives', 'discussion', 'appendix',
            'quarterly report', 'annual report', 'status report'
        ],
        'patterns': [
            r'executive\s+summary\s*:?',
            r'(?:table\s+of\s+)?contents\s*:?',
            r'(?:section|chapter)\s+\d+',
            r'findings\s+(?:and\s+)?(?:results\s*)?:?',
            r'conclusions?\s+(?:and\s+)?(?:recommendations\s*)?:?',
            r'methodology\s*:?'
        ],
        'structure_indicators': ['abstract', 'introduction', 'methodology', 'results', 'conclusion']
    },
    'MEMO': {
        'keywords': [
            'memorandum', 'memo', 'from:', 'to:', 'date:', 'subject:', 're:',
            'urgent', 'for your information', 'please note', 'attention',
            'internal communication', 'company policy', 'announcement'
        ],
        'patterns': [
            r'(?:memo|memorandum)\s*(?:to|for)\s*:',
            r'from\s*:\s*[^\n]+',
            r'to\s*:\s*[^\n]+',
            r'date\s*:\s*[^\n]+',
            r'(?:subject|re)\s*:\s*[^\n]+',
            r'urgent\s*:?\s*(?:memo|memorandum|communication)'
        ],
        'structure_indicators': ['header', 'to', 'from', 'date', 'subject', 'body']
    },
    'AGREEMENT': {
        'keywords': [
            'agreement', 'mutual understanding', 'parties', 'terms',
            'service agreement', 'license agreement', 'partnership agreement',
            'non-disclosure agreement', 'confidentiality agreement', 'mou',
            'memorandum of understanding', 'letter of intent'
        ],
        'patterns': [
            r'(?:service|license|partnership|confidentiality)\s+agreement',
            r'non-disclosure\s+agreement',
            r'memorandum\s+of\s+understanding',
            r'letter\s+of\s+intent',
            r'mutual\s+(?:understanding|agreement)',
            r'parties\s+(?:hereby\s+)?agree'
        ],
        'structure_indicators': ['preamble', 'definitions', 'terms', 'conditions', 'signatures']
    },
    'GRIEVANCE': {
        'keywords': [
            'complaint', 'grievance', 'formal complaint', 'violation',
            'harassment', 'discrimination', 'misconduct', 'dispute',
            'unfair treatment', 'workplace issue', 'hr complaint',
            'disciplinary action', 'appeal', 'incident report'
        ],
        'patterns': [
            r'formal\s+complaint',
            r'grievance\s+(?:report|filing)',
            r'incident\s+(?:report|number)',
            r'complaint\s+(?:against|regarding)',
            r'violation\s+of\s+(?:policy|procedure)',
            r'harassment\s+(?:complaint|allegation)'
        ],
        'structure_indicators': ['complainant', 'respondent', 'incident', 'witness', 'resolution']
    },
    'ID_PROOF': {
        'keywords': [
            'driver license', 'passport', 'identification', 'id card',
            'social security', 'birth certificate', 'voter id',
            'government issued', 'photo id', 'identity document',
            'citizenship', 'visa', 'green card', 'permit'
        ],
        'patterns': [
            r'driver\s*(?:\'?s)?\s*licen[sc]e',
            r'passport\s+(?:number|no\.?)',
            r'social\s+security\s+(?:number|no\.?)',
            r'birth\s+certificate',
            r'identification\s+(?:card|number)',
            r'government\s+issued\s+id'
        ],
        'structure_indicators': ['photo', 'expiration', 'issued by', 'document number', 'signature']
    }
}

# --- IMPROVED CONNECTION MANAGEMENT ---
class RabbitMQManager:
    def __init__(self, host):
        self.host = host
        
    def get_fresh_connection(self):
        """Get a fresh connection for one-time operations"""
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.host,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
            )
            return connection
        except Exception as e:
            print(f"[!] Failed to create fresh connection: {e}")
            return None

rabbitmq_manager = RabbitMQManager(RABBITMQ_HOST)

# --- HELPER & CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None, is_vip: bool = False, vip_level: str = None):
    """Publish status update with improved error handling"""
    if details is None: 
        details = {}
    
    status_message = {
        "document_id": doc_id, 
        "status": status, 
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details, 
        "doc_type": doc_type, 
        "confidence": confidence,
        "is_vip": is_vip, 
        "vip_level": vip_level
    }
    
    connection = None
    try:
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

def classify_with_rule_based(text: str) -> dict:
    """Enhanced rule-based classification with pattern matching"""
    if not text or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "analysis": {}}
    
    text_lower = text.lower()
    text_lines = text.split('\n')
    
    scores = {}
    
    for doc_type, patterns in DOCUMENT_PATTERNS.items():
        score = 0
        keyword_count = 0
        pattern_count = 0
        structure_count = 0
        
        # Check keywords
        for keyword in patterns['keywords']:
            if keyword.lower() in text_lower:
                keyword_count += 1
                score += 1
        
        # Check regex patterns
        for pattern in patterns['patterns']:
            try:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    pattern_count += 1
                    score += 2
            except re.error:
                continue  # Skip invalid regex patterns
        
        # Check structure indicators
        for indicator in patterns['structure_indicators']:
            if indicator.lower() in text_lower:
                structure_count += 1
                score += 1.5
        
        # Special handling for contract vs memo confusion
        if doc_type == 'CONTRACT':
            contract_phrases = ['party of the first part', 'party of the second part', 
                              'whereas', 'witnesseth', 'consideration', 'covenant']
            for phrase in contract_phrases:
                if phrase in text_lower:
                    score += 3
        
        elif doc_type == 'MEMO':
            memo_header_found = False
            for line in text_lines[:10]:
                line_lower = line.lower().strip()
                if any(header in line_lower for header in ['from:', 'to:', 'date:', 'subject:', 're:']):
                    memo_header_found = True
                    break
            
            if memo_header_found:
                score += 4
            
            if any(phrase in text_lower for phrase in ['agreement', 'contract', 'parties agree']):
                score -= 2
        
        # Calculate confidence
        total_possible = len(patterns['keywords']) + len(patterns['patterns']) * 2 + len(patterns['structure_indicators']) * 1.5
        confidence = min(score / max(total_possible * 0.3, 1), 1.0)
        
        scores[doc_type] = {
            'score': score,
            'confidence': confidence,
            'keyword_count': keyword_count,
            'pattern_count': pattern_count,
            'structure_count': structure_count
        }
    
    # Find the best match
    if scores:
        best_type = max(scores.keys(), key=lambda k: scores[k]['score'])
        best_score = scores[best_type]
        
        if best_score['score'] < 2:
            return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "analysis": scores}
        
        return {
            "doc_type": best_type,
            "confidence_score": best_score['confidence'],
            "analysis": scores
        }
    
    return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "analysis": {}}

def classify_with_llm(text: str) -> dict:
    """Classify document using LLM with better error handling"""
    if not model or not text or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
    
    print("-> Using Gemini for document classification...")
    try:
        prompt = f"""
        Analyze the following document text and classify it into ONE of these specific categories:
        - REPORT: Research reports, status reports, analysis documents, quarterly/annual reports
        - RESUME: CV, curriculum vitae, job application documents, professional profiles
        - MEMO: Internal communications, memorandums, company announcements, urgent notices
        - INVOICE: Bills, invoices, payment requests, financial statements
        - AGREEMENT: Service agreements, partnerships, MOUs, license agreements (general agreements)
        - CONTRACT: Legal contracts with binding terms, formal legal documents with parties and clauses
        - GRIEVANCE: Complaints, formal grievances, incident reports, HR complaints
        - ID_PROOF: Government IDs, driver's licenses, passports, identification documents

        IMPORTANT DISTINCTIONS:
        - CONTRACT vs MEMO: Contracts have legal binding language, parties, clauses. Memos are internal communications with To/From/Date/Subject format.
        - CONTRACT vs AGREEMENT: Contracts are formal legal documents. Agreements can be less formal mutual understandings.
        - If the document has "URGENT", "From:", "To:", "Date:", "Subject:" structure, it's likely a MEMO.
        - If it doesn't clearly fit any category, classify as "HUMAN_REVIEW_NEEDED".

        Return ONLY a valid JSON object:
        {{
            "doc_type": "CATEGORY_NAME",
            "confidence_score": 0.95,
            "reasoning": "Brief explanation of classification"
        }}

        Document text:
        ---
        {text[:2000]}  # Limit text to avoid token limits
        ---
        """
        
        response = model.generate_content(prompt)
        json_response_text = response.text.strip()
        
        # Clean up response
        if json_response_text.startswith('```'):
            json_response_text = json_response_text[3:]
        if json_response_text.endswith('```'):
            json_response_text = json_response_text[:-3]
        if json_response_text.startswith('json'):
            json_response_text = json_response_text[4:]
        
        result = json.loads(json_response_text)
        doc_type = result.get('doc_type', 'UNKNOWN')
        confidence = result.get('confidence_score', 0.0)
        
        print(f"-> Gemini classified as '{doc_type}' with confidence {confidence}")
        return result
        
    except Exception as e:
        print(f"-> Gemini Classification Error: {e}")
        print(f"-> Gemini error traceback: {traceback.format_exc()}")
        return {"doc_type": "LLM_ERROR", "confidence_score": 0.0}

def hybrid_classify(text: str) -> dict:
    """Combine rule-based and LLM classification for better accuracy"""
    if not text or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "method": "no_text"}
    
    # First try rule-based classification
    rule_result = classify_with_rule_based(text)
    rule_confidence = rule_result.get('confidence_score', 0.0)
    rule_type = rule_result.get('doc_type', 'UNKNOWN')
    
    print(f"-> Rule-based: {rule_type} (confidence: {rule_confidence:.2f})")
    
    # If rule-based is confident, use it
    if rule_confidence >= 0.8 and rule_type != 'UNKNOWN':
        return {
            "doc_type": rule_type,
            "confidence_score": rule_confidence,
            "method": "rule_based"
        }
    
    # Otherwise, use LLM
    llm_result = classify_with_llm(text)
    llm_confidence = llm_result.get('confidence_score', 0.0)
    llm_type = llm_result.get('doc_type', 'UNKNOWN')
    
    # If both methods agree, boost confidence
    if rule_type == llm_type and rule_type != 'UNKNOWN':
        combined_confidence = min((rule_confidence + llm_confidence) / 1.5, 1.0)
        return {
            "doc_type": rule_type,
            "confidence_score": combined_confidence,
            "method": "hybrid_agreement"
        }
    
    # If LLM has higher confidence, use it
    if llm_confidence > rule_confidence:
        return {
            "doc_type": llm_type,
            "confidence_score": llm_confidence,
            "method": "llm_primary"
        }
    
    # Default to rule-based if available
    if rule_type != 'UNKNOWN':
        return {
            "doc_type": rule_type,
            "confidence_score": rule_confidence,
            "method": "rule_fallback"
        }
    
    return {
        "doc_type": "HUMAN_REVIEW_NEEDED",
        "confidence_score": 0.0,
        "method": "uncertain"
    }

def determine_vip_status(sender: str, extracted_text: str, priority_content: dict) -> tuple:
    """Determine VIP status with improved error handling"""
    is_vip = False
    vip_level = "NONE"

    try:
        # Safely handle None values
        sender = sender or ""
        extracted_text = extracted_text or ""
        priority_content = priority_content or {}

        # 1. Domain-Based VIP Detection
        if sender:
            sender_email = sender.split('<')[-1].replace('>', '').strip().lower()
            for domain in CUSTOM_VIP_DOMAINS:
                if domain in sender_email:
                    is_vip = True
                    vip_level = "HIGH"
                    print(f"-> Detected VIP (HIGH) based on sender domain: {domain}")
                    return True, vip_level

        # 2. Keyword Analysis
        lower_sender = sender.lower()
        lower_extracted_text = extracted_text.lower()
        
        # Check for HIGH VIP keywords first
        high_vip_keywords = ['ceo', 'chief executive officer', 'board member', 'director', 'founder']
        for keyword in high_vip_keywords:
            if keyword in lower_sender or keyword in lower_extracted_text:
                is_vip = True
                vip_level = "HIGH"
                print(f"-> Detected VIP (HIGH) based on keyword: {keyword}")
                return True, vip_level

        # Check for MEDIUM VIP keywords
        medium_vip_keywords = ['vp', 'vice president', 'senior manager', 'department head', 'legal counsel', 'hr director']
        for keyword in medium_vip_keywords:
            if keyword in lower_sender or keyword in lower_extracted_text:
                is_vip = True
                vip_level = "MEDIUM"
                print(f"-> Detected VIP (MEDIUM) based on keyword: {keyword}")
                return True, vip_level
                
        # 3. AI-Powered Context Analysis for Urgency
        urgency_level = priority_content.get("urgency_level", "low")
        if isinstance(urgency_level, str) and urgency_level.lower() == "high" and not is_vip:
            is_vip = True
            vip_level = "MEDIUM"
            print(f"-> Detected VIP (MEDIUM) based on high urgency content.")

        return is_vip, vip_level
        
    except Exception as e:
        print(f"[!] Error in VIP determination: {e}")
        return False, "NONE"

def validate_message_structure(message: dict) -> tuple:
    """Validate message structure and extract required fields safely"""
    try:
        if not isinstance(message, dict):
            return False, "Message is not a dictionary", None, None, None, None, None, None
        
        # Extract required fields with defaults
        filename = message.get('filename', 'unknown_file')
        document_id = message.get('document_id', 'unknown_id')
        sender = message.get('sender', '')
        extracted_text = message.get('extracted_text', '')
        priority_content = message.get('priority_content', {})
        entities = message.get('entities', {})
        summary = message.get('summary', 'No summary available.')
        
        # Validate that we have at least some text to work with
        if not extracted_text or not extracted_text.strip():
            return False, "No extracted text available", filename, document_id, sender, extracted_text, priority_content, entities
        
        return True, "Valid", filename, document_id, sender, extracted_text, priority_content, entities
        
    except Exception as e:
        return False, f"Error validating message: {e}", None, None, None, None, None, None

# --- MAIN AGENT LOGIC ---
def process_message(ch, method, properties, body):
    """Process individual message with comprehensive error handling"""
    document_id = "unknown_id"
    filename = "unknown_file"
    
    try:
        # Step 1: Parse JSON message
        try:
            message = json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[e] FAILED to parse JSON message: {e}")
            print(f"[e] Raw message body: {body[:200]}...")  # Show first 200 chars
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Don't requeue malformed JSON
            return
        
        # Step 2: Validate message structure
        is_valid, error_msg, filename, document_id, sender, extracted_text, priority_content, entities = validate_message_structure(message)
        
        if not is_valid:
            print(f"[e] Invalid message structure for '{filename}' (Doc ID: {document_id}): {error_msg}")
            publish_status_update(
                doc_id=document_id,
                status="Classification Failed",
                details={"error": f"Invalid message structure: {error_msg}"}
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Don't requeue invalid messages
            return

        print(f"\n[x] Received '{filename}' (Doc ID: {document_id}) for classification.")

        # Step 3: Determine VIP status
        is_vip, vip_level = determine_vip_status(sender, extracted_text, priority_content)
        if is_vip:
            print(f"-> Document identified as VIP with level: {vip_level}")
        
        # Step 4: Perform classification
        classification_result = hybrid_classify(extracted_text)
        doc_type = classification_result.get('doc_type', 'UNKNOWN')
        confidence = classification_result.get('confidence_score', 0.0)
        classification_method = classification_result.get('method', 'unknown')
        
        print(f"-> Classification: {doc_type} (confidence: {confidence:.2f}, method: {classification_method})")

        # Step 5: Apply confidence thresholds
        VALID_TYPES = ['REPORT', 'RESUME', 'MEMO', 'INVOICE', 'AGREEMENT', 'CONTRACT', 'GRIEVANCE', 'ID_PROOF']
        
        if doc_type not in VALID_TYPES or doc_type in ['UNKNOWN', 'LLM_ERROR', 'HUMAN_REVIEW_NEEDED']:
            print(f"-> Document type '{doc_type}' requires human review.")
            doc_type = "HUMAN_REVIEW_NEEDED"
            confidence = 0.0
        elif confidence < 0.75:
            print(f"-> Confidence ({confidence:.2f}) is below threshold. Flagging for human review.")
            doc_type = "HUMAN_REVIEW_NEEDED"
            confidence = 0.0
        elif is_vip and confidence < 0.85:
            print(f"-> VIP document confidence ({confidence:.2f}) is below VIP threshold. Flagging for human review.")
            doc_type = "HUMAN_REVIEW_NEEDED"
            confidence = 0.0

        # Step 6: Publish status update
        publish_status_update(
            doc_id=document_id,
            status="Classified",
            doc_type=doc_type,
            confidence=confidence,
            is_vip=is_vip,
            vip_level=vip_level
        )

        # Step 7: Prepare and send message to router
        router_message = {
            'document_id': document_id,
            'filename': filename,
            'doc_type': doc_type,
            'confidence': confidence,
            'entities': entities,
            'summary': message.get('summary', 'No summary available.'),
            'priority_content': priority_content,
            'is_vip': is_vip,
            'vip_level': vip_level,
            'classification_method': classification_method
        }
        
        # Step 8: Publish to router with retry logic
        max_publish_retries = 3
        publish_success = False
        
        for attempt in range(max_publish_retries):
            try:
                connection = rabbitmq_manager.get_fresh_connection()
                if not connection:
                    raise Exception("Failed to get fresh connection for publishing")
                
                channel = connection.channel()
                channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                channel.basic_publish(
                    exchange='', 
                    routing_key=PUBLISH_QUEUE_NAME, 
                    body=json.dumps(router_message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                connection.close()
                
                print(f"[>] Sent '{filename}' (Type: {doc_type}, VIP: {is_vip}) for routing.")
                publish_success = True
                break
                
            except Exception as pub_error:
                print(f"[!] Publish attempt {attempt + 1} failed: {pub_error}")
                if attempt < max_publish_retries - 1:
                    time.sleep(1)  # Brief delay before retry
                else:
                    raise Exception(f"Failed to publish after {max_publish_retries} attempts: {pub_error}")

        # Step 9: Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print(f"-> Successfully processed and acknowledged '{filename}'.")

    except Exception as e:
        print(f"[e] FAILED to process '{filename}': {e}")
        print(f"[e] Error traceback: {traceback.format_exc()}")
        
        publish_status_update(
            doc_id=document_id,
            status="Classification Failed",
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
            print('[*] Successfully connected to RabbitMQ.')
        except pika.exceptions.AMQPConnectionError:
            print("[!] RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

    try:
        channel = connection.channel()
        channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
        channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
        channel.basic_qos(prefetch_count=1)  # Process one message at a time
        
        print('[*] Enhanced AI-Powered Classifier Agent waiting for messages. To exit press CTRL+C')

        channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=process_message)
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print('[!] Interrupted by user')
        if connection and connection.is_open:
            channel.stop_consuming()
            connection.close()
    except Exception as e:
        print(f"[!!!] Consumer error: {e}")
        print(f"[!!!] Consumer error traceback: {traceback.format_exc()}")
    finally:
        if connection and connection.is_open:
            connection.close()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        exit(0)
    except Exception as e:
        print(f"[!!!] Classifier Agent crashed: {e}")
        print(f"[!!!] Crash traceback: {traceback.format_exc()}")
        exit(1)