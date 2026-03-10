import pytest
from app import create_app

@pytest.fixture
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
    )
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def test_app_runs(app):
    assert app is not None

def test_index_route_works(client):
    # Ensure the index route returns HTTP 200
    response = client.get("/")
    assert response.status_code == 200

def test_database_route_works(client):
    # Hit the /test-db route and assert it returns 200
    response = client.get("/test-db")
    assert response.status_code == 200
    assert b"Database Error" not in response.data