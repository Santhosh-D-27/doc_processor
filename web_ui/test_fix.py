import sqlite3
import json
import time

def test_extracted_text_storage():
    """Test if extracted text is now being stored properly"""
    conn = sqlite3.connect('state.db')
    cursor = conn.cursor()
    
    print("🔍 Testing extracted text storage...")
    print("="*60)
    
    # Check recent extracted records
    cursor.execute("""
        SELECT document_id, status, details, timestamp 
        FROM document_history 
        WHERE status='Extracted' 
        ORDER BY timestamp DESC 
        LIMIT 3
    """)
    
    records = cursor.fetchall()
    print(f"Found {len(records)} recent extracted records:")
    
    for i, record in enumerate(records, 1):
        doc_id, status, details, timestamp = record
        print(f"\n{i}. Document ID: {doc_id}")
        print(f"   Status: {status}")
        print(f"   Timestamp: {timestamp}")
        
        if details:
            try:
                details_dict = json.loads(details)
                print(f"   Details keys: {list(details_dict.keys())}")
                
                # Check for extracted_text
                if 'extracted_text' in details_dict:
                    text = details_dict['extracted_text']
                    print(f"   ✅ EXTRACTED TEXT FOUND! Length: {len(text)} characters")
                    print(f"   Text preview: {text[:200]}...")
                else:
                    print(f"   ❌ No extracted_text found")
                
                # Check for other fields
                if 'chars_extracted' in details_dict:
                    print(f"   Characters extracted: {details_dict['chars_extracted']}")
                
                if 'processing_time' in details_dict:
                    print(f"   Processing time: {details_dict['processing_time']:.2f}s")
                    
            except json.JSONDecodeError:
                print(f"   ❌ Could not parse details JSON")
        else:
            print(f"   ❌ No details field")
    
    print("\n" + "="*60)
    print("SUMMARY:")
    
    # Count records with extracted_text
    cursor.execute("""
        SELECT COUNT(*) FROM document_history 
        WHERE status='Extracted' AND details LIKE '%extracted_text%'
    """)
    count_with_text = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM document_history 
        WHERE status='Extracted'
    """)
    total_extracted = cursor.fetchone()[0]
    
    print(f"Total extracted records: {total_extracted}")
    print(f"Records with extracted_text: {count_with_text}")
    
    if count_with_text > 0:
        print("✅ FIX SUCCESSFUL! Extracted text is now being stored.")
        print("✅ Re-classify should now work properly!")
    else:
        print("❌ No records with extracted_text found yet.")
        print("   This might be because no new documents have been processed since the fix.")
    
    conn.close()

if __name__ == "__main__":
    test_extracted_text_storage() 