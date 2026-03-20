from flask import Flask, render_template, request, redirect, url_for, flash, abort
from datetime import datetime

from app.models import User

from .extensions import db, login_manager
from config import Config

from functools import wraps
from flask_login import current_user, login_required, login_user, logout_user



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
    # ----------- LOGIN MANAGER ---------
    # -----------------------------------
    login_manager.init_app(app)
    login_manager.login_view = 'login'


    # -------------------------------------
    # ------------ DECORATORS -------------
    # -------------------------------------

    def developer_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_developer():
                abort(403)
            return f(*args, **kwargs)
        return decorated_function

    def sysadmin_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_sysadmin():
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    
    def admin_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_admin():
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    
    # Then just use @login_required for accountant-level access


    # -----------------------------------
    # ------------- ROUTES --------------
    # -----------------------------------

    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/login')
    def login():
        return render_template('login.html')
    
    @app.route('/log_user_in', methods=['POST'])
    def log_user_in():
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        # Find the user
        user = User.query.filter_by(email=email).first()
        #Check if user exists and password is correct
        if not user or not user.check_password(password):
            flash('Please check your login details and try again.', 'danger')
            return redirect(url_for('login'))
        # Log in
        login_user(user, remember=remember)
        return redirect(url_for('dashboard'))
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))
    
    @app.route('/dashboard')
    @login_required
    def dashboard():
        from .models import Client

        if current_user.is_admin():
            # Admins can see all clients in their firm
            from .models import Client
            clients = Client.query.filter_by(firm_id=current_user.firm_id).all()
        else:
            # Accounants can only see their clients
            clients = current_user.clients
        
        now = datetime.now()
        return render_template(
            'dashboard.html',
            clients=clients,
            default_input_date=now.strftime('%m/%d/%Y'),
            default_input_time=now.strftime('%H:%M')
        )

    @app.route('/tax-payments', methods=['POST'])
    @login_required
    def create_tax_payment():
        from .models import Client, TaxPayment

        client_id = request.form.get('client_id', '').strip()
        if not client_id or not client_id.isdigit():
            flash('Please select a valid client before saving tax data.', 'danger')
            return redirect(url_for('dashboard'))

        client = Client.query.get(int(client_id))
        if client is None:
            flash('Selected client does not exist.', 'danger')
            return redirect(url_for('dashboard'))

        tin = request.form.get('tin', '').strip()
        taxpayer_type_code = request.form.get('taxpayer_type_code', '').strip().upper()
        eft_number = request.form.get('eft_number', '').strip()
        tax_form = request.form.get('tax_form', '').strip()
        tax_type = request.form.get('tax_type', '').strip()
        tax_period = request.form.get('tax_period', '').strip()
        total_payment_amount = request.form.get('total_payment_amount', '').strip()
        settlement_date = request.form.get('settlement_date', '').strip()
        payment_input_method = request.form.get('payment_input_method', '').strip().upper()

        if not (tin.isdigit() and len(tin) == 9):
            flash('TIN (SSN/EIN) must be exactly 9 digits.', 'danger')
            return redirect(url_for('dashboard'))

        if taxpayer_type_code not in {'I', 'B'}:
            flash('Taxpayer Type Code must be I (individual) or B (business).', 'danger')
            return redirect(url_for('dashboard'))

        if not (eft_number.isdigit() and len(eft_number) == 15):
            flash('EFT Number must be exactly 15 digits.', 'danger')
            return redirect(url_for('dashboard'))

        if not tax_form:
            flash('Tax Form is required.', 'danger')
            return redirect(url_for('dashboard'))

        if not tax_type:
            flash('Tax Type is required.', 'danger')
            return redirect(url_for('dashboard'))

        if not tax_period:
            flash('Tax Period is required.', 'danger')
            return redirect(url_for('dashboard'))

        if len(tax_period) not in {4, 6} or not tax_period.isdigit():
            flash('Tax Period must be YYYY or YYYYMM.', 'danger')
            return redirect(url_for('dashboard'))

        try:
            amount = float(total_payment_amount)
            if amount <= 0:
                raise ValueError()
        except ValueError:
            flash('Total Payment Amount must be a valid number greater than 0.', 'danger')
            return redirect(url_for('dashboard'))

        try:
            settlement_date_value = datetime.strptime(settlement_date, '%m/%d/%Y').date()
        except ValueError:
            flash('Settlement Date must be in MM/DD/YYYY format.', 'danger')
            return redirect(url_for('dashboard'))

        now = datetime.now()
        input_date_raw = request.form.get('input_date', '').strip() or now.strftime('%m/%d/%Y')
        input_time_raw = request.form.get('input_time', '').strip() or now.strftime('%H:%M')
        input_date_value = None
        input_time_value = None

        try:
            input_date_value = datetime.strptime(input_date_raw, '%m/%d/%Y').date()
        except ValueError:
            flash('Input Date must be in MM/DD/YYYY format.', 'danger')
            return redirect(url_for('dashboard'))

        try:
            input_time_value = datetime.strptime(input_time_raw, '%H:%M').time()
        except ValueError:
            flash('Input Time must be in HH:MM (24-hour) format.', 'danger')
            return redirect(url_for('dashboard'))

        new_payment = TaxPayment(
            amount=amount,
            tin=tin,
            taxpayer_type_code=taxpayer_type_code,
            eft_number=eft_number,
            original_eft_number=request.form.get('original_eft_number', '').strip() or None,
            cancellation_eft_number=request.form.get('cancellation_eft_number', '').strip() or None,
            bulk_debit_trace_number=request.form.get('bulk_debit_trace_number', '').strip() or None,
            bulk_debit_cancellation_number=request.form.get('bulk_debit_cancellation_number', '').strip() or None,
            payment_input_method=payment_input_method or None,
            tax_form=tax_form,
            tax_form_description=request.form.get('tax_form_description', '').strip() or None,
            tax_type=tax_type,
            tax_period=tax_period,
            settlement_date=settlement_date_value,
            ach_trace_number=request.form.get('ach_trace_number', '').strip() or None,
            payment_status=request.form.get('payment_status', '').strip() or None,
            transaction_code=request.form.get('transaction_code', '').strip() or None,
            input_date=input_date_value,
            input_time=input_time_value,
            client_id=client.id
        )

        try:
            db.session.add(new_payment)
            db.session.commit()
            flash(f'Tax data saved for {client.name}.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Unable to save tax data: {e}', 'danger')

        return redirect(url_for('dashboard'))
    
    @app.route('/admin')
    @admin_required
    def admin():
        return render_template('admin.html')
    
    @app.route('/sysadmin')
    @sysadmin_required
    def sysadmin():
        return render_template('sysadmin.html')



    # ------------------------------------
    # ----------- TEST ROUTES ------------
    # ------------------------------------
    
    # Test route
    @app.route('/test')
    @developer_required
    def test():
        return render_template('test.html')

    # Test database
    @app.route('/test-db')
    @developer_required
    def test_db():
        from .models import Client
        
        # Obtain all clients from the database
        all_clients = Client.query.all()
        
        # Pass the clients and the name of the last added client to the template
        return render_template('test_db.html', clients=all_clients)
    
    # Add new client to database
    @app.route('/generate_client', methods=['POST'])
    @developer_required
    def generate_client():
        from .models import Client, Firm
        from faker import Faker
        fake = Faker()
        
        # Use the firm the user is associated with
        target_firm_id = current_user.firm_id
        
        # Generate test client
        new_client = Client(
            name=fake.company(),
            email=fake.company_email(),
            phone=fake.phone_number()[:15],
            tax_id=fake.numerify(text="#########"),
            address=fake.address(),
            firm_id=target_firm_id
        )
        
        # Add client to database
        try:
            db.session.add(new_client)
            db.session.commit()
            # flash(f"Generated client: {new_client.name}", "success")
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {e}"
        
        return redirect(url_for('test_db'))



    return app