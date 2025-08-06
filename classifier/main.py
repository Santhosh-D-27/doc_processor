# classifier/main.py - Optimized Priority-Aware Document Classifier

import time
import pika
import json
import os
import threading
import queue
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import IntEnum
import google.generativeai as genai
from datetime import datetime, UTC
from dotenv import load_dotenv
import re
import traceback
import groq

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
CUSTOM_VIP_KEYWORDS = ['ceo', 'director', 'vice president', 'vp', 'senior manager', 'head of', 
                      'board member', 'hr director', 'legal counsel', 'president', 'founder', 
                      'partner', 'owner', 'chairman', 'chairwoman']

CUSTOM_VIP_DOMAINS = ['board@yourcompany.com', 'executives@yourcompany.com', 
                     'leadership@yourcompany.com', 'c-suite@yourcompany.com']

# Initialize LLM clients
groq_client = None
gemini_model = None

try:
    groq_client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    logger.info("✓ Groq client initialized (Primary)")
except Exception:
    pass

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    logger.info("✓ Gemini client initialized (Fallback)")
except Exception:
    pass

if not groq_client and not gemini_model:
    logger.warning("⚠ No LLM clients available - analysis will be limited")

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
    reasoning: str = ""  # NEW: classification reasoning
    entity_boost: float = 0.0  # NEW: confidence boost from entities
    processing_time: float = 0.0
    error: str = ""
# Strengthened Document Classification Patterns
DOCUMENT_PATTERNS = {
    'RESUME': {
        'keywords': ['resume', 'curriculum vitae', 'cv', 'academic profile', 'technical qualification',
                    'education', 'experience', 'skills', 'qualifications', 'employment', 'work history',
                    'career objective', 'references', 'certifications', 'bachelor', 'master', 'degree',
                    'personal details', 'declaration', 'yours truly', 'thanking you'],
        'patterns': [r'\bresume\b', r'curriculum\s+vitae', r'\bcv\b', r'academic\s+profile',
                    r'technical\s+qualification', r'(?:work\s+)?experience\s*:', r'education\s*:',
                    r'skills\s*:', r'references\s*:', r'personal\s+details\s*:',
                    r'(?:bachelor|master)(?:\'?s)?\s+(?:of\s+)?(?:arts|science|mathematics)',
                    r'declaration\s*:\s*i\s+hereby\s+declare', r'yours\s+truly', r'thanking\s+you'],
        'strong_indicators': ['resume', 'curriculum vitae', 'academic profile', 'technical qualification'],
        'boost': 2.5
    },
    'CONTRACT': {
        'keywords': ['agreement', 'contract', 'terms and conditions', 'parties agree', 'whereas', 
                    'hereby agree', 'effective date', 'breach of contract', 'binding agreement',
                    'consideration', 'covenant', 'indemnify', 'force majeure', 'witnesseth'],
        'patterns': [r'this\s+(?:agreement|contract)', r'party\s+(?:of\s+the\s+)?(?:first|second)\s+part',
                    r'effective\s+(?:as\s+of|date)', r'breach\s+of\s+(?:this\s+)?(?:agreement|contract)',
                    r'whereas\s+clause', r'consideration\s+clause', r'force\s+majeure'],
        'strong_indicators': ['this agreement', 'party of the first part', 'whereas', 'consideration'],
        'boost': 2.0
    },
    'INVOICE': {
        'keywords': ['invoice', 'bill to', 'ship to', 'payment due', 'total amount', 'invoice number',
                    'due date', 'amount due', 'subtotal', 'tax', 'payment terms', 'remit to',
                    'purchase order', 'po number', 'billing address'],
        'patterns': [r'invoice\s+(?:#|number|no\.?)\s*:?\s*\d+', r'bill\s+to\s*:', r'payment\s+due\s*:',
                    r'total\s+(?:amount\s+)?due\s*:?\s*[\$₹]', r'invoice\s+date\s*:', r'due\s+date\s*:',
                    r'purchase\s+order\s*(?:#|number)?', r'amount\s*:\s*[\$₹]'],
        'strong_indicators': ['invoice number', 'bill to', 'payment due', 'invoice date'],
        'boost': 1.8
    },
    'REPORT': {
        'keywords': ['executive summary', 'introduction', 'methodology', 'findings', 'conclusions',
                    'recommendations', 'analysis', 'results', 'quarterly report', 'annual report',
                    'table of contents', 'appendix', 'bibliography', 'abstract'],
        'patterns': [r'executive\s+summary\s*:?', r'(?:section|chapter)\s+\d+', r'findings\s+(?:and\s+)?(?:results\s*)?:?',
                    r'conclusions?\s+(?:and\s+)?(?:recommendations\s*)?:?', r'table\s+of\s+contents',
                    r'(?:quarterly|annual|monthly)\s+report'],
        'strong_indicators': ['executive summary', 'table of contents', 'quarterly report', 'annual report'],
        'boost': 1.6
    },
    'MEMO': {
        'keywords': ['memorandum', 'memo', 'from:', 'to:', 'date:', 'subject:', 're:', 'urgent',
                    'for your information', 'internal communication', 'company policy', 'announcement'],
        'patterns': [r'(?:memo|memorandum)\s*(?:to|for)\s*:', r'from\s*:\s*[^\n]+', r'to\s*:\s*[^\n]+',
                    r'(?:subject|re)\s*:\s*[^\n]+', r'urgent\s*:?\s*(?:memo|memorandum)'],
        'strong_indicators': ['memorandum', 'memo to', 'from:', 'subject:'],
        'boost': 2.2
    },
    'AGREEMENT': {
        'keywords': ['agreement', 'mutual understanding', 'service agreement', 'license agreement',
                    'non-disclosure agreement', 'confidentiality agreement', 'mou', 'letter of intent',
                    'framework agreement', 'partnership agreement'],
        'patterns': [r'(?:service|license|partnership|confidentiality)\s+agreement',
                    r'non-disclosure\s+agreement', r'memorandum\s+of\s+understanding',
                    r'letter\s+of\s+intent', r'mutual\s+(?:understanding|agreement)'],
        'strong_indicators': ['service agreement', 'license agreement', 'non-disclosure agreement', 'mou'],
        'boost': 1.7
    },
    'GRIEVANCE': {
        'keywords': ['complaint', 'grievance', 'formal complaint', 'violation', 'harassment',
                    'discrimination', 'misconduct', 'dispute', 'hr complaint', 'incident report',
                    'allegation', 'disciplinary action', 'appeal'],
        'patterns': [r'formal\s+complaint', r'grievance\s+(?:report|filing)', r'incident\s+(?:report|number)',
                    r'violation\s+of\s+(?:policy|procedure)', r'harassment\s+(?:complaint|allegation)',
                    r'disciplinary\s+action'],
        'strong_indicators': ['formal complaint', 'grievance report', 'incident report', 'harassment complaint'],
        'boost': 1.9
    },
    'ID_PROOF': {
        'keywords': ['driver license', 'driver licence', 'passport', 'identification card', 'id card',
                    'social security', 'birth certificate', 'government issued', 'photo id', 'voter id',
                    'national id', 'citizenship card', 'visa', 'green card', 'permit'],
        'patterns': [r'driver\s*(?:\'?s)?\s*licen[sc]e\s+(?:number|no\.?)', r'passport\s+(?:number|no\.?)\s*:?\s*[A-Z0-9]+',
                    r'social\s+security\s+(?:number|no\.?)\s*:?\s*\d+', r'government\s+issued\s+id',
                    r'national\s+(?:id|identification)\s+(?:number|no\.?)', r'birth\s+certificate\s+(?:number|no\.?)'],
        'strong_indicators': ['driver license number', 'passport number', 'social security number', 'government issued id'],
        'exclude_patterns': [r'\bresume\b', r'academic\s+profile', r'technical\s+qualification', r'yours\s+truly'],
        'boost': 1.4
    }
}

class RabbitMQConnectionPool:
    def __init__(self, host: str, max_connections: int = 5):
        self.host = host
        self._connections = queue.Queue(maxsize=max_connections)
        self._initialize_pool()
    
    def _initialize_pool(self):
        for _ in range(5):
            try:
                conn = pika.BlockingConnection(pika.ConnectionParameters(
                    host=self.host, heartbeat=600, blocked_connection_timeout=300, socket_timeout=10
                ))
                if conn:
                    self._connections.put(conn)
            except Exception:
                pass
    
    def get_connection(self, timeout: float = 5.0):
        try:
            return self._connections.get(timeout=timeout)
        except queue.Empty:
            return pika.BlockingConnection(pika.ConnectionParameters(host=self.host))
    
    def return_connection(self, connection):
        if connection and hasattr(connection, 'is_open') and connection.is_open:
            try:
                self._connections.put_nowait(connection)
            except queue.Full:
                connection.close()

connection_pool = RabbitMQConnectionPool(RABBITMQ_HOST)

def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, 
                         confidence: float = None, is_vip: bool = False, vip_level: str = None,
                         priority_score: int = None, priority_reason: str = None, summary: str = None, filename: str = None):
    if details is None:
        details = {}
    
    if priority_score is not None:
        details['priority_score'] = priority_score
    if priority_reason is not None:
        details['priority_reason'] = priority_reason
    
    status_message = {
        "document_id": doc_id, 
        "filename": filename,  # ADD THIS
        "status": status, 
        "last_updated": datetime.now(UTC).isoformat(),  # CHANGE from "timestamp"
        "details": details, 
        "doc_type": doc_type, 
        "confidence": confidence,
        "is_vip": is_vip, 
        "vip_level": vip_level, 
        "summary": summary
    }
    
    connection = None
    try:
        connection = connection_pool.get_connection(timeout=2.0)
        if connection:
            channel = connection.channel()
            channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
            channel.basic_publish(exchange='', routing_key=STATUS_QUEUE_NAME, 
                                body=json.dumps(status_message), 
                                properties=pika.BasicProperties(delivery_mode=2))
    except Exception:
        pass
    finally:
        if connection:
            connection_pool.return_connection(connection)
# Add this function after publish_status_update()

def publish_doc_type_event(doc_id: str, filename: str, doc_type: str, confidence: float, 
                          reasoning: str, is_vip: bool, vip_level: str):
    """Publish doc.type event as per specification"""
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
    
    connection = None
    try:
        connection = connection_pool.get_connection(timeout=2.0)
        if connection:
            channel = connection.channel()
            channel.queue_declare(queue='doc_type_events', durable=True)
            channel.basic_publish(
                exchange='', 
                routing_key='doc_type_events', 
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
    except Exception as e:
        logger.warning(f"Failed to publish doc.type event: {e}")
    finally:
        if connection:
            connection_pool.return_connection(connection)
def classify_with_rule_based(text: str, priority_score: int = 20) -> dict:
    if not text or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
    
    text_lower = text.lower()
    scores = {}
    
    for doc_type, patterns in DOCUMENT_PATTERNS.items():
        score = 0
        strong_indicator_found = False
        
        # Check for exclusion patterns first (for ID_PROOF)
        if 'exclude_patterns' in patterns:
            excluded = False
            for exclude_pattern in patterns['exclude_patterns']:
                if re.search(exclude_pattern, text_lower, re.IGNORECASE):
                    excluded = True
                    break
            if excluded:
                continue
        
        # Check for strong indicators (document-defining terms)
        strong_indicators = patterns.get('strong_indicators', [])
        for indicator in strong_indicators:
            if indicator.lower() in text_lower:
                strong_indicator_found = True
                score += 5.0  # Heavy weight for strong indicators
                break
        
        # Check keywords with contextual weighting
        keyword_matches = 0
        for keyword in patterns['keywords']:
            if keyword.lower() in text_lower:
                keyword_matches += 1
                base_score = 1.0
                
                # Boost for document-specific context
                if doc_type == 'RESUME' and keyword in ['resume', 'academic profile', 'technical qualification']:
                    base_score = 3.0
                elif doc_type == 'INVOICE' and keyword in ['invoice number', 'bill to', 'payment due']:
                    base_score = 3.0
                elif doc_type == 'CONTRACT' and keyword in ['agreement', 'contract', 'parties agree']:
                    base_score = 3.0
                elif doc_type == 'ID_PROOF' and keyword in ['driver license', 'passport', 'government issued']:
                    base_score = 3.0
                
                if priority_score >= Priority.HIGH:
                    base_score *= patterns.get('boost', 1.0)
                score += base_score
        
        # Check regex patterns with enhanced scoring
        pattern_matches = 0
        for pattern in patterns['patterns']:
            try:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    pattern_matches += 1
                    boost = 3.0  # Higher weight for pattern matches
                    if priority_score >= Priority.HIGH:
                        boost *= patterns.get('boost', 1.0)
                    score += boost
            except re.error:
                continue
        
        # Enhanced scoring logic with document type specificity
        if doc_type == 'RESUME':
            # Resume must have either "RESUME" explicitly or strong academic/professional indicators
            if ('resume' in text_lower or 'curriculum vitae' in text_lower or 
                ('academic profile' in text_lower and 'technical qualification' in text_lower) or
                ('yours truly' in text_lower and 'declaration' in text_lower)):
                score += 5.0
        
        elif doc_type == 'ID_PROOF':
            # ID_PROOF requires very specific government/official document indicators
            if not any(indicator in text_lower for indicator in 
                      ['license number', 'passport number', 'social security number', 'government issued']):
                score *= 0.3  # Heavily penalize without specific ID indicators
        
        elif doc_type == 'INVOICE':
            # Invoice needs financial/billing context
            if not any(indicator in text_lower for indicator in 
                      ['invoice', 'bill to', 'payment', 'amount due', 'total']):
                score *= 0.5
        
        # Calculate confidence with enhanced logic
        total_possible = (len(patterns['keywords']) + len(patterns['patterns']) * 3 + 
                         len(strong_indicators) * 5)
        base_confidence = min(score / max(total_possible * 0.25, 1), 1.0)
        
        # Boost confidence for strong indicators
        if strong_indicator_found:
            base_confidence = min(base_confidence * 1.3, 1.0)
        
        # Document type specific confidence adjustments
        if doc_type == 'RESUME' and keyword_matches >= 3 and pattern_matches >= 1:
            base_confidence = min(base_confidence * 1.2, 1.0)
        elif doc_type == 'ID_PROOF' and keyword_matches < 2:
            base_confidence *= 0.6  # Reduce confidence for weak ID proof matches
        
        if priority_score >= Priority.CRITICAL and base_confidence > 0.6:
            base_confidence = min(base_confidence * 1.1, 1.0)
        
        scores[doc_type] = {
            'score': score, 
            'confidence': base_confidence,
            'keyword_matches': keyword_matches,
            'pattern_matches': pattern_matches,
            'strong_indicator': strong_indicator_found
        }
    
    if scores:
        # Sort by score and apply tie-breaking logic
        sorted_types = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)
        best_type, best_score = sorted_types[0]
        
        # Enhanced minimum score thresholds
        if best_type == 'RESUME':
            min_score = 4.0 if priority_score < Priority.HIGH else 3.0
        elif best_type == 'ID_PROOF':
            min_score = 6.0 if priority_score < Priority.HIGH else 5.0  # Higher threshold for ID_PROOF
        else:
            min_score = 3.0 if priority_score < Priority.HIGH else 2.0
        
        if best_score['score'] < min_score:
            return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
        
        # Additional tie-breaking: if scores are close, prefer document types with strong indicators
        if len(sorted_types) > 1:
            second_best = sorted_types[1][1]
            if abs(best_score['score'] - second_best['score']) < 2.0:
                if best_score['strong_indicator'] and not second_best['strong_indicator']:
                    pass  # Keep best_type
                elif second_best['strong_indicator'] and not best_score['strong_indicator']:
                    best_type = sorted_types[1][0]
                    best_score = second_best
        
        return {"doc_type": best_type, "confidence_score": best_score['confidence']}
    
    return {"doc_type": "UNKNOWN", "confidence_score": 0.0}

def classify_with_llm(text: str, priority_score: int = 20) -> dict:
    if not groq_client and not gemini_model:
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
    
    processing_text = text[:4000]
    if len(text) > 4000:
        processing_text += "\n[... text truncated for classification ...]"
    
    urgency_context = ""
    if priority_score >= Priority.CRITICAL:
        urgency_context = "This is a CRITICAL priority document requiring immediate attention."
    elif priority_score >= Priority.HIGH:
        urgency_context = "This is a HIGH priority document requiring prompt processing."
    
    prompt = f"""
    {urgency_context}
    
    Classify this document into ONE category:
    REPORT, RESUME, MEMO, INVOICE, AGREEMENT, CONTRACT, GRIEVANCE, ID_PROOF
    
    Return ONLY valid JSON:
    {{"doc_type": "CATEGORY_NAME", "confidence_score": 0.95, "reasoning": "Brief explanation"}}
    
    Document text:
    ---
    {processing_text}
    ---
    """
    
    # Try Groq first
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant", temperature=0.1, max_tokens=512
            )
            json_response_text = response.choices[0].message.content.strip()
            json_response_text = json_response_text.lstrip('```json').rstrip('```').strip()
            return json.loads(json_response_text)
        except Exception:
            pass
    
    # Fallback to Gemini
    if gemini_model:
        try:
            response = gemini_model.generate_content(prompt)
            json_response_text = response.text.strip().lstrip('```json').rstrip('```').strip()
            return json.loads(json_response_text)
        except Exception:
            pass
    
    return {"doc_type": "LLM_ERROR", "confidence_score": 0.0}

def hybrid_classify(text: str, priority_score: int = 20) -> dict:
    if not text or not text.strip():
        return {"doc_type": "UNKNOWN", "confidence_score": 0.0}
    
    rule_result = classify_with_rule_based(text, priority_score)
    rule_confidence = rule_result.get('confidence_score', 0.0)
    rule_type = rule_result.get('doc_type', 'UNKNOWN')
    
    high_confidence_threshold = 0.85 if priority_score >= Priority.HIGH else 0.8
    
    if rule_confidence >= high_confidence_threshold and rule_type != 'UNKNOWN':
        return {"doc_type": rule_type, "confidence_score": rule_confidence}
    
    llm_result = classify_with_llm(text, priority_score)
    llm_confidence = llm_result.get('confidence_score', 0.0)
    llm_type = llm_result.get('doc_type', 'UNKNOWN')
    
    if rule_type == llm_type and rule_type != 'UNKNOWN':
        combined_confidence = min((rule_confidence + llm_confidence) / 1.5, 1.0)
        return {"doc_type": rule_type, "confidence_score": combined_confidence}
    
    if llm_confidence > rule_confidence:
        return {"doc_type": llm_type, "confidence_score": llm_confidence}
    
    if rule_type != 'UNKNOWN':
        return {"doc_type": rule_type, "confidence_score": rule_confidence}
    
    return {"doc_type": "HUMAN_REVIEW_NEEDED", "confidence_score": 0.0}
# Add this function after hybrid_classify()

def entity_enhanced_classify(text: str, entities: dict, priority_score: int = 20) -> dict:
    """Enhanced classification using both text and extracted entities"""
    
    # Get base classification
    base_result = hybrid_classify(text, priority_score)
    base_type = base_result.get('doc_type', 'UNKNOWN')
    base_confidence = base_result.get('confidence_score', 0.0)
    
    # Entity-based confidence boosting
    confidence_boost = 0.0
    reasoning_parts = []
    
    if entities:
        # INVOICE indicators
        if base_type == 'INVOICE':
            amounts = entities.get('amounts', [])
            dates = entities.get('dates', [])
            if amounts:
                confidence_boost += 0.1
                reasoning_parts.append(f"Found {len(amounts)} financial amounts")
            if any('due' in str(date).lower() or 'payment' in str(date).lower() for date in dates):
                confidence_boost += 0.1
                reasoning_parts.append("Found payment/due dates")
        
        # CONTRACT/AGREEMENT indicators
        elif base_type in ['CONTRACT', 'AGREEMENT']:
            parties = entities.get('parties', [])
            dates = entities.get('dates', [])
            if len(parties) >= 2:
                confidence_boost += 0.15
                reasoning_parts.append(f"Found {len(parties)} parties")
            if dates:
                confidence_boost += 0.1
                reasoning_parts.append("Found contract dates")
        
        # RESUME indicators
        elif base_type == 'RESUME':
            organizations = entities.get('organizations', [])
            dates = entities.get('dates', [])
            if organizations:
                confidence_boost += 0.1
                reasoning_parts.append(f"Found {len(organizations)} organizations")
            if len(dates) >= 2:  # Multiple dates suggest work history
                confidence_boost += 0.1
                reasoning_parts.append("Found multiple dates (work history)")
        
        # ID_PROOF indicators
        elif base_type == 'ID_PROOF':
            dates = entities.get('dates', [])
            locations = entities.get('locations', [])
            if dates:
                confidence_boost += 0.1
                reasoning_parts.append("Found dates (issue/expiry)")
            if locations:
                confidence_boost += 0.1
                reasoning_parts.append("Found locations")
    
    # Apply confidence boost
    enhanced_confidence = min(base_confidence + confidence_boost, 1.0)
    
    # Generate reasoning
    reasoning = f"Base classification: {base_type} ({base_confidence:.2f})"
    if reasoning_parts:
        reasoning += f"; Entity boost: {', '.join(reasoning_parts)} (+{confidence_boost:.2f})"
    
    return {
        "doc_type": base_type,
        "confidence_score": enhanced_confidence,
        "reasoning": reasoning,
        "entity_boost": confidence_boost
    }
def determine_vip_status(sender: str, extracted_text: str, priority_content: dict, 
                        priority_score: int = 20) -> Tuple[bool, str]:
    try:
        sender = sender or ""
        extracted_text = extracted_text or ""
        priority_content = priority_content or {}

        # Priority-based VIP detection
        if priority_score >= Priority.CRITICAL:
            return True, "HIGH"
        elif priority_score >= Priority.HIGH:
            return True, "MEDIUM"

        # Domain-based VIP detection
        if sender:
            sender_email = sender.split('<')[-1].replace('>', '').strip().lower()
            for domain in CUSTOM_VIP_DOMAINS:
                if domain in sender_email:
                    return True, "HIGH"

        # Keyword analysis
        lower_sender = sender.lower()
        lower_extracted_text = extracted_text.lower()
        
        high_vip_keywords = ['ceo', 'chief executive officer', 'board member', 'director', 
                           'founder', 'president', 'chairman', 'chairwoman']
        for keyword in high_vip_keywords:
            if keyword in lower_sender or keyword in lower_extracted_text:
                return True, "HIGH"

        medium_vip_keywords = ['vp', 'vice president', 'senior manager', 'department head', 
                             'legal counsel', 'hr director', 'partner', 'owner']
        for keyword in medium_vip_keywords:
            if keyword in lower_sender or keyword in lower_extracted_text:
                return True, "MEDIUM"
                
        urgency_level = priority_content.get("urgency_level", "low")
        if isinstance(urgency_level, str) and urgency_level.lower() == "high":
            return True, "MEDIUM"

        return False, "NONE"
        
    except Exception:
        return False, "NONE"

class PriorityClassificationProcessor:
    def __init__(self):
        self.stats = {'total_processed': 0, 'vip_processed': 0, 'errors': 0}
        self.stats_lock = threading.Lock()
    
    def process_document(self, task: ClassificationTask) -> ClassificationResult:
        start_time = time.time()
        
        try:
            message = task.message
            extracted_text = message.get('extracted_text', '')
            sender = message.get('sender', 'N/A')
            priority_content = message.get('priority_content', {})
            
            # Check for override parameters
            override_params = message.get('override_parameters', {})
            force_classification = override_params.get('force_classification', False)
            manual_type_hint = override_params.get('manual_type_hint')
            custom_threshold = override_params.get('confidence_threshold')
            
            is_vip, vip_level = determine_vip_status(sender, extracted_text, priority_content, task.priority_score)
            
            # Get entities from the message
            entities = message.get('entities', {})

# Use entity-enhanced classification
            classification_result = entity_enhanced_classify(extracted_text, entities, task.priority_score)
            doc_type = classification_result.get('doc_type', 'UNKNOWN')
            confidence = classification_result.get('confidence_score', 0.0)
            
            VALID_TYPES = ['REPORT', 'RESUME', 'MEMO', 'INVOICE', 'AGREEMENT', 'CONTRACT', 'GRIEVANCE', 'ID_PROOF']
            
            # Use custom threshold if provided in override
            if custom_threshold is not None:
                min_confidence = custom_threshold
            elif task.priority_score >= Priority.CRITICAL:
                min_confidence = 0.90
            elif task.priority_score >= Priority.HIGH or is_vip:
                min_confidence = 0.85
            else:
                min_confidence = 0.75
            
            # Handle manual type hint
            if manual_type_hint and manual_type_hint in VALID_TYPES:
                doc_type = manual_type_hint
                confidence = 1.0  # Full confidence for manual override
            
            # Allow force classification to bypass thresholds
            if not force_classification and (doc_type not in VALID_TYPES or doc_type in ['UNKNOWN', 'LLM_ERROR'] or confidence < min_confidence):
                doc_type = "HUMAN_REVIEW_NEEDED"
                confidence = 0.0
            
            processing_time = time.time() - start_time
            
            with self.stats_lock:
                self.stats['total_processed'] += 1
                if is_vip:
                    self.stats['vip_processed'] += 1
            
            return ClassificationResult(
                success=True, document_id=task.document_id, filename=task.filename,
                doc_type=doc_type, confidence=confidence, is_vip=is_vip, vip_level=vip_level,
                reasoning=classification_result.get('reasoning', 'Classification completed'),
                entity_boost=classification_result.get('entity_boost', 0.0),
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            with self.stats_lock:
                self.stats['errors'] += 1
            
            return ClassificationResult(
                success=False, document_id=task.document_id, filename=task.filename,
                processing_time=processing_time, error=str(e)
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
                    logger.error(f"Failed to connect after {max_retries} attempts")
                    return False
        return False
    
    def process_message_callback(self, ch, method, properties, body):
        task = None
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
            
            # Process immediately and ack only after successful processing
            result = self.processor.process_document(task)
            
            if result.success:
                # Send to router first
                publish_doc_type_event(
                    doc_id=result.document_id,
                    filename=result.filename,
                    doc_type=result.doc_type,
                    confidence=result.confidence,
                    reasoning=getattr(result, 'reasoning', 'Classification completed'),
                    is_vip=result.is_vip,
                    vip_level=result.vip_level
                )
                router_message = {
                    'document_id': result.document_id, 'filename': result.filename,
                    'doc_type': result.doc_type, 'confidence': result.confidence,
                    'entities': task.message.get('entities', {}),
                    'summary': task.message.get('summary', 'No summary available.'),
                    'priority_content': task.message.get('priority_content', {}),
                    'is_vip': result.is_vip, 'vip_level': result.vip_level,
                    'priority_score': task.priority_score, 'priority_reason': task.priority_reason,
                    'sender': task.message.get('sender', 'N/A')
                }
                
                # Try to send to router with retry
                if self.send_to_router_with_retry(router_message):
                    # Only ack if router message was sent successfully
                    try:
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        
                        # Send status update (non-critical, fire-and-forget)
                        publish_status_update(
                            doc_id=result.document_id, status="Classified", doc_type=result.doc_type,
                            confidence=result.confidence, is_vip=result.is_vip, vip_level=result.vip_level,
                            filename=result.filename,
                            priority_score=task.priority_score, priority_reason=task.priority_reason,
                            summary=task.message.get('summary', 'No summary available'),
                            details={"processing_time": result.processing_time}
                        )
                    except Exception as ack_error:
                        logger.error(f"Failed to ack message for {task.document_id}: {ack_error}")
                        # Don't requeue if we already sent to router successfully
                else:
                    # Failed to send to router, nack and requeue
                    try:
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    except:
                        pass
            else:
                # Processing failed
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    publish_status_update(
                        doc_id=result.document_id, status="Classification Failed",
                        filename=result.filename,
                        priority_score=task.priority_score, priority_reason=task.priority_reason,
                        summary=task.message.get('summary', 'No summary available'),
                        details={"error": result.error, "processing_time": result.processing_time}
                    )
                except:
                    pass
                    
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
            try:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            except:
                pass
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            try:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            except:
                pass

    def send_to_router_with_retry(self, message: dict, max_retries: int = 3) -> bool:
        """Send message to router with retry logic"""
        for attempt in range(max_retries):
            connection = None
            try:
                connection = connection_pool.get_connection(timeout=5.0)
                if connection and hasattr(connection, 'is_open') and connection.is_open:
                    channel = connection.channel()
                    channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                    channel.basic_publish(
                        exchange='', 
                        routing_key=PUBLISH_QUEUE_NAME, 
                        body=json.dumps(message), 
                        properties=pika.BasicProperties(delivery_mode=2)
                    )
                    return True
            except Exception as e:
                logger.warning(f"Router send attempt {attempt + 1} failed: {e}")
                if connection:
                    try:
                        connection.close()
                    except:
                        pass
                    connection = None
            finally:
                if connection:
                    connection_pool.return_connection(connection)
            
            if attempt < max_retries - 1:
                time.sleep(1)  # Brief pause before retry
        
        return False
    
    def process_task(self, task: ClassificationTask):
        try:
            result = self.processor.process_document(task)
            
            if result.success:
                router_message = {
                    'document_id': result.document_id, 'filename': result.filename,
                    'doc_type': result.doc_type, 'confidence': result.confidence,
                    'entities': task.message.get('entities', {}),
                    'summary': task.message.get('summary', 'No summary available.'),
                    'priority_content': task.message.get('priority_content', {}),
                    'is_vip': result.is_vip, 'vip_level': result.vip_level,
                    'priority_score': task.priority_score, 'priority_reason': task.priority_reason,
                    'sender': task.message.get('sender', 'N/A')
                }
                
                self.send_to_router(router_message)
                publish_status_update(
                    doc_id=result.document_id, status="Classified", doc_type=result.doc_type,
                    filename=result.filename,
                    confidence=result.confidence, is_vip=result.is_vip, vip_level=result.vip_level,
                    priority_score=task.priority_score, priority_reason=task.priority_reason,
                    summary=task.message.get('summary', 'No summary available'),
                    details={"processing_time": result.processing_time}
                )
            else:
                publish_status_update(
                    doc_id=result.document_id, status="Classification Failed",
                    filename=result.filename,
                    priority_score=task.priority_score, priority_reason=task.priority_reason,
                    summary=task.message.get('summary', 'No summary available'),
                    details={"error": result.error, "processing_time": result.processing_time}
                )
                
        except Exception as e:
            logger.error(f"Task processing error {task.document_id}: {e}")
    
    def send_to_router(self, message: dict):
        connection = None
        try:
            connection = connection_pool.get_connection(timeout=2.0)
            if connection:
                channel = connection.channel()
                channel.queue_declare(queue=PUBLISH_QUEUE_NAME, durable=True)
                channel.basic_publish(exchange='', routing_key=PUBLISH_QUEUE_NAME, 
                                    body=json.dumps(message), 
                                    properties=pika.BasicProperties(delivery_mode=2))
        except Exception:
            pass
        finally:
            if connection:
                connection_pool.return_connection(connection)
    
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
            except Exception:
                pass
    
    def stop(self):
        logger.info("🛑 Stopping Classification Service...")
        self.is_running = False
        if self.channel and hasattr(self.channel, 'stop_consuming'):
            self.channel.stop_consuming()
        self.executor.shutdown(wait=True, timeout=30)
        connection_pool._connections = queue.Queue()
        logger.info("✓ Classification Service stopped")
    
    def cleanup(self):
        if self.connection and hasattr(self.connection, 'is_open') and self.connection.is_open:
            try:
                self.connection.close()
            except Exception:
                pass

def main():
    try:
        service = PriorityClassificationService()
        service.start()
    except Exception as e:
        logger.error(f"Service failed to start: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()