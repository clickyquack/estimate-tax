import os
import secrets
from cryptography.fernet import Fernet

def generate_dotenv():
    secret_key = secrets.token_hex(32)
    encryption_key = Fernet.generate_key().decode()

    env_content = f"""FLASK_APP=app.py
FLASK_DEBUG=1
SECRET_KEY={secret_key}
ENCRYPTION_KEY={encryption_key}
"""
    
    if os.path.exists('.env'):
        confirm = input(".env file already exists. Overwrite? (y/n): ")
        if confirm.lower() != 'y':
            print("Operation cancelled.")
            return

    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("Successfully generated .env file")

if __name__ == "__main__":
    generate_dotenv()