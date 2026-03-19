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
    tin = db.Column(db.String(9), nullable=False)
    taxpayer_type_code = db.Column(db.String(1), nullable=False)
    eft_number = db.Column(db.String(15), nullable=False)
    original_eft_number = db.Column(db.String(15), nullable=True)
    cancellation_eft_number = db.Column(db.String(15), nullable=True)
    bulk_debit_trace_number = db.Column(db.String(64), nullable=True)
    bulk_debit_cancellation_number = db.Column(db.String(64), nullable=True)
    payment_input_method = db.Column(db.String(1), nullable=True)
    tax_form = db.Column(db.String(16), nullable=False)
    tax_form_description = db.Column(db.String(255), nullable=True)
    tax_type = db.Column(db.String(32), nullable=False)
    tax_period = db.Column(db.String(8), nullable=False)
    settlement_date = db.Column(db.Date, nullable=False)
    ach_trace_number = db.Column(db.String(64), nullable=True)
    payment_status = db.Column(db.String(32), nullable=True)
    transaction_code = db.Column(db.String(32), nullable=True)
    input_date = db.Column(db.Date, nullable=True)
    input_time = db.Column(db.Time, nullable=True)
    date_scheduled = db.Column(db.DateTime, default=datetime.utcnow)
    is_paid = db.Column(db.Boolean, default=False)
    # Foreign Key to link to the Client
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)