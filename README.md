# estimate-tax



# Quick Start
[Install Requirements](#install-requirements)

**Windows**
```
# Run virtual environment 
Set-ExecutionPolicy RemoteSigned -Scope Process
venv\Scripts\activate

# Open test dashboard in browser
start http://127.0.0.1:5000/test

# Run the app
python run.py
```



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

# Install software
pip install Flask 
pip install Flask-SQLAlchemy

# Save requirements
pip freeze > requirements.txt
```
**Linux/Mac**
```
# Set up virtual environment
python -m venv venv
source venv/bin/activate

# Install software
pip install Flask 
pip install Flask-SQLAlchemy

# Save requirements
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