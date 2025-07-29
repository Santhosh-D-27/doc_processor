# web_ui/database.py (UPDATED)
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, Boolean # Import Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, UTC # Import UTC

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
    __tablename__ = "document_status" # Renamed to match the sqlite3 table name in web_ui/main.py

    document_id = Column(String, primary_key=True, index=True) # Unique ID for the document (e.g., hash or unique identifier)
    filename = Column(String, index=True, nullable=False)
    status = Column(String, default="Ingested", nullable=False) # Renamed from current_status
    doc_type = Column(String, nullable=True) # Classified type (e.g., INVOICE, RESUME)
    confidence = Column(Float, nullable=True) # Confidence score from classifier
    last_updated = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC), nullable=False) # Use datetime.now(UTC)

    # New fields for VIP and summarization features
    is_vip = Column(Boolean, default=False, nullable=False)
    vip_level = Column(String, nullable=True) # E.g., 'HIGH', 'MEDIUM', 'LOW', 'NONE'
    summary = Column(Text, nullable=True) # 2-3 sentence summary
    priority_content = Column(Text, nullable=True) # JSON string of priority content

class DocumentHistory(Base): # Renamed from DocumentStep
    """
    Records each step a document goes through in the pipeline.
    This provides the history for the progress bar and hover details.
    """
    __tablename__ = "document_history"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, index=True, nullable=False) # Foreign key to Document
    status = Column(String, nullable=False) # Renamed from step_name
    timestamp = Column(DateTime, default=datetime.now(UTC), nullable=False) # Use datetime.now(UTC)
    details = Column(Text, nullable=True) # JSON string of details
    doc_type = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    file_content_encoded = Column(Text, nullable=True) # Stored raw file on ingest

    # Additional fields for history if relevant (matching status updates)
    is_vip = Column(Boolean, default=False, nullable=False)
    vip_level = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    priority_content = Column(Text, nullable=True)


class MailboxConfig(Base):
    """
    Stores configuration and authentication tokens for connected email mailboxes.
    """
    __tablename__ = "mailboxes" # Match the sqlite3 table name in web_ui/main.py

    id = Column(Integer, primary_key=True, index=True) # Changed to Integer to match existing DB
    email = Column(String, unique=True, nullable=False)
    app_password_encoded = Column(String, nullable=False)
    folder = Column(String, nullable=False)
    status = Column(String, default='Pending')
    status_timestamp = Column(DateTime, nullable=True) # Ensure this is DateTime

class VIPDocument(Base):
    """
    Stores metadata and analysis specific to VIP documents.
    """
    __tablename__ = "vip_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, unique=True, nullable=False) # Link to main document
    filename = Column(String, nullable=False)
    vip_level = Column(String, nullable=False) # HIGH, MEDIUM, LOW
    sender = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    priority_content = Column(Text, nullable=True) # JSON string
    status = Column(String, default="Pending Review", nullable=False) # E.g., "Pending Review", "Reviewed", "Archived"
    risk_assessment = Column(String, nullable=True) # E.g., "Low", "Medium", "High"
    last_updated = Column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC), nullable=False)

class VIPContact(Base):
    """
    Manages a directory of VIP contacts for identification.
    """
    __tablename__ = "vip_contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    vip_level = Column(String, nullable=False) # HIGH, MEDIUM, LOW
    department = Column(String, nullable=True)
    role = Column(String, nullable=True)
    added_at = Column(DateTime, default=datetime.now(UTC), nullable=False)

# Create a SessionLocal class to get a database session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Function to create all tables
def create_db_tables():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")

# Dependency to get DB session (for FastAPI)
# This part is for SQLAlchemy, but web_ui/main.py uses raw sqlite3.
# The user's request implies they want me to adapt the existing code.
# I will keep this for completeness if they decide to switch to SQLAlchemy ORM,
# but the main.py will be updated with raw sqlite3 operations.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()