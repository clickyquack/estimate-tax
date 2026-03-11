from flask import Flask, render_template, request, redirect, url_for

from .extensions import db
from config import Config


def create_app():
    app = Flask(__name__)
    
    # -----------------------------------
    # ------------ DATABASE -------------
    # -----------------------------------

    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        from . import models
        db.create_all()



    # -----------------------------------
    # ------------- ROUTES --------------
    # -----------------------------------

    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/login')
    def login():
        return render_template('login.html')
    
    @app.route('/login_user', methods=['POST'])
    def login_user():
        return redirect(url_for('login'))
    
    @app.route('/dashboard')
    def dashboard():
        from .models import Client
        
        all_clients = Client.query.all() # Query all clients from the database
        return render_template('dashboard.html', clients=all_clients)
    
    @app.route('/admin')
    def admin():
        return render_template('admin.html')
    
    @app.route('/sysadmin')
    def sysadmin():
        return render_template('sysadmin.html')



    # ------------------------------------
    # ----------- TEST ROUTES ------------
    # ------------------------------------
    
    # Test route
    @app.route('/test')
    def test():
        return render_template('test.html')

    # Test database
    @app.route('/test-db')
    def test_db():
        from .models import Client
        
        # Obtain all clients from the database
        all_clients = Client.query.all()
        
        # Pass the clients and the name of the last added client to the template
        return render_template('test_db.html', clients=all_clients)
    
    # Add new client to database
    @app.route('/generate_client', methods=['POST'])
    def generate_client():
        from .models import Client
        import uuid
        
        # Generate test client
        unique_id = str(uuid.uuid4())[:8]
        new_client = Client(
            name=f"Test-{unique_id}", 
            email=f"{unique_id}@email.com"
        )
        
        # Add client to database
        try:
            db.session.add(new_client)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {e}"
        
        # 3. Redirect back to the test page to see the update
        return redirect(url_for('test_db'))



    return app