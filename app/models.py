from .extensions import db
from datetime import datetime

# EXAMPLE DATABASE MODELS FOR TESTING
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Relationship to link payments to this client
    payments = db.relationship('TaxPayment', backref='client', lazy=True)

class TaxPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    date_scheduled = db.Column(db.DateTime, default=datetime.utcnow)
    is_paid = db.Column(db.Boolean, default=False)
    # Foreign Key to link to the Client
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)