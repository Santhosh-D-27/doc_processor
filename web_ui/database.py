# web_ui/database.py (UPDATED)
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os # Import os for path manipulation

# SQLite database URL. 'state.db' will be created IN THE SAME DIRECTORY AS THIS FILE.
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Get the directory of database.py
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'state.db')}"

# Create the SQLAlchemy engine
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} # Needed for SQLite with FastAPI/multi-threading
)


# Base class for declarative models
Base = declarative_base()

# --- Database Models ---

class Document(Base):
    """
    Represents a document in the pipeline, tracking its latest status.
    """
    __tablename__ = "documents"

    id = Column(String, primary_key=True, index=True) # Unique ID for the document (e.g., hash or unique identifier)
    filename = Column(String, index=True, nullable=False)
    current_status = Column(String, default="Ingested", nullable=False)
    doc_type = Column(String, nullable=True) # Classified type (e.g., INVOICE, RESUME)
    confidence = Column(Float, nullable=True) # Confidence score from classifier
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # You might add more fields here like source, original_size, etc.

class DocumentStep(Base):
    """
    Records each step a document goes through in the pipeline.
    This provides the history for the progress bar and hover details.
    """
    __tablename__ = "document_history"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, index=True, nullable=False) # Foreign key to Document
    step_name = Column(String, nullable=False) # e.g., "Ingested", "Extracted", "Classified", "Routed"
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    details = Column(Text, nullable=True) # e.g., "OCR took 3.2s", "Type=Contract (94% confidence)"
    # You might add more specific metrics here if needed
class MailboxConfig(Base):
    """
    Stores configuration and authentication tokens for connected email mailboxes.
    """
    __tablename__ = "mailbox_configs"

    id = Column(String, primary_key=True, index=True) # Unique ID for this mailbox config (e.g., UUID)
    user_id = Column(String, nullable=False) # Identifies which UI user connected this mailbox (if you add user auth later)
    email_address = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False, default="Gmail") # e.g., "Gmail", "Outlook"
    
    # OAuth Tokens - Sensitive, ideally encrypted in production
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True) # Important for long-lived access
    token_expiry = Column(DateTime, nullable=True)

    # Monitoring Settings
    folders_to_monitor = Column(String, default="Inbox", nullable=False) # Comma-separated list (e.g., "Inbox,Invoices")
    filter_sender_whitelist = Column(Text, nullable=True) # JSON string of list of senders
    filter_subject_keywords = Column(Text, nullable=True) # JSON string of list of keywords
    filter_file_types = Column(String, nullable=True) # Comma-separated (e.g., "pdf,docx")

    # Status & Metadata
    is_active = Column(Integer, default=1) # 1 for active, 0 for inactive
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
# Create a SessionLocal class to get a database session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Function to create all tables
def create_db_tables():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")

# Dependency to get DB session (for FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()