import time
import pika
import json
import os
import google.generativeai as genai
from datetime import datetime, UTC
from dotenv import load_dotenv
import re

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

# --- HELPER & CORE FUNCTIONS ---
def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, confidence: float = None, is_vip: bool = False, vip_level: str = None):
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
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='', 
            routing_key=STATUS_QUEUE_NAME, 
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2)  # Make message persistent
        )
        connection.close()
        print(f" [->] Status update published for Doc ID {doc_id}: {status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def classify_with_rule_based(text: str) -> dict:
    """Enhanced rule-based classification with pattern matching"""
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
            if re.search(pattern, text_lower, re.IGNORECASE):
                pattern_count += 1
                score += 2  # Patterns weighted higher
        
        # Check structure indicators
        for indicator in patterns['structure_indicators']:
            if indicator.lower() in text_lower:
                structure_count += 1
                score += 1.5
        
        # Special handling for contract vs memo confusion
        if doc_type == 'CONTRACT':
            # Look for specific contract language
            contract_phrases = ['party of the first part', 'party of the second part', 
                              'whereas', 'witnesseth', 'consideration', 'covenant']
            for phrase in contract_phrases:
                if phrase in text_lower:
                    score += 3  # Strong contract indicators
        
        elif doc_type == 'MEMO':
            # Check for memo header structure
            memo_header_found = False
            for line in text_lines[:10]:  # Check first 10 lines
                line_lower = line.lower().strip()
                if any(header in line_lower for header in ['from:', 'to:', 'date:', 'subject:', 're:']):
                    memo_header_found = True
                    break
            
            if memo_header_found:
                score += 4  # Strong memo indicator
            
            # Penalize if it has contract-like language
            if any(phrase in text_lower for phrase in ['agreement', 'contract', 'parties agree']):
                score -= 2
        
        # Calculate confidence based on multiple factors
        total_possible = len(patterns['keywords']) + len(patterns['patterns']) * 2 + len(patterns['structure_indicators']) * 1.5
        confidence = min(score / max(total_possible * 0.3, 1), 1.0)  # Cap at 1.0
        
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
        
        # If best score is too low, return unknown
        if best_score['score'] < 2:
            return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "analysis": scores}
        
        return {
            "doc_type": best_type,
            "confidence_score": best_score['confidence'],
            "analysis": scores
        }
    
    return {"doc_type": "UNKNOWN", "confidence_score": 0.0, "analysis": {}}

def classify_with_llm(text: str) -> dict:
    if not model or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
    print("  -> Using Gemini for document classification...")
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
        {text}
        ---
        """
        response = model.generate_content(prompt)
        json_response_text = response.text.strip().replace('``````', '')
        
        # Clean up response
        json_response_text = json_response_text.strip()
        if json_response_text.startswith('```'):
            json_response_text = json_response_text[3:]
        if json_response_text.endswith('```'):
            json_response_text = json_response_text[:-3]
        
        result = json.loads(json_response_text)
        doc_type = result.get('doc_type', 'UNKNOWN')
        confidence = result.get('confidence_score', 0.0)
        
        print(f"  -> Gemini classified as '{doc_type}' with confidence {confidence}")
        return result
    except Exception as e:
        print(f"  -> Gemini Classification Error: {e}")
        return {"doc_type": "LLM_ERROR", "confidence_score": 0.0}

def hybrid_classify(text: str) -> dict:
    """Combine rule-based and LLM classification for better accuracy"""
    
    # First try rule-based classification
    rule_result = classify_with_rule_based(text)
    rule_confidence = rule_result.get('confidence_score', 0.0)
    rule_type = rule_result.get('doc_type', 'UNKNOWN')
    
    print(f"  -> Rule-based: {rule_type} (confidence: {rule_confidence:.2f})")
    
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
    """Fixed return type annotation"""
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
        if is_vip: 
            return True, vip_level

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

    print(' [*] Enhanced AI-Powered Classifier Agent waiting for messages. To exit press CTRL+C')

    def callback(ch, method, properties, body):
        """Fixed callback function with proper error handling"""
        document_id = "unknown_id"  # Initialize at the start
        filename = "unknown_file"   # Initialize at the start
        
        try:
            message = json.loads(body)
            filename = message['filename']
            document_id = message.get('document_id', 'unknown_id')
            sender = message.get('sender', '') # Get sender information
            extracted_text = message.get('extracted_text', '')
            priority_content = message.get('priority_content', {}) # Get priority content from Extractor
            
            print(f"\n [x] Received '{filename}' (Doc ID: {document_id}) for classification.")

            # Determine VIP status and level
            is_vip, vip_level = determine_vip_status(sender, extracted_text, priority_content)
            if is_vip:
                print(f"  -> Document identified as VIP with level: {vip_level}")
            
            # Perform enhanced document classification
            classification_result = hybrid_classify(extracted_text)
            doc_type = classification_result.get('doc_type', 'UNKNOWN')
            confidence = classification_result.get('confidence_score', 0.0)
            classification_method = classification_result.get('method', 'unknown')
            
            print(f"  -> Classification: {doc_type} (confidence: {confidence:.2f}, method: {classification_method})")

            # Define valid document types
            VALID_TYPES = ['REPORT', 'RESUME', 'MEMO', 'INVOICE', 'AGREEMENT', 'CONTRACT', 'GRIEVANCE', 'ID_PROOF']
            
            # Apply confidence thresholds and human review logic
            if doc_type not in VALID_TYPES or doc_type in ['UNKNOWN', 'LLM_ERROR', 'HUMAN_REVIEW_NEEDED']:
                print(f"  -> Document type '{doc_type}' requires human review.")
                doc_type = "HUMAN_REVIEW_NEEDED"
                confidence = 0.0
            elif confidence < 0.75:  # Lower threshold for higher accuracy
                print(f"  -> Confidence ({confidence:.2f}) is below threshold. Flagging for human review.")
                doc_type = "HUMAN_REVIEW_NEEDED"
                confidence = 0.0
            elif is_vip and confidence < 0.85:  # Higher threshold for VIP documents
                print(f"  -> VIP document confidence ({confidence:.2f}) is below VIP threshold. Flagging for human review.")
                doc_type = "HUMAN_REVIEW_NEEDED"
                confidence = 0.0

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
                'vip_level': vip_level, # Pass VIP level
                'classification_method': classification_method # Pass classification method used
            }
            
            # Fixed: Create new connection for publishing
            try:
                publish_connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
                publish_channel = publish_connection.channel()
                publish_channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                publish_channel.basic_publish(
                    exchange='', 
                    routing_key=PUBLISH_QUEUE_NAME, 
                    body=json.dumps(router_message),
                    properties=pika.BasicProperties(delivery_mode=2)  # Make message persistent
                )
                publish_connection.close()
                
                print(f" [>] Sent '{filename}' (Type: {doc_type}, VIP: {is_vip}) for routing.")
                
                # Acknowledge the message successfully processed
                ch.basic_ack(delivery_tag=method.delivery_tag)
                
            except Exception as publish_error:
                print(f" [e] Failed to publish to router: {publish_error}")
                publish_status_update(
                    doc_id=document_id,
                    status="Classification Failed",
                    details={"error": f"Failed to send to router: {str(publish_error)}"}
                )
                # Don't acknowledge if we can't publish
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        except json.JSONDecodeError as e:
            print(f" [e] FAILED to parse JSON for message: {e}")
            # Reject malformed messages permanently
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
        except KeyError as e:
            print(f" [e] FAILED to process '{filename}' - missing required field {e}")
            publish_status_update(
                doc_id=document_id, 
                status="Classification Failed",
                details={"error": f"Missing required field: {str(e)}"}
            )
            # Reject messages with missing required fields
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
        except Exception as e:
            print(f" [e] FAILED to process '{filename}': {e}")
            publish_status_update(
                doc_id=document_id, 
                status="Classification Failed",
                details={"error": str(e)}
            )
            # On general failure, requeue for retry
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    # Set QoS to process one message at a time
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=callback)
    
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print(' [*] Stopping classifier...')
        channel.stop_consuming()
        connection.close()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        exit(0)
