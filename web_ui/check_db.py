import sqlite3
import json

def check_database():
    conn = sqlite3.connect('state.db')
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("Tables in database:")
    for table in tables:
        print(f"  - {table[0]}")
    
    print("\n" + "="*50)
    
    # Check document_status table structure
    cursor.execute("PRAGMA table_info(document_status)")
    columns = cursor.fetchall()
    print("document_status table columns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    print("\n" + "="*50)
    
    # Check document_history table structure
    cursor.execute("PRAGMA table_info(document_history)")
    columns = cursor.fetchall()
    print("document_history table columns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    print("\n" + "="*50)
    
    # Check sample documents
    cursor.execute("SELECT document_id, filename, status, doc_type FROM document_status LIMIT 5")
    docs = cursor.fetchall()
    print(f"Sample documents ({len(docs)} found):")
    for doc in docs:
        print(f"  - {doc[0]}: {doc[1]} ({doc[2]}) - Type: {doc[3]}")
    
    print("\n" + "="*50)
    
    # Check if we have extracted data
    cursor.execute("SELECT document_id, status, details FROM document_history WHERE status='Extracted' LIMIT 3")
    extracted = cursor.fetchall()
    print(f"Extracted documents ({len(extracted)} found):")
    for ext in extracted:
        print(f"  - {ext[0]}: {ext[1]}")
        if ext[2]:
            try:
                details = json.loads(ext[2])
                if 'extracted_text' in details:
                    text_preview = details['extracted_text'][:100] + "..." if len(details['extracted_text']) > 100 else details['extracted_text']
                    print(f"    Text preview: {text_preview}")
                else:
                    print(f"    No extracted_text in details")
            except:
                print(f"    Could not parse details JSON")
    
    print("\n" + "="*50)
    
    # Check for file_content_encoded
    cursor.execute("SELECT document_id, file_content_encoded FROM document_history WHERE file_content_encoded IS NOT NULL LIMIT 3")
    encoded_files = cursor.fetchall()
    print(f"Documents with encoded file content ({len(encoded_files)} found):")
    for file in encoded_files:
        print(f"  - {file[0]}: Has encoded content ({len(file[1]) if file[1] else 0} chars)")
    
    conn.close()

if __name__ == "__main__":
    check_database() 