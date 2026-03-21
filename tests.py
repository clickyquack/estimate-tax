# to run tests manually, use: pytest tests.py

import pytest
from app import create_app
from app.models import User, Role

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
    })
    return app

@pytest.fixture
def client(app):
    return app.test_client()

# Authenticate using a developer user role
@pytest.fixture
def auth_developer(client, app):
    with app.app_context():
        # Target the developer user created by sample_data.py
        user = User.query.filter_by(email="developer@test.com").first()
        if not user:
            pytest.fail("Developer user not found. Ensure sample_data.py ran correctly.")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True   
    return client

# Authenicate using a sysadmin user role
@pytest.fixture
def auth_sysadmin(client, app):
    with app.app_context():
        # Target the sysadmin user created by sample_data.py
        user = User.query.filter_by(email="sysadmin@test.com").first()
        if not user:
            pytest.fail("SysAdmin user not found. Ensure sample_data.py ran correctly.")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True   
    return client

# Authenticate using an admin user role
@pytest.fixture
def auth_admin(client, app):
    with app.app_context():
        # Target the admin user created by sample_data.py
        user = User.query.filter_by(email="admin@test.com").first()
        if not user:
            pytest.fail("Admin user not found. Ensure sample_data.py ran correctly.")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True   
    return client

# Authenticate using an accountant user role
@pytest.fixture
def auth_accountant(client, app):
    with app.app_context():
        # Target the accountant user created by sample_data.py
        user = User.query.filter_by(email="accountant1@test.com").first()
        if not user:
            pytest.fail("Accountant user not found. Ensure sample_data.py ran correctly.")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True   
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