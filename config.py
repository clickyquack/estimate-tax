import os

class Config:
    # -----------------------------------------------
    # ----------- ENVIRONMENTAL VARIABLES -----------
    # -----------------------------------------------

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'development-key-123'
    


    # --------------------------------
    # ----------- DATABASE -----------
    # --------------------------------

    # Path to the SQLite database
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'estimate_tax.db')
    
    # Disable tracking to save memory (?)
    SQLALCHEMY_TRACK_MODIFICATIONS = False