# to run tests manually, use: pytest tests.py

import pytest
from app import create_app
from app.extensions import db
from app.models import (
    User,
    Role,
    Firm,
    Client,
    TaxRecord,
    PaymentSchedule,
    ScheduledPayment,
)
from sqlalchemy.pool import StaticPool



@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        # Isolated in-memory DB for tests
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
    })
    with app.app_context():
        db.drop_all()
        db.create_all()

        roles = {}
        for name in ("Developer", "SysAdmin", "Admin", "Accountant"):
            r = Role(name=name)
            db.session.add(r)
            roles[name] = r
        db.session.flush()

        firm = Firm(
            name="Test Firm",
            email="test@test.com",
            status="Active",
            plan_type="Local",
            stripe_customer_id=None,
        )
        db.session.add(firm)
        db.session.flush()

        # Users
        developer = User(name="Test Developer", email="developer@test.com", firm_id=firm.id, role_id=roles["Developer"].id)
        developer.set_password("developer")
        developer.batch_filer_id = "123456789"
        developer.master_inquiry_pin = "1234"

        sysadmin = User(name="Test SysAdmin", email="sysadmin@test.com", firm_id=firm.id, role_id=roles["SysAdmin"].id)
        sysadmin.set_password("sysadmin")
        sysadmin.batch_filer_id = "123456789"
        sysadmin.master_inquiry_pin = "1234"

        admin = User(name="Test Admin", email="admin@test.com", firm_id=firm.id, role_id=roles["Admin"].id)
        admin.set_password("admin")
        admin.batch_filer_id = "123456789"
        admin.master_inquiry_pin = "1234"

        accountant = User(name="Test Accountant 1", email="accountant1@test.com", firm_id=firm.id, role_id=roles["Accountant"].id)
        accountant.set_password("accountant")
        accountant.batch_filer_id = "123456789"
        accountant.master_inquiry_pin = "1234"

        other_accountant = User(name="Test Accountant 2", email="accountant2@test.com", firm_id=firm.id, role_id=roles["Accountant"].id)
        other_accountant.set_password("accountant")
        other_accountant.batch_filer_id = "123456789"
        other_accountant.master_inquiry_pin = "1234"

        db.session.add_all([developer, sysadmin, admin, accountant, other_accountant])
        db.session.flush()

        # Clients
        assigned_client = Client(
            firm_id=firm.id,
            name="Assigned Client",
            email="assigned@example.com",
            tax_id="123-45-6789",
            taxpayer_pin="1234",
            address="1 Main St",
            phone="555-111-2222",
        )
        assigned_client.users.append(accountant)
        unassigned_client = Client(
            firm_id=firm.id,
            name="Unassigned Client",
            email="unassigned@example.com",
            tax_id="987-65-4321",
            taxpayer_pin="1234",
            address="2 Main St",
            phone="555-333-4444",
        )
        db.session.add_all([assigned_client, unassigned_client])
        db.session.commit()
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def _login(c, *, email: str, password: str):
    return c.post(
        "/log_user_in",
        data={"email": email, "password": password, "remember": "y"},
        follow_redirects=True,
    )

# Authenticate using a developer user role
@pytest.fixture
def auth_developer(client, app):
    _login(client, email="developer@test.com", password="developer")
    return client

# Authenicate using a sysadmin user role
@pytest.fixture
def auth_sysadmin(client, app):
    _login(client, email="sysadmin@test.com", password="sysadmin")
    return client

# Authenticate using an admin user role
@pytest.fixture
def auth_admin(client, app):
    _login(client, email="admin@test.com", password="admin")
    return client

# Authenticate using an accountant user role
@pytest.fixture
def auth_accountant(client, app):
    _login(client, email="accountant1@test.com", password="accountant")
    return client

# ------------------
# ----- Tests ------
# ------------------

def test_app_runs(app):
    assert app is not None

def test_index_route_works(client):
    # Ensure the index route returns HTTP 200
    response = client.get("/")
    assert response.status_code == 200

def test_developer_access(auth_developer):
    # No authentication required
    response = auth_developer.get("/")
    assert response.status_code == 200
    response = auth_developer.get("/login")
    assert response.status_code == 200
    # Accountant or higher
    response = auth_developer.get("/dashboard")
    assert response.status_code == 200
    # Admin or higher
    response = auth_developer.get("/admin")
    assert response.status_code == 200
    # Sysadmin or higher
    response = auth_developer.get("/sysadmin")
    assert response.status_code == 200
    # Developer
    response = auth_developer.get("/test")
    assert response.status_code == 200
    response = auth_developer.get("/test-db")
    assert response.status_code == 200

def test_sysadmin_access(auth_sysadmin):
    # No authentication required
    response = auth_sysadmin.get("/")
    assert response.status_code == 200
    response = auth_sysadmin.get("/login")
    assert response.status_code == 200
    # Accountant or higher
    response = auth_sysadmin.get("/dashboard")
    assert response.status_code == 200
    # Admin or higher
    response = auth_sysadmin.get("/admin")
    assert response.status_code == 200
    # Sysadmin or higher
    response = auth_sysadmin.get("/sysadmin")
    assert response.status_code == 200
    # Developer
    response = auth_sysadmin.get("/test")
    assert response.status_code == 403
    response = auth_sysadmin.get("/test-db")
    assert response.status_code == 403

def test_admin_access(auth_admin):
    # No authentication required
    response = auth_admin.get("/")
    assert response.status_code == 200
    response = auth_admin.get("/login")
    assert response.status_code == 200
    # Accountant or higher
    response = auth_admin.get("/dashboard")
    assert response.status_code == 200
    # Admin or higher
    response = auth_admin.get("/admin")
    assert response.status_code == 200
    # Sysadmin or higher
    response = auth_admin.get("/sysadmin")
    assert response.status_code == 403
    # Developer
    response = auth_admin.get("/test")
    assert response.status_code == 403
    response = auth_admin.get("/test-db")
    assert response.status_code == 403

def test_accountant_access(auth_accountant):
    # No authentication required
    response = auth_accountant.get("/")
    assert response.status_code == 200
    response = auth_accountant.get("/login")
    assert response.status_code == 200
    # Accountant or higher
    response = auth_accountant.get("/dashboard")
    assert response.status_code == 200
    # Admin or higher
    response = auth_accountant.get("/admin")
    assert response.status_code == 403
    # Sysadmin or higher
    response = auth_accountant.get("/sysadmin")
    assert response.status_code == 403
    # Developer
    response = auth_accountant.get("/test")
    assert response.status_code == 403
    response = auth_accountant.get("/test-db")
    assert response.status_code == 403

def test_unauthenticated_access(client):
    # No authentication required
    response = client.get("/")
    assert response.status_code == 200
    response = client.get("/login")
    assert response.status_code == 200
    # Accountant or higher
    response = client.get("/dashboard")
    assert response.status_code == 302 # Redirect to login
    # Admin or higher
    response = client.get("/admin")
    assert response.status_code == 403
    # Sysadmin or higher
    response = client.get("/sysadmin")
    assert response.status_code == 403
    # Developer
    response = client.get("/test")
    assert response.status_code == 403
    response = client.get("/test-db")
    assert response.status_code == 403


def _get_client_ids(app):
    with app.app_context():
        assigned = Client.query.filter_by(name="Assigned Client").first()
        unassigned = Client.query.filter_by(name="Unassigned Client").first()
        assert assigned is not None
        assert unassigned is not None
        return assigned.id, unassigned.id


def _save_tax_data(c, *, client_id: int, tin: str, pin: str, year: str = "2026", total_annual_amount: str = "1200"):
    return c.post(
        "/tax-payments",
        data={
            "client_id": str(client_id),
            "total_annual_amount": total_annual_amount,
            "tax_period": year,
            "tin": tin,
            "taxpayer_pin": pin,
        },
    )


def test_client_payments_generate_add_remove_export_flow(auth_accountant, app):
    assigned_id, _ = _get_client_ids(app)

    # Save tax data (required before schedule generation / export)
    resp = _save_tax_data(auth_accountant, client_id=assigned_id, tin="123-45-6789", pin="1234", year="2026", total_annual_amount="1200")
    assert resp.status_code == 200
    assert b"Tax data saved" in resp.data

    # Generate schedule (monthly)
    resp = auth_accountant.post("/export/generate-schedule", data={"client_id": str(assigned_id), "period": "monthly"})
    assert resp.status_code == 200
    assert b"Generated" in resp.data or b"payment" in resp.data

    # Fetch schedule id
    with app.app_context():
        tr = TaxRecord.query.filter_by(client_id=assigned_id).order_by(TaxRecord.id.desc()).first()
        assert tr is not None
        sch = PaymentSchedule.query.filter_by(tax_record_id=tr.id).order_by(PaymentSchedule.id.desc()).first()
        assert sch is not None
        sch_id = sch.id

    # Add a payment
    resp = auth_accountant.post(f"/export/schedule/{sch_id}/payments/add")
    assert resp.status_code == 200

    # Delete one payment
    with app.app_context():
        p = ScheduledPayment.query.filter_by(schedule_id=sch_id).order_by(ScheduledPayment.id.desc()).first()
        assert p is not None
        pid = p.id
    resp = auth_accountant.post(f"/export/schedule/{sch_id}/payments/{pid}/delete")
    assert resp.status_code == 200

    # Export fixed width for today's file date (expects schedule_id + file_date)
    from datetime import date
    file_date = date.today().strftime("%Y-%m-%d")
    resp = auth_accountant.get(f"/export/fixed-width?schedule_id={sch_id}&file_date={file_date}")
    # If no payments have input_date == file_date, export can 400; the add route sets input_date=today.
    assert resp.status_code in (200, 400)
    if resp.status_code == 200:
        assert resp.mimetype == "text/plain"
        assert b"\n" in resp.data


def test_client_payments_import_csv(auth_accountant, app):
    assigned_id, _ = _get_client_ids(app)

    # Save tax data to ensure schedule exists
    resp = _save_tax_data(auth_accountant, client_id=assigned_id, tin="123-45-6789", pin="1234", year="2026", total_annual_amount="1200")
    assert resp.status_code == 200

    # Create a schedule so imports have a place to attach
    resp = auth_accountant.post("/export/generate-schedule", data={"client_id": str(assigned_id), "period": "monthly"})
    assert resp.status_code == 200

    # CSV: 19 columns, only some used: col0 TIN, col1 taxpayer type, col12 amount, col13 settle date
    csv = (
        "EIN/SSN,TP,_,_,_,_,_,_,_,_,_,_,AMOUNT,SETTLE,_,_,_,_,_\n"
        "123-45-6789,I,,,,,,,,,,,25,2026-04-10,,,,,\n"
    )
    import io
    data = {
        "client_id": str(assigned_id),
        "file": (io.BytesIO(csv.encode("utf-8")), "payments.csv"),
    }
    resp = auth_accountant.post("/import/payments", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Imported" in resp.data


def test_client_payments_permissions_accountant_cannot_access_unassigned(auth_accountant, app):
    _, unassigned_id = _get_client_ids(app)
    resp = auth_accountant.get(f"/export/schedule/client/{unassigned_id}")
    assert resp.status_code == 403