from flask import Flask, render_template
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



    # ------------------------------------
    # ----------- TEST ROUTES ------------
    # ------------------------------------
    
    # Test route
    @app.route('/test')
    def hello():
        return "<h1>Estimate.tax Test Dashboard</h1> <p><a href=\"/\">Index</a></p> <p><a href=\"/test-db\">Test Database</a></p> "
    

    # Test database
    @app.route('/test-db')
    def test_db():
        from .models import Client
        import uuid # Generates a short unique string
        
        # 1. Create a unique identifier for this specific test run
        unique_id = str(uuid.uuid4())[:8]
        
        # 2. Use that ID to make the name and email unique
        new_client = Client(
            name=f"{unique_id}", 
            email=f"{unique_id}@email.com"
        )
        
        # 3. Try to add and commit
        try:
            db.session.add(new_client)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {e}"
        
        # 4. Return the full list to see the unique entries growing
        all_clients = Client.query.all()
        output = [f"ID: {c.id} | Name: {c.name} | Email: {c.email}" for c in all_clients]
        
        return "<br>".join(output)



    return app