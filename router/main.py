# router/main.py - Enhanced Smart Router Agent with Dynamic Routing

import pika
import json
import os
import requests
import sys
import time
from datetime import datetime, UTC
from typing import Dict, List, Optional, Tuple

# --- Google Sheets API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', '127.0.0.1')
CONSUME_QUEUE_NAME = 'routing_queue'  # Regular documents
VIP_CONSUME_QUEUE_NAME = 'vip_documents_queue'  # VIP documents
STATUS_QUEUE_NAME = 'document_status_queue'

# SECRETS (retrieved from environment variables)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
VIP_GOOGLE_SHEET_ID = os.environ.get("VIP_GOOGLE_SHEET_ID")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
VIP_SLACK_WEBHOOK_URL = os.environ.get("VIP_SLACK_WEBHOOK_URL")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")  # For enterprise integration

# Enhanced routing destinations
ERP_SYSTEM_URL = os.environ.get("ERP_SYSTEM_URL")
DMS_SYSTEM_URL = os.environ.get("DMS_SYSTEM_URL")
CRM_SYSTEM_URL = os.environ.get("CRM_SYSTEM_URL")

# Define sheet ranges
SHEET_RANGE_NAME = 'Documents!A:J'  # Extended for more metadata
VIP_SHEET_RANGE_NAME = 'VIPDocs!A:M'  # VIP sheet with comprehensive tracking
ANALYTICS_SHEET_RANGE = 'Analytics!A:F'  # For processing analytics

# --- Google Sheets Service Initialization ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

sheets_service = None

class SmartRouter:
    def __init__(self):
        self.routing_rules = self._load_routing_rules()
        self.system_health = self._check_system_health()
        
    def _load_routing_rules(self) -> Dict:
        """Load dynamic routing rules - can be extended to load from database"""
        return {
            "INVOICE": {
                "primary": "erp_system",
                "secondary": "google_sheets",
                "fallback": "slack_alert",
                "requires_approval": False
            },
            "CONTRACT": {
                "primary": "dms_system",
                "secondary": "google_sheets", 
                "fallback": "slack_alert",
                "requires_approval": True
            },
            "RESUME": {
                "primary": "crm_system",
                "secondary": "google_sheets",
                "fallback": "slack_alert",
                "requires_approval": False
            },
            "RECEIPT": {
                "primary": "google_sheets",
                "secondary": "erp_system",
                "fallback": "slack_alert",
                "requires_approval": False
            },
            "MEMO": {
                "primary": "google_sheets",
                "secondary": "slack_alert",
                "fallback": "teams_notification",
                "requires_approval": False
            },
            "REPORT": {
                "primary": "google_sheets",
                "secondary": "dms_system",
                "fallback": "slack_alert",
                "requires_approval": True
            },
            "URGENT_VIP_NOTICE": {
                "primary": "vip_priority_alert",
                "secondary": "google_sheets",
                "fallback": "multi_channel_alert",
                "requires_approval": True
            }
        }
    
    def _check_system_health(self) -> Dict[str, bool]:
        """Check health of external systems"""
        health = {
            "google_sheets": True,  # Will be checked dynamically
            "slack": bool(SLACK_WEBHOOK_URL),
            "teams": bool(TEAMS_WEBHOOK_URL),
            "erp_system": bool(ERP_SYSTEM_URL),
            "dms_system": bool(DMS_SYSTEM_URL),
            "crm_system": bool(CRM_SYSTEM_URL)
        }
        return health
    
    def get_routing_destination(self, doc_type: str, confidence: float, is_vip: bool = False) -> Tuple[str, List[str]]:
        """Intelligent routing decision based on document type, confidence, and VIP status"""
        if is_vip:
            return "vip_priority_routing", ["vip_sheets", "vip_slack", "priority_notifications"]
        
        if confidence < 0.6:
            return "human_review", ["slack_alert", "low_confidence_queue"]
        
        rules = self.routing_rules.get(doc_type, self.routing_rules["MEMO"])
        
        # Check primary system health
        primary_system = rules["primary"]
        if not self.system_health.get(primary_system, False):
            print(f"  -> Primary system {primary_system} unavailable, using secondary")
            return rules["secondary"], [rules["fallback"]]
        
        destinations = [rules["primary"]]
        if rules.get("requires_approval"):
            destinations.append("approval_workflow")
        
        return rules["primary"], destinations

# Initialize smart router
smart_router = SmartRouter()

def publish_status_update(doc_id: str, status: str, details: dict = None, doc_type: str = None, 
                         confidence: float = None, is_vip: bool = False, routing_info: dict = None):
    """Enhanced status update with routing information"""
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
        "routing_info": routing_info or {}
    }
    
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=STATUS_QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=STATUS_QUEUE_NAME,
            body=json.dumps(status_message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        vip_status = " [VIP]" if is_vip else ""
        print(f" [->] Status update published for Doc ID {doc_id}: {status}{vip_status}")
    except Exception as e:
        print(f" [!!!] WARNING: Failed to publish status update for {doc_id}: {e}")

def get_sheets_service():
    """Initializes and returns the Google Sheets API service."""
    global sheets_service
    if sheets_service is None:
        if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
            print("  -> ERROR: GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
            smart_router.system_health["google_sheets"] = False
            return None

        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            sheets_service = build('sheets', 'v4', credentials=creds)
            smart_router.system_health["google_sheets"] = True
            print("  -> Google Sheets service initialized.")
        except Exception as e:
            print(f"  -> ERROR: Failed to initialize Google Sheets service: {e}")
            smart_router.system_health["google_sheets"] = False
            sheets_service = None
    return sheets_service

def send_to_erp_system(document_data: Dict) -> bool:
    """Send document to ERP system"""
    if not ERP_SYSTEM_URL:
        print("  -> ERP system URL not configured")
        return False
    
    try:
        payload = {
            "document_id": document_data["document_id"],
            "filename": document_data["filename"],
            "doc_type": document_data["doc_type"],
            "extracted_data": document_data.get("entities", {}),
            "confidence": document_data.get("confidence", 0.0)
        }
        
        response = requests.post(f"{ERP_SYSTEM_URL}/api/documents", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> Successfully sent to ERP system: {document_data['filename']}")
        return True
    except Exception as e:
        print(f"  -> Failed to send to ERP system: {e}")
        return False

def send_to_dms_system(document_data: Dict) -> bool:
    """Send document to Document Management System"""
    if not DMS_SYSTEM_URL:
        print("  -> DMS system URL not configured")
        return False
    
    try:
        payload = {
            "document_id": document_data["document_id"],
            "filename": document_data["filename"],
            "doc_type": document_data["doc_type"],
            "content": document_data.get("file_content", ""),
            "metadata": {
                "sender": document_data.get("sender", ""),
                "confidence": document_data.get("confidence", 0.0),
                "is_vip": document_data.get("is_vip", False)
            }
        }
        
        response = requests.post(f"{DMS_SYSTEM_URL}/api/upload", json=payload, timeout=15)
        response.raise_for_status()
        print(f"  -> Successfully sent to DMS system: {document_data['filename']}")
        return True
    except Exception as e:
        print(f"  -> Failed to send to DMS system: {e}")
        return False

def send_to_crm_system(document_data: Dict) -> bool:
    """Send document to CRM system"""
    if not CRM_SYSTEM_URL:
        print("  -> CRM system URL not configured")
        return False
    
    try:
        payload = {
            "document_id": document_data["document_id"],
            "filename": document_data["filename"],
            "candidate_data": document_data.get("entities", {}),
            "sender": document_data.get("sender", ""),
            "summary": document_data.get("summary", "")
        }
        
        response = requests.post(f"{CRM_SYSTEM_URL}/api/candidates", json=payload, timeout=10)
        response.raise_for_status()
        print(f"  -> Successfully sent to CRM system: {document_data['filename']}")
        return True
    except Exception as e:
        print(f"  -> Failed to send to CRM system: {e}")
        return False

def log_to_google_sheet(filename: str, doc_type: str, confidence: float, is_vip: bool = False, 
                       vip_level: str = None, sender: str = None, summary: str = None,
                       routing_destination: str = None, processing_time: float = None) -> bool:
    """Enhanced logging with routing and performance metrics"""
    service = get_sheets_service()
    sheet_id = VIP_GOOGLE_SHEET_ID if is_vip and VIP_GOOGLE_SHEET_ID else GOOGLE_SHEET_ID
    
    if not service or not sheet_id:
        print("  -> Google Sheets service not available or SHEET_ID not set.")
        return False

    print(f"  -> Logging to Google Sheets: '{filename}' {'[VIP]' if is_vip else ''}")
    try:
        if is_vip:
            # VIP sheet with comprehensive tracking
            values = [
                filename,
                doc_type,
                confidence,
                vip_level or 'medium',
                sender or 'Unknown',
                (summary or 'No summary')[:150] + ('...' if len(summary or '') > 150 else ''),
                routing_destination or 'Unknown',
                processing_time or 0.0,
                'VIP',
                datetime.now(UTC).strftime('%Y-%m-%d'),
                datetime.now(UTC).strftime('%H:%M:%S'),
                'Active',
                'Pending Review'
            ]
            range_name = VIP_SHEET_RANGE_NAME
        else:
            # Regular sheet with enhanced metadata
            values = [
                filename,
                doc_type,
                confidence,
                sender or 'Unknown',
                (summary or 'No summary')[:100] + ('...' if len(summary or '') > 100 else ''),
                routing_destination or 'Unknown',
                processing_time or 0.0,
                datetime.now(UTC).strftime('%Y-%m-%d'),
                datetime.now(UTC).strftime('%H:%M:%S'),
                'Processed'
            ]
            range_name = SHEET_RANGE_NAME
        
        body = {'values': [values]}
        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        cells_updated = result.get('updates', {}).get('updatedCells', 0)
        print(f"  -> Successfully logged {cells_updated} cells to {'VIP' if is_vip else 'regular'} sheet.")
        
        # Also log analytics data
        log_analytics_data(doc_type, confidence, processing_time, is_vip)
        return True
    except Exception as e:
        print(f"  -> ERROR: Failed to log to Google Sheet: {e}")
        return False

def log_analytics_data(doc_type: str, confidence: float, processing_time: float, is_vip: bool):
    """Log analytics data for dashboard insights"""
    try:
        service = get_sheets_service()
        if not service or not GOOGLE_SHEET_ID:
            return
        
        analytics_values = [
            datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
            doc_type,
            confidence,
            processing_time,
            'VIP' if is_vip else 'Regular',
            smart_router.system_health.get('google_sheets', False)
        ]
        
        body = {'values': [analytics_values]}
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=ANALYTICS_SHEET_RANGE,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        print("  -> Analytics data logged successfully")
    except Exception as e:
        print(f"  -> Warning: Failed to log analytics: {e}")

def send_enhanced_slack_alert(filename: str, reason: str, doc_type: str = "N/A", is_vip: bool = False, 
                            vip_level: str = None, sender: str = None, priority_content: dict = None,
                            routing_info: dict = None):
    """Enhanced Slack alerts with rich formatting and routing information"""
    webhook_url = VIP_SLACK_WEBHOOK_URL if is_vip and VIP_SLACK_WEBHOOK_URL else SLACK_WEBHOOK_URL
    
    if not webhook_url:
        print("  -> Slack Webhook URL not configured")
        return

    # Enhanced emoji selection
    if is_vip:
        urgency_emoji = "🚨" if vip_level == 'high' else "⚠️" if vip_level == 'medium' else "📋"
        doc_emoji = "👑"
    else:
        urgency_emoji = "⚠️" if "Failed" in reason else "📄"
        doc_emoji = "📊" if doc_type == "REPORT" else "💰" if doc_type == "INVOICE" else "📋"
    
    print(f"  -> Sending enhanced {'VIP ' if is_vip else ''}Slack alert...")
    
    # Build rich message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{urgency_emoji} {'VIP ' if is_vip else ''}Document Processing Alert"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{doc_emoji} *{reason}*"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*File:*\n`{filename}`"},
                {"type": "mrkdwn", "text": f"*Type:*\n{doc_type}"},
                {"type": "mrkdwn", "text": f"*Time:*\n{datetime.now(UTC).strftime('%H:%M:%S')}"},
                {"type": "mrkdwn", "text": f"*Sender:*\n{sender or 'Unknown'}"}
            ]
        }
    ]
    
    # Add VIP-specific information
    if is_vip and vip_level:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎯 *VIP Level:* {vip_level.upper()}"
            }
        })
    
    # Add routing information
    if routing_info:
        routing_text = f"🔄 *Routing:* {routing_info.get('primary_destination', 'Unknown')}"
        if routing_info.get('fallback_used'):
            routing_text += f"\n⚠️ *Fallback Applied:* {routing_info.get('fallback_reason', 'System unavailable')}"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": routing_text
            }
        })
    
    # Add priority content for VIP documents
    if priority_content and is_vip:
        priority_text = "🎯 *Priority Items:*\n"
        if priority_content.get('deadlines'):
            priority_text += f"⏰ {', '.join(priority_content['deadlines'][:2])}\n"
        if priority_content.get('financial_commitments'):
            priority_text += f"💰 {', '.join(priority_content['financial_commitments'][:2])}\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": priority_text
            }
        })
    
    # Add action buttons for interactive workflow
    if is_vip or doc_type in ["CONTRACT", "REPORT"]:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📋 Review Document"},
                    "style": "primary",
                    "url": f"http://localhost:5173"  # Link to your dashboard
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary" if is_vip else "danger"
                }
            ]
        })
    
    message = {
        "text": f"{doc_emoji} {'VIP ' if is_vip else ''}Document: `{filename}`",
        "blocks": blocks,
        "username": "Document Router",
        "icon_emoji": ":robot_face:"
    }
    
    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        print(f"  -> Enhanced {'VIP ' if is_vip else ''}Slack alert sent successfully")
    except requests.exceptions.RequestException as e:
        print(f"  -> ERROR: Failed to send Slack alert: {e}")

def send_teams_notification(document_data: Dict):
    """Send notification to Microsoft Teams"""
    if not TEAMS_WEBHOOK_URL:
        print("  -> Teams webhook not configured")
        return
    
    try:
        card = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"Document Processing: {document_data['filename']}",
            "themeColor": "0078D4",
            "title": "📄 Document Processed",
            "sections": [
                {
                    "activityTitle": f"**{document_data['doc_type']}** document routed",
                    "activitySubtitle": f"File: {document_data['filename']}",
                    "facts": [
                        {"name": "Sender", "value": document_data.get('sender', 'Unknown')},
                        {"name": "Confidence", "value": f"{document_data.get('confidence', 0):.2f}"},
                        {"name": "VIP Status", "value": "Yes" if document_data.get('is_vip') else "No"}
                    ]
                }
            ],
            "potentialAction": [
                {
                    "@type": "OpenUri",
                    "name": "View Dashboard",
                    "targets": [{"os": "default", "uri": "http://localhost:5173"}]
                }
            ]
        }
        
        response = requests.post(TEAMS_WEBHOOK_URL, json=card, timeout=10)
        response.raise_for_status()
        print(f"  -> Teams notification sent for {document_data['filename']}")
    except Exception as e:
        print(f"  -> Failed to send Teams notification: {e}")

def process_regular_document(message):
    """Enhanced regular document processing with smart routing"""
    start_time = time.time()
    document_id = message.get('document_id', 'unknown_id')
    doc_type = message.get('doc_type', 'UNKNOWN')
    filename = message.get('filename', 'Unknown_File')
    confidence = message.get('confidence', 0.0)
    sender = message.get('sender', '')
    summary = message.get('summary', '')
    
    print(f"\n [x] Smart routing for document '{filename}' (Doc ID: {document_id})")
    
    try:
        # Get smart routing decision
        primary_destination, all_destinations = smart_router.get_routing_destination(
            doc_type, confidence, False
        )
        
        routing_info = {
            "primary_destination": primary_destination,
            "all_destinations": all_destinations,
            "fallback_used": False
        }
        
        success_count = 0
        failed_destinations = []
        
        # Execute routing to all destinations
        for destination in all_destinations:
            try:
                if destination == "google_sheets":
                    if log_to_google_sheet(filename, doc_type, confidence, False, None, sender, summary, 
                                         primary_destination, time.time() - start_time):
                        success_count += 1
                    else:
                        failed_destinations.append(destination)
                
                elif destination == "erp_system":
                    if send_to_erp_system(message):
                        success_count += 1
                    else:
                        failed_destinations.append(destination)
                
                elif destination == "dms_system":
                    if send_to_dms_system(message):
                        success_count += 1
                    else:
                        failed_destinations.append(destination)
                
                elif destination == "crm_system":
                    if send_to_crm_system(message):
                        success_count += 1
                    else:
                        failed_destinations.append(destination)
                
                elif destination == "slack_alert":
                    send_enhanced_slack_alert(
                        filename, 
                        f"Document routed to {primary_destination}", 
                        doc_type, False, None, sender, None, routing_info
                    )
                    success_count += 1
                
                elif destination == "teams_notification":
                    send_teams_notification(message)
                    success_count += 1
                    
            except Exception as e:
                print(f"  -> Failed to route to {destination}: {e}")
                failed_destinations.append(destination)
        
        # Handle fallbacks if primary routing failed
        if failed_destinations and primary_destination in failed_destinations:
            print(f"  -> Primary destination failed, executing fallback routing")
            routing_info["fallback_used"] = True
            routing_info["fallback_reason"] = f"{primary_destination} unavailable"
            
            send_enhanced_slack_alert(
                filename,
                f"FALLBACK: Primary routing to {primary_destination} failed",
                doc_type, False, None, sender, None, routing_info
            )
        
        processing_time = time.time() - start_time
        
        publish_status_update(
            doc_id=document_id,
            status="Routed" if success_count > 0 else "Routing Failed",
            details={
                "destinations": all_destinations,
                "successful_routes": success_count,
                "failed_routes": len(failed_destinations),
                "processing_time": processing_time
            },
            doc_type=doc_type,
            confidence=confidence,
            is_vip=False,
            routing_info=routing_info
        )
        
        print(f"  -> Document '{filename}' routed successfully to {success_count}/{len(all_destinations)} destinations")
        return success_count > 0

    except Exception as e:
        print(f" [e] Error in smart routing for '{filename}': {e}")
        publish_status_update(
            doc_id=document_id,
            status="Routing Failed",
            details={"error": str(e), "processing_time": time.time() - start_time},
            is_vip=False
        )
        return False

def process_vip_document(message):
    """Enhanced VIP document processing with priority routing"""
    start_time = time.time()
    document_id = message.get('document_id', 'unknown_id')
    doc_type = message.get('doc_type', 'UNKNOWN')
    filename = message.get('filename', 'Unknown_File')
    confidence = message.get('confidence', 0.0)
    sender = message.get('sender', '')
    summary = message.get('summary', '')
    priority_content = message.get('priority_content', {})
    vip_status = message.get('vip_status', {})
    vip_level = vip_status.get('vip_level', 'medium')
    
    print(f"\n [👑] VIP Smart Routing for '{filename}' (Level: {vip_level})")
    
    try:
        # VIP documents get priority routing
        routing_info = {
            "primary_destination": "vip_priority_system",
            "all_destinations": ["vip_sheets", "vip_alerts", "priority_notifications"],
            "vip_level": vip_level,
            "fallback_used": False
        }
        
        success_count = 0
        
        # Always log VIP documents to sheets (both regular and VIP if configured)
        if log_to_google_sheet(filename, doc_type, confidence, True, vip_level, sender, summary,
                             "VIP Priority System", time.time() - start_time):
            success_count += 1
        
        # Send VIP-specific notifications
        send_enhanced_slack_alert(
            filename, 
            f"VIP DOCUMENT PROCESSED - Level: {vip_level.upper()}", 
            doc_type, True, vip_level, sender, priority_content, routing_info
        )
        success_count += 1
        
        # Send Teams notification for high-priority VIP docs
        if vip_level == 'high':
            send_teams_notification({**message, 'is_vip': True, 'vip_level': vip_level})
            success_count += 1
        
        # Route to appropriate business systems based on document type
        if doc_type == "CONTRACT" and DMS_SYSTEM_URL:
            if send_to_dms_system({**message, 'is_vip': True}):
                success_count += 1
        elif doc_type == "INVOICE" and ERP_SYSTEM_URL:
            if send_to_erp_system({**message, 'is_vip': True}):
                success_count += 1
        
        processing_time = time.time() - start_time
        
        publish_status_update(
            doc_id=document_id,
            status="VIP Routed",
            details={
                "vip_level": vip_level,
                "priority_items": len(priority_content) if priority_content else 0,
                "successful_routes": success_count,
                "processing_time": processing_time
            },
            doc_type=doc_type,
            confidence=confidence,
            is_vip=True,
            routing_info=routing_info
        )
        
        print(f"  -> VIP document '{filename}' routed successfully ({success_count} destinations)")
        return True

    except Exception as e:
        print(f" [e] Error in VIP routing for '{filename}': {e}")
        publish_status_update(
            doc_id=document_id,
            status="VIP Routing Failed",
            details={"error": str(e), "processing_time": time.time() - start_time},
            is_vip=True
        )
        return False

def main():
    """Enhanced main loop with system health monitoring"""
    connection = None
    while not connection:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            print(' [*] Successfully connected to RabbitMQ.')
        except pika.exceptions.AMQPConnectionError:
            print(" [!] RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

    channel = connection.channel()
    
    # Declare both queues
    channel.queue_declare(queue=CONSUME_QUEUE_NAME, durable=True)
    channel.queue_declare(queue=VIP_CONSUME_QUEUE_NAME, durable=True)
    
    print(' [*] 🚀 Enhanced Smart Router with AI-powered routing ready!')
    print(f' [*] System Health: {smart_router.system_health}')

    def regular_callback(ch, method, properties, body):
        """Handle regular documents with smart routing"""
        message = json.loads(body)
        try:
            if process_regular_document(message):
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                print(f" [!] Routing failed for {message.get('filename', 'unknown')}")
                # Could implement retry logic here
        except Exception as e:
            print(f" [e] Critical error in regular document processing: {e}")

    def vip_callback(ch, method, properties, body):
        """Handle VIP documents with priority routing"""
        message = json.loads(body)
        try:
            if process_vip_document(message):
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                print(f" [!] VIP routing failed for {message.get('filename', 'unknown')}")
                # VIP documents get immediate fallback attention
                send_enhanced_slack_alert(
                    message.get('filename', 'Unknown'),
                    "🚨 CRITICAL: VIP Document Routing Failed - Manual Intervention Required",
                    message.get('doc_type', 'UNKNOWN'),
                    True,
                    message.get('vip_status', {}).get('vip_level', 'high'),
                    message.get('sender', 'Unknown')
                )
        except Exception as e:
            print(f" [e] Critical error in VIP document processing: {e}")

    # Set up consumers for both queues with VIP priority
    channel.basic_consume(queue=VIP_CONSUME_QUEUE_NAME, on_message_callback=vip_callback)
    channel.basic_consume(queue=CONSUME_QUEUE_NAME, on_message_callback=regular_callback)
    
    # Set QoS to handle VIP documents with higher priority
    channel.basic_qos(prefetch_count=1)
    
    print(' [*] 🎯 Smart Router ready - VIP priority enabled, AI routing active!')
    print(' [*] 📊 Monitoring system health and routing performance...')
    
    # Periodic health check could be added here
    channel.start_consuming()

if __name__ == '__main__':
    try:
        print("🚀 Starting Enhanced Smart Router Agent...")
        print("📋 Features: AI Routing, VIP Priority, Multi-system Integration, Fallback Logic")
        main()
    except KeyboardInterrupt:
        print('\n🛑 Router shutdown requested')
        exit(0)
    except Exception as e:
        print(f'💥 Critical router error: {e}')
        exit(1)
        ##xoxb-9257542568709-9259002406498-C4XehLEmOTFfuxmJ9iUCX3KA