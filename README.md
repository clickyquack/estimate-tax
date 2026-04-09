# estimate-tax

# First Time Setup
### 1. Set up Virtual Environment and Install Requirements
Ensure that you have python 3.x installed. Instructions to install the requirements in the virtual environment can be found [here](#install-requirements)
### 2. Generate env file
In the directory, run the following:
```
python generate_env.py
```
### 3. Generate sample data
run the following:
```
python sample_data.py
```
### 4. Run the application
run the following:
```
python run.py
```
The application will be accessible at http://127.0.0.1:5000. Sample login info is provided [here](#sample-login-info). The developer has the most permissions.


# Quick Start
[Install Requirements](#install-requirements) <br>
[Run on Server](#run-on-server)

**Windows**
```
# Run virtual environment 
Set-ExecutionPolicy RemoteSigned -Scope Process
venv\Scripts\activate

# Generate New Sample Data
python sample_data.py

# Open index in browser
start http://127.0.0.1:5000

# Run the app
python run.py
```



# Using Sample Data

### Run the sample data script
This will **WIPE THE DATABASE**
```
python sample_data.py
```

### Sample Login Info
All of these are users with various roles of the same test firm
| Email | Password |
| :--- | :--- |
| developer@test.com | developer |
| sysadmin@test.com | sysadmin |
| admin@test.com | admin |
| accountant1@test.com | accountant |
| accountant2@test.com | accountant |



# Virtual Environment

## Run Virtual Environment
**Windows**
```
Set-ExecutionPolicy RemoteSigned -Scope Process
venv\Scripts\activate
```
**Linux/Mac**
```
source venv/bin/activate
```


## Install Requirements
**Windows**
```
Set-ExecutionPolicy RemoteSigned -Scope Process
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
**Linux/Mac**
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```


## Build New 'requirements.txt' File for Virtual Environment
**Windows**
```
# Set up virtual environment
Set-ExecutionPolicy RemoteSigned -Scope Process
python -m venv venv
venv\Scripts\activate

# (Install Software Here)

# Save software requirements
pip freeze > requirements.txt
```
**Linux/Mac**
```
# Set up virtual environment
python -m venv venv
source venv/bin/activate

# (Install Software Here)

# Save software requirements
pip freeze > requirements.txt
```


# Run on Server
This repository supports:
- **Local/dev**: `run.py` uses **SQLite**.
- **Production**: `serve.py` uses **MySQL** + **Waitress** behind **Nginx**.

## Local/dev (SQLite)
```
python run.py
```

## Production (MySQL + Waitress + Nginx)

### 1) Install OS packages (Ubuntu)
```
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx ufw mysql-server
```

### 2) Create MySQL database and user
```
sudo mysql
```
```
CREATE DATABASE estimate_tax CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'estimate_tax'@'localhost' IDENTIFIED BY 'REPLACE_WITH_A_LONG_PASSWORD';
GRANT ALL PRIVILEGES ON estimate_tax.* TO 'estimate_tax'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3) Deploy code and install Python requirements
```
git clone https://github.com/clickyquack/estimate-tax.git
cd estimate-tax
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4) Set environment variables (required in production)
Production expects these environment variables:
- `SECRET_KEY`
- `ENCRYPTION_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_SEAT_PRICE_ID`
- `STRIPE_WEBHOOK_SECRET`
- `DATABASE_URL` (MySQL SQLAlchemy URL)

Example `DATABASE_URL` (local MySQL):
```
mysql+pymysql://estimate_tax:REPLACE_WITH_A_LONG_PASSWORD@127.0.0.1:3306/estimate_tax?charset=utf8mb4
```

### 5) Run the app with Waitress (bind to localhost only)
```
waitress-serve --host 127.0.0.1 --port 8000 --call serve:build_app
```

### 6) Put Nginx in front (HTTPS)
Install Certbot + get a Let’s Encrypt certificate:
```
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
```

Create an Nginx site (replace `YOUR_DOMAIN`), then reload Nginx:
```
server {
    listen 80;
    server_name YOUR_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Request the certificate and let Certbot update Nginx for HTTPS automatically:
```
sudo certbot --nginx -d YOUR_DOMAIN
sudo systemctl enable --now certbot.timer
```

After Certbot runs, confirm HTTP redirects to HTTPS and the app loads at `https://YOUR_DOMAIN`.



# Tech Stack

| Technology | Description |
| :--- | :--- |
| **Python** | Python 3.x - Backend programming language. |
| **Flask** | Web framework. |
| **SQLAlchemy** | Object-Relational Mapper (ORM). Allows managing the database using Python code instead of writing raw SQL strings. Convenient, modular, and secure. Allows for database type to be changed easily. |
| **SQLite** | Database. Good for development, but not scalable. |
| **MySQL** | Database. Better for concurrency than SQLite, but needs a server to host it. |
| **Pytest** | Automated Testing Framework |
| **HTMX** | Frontend Interactivity. Enables AJAX requests directly from HTML attributes to swap page fragments without a full reload. |