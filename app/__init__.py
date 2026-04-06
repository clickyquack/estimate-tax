from flask import Flask, app, make_response, render_template, request, redirect, url_for, flash, abort, Response
from markupsafe import escape
from datetime import datetime, date, timedelta, time

from .extensions import db, login_manager
from config import Config

from functools import wraps
from flask_login import current_user, login_required, login_user, logout_user
import re

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .tax_helpers import (
    map_csv_tax_type_to_code,
    normalize_tax_period_storage,
    parse_csv_payment_rows,
    parse_decimal_amount,
    parse_flexible_date,
)


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
    @limiter.limit("10 per minute")
    def register_firm():
        from .models import Firm, User, Role
        all_firms = Firm.query.all()
        if request.method == 'POST':
            firm_name = request.form.get('firm_name')
            firm_email = request.form.get('firm_email')
            owner_name = request.form.get('owner_name')
            admin_email = request.form.get('admin_email')
            owner_password = request.form.get('owner_password')

            # Integrity Checks
            existing_user = User.query.filter_by(email=admin_email).first()
            if existing_user:
                flash('That email is already registered to a user.', 'danger')
                return render_template('register-firm.html')
            
            # Create the firm and admin
            try:
                new_firm = Firm(name=firm_name, email=firm_email, status="Active")
                db.session.add(new_firm)
                db.session.flush() # Gets the firm ID before committing

                # Create the owner user
                admin_role = Role.query.filter_by(name='Admin').first()
                owner = User(name=owner_name, email=admin_email, firm_id=new_firm.id, role_id=admin_role.id)
                owner.set_password(owner_password)
                db.session.add(owner)
                db.session.commit()
            
                flash('Firm registered successfully', 'success')
                return redirect(url_for('login'))
            
            except Exception as e:
                db.session.rollback()
                flash('An error occurred during registration. Please try again.', 'danger')
            
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

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        if request.method == 'POST':
            batch_filer_id = (request.form.get('batch_filer_id') or '').strip()
            master_inquiry_pin = (request.form.get('master_inquiry_pin') or '').strip()

            if not re.fullmatch(r"\d{9}", batch_filer_id):
                return render_template('profile.html', error="Batch Filer ID must be exactly 9 digits.")
            if not re.fullmatch(r"\d{4}", master_inquiry_pin):
                return render_template('profile.html', error="Master Inquiry PIN must be exactly 4 digits.")

            current_user.batch_filer_id = batch_filer_id
            current_user.master_inquiry_pin = master_inquiry_pin
            db.session.commit()
            flash("Export settings saved.", "success")
            return redirect(url_for('profile'))

        return render_template('profile.html')

    def _digits_only(value: str) -> str:
        return re.sub(r"\D+", "", value or "")

    def _fixed_width(value: str, length: int, *, pad: str = " ", align: str = "left") -> str:
        text = value or ""
        if len(text) > length:
            text = text[:length]
        if align == "right":
            return text.rjust(length, pad)
        return text.ljust(length, pad)

    def _last_day_of_month(y: int, m: int) -> int:
        if m == 12:
            nfd = date(y + 1, 1, 1)
        else:
            nfd = date(y, m + 1, 1)
        return (nfd - timedelta(days=1)).day

    def _payment_dates_for_period(calendar_year: int, period: str, start: date, end: date):
        """Return sorted unique payment dates in [start, end] for the given cadence."""
        period = (period or "").strip().lower()
        if start > end:
            return []

        if period == "weekly":
            out = []
            d = start
            while d <= end:
                out.append(d)
                d += timedelta(days=7)
            return out

        if period == "biweekly":
            out = []
            d = start
            while d <= end:
                out.append(d)
                d += timedelta(days=14)
            return out

        if period == "monthly":
            out = []
            y, m = start.year, start.month
            day = start.day
            while (y < end.year) or (y == end.year and m <= end.month):
                ld = _last_day_of_month(y, m)
                d = date(y, m, min(day, ld))
                if d >= start and d <= end:
                    out.append(d)
                if m == 12:
                    y += 1
                    m = 1
                else:
                    m += 1
            return out

        if period == "quarterly":
            candidates = [
                date(calendar_year, 3, 31),
                date(calendar_year, 6, 30),
                date(calendar_year, 9, 30),
                date(calendar_year, 12, 31),
            ]
            return [d for d in candidates if start <= d <= end]

        return []

    def _split_amount_cents(total_cents: int, n: int):
        if n <= 0:
            return []
        base = total_cents // n
        rem = total_cents % n
        return [base + (1 if i < rem else 0) for i in range(n)]

    @app.route('/export/generate-schedule', methods=['POST'])
    @login_required
    def generate_export_schedule():
        from .models import Client, TaxRecord, ScheduledPayment, PaymentSchedule
        from decimal import Decimal, ROUND_HALF_UP

        client_id = (request.form.get('client_id') or '').strip()
        period = (request.form.get('period') or '').strip().lower()
        year_raw = (request.form.get('calendar_year') or '').strip()
        total_raw = (request.form.get('total_annual_amount') or '').strip()
        tax_type_code_in = re.sub(r"\D+", "", (request.form.get('schedule_tax_type_code') or '').strip())
        tax_form_in = (request.form.get('schedule_tax_form') or '').strip() or "1040"
        taxpayer_type_in = (request.form.get('schedule_taxpayer_type') or "").strip().upper() or "I"

        if not client_id.isdigit():
            return '<div class="alert alert-danger py-2 small">Invalid client.</div>', 200
        try:
            calendar_year = int(year_raw)
        except ValueError:
            return '<div class="alert alert-danger py-2 small">Calendar year must be a number.</div>', 200

        try:
            total_annual = Decimal(total_raw)
        except Exception:
            return '<div class="alert alert-danger py-2 small">Total amount must be a valid number.</div>', 200

        total_annual = total_annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_annual <= 0:
            return '<div class="alert alert-danger py-2 small">Total amount must be greater than 0.</div>', 200

        if period in {"", "none"}:
            return '<div class="alert alert-danger py-2 small">Choose a split period above to generate a schedule.</div>', 200
        if period not in {"quarterly", "monthly", "biweekly", "weekly"}:
            return '<div class="alert alert-danger py-2 small">Choose a valid period.</div>', 200

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return '<div class="alert alert-danger py-2 small">Forbidden.</div>', 403

        tin = _digits_only(client.tax_id)
        if not re.fullmatch(r"\d{9}", tin):
            return '<div class="alert alert-danger py-2 small">Client TIN must be 9 digits before scheduling.</div>', 200
        tp = _digits_only(client.taxpayer_pin)
        if not re.fullmatch(r"\d{4}", tp):
            return '<div class="alert alert-danger py-2 small">Client Taxpayer PIN must be 4 digits before scheduling.</div>', 200

        today = date.today()
        year_start = date(calendar_year, 1, 1)
        year_end = date(calendar_year, 12, 31)

        if year_end < today:
            return '<div class="alert alert-danger py-2 small">That calendar year has already ended.</div>', 200

        start = max(today, year_start)
        if start > year_end:
            return '<div class="alert alert-danger py-2 small">No remaining dates in that year.</div>', 200

        pay_dates = _payment_dates_for_period(calendar_year, period, start, year_end)
        if not pay_dates:
            return '<div class="alert alert-danger py-2 small">No payment dates could be generated for that period.</div>', 200
        if len(pay_dates) > 400:
            return '<div class="alert alert-danger py-2 small">Too many payments; narrow the period or year.</div>', 200

        latest_payment = (
            ScheduledPayment.query
            .join(PaymentSchedule, ScheduledPayment.schedule_id == PaymentSchedule.id)
            .join(TaxRecord, PaymentSchedule.tax_record_id == TaxRecord.id)
            .filter(TaxRecord.client_id == client.id)
            .order_by(
                ScheduledPayment.input_date.desc(),
                ScheduledPayment.input_time.desc(),
                ScheduledPayment.id.desc(),
            )
            .first()
        )
        latest_record = None
        if latest_payment and latest_payment.schedule and latest_payment.schedule.tax_record:
            latest_record = latest_payment.schedule.tax_record

        tax_type_code = tax_type_code_in
        if not re.fullmatch(r"\d{5}", tax_type_code) and latest_record and latest_record.tax_type_code:
            tax_type_code = re.sub(r"\D+", "", latest_record.tax_type_code)
        if not tax_type_code or not re.fullmatch(r"\d{5}", tax_type_code):
            return '<div class="alert alert-danger py-2 small">Tax Type Code must be 5 digits.</div>', 200

        tax_form = tax_form_in
        taxpayer_type = taxpayer_type_in if taxpayer_type_in in {"B", "I"} else "I"

        total_cents = int((total_annual * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if total_cents < len(pay_dates):
            return (
                '<div class="alert alert-danger py-2 small">Total is too small for this many payments '
                '(each installment must be at least $0.01).</div>',
                200,
            )
        cents_parts = _split_amount_cents(total_cents, len(pay_dates))
        if sum(cents_parts) != total_cents:
            return '<div class="alert alert-danger py-2 small">Could not split payment amounts.</div>', 200
        if min(cents_parts) < 1:
            return '<div class="alert alert-danger py-2 small">Invalid payment split.</div>', 200

        try:
            sched_tax_type = None
            if latest_record:
                sched_tax_type = latest_record.tax_type
            if taxpayer_type == "I" and not sched_tax_type:
                sched_tax_type = "ES"

            new_record = TaxRecord(
                client_id=client.id,
                tax_year=calendar_year,
                estimated_tax_total=float(total_annual),
                uploaded_by=current_user.id,
                tax_form=tax_form,
                tax_type_code=tax_type_code,
                tax_type=sched_tax_type,
                taxpayer_type=taxpayer_type,
                description=None,
            )
            db.session.add(new_record)
            db.session.flush()

            schedule = PaymentSchedule(
                tax_record_id=new_record.id,
                schedule_name=f"{calendar_year} {period} export schedule",
            )
            db.session.add(schedule)
            db.session.flush()

            noon = time(12, 0)
            for d, cents in zip(pay_dates, cents_parts):
                amt = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                tax_period = f"{d.year}{str(d.month).zfill(2)}"
                sp = ScheduledPayment(
                    schedule_id=schedule.id,
                    due_date=d,
                    amount=float(amt),
                    status="pending",
                    eft_number="000000000000000",
                    tax_period=tax_period,
                    input_method="B",
                    input_date=d,
                    input_time=noon,
                )
                db.session.add(sp)

            db.session.flush()
            log_action(
                f"Generated {len(pay_dates)} scheduled export payments ({period}, {calendar_year})",
                entity_type="PaymentSchedule",
                entity_id=schedule.id,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            return '<div class="alert alert-danger py-2 small">Could not save schedule. Check inputs and try again.</div>', 200

        return (
            f'<div class="alert alert-success py-2 small">Created {len(pay_dates)} payments for {client.name}. '
            f'Download exports using <strong>File Date</strong> equal to each payment’s date.</div>',
            200,
        )

    @app.route('/export/fixed-width', methods=['GET'])
    @login_required
    def export_fixed_width():
        from .models import ScheduledPayment, PaymentSchedule, TaxRecord, Client, Export
        from decimal import Decimal, ROUND_HALF_UP
        from sqlalchemy.orm import joinedload

        file_date_raw = (request.args.get('file_date') or '').strip()
        try:
            file_date = datetime.strptime(file_date_raw, "%Y-%m-%d").date()
        except ValueError:
            return "file_date must be YYYY-MM-DD", 400

        client_id_filter = request.args.get("client_id", type=int)

        batch_filer_id = _digits_only(current_user.batch_filer_id)
        master_pin = _digits_only(current_user.master_inquiry_pin)
        if not re.fullmatch(r"\d{9}", batch_filer_id):
            return "Batch Filer ID must be set to 9 digits in profile.", 400
        if not re.fullmatch(r"\d{4}", master_pin):
            return "Master Inquiry PIN must be set to 4 digits in profile.", 400

        # Allocate per-user filer sequence number for this file_date
        if current_user.last_filer_sequence_date == file_date:
            next_seq = (current_user.last_filer_sequence_number or 0) + 1
        else:
            next_seq = 1
        if next_seq > 999:
            return "Filer Sequence Number exceeded 999 for this date.", 400
        current_user.last_filer_sequence_date = file_date
        current_user.last_filer_sequence_number = next_seq

        q = (
            ScheduledPayment.query
            .options(
                joinedload(ScheduledPayment.schedule)
                .joinedload(PaymentSchedule.tax_record)
                .joinedload(TaxRecord.client)
            )
            .join(PaymentSchedule, ScheduledPayment.schedule_id == PaymentSchedule.id)
            .join(TaxRecord, PaymentSchedule.tax_record_id == TaxRecord.id)
            .join(Client, TaxRecord.client_id == Client.id)
            .filter(
                Client.firm_id == current_user.firm_id,
                ScheduledPayment.input_date == file_date,
                ScheduledPayment.status == 'pending',
            )
        )
        if client_id_filter is not None:
            scope = db.session.get(Client, client_id_filter)
            if not scope or scope.firm_id != current_user.firm_id:
                return "Invalid client.", 400
            if not current_user.is_admin() and scope not in current_user.clients:
                return "Forbidden", 403
            q = q.filter(TaxRecord.client_id == client_id_filter)

        payments = q.order_by(ScheduledPayment.id.asc()).all()

        if not payments:
            return "No pending payments found for that file date.", 400

        lines = []
        payment_ref = 1
        for p in payments:
            tr = p.schedule.tax_record
            c = tr.client

            tr_saved = (
                TaxRecord.query.filter_by(client_id=c.id)
                .order_by(TaxRecord.id.desc())
                .first()
            )
            tr_export = tr_saved or tr

            tin = _digits_only(c.tax_id)
            if not re.fullmatch(r"\d{9}", tin):
                return f"Client {c.id} has invalid TIN; must be 9 digits.", 400

            taxpayer_pin = _digits_only(c.taxpayer_pin)
            if not re.fullmatch(r"\d{4}", taxpayer_pin):
                return f"Client {c.id} is missing a valid Taxpayer PIN (4 digits).", 400

            taxpayer_type = (tr_export.taxpayer_type or "").strip().upper()
            if taxpayer_type not in {"B", "I"}:
                return f"Taxpayer Type Code must be B or I for client {c.id}.", 400

            tax_type_code = _digits_only(tr_export.tax_type_code)
            if not tax_type_code:
                tax_type_code = "00000"
            elif not re.fullmatch(r"\d{5}", tax_type_code):
                return f"Tax Type Code must be 5 digits (or empty for business) for client {c.id}.", 400

            tax_period = _digits_only(p.tax_period)
            if not re.fullmatch(r"\d{6}", tax_period):
                return f"Tax Period must be YYYYMM or YYYY00 for client {c.id}.", 400
            month = int(tax_period[4:6])
            if month != 0 and (month < 1 or month > 12):
                return f"Tax Period month must be 00 (annual) or 01-12 for client {c.id}.", 400

            if not p.due_date:
                return f"Settlement Date missing for client {c.id}.", 400

            amount = Decimal(str(p.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if amount <= 0 or amount >= Decimal("100000000"):
                return f"Payment Amount out of range for client {c.id}.", 400
            amount_cents = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))

            line = (
                _fixed_width(batch_filer_id, 9, pad="0", align="right") +
                _fixed_width(master_pin, 4, pad="0", align="right") +
                _fixed_width(file_date.strftime("%Y%m%d"), 8, pad="0", align="right") +
                _fixed_width(str(next_seq), 3, pad="0", align="right") +
                _fixed_width(str(payment_ref), 4, pad="0", align="right") +
                _fixed_width("P", 1) +
                _fixed_width(tin, 9, pad="0", align="right") +
                _fixed_width(taxpayer_pin, 4, pad="0", align="right") +
                _fixed_width(taxpayer_type, 1) +
                _fixed_width(tax_type_code, 5, pad="0", align="right") +
                _fixed_width(tax_period, 6, pad="0", align="right") +
                _fixed_width(p.due_date.strftime("%Y%m%d"), 8, pad="0", align="right") +
                _fixed_width(str(amount_cents), 15, pad="0", align="right")
            )

            lines.append(line)
            payment_ref += 1

        export_record = Export(user_id=current_user.id, status="generated")
        export_record.payments = payments
        db.session.add(export_record)
        db.session.commit()

        content = "\n".join(lines) + "\n"
        filename = f"estimate_tax_{current_user.firm_id}_{file_date.strftime('%Y%m%d')}_{str(next_seq).zfill(3)}.txt"
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route('/get-client-partial/<int:client_id>')
    @login_required
    def get_client_panel(client_id):
        from .models import Client, ScheduledPayment, PaymentSchedule, TaxRecord
        from datetime import datetime
        # Fetch the specific client
        client = db.session.get(Client, client_id)
        # Check if the user is authorized to view this client
        if not current_user.is_admin() and client not in current_user.clients:
            return "<div class='alert alert-danger'>Unauthorized Access</div>", 403

        latest_payment = (
            ScheduledPayment.query
            .join(PaymentSchedule, ScheduledPayment.schedule_id == PaymentSchedule.id)
            .join(TaxRecord, PaymentSchedule.tax_record_id == TaxRecord.id)
            .filter(TaxRecord.client_id == client.id)
            .order_by(
                ScheduledPayment.input_date.desc(),
                ScheduledPayment.input_time.desc(),
                ScheduledPayment.id.desc(),
            )
            .first()
        )

        latest_record = None
        if latest_payment and latest_payment.schedule and latest_payment.schedule.tax_record:
            latest_record = latest_payment.schedule.tax_record

        # Return the main panel with the selected client's information
        now = datetime.now()
        iso_date_string = now.strftime('%Y-%m-%d')
        return render_template(
            'partials/main_panel.html', 
            client=client,
            latest_payment=latest_payment,
            latest_record=latest_record,
            default_input_date=iso_date_string,
            default_input_time=now.strftime('%H:%M')
        )

    @app.route('/import/payments', methods=['POST'])
    @login_required
    def import_payments():
        from .models import Client, TaxRecord, ScheduledPayment, PaymentSchedule

        client_id = (request.form.get('client_id') or '').strip()
        up = request.files.get('file')
        if not client_id.isdigit() or not up or not getattr(up, "filename", None):
            return make_response('<div class="alert alert-danger py-2 small">Choose a CSV file.</div>', 200)

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return make_response('<div class="alert alert-danger py-2 small">Forbidden.</div>', 403)

        try:
            raw = up.read()
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            return make_response('<div class="alert alert-danger py-2 small">Could not read file.</div>', 200)

        def _looks_like_header(row):
            if not row:
                return False
            a = (row[0] or "").strip().lower()
            return "ein" in a or "ssn" in a or a == "tin"

        ok = 0
        errors = []
        for idx, row in enumerate(parse_csv_payment_rows(text), start=1):
            if _looks_like_header(row):
                continue
            if len(row) < 19:
                errors.append(f"Row {idx}: expected 19 columns, got {len(row)}.")
                continue
            try:
                ein = row[0].strip()
                tt = row[1].strip().upper()[:1]
                if tt not in ("B", "I"):
                    raise ValueError("column 2 must be B or I")

                # Columns 2–7, 9, 14–16, 18–19 are accepted in the file but not stored (export-only save path).

                tax_form = row[8].strip()
                # Column 10 = Tax Type (e.g. ES); 5 digits means tax type code only with no separate label
                raw_tax_col = row[10].strip()
                if re.fullmatch(r"\d{5}", raw_tax_col):
                    ttc = raw_tax_col
                    tax_type_label = ""
                else:
                    tax_type_label = raw_tax_col.upper()
                    ttc = map_csv_tax_type_to_code(raw_tax_col)
                    if tt == "I" and not ttc:
                        ttc = "10406"

                tp_digits, tax_year_int = normalize_tax_period_storage(row[11])
                amt = parse_decimal_amount(row[12])
                settle = parse_flexible_date(row[13])

                if amt <= 0:
                    raise ValueError("amount must be greater than 0")

                tin_digits = _digits_only(ein)
                if not re.fullmatch(r"\d{9}", tin_digits):
                    raise ValueError("EIN/SSN must be 9 digits")

                if tt == "B":
                    tax_form_f = tax_form
                    ttc_f = ttc
                else:
                    tax_form_f = tax_form or "1040"
                    ttc_f = ttc or "10406"

                if ttc_f and not re.fullmatch(r"\d{5}", ttc_f):
                    raise ValueError("Tax Type column: use 5-digit code, or a label like ES (maps to code 10406 for individuals).")

                # Sync TIN on client (formatted)
                if ein:
                    client.tax_id = ein

                new_record = TaxRecord(
                    client_id=client.id,
                    tax_year=tax_year_int,
                    estimated_tax_total=float(amt),
                    uploaded_by=current_user.id,
                    tax_form=tax_form_f,
                    tax_type_code=ttc_f,
                    tax_type=tax_type_label or None,
                    taxpayer_type=tt,
                    description=None,
                    upload_source="csv_import",
                )
                db.session.add(new_record)
                db.session.flush()

                sch = PaymentSchedule(tax_record_id=new_record.id, schedule_name="CSV import")
                db.session.add(sch)
                db.session.flush()

                sp = ScheduledPayment(
                    schedule_id=sch.id,
                    due_date=settle,
                    amount=float(amt),
                    status="pending",
                    eft_number="000000000000000",
                    tax_period=tp_digits,
                    input_method="B",
                    input_date=settle,
                    input_time=time(12, 0),
                )
                db.session.add(sp)
                db.session.flush()
                log_action("Imported Tax Payment (CSV)", entity_type="ScheduledPayment", entity_id=sp.id)
                db.session.commit()
                ok += 1
            except Exception as e:
                db.session.rollback()
                errors.append(f"Row {idx}: {e}")

        parts = [f'<div class="alert alert-success py-2 small border-0">Imported {ok} payment(s).</div>']
        if errors:
            lis = "".join(f'<li class="small">{escape(str(e))}</li>' for e in errors[:25])
            more = f"<li>… {len(errors) - 25} more</li>" if len(errors) > 25 else ""
            parts.append(
                f'<div class="alert alert-warning py-2 small border-0"><div class="fw-semibold">Issues</div>'
                f'<ul class="mb-0 ps-3">{lis}{more}</ul></div>'
            )
        return make_response("".join(parts), 200)

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
        settlement_date = request.form.get('settlement_date', '')
        tax_period_raw = request.form.get('tax_period', '').strip()
        tax_type_code = (request.form.get('tax_type_code') or '').strip()
        tin_raw = (request.form.get('tin') or '').strip()
        tin_digits = re.sub(r"\D+", "", tin_raw)
        taxpayer_type = (request.form.get('taxpayer_type_code') or 'I').strip().upper()

        # Validation Logic
        try:
            payment_amount = float(amount)
            settle_date_obj = datetime.strptime(settlement_date, '%Y-%m-%d').date()
        except ValueError:
            response = make_response('<div class="alert alert-danger">Check your date/amount format.</div>', 200)
            return response

        if not re.fullmatch(r"\d{9}", tin_digits):
            response = make_response('<div class="alert alert-danger">TIN must be 9 digits.</div>', 200)
            return response

        try:
            tax_period_digits, tax_year_int = normalize_tax_period_storage(tax_period_raw)
        except ValueError:
            response = make_response(
                '<div class="alert alert-danger">Tax Period must be YYYY or YYYYMM (annual exports as YYYY00).</div>',
                200,
            )
            return response

        ttc_digits = re.sub(r"\D+", "", tax_type_code)
        if taxpayer_type == 'B':
            if ttc_digits and not re.fullmatch(r"\d{5}", ttc_digits):
                response = make_response('<div class="alert alert-danger">Tax Type Code must be 5 digits or empty.</div>', 200)
                return response
            tax_type_code_stored = ttc_digits if ttc_digits else ''
            tax_form_val = (request.form.get('tax_form') or '').strip()
        else:
            if not re.fullmatch(r"\d{5}", ttc_digits):
                response = make_response('<div class="alert alert-danger">Tax Type Code must be 5 digits.</div>', 200)
                return response
            tax_type_code_stored = ttc_digits
            tax_form_val = (request.form.get('tax_form') or '').strip() or '1040'

        tax_type_label = (request.form.get('tax_type') or '').strip()
        if taxpayer_type == 'I':
            tax_type_label = tax_type_label or 'ES'
        else:
            tax_type_label = tax_type_label or None

        # Save to Database
        try:
            # Keep the client's stored TIN in sync with the tax input.
            client.tax_id = tin_raw

            # Create the Record
            new_record = TaxRecord(
                client_id=client.id,
                tax_year=tax_year_int,
                estimated_tax_total=payment_amount,
                uploaded_by=current_user.id,
                tax_form=tax_form_val,
                tax_type_code=tax_type_code_stored,
                tax_type=tax_type_label,
                taxpayer_type=taxpayer_type if taxpayer_type in {'B', 'I'} else 'I',
                description=None,
            )
            db.session.add(new_record)
            db.session.flush()

            new_schedule = PaymentSchedule(tax_record_id=new_record.id, schedule_name="Unspecified")
            db.session.add(new_schedule)
            db.session.flush()

            # Create the Payment (only export-related fields persisted; placeholder EFT for schema)
            new_payment = ScheduledPayment(
                schedule_id=new_schedule.id,
                due_date=settle_date_obj,
                amount=payment_amount,
                status='pending',
                eft_number='000000000000000',
                tax_period=tax_period_digits,
                input_method='B',
                input_date=settle_date_obj,
                input_time=time(12, 0),
            )

            db.session.add(new_payment)
            db.session.flush()
            log_action('Created Tax Payment', entity_type='ScheduledPayment', entity_id=new_payment.id)
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
        client.taxpayer_pin = request.form.get('taxpayer_pin')
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
            taxpayer_pin=request.form.get('taxpayer_pin'),
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