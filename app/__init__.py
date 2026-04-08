from flask import (
    Flask,
    app,
    current_app,
    make_response,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    Response,
    jsonify,
)
from markupsafe import escape
from datetime import datetime, date, timedelta, time

from .extensions import db, login_manager
from config import Config

from functools import wraps
from flask_login import current_user, login_required, login_user, logout_user
import os
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

import stripe


# Helper function to log user actions
def log_action(action, entity_type=None, entity_id=None):
    from .models import AuditLog

    uid = None
    if current_user and current_user.is_authenticated:
        uid = current_user.id

    new_log = AuditLog(
        user_id=uid,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=request.remote_addr
    )
    db.session.add(new_log)


# Initialize the rate limiter (attached to app later if not testing)
limiter = Limiter(get_remote_address)


def infer_taxpayer_type_from_tin(tin_raw: str) -> str:
    """
    Infer taxpayer type from formatted TIN string.
    - EIN format: XX-XXXXXXX -> Business (B)
    - SSN format: XXX-XX-XXXX -> Individual (I)
    """
    s = (tin_raw or "").strip()
    if re.fullmatch(r"\d{2}-\d{7}", s):
        return "B"
    if re.fullmatch(r"\d{3}-\d{2}-\d{4}", s):
        return "I"
    return "I"


def _require_4_digit_pin(pin_raw: str):
    pin = (pin_raw or "").strip()
    if not re.fullmatch(r"\d{4}", pin):
        return None
    return pin


def _normalize_ssn_optional(raw):
    """Return (9-digit SSN or None if empty, error message or None). Hyphens/formatting stripped."""
    def _digits_only(value: str) -> str:
        return re.sub(r"\D+", "", value or "")
    d = _digits_only(raw or "")
    if not d:
        return None, None
    if not re.fullmatch(r"\d{9}", d):
        return None, "SSN must be exactly 9 digits."
    return d, None


def _ensure_default_roles() -> None:
    """Seed roles table on fresh databases (create_all does not insert rows). Registration requires Admin."""
    from .models import Role

    names = ("Developer", "SysAdmin", "Admin", "Accountant")
    try:
        existing = {r.name for r in Role.query.all()}
        added = False
        for name in names:
            if name not in existing:
                db.session.add(Role(name=name))
                added = True
        if added:
            db.session.commit()
    except Exception:
        db.session.rollback()


def _ensure_sqlite_schema_up_to_date(app: Flask) -> None:
    """
    Lightweight SQLite schema patcher for local/dev DBs.

    SQLAlchemy's create_all() will not add new columns to an existing table.
    """
    uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
    if not uri.startswith("sqlite:///"):
        return

    try:
        from sqlalchemy import text

        cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(tax_records)")).all()]
        if "tax_type" not in cols:
            db.session.execute(text("ALTER TABLE tax_records ADD COLUMN tax_type VARCHAR(50)"))
            db.session.commit()
    except Exception:
        db.session.rollback()
        return


def create_app():
    app = Flask(__name__)
    
    # -----------------------------------
    # ------------ DATABASE -------------
    # -----------------------------------

    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        from . import models
        base = app.config.get("BASE_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        instance_dir = os.path.join(base, "instance")
        os.makedirs(instance_dir, exist_ok=True)
        db.create_all()
        _ensure_sqlite_schema_up_to_date(app)
        _ensure_default_roles()

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
        stripe.api_key = app.config['STRIPE_SECRET_KEY']

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
                existing_firm = Firm.query.get(existing_user.firm_id)

                if existing_firm and existing_firm.status == "Pending":
                    db.session.delete(existing_user)
                    db.session.delete(existing_firm)
                    db.session.commit()
                else:
                    flash('That email is already registered to a user.', 'danger')
                    return render_template('register-firm.html')
            
            # Create the firm and admin
            try:
                admin_role = Role.query.filter_by(name="Admin").first()
                if not admin_role:
                    current_app.logger.error("register_firm: Admin role missing; run DB seed or restart app to create roles.")
                    flash(
                        "Registration is unavailable because the server database is not fully initialized. "
                        "Ask the operator to restart the application or run role seeding.",
                        "danger",
                    )
                    return render_template("register-firm.html", firms=all_firms)

                new_firm = Firm(name=firm_name, email=firm_email, status="Pending")
                db.session.add(new_firm)
                db.session.flush() # Gets the firm ID before committing

                # Create the owner user
                owner = User(name=owner_name, email=admin_email, firm_id=new_firm.id, role_id=admin_role.id)
                owner.set_password(owner_password)
                db.session.add(owner)
                db.session.commit()

                # Create Stripe Checkout Session for the subscription
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price': app.config['STRIPE_SEAT_PRICE_ID'],
                        'quantity': 1, # 1 seat for the admin
                    }],
                    mode='subscription',
                    client_reference_id=str(new_firm.id), 
                    customer_email=firm_email,
                    
                    # Where to send them after they pay or cancel
                    success_url=url_for('login', _external=True) + '?registered=success',
                    cancel_url=url_for('register_firm', _external=True) + '?error=cancelled',
                )
                return redirect(checkout_session.url, code=303)
            
            except Exception as e:
                db.session.rollback()
                if app.config['TESTING']:
                    print(f"Registration Error: {e}")
                flash('An error occurred during registration. Please try again.', 'danger')
            
        return render_template('register-firm.html', firms=all_firms)
    

    @app.route('/webhook', methods=['POST'])
    def stripe_webhook():
        from .models import Firm
        
        payload = request.data
        sig_header = request.headers.get('Stripe-Signature')
        endpoint_secret = app.config.get('STRIPE_WEBHOOK_SECRET')

        try:
            # Verifies the webhook signature and constructs the event
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError as e:
            return jsonify({'error': 'Invalid payload'}), 400
        except stripe.error.SignatureVerificationError as e:
            return jsonify({'error': 'Invalid signature'}), 400

        # Handle successful checkout
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            firm_id = session.client_reference_id
            customer_id = session.customer

            if firm_id:
                firm = Firm.query.get(firm_id)
                if firm:
                    firm.status = "Active"
                    firm.stripe_customer_id = customer_id
                    log_action('Firm Activated', entity_type='Firm', entity_id=firm.id)
                    db.session.commit()
                    if app.config['TESTING']:
                        print(f"Webhook Success: Firm {firm.name} is now Active!")\
                        
        elif event['type'] == 'invoice.paid':
            invoice = event['data']['object']
            customer_id = invoice.customer

            firm = Firm.query.filter_by(stripe_customer_id=customer_id).first()
            if firm:
                firm.status = "Active"
                log_action('Payment Received - Marked Active', entity_type='Firm', entity_id=firm.id)
                db.session.commit()
                if app.config['TESTING']:
                    print(f"Webhook Alert: Payment received for Firm {firm.name}, marked as Active.")

        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            customer_id = invoice.customer

            firm = Firm.query.filter_by(stripe_customer_id=customer_id).first()
            if firm:
                firm.status = "Unpaid"
                log_action('Payment Failed - Marked Unpaid', entity_type='Firm', entity_id=firm.id)
                db.session.commit()
                if app.config['TESTING']:
                    print(f"Webhook Alert: Payment failed for Firm {firm.name}, marked as Unpaid.")

        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            customer_id = subscription.customer

            firm = Firm.query.filter_by(stripe_customer_id=customer_id).first()
            if firm:
                firm.status = "Cancelled"
                log_action('Subscription Cancelled', entity_type='Firm', entity_id=firm.id)
                db.session.commit()
                if app.config['TESTING']:
                    print(f"Webhook Alert: Subscription cancelled for Firm {firm.name}, marked as Cancelled.")

        # Return a 200 response to acknowledge receipt of the event
        return jsonify({'status': 'success'}), 200
        
    
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
            if user.firm.status == "Active":
                login_user(user, remember=remember)
                return redirect(url_for('dashboard'))
            else:
                if user.is_admin():
                    # Allow admins in with limited access
                    login_user(user, remember=remember)
                    return redirect(url_for('admin'))
                else:
                    flash('Your firm is currently not active. Please contact your administrator.', 'danger')
                    return redirect(url_for('login'))
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

        # Block being able to use dashboard if firm is not active
        if current_user.firm.status != "Active":
            return redirect(url_for('admin'))

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
        ssn_last2 = ""
        if selected_client and getattr(selected_client, "tax_id", None):
            d = re.sub(r"\D+", "", selected_client.tax_id or "")
            if re.fullmatch(r"\d{9}", d):
                ssn_last2 = d[-2:]
        return render_template(
            'dashboard.html',
            clients=clients,
            client=selected_client,
            selected_client=selected_client,
            default_taxpayer_type=infer_taxpayer_type_from_tin(getattr(selected_client, "tax_id", None)) if selected_client else "I",
            ssn_last2=ssn_last2,
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

    def _payment_dates_for_period(calendar_year: int, period: str, start: date, end: date, *, first_payment_date: date | None = None):
        """Return sorted unique payment dates in [start, end] for the given cadence."""
        period = (period or "").strip().lower()
        if start > end:
            return []

        def _add_months(d: date, months: int) -> date:
            y = d.year + (d.month - 1 + months) // 12
            m = (d.month - 1 + months) % 12 + 1
            ld = _last_day_of_month(y, m)
            return date(y, m, min(d.day, ld))

        def _anchored_dates(step_days: int | None = None, step_months: int | None = None):
            if not first_payment_date:
                return None
            d = first_payment_date
            out = []
            # Step forward until we're within [start, end]
            guard = 0
            while d < start and guard < 2000:
                if step_days is not None:
                    d = d + timedelta(days=step_days)
                else:
                    d = _add_months(d, int(step_months or 0))
                guard += 1
            while d <= end and guard < 4000:
                out.append(d)
                if step_days is not None:
                    d = d + timedelta(days=step_days)
                else:
                    d = _add_months(d, int(step_months or 0))
                guard += 1
            return out

        if period == "weekly":
            anchored = _anchored_dates(step_days=7)
            if anchored is not None:
                return anchored
            # End of week = Saturday.
            # Find first Saturday on/after start, then step by 7 days.
            days_until_sat = (5 - start.weekday()) % 7  # Mon=0 ... Sat=5
            d = start + timedelta(days=days_until_sat)
            out = []
            while d <= end:
                out.append(d)
                d += timedelta(days=7)
            return out

        if period == "biweekly":
            anchored = _anchored_dates(step_days=14)
            if anchored is not None:
                return anchored
            # End of week = Saturday, every other week.
            days_until_sat = (5 - start.weekday()) % 7
            d = start + timedelta(days=days_until_sat)
            out = []
            while d <= end:
                out.append(d)
                d += timedelta(days=14)
            return out

        if period == "monthly":
            anchored = _anchored_dates(step_months=1)
            if anchored is not None:
                return anchored
            out = []
            y, m = start.year, start.month
            while (y < end.year) or (y == end.year and m <= end.month):
                ld = _last_day_of_month(y, m)
                # Use end-of-month settlement dates.
                d = date(y, m, ld)
                if d >= start and d <= end:
                    out.append(d)
                if m == 12:
                    y += 1
                    m = 1
                else:
                    m += 1
            return out

        if period == "quarterly":
            anchored = _anchored_dates(step_months=3)
            if anchored is not None:
                return anchored
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

    def _split_total_dollars_by_quarter_targets(calendar_year: int, start: date, pay_dates: list[date], total_dollars: int) -> list[int]:
        """
        Split a whole-dollar annual total across pay_dates such that by each quarter end,
        the cumulative total meets 25%/50%/75%/100% targets (with integer rounding).

        Any remainder dollars are pushed into the last payment of the relevant quarter.
        """
        if total_dollars < 0:
            raise ValueError("total_dollars must be non-negative")
        if not pay_dates:
            return []

        q_ends = [
            date(calendar_year, 3, 31),
            date(calendar_year, 6, 30),
            date(calendar_year, 9, 30),
            date(calendar_year, 12, 31),
        ]

        # Bucket pay_dates by quarter index.
        buckets: list[list[int]] = [[], [], [], []]  # indices into pay_dates
        for i, d in enumerate(pay_dates):
            if d <= q_ends[0]:
                buckets[0].append(i)
            elif d <= q_ends[1]:
                buckets[1].append(i)
            elif d <= q_ends[2]:
                buckets[2].append(i)
            else:
                buckets[3].append(i)

        # Quarter cumulative targets (whole dollars). Use integer math with "round up" to avoid falling short.
        def _ceil_div(a: int, b: int) -> int:
            return (a + b - 1) // b

        targets = [
            _ceil_div(total_dollars * 1, 4),
            _ceil_div(total_dollars * 2, 4),
            _ceil_div(total_dollars * 3, 4),
            total_dollars,
        ]

        parts = [0] * len(pay_dates)
        allocated = 0
        for qi, q_end in enumerate(q_ends):
            idxs = buckets[qi]
            # If this quarter has no pay dates, we can't allocate here; next quarters must catch up.
            if not idxs:
                continue
            required_cum = targets[qi]
            q_total = max(0, required_cum - allocated)
            # Split q_total across this quarter's payments in whole dollars.
            base = q_total // len(idxs)
            rem = q_total % len(idxs)
            for j, pay_i in enumerate(idxs):
                parts[pay_i] = base + (1 if j < rem else 0)
            allocated += q_total

        # If we still have unallocated dollars (e.g., because early quarters had no payments),
        # put them into the last payment date.
        if allocated != total_dollars:
            parts[-1] += (total_dollars - allocated)

        if sum(parts) != total_dollars or min(parts) < 0:
            raise ValueError("Could not split dollars by quarter targets")
        return parts

    @app.route('/export/generate-schedule', methods=['POST'])
    @login_required
    def generate_export_schedule():
        from .models import Client, TaxRecord, ScheduledPayment, PaymentSchedule
        from decimal import Decimal, ROUND_HALF_UP

        client_id = (request.form.get("client_id") or "").strip()
        period = (request.form.get("period") or "").strip().lower()
        first_payment_date_raw = (request.form.get("first_payment_date") or "").strip()
        first_payment_date = None
        if first_payment_date_raw:
            try:
                first_payment_date = datetime.strptime(first_payment_date_raw, "%Y-%m-%d").date()
            except ValueError:
                return '<div class="alert alert-danger py-2 small">First payment date must be YYYY-MM-DD.</div>', 200

        if not client_id.isdigit():
            return '<div class="alert alert-danger py-2 small">Invalid client.</div>', 200
        if period in {"", "none"}:
            return '<div class="alert alert-danger py-2 small">Choose a split period above to generate payments.</div>', 200
        if period not in {"quarterly", "monthly", "biweekly", "weekly"}:
            return '<div class="alert alert-danger py-2 small">Choose a valid period.</div>', 200

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return '<div class="alert alert-danger py-2 small">Forbidden.</div>', 403

        tin = _digits_only(client.tax_id)
        if not re.fullmatch(r"\d{9}", tin):
            return '<div class="alert alert-danger py-2 small">Client SSN must be 9 digits before generating payments.</div>', 200
        tp = _digits_only(client.taxpayer_pin)
        if not re.fullmatch(r"\d{4}", tp):
            return '<div class="alert alert-danger py-2 small">Client Taxpayer PIN must be 4 digits before generating payments.</div>', 200

        latest_record = (
            TaxRecord.query
            .filter_by(client_id=client.id)
            .order_by(TaxRecord.id.desc())
            .first()
        )
        if not latest_record:
            return '<div class="alert alert-danger py-2 small">Save client tax data first (tax year + annual total) before generating payments.</div>', 200

        calendar_year = int(latest_record.tax_year or date.today().year)
        try:
            total_annual = Decimal(str(latest_record.estimated_tax_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            return '<div class="alert alert-danger py-2 small">Saved annual total is not a valid number.</div>', 200
        if total_annual <= 0:
            return '<div class="alert alert-danger py-2 small">Saved annual total must be greater than 0.</div>', 200
        if total_annual != total_annual.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
            return '<div class="alert alert-danger py-2 small">Saved annual total must be whole dollars (no decimals).</div>', 200

        year_start = date(calendar_year, 1, 1)
        year_end = date(calendar_year, 12, 31)
        pay_dates = _payment_dates_for_period(calendar_year, period, year_start, year_end, first_payment_date=first_payment_date)
        if not pay_dates:
            return '<div class="alert alert-danger py-2 small">No payment dates could be generated for that period.</div>', 200
        if len(pay_dates) > 400:
            return '<div class="alert alert-danger py-2 small">Too many payments; narrow the period or year.</div>', 200

        total_dollars = int(total_annual.to_integral_value(rounding=ROUND_HALF_UP))
        if total_dollars < len(pay_dates):
            return '<div class="alert alert-danger py-2 small">Saved annual total is too small for this many payments (each installment must be at least $1).</div>', 200

        try:
            if period == "quarterly":
                dollar_parts = _split_total_dollars_by_quarter_targets(calendar_year, year_start, pay_dates, total_dollars)
            else:
                base = total_dollars // len(pay_dates)
                rem = total_dollars % len(pay_dates)
                dollar_parts = [base + (1 if i < rem else 0) for i in range(len(pay_dates))]
        except Exception:
            return '<div class="alert alert-danger py-2 small">Could not split payment amounts.</div>', 200

        try:
            schedule = PaymentSchedule(
                tax_record_id=latest_record.id,
                schedule_name=f"{calendar_year} {period} export schedule",
            )
            db.session.add(schedule)
            db.session.flush()

            noon = time(12, 0)
            rows = []
            for d, dollars in zip(pay_dates, dollar_parts):
                sp = ScheduledPayment(
                    schedule_id=schedule.id,
                    due_date=d,
                    amount=float(Decimal(int(dollars)).quantize(Decimal("0.00"))),
                    status="pending",
                    eft_number="000000000000000",
                    tax_period=f"{calendar_year}00",
                    input_method="B",
                    input_date=date.today(),
                    input_time=noon,
                )
                db.session.add(sp)
                rows.append((d, int(dollars)))

            db.session.flush()
            log_action(
                f"Generated {len(pay_dates)} scheduled export payments ({period}, {calendar_year})",
                entity_type="PaymentSchedule",
                entity_id=schedule.id,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            return '<div class="alert alert-danger py-2 small">Could not save payments. Try again.</div>', 200

        payments = (
            ScheduledPayment.query.filter_by(schedule_id=schedule.id)
            .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
            .all()
        )
        return render_template(
            "partials/export_schedule_payments.html",
            schedule=schedule,
            payments=payments,
            save_message=f"Generated {len(payments)} payment(s). Review or edit below, then save if you change anything.",
        )

    @app.route("/export/schedule/<int:schedule_id>/payments", methods=["POST"])
    @login_required
    def update_schedule_payments(schedule_id):
        from .models import ScheduledPayment, PaymentSchedule, TaxRecord
        from decimal import Decimal, ROUND_HALF_UP

        sch = db.session.get(PaymentSchedule, schedule_id)
        if not sch:
            return '<div class="alert alert-danger py-2 small">Schedule not found.</div>', 200
        tr = sch.tax_record
        if not tr:
            return '<div class="alert alert-danger py-2 small">Invalid schedule.</div>', 200
        client = tr.client
        if not client or client.firm_id != current_user.firm_id:
            return '<div class="alert alert-danger py-2 small">Forbidden.</div>', 403
        if not current_user.is_admin() and client not in current_user.clients:
            return '<div class="alert alert-danger py-2 small">Forbidden.</div>', 403

        pids = [p.id for p in ScheduledPayment.query.filter_by(schedule_id=schedule_id).all()]
        if not pids:
            return '<div class="alert alert-danger py-2 small">No payments in this schedule.</div>', 200

        updates = []
        for pid in pids:
            d_raw = (request.form.get(f"due_date_{pid}") or "").strip()
            a_raw = (request.form.get(f"amount_{pid}") or "").strip()
            try:
                d_obj = datetime.strptime(d_raw, "%Y-%m-%d").date()
            except ValueError:
                return render_template(
                    "partials/export_schedule_payments.html",
                    schedule=sch,
                    payments=ScheduledPayment.query.filter_by(schedule_id=schedule_id)
                    .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
                    .all(),
                    save_message="Invalid date on one or more rows.",
                ), 200
            try:
                amt_dec = Decimal(str(a_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception:
                return render_template(
                    "partials/export_schedule_payments.html",
                    schedule=sch,
                    payments=ScheduledPayment.query.filter_by(schedule_id=schedule_id)
                    .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
                    .all(),
                    save_message="Invalid amount on one or more rows.",
                ), 200
            if amt_dec != amt_dec.quantize(Decimal("1")):
                return render_template(
                    "partials/export_schedule_payments.html",
                    schedule=sch,
                    payments=ScheduledPayment.query.filter_by(schedule_id=schedule_id)
                    .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
                    .all(),
                    save_message="Amounts must be whole dollars.",
                ), 200
            if amt_dec < 1:
                return render_template(
                    "partials/export_schedule_payments.html",
                    schedule=sch,
                    payments=ScheduledPayment.query.filter_by(schedule_id=schedule_id)
                    .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
                    .all(),
                    save_message="Each amount must be at least $1.",
                ), 200
            updates.append((pid, d_obj, float(amt_dec)))

        try:
            for pid, d_obj, amt_f in updates:
                sp = db.session.get(ScheduledPayment, pid)
                if not sp or sp.schedule_id != schedule_id:
                    raise ValueError("payment mismatch")
                sp.due_date = d_obj
                sp.amount = amt_f
                sp.tax_period = f"{d_obj.year}00"
            db.session.flush()
            log_action("Updated scheduled export payments", entity_type="PaymentSchedule", entity_id=schedule_id)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return render_template(
                "partials/export_schedule_payments.html",
                schedule=sch,
                payments=ScheduledPayment.query.filter_by(schedule_id=schedule_id)
                .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
                .all(),
                save_message="Could not save changes.",
            ), 200

        payments = (
            ScheduledPayment.query.filter_by(schedule_id=schedule_id)
            .order_by(ScheduledPayment.due_date.asc(), ScheduledPayment.id.asc())
            .all()
        )
        return render_template(
            "partials/export_schedule_payments.html",
            schedule=sch,
            payments=payments,
            save_message="Changes saved.",
        )

    @app.route('/export/auto', methods=['POST'])
    @login_required
    def export_auto():
        """
        One-click export:
        - If a split period is selected, generate a full schedule (if none pending already).
        - Export all pending payments for the client in a single file using today's file_date.
        """
        from .models import Client, ScheduledPayment, PaymentSchedule, TaxRecord

        client_id = (request.form.get("client_id") or "").strip()
        if not client_id.isdigit():
            return make_response('<div class="alert alert-danger py-2 small">Invalid client.</div>', 200)

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return make_response('<div class="alert alert-danger py-2 small">Forbidden.</div>', 403)

        period = (request.form.get("period") or "").strip().lower()
        if period in {"", "none"}:
            period = ""

        today = date.today()
        first_payment_date_raw = (request.form.get("first_payment_date") or "").strip()
        first_payment_date = None
        if first_payment_date_raw:
            try:
                first_payment_date = datetime.strptime(first_payment_date_raw, "%Y-%m-%d").date()
            except ValueError:
                return make_response('<div class="alert alert-danger py-2 small">First payment date must be YYYY-MM-DD.</div>', 200)

        schedule_id = None

        # If asked to split, auto-generate a schedule using the client's latest saved tax record
        # (no need to re-select taxpayer type/form/type code in the UI).
        if period:
            if period not in {"quarterly", "monthly", "biweekly", "weekly"}:
                return make_response('<div class="alert alert-danger py-2 small">Choose a valid period.</div>', 200)

            tin = _digits_only(client.tax_id)
            if not re.fullmatch(r"\d{9}", tin):
                return make_response('<div class="alert alert-danger py-2 small">Client TIN must be 9 digits before exporting.</div>', 200)
            tp = _digits_only(client.taxpayer_pin)
            if not re.fullmatch(r"\d{4}", tp):
                return make_response('<div class="alert alert-danger py-2 small">Client Taxpayer PIN must be 4 digits before exporting.</div>', 200)

            latest_record = (
                TaxRecord.query
                .filter_by(client_id=client.id)
                .order_by(TaxRecord.id.desc())
                .first()
            )
            if not latest_record:
                return make_response('<div class="alert alert-danger py-2 small">Save client tax data first (to store tax form/type code/amount) before exporting.</div>', 200)

            calendar_year = int(latest_record.tax_year or today.year)

            from decimal import Decimal, ROUND_HALF_UP
            try:
                total_annual = Decimal(str(latest_record.estimated_tax_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception:
                return make_response('<div class="alert alert-danger py-2 small">Saved annual total is not a valid number.</div>', 200)
            if total_annual <= 0:
                return make_response('<div class="alert alert-danger py-2 small">Saved annual total must be greater than 0.</div>', 200)
            if total_annual != total_annual.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
                return make_response('<div class="alert alert-danger py-2 small">Saved annual total must be whole dollars (no decimals).</div>', 200)

            taxpayer_type = (latest_record.taxpayer_type or "").strip().upper() or infer_taxpayer_type_from_tin(client.tax_id)
            if taxpayer_type not in {"B", "I"}:
                taxpayer_type = infer_taxpayer_type_from_tin(client.tax_id)

            tax_form_in = "1040"
            tax_type_code_in = "10406"

            year_start = date(calendar_year, 1, 1)
            year_end = date(calendar_year, 12, 31)
            pay_dates = _payment_dates_for_period(calendar_year, period, year_start, year_end, first_payment_date=first_payment_date)
            if not pay_dates:
                return make_response('<div class="alert alert-danger py-2 small">No payment dates could be generated for that period.</div>', 200)
            if len(pay_dates) > 400:
                return make_response('<div class="alert alert-danger py-2 small">Too many payments; narrow the period or year.</div>', 200)

            total_dollars = int(total_annual.to_integral_value(rounding=ROUND_HALF_UP))
            if total_dollars < len(pay_dates):
                return make_response('<div class="alert alert-danger py-2 small">Saved annual total is too small for this many payments (each installment must be at least $1).</div>', 200)

            try:
                if period == "quarterly":
                    dollar_parts = _split_total_dollars_by_quarter_targets(calendar_year, year_start, pay_dates, total_dollars)
                else:
                    # Even split across the generated payments (whole dollars).
                    base = total_dollars // len(pay_dates)
                    rem = total_dollars % len(pay_dates)
                    dollar_parts = [base + (1 if i < rem else 0) for i in range(len(pay_dates))]
            except Exception:
                return make_response('<div class="alert alert-danger py-2 small">Could not split payment amounts.</div>', 200)

            try:
                schedule = PaymentSchedule(
                    tax_record_id=latest_record.id,
                    schedule_name=f"{calendar_year} {period} export schedule",
                )
                db.session.add(schedule)
                db.session.flush()
                schedule_id = schedule.id

                noon = time(12, 0)
                for d, dollars in zip(pay_dates, dollar_parts):
                    sp = ScheduledPayment(
                        schedule_id=schedule.id,
                        due_date=d,
                        amount=float(Decimal(int(dollars)).quantize(Decimal("0.00"))),
                        status="pending",
                        eft_number="000000000000000",
                            tax_period=f"{calendar_year}00",
                        input_method="B",
                        input_date=today,  # one-click file date
                        input_time=noon,
                    )
                    db.session.add(sp)

                db.session.flush()
                log_action(
                    f"Auto-generated {len(pay_dates)} scheduled export payments ({period}, {calendar_year})",
                    entity_type="PaymentSchedule",
                    entity_id=schedule.id,
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                return make_response('<div class="alert alert-danger py-2 small">Could not save schedule. Check saved tax data and try again.</div>', 200)

        if schedule_id:
            return redirect(url_for("export_fixed_width", schedule_id=schedule_id, file_date=today.strftime("%Y-%m-%d")))
        return (
            "Choose a split period and generate payments before exporting (export requires a schedule).",
            400,
        )

    @app.route('/export/fixed-width', methods=['GET'])
    @login_required
    def export_fixed_width():
        from .models import ScheduledPayment, PaymentSchedule, TaxRecord, Client, Export
        from decimal import Decimal, ROUND_HALF_UP

        file_date_raw = (request.args.get('file_date') or '').strip()
        try:
            file_date = datetime.strptime(file_date_raw, "%Y-%m-%d").date()
        except ValueError:
            return "file_date must be YYYY-MM-DD", 400

        schedule_id_filter = request.args.get("schedule_id", type=int)
        export_all_dates = (request.args.get("all_dates") or "").strip() in {"1", "true", "yes"}

        if schedule_id_filter is None:
            return (
                "Export requires schedule_id (generate payments for this client, then export that schedule).",
                400,
            )

        sch = db.session.get(PaymentSchedule, schedule_id_filter)
        if not sch:
            return "Invalid schedule.", 400
        tr = sch.tax_record
        if not tr:
            return "Invalid schedule.", 400
        client_scope = tr.client
        if not client_scope or client_scope.firm_id != current_user.firm_id:
            return "Forbidden", 403
        if not current_user.is_admin() and client_scope not in current_user.clients:
            return "Forbidden", 403

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

        q = ScheduledPayment.query.filter(
            ScheduledPayment.schedule_id == schedule_id_filter,
            ScheduledPayment.status == "pending",
        )
        if not export_all_dates:
            q = q.filter(ScheduledPayment.input_date == file_date)

        payments = q.order_by(ScheduledPayment.id.asc()).all()
        # Safety: ORM/joins elsewhere have duplicated rows; schedules are unique by id here.
        payments = sorted({p.id: p for p in payments}.values(), key=lambda p: p.id)

        if not payments:
            return "No pending payments found for this schedule and file date.", 400

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

            tax_type_code = "10406"

            tax_period = _digits_only(p.tax_period)
            if not re.fullmatch(r"\d{6}", tax_period):
                return f"Tax Period must be YYYY00 for client {c.id}.", 400
            month = int(tax_period[4:6])
            if month != 0:
                return f"Tax Period month must be 00 (annual) for client {c.id}.", 400

            if not p.due_date:
                return f"Settlement Date missing for client {c.id}.", 400

            amount = Decimal(str(p.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            # Payment amounts are whole dollars; export file does NOT use cents.
            if amount != amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
                return f"Payment Amount must be whole dollars for client {c.id}.", 400
            if amount <= 0 or amount >= Decimal("1000000000000000"):
                return f"Payment Amount out of range for client {c.id}.", 400
            amount_dollars = int(amount.to_integral_value(rounding=ROUND_HALF_UP))

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
                _fixed_width(str(amount_dollars), 15, pad="0", align="right")
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

        latest_record = (
            TaxRecord.query
            .filter(TaxRecord.client_id == client.id)
            .order_by(TaxRecord.id.desc())
            .first()
        )

        # Return the main panel with the selected client's information
        now = datetime.now()
        iso_date_string = now.strftime('%Y-%m-%d')
        ssn_last2 = ""
        if getattr(client, "tax_id", None):
            d = re.sub(r"\D+", "", client.tax_id or "")
            if re.fullmatch(r"\d{9}", d):
                ssn_last2 = d[-2:]
        return render_template(
            'partials/main_panel.html', 
            client=client,
            latest_record=latest_record,
            default_taxpayer_type=infer_taxpayer_type_from_tin(getattr(client, "tax_id", None)),
            ssn_last2=ssn_last2,
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
        from .models import Client, TaxRecord
        from decimal import Decimal

        # Verification & Client Lookup
        client_id = request.form.get('client_id', '').strip()
        if not client_id or not client_id.isdigit():
            response = make_response('<div class="alert alert-danger">Please select a valid client.</div>', 200)
            return response

        client = Client.query.get_or_404(int(client_id))
        if client.firm_id != current_user.firm_id:
            return "Forbidden", 403

        # Data Extraction
        amount = request.form.get('total_annual_amount', '0')
        tax_year_raw = (request.form.get('tax_period') or '').strip()
        tin_raw_in = (request.form.get('tin') or '').strip()
        tin_digits_in = re.sub(r"\D+", "", tin_raw_in)
        pin_raw = (request.form.get('taxpayer_pin') or '').strip()

        # Validation Logic
        try:
            payment_amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
            if payment_amount_dec != payment_amount_dec.quantize(Decimal("1")):
                response = make_response('<div class="alert alert-danger">Payment amount must be whole dollars (no decimals).</div>', 200)
                return response
            payment_amount = float(payment_amount_dec)
        except ValueError:
            response = make_response('<div class="alert alert-danger">Check your date/amount format.</div>', 200)
            return response

        tin_digits = tin_digits_in
        if not tin_digits:
            # Allow leaving SSN hidden/unchanged.
            tin_digits = re.sub(r"\D+", "", client.tax_id or "")
        if not re.fullmatch(r"\d{9}", tin_digits):
            response = make_response('<div class="alert alert-danger">SSN must be 9 digits.</div>', 200)
            return response

        pin = _require_4_digit_pin(pin_raw)
        if not pin:
            response = make_response('<div class="alert alert-danger">Taxpayer PIN must be exactly 4 digits.</div>', 200)
            return response

        if not re.fullmatch(r"\d{4}", tax_year_raw):
            response = make_response('<div class="alert alert-danger">Tax Year must be YYYY.</div>', 200)
            return response
        tax_year_int = int(tax_year_raw)

        # Tax metadata is fixed for this app.
        tax_type_code_stored = "10406"
        tax_form_val = "1040"
        tax_type_label = "ES"

        # Save to Database
        try:
            # Keep the client's stored SSN/PIN in sync with the tax input.
            client.tax_id = tin_digits
            client.taxpayer_pin = pin

            # Create the Record
            new_record = TaxRecord(
                client_id=client.id,
                tax_year=tax_year_int,
                estimated_tax_total=payment_amount,
                uploaded_by=current_user.id,
                tax_form=tax_form_val,
                tax_type_code=tax_type_code_stored,
                tax_type=tax_type_label,
                taxpayer_type='I',
                description=None,
            )
            db.session.add(new_record)
            db.session.flush()
            log_action('Saved Client Tax Data', entity_type='TaxRecord', entity_id=new_record.id)
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
        from .models import Client, User, Role, Firm

        # Get all clients and accountants in the firm
        clients = Client.query.filter_by(firm_id=current_user.firm_id).all()
        accountants = User.query.filter(
            User.role.has(Role.name == 'Accountant'), 
            User.firm_id == current_user.firm_id
        ).all()

        # Get subscription info from Stripe
        firm = Firm.query.get(current_user.firm_id)
        next_payment_date = "N/A"
        payment_amount = "0.00"
        stripe.api_key = app.config['STRIPE_SECRET_KEY']

        if firm.stripe_customer_id:
            try:
                subs = stripe.Subscription.list(customer=firm.stripe_customer_id, status='active', limit=1)
                
                if subs.data:
                    active_sub_id = subs.data[0].id
                    
                    upcoming_invoice = stripe.Invoice.create_preview(
                        customer=firm.stripe_customer_id,
                        subscription=active_sub_id
                    )
                    
                    raw_amount = getattr(upcoming_invoice, 'amount_due', 0)
                    payment_amount = f"{raw_amount / 100:.2f}"
                    
                    end_timestamp = getattr(upcoming_invoice, 'period_end', None)
                    if not end_timestamp and hasattr(upcoming_invoice, 'get'):
                        end_timestamp = upcoming_invoice.get('period_end')
                        
                    if end_timestamp:
                        next_payment_date = datetime.fromtimestamp(end_timestamp).strftime('%B %d, %Y')
                    
            except Exception as e:
                if app.config['TESTING']:
                    print(f"Stripe Error: {e}")

        return render_template('admin.html', 
                            clients=clients, 
                            accountants=accountants,
                            next_payment_date=next_payment_date,
                            payment_amount=payment_amount)
    
    
    @app.route('/billing-portal', methods=['POST'])
    def billing_portal():
        from .models import Firm
        firm = Firm.query.get(current_user.firm_id)
        stripe.api_key = app.config['STRIPE_SECRET_KEY']
        
        if not firm.stripe_customer_id:
            # flash("No active billing account found.", "danger")
            return redirect(url_for('admin'))
            
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=firm.stripe_customer_id,
                return_url=url_for('admin', _external=True)
            )
            return redirect(portal_session.url, code=303)
        except Exception as e:
            print(f"Portal Error: {e}")
            # flash("Could not connect to billing portal.", "danger")
            return redirect(url_for('admin'))

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
        tp = _require_4_digit_pin(request.form.get('taxpayer_pin'))
        if not tp:
            return render_template('partials/edit_client_form.html', client=client, error="Taxpayer PIN must be exactly 4 digits.")
        ssn, ssn_err = _normalize_ssn_optional(request.form.get("tax_id"))
        if ssn_err:
            return render_template("partials/edit_client_form.html", client=client, error=ssn_err)
        # Update info
        client.name = request.form.get('name')
        client.email = request.form.get('email')
        client.phone = request.form.get('phone')
        client.address = request.form.get('address')
        client.tax_id = ssn
        client.taxpayer_pin = tp
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

        tp = _require_4_digit_pin(request.form.get('taxpayer_pin'))
        if not tp:
            from .models import Role
            all_accountants = User.query.filter(User.role.has(Role.name == 'Accountant'), User.firm_id == current_user.firm_id).all()
            return render_template('partials/add_client_form.html', all_accountants=all_accountants, error="Taxpayer PIN must be exactly 4 digits.")

        ssn, ssn_err = _normalize_ssn_optional(request.form.get("tax_id"))
        if ssn_err:
            from .models import Role
            all_accountants = User.query.filter(User.role.has(Role.name == 'Accountant'), User.firm_id == current_user.firm_id).all()
            return render_template("partials/add_client_form.html", all_accountants=all_accountants, error=ssn_err)

        new_client = Client(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            tax_id=ssn,
            taxpayer_pin=tp,
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
        from .models import User, Firm
        from flask import make_response
        
        accountant = User.query.get_or_404(user_id)
        if accountant.firm_id != current_user.firm_id:
            return "Forbidden", 403
        log_action('Deleted Accountant: ' + accountant.name, entity_type='User', entity_id=accountant.id)
        db.session.delete(accountant)
        db.session.commit()

        # Stripe logic for updating subscription
        stripe.api_key = app.config['STRIPE_SECRET_KEY']
        firm = Firm.query.get(current_user.firm_id)
        total_seats = User.query.filter_by(firm_id=firm.id).count()
        if firm.stripe_customer_id:
            try:
                subs = stripe.Subscription.list(customer=firm.stripe_customer_id, status='active', limit=1)
                
                if subs.data:
                    sub = subs.data[0]
                    sub_item_id = sub.items.data[0].id
                    
                    stripe.Subscription.modify(
                        sub.id,
                        items=[{"id": sub_item_id, "quantity": total_seats}]
                    )
                    print(f"Stripe Success: Firm seats updated to {total_seats}!")
                    
            except Exception as e:
                if app.config['TESTING']:
                    print(f"Stripe Seat Update Error: {e}")

        response = make_response("", 200)
        response.headers['HX-Refresh'] = 'true'
        return response
    
    @app.route('/admin/accountant/add', methods=['GET'])
    @admin_required
    def add_accountant_form():
        from .models import Firm

        stripe.api_key = app.config['STRIPE_SECRET_KEY']
        firm = Firm.query.get(current_user.firm_id)
        seat_price = "0.00"
        if firm.stripe_customer_id:
            try:
                subs = stripe.Subscription.list(customer=firm.stripe_customer_id, status='active', limit=1)
                if subs.data:
                    first_item = subs.data[0].items.data[0]
                    raw_amount = getattr(first_item.price, 'unit_amount', 0)
                    if raw_amount:
                        seat_price = f"{raw_amount / 100:.2f}"
            except Exception as e:
                if app.config['TESTING']:
                    print(f"Form Price Fetch Error: {e}")

        return render_template('partials/add_accountant_form.html', seat_price=seat_price)
    
    @app.route('/admin/accountant/create', methods=['POST'])
    @admin_required
    def create_accountant():
        from .models import User, Role, Firm
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

            # Stripe logic for updating subscription
            stripe.api_key = app.config['STRIPE_SECRET_KEY']
            firm = Firm.query.get(current_user.firm_id)
            total_seats = User.query.filter_by(firm_id=firm.id).count()
            if firm.stripe_customer_id:
                try:
                    subs = stripe.Subscription.list(customer=firm.stripe_customer_id, status='active', limit=1)
                    
                    if subs.data:
                        sub = subs.data[0]
                        sub_item_id = sub.items.data[0].id
                        
                        stripe.Subscription.modify(
                            sub.id,
                            items=[{"id": sub_item_id, "quantity": total_seats}]
                        )
                        print(f"Stripe Success: Firm seats updated to {total_seats}!")
                        
                except Exception as e:
                    if app.config['TESTING']:
                        print(f"Stripe Seat Update Error: {e}")


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