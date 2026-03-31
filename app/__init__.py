from flask import Flask, app, make_response, render_template, request, redirect, url_for, flash, abort
from datetime import datetime

from .extensions import db, login_manager
from config import Config

from functools import wraps
from flask_login import current_user, login_required, login_user, logout_user

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Helper function to log user actions
def log_action(action, entity_type=None, entity_id=None):
    from .models import AuditLog
    new_log = AuditLog(
        user_id=current_user.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=request.remote_addr
    )
    db.session.add(new_log)


# Initialize the rate limiter (attached to app later if not testing)
limiter = Limiter(get_remote_address)



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

    # Attach rate limiter only if not in testing mode
    if app.config['TESTING']:
        limiter.enabled = False
    else:
        limiter.init_app(app)

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
    
    @app.route('/register-firm', methods=['GET', 'POST'])
    def register_firm():
        from .models import Firm, User, Role
        all_firms = Firm.query.all()
        if request.method == 'POST':
            firm_name = request.form.get('firm_name')
            firm_email = request.form.get('firm_email')
            owner_name = request.form.get('owner_name')
            owner_password = request.form.get('owner_password')
            
            new_firm = Firm(name=firm_name, email=firm_email, status="Active")
            db.session.add(new_firm)
            db.session.flush() # Gets the firm ID before committing

            # Create the owner user
            admin_role = Role.query.filter_by(name='Admin').first()
            owner = User(name=owner_name, email=firm_email, firm_id=new_firm.id, role_id=admin_role.id)
            owner.set_password(owner_password)
            db.session.add(owner)
            db.session.commit()
            
            flash('Firm registered successfully', 'success')
            return redirect(url_for('login'))
            
        return render_template('register-firm.html', firms=all_firms)
        
    
    @app.route('/log_user_in', methods=['POST'])
    @limiter.limit("10 per minute")
    def log_user_in():
        from .models import User

        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        # Find the user
        user = User.query.filter_by(email=email).first()
        #Check if user exists and password is correct
        if user and user.check_password(password):
            login_user(user, remember=remember)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
            return redirect(url_for('login'))
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))
    
    @app.route('/dashboard')
    @app.route('/dashboard/client/<int:client_id>')
    @login_required
    def dashboard(client_id=None):
        from .models import Client

        if current_user.is_admin():
            # Admins can see all clients in their firm
            from .models import Client
            clients = Client.query.filter_by(firm_id=current_user.firm_id).all()
        else:
            # Accounants can only see their clients
            clients = current_user.clients
        
        # Check if a specific client was requested via query parameter
        selected_id = client_id or request.args.get('client_id', type=int)
        selected_client = None
        if selected_id:
            selected_client = db.session.get(Client, selected_id)
            # Ensure user can view this client
            if selected_client not in clients and not current_user.is_admin():
                selected_client = None

        now = datetime.now()
        iso_date_string = now.strftime('%Y-%m-%d')
        return render_template(
            'dashboard.html',
            clients=clients,
            client=selected_client,
            selected_client=selected_client,
            default_input_date=iso_date_string,
            default_input_time=now.strftime('%H:%M')
        )
    
    @app.route('/dashboard/overview')
    @login_required
    def get_overview_panel():
        return render_template('partials/overview_panel.html')

    @app.route('/get-client-partial/<int:client_id>')
    @login_required
    def get_client_panel(client_id):
        from .models import Client
        from datetime import datetime
        # Fetch the specific client
        client = db.session.get(Client, client_id)
        # Check if the user is authorized to view this client
        if not current_user.is_admin() and client not in current_user.clients:
            return "<div class='alert alert-danger'>Unauthorized Access</div>", 403
        # Return the main panel with the selected client's information
        now = datetime.now()
        iso_date_string = now.strftime('%Y-%m-%d')
        return render_template(
            'partials/main_panel.html', 
            client=client,
            default_input_date=iso_date_string,
            default_input_time=now.strftime('%H:%M')
        )

    @app.route('/tax-payments', methods=['POST'])
    @login_required
    def create_tax_payment():
        from .models import Client, TaxRecord, ScheduledPayment, PaymentSchedule

        # Verification & Client Lookup
        client_id = request.form.get('client_id', '').strip()
        if not client_id or not client_id.isdigit():
            response = make_response('<div class="alert alert-danger">Please select a valid client.</div>', 200)
            return response

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return "Forbidden", 403

        # Data Extraction
        amount = request.form.get('total_payment_amount', '0')
        tax_year = request.form.get('tax_period', '')[:4] # Extract YYYY from YYYYMM
        settlement_date = request.form.get('settlement_date', '')
        tax_period = request.form.get('tax_period', '').strip()

        # Validation Logic
        try:
            payment_amount = float(amount)
            settle_date_obj = datetime.strptime(settlement_date, '%Y-%m-%d').date()
        except ValueError:
            response = make_response('<div class="alert alert-danger">Check your date/amount format.</div>', 200)
            return response

        # Save to Database
        try:
            # Create the Record
            new_record = TaxRecord(
                client_id=client.id,
                tax_year=int(tax_year) if tax_year.isdigit() else 2026,
                estimated_tax_total=payment_amount,
                uploaded_by=current_user.id,
                tax_form=request.form.get('tax_form', '1040'),
                tax_type_code=request.form.get('tax_type', 'ES'),
                taxpayer_type=request.form.get('taxpayer_type_code', 'I'),
                description=request.form.get('tax_form_description', '').strip() or None
            )
            db.session.add(new_record)
            db.session.flush()

            new_schedule = PaymentSchedule(tax_record_id=new_record.id, schedule_name="Unspecified")
            db.session.add(new_schedule)
            db.session.flush()

            # Create the Payment
            new_payment = ScheduledPayment(
                schedule_id=new_schedule.id,
                due_date=settle_date_obj,
                amount=payment_amount,
                status='pending',
                eft_number=request.form.get('eft_number', '').strip(),
                tax_period=tax_period,
                input_method=request.form.get('payment_input_method', 'B'),

                original_eft_number=request.form.get('original_eft_number', '').strip() or None,
                cancellation_eft_number=request.form.get('cancellation_eft_number', '').strip() or None,
                bulk_debit_trace_number=request.form.get('bulk_debit_trace_number', '').strip() or None,
                bulk_debit_cancellation_number=request.form.get('bulk_debit_cancellation_number', '').strip() or None,
                ach_trace_number=request.form.get('ach_trace_number', '').strip() or None,
                transaction_code=request.form.get('transaction_code', '').strip() or None,
                input_date=datetime.strptime(request.form.get('input_date'), '%Y-%m-%d').date(),
                input_time=datetime.strptime(request.form.get('input_time'), '%H:%M').time(),
                payment_status=request.form.get('payment_status'),
            )

            log_action('Created Tax Payment', entity_type='ScheduledPayment', entity_id=new_payment.id)
            
            db.session.add(new_payment)
            db.session.commit()
            success_html = f'<div class="alert alert-success">Tax data saved for {client.name}</div>'
            response = make_response(success_html, 200)
            return response

        except Exception as e:
            db.session.rollback()
            # response = make_response(f'<div class="alert alert-danger border-0 shadow-sm"><strong>Database Error:</strong> {str(e)}</div>', 200) # Detailed error for debugging
            response = make_response(f'<div class="alert alert-danger border-0 shadow-sm"><strong>Invalid Input:</strong> Please check your entries and try again.</div>', 200)
            return response
    
    # ------- ADMIN ROUTES -------
    @app.route('/admin')
    @admin_required
    def admin():
        from .models import Client, User, Role

        clients = Client.query.filter_by(firm_id=current_user.firm_id).all()
        accountants = User.query.filter(
            User.role.has(Role.name == 'Accountant'), 
            User.firm_id == current_user.firm_id
        ).all()
        return render_template('admin.html', clients=clients, accountants=accountants)
    
    # --- ADMIN: Client Management ---
    @app.route('/admin/client/<int:client_id>/edit', methods=['GET'])
    @admin_required
    def edit_client(client_id):
        from .models import Client, User, Role

        
        client = Client.query.get_or_404(client_id)
        if client.firm_id != current_user.firm_id:
            return "Forbidden", 403
        # Get all accountants in the firm
        all_accountants = User.query.filter(
            User.role.has(Role.name == 'Accountant'), 
            User.firm_id == current_user.firm_id
        ).all()
        return render_template('partials/edit_client_form.html', 
                            client=client, 
                            all_accountants=all_accountants)
    
    @app.route('/admin/client/<int:client_id>/update', methods=['POST'])
    @admin_required
    def update_client(client_id):
        from .models import Client, User
        from flask import make_response

        client = Client.query.get_or_404(client_id)
        if client.firm_id != current_user.firm_id:
            return "Forbidden", 403
        # Update info
        client.name = request.form.get('name')
        client.email = request.form.get('email')
        client.phone = request.form.get('phone')
        client.address = request.form.get('address')
        client.tax_id = request.form.get('tax_id')
        # Update Assignments
        selected_accountant_ids = request.form.getlist('accountant_ids')
        selected_users = User.query.filter(User.id.in_(selected_accountant_ids)).all()
        client.users = selected_users

        log_action('Updated Client: ' + client.name, entity_type='Client', entity_id=client.id)

        db.session.commit()
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response

    @app.route('/admin/client/<int:client_id>', methods=['DELETE'])
    @admin_required
    def delete_client(client_id):
        from .models import Client

        client = Client.query.get_or_404(client_id)
        if client.firm_id != current_user.firm_id:
            return "Forbidden", 403
        # Delete the client
        log_action('Deleted Client: ' + client.name, entity_type='Client', entity_id=client.id)
        db.session.delete(client)
        db.session.commit()
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    
    @app.route('/admin/client/add', methods=['GET'])
    @admin_required
    def add_client_form():
        from .models import User, Role

        all_accountants = User.query.filter(User.role.has(Role.name == 'Accountant'), User.firm_id == current_user.firm_id).all()
        return render_template('partials/add_client_form.html', all_accountants=all_accountants)

    @app.route('/admin/client/create', methods=['POST'])
    @admin_required
    def create_client():
        from .models import Client, User

        new_client = Client(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            tax_id=request.form.get('tax_id'),
            firm_id=current_user.firm_id
        )
    
        selected_ids = request.form.getlist('accountant_ids')
        new_client.users = User.query.filter(User.id.in_(selected_ids)).all()
        db.session.add(new_client)
        db.session.flush()
        log_action('Created Client: ' + new_client.name, entity_type='Client', entity_id=new_client.id)
        db.session.commit()
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    
    # --- ADMIN: Accountant Management ---
    @app.route('/admin/accountant/<int:user_id>/edit', methods=['GET'])
    @admin_required
    def edit_accountant(user_id):
        from .models import User

        accountant = User.query.get_or_404(user_id)
        if accountant.firm_id != current_user.firm_id:
            return "Forbidden", 403
        return render_template('partials/edit_accountant_form.html', accountant=accountant)

    @app.route('/admin/accountant/<int:user_id>/update', methods=['POST'])
    @admin_required
    def update_accountant(user_id):
        from .models import User

        # Integrity check
        accountant = User.query.get_or_404(user_id)
        new_email = request.form.get('email')
        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user and existing_user.id != accountant.id:
            return render_template('partials/edit_accountant_form.html', 
                               accountant=accountant, 
                               error="This email is already taken.")
        # Update
        accountant = User.query.get_or_404(user_id)
        if accountant.firm_id != current_user.firm_id:
            return "Forbidden", 403
        accountant.name = request.form.get('name')
        accountant.email = request.form.get('email')
        accountant.is_active = 'is_active' in request.form
        new_password = request.form.get('new_password')
        if new_password and len(new_password) >= 8:
            accountant.set_password(new_password)
        log_action('Updated Accountant: ' + accountant.name, entity_type='User', entity_id=accountant.id)
        db.session.commit()
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response

    @app.route('/admin/accountant/<int:user_id>', methods=['DELETE'])
    @admin_required
    def delete_accountant(user_id):
        from .models import User
        from flask import make_response
        
        accountant = User.query.get_or_404(user_id)
        if accountant.firm_id != current_user.firm_id:
            return "Forbidden", 403
        log_action('Deleted Accountant: ' + accountant.name, entity_type='User', entity_id=accountant.id)
        db.session.delete(accountant)
        db.session.commit()
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    
    @app.route('/admin/accountant/add', methods=['GET'])
    @admin_required
    def add_accountant_form():
        return render_template('partials/add_accountant_form.html')
    
    @app.route('/admin/accountant/create', methods=['POST'])
    @admin_required
    def create_accountant():
        from .models import User, Role
        from flask import make_response, render_template, request

        # Integrity Check
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return render_template('partials/add_accountant_form.html', 
                                error=f"Email {email} is already in use.")
        #Create and Save
        new_acc = User(
            name=name,
            email=email,
            firm_id=current_user.firm_id,
            is_active=True
        )
        # Assign Role
        acc_role = Role.query.filter_by(name='Accountant').first()
        new_acc.role = acc_role
        # Hash Password
        new_acc.set_password(password)
        try:
            db.session.add(new_acc)
            db.session.flush()
            log_action('Created Accountant: ' + new_acc.name, entity_type='User', entity_id=new_acc.id)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return "Internal Server Error", 500
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response


    # ------- SYSADMIN ROUTES -------
    @app.route('/sysadmin')
    @sysadmin_required
    def sysadmin():

        from .models import Firm, User, AuditLog
        
        total_firms = Firm.query.count()
        total_users = User.query.count()

        all_users = User.query.join(Firm).order_by(Firm.name, User.name).all()
        
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
        
        return render_template(
            'sysadmin.html', 
            total_firms=total_firms, 
            total_users=total_users, 
            all_users=all_users,
            logs=logs
        )
    
    @app.route('/sysadmin/user/<int:user_id>/edit', methods=['GET'])
    @sysadmin_required
    def sysadmin_edit_user(user_id):
        from .models import User, Firm
        
        target_user = User.query.get_or_404(user_id)
        all_firms = Firm.query.order_by(Firm.name).all()
        
        return render_template('partials/sysadmin_edit_user.html', 
                            target_user=target_user, 
                            all_firms=all_firms)

    @app.route('/sysadmin/user/<int:user_id>/update', methods=['POST'])
    @sysadmin_required
    def sysadmin_update_user(user_id):
        from .models import User, Role
        
        target_user = User.query.get_or_404(user_id)
        
        target_user.name = request.form.get('name')
        target_user.email = request.form.get('email')
        target_user.is_active = 'is_active' in request.form
        
        target_user.firm_id = int(request.form.get('firm_id'))
        
        new_role_name = request.form.get('role_name')
        if new_role_name:
            target_user.role = Role.query.filter_by(name=new_role_name).first()
        
        new_pw = request.form.get('new_password')
        if new_pw and len(new_pw) >= 8:
            target_user.set_password(new_pw)
            
        log_action(f"Sysadmin Panel: Updated {target_user.name} (Firm ID: {target_user.firm_id})", "User", target_user.id)
        db.session.commit()
        
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    
    @app.route('/sysadmin/user/<int:user_id>', methods=['DELETE'])
    @sysadmin_required
    def sysadmin_delete_user(user_id):
        from .models import User
        from flask import make_response
        
        target_user = User.query.get_or_404(user_id)
        log_action(f"Sysadmin Panel: Deleted {target_user.name} (Firm ID: {target_user.firm_id})", "User", target_user.id)
        db.session.delete(target_user)
        db.session.commit()
        
        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    

    @app.route('/sysadmin/user/add', methods=['GET'])
    @sysadmin_required
    def sysadmin_add_user_form():
        from .models import Firm
        all_firms = Firm.query.order_by(Firm.name).all()
        return render_template('partials/sysadmin_add_user.html', all_firms=all_firms)

    @app.route('/sysadmin/user/create', methods=['POST'])
    @sysadmin_required
    def sysadmin_create_user():
        from .models import User, Role, Firm
        
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        firm_id = request.form.get('firm_id')
        role_name = request.form.get('role_name')

        # Check if email is already taken
        if User.query.filter_by(email=email).first():
            all_firms = Firm.query.order_by(Firm.name).all()
            return render_template('partials/sysadmin_add_user.html', 
                                all_firms=all_firms, 
                                error=f"Email {email} is already in use.")

        new_user = User(
            name=name,
            email=email,
            firm_id=int(firm_id),
            is_active=True
        )
        new_user.role = Role.query.filter_by(name=role_name).first()
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.flush()
        log_action(f"Sysadmin Panel: Created User {name} (Firm ID: {firm_id})", "User", new_user.id)
        db.session.commit()

        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response



    # ------------------------------------
    # ----------- TEST ROUTES ------------
    # ------------------------------------
    
    # Test route
    @app.route('/test')
    @developer_required
    def test():
        return render_template('test.html')
    
    # Generate new firm
    @app.route('/generate_firm', methods=['POST'])
    @developer_required
    def generate_firm():
        from .models import Firm
        from faker import Faker
        fake = Faker()

        new_firm = Firm(
            name=fake.company(),
            email=fake.email(),
            status="Active"
        )
        db.session.add(new_firm)
        db.session.commit()
        
        return redirect(url_for('test_db')) 


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
            db.session.flush()
            log_action('Generated Test Client: ' + new_client.name, entity_type='Client', entity_id=new_client.id)
            db.session.commit()
            # flash(f"Generated client: {new_client.name}", "success")
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {e}"
        
        return redirect(url_for('test_db'))

    # ----------------------------------------
    # ------------- ERROR ROUTES -------------
    # ----------------------------------------

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(401)
    def unauthorized(error):
        return render_template('errors/401.html'), 401



    return app