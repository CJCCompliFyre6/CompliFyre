# app/models/chat.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class ChatSessions(db.Model):
    __tablename__ = "ChatSessions"
    session_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    start_time = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    end_time = db.Column(db.TIMESTAMP)

    # Relationships
    organization = db.relationship("Organizations", backref="chat_sessions")
    user = db.relationship("Users", backref="chat_sessions")


class ChatMessages(db.Model):
    __tablename__ = "ChatMessages"
    message_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    session_id = db.Column(db.BigInteger, db.ForeignKey("ChatSessions.session_id"))
    message_type = db.Column(Enum("user", "system", name="message_type_enum"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    referenced_data = db.Column(db.JSON)

    # Relationships
    session = db.relationship("ChatSessions", backref="chat_messages")
