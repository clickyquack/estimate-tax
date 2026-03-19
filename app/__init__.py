from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime

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
    
    @app.route('/login')
    def login():
        return render_template('login.html')
    
    @app.route('/login_user', methods=['POST'])
    def login_user():
        return redirect(url_for('login'))
    
    @app.route('/dashboard')
    def dashboard():
        from .models import Client
        
        all_clients = Client.query.all() # Query all clients from the database
        now = datetime.now()
        return render_template(
            'dashboard.html',
            clients=all_clients,
            default_input_date=now.strftime('%m/%d/%Y'),
            default_input_time=now.strftime('%H:%M')
        )

    @app.route('/tax-payments', methods=['POST'])
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
    def admin():
        return render_template('admin.html')
    
    @app.route('/sysadmin')
    def sysadmin():
        return render_template('sysadmin.html')



    # ------------------------------------
    # ----------- TEST ROUTES ------------
    # ------------------------------------
    
    # Test route
    @app.route('/test')
    def test():
        return render_template('test.html')

    # Test database
    @app.route('/test-db')
    def test_db():
        from .models import Client
        
        # Obtain all clients from the database
        all_clients = Client.query.all()
        
        # Pass the clients and the name of the last added client to the template
        return render_template('test_db.html', clients=all_clients)
    
    # Add new client to database
    @app.route('/generate_client', methods=['POST'])
    def generate_client():
        from .models import Client, Firm
        import uuid
        
        #Ensure a Firm exists to own the client
        test_firm = Firm.query.first()
        
        # Create a test firm if needed
        if not test_firm:
            test_firm = Firm(
                name="Kent Tax Strategy Group", 
                email="admin@kent.edu",
                status="active"
            )
            db.session.add(test_firm)
            db.session.commit() # Commit so ID is obtainable
        
        # Generate test client
        unique_id = str(uuid.uuid4())[:8]
        new_client = Client(
            name=f"Test-{unique_id}", 
            email=f"{unique_id}@email.com",
            firm_id=test_firm.id
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