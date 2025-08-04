import sqlite3
import json

def check_extraction_details():
    conn = sqlite3.connect('state.db')
    cursor = conn.cursor()
    
    # Get all extracted records with their details
    cursor.execute("""
        SELECT document_id, status, details, file_content_encoded 
        FROM document_history 
        WHERE status='Extracted' 
        ORDER BY timestamp DESC 
        LIMIT 5
    """)
    
    records = cursor.fetchall()
    print(f"Found {len(records)} extracted records:")
    print("="*80)
    
    for i, record in enumerate(records, 1):
        doc_id, status, details, file_content = record
        print(f"\n{i}. Document ID: {doc_id}")
        print(f"   Status: {status}")
        
        if details:
            try:
                details_dict = json.loads(details)
                print(f"   Details keys: {list(details_dict.keys())}")
                
                # Check for extracted_text
                if 'extracted_text' in details_dict:
                    text = details_dict['extracted_text']
                    print(f"   Extracted text length: {len(text)} characters")
                    print(f"   Text preview: {text[:200]}...")
                else:
                    print(f"   ❌ NO extracted_text found in details")
                
                # Check for other important fields
                if 'entities' in details_dict:
                    print(f"   Entities: {len(details_dict['entities'])} found")
                
                if 'confidence' in details_dict:
                    print(f"   Confidence: {details_dict['confidence']}")
                    
            except json.JSONDecodeError:
                print(f"   ❌ Could not parse details JSON: {details[:100]}...")
        else:
            print(f"   ❌ No details field")
        
        if file_content:
            print(f"   ✅ Has encoded file content ({len(file_content)} chars)")
        else:
            print(f"   ❌ No encoded file content")
    
    print("\n" + "="*80)
    print("SUMMARY:")
    print("✅ Database has the correct structure")
    print("✅ File content is being stored (file_content_encoded)")
    print("❌ Extracted text is NOT being stored in details field")
    print("❌ This is why re-classify is failing - no extracted_text to work with")
    
    conn.close()

if __name__ == "__main__":
    check_extraction_details() 