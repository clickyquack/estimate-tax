import os

class Config:
    # -----------------------------------------------
    # ----------- ENVIRONMENTAL VARIABLES -----------
    # -----------------------------------------------

    # Reference environment variables here like API keys (do not put them in here raw)
    


    # --------------------------------
    # ----------- DATABASE -----------
    # --------------------------------

    # Path to the SQLite database
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'estimate_tax.db')
    
    # Disable tracking to save memory (?)
    SQLALCHEMY_TRACK_MODIFICATIONS = False