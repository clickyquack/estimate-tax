from datetime import timedelta
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    # -----------------------------------------------
    # ----------- ENVIRONMENTAL VARIABLES -----------
    # -----------------------------------------------

    TESTING = True

    SECRET_KEY = os.environ.get('SECRET_KEY')
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_SEAT_PRICE_ID = os.environ.get('STRIPE_SEAT_PRICE_ID')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    SESSION_PERMANENT = False
    REMEMBER_COOKIE_DURATION = timedelta(seconds=0)
    SESSION_PROTECTION = 'strong'

    # --------------------------------
    # ----------- DATABASE -----------
    # --------------------------------

    # Path to the SQLite database
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'estimate_tax.db')
    
    # Disable tracking to save memory (?)
    SQLALCHEMY_TRACK_MODIFICATIONS = False