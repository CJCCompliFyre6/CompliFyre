# backend/app/models/download.py
from app import db
from datetime import datetime, timezone

class PolicyDocument(db.Model):
    __tablename__ = "policy_documents"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    url = db.Column(db.Text, nullable=False, unique=True)
    title = db.Column(db.String(255), nullable=False)
    size = db.Column(db.BigInteger, default=0)  # size in bytes, 0 if unknown

    created_at = db.Column(db.TIMESTAMP, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.TIMESTAMP, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))



class Download(db.Model):
    __tablename__ = "download"
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    data = db.Column(db.JSON, nullable=True)
    clause = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(50), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)



class File(db.Model):
    __tablename__ = "file"
    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), nullable=True)
    path = db.Column(db.String(500), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    data = db.Column(db.JSON, nullable=True)
    clause = db.Column(db.JSON, nullable=True)
    vector_store_id=db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_accessed = db.Column(db.DateTime)
    duplicate_count = db.Column(db.Integer, default=0)


class Prompts(db.Model):
    __tablename__ = "prompts"
    id = db.Column(db.Integer, primary_key=True)
    # prompt_description = db.Column(db.String(500), nullable=False)
    prompt = db.Column(db.String(100000), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "prompt": self.prompt,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
