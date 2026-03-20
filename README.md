# estimate-tax



# Quick Start
[Install Requirements](#install-requirements)

**Windows**
```
# Run virtual environment 
Set-ExecutionPolicy RemoteSigned -Scope Process
venv\Scripts\activate

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



# Tech Stack

| Technology | Description |
| :--- | :--- |
| **Python** | Backend programming language. |
| **Flask** | Web framework. |
| **SQLAlchemy** | Object-Relational Mapper (ORM). Allows managing the database using Python code instead of writing raw SQL strings. Convenient, modular, and secure. Allows for database type to be changed easily. |
| **SQLite** | Database. Good for development, but not scalable. |
| **MySQL** | Database. Better for concurrency than SQLite, but needs a server to host it. |
| **Pytest** | Automated Testing Framework |
| **HTMX** | Frontend Interactivity. Enables AJAX requests directly from HTML attributes to swap page fragments without a full reload. |