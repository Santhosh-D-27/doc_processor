import sqlite3
import json

def debug_details():
    conn = sqlite3.connect('state.db')
    cursor = conn.cursor()
    
    # Get raw details content
    cursor.execute("""
        SELECT document_id, details 
        FROM document_history 
        WHERE status='Extracted' 
        LIMIT 3
    """)
    
    records = cursor.fetchall()
    print(f"Raw details content from {len(records)} extracted records:")
    print("="*80)
    
    for i, record in enumerate(records, 1):
        doc_id, details = record
        print(f"\n{i}. Document ID: {doc_id}")
        print(f"   Details (raw): {details}")
        
        if details:
            try:
                details_dict = json.loads(details)
                print(f"   Details (parsed): {details_dict}")
            except json.JSONDecodeError as e:
                print(f"   JSON parse error: {e}")
        else:
            print(f"   Details is NULL/empty")
    
    # Also check what the extractor is supposed to send
    print("\n" + "="*80)
    print("Checking what the extractor should be sending...")
    
    # Check if there are any records with extracted_text
    cursor.execute("""
        SELECT document_id, details 
        FROM document_history 
        WHERE details LIKE '%extracted_text%'
        LIMIT 3
    """)
    
    text_records = cursor.fetchall()
    print(f"Records containing 'extracted_text': {len(text_records)}")
    
    for record in text_records:
        doc_id, details = record
        print(f"   {doc_id}: {details[:200]}...")
    
    conn.close()

if __name__ == "__main__":
    debug_details() 