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
### ssh and start virtual environment
```
ssh root@104.236.55.193
cd ~/estimate-tax
source venv/bin/activate
```
from here, you can make any changes desired, including git commands. To check out a different branch, do the following:
```
git fetch origin
git checkout Example-Branch
git pull origin Example-Branch
```
after making changes, you should restart the process
### Restart process 
```
pkill -f waitress
waitress-serve --call app:create_app &
```



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