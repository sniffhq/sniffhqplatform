"""
SniffHQ Platform Admin
admin.sniffhq.app — tenant provisioning control plane + monitoring

Run with:
    waitress-serve --port=9000 --threads=4 app:app
"""

import os
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY']                = os.environ['PLATFORM_SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI']   = 'sqlite:///platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_ENABLED']          = False   # internal-only admin tool

db = SQLAlchemy(app)

TIER_LABELS = {
    'starter':      'Starter — $55/mo',
    'professional': 'Professional — $135/mo',
    'enterprise':   'Enterprise — $249/mo',
}


# ── Model ─────────────────────────────────────────────────────────────────────

class Tenant(db.Model):
    __tablename__ = 'tenant'
    id              = db.Column(db.Integer, primary_key=True)
    slug            = db.Column(db.String(100), unique=True, nullable=False)
    business_name   = db.Column(db.String(200), nullable=False)
    email           = db.Column(db.String(200), nullable=False)
    tier            = db.Column(db.String(50),  nullable=False)
    status          = db.Column(db.String(20),  default='active')   # active | suspended
    port            = db.Column(db.Integer,     nullable=True)
    provisioned_at  = db.Column(db.DateTime,    default=datetime.utcnow)
    notes           = db.Column(db.Text,        nullable=True)


class Snapshot(db.Model):
    """5-minute historical metric snapshots per tenant."""
    __tablename__ = 'snapshot'
    id         = db.Column(db.Integer, primary_key=True)
    app_id     = db.Column(db.String(100), nullable=False, index=True)
    ts         = db.Column(db.DateTime,    default=datetime.utcnow, index=True)
    cpu_pct    = db.Column(db.Float,   nullable=True)
    mem_pct    = db.Column(db.Float,   nullable=True)
    disk_pct   = db.Column(db.Float,   nullable=True)
    svc_up     = db.Column(db.Boolean, nullable=True)
    resp_ms    = db.Column(db.Integer, nullable=True)
    error_cnt  = db.Column(db.Integer, nullable=True)
    sms_sent   = db.Column(db.Integer, nullable=True)
    bookings   = db.Column(db.Integer, nullable=True)
    logins     = db.Column(db.Integer, nullable=True)


class AlertConfig(db.Model):
    """Per-metric alert thresholds."""
    __tablename__ = 'alert_config'
    id           = db.Column(db.Integer, primary_key=True)
    metric       = db.Column(db.String(50), unique=True, nullable=False)
    enabled      = db.Column(db.Boolean, default=False)
    threshold    = db.Column(db.Float,   nullable=True)
    notify_email = db.Column(db.String(120), nullable=True)
    updated_at   = db.Column(db.DateTime,    default=datetime.utcnow)


with app.app_context():
    db.create_all()


# ── Monitoring helpers ─────────────────────────────────────────────────────────

def _get_monitored_apps():
    """Build monitored-apps list dynamically from provisioned tenants."""
    tenants_dir = os.environ.get('TENANTS_DIR', r'C:\SniffHQ\tenants')
    tenants = Tenant.query.filter_by(status='active').order_by(Tenant.business_name).all()
    return [
        {
            'id':           t.slug,
            'name':         t.business_name,
            'tier':         t.tier,
            'db_path':      os.path.join(tenants_dir, t.slug, 'instance', 'sniffhq.db'),
            'log_path':     os.path.join(tenants_dir, t.slug, 'logs', 'app.log'),
            'nssm_service': f'SniffHQ_{t.slug}',
            'base_url':     f'http://localhost:{t.port}',
            'color':        '#3DBDB5',
            'port':         t.port,
        }
        for t in tenants if t.port
    ]


def _collect_all():
    from metrics.infrastructure import get_system_metrics, get_service_status, ping_app
    from metrics.application    import get_all_metrics
    from metrics.logs           import get_error_count, get_recent_error_lines

    sys_m    = get_system_metrics()
    app_cfgs = _get_monitored_apps()
    app_data = []

    for cfg in app_cfgs:
        svc_up        = get_service_status(cfg['nssm_service'])
        resp_ms       = ping_app(cfg['base_url']) if svc_up else None
        metrics       = get_all_metrics(cfg['db_path'])
        error_count   = get_error_count(cfg.get('log_path', ''))
        recent_errors = get_recent_error_lines(cfg.get('log_path', ''), limit=10)

        score = 100
        if not svc_up:                     score -= 50
        if resp_ms and resp_ms > 2000:     score -= 20
        if error_count > 10:               score -= 15
        if metrics['sms_failures'] > 5:    score -= 10
        if metrics['failed_logins'] > 20:  score -= 5
        score = max(0, score)

        app_data.append({
            'cfg':           cfg,
            'svc_up':        svc_up,
            'resp_ms':       resp_ms,
            'metrics':       metrics,
            'error_count':   error_count,
            'recent_errors': recent_errors,
            'health_score':  score,
            'health_color':  '#22c55e' if score >= 80 else '#f59e0b' if score >= 50 else '#ef4444',
        })

    return sys_m, app_data


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if (email    == os.environ.get('ADMIN_EMAIL', '').lower() and
                password == os.environ.get('ADMIN_PASSWORD', '')):
            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    tenants = Tenant.query.order_by(Tenant.provisioned_at.desc()).all()
    return render_template('dashboard.html', tenants=tenants, tier_labels=TIER_LABELS)


# ── Provision ─────────────────────────────────────────────────────────────────

@app.route('/provision', methods=['GET', 'POST'])
@login_required
def provision():
    if request.method == 'POST':
        email         = request.form.get('email', '').strip().lower()
        business_name = request.form.get('business_name', '').strip()
        tier          = request.form.get('tier', '').strip()
        notes         = request.form.get('notes', '').strip()

        if not all([email, business_name, tier]):
            flash('Email, business name, and tier are all required.', 'error')
            return render_template('provision.html', tier_labels=TIER_LABELS)

        from provisioner import provision_tenant, slugify, ProvisionError

        slug     = slugify(business_name)
        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            flash(
                f'The slug "{slug}" is already taken by {existing.business_name}. '
                f'Try adjusting the business name.',
                'error'
            )
            return render_template('provision.html', tier_labels=TIER_LABELS,
                                   prefill={'email': email, 'business_name': business_name,
                                            'tier': tier, 'notes': notes})

        try:
            port = provision_tenant(email, business_name, tier, slug)
        except ProvisionError as e:
            flash(f'Provisioning failed: {e}', 'error')
            return render_template('provision.html', tier_labels=TIER_LABELS)

        tenant = Tenant(
            slug          = slug,
            business_name = business_name,
            email         = email,
            tier          = tier,
            port          = port,
            notes         = notes,
        )
        db.session.add(tenant)
        db.session.commit()

        flash(
            f'✅ "{business_name}" provisioned at {slug}.sniffhq.app (port {port}). '
            f'Welcome email sent to {email}.',
            'success'
        )
        return redirect(url_for('dashboard'))

    return render_template('provision.html', tier_labels=TIER_LABELS)


# ── Tenant actions ─────────────────────────────────────────────────────────────

@app.route('/tenants/<int:tenant_id>/suspend', methods=['POST'])
@login_required
def suspend_tenant(tenant_id):
    t = Tenant.query.get_or_404(tenant_id)
    t.status = 'suspended'
    db.session.commit()
    flash(f'{t.business_name} suspended.', 'warning')
    return redirect(url_for('dashboard'))


@app.route('/tenants/<int:tenant_id>/activate', methods=['POST'])
@login_required
def activate_tenant(tenant_id):
    t = Tenant.query.get_or_404(tenant_id)
    t.status = 'active'
    db.session.commit()
    flash(f'{t.business_name} reactivated.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/tenants/<int:tenant_id>/resend-welcome', methods=['POST'])
@login_required
def resend_welcome(tenant_id):
    t = Tenant.query.get_or_404(tenant_id)
    try:
        from provisioner import send_welcome_email
        send_welcome_email(t.email, t.business_name, t.slug)
        flash(f'Welcome email resent to {t.email}.', 'success')
    except Exception as e:
        flash(f'Failed to resend: {e}', 'error')
    return redirect(url_for('dashboard'))


@app.route('/tenants/<int:tenant_id>/activate-ssl', methods=['POST'])
@login_required
def activate_ssl(tenant_id):
    t = Tenant.query.get_or_404(tenant_id)
    try:
        from provisioner import provision_ssl, ProvisionError
        provision_ssl(t.slug)
        flash(f'SSL certificate activated for {t.slug}.sniffhq.app.', 'success')
    except Exception as e:
        flash(f'SSL activation failed: {e}', 'error')
    return redirect(url_for('dashboard'))


# ── Monitoring routes ──────────────────────────────────────────────────────────

ALERT_METRICS = [
    ('cpu',           'CPU Usage',     85,  '%'),
    ('memory',        'Memory Usage',  85,  '%'),
    ('disk',          'Disk Usage',    90,  '%'),
    ('error_spike',   'Error Spike',   10,  'errors/5min'),
    ('service_down',  'Service Down',  1,   'boolean'),
    ('sms_failures',  'SMS Failures',  5,   'count'),
    ('failed_logins', 'Failed Logins', 20,  'count/day'),
]


@app.route('/monitoring')
@login_required
def monitoring():
    sys_m, app_data = _collect_all()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template('monitoring.html',
                           sys_metrics=sys_m, app_data=app_data, now=now)


@app.route('/monitoring/<slug>')
@login_required
def monitoring_detail(slug):
    from metrics.infrastructure import get_service_status, ping_app
    from metrics.application    import get_all_metrics
    from metrics.logs           import get_error_count, get_recent_error_lines

    tenant = Tenant.query.filter_by(slug=slug).first_or_404()
    tenants_dir = os.environ.get('TENANTS_DIR', r'C:\SniffHQ\tenants')
    cfg = {
        'id':           tenant.slug,
        'name':         tenant.business_name,
        'tier':         tenant.tier,
        'db_path':      os.path.join(tenants_dir, tenant.slug, 'instance', 'sniffhq.db'),
        'log_path':     os.path.join(tenants_dir, tenant.slug, 'logs', 'app.log'),
        'nssm_service': f'SniffHQ_{tenant.slug}',
        'base_url':     f'http://localhost:{tenant.port}',
        'port':         tenant.port,
    }
    svc_up        = get_service_status(cfg['nssm_service'])
    resp_ms       = ping_app(cfg['base_url']) if svc_up else None
    metrics       = get_all_metrics(cfg['db_path'])
    error_count   = get_error_count(cfg['log_path'])
    recent_errors = get_recent_error_lines(cfg['log_path'], limit=25)

    score = 100
    if not svc_up:                       score -= 50
    if resp_ms and resp_ms > 2000:       score -= 20
    if error_count > 10:                 score -= 15
    if metrics['sms_failures'] > 5:      score -= 10
    if metrics['failed_logins'] > 20:    score -= 5
    score = max(0, score)
    health_color = '#22c55e' if score >= 80 else '#f59e0b' if score >= 50 else '#ef4444'

    snapshots = (Snapshot.query
                 .filter_by(app_id=tenant.slug)
                 .order_by(Snapshot.ts.desc())
                 .limit(12).all())

    return render_template('monitoring_detail.html',
                           tenant=tenant, cfg=cfg,
                           svc_up=svc_up, resp_ms=resp_ms,
                           metrics=metrics, error_count=error_count,
                           recent_errors=recent_errors,
                           health_score=score, health_color=health_color,
                           snapshots=snapshots,
                           now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/monitoring/alerts', methods=['GET', 'POST'])
@login_required
def monitoring_alerts():
    if request.method == 'POST':
        for key, label, default_thresh, unit in ALERT_METRICS:
            ac = AlertConfig.query.filter_by(metric=key).first()
            if not ac:
                ac = AlertConfig(metric=key)
                db.session.add(ac)
            ac.enabled      = request.form.get(f'enabled_{key}') == '1'
            thresh          = request.form.get(f'threshold_{key}', '').strip()
            ac.threshold    = float(thresh) if thresh else default_thresh
            ac.notify_email = request.form.get(f'email_{key}', '').strip() or None
            ac.updated_at   = datetime.utcnow()
        db.session.commit()
        flash('Alert rules saved.', 'success')
        return redirect(url_for('monitoring_alerts'))

    # Seed defaults
    configs = {c.metric: c for c in AlertConfig.query.all()}
    for key, label, default_thresh, unit in ALERT_METRICS:
        if key not in configs:
            ac = AlertConfig(metric=key, enabled=False, threshold=default_thresh)
            db.session.add(ac)
    db.session.commit()
    configs = {c.metric: c for c in AlertConfig.query.all()}
    return render_template('monitoring_alerts.html',
                           alert_metrics=ALERT_METRICS, configs=configs)


@app.route('/monitoring/api/metrics')
@login_required
def monitoring_api():
    from metrics.infrastructure import get_system_metrics
    sys_m, app_data = _collect_all()
    return jsonify({
        'sys': sys_m,
        'ts':  datetime.now().isoformat(),
        'apps': [{
            'id':        a['cfg']['id'],
            'name':      a['cfg']['name'],
            'svc_up':    a['svc_up'],
            'resp_ms':   a['resp_ms'],
            'health':    a['health_score'],
            'customers': a['metrics']['customers'],
            'sms_today': a['metrics']['sms_today'],
            'errors':    a['error_count'],
        } for a in app_data],
    })


if __name__ == '__main__':
    app.run(debug=False, port=9000)
