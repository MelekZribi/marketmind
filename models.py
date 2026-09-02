"""
Modeles de base de donnees pour MarketMind.
- User : un compte personnel (nom d'utilisateur + mot de passe hache)
- Conversation : une discussion (comme un "chat" dans ChatGPT/Claude)
- Message : chaque message individuel (role user ou assistant) dans une conversation
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversations = db.relationship(
        "Conversation", backref="utilisateur",
        order_by="desc(Conversation.updated_at)", lazy=True,
        cascade="all, delete-orphan",
    )


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), default="Nouvelle discussion")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages = db.relationship(
        "Message", backref="conversation",
        order_by="Message.created_at", lazy=True,
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # "user" ou "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)