from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date,
    ForeignKey, Text, Numeric, Table
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

# =========================
# ASSOCIATION TABLES (Many-to-Many)
# =========================
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

user_permissions = Table(
    'user_permissions',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

client_assignments = Table(
    'client_assignments',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('client_id', Integer, ForeignKey('clients.id', ondelete='CASCADE'), primary_key=True)
)

export_items = Table(
    'export_items',
    Base.metadata,
    Column('export_id', Integer, ForeignKey('exports.id', ondelete='CASCADE'), primary_key=True),
    Column('payment_id', Integer, ForeignKey('scheduled_payments.id', ondelete='CASCADE'), primary_key=True)
)


# =========================
# MODELS
# =========================
class Firm(Base):
    __tablename__ = 'firms'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    plan_type = Column(String(50))
    status = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    users = relationship('User', back_populates='firm', cascade='all, delete-orphan')
    clients = relationship('Client', back_populates='firm', cascade='all, delete-orphan')
    subscriptions = relationship('Subscription', back_populates='firm', cascade='all, delete-orphan')


class Role(Base):
    __tablename__ = 'roles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)

    # Relationships
    users = relationship('User', back_populates='role')
    permissions = relationship('Permission', secondary=role_permissions, back_populates='roles')


class Permission(Base):
    __tablename__ = 'permissions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)

    # Relationships
    roles = relationship('Role', secondary=role_permissions, back_populates='permissions')
    users = relationship('User', secondary=user_permissions, back_populates='permissions')


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    firm_id = Column(Integer, ForeignKey('firms.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    firm = relationship('Firm', back_populates='users')
    role = relationship('Role', back_populates='users')
    permissions = relationship('Permission', secondary=user_permissions, back_populates='users')
    clients = relationship('Client', secondary=client_assignments, back_populates='users')
    tax_records = relationship('TaxRecord', back_populates='uploaded_by_user')
    payment_schedules = relationship('PaymentSchedule', back_populates='created_by_user')
    exports = relationship('Export', back_populates='user')
    audit_logs = relationship('AuditLog', back_populates='user')


class Client(Base):
    __tablename__ = 'clients'

    id = Column(Integer, primary_key=True, autoincrement=True)
    firm_id = Column(Integer, ForeignKey('firms.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))
    tax_id = Column(String(50))
    address = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    firm = relationship('Firm', back_populates='clients')
    users = relationship('User', secondary=client_assignments, back_populates='clients')
    tax_records = relationship('TaxRecord', back_populates='client', cascade='all, delete-orphan')


class TaxRecord(Base):
    __tablename__ = 'tax_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    tax_year = Column(Integer, nullable=False)  # SQLAlchemy doesn't have a native YEAR type universally
    estimated_tax_total = Column(Numeric(12, 2), nullable=False)
    upload_source = Column(String(255))
    uploaded_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    client = relationship('Client', back_populates='tax_records')
    uploaded_by_user = relationship('User', back_populates='tax_records')
    payment_schedules = relationship('PaymentSchedule', back_populates='tax_record', cascade='all, delete-orphan')


class PaymentSchedule(Base):
    __tablename__ = 'payment_schedules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tax_record_id = Column(Integer, ForeignKey('tax_records.id', ondelete='CASCADE'), nullable=False)
    schedule_name = Column(String(255))
    start_date = Column(Date)
    end_date = Column(Date)
    frequency = Column(String(50))
    total_amount = Column(Numeric(12, 2))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    tax_record = relationship('TaxRecord', back_populates='payment_schedules')
    created_by_user = relationship('User', back_populates='payment_schedules')
    scheduled_payments = relationship('ScheduledPayment', back_populates='schedule', cascade='all, delete-orphan')


class ScheduledPayment(Base):
    __tablename__ = 'scheduled_payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey('payment_schedules.id', ondelete='CASCADE'), nullable=False)
    due_date = Column(Date, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(50), default='pending')

    # Relationships
    schedule = relationship('PaymentSchedule', back_populates='scheduled_payments')
    exports = relationship('Export', secondary=export_items, back_populates='payments')


class Export(Base):
    __tablename__ = 'exports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    generated_at = Column(DateTime, server_default=func.now(), index=True)
    file_path = Column(String(255))
    status = Column(String(50))

    # Relationships
    user = relationship('User', back_populates='exports')
    payments = relationship('ScheduledPayment', secondary=export_items, back_populates='exports')


class Subscription(Base):
    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    firm_id = Column(Integer, ForeignKey('firms.id', ondelete='CASCADE'), nullable=False)
    plan = Column(String(100))
    price = Column(Numeric(10, 2))
    billing_cycle = Column(String(50))
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String(50))

    # Relationships
    firm = relationship('Firm', back_populates='subscriptions')
    billing_payments = relationship('BillingPayment', back_populates='subscription', cascade='all, delete-orphan')


class BillingPayment(Base):
    __tablename__ = 'billing_payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey('subscriptions.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Numeric(10, 2))
    payment_date = Column(DateTime, server_default=func.now())
    payment_method = Column(String(100))
    status = Column(String(50))

    # Relationships
    subscription = relationship('Subscription', back_populates='billing_payments')


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    action = Column(String(255))
    entity_type = Column(String(100))
    entity_id = Column(Integer)
    ip_address = Column(String(45))
    timestamp = Column(DateTime, server_default=func.now())

    # Relationships
    user = relationship('User', back_populates='audit_logs')


class PermissionLog(Base):
    __tablename__ = 'permission_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    target_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    permission_id = Column(Integer, ForeignKey('permissions.id', ondelete='SET NULL'))
    action = Column(String(50))
    timestamp = Column(DateTime, server_default=func.now())

    # Relationships
    admin_user = relationship('User', foreign_keys=[admin_user_id])
    target_user = relationship('User', foreign_keys=[target_user_id])
    permission = relationship('Permission')
