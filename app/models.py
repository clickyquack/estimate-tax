from .extensions import db
from sqlalchemy.sql import func

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import login_manager

from cryptography.fernet import Fernet
import os


cipher = Fernet(os.environ.get('ENCRYPTION_KEY').encode())

# Helper function to create encrypted properties
def encrypted_property(attr_name):
    @property
    def getter(self):
        encrypted_val = getattr(self, attr_name)
        # If there's no encrypted data, just show blank field
        if not encrypted_val:
            return None
        # If the data exists but the ENCRYPTION_KEY is missing from .env
        if not cipher:
            return "[Key Missing]"   
        # Try to decrypt
        try:
            return cipher.decrypt(encrypted_val.encode()).decode()
        except Exception:
            # Wrong key or something
            return "[Encrypted]"

    @getter.setter
    def setter(self, value):
        if value:
            encrypted_val = cipher.encrypt(value.encode()).decode()
            setattr(self, attr_name, encrypted_val)
        else:
            setattr(self, attr_name, None)

    return setter # object with both getter and setter


# =========================
# ASSOCIATION TABLES (Many-to-Many)
# =========================
role_permissions = db.Table(
    'role_permissions',
    db.metadata,
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

user_permissions = db.Table(
    'user_permissions',
    db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

client_assignments = db.Table(
    'client_assignments',
    db.metadata,
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('client_id', db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), primary_key=True)
)

export_items = db.Table(
    'export_items',
    db.metadata,
    db.Column('export_id', db.Integer, db.ForeignKey('exports.id', ondelete='CASCADE'), primary_key=True),
    db.Column('payment_id', db.Integer, db.ForeignKey('scheduled_payments.id', ondelete='CASCADE'), primary_key=True)
)


# =========================
# MODELS
# =========================
class Firm(db.Model):
    __tablename__ = 'firms'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    plan_type = db.Column(db.String(50))
    status = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, server_default=func.now())
    stripe_customer_id = db.Column(db.String(255))

    # Relationships
    users = db.relationship('User', back_populates='firm', cascade='all, delete-orphan')
    clients = db.relationship('Client', back_populates='firm', cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', back_populates='firm', cascade='all, delete-orphan')


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False, unique=True)

    # Relationships
    users = db.relationship('User', back_populates='role')
    permissions = db.relationship('Permission', secondary=role_permissions, back_populates='roles')


class Permission(db.Model):
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    # Relationships
    roles = db.relationship('Role', secondary=role_permissions, back_populates='permissions')
    users = db.relationship('User', secondary=user_permissions, back_populates='permissions')


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    # Relationships
    firm = db.relationship('Firm', back_populates='users')
    role = db.relationship('Role', back_populates='users')
    permissions = db.relationship('Permission', secondary=user_permissions, back_populates='users')
    clients = db.relationship('Client', secondary=client_assignments, back_populates='users')
    tax_records = db.relationship('TaxRecord', back_populates='uploaded_by_user')
    payment_schedules = db.relationship('PaymentSchedule', back_populates='created_by_user')
    exports = db.relationship('Export', back_populates='user')
    audit_logs = db.relationship('AuditLog', back_populates='user')

    # User Functions
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    # Hierarchical role checks
    def is_developer(self):
        return self.role.name == 'Developer'
    def is_sysadmin(self):
        return (self.role.name == 'SysAdmin' or self.role.name == 'Developer')
    def is_admin(self):
        return (self.role.name == 'Admin' or self.role.name == 'SysAdmin' or self.role.name == 'Developer')
    def is_accountant(self):
        return (self.role.name == 'Accountant' or self.role.name == 'Admin' or self.role.name == 'SysAdmin' or self.role.name == 'Developer')
    
# Flask-Login user loader
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Client(db.Model):
    __tablename__ = 'clients'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, server_default=func.now())

    # Ecrypted fields
    _tax_id_encrypted = db.Column('tax_id', db.Text)
    tax_id = encrypted_property('_tax_id_encrypted')
    _address_encrypted = db.Column('address', db.Text)
    address = encrypted_property('_address_encrypted')
    _phone_encrypted = db.Column('phone', db.Text)
    phone = encrypted_property('_phone_encrypted')

    # Relationships
    firm = db.relationship('Firm', back_populates='clients')
    users = db.relationship('User', secondary=client_assignments, back_populates='clients')
    tax_records = db.relationship('TaxRecord', back_populates='client', cascade='all, delete-orphan')


class TaxRecord(db.Model):
    __tablename__ = 'tax_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    tax_year = db.Column(db.Integer, nullable=False)  # SQLAlchemy doesn't have a native YEAR type universally
    estimated_tax_total = db.Column(db.Numeric(12, 2), nullable=False)
    upload_source = db.Column(db.String(255))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, server_default=func.now())
    
    # --- Added field ---
    tax_form = db.Column(db.String(10), nullable=False)
    tax_type_code = db.Column(db.String(5), nullable=False)
    taxpayer_type = db.Column(db.String(1), nullable=False)
    description = db.Column(db.String(255))

    # Relationships
    client = db.relationship('Client', back_populates='tax_records')
    uploaded_by_user = db.relationship('User', back_populates='tax_records')
    payment_schedules = db.relationship('PaymentSchedule', back_populates='tax_record', cascade='all, delete-orphan')


class PaymentSchedule(db.Model):
    __tablename__ = 'payment_schedules'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tax_record_id = db.Column(db.Integer, db.ForeignKey('tax_records.id', ondelete='CASCADE'), nullable=False)
    schedule_name = db.Column(db.String(255))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    frequency = db.Column(db.String(50))
    total_amount = db.Column(db.Numeric(12, 2))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, server_default=func.now())

    # Relationships
    tax_record = db.relationship('TaxRecord', back_populates='payment_schedules')
    created_by_user = db.relationship('User', back_populates='payment_schedules')
    scheduled_payments = db.relationship('ScheduledPayment', back_populates='schedule', cascade='all, delete-orphan')


class ScheduledPayment(db.Model):
    __tablename__ = 'scheduled_payments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('payment_schedules.id', ondelete='CASCADE'))
    due_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(50), default='pending')
    
    # --- Added field ---
    tax_period = db.Column(db.String(6), nullable=False)
    input_method = db.Column(db.String(1), nullable=False)
    transaction_code = db.Column(db.String(10))
    input_date = db.Column(db.Date, server_default=func.current_date())
    input_time = db.Column(db.Time, server_default=func.current_time())
    payment_status = db.Column(db.String(50))
    # Encrypted fields
    _eft_number_encrypted = db.Column('eft_number', db.Text)
    eft_number = encrypted_property('_eft_number_encrypted')
    _original_eft_number_encrypted = db.Column('original_eft_number', db.Text)
    original_eft_number = encrypted_property('_original_eft_number_encrypted')
    _ach_trace_number_encrypted = db.Column('ach_trace_number', db.Text)
    ach_trace_number = encrypted_property('_ach_trace_number_encrypted')
    _cancellation_eft_number_encrypted = db.Column('cancellation_eft_number', db.Text)
    cancellation_eft_number = encrypted_property('_cancellation_eft_number_encrypted')
    _bulk_debit_trace_number_encrypted = db.Column('bulk_debit_trace_number', db.Text)
    bulk_debit_trace_number = encrypted_property('_bulk_debit_trace_number_encrypted')
    _bulk_debit_cancellation_number_encrypted = db.Column('bulk_debit_cancellation_number', db.Text)
    bulk_debit_cancellation_number = encrypted_property('_bulk_debit_cancellation_number_encrypted')

    # Relationships
    schedule = db.relationship('PaymentSchedule', back_populates='scheduled_payments')
    exports = db.relationship('Export', secondary=export_items, back_populates='payments')


class Export(db.Model):
    __tablename__ = 'exports'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    generated_at = db.Column(db.DateTime, server_default=func.now(), index=True)
    file_path = db.Column(db.String(255))
    status = db.Column(db.String(50))

    # Relationships
    user = db.relationship('User', back_populates='exports')
    payments = db.relationship('ScheduledPayment', secondary=export_items, back_populates='exports')


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id', ondelete='CASCADE'), nullable=False)
    plan = db.Column(db.String(100))
    price = db.Column(db.Numeric(10, 2))
    billing_cycle = db.Column(db.String(50))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(50))

    # Relationships
    firm = db.relationship('Firm', back_populates='subscriptions')
    billing_payments = db.relationship('BillingPayment', back_populates='subscription', cascade='all, delete-orphan')


class BillingPayment(db.Model):
    __tablename__ = 'billing_payments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id', ondelete='CASCADE'), nullable=False)
    amount = db.Column(db.Numeric(10, 2))
    payment_date = db.Column(db.DateTime, server_default=func.now())
    payment_method = db.Column(db.String(100))
    status = db.Column(db.String(50))

    # Relationships
    subscription = db.relationship('Subscription', back_populates='billing_payments')


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    action = db.Column(db.String(255))
    entity_type = db.Column(db.String(100))
    entity_id = db.Column(db.Integer)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, server_default=func.now())

    # Relationships
    user = db.relationship('User', back_populates='audit_logs')


class PermissionLog(db.Model):
    __tablename__ = 'permission_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id', ondelete='SET NULL'))
    action = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, server_default=func.now())

    # Relationships
    admin_user = db.relationship('User', foreign_keys=[admin_user_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    permission = db.relationship('Permission')
