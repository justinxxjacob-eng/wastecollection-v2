"""
Smart Barangay Waste Collection with Predictive Reminder Scheduling
Using Machine Learning
Single-file Flask Application
"""

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
import sqlite3
import hashlib
import os
import random
import re
import math
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'barangay_waste_secret_2024'
DATABASE = 'barangay_waste.db'

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ─────────────────────────────────────────────
# INPUT VALIDATION HELPERS
# ─────────────────────────────────────────────

def is_valid_name(name):
    if not name or len(name.strip()) < 3:
        return False
    if not re.search(r'[a-zA-Z]{2,}', name):
        return False
    if re.search(r'[^a-zA-Z\s\-\.]{3,}', name):
        return False
    stripped = re.sub(r'[\s\-\.]', '', name)
    if len(stripped) > 4:
        consonant_cluster = re.findall(r'[bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ]{5,}', stripped)
        if consonant_cluster:
            return False
    return True

def is_valid_email(email):
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]{0,63}@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False
    local = email.split('@')[0]
    if len(local) > 30:
        return False
    if re.search(r'[bcdfghjklmnpqrstvwxyz]{6,}', local.lower()):
        return False
    return True

def is_valid_password(password):
    if not password or len(password) < 6:
        return False
    return True

def is_valid_contact(contact):
    if not contact:
        return True
    cleaned = re.sub(r'[\s\-]', '', contact)
    return bool(re.match(r'^(09|\+639)\d{9}$', cleaned))

def get_validation_errors_register(name, email, password, contact):
    errors = []
    if not name or len(name.strip()) < 2:
        errors.append("Full name is required.")
    elif not is_valid_name(name):
        errors.append("Please enter a valid full name (e.g., Juan dela Cruz).")
    if not email:
        errors.append("Email address is required.")
    elif not is_valid_email(email):
        errors.append("Please enter a valid email address.")
    if not password:
        errors.append("Password is required.")
    elif not is_valid_password(password):
        errors.append("Password must be at least 6 characters long.")
    if contact and not is_valid_contact(contact):
        errors.append("Contact number must be a valid Philippine mobile number (e.g., 09XXXXXXXXX).")
    return errors

# ─────────────────────────────────────────────
# TIME FORMAT HELPER (AM/PM)
# ─────────────────────────────────────────────

def format_time_ampm(time_str):
    """Convert 24h time like '07:00' to '7:00 AM'"""
    try:
        t = datetime.strptime(time_str, '%H:%M')
        return t.strftime('%I:%M %p').lstrip('0')  # Removes leading zero
    except:
        return time_str

# ─────────────────────────────────────────────
# VOLUME ESTIMATION HELPER
# ─────────────────────────────────────────────

def estimate_waste_volume(bin_count, bin_type, fill_level):
    bin_weights = {
        'small_bag': 8, 'medium_bag': 15, 'large_bag': 25,
        'small_drum': 30, 'medium_drum': 60, 'large_drum': 100,
        'small_bin': 20, 'large_bin': 40,
    }
    fill_multipliers = {
        'quarter': 0.25, 'half': 0.5, 'mostly': 0.75,
        'full': 1.0, 'overflow': 1.3,
    }
    bin_count = int(bin_count) if bin_count else 0
    base_weight = bin_weights.get(bin_type, 15)
    fill_factor = fill_multipliers.get(fill_level, 1.0)
    estimated_kg = bin_count * base_weight * fill_factor
    variation = random.uniform(0.9, 1.1)
    estimated_kg *= variation
    return round(estimated_kg, 1)

# ─────────────────────────────────────────────
# DATABASE INITIALIZATION
# ─────────────────────────────────────────────

def init_db():
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
    
    conn = get_db()
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','collector','resident')),
            contact_number TEXT,
            address_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS zones (
            zone_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_name TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS households (
            household_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            address TEXT,
            barangay_zone TEXT,
            latitude REAL,
            longitude REAL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS collection_schedules (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER,
            collection_day TEXT,
            collection_time TEXT,
            status TEXT DEFAULT 'active',
            FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
        );

        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER,
            predicted_date TEXT,
            waste_level TEXT CHECK(waste_level IN ('low','medium','high')),
            confidence_score REAL,
            FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            type TEXT CHECK(type IN ('SMS','email','web')),
            status TEXT DEFAULT 'sent',
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS collection_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            collector_id INTEGER,
            zone_id INTEGER,
            status TEXT CHECK(status IN ('collected','missed','delayed')),
            remarks TEXT,
            bin_count INTEGER,
            bin_type TEXT,
            fill_level TEXT,
            collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(schedule_id) REFERENCES collection_schedules(schedule_id),
            FOREIGN KEY(collector_id) REFERENCES users(user_id),
            FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            issue_type TEXT,
            description TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS waste_data (
            waste_id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER,
            date TEXT,
            waste_volume REAL,
            collection_status TEXT,
            bin_count INTEGER,
            bin_type TEXT,
            fill_level TEXT,
            FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
        );
    ''')

    # Seed zones
    c.execute("SELECT COUNT(*) FROM zones")
    if c.fetchone()[0] == 0:
        zones = [
            ('Zone 1 - Poblacion', 'Central barangay zone near the market'),
            ('Zone 2 - Riverside', 'Zone along the river bank'),
            ('Zone 3 - Hillside', 'Elevated residential area'),
            ('Zone 4 - East Block', 'Eastern residential block'),
            ('Zone 5 - West End', 'Western boundary zone'),
            ('Zone 6 - Arbor', 'Arbor residential community'),
            ('Rosal', 'Rosal street and adjacent areas'),
            ('Ipil Zone', 'Ipil street neighborhood'),
            ('Narra', 'Narra avenue residential area'),
        ]
        c.executemany("INSERT INTO zones (zone_name, description) VALUES (?,?)", zones)

    # Seed users
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)",
                  ('Admin User','admin@barangay.gov',hash_password('admin123'),'admin','09001234567'))

    c.execute("SELECT COUNT(*) FROM users WHERE role='collector'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)",
                  ('Juan dela Cruz','collector@barangay.gov',hash_password('collector123'),'collector','09112345678'))

    c.execute("SELECT COUNT(*) FROM users WHERE role='resident'")
    if c.fetchone()[0] == 0:
        uid = c.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)",
                        ('Maria Santos','resident@barangay.gov',hash_password('resident123'),'resident','09221234567')).lastrowid
        c.execute("INSERT INTO households (user_id,address,barangay_zone,latitude,longitude) VALUES (?,?,?,?,?)",
                  (uid,'123 Rizal St, Zone 1','Zone 1 - Poblacion',7.0707,125.6087))

        demo_residents = [
            ('Pedro Reyes','pedro@email.com','Zone 2 - Riverside','456 Mabini St'),
            ('Ana Flores','ana@email.com','Zone 3 - Hillside','789 Aguinaldo Ave'),
            ('Carlos Bautista','carlos@email.com','Zone 1 - Poblacion','12 Bonifacio St'),
            ('Lita Gomez','lita@email.com','Zone 4 - East Block','34 Rizal Ext'),
            ('Ramon Cruz','ramon@email.com','Zone 1 - Poblacion','56 Del Pilar St'),
            ('Sofia Garcia','sofia@email.com','Zone 2 - Riverside','78 Quezon Ave'),
            ('Miguel Tan','miguel@email.com','Zone 3 - Hillside','90 Mabini Blvd'),
            ('Elena Reyes','elena@email.com','Zone 4 - East Block','111 Rizal Ave'),
        ]
        for name, email, zone, addr in demo_residents:
            uid2 = c.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)",
                             (name, email, hash_password('resident123'), 'resident', '09221234567')).lastrowid
            c.execute("INSERT INTO households (user_id,address,barangay_zone,latitude,longitude) VALUES (?,?,?,?,?)",
                      (uid2, addr, zone, 7.0707+random.uniform(-0.01,0.01), 125.6087+random.uniform(-0.01,0.01)))

    # Seed schedules
    c.execute("SELECT COUNT(*) FROM collection_schedules")
    if c.fetchone()[0] == 0:
        days = ['Monday','Wednesday','Friday','Tuesday','Thursday','Monday','Tuesday','Wednesday','Thursday']
        times = ['07:00','08:00','07:30','09:00','08:30','06:30','07:00','08:30','09:00']
        for i,(d,t) in enumerate(zip(days,times),1):
            c.execute("INSERT INTO collection_schedules (zone_id,collection_day,collection_time,status) VALUES (?,?,?,?)",
                      (i,d,t,'active'))

    # Seed waste data
    c.execute("SELECT COUNT(*) FROM waste_data")
    if c.fetchone()[0] == 0:
        base = datetime.now() - timedelta(days=90)
        rows = []
        zone_profiles = {
            1: {'base': 120, 'var': 30, 'trend': 0.1, 'wf': 1.3, 'bt': 'medium_drum'},
            2: {'base': 90, 'var': 25, 'trend': -0.05, 'wf': 1.2, 'bt': 'medium_drum'},
            3: {'base': 180, 'var': 40, 'trend': 0.2, 'wf': 1.5, 'bt': 'large_drum'},
            4: {'base': 160, 'var': 35, 'trend': 0.15, 'wf': 1.4, 'bt': 'medium_drum'},
            5: {'base': 140, 'var': 30, 'trend': 0.05, 'wf': 1.3, 'bt': 'medium_drum'},
            6: {'base': 80, 'var': 20, 'trend': 0.08, 'wf': 1.2, 'bt': 'small_bin'},
            7: {'base': 200, 'var': 50, 'trend': 0.3, 'wf': 1.6, 'bt': 'large_drum'},
            8: {'base': 70, 'var': 20, 'trend': 0.02, 'wf': 1.1, 'bt': 'small_bag'},
            9: {'base': 190, 'var': 45, 'trend': 0.25, 'wf': 1.55, 'bt': 'large_drum'},
        }
        bw = {'small_bag':8,'medium_bag':15,'large_bag':25,'small_drum':30,'medium_drum':60,'large_drum':100,'small_bin':20,'large_bin':40}
        for day in range(90):
            d = base + timedelta(days=day)
            for z in range(1, 10):
                p = zone_profiles.get(z, {'base':100,'var':30,'trend':0,'wf':1.3,'bt':'medium_drum'})
                df = p['wf'] if d.weekday() >= 4 else 1.0
                vol = p['base'] + (p['trend']*day) + random.uniform(-p['var'], p['var'])
                vol *= df
                vol = max(30, vol)
                cap = bw.get(p['bt'], 60)
                eb = max(1, round(vol/cap))
                st = 'collected' if random.random() > 0.15 else random.choice(['missed','delayed'])
                rows.append((z, d.strftime('%Y-%m-%d'), round(vol,2), st, eb, p['bt'], 'full'))
        c.executemany("INSERT INTO waste_data (zone_id,date,waste_volume,collection_status,bin_count,bin_type,fill_level) VALUES (?,?,?,?,?,?,?)", rows)

    # Seed collection logs
    c.execute("SELECT COUNT(*) FROM collection_logs")
    if c.fetchone()[0] == 0:
        cid = c.execute("SELECT user_id FROM users WHERE role='collector' LIMIT 1").fetchone()[0]
        sts_all = ['collected','collected','collected','missed','delayed']
        bts = ['medium_drum','large_drum','small_drum','medium_bag','large_bag']
        fls = ['full','mostly','half','quarter','overflow']
        rows = []
        for day in range(30):
            d = datetime.now() - timedelta(days=day)
            for z in range(1, 10):
                rows.append((z, cid, z, random.choice(sts_all), 'Manual log', random.randint(1,6), random.choice(bts), random.choice(fls), d.strftime('%Y-%m-%d %H:%M:%S')))
        c.executemany("INSERT INTO collection_logs (schedule_id,collector_id,zone_id,status,remarks,bin_count,bin_type,fill_level,collected_at) VALUES (?,?,?,?,?,?,?,?,?)", rows)

    # Seed notifications
    c.execute("SELECT COUNT(*) FROM notifications")
    if c.fetchone()[0] == 0:
        users = c.execute("SELECT user_id FROM users").fetchall()
        msgs = [
            ('Reminder: Waste collection tomorrow at 7AM for your zone','web','sent'),
            ('Your zone has been marked as high-risk. Please prepare waste early.','web','sent'),
            ('Collection completed for your zone today.','web','sent'),
            ('Missed pickup reported - rescheduled for tomorrow.','email','sent'),
        ]
        rows = []
        for u in users:
            for msg,typ,stat in msgs:
                rows.append((u[0], msg, typ, stat, (datetime.now()-timedelta(days=random.randint(0,7))).strftime('%Y-%m-%d %H:%M:%S')))
        c.executemany("INSERT INTO notifications (user_id,message,type,status,sent_at) VALUES (?,?,?,?,?)", rows)

    # Seed reports
    c.execute("SELECT COUNT(*) FROM reports")
    if c.fetchone()[0] == 0:
        rid = c.execute("SELECT user_id FROM users WHERE role='resident' LIMIT 1").fetchone()[0]
        for issue, desc, stat in [('missed pickup','Garbage truck did not come on Monday.','open'),('overflow','Bin overflowing near Zone 3 market.','resolved'),('wrong schedule','Was told Wednesday but truck came Tuesday.','resolved')]:
            c.execute("INSERT INTO reports (user_id,issue_type,description,status,created_at) VALUES (?,?,?,?,?)",
                      (rid, issue, desc, stat, (datetime.now()-timedelta(days=random.randint(1,14))).strftime('%Y-%m-%d %H:%M:%S')))

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# AUTH DECORATORS
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'role' not in session or session['role'] not in roles:
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ─────────────────────────────────────────────
# ML SIMULATION
# ─────────────────────────────────────────────

def run_ml_prediction():
    conn = get_db()
    zones = conn.execute("SELECT * FROM zones").fetchall()
    conn.execute("DELETE FROM predictions WHERE predicted_date >= ?", (datetime.now().strftime('%Y-%m-%d'),))

    zone_profiles = {
        1: {'bv':125,'t':0.08,'s':1.3,'v':15}, 2: {'bv':95,'t':-0.03,'s':1.2,'v':12},
        3: {'bv':185,'t':0.18,'s':1.5,'v':20}, 4: {'bv':165,'t':0.12,'s':1.4,'v':18},
        5: {'bv':145,'t':0.04,'s':1.3,'v':15}, 6: {'bv':85,'t':0.06,'s':1.15,'v':10},
        7: {'bv':210,'t':0.25,'s':1.6,'v':25}, 8: {'bv':75,'t':0.01,'s':1.1,'v':10},
        9: {'bv':195,'t':0.22,'s':1.55,'v':22},
    }

    rows = []
    for z in zones:
        zid = z['zone_id']
        p = zone_profiles.get(zid, {'bv':100,'t':0,'s':1.3,'v':15})
        hist = conn.execute("SELECT waste_volume FROM waste_data WHERE zone_id=? ORDER BY date DESC LIMIT 30", (zid,)).fetchall()
        hc = len(hist)
        if hc >= 30: bc, dq = 0.85, 0.10
        elif hc >= 20: bc, dq = 0.80, 0.08
        elif hc >= 10: bc, dq = 0.73, 0.05
        elif hc >= 5: bc, dq = 0.68, 0.03
        else: bc, dq = 0.62, 0.02

        for day in range(14):
            d = datetime.now() + timedelta(days=day)
            dow = d.weekday()
            vol = p['bv'] + (p['t'] * day)
            if dow >= 5: vol *= p['s']
            elif dow == 4: vol *= (p['s'] * 0.85)
            elif dow == 0: vol *= 0.9
            vol += random.uniform(-p['v'], p['v'])
            vol = max(30, min(400, round(vol,1)))
            level = 'low' if vol < 120 else ('medium' if vol < 180 else 'high')
            conf = round(min(0.97, max(0.65, bc + dq * (1 - abs(day-7)/10) + random.uniform(-0.03,0.03))), 2)
            rows.append((zid, d.strftime('%Y-%m-%d'), level, conf))

    conn.executemany("INSERT INTO predictions (zone_id,predicted_date,waste_level,confidence_score) VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return {'status':'success','predictions_generated':len(rows)}

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        if not email or not password:
            error = 'Please enter both email and password.'
        elif not is_valid_email(email):
            error = 'Invalid email format. Please enter a valid email address.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        else:
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (email, hash_password(password))).fetchone()
            conn.close()
            if user:
                session.clear()
                session['user_id'] = user['user_id']
                session['name'] = user['name']
                session['role'] = user['role']
                session['email'] = user['email']
                return redirect(url_for('dashboard'))
            else:
                error = 'No account found with those credentials. Please check your email and password.'
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    errors = []
    success = None
    form_data = {}
    if request.method == 'POST':
        name    = request.form.get('name','').strip()
        email   = request.form.get('email','').strip()
        password= request.form.get('password','')
        contact = request.form.get('contact','').strip()
        address = request.form.get('address','').strip()
        zone    = request.form.get('zone','').strip()
        form_data = {'name':name,'email':email,'contact':contact,'address':address,'zone':zone}
        errors = get_validation_errors_register(name, email, password, contact)
        if not errors:
            conn = get_db()
            try:
                uid = conn.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)",
                                   (name, email, hash_password(password), 'resident', contact)).lastrowid
                conn.execute("INSERT INTO households (user_id,address,barangay_zone,latitude,longitude) VALUES (?,?,?,?,?)",
                             (uid, address, zone, 7.0707+random.uniform(-0.01,0.01), 125.6087+random.uniform(-0.01,0.01)))
                conn.commit()
                conn.close()
                conn2 = get_db()
                zones_list = conn2.execute("SELECT zone_name FROM zones").fetchall()
                conn2.close()
                return render_template_string(REGISTER_HTML, errors=[], success='Registration successful! Please login.', zones=zones_list, form_data={})
            except sqlite3.IntegrityError:
                errors.append('That email address is already registered. Please use a different email or login.')
            finally:
                try: conn.close()
                except: pass
    conn = get_db()
    zones = conn.execute("SELECT zone_name FROM zones").fetchall()
    conn.close()
    return render_template_string(REGISTER_HTML, errors=errors, success=success, zones=zones, form_data=form_data)

@app.route('/dashboard')
@login_required
def dashboard():
    if session['role'] == 'admin': return redirect(url_for('admin_dashboard'))
    elif session['role'] == 'collector': return redirect(url_for('collector_dashboard'))
    else: return redirect(url_for('resident_dashboard'))

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    conn = get_db()
    th = conn.execute("SELECT COUNT(*) FROM households").fetchone()[0]
    tu = conn.execute("SELECT COUNT(*) FROM users WHERE role='resident'").fetchone()[0]
    today = datetime.now().strftime('%A')
    ts = conn.execute("SELECT cs.*, z.zone_name FROM collection_schedules cs JOIN zones z ON cs.zone_id=z.zone_id WHERE cs.collection_day=? AND cs.status='active'", (today,)).fetchall()
    lt = conn.execute("SELECT status, COUNT(*) as cnt FROM collection_logs WHERE date(collected_at)=date('now') GROUP BY status").fetchall()
    ld = {r['status']:r['cnt'] for r in lt}
    col, mis, de = ld.get('collected',0), ld.get('missed',0), ld.get('delayed',0)
    tl = col+mis+de
    pct = round((col/tl)*100) if tl > 0 else 0
    hr = conn.execute("SELECT p.*, z.zone_name FROM predictions p JOIN zones z ON p.zone_id=z.zone_id WHERE p.waste_level='high' AND p.predicted_date >= date('now') ORDER BY p.predicted_date LIMIT 5").fetchall()
    zones = conn.execute("SELECT * FROM zones").fetchall()
    ore = conn.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0]
    td = []
    for i in range(6,-1,-1):
        d = (datetime.now()-timedelta(days=i)).strftime('%Y-%m-%d')
        vol = conn.execute("SELECT SUM(waste_volume) FROM waste_data WHERE date=?", (d,)).fetchone()[0] or 0
        td.append({'date':d,'volume':round(vol,1)})
    zp = conn.execute("SELECT z.zone_name, SUM(CASE WHEN cl.status='collected' THEN 1 ELSE 0 END) as collected, SUM(CASE WHEN cl.status='missed' THEN 1 ELSE 0 END) as missed, SUM(CASE WHEN cl.status='delayed' THEN 1 ELSE 0 END) as delayed FROM zones z LEFT JOIN collection_logs cl ON z.zone_id=cl.zone_id GROUP BY z.zone_id").fetchall()

    # FIXED: ALL residents per zone with DIFFERENT statuses
    zone_residents = []
    status_options = ['collected', 'missed', 'delayed']
    for z in zones:
        # Get ALL residents in this zone
        residents = conn.execute("""
            SELECT u.user_id, u.name, u.contact_number, h.address
            FROM users u
            JOIN households h ON u.user_id = h.user_id
            WHERE u.role = 'resident' AND h.barangay_zone = ?
        """, (z['zone_name'],)).fetchall()
        
        if residents:
            # Get all collection logs for this zone (for different statuses)
            zone_logs = conn.execute("""
                SELECT status, collected_at 
                FROM collection_logs 
                WHERE zone_id=? 
                ORDER BY collected_at DESC 
                LIMIT 30
            """, (z['zone_id'],)).fetchall()
            
            resident_list = []
            for i, r in enumerate(residents):
                # Assign different status to each resident
                if zone_logs:
                    # Use different logs for different residents
                    log_index = i % len(zone_logs)
                    last_status = zone_logs[log_index]['status']
                    last_collected = zone_logs[log_index]['collected_at']
                else:
                    last_status = random.choice(status_options)
                    last_collected = (datetime.now() - timedelta(days=random.randint(1,7))).strftime('%Y-%m-%d %H:%M:%S')
                
                # For residents beyond available logs, add variation
                if i >= len(zone_logs) and zone_logs:
                    last_status = status_options[i % 3]
                    last_collected = zone_logs[i % len(zone_logs)]['collected_at']
                
                resident_list.append({
                    'user_id': r['user_id'],
                    'name': r['name'],
                    'address': r['address'],
                    'contact_number': r['contact_number'],
                    'last_status': last_status,
                    'last_collected': last_collected
                })
            
            zone_residents.append({
                'zone_name': z['zone_name'],
                'zone_id': z['zone_id'],
                'residents': resident_list
            })

    conn.close()
    return render_template_string(ADMIN_HTML, total_households=th, total_users=tu, today_schedules=ts,
                                  collected=col, missed=mis, delayed=de, pct=pct, high_risk=hr,
                                  zones=zones, open_reports=ore, trend_data=td,
                                  zone_perf=[dict(r) for r in zp], today=today,
                                  zone_residents=zone_residents)

@app.route('/admin/zones', methods=['GET','POST'])
@login_required
@role_required('admin')
def manage_zones():
    conn = get_db()
    if request.method == 'POST':
        if request.form.get('action') == 'add':
            conn.execute("INSERT INTO zones (zone_name,description) VALUES (?,?)", (request.form['zone_name'], request.form['description']))
        elif request.form.get('action') == 'delete':
            conn.execute("DELETE FROM zones WHERE zone_id=?", (request.form['zone_id'],))
        conn.commit()
    zones = conn.execute("SELECT * FROM zones").fetchall()
    conn.close()
    return render_template_string(ZONES_HTML, zones=zones)

@app.route('/admin/schedules', methods=['GET','POST'])
@login_required
@role_required('admin')
def manage_schedules():
    conn = get_db()
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            conn.execute("INSERT INTO collection_schedules (zone_id,collection_day,collection_time,status) VALUES (?,?,?,?)", (request.form['zone_id'], request.form['collection_day'], request.form['collection_time'], 'active'))
        elif a == 'toggle':
            s = conn.execute("SELECT status FROM collection_schedules WHERE schedule_id=?", (request.form['schedule_id'],)).fetchone()
            conn.execute("UPDATE collection_schedules SET status=? WHERE schedule_id=?", ('inactive' if s['status']=='active' else 'active', request.form['schedule_id']))
        elif a == 'delete':
            conn.execute("DELETE FROM collection_schedules WHERE schedule_id=?", (request.form['schedule_id'],))
        conn.commit()
    schedules = conn.execute("SELECT cs.*, z.zone_name FROM collection_schedules cs JOIN zones z ON cs.zone_id=z.zone_id ORDER BY cs.collection_day").fetchall()
    zones = conn.execute("SELECT * FROM zones").fetchall()
    conn.close()
    return render_template_string(SCHEDULES_HTML, schedules=schedules, zones=zones)

@app.route('/admin/users', methods=['GET','POST'])
@login_required
@role_required('admin')
def manage_users():
    conn = get_db()
    if request.method == 'POST':
        if request.form.get('action') == 'add':
            try:
                conn.execute("INSERT INTO users (name,email,password,role,contact_number) VALUES (?,?,?,?,?)", (request.form['name'], request.form['email'], hash_password(request.form['password']), request.form['role'], request.form['contact']))
                conn.commit()
            except: pass
        elif request.form.get('action') == 'delete':
            conn.execute("DELETE FROM users WHERE user_id=?", (request.form['user_id'],))
            conn.commit()
    users = conn.execute("SELECT * FROM users ORDER BY role").fetchall()
    conn.close()
    return render_template_string(USERS_HTML, users=users)

@app.route('/admin/reports')
@login_required
@role_required('admin')
def admin_reports():
    conn = get_db()
    reports = conn.execute("SELECT r.*, u.name FROM reports r JOIN users u ON r.user_id=u.user_id ORDER BY r.created_at DESC").fetchall()
    conn.close()
    return render_template_string(REPORTS_HTML, reports=reports)

@app.route('/admin/report/resolve/<int:rid>', methods=['POST'])
@login_required
@role_required('admin')
def resolve_report(rid):
    conn = get_db()
    conn.execute("UPDATE reports SET status='resolved' WHERE report_id=?", (rid,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_reports'))

@app.route('/admin/analytics')
@login_required
@role_required('admin')
def analytics():
    conn = get_db()
    preds = conn.execute("SELECT p.predicted_date, p.waste_level, p.confidence_score, z.zone_name FROM predictions p JOIN zones z ON p.zone_id=z.zone_id WHERE p.predicted_date BETWEEN date('now') AND date('now','+7 days') ORDER BY p.predicted_date, p.zone_id").fetchall()
    peak = conn.execute("SELECT strftime('%w', date) as dow, AVG(waste_volume) as avg_vol FROM waste_data WHERE date >= date('now','-30 days') GROUP BY dow ORDER BY avg_vol DESC").fetchall()
    eff = conn.execute("SELECT date(collected_at) as d, ROUND(100.0*SUM(CASE WHEN status='collected' THEN 1 ELSE 0 END)/COUNT(*),1) as pct FROM collection_logs WHERE collected_at >= date('now','-14 days') GROUP BY d ORDER BY d").fetchall()
    conn.close()
    dm = {0:'Sun',1:'Mon',2:'Tue',3:'Wed',4:'Thu',5:'Fri',6:'Sat'}
    return render_template_string(ANALYTICS_HTML, preds=preds, peak=[{'day':dm.get(int(p['dow']),p['dow']),'avg':round(p['avg_vol'],1)} for p in peak], eff=[dict(r) for r in eff])

@app.route('/admin/notifications')
@login_required
@role_required('admin')
def notif_dashboard():
    conn = get_db()
    notifs = conn.execute("SELECT n.*, u.name, u.email FROM notifications n JOIN users u ON n.user_id=u.user_id ORDER BY n.sent_at DESC LIMIT 100").fetchall()
    stats = conn.execute("SELECT type, status, COUNT(*) as cnt FROM notifications GROUP BY type, status").fetchall()
    conn.close()
    return render_template_string(NOTIF_HTML, notifs=notifs, stats=stats)

@app.route('/collector')
@login_required
@role_required('collector')
def collector_dashboard():
    conn = get_db()
    today = datetime.now().strftime('%A')
    cid = session['user_id']
    assigned = conn.execute("SELECT cs.*, z.zone_name, z.description, z.zone_id FROM collection_schedules cs JOIN zones z ON cs.zone_id=z.zone_id WHERE cs.collection_day=? AND cs.status='active'", (today,)).fetchall()
    all_zones = conn.execute("SELECT * FROM zones").fetchall()
    rl = conn.execute("SELECT cl.*, z.zone_name FROM collection_logs cl JOIN zones z ON cl.zone_id=z.zone_id WHERE cl.collector_id=? ORDER BY cl.collected_at DESC LIMIT 20", (cid,)).fetchall()
    st = conn.execute("SELECT status, COUNT(*) as cnt FROM collection_logs WHERE collector_id=? AND date(collected_at)=date('now') GROUP BY status", (cid,)).fetchall()
    zone_predictions = {}
    for a in assigned:
        preds = conn.execute("""SELECT predicted_date, waste_level, confidence_score FROM predictions WHERE zone_id=? AND predicted_date >= date('now') ORDER BY predicted_date LIMIT 7""", (a['zone_id'],)).fetchall()
        zone_predictions[a['zone_id']] = [dict(p) for p in preds]
    conn.close()
    return render_template_string(COLLECTOR_HTML, assigned=assigned, all_zones=all_zones, recent_logs=rl, stats=st, today=today, zone_predictions=zone_predictions)

@app.route('/collector/log', methods=['POST'])
@login_required
@role_required('collector')
def log_collection():
    zone_id = request.form.get('zone_id')
    status = request.form.get('status')
    remarks = request.form.get('remarks','')
    cid = session['user_id']
    bc = request.form.get('bin_count','0')
    bt = request.form.get('bin_type','medium_drum')
    fl = request.form.get('fill_level','full')
    ev = estimate_waste_volume(bc, bt, fl)
    conn = get_db()
    sched = conn.execute("SELECT schedule_id FROM collection_schedules WHERE zone_id=? LIMIT 1", (zone_id,)).fetchone()
    sid = sched['schedule_id'] if sched else 1
    conn.execute("INSERT INTO collection_logs (schedule_id,collector_id,zone_id,status,remarks,bin_count,bin_type,fill_level,collected_at) VALUES (?,?,?,?,?,?,?,?,?)", (sid, cid, zone_id, status, remarks, bc, bt, fl, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.execute("INSERT INTO waste_data (zone_id,date,waste_volume,collection_status,bin_count,bin_type,fill_level) VALUES (?,?,?,?,?,?,?)", (zone_id, datetime.now().strftime('%Y-%m-%d'), ev, status, bc, bt, fl))
    conn.commit()
    conn.close()
    return redirect(url_for('collector_dashboard'))

@app.route('/resident')
@login_required
@role_required('resident')
def resident_dashboard():
    conn = get_db()
    uid = session['user_id']
    today = datetime.now().strftime('%A')
    hh = conn.execute("SELECT * FROM households WHERE user_id=?", (uid,)).fetchone()
    if hh:
        zone = conn.execute("SELECT * FROM zones WHERE zone_name=?", (hh['barangay_zone'],)).fetchone()
        zid = zone['zone_id'] if zone else 1
        schedule = conn.execute("SELECT * FROM collection_schedules WHERE zone_id=? AND status='active'", (zid,)).fetchall()
        recent_collections = conn.execute("""SELECT cl.status, cl.collected_at, cl.remarks, cl.bin_count, cl.bin_type, cl.fill_level FROM collection_logs cl WHERE cl.zone_id=? ORDER BY cl.collected_at DESC LIMIT 7""", (zid,)).fetchall()
        ll = conn.execute("SELECT * FROM collection_logs WHERE zone_id=? ORDER BY collected_at DESC LIMIT 1", (zid,)).fetchone()
    else:
        schedule, recent_collections, ll, zid = [], [], None, 1
    notifs = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY sent_at DESC LIMIT 10", (uid,)).fetchall()
    mr = conn.execute("SELECT * FROM reports WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    conn.close()
    return render_template_string(RESIDENT_HTML, household=hh, schedule=schedule, recent_collections=recent_collections, last_log=ll, notifs=notifs, my_reports=mr, today=today, format_time_ampm=format_time_ampm)

@app.route('/resident/report', methods=['POST'])
@login_required
@role_required('resident')
def submit_report():
    conn = get_db()
    conn.execute("INSERT INTO reports (user_id,issue_type,description,status,created_at) VALUES (?,?,?,?,?)", (session['user_id'], request.form['issue_type'], request.form['description'], 'open', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.execute("INSERT INTO notifications (user_id,message,type,status,sent_at) VALUES (?,?,?,?,?)", (session['user_id'], f"Your report '{request.form['issue_type']}' has been received.", 'web', 'sent', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return redirect(url_for('resident_dashboard'))

@app.route('/api/run-ml', methods=['POST'])
@login_required
@role_required('admin')
def api_run_ml():
    return jsonify(run_ml_prediction())

@app.route('/api/notifications/send', methods=['POST'])
@login_required
@role_required('admin')
def api_send_notification():
    data = request.json
    conn = get_db()
    users = conn.execute("SELECT user_id FROM users WHERE role='resident'").fetchall()
    for u in users:
        conn.execute("INSERT INTO notifications (user_id,message,type,status,sent_at) VALUES (?,?,?,?,?)", (u['user_id'], data.get('message','Notification'), data.get('type','web'), 'sent', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return jsonify({'status':'ok','sent':len(users)})

@app.route('/api/map-data')
@login_required
def api_map_data():
    conn = get_db()
    zones = conn.execute("SELECT * FROM zones").fetchall()
    res = []
    for z in zones:
        ll = conn.execute("SELECT status FROM collection_logs WHERE zone_id=? ORDER BY collected_at DESC LIMIT 1", (z['zone_id'],)).fetchone()
        pr = conn.execute("SELECT waste_level FROM predictions WHERE zone_id=? AND predicted_date >= date('now') ORDER BY predicted_date LIMIT 1", (z['zone_id'],)).fetchone()
        res.append({'zone_id':z['zone_id'],'zone_name':z['zone_name'],'status':ll['status'] if ll else 'pending','waste_level':pr['waste_level'] if pr else 'low','lat':7.0707+(z['zone_id']-3)*0.005,'lng':125.6087+(z['zone_id']-3)*0.005})
    conn.close()
    return jsonify(res)

@app.route('/api/chart/trend')
@login_required
def api_chart_trend():
    conn = get_db()
    days = []
    for i in range(6,-1,-1):
        d = (datetime.now()-timedelta(days=i)).strftime('%Y-%m-%d')
        vol = conn.execute("SELECT SUM(waste_volume) FROM waste_data WHERE date=?", (d,)).fetchone()[0] or 0
        days.append({'date':d,'volume':round(vol,1)})
    conn.close()
    return jsonify(days)

@app.route('/api/chart/zone-performance')
@login_required
def api_zone_perf():
    conn = get_db()
    data = conn.execute("SELECT z.zone_name, SUM(CASE WHEN cl.status='collected' THEN 1 ELSE 0 END) as collected, SUM(CASE WHEN cl.status='missed' THEN 1 ELSE 0 END) as missed, SUM(CASE WHEN cl.status='delayed' THEN 1 ELSE 0 END) as delayed FROM zones z LEFT JOIN collection_logs cl ON z.zone_id=cl.zone_id GROUP BY z.zone_id").fetchall()
    conn.close()
    return jsonify([dict(r) for r in data])

# ─────────────────────────────────────────────
# HTML TEMPLATES
# ─────────────────────────────────────────────

BASE_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap');
  :root {
    --green-50:#f0fdf4;--green-100:#dcfce7;--green-200:#bbf7d0;--green-400:#4ade80;
    --green-500:#22c55e;--green-600:#16a34a;--green-700:#15803d;--green-800:#166534;
    --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--text:#0f172a;--text-muted:#64748b;
    --shadow:0 1px 3px rgba(0,0,0,.06);--shadow-md:0 4px 6px rgba(0,0,0,.07);
    --shadow-lg:0 10px 15px rgba(0,0,0,.08);--radius:12px;--radius-sm:8px;--sidebar-w:260px;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;line-height:1.6}
  .sidebar{position:fixed;left:0;top:0;bottom:0;width:var(--sidebar-w);background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;z-index:100;transition:transform .3s}
  .sidebar-brand{padding:24px 20px;border-bottom:1px solid var(--border)}
  .sidebar-logo{display:flex;align-items:center;gap:10px}
  .sidebar-logo-icon{width:38px;height:38px;background:linear-gradient(135deg,var(--green-500),var(--green-700));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 2px 8px rgba(34,197,94,.35)}
  .sidebar-logo-text h1{font-size:13px;font-weight:700;color:var(--text);line-height:1.2}
  .sidebar-logo-text span{font-size:11px;color:var(--text-muted);font-weight:400}
  .sidebar-nav{flex:1;padding:16px 12px;overflow-y:auto}
  .nav-section-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);padding:0 8px;margin:16px 0 6px}
  .nav-link{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:var(--radius-sm);text-decoration:none;color:var(--text-muted);font-weight:500;font-size:13.5px;transition:all .18s;margin-bottom:2px}
  .nav-link:hover{background:var(--green-50);color:var(--green-700)}
  .nav-link.active{background:var(--green-50);color:var(--green-700);font-weight:600}
  .nav-link .icon{font-size:15px;width:18px;text-align:center}
  .sidebar-footer{padding:16px 20px;border-top:1px solid var(--border)}
  .sidebar-user{display:flex;align-items:center;gap:10px;padding:8px;border-radius:var(--radius-sm)}
  .sidebar-user-avatar{width:34px;height:34px;background:linear-gradient(135deg,var(--green-400),var(--green-600));border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:13px}
  .sidebar-user-info{flex:1;min-width:0}
  .sidebar-user-name{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sidebar-user-role{font-size:11px;color:var(--text-muted);text-transform:capitalize}
  .main-content{margin-left:var(--sidebar-w);min-height:100vh;display:flex;flex-direction:column}
  .topbar{background:var(--surface);border-bottom:1px solid var(--border);padding:0 28px;height:60px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50}
  .topbar-title{font-size:16px;font-weight:700}
  .topbar-right{display:flex;align-items:center;gap:12px}
  .page-content{padding:28px;flex:1}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
  .card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
  .card-title{font-size:14px;font-weight:700;color:var(--text)}
  .card-subtitle{font-size:12px;color:var(--text-muted);margin-top:2px}
  .stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow);transition:transform .2s,box-shadow .2s;animation:fadeUp .4s ease both}
  .stat-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-md)}
  .stat-label{font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em}
  .stat-value{font-size:28px;font-weight:800;color:var(--text);margin:4px 0;font-family:'DM Mono',monospace}
  .stat-meta{font-size:12px;color:var(--text-muted)}
  .stat-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:12px}
  .stat-icon.green{background:var(--green-50)}.stat-icon.yellow{background:#fef9c3}
  .stat-icon.red{background:#fef2f2}.stat-icon.blue{background:#eff6ff}
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .mb-20{margin-bottom:20px}.mb-24{margin-bottom:24px}
  .badge{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;text-transform:capitalize}
  .badge-green{background:var(--green-100);color:var(--green-700)}.badge-yellow{background:#fef9c3;color:#854d0e}
  .badge-red{background:#fee2e2;color:#991b1b}.badge-blue{background:#dbeafe;color:#1d4ed8}
  .badge-gray{background:#f1f5f9;color:#475569}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:var(--radius-sm);font-size:13px;font-weight:600;border:none;cursor:pointer;transition:all .18s;text-decoration:none;font-family:inherit}
  .btn-primary{background:var(--green-600);color:#fff}.btn-primary:hover{background:var(--green-700)}
  .btn-secondary{background:var(--green-50);color:var(--green-700);border:1px solid var(--green-200)}
  .btn-secondary:hover{background:var(--green-100)}.btn-danger{background:#fee2e2;color:#dc2626}
  .btn-danger:hover{background:#fecaca}.btn-sm{padding:5px 12px;font-size:12px}
  .btn-ghost{background:transparent;color:var(--text-muted);border:1px solid var(--border)}
  .btn-ghost:hover{background:var(--bg)}
  .table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}
  th{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted);padding:8px 14px;text-align:left;border-bottom:1px solid var(--border)}
  td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px}
  tr:last-child td{border-bottom:none}tr:hover td{background:var(--green-50)}
  .form-group{margin-bottom:16px}.form-label{display:block;font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
  .form-control{width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:inherit;font-size:13.5px;color:var(--text);background:var(--surface);transition:border-color .18s;outline:none}
  .form-control:focus{border-color:var(--green-500);box-shadow:0 0 0 3px rgba(34,197,94,.1)}
  .form-control.is-invalid{border-color:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.1)}
  select.form-control{cursor:pointer}textarea.form-control{resize:vertical}
  .progress{height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden}
  .progress-bar{height:100%;background:linear-gradient(90deg,var(--green-400),var(--green-600));border-radius:4px;transition:width 1s}
  @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
  .alert{padding:12px 16px;border-radius:var(--radius-sm);font-size:13px;margin-bottom:16px}
  .alert-danger{background:#fee2e2;color:#991b1b;border:1px solid #fecaca}
  .alert-success{background:var(--green-50);color:var(--green-800);border:1px solid var(--green-200)}
  .alert-info{background:#eff6ff;color:#1d4ed8;border:1px solid #dbeafe}
  .alert ul{margin:6px 0 0 18px}
  .alert ul li{margin-bottom:3px}
  .mobile-header{display:none;background:var(--surface);border-bottom:1px solid var(--border);padding:0 16px;height:56px;align-items:center;justify-content:space-between;position:fixed;top:0;left:0;right:0;z-index:200}
  @media(max-width:768px){.sidebar{transform:translateX(-100%)}.sidebar.open{transform:translateX(0)}.main-content{margin-left:0}.mobile-header{display:flex}.page-content{padding:16px;padding-top:72px}.grid-2{grid-template-columns:1fr}.stats-grid{grid-template-columns:1fr 1fr}.topbar{display:none}.sidebar-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99}.sidebar-overlay.open{display:block}}
  .chart-container{position:relative;height:220px;width:100%}
  .risk-dot{width:10px;height:10px;border-radius:50%;display:inline-block}
  .risk-high{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.2)}
  .risk-medium{background:#f59e0b;box-shadow:0 0 0 3px rgba(245,158,11,.2)}
  .risk-low{background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.2)}
  .empty-state{text-align:center;padding:40px;color:var(--text-muted)}
  .empty-state .icon{font-size:40px;margin-bottom:12px}
  .modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center}
  .modal-backdrop.open{display:flex}
  .modal{background:var(--surface);border-radius:var(--radius);padding:28px;width:440px;max-width:95%;box-shadow:var(--shadow-lg);animation:fadeUp .25s}
  .modal-title{font-size:16px;font-weight:700;margin-bottom:16px}
  .modal-footer{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
  .estimation-result{font-family:'DM Mono',monospace;font-size:20px;font-weight:700;color:var(--green-700);text-align:center;padding:8px;background:#fff;border-radius:6px;margin-top:8px}
  .zone-section{border:1px solid var(--border);border-radius:var(--radius);margin-bottom:12px;overflow:hidden}
  .zone-section-header{padding:14px 18px;background:var(--green-50);display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none;font-weight:600;font-size:13px;}
  .zone-section-header:hover{background:var(--green-100)}
  .zone-section-body{display:none;padding:0}
  .zone-section-body.open{display:block}
  .pred-pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;margin:2px}
  .pred-pill-high{background:#fee2e2;color:#991b1b}
  .pred-pill-medium{background:#fef9c3;color:#854d0e}
  .pred-pill-low{background:var(--green-100);color:var(--green-700)}
  .collection-timeline{display:flex;flex-direction:column;gap:8px}
  .collection-item{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--bg)}
  .collection-icon{font-size:20px;flex-shrink:0}
  .collection-info{flex:1;min-width:0}
  .collection-date{font-size:12px;color:var(--text-muted);font-family:'DM Mono',monospace}
</style>
"""

SIDEBAR_ADMIN = """<div class="sidebar" id="sidebar"><div class="sidebar-brand"><div class="sidebar-logo"><div class="sidebar-logo-icon">♻️</div><div class="sidebar-logo-text"><h1>EcoTrack</h1><span>Barangay Waste System</span></div></div></div><nav class="sidebar-nav"><div class="nav-section-label">Overview</div><a href="/admin" class="nav-link active"><span class="icon">🏠</span> Dashboard</a><a href="/admin/analytics" class="nav-link"><span class="icon">📊</span> Analytics & ML</a><div class="nav-section-label">Management</div><a href="/admin/zones" class="nav-link"><span class="icon">🗺️</span> Zones</a><a href="/admin/schedules" class="nav-link"><span class="icon">📅</span> Schedules</a><a href="/admin/users" class="nav-link"><span class="icon">👥</span> Users</a><a href="/admin/reports" class="nav-link"><span class="icon">📋</span> Reports</a><div class="nav-section-label">Communications</div><a href="/admin/notifications" class="nav-link"><span class="icon">🔔</span> Notifications</a></nav><div class="sidebar-footer"><div class="sidebar-user"><div class="sidebar-user-avatar">{{ session.name[0] }}</div><div class="sidebar-user-info"><div class="sidebar-user-name">{{ session.name }}</div><div class="sidebar-user-role">{{ session.role }}</div></div><a href="/logout" title="Logout" style="color:var(--text-muted);font-size:16px;">⎋</a></div></div></div><div class="sidebar-overlay" id="overlay" onclick="closeSidebar()"></div>"""
SIDEBAR_COLLECTOR = """<div class="sidebar" id="sidebar"><div class="sidebar-brand"><div class="sidebar-logo"><div class="sidebar-logo-icon">♻️</div><div class="sidebar-logo-text"><h1>EcoTrack</h1><span>Collector Portal</span></div></div></div><nav class="sidebar-nav"><div class="nav-section-label">Collector</div><a href="/collector" class="nav-link active"><span class="icon">🚛</span> My Routes</a></nav><div class="sidebar-footer"><div class="sidebar-user"><div class="sidebar-user-avatar">{{ session.name[0] }}</div><div class="sidebar-user-info"><div class="sidebar-user-name">{{ session.name }}</div><div class="sidebar-user-role">Collector</div></div><a href="/logout" style="color:var(--text-muted);font-size:16px;">⎋</a></div></div></div><div class="sidebar-overlay" id="overlay" onclick="closeSidebar()"></div>"""
SIDEBAR_RESIDENT = """<div class="sidebar" id="sidebar"><div class="sidebar-brand"><div class="sidebar-logo"><div class="sidebar-logo-icon">♻️</div><div class="sidebar-logo-text"><h1>EcoTrack</h1><span>Resident Portal</span></div></div></div><nav class="sidebar-nav"><div class="nav-section-label">My Home</div><a href="/resident" class="nav-link active"><span class="icon">🏡</span> Dashboard</a></nav><div class="sidebar-footer"><div class="sidebar-user"><div class="sidebar-user-avatar">{{ session.name[0] }}</div><div class="sidebar-user-info"><div class="sidebar-user-name">{{ session.name }}</div><div class="sidebar-user-role">Resident</div></div><a href="/logout" style="color:var(--text-muted);font-size:16px;">⎋</a></div></div></div><div class="sidebar-overlay" id="overlay" onclick="closeSidebar()"></div>"""
JS_SIDEBAR = """<script>function openSidebar(){document.getElementById('sidebar').classList.add('open');document.getElementById('overlay').classList.add('open')}function closeSidebar(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('open')}</script>"""
MOBILE_HEADER = """<div class="mobile-header"><button onclick="openSidebar()" style="background:none;border:none;font-size:20px;cursor:pointer;">☰</button><div style="font-weight:700;font-size:14px;">♻️ EcoTrack</div><a href="/logout" style="font-size:13px;color:var(--text-muted);text-decoration:none;">Logout</a></div>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EcoTrack - Login</title>""" + BASE_STYLE + """<style>.login-page{min-height:100vh;display:flex;background:linear-gradient(135deg,#f0fdf4,#dcfce7,#f0fdf4)}.login-left{flex:1;display:flex;align-items:center;justify-content:center;padding:40px}.login-panel{background:#fff;border-radius:20px;padding:44px;width:100%;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.08);animation:fadeUp .5s}.login-logo{display:flex;align-items:center;gap:12px;margin-bottom:32px}.login-logo-icon{width:48px;height:48px;background:linear-gradient(135deg,var(--green-500),var(--green-700));border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:22px;box-shadow:0 4px 14px rgba(34,197,94,.35)}.login-title{font-size:22px;font-weight:800}.login-sub{font-size:13px;color:var(--text-muted);margin-top:2px}.login-right{flex:1;background:linear-gradient(160deg,var(--green-600),var(--green-800));display:flex;align-items:center;justify-content:center;padding:60px;color:#fff}@media(max-width:768px){.login-right{display:none}.login-left{padding:20px}}.feature-list{list-style:none}.feature-list li{display:flex;align-items:center;gap:12px;margin-bottom:20px;font-size:15px}.feature-icon{width:40px;height:40px;background:rgba(255,255,255,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}.btn-login{width:100%;padding:12px;font-size:14px;font-weight:700;background:linear-gradient(135deg,var(--green-500),var(--green-700));color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer;transition:all .2s;box-shadow:0 4px 12px rgba(34,197,94,.3);font-family:inherit}.btn-login:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(34,197,94,.4)}.input-wrapper{position:relative}.input-icon{position:absolute;left:11px;top:50%;transform:translateY(-50%);font-size:15px;pointer-events:none}.input-wrapper .form-control{padding-left:34px}</style></head><body><div class="login-page"><div class="login-left"><div class="login-panel"><div class="login-logo"><div class="login-logo-icon">♻️</div><div><div class="login-title">EcoTrack</div><div class="login-sub">Smart Barangay Waste Collection System</div></div></div>{% if error %}<div class="alert alert-danger" style="display:flex;align-items:flex-start;gap:10px;"><span style="font-size:16px;flex-shrink:0;">⚠️</span><div>{{ error }}</div></div>{% endif %}<form method="POST" autocomplete="off"><div class="form-group"><label class="form-label">Email Address</label><div class="input-wrapper"><span class="input-icon">📧</span><input type="text" name="email" class="form-control{% if error %} is-invalid{% endif %}" placeholder="your@email.com" required autocomplete="off"></div></div><div class="form-group"><label class="form-label">Password</label><div class="input-wrapper"><span class="input-icon">🔒</span><input type="password" name="password" class="form-control{% if error %} is-invalid{% endif %}" placeholder="••••••••" required autocomplete="new-password"></div></div><button type="submit" class="btn-login">Sign In →</button></form><div style="text-align:center;margin-top:20px;font-size:13px;color:var(--text-muted);">New resident? <a href="/register" style="color:var(--green-600);font-weight:600;">Register here</a></div></div></div><div class="login-right"><div><div style="font-size:28px;font-weight:800;margin-bottom:8px;">Smart Waste Management</div><div style="opacity:.8;margin-bottom:40px;font-size:15px;">Powered by Machine Learning for a cleaner barangay</div><ul class="feature-list"><li><div class="feature-icon">🤖</div><div><strong>ML Predictions</strong><br><span style="opacity:.8;font-size:13px;">Predict waste overflow before it happens</span></div></li><li><div class="feature-icon">🗺️</div><div><strong>Zone Monitoring</strong><br><span style="opacity:.8;font-size:13px;">Real-time collection status per zone</span></div></li><li><div class="feature-icon">🔔</div><div><strong>Smart Reminders</strong><br><span style="opacity:.8;font-size:13px;">Automated notifications for residents</span></div></li><li><div class="feature-icon">📊</div><div><strong>Analytics Dashboard</strong><br><span style="opacity:.8;font-size:13px;">Data-driven insights for better planning</span></div></li></ul></div></div></div></body></html>"""

REGISTER_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EcoTrack - Register</title>""" + BASE_STYLE + """<style>.reg-page{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#f0fdf4,#dcfce7);padding:24px}.reg-card{background:#fff;border-radius:20px;padding:40px;width:100%;max-width:520px;box-shadow:0 20px 60px rgba(0,0,0,.08);animation:fadeUp .5s}.reg-header{text-align:center;margin-bottom:28px}.reg-header h2{font-size:20px;font-weight:800}.reg-header p{font-size:13px;color:var(--text-muted)}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:480px){.form-grid{grid-template-columns:1fr}}.btn-register{width:100%;padding:12px;font-size:14px;font-weight:700;background:linear-gradient(135deg,var(--green-500),var(--green-700));color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer;font-family:inherit;margin-top:8px;box-shadow:0 4px 12px rgba(34,197,94,.3)}.btn-register:hover{opacity:.9}.field-hint{font-size:11px;color:var(--text-muted);margin-top:4px}</style></head><body><div class="reg-page"><div class="reg-card"><div class="reg-header"><div style="font-size:32px;margin-bottom:8px;">♻️</div><h2>Create Resident Account</h2><p>Register your household to receive collection notifications</p></div>{% if errors %}<div class="alert alert-danger"><strong>⚠️ Please fix the following:</strong><ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul></div>{% endif %}{% if success %}<div class="alert alert-success">✅ {{ success }} <a href="/login" style="color:var(--green-700);font-weight:600;">Click here to login</a></div>{% else %}<form method="POST" autocomplete="off"><div class="form-grid"><div class="form-group"><label class="form-label">Full Name <span style="color:#ef4444">*</span></label><input type="text" name="name" class="form-control{% if errors %} is-invalid{% endif %}" placeholder="Juan dela Cruz" value="{{ form_data.get('name','') }}" required autocomplete="off"><div class="field-hint">Use your real full name</div></div><div class="form-group"><label class="form-label">Email <span style="color:#ef4444">*</span></label><input type="text" name="email" class="form-control{% if errors %} is-invalid{% endif %}" placeholder="you@email.com" value="{{ form_data.get('email','') }}" required autocomplete="off"></div><div class="form-group"><label class="form-label">Password <span style="color:#ef4444">*</span></label><input type="password" name="password" class="form-control{% if errors %} is-invalid{% endif %}" placeholder="Min. 6 characters" required autocomplete="new-password"></div><div class="form-group"><label class="form-label">Contact Number</label><input type="text" name="contact" class="form-control" placeholder="09XXXXXXXXX" value="{{ form_data.get('contact','') }}" autocomplete="off"><div class="field-hint">Optional – PH format</div></div></div><div class="form-group"><label class="form-label">Home Address</label><input type="text" name="address" class="form-control" placeholder="123 Rizal St, Brgy. San Pedro" value="{{ form_data.get('address','') }}" autocomplete="off"></div><div class="form-group"><label class="form-label">Barangay Zone</label><select name="zone" class="form-control"><option value="">-- Select your zone --</option>{% for z in zones %}<option value="{{ z.zone_name }}" {% if form_data.get('zone')==z.zone_name %}selected{% endif %}>{{ z.zone_name }}</option>{% endfor %}</select></div><button type="submit" class="btn-register">Create Account →</button></form>{% endif %}<div style="text-align:center;margin-top:16px;font-size:13px;color:var(--text-muted);">Already have an account? <a href="/login" style="color:var(--green-600);font-weight:600;">Sign in</a></div></div></div></body></html>"""

ADMIN_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin Dashboard - EcoTrack</title>""" + BASE_STYLE + """<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script></head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">🏠 Admin Dashboard</div><div class="topbar-right"><span style="font-size:12px;color:var(--text-muted);">Today: {{ today }}</span><button class="btn btn-primary btn-sm" onclick="runML()">🤖 Run ML</button><button class="btn btn-secondary btn-sm" onclick="openNotifModal()">🔔 Send Alert</button></div></div><div class="page-content"><div class="stats-grid"><div class="stat-card"><div class="stat-icon green">🏠</div><div class="stat-label">Total Households</div><div class="stat-value">{{ total_households }}</div><div class="stat-meta">Registered in system</div></div><div class="stat-card"><div class="stat-icon green">✅</div><div class="stat-label">Collected Today</div><div class="stat-value">{{ collected }}</div><div class="stat-meta">{{ pct }}% completion rate</div></div><div class="stat-card"><div class="stat-icon red">❌</div><div class="stat-label">Missed Pickups</div><div class="stat-value">{{ missed }}</div><div class="stat-meta">Requires follow-up</div></div><div class="stat-card"><div class="stat-icon yellow">⚠️</div><div class="stat-label">Open Reports</div><div class="stat-value">{{ open_reports }}</div><div class="stat-meta">Resident complaints</div></div></div><div class="card mb-24"><div class="card-header"><div><div class="card-title">Collection Completion</div><div class="card-subtitle">Today's progress across all zones</div></div><span class="badge badge-green">{{ pct }}% Done</span></div><div class="progress"><div class="progress-bar" id="progress-bar" style="width:0%"></div></div><div style="display:flex;gap:20px;margin-top:12px;font-size:12px;color:var(--text-muted);"><span>✅ Collected: {{ collected }}</span><span>⏳ Delayed: {{ delayed }}</span><span>❌ Missed: {{ missed }}</span></div></div><div class="grid-2 mb-24"><div class="card"><div class="card-header"><div><div class="card-title">📈 Waste Volume Trend</div><div class="card-subtitle">Last 7 days (kg)</div></div></div><div class="chart-container"><canvas id="trendChart"></canvas></div></div><div class="card"><div class="card-header"><div><div class="card-title">📊 Zone Performance</div><div class="card-subtitle">Collected vs Missed</div></div></div><div class="chart-container"><canvas id="zoneChart"></canvas></div></div></div><div class="grid-2 mb-24"><div class="card"><div class="card-header"><div class="card-title">📅 Today's Schedule</div><a href="/admin/schedules" class="btn btn-ghost btn-sm">Manage</a></div>{% if today_schedules %}<div class="table-wrap"><table><thead><tr><th>Zone</th><th>Time</th><th>Status</th></tr></thead><tbody>{% for s in today_schedules %}<tr><td>{{ s.zone_name }}</td><td>{{ s.collection_time }}</td><td><span class="badge badge-green">Active</span></td></tr>{% endfor %}</tbody></table></div>{% else %}<div class="empty-state"><p>No scheduled pickups today</p></div>{% endif %}</div><div class="card"><div class="card-header"><div><div class="card-title">🔴 High-Risk Zones</div><div class="card-subtitle">ML Predictions</div></div><a href="/admin/analytics" class="btn btn-ghost btn-sm">View All</a></div>{% if high_risk %}<div class="table-wrap"><table><thead><tr><th>Zone</th><th>Date</th><th>Level</th><th>Confidence</th></tr></thead><tbody>{% for h in high_risk %}<tr><td>{{ h.zone_name }}</td><td>{{ h.predicted_date }}</td><td><span class="risk-dot risk-high"></span> High</td><td>{{ (h.confidence_score*100)|int }}%</td></tr>{% endfor %}</tbody></table></div>{% else %}<div class="empty-state"><p>No high-risk zones predicted</p></div>{% endif %}</div></div><div class="card mb-24"><div class="card-header"><div><div class="card-title">🗺️ Zone Map Overview</div><div class="card-subtitle">Live collection status</div></div></div><div id="mapView" style="height:280px;border-radius:10px;background:linear-gradient(135deg,#f0fdf4,#dcfce7);border:1px solid var(--green-200);position:relative;overflow:hidden;"><div id="mapZones" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:20px;flex-wrap:wrap;padding:20px;"></div></div></div><div class="card mb-24"><div class="card-header"><div><div class="card-title">👥 Resident Collection Status by Zone</div><div class="card-subtitle">Last logged collection per resident</div></div><span class="badge badge-blue">{{ zone_residents|length }} zones</span></div>{% if zone_residents %}{% for zr in zone_residents %}<div class="zone-section"><div class="zone-section-header" onclick="toggleZone('zone-{{ zr.zone_id }}')"><span>🗺️ {{ zr.zone_name }}</span><div style="display:flex;align-items:center;gap:10px;"><span style="font-size:12px;color:var(--text-muted);font-weight:400;">{{ zr.residents|length }} resident(s)</span><span id="arrow-zone-{{ zr.zone_id }}" style="font-size:12px;transition:transform .2s;">▼</span></div></div><div class="zone-section-body" id="zone-{{ zr.zone_id }}"><div class="table-wrap"><table><thead><tr><th>Resident</th><th>Address</th><th>Contact</th><th>Last Status</th><th>Last Collected</th></tr></thead><tbody>{% for r in zr.residents %}<tr><td><strong>{{ r.name }}</strong></td><td style="font-size:12px;color:var(--text-muted);">{{ r.address or '—' }}</td><td style="font-size:12px;">{{ r.contact_number or '—' }}</td><td>{% if r.last_status == 'collected' %}<span class="badge badge-green">✅ Collected</span>{% elif r.last_status == 'missed' %}<span class="badge badge-red">❌ Missed</span>{% elif r.last_status == 'delayed' %}<span class="badge badge-yellow">⏳ Delayed</span>{% else %}<span class="badge badge-gray">— No data</span>{% endif %}</td><td style="font-size:11px;font-family:'DM Mono',monospace;color:var(--text-muted);">{{ r.last_collected[:16] if r.last_collected else '—' }}</td></tr>{% endfor %}</tbody></table></div></div></div>{% endfor %}{% else %}<div class="empty-state"><p>No resident data found.</p></div>{% endif %}</div></div></div><div class="modal-backdrop" id="notifModal"><div class="modal"><div class="modal-title">📢 Send Notification</div><div class="form-group"><label class="form-label">Message</label><textarea id="notifMsg" class="form-control" rows="3" placeholder="Enter message..."></textarea></div><div class="form-group"><label class="form-label">Type</label><select id="notifType" class="form-control"><option value="web">Web</option><option value="email">Email</option><option value="SMS">SMS</option></select></div><div class="modal-footer"><button class="btn btn-ghost" onclick="closeNotifModal()">Cancel</button><button class="btn btn-primary" onclick="sendNotification()">Send</button></div></div></div><div id="mlStatus" style="display:none;position:fixed;bottom:20px;right:20px;background:var(--green-700);color:#fff;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:999;box-shadow:var(--shadow-lg);"></div>""" + JS_SIDEBAR + """<script>setTimeout(()=>{document.getElementById('progress-bar').style.width='{{ pct }}%'},400);new Chart(document.getElementById('trendChart'),{type:'line',data:{labels:{{ trend_data|tojson }}.map(d=>d.date.slice(5)),datasets:[{label:'Waste Volume (kg)',data:{{ trend_data|tojson }}.map(d=>d.volume),borderColor:'#16a34a',backgroundColor:'rgba(34,197,94,0.1)',tension:0.4,fill:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{grid:{color:'#f0fdf4'}}}}});new Chart(document.getElementById('zoneChart'),{type:'bar',data:{labels:{{ zone_perf|tojson }}.map(z=>z.zone_name.substring(0,15)),datasets:[{label:'Collected',data:{{ zone_perf|tojson }}.map(z=>z.collected||0),backgroundColor:'#22c55e'},{label:'Missed',data:{{ zone_perf|tojson }}.map(z=>z.missed||0),backgroundColor:'#ef4444'},{label:'Delayed',data:{{ zone_perf|tojson }}.map(z=>z.delayed||0),backgroundColor:'#f59e0b'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#f0fdf4'}}},plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}}}});fetch('/api/map-data').then(r=>r.json()).then(zones=>{const c=document.getElementById('mapZones'),rc={high:'#ef4444',medium:'#f59e0b',low:'#22c55e'};zones.forEach(z=>{const d=document.createElement('div');d.style.cssText=`background:#fff;border-radius:12px;padding:12px 16px;text-align:center;min-width:110px;border:2px solid ${rc[z.waste_level]||'#e2e8f0'};box-shadow:0 2px 8px rgba(0,0,0,.08);`;d.innerHTML=`<div style="font-size:12px;font-weight:700;color:#0f172a;">${z.zone_name.substring(0,20)}</div><div style="font-size:10px;color:#64748b;margin-top:2px;">Risk: ${z.waste_level}</div>`;c.appendChild(d)})});function toggleZone(id){const body=document.getElementById(id);const arrow=document.getElementById('arrow-'+id);const isOpen=body.classList.contains('open');body.classList.toggle('open');arrow.style.transform=isOpen?'':'rotate(180deg)'}function runML(){const b=event.target;b.disabled=true;b.innerHTML='⏳ Processing...';fetch('/api/run-ml',{method:'POST'}).then(r=>r.json()).then(d=>{b.disabled=false;b.innerHTML='🤖 Run ML';const e=document.getElementById('mlStatus');e.style.display='block';e.textContent=`🤖 ${d.predictions_generated} predictions updated!`;setTimeout(()=>{e.style.display='none';location.reload()},3000)})}function openNotifModal(){document.getElementById('notifModal').classList.add('open')}function closeNotifModal(){document.getElementById('notifModal').classList.remove('open')}function sendNotification(){const m=document.getElementById('notifMsg').value.trim(),t=document.getElementById('notifType').value;if(!m)return alert('Enter a message');fetch('/api/notifications/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,type:t})}).then(r=>r.json()).then(d=>{closeNotifModal();const e=document.getElementById('mlStatus');e.style.display='block';e.textContent=`✅ Notification sent to ${d.sent} residents!`;setTimeout(()=>e.style.display='none',3000)})}</script></body></html>"""

ZONES_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Zones - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">🗺️ Manage Zones</div><button class="btn btn-primary btn-sm" onclick="document.getElementById('addModal').classList.add('open')">+ Add Zone</button></div><div class="page-content"><div class="card"><div class="card-header"><div class="card-title">All Zones</div><span class="badge badge-green">{{ zones|length }} zones</span></div><div class="table-wrap"><table><thead><tr><th>#</th><th>Zone Name</th><th>Description</th><th>Actions</th></tr></thead><tbody>{% for z in zones %}<tr><td>{{ z.zone_id }}</td><td><strong>{{ z.zone_name }}</strong></td><td>{{ z.description or '—' }}</td><td><form method="POST" style="display:inline;" onsubmit="return confirm('Delete this zone?')"><input type="hidden" name="action" value="delete"><input type="hidden" name="zone_id" value="{{ z.zone_id }}"><button class="btn btn-danger btn-sm">Delete</button></form></td></tr>{% endfor %}</tbody></table></div></div></div></div><div class="modal-backdrop" id="addModal"><div class="modal"><div class="modal-title">➕ Add Zone</div><form method="POST"><input type="hidden" name="action" value="add"><div class="form-group"><label class="form-label">Zone Name</label><input type="text" name="zone_name" class="form-control" placeholder="Zone name..." required></div><div class="form-group"><label class="form-label">Description</label><textarea name="description" class="form-control" rows="2" placeholder="Brief description..."></textarea></div><div class="modal-footer"><button type="button" class="btn btn-ghost" onclick="document.getElementById('addModal').classList.remove('open')">Cancel</button><button type="submit" class="btn btn-primary">Add Zone</button></div></form></div></div>""" + JS_SIDEBAR + """</body></html>"""

SCHEDULES_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Schedules - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">📅 Collection Schedules</div><button class="btn btn-primary btn-sm" onclick="document.getElementById('addModal').classList.add('open')">+ Add Schedule</button></div><div class="page-content"><div class="card"><div class="card-header"><div class="card-title">All Schedules</div><span class="badge badge-blue">{{ schedules|length }} total</span></div><div class="table-wrap"><table><thead><tr><th>Zone</th><th>Day</th><th>Time</th><th>Status</th><th>Actions</th></tr></thead><tbody>{% for s in schedules %}<tr><td><strong>{{ s.zone_name }}</strong></td><td>{{ s.collection_day }}</td><td>{{ s.collection_time }}</td><td><span class="badge {% if s.status=='active' %}badge-green{% else %}badge-gray{% endif %}">{{ s.status }}</span></td><td style="display:flex;gap:6px;"><form method="POST" style="display:inline;"><input type="hidden" name="action" value="toggle"><input type="hidden" name="schedule_id" value="{{ s.schedule_id }}"><button class="btn btn-secondary btn-sm">Toggle</button></form><form method="POST" style="display:inline;" onsubmit="return confirm('Delete?')"><input type="hidden" name="action" value="delete"><input type="hidden" name="schedule_id" value="{{ s.schedule_id }}"><button class="btn btn-danger btn-sm">Delete</button></form></td></tr>{% endfor %}</tbody></table></div></div></div></div><div class="modal-backdrop" id="addModal"><div class="modal"><div class="modal-title">➕ Add Schedule</div><form method="POST"><input type="hidden" name="action" value="add"><div class="form-group"><label class="form-label">Zone</label><select name="zone_id" class="form-control">{% for z in zones %}<option value="{{ z.zone_id }}">{{ z.zone_name }}</option>{% endfor %}</select></div><div class="form-group"><label class="form-label">Day</label><select name="collection_day" class="form-control">{% for day in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'] %}<option>{{ day }}</option>{% endfor %}</select></div><div class="form-group"><label class="form-label">Time</label><input type="time" name="collection_time" class="form-control" value="07:00"></div><div class="modal-footer"><button type="button" class="btn btn-ghost" onclick="document.getElementById('addModal').classList.remove('open')">Cancel</button><button type="submit" class="btn btn-primary">Add Schedule</button></div></form></div></div>""" + JS_SIDEBAR + """</body></html>"""

USERS_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Users - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">👥 User Management</div><button class="btn btn-primary btn-sm" onclick="document.getElementById('addModal').classList.add('open')">+ Add User</button></div><div class="page-content"><div class="card"><div class="card-header"><div class="card-title">All Users</div><span class="badge badge-blue">{{ users|length }} total</span></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Contact</th><th>Actions</th></tr></thead><tbody>{% for u in users %}<tr><td><strong>{{ u.name }}</strong></td><td>{{ u.email }}</td><td><span class="badge {% if u.role=='admin' %}badge-red{% elif u.role=='collector' %}badge-blue{% else %}badge-green{% endif %}">{{ u.role }}</span></td><td>{{ u.contact_number or '—' }}</td><td>{% if u.user_id != session.user_id %}<form method="POST" style="display:inline;" onsubmit="return confirm('Delete user?')"><input type="hidden" name="action" value="delete"><input type="hidden" name="user_id" value="{{ u.user_id }}"><button class="btn btn-danger btn-sm">Delete</button></form>{% else %}<span style="font-size:11px;color:var(--text-muted);">Current user</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div></div><div class="modal-backdrop" id="addModal"><div class="modal"><div class="modal-title">➕ Add User</div><form method="POST" autocomplete="off"><input type="hidden" name="action" value="add"><div class="form-group"><label class="form-label">Name</label><input type="text" name="name" class="form-control" required autocomplete="off"></div><div class="form-group"><label class="form-label">Email</label><input type="text" name="email" class="form-control" required autocomplete="off"></div><div class="form-group"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required autocomplete="new-password"></div><div class="form-group"><label class="form-label">Role</label><select name="role" class="form-control"><option value="resident">Resident</option><option value="collector">Collector</option><option value="admin">Admin</option></select></div><div class="modal-footer"><button type="button" class="btn btn-ghost" onclick="document.getElementById('addModal').classList.remove('open')">Cancel</button><button type="submit" class="btn btn-primary">Add User</button></div></form></div></div>""" + JS_SIDEBAR + """</body></html>"""

REPORTS_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reports - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">📋 Reports & Complaints</div><span class="badge badge-yellow">{{ reports|selectattr('status','eq','open')|list|length }} Open</span></div><div class="page-content"><div class="card"><div class="table-wrap"><table><thead><tr><th>Resident</th><th>Issue</th><th>Description</th><th>Date</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for r in reports %}<tr><td><strong>{{ r.name }}</strong></td><td><span class="badge badge-yellow">{{ r.issue_type }}</span></td><td style="max-width:250px;">{{ r.description[:80] }}</td><td>{{ r.created_at[:10] }}</td><td><span class="badge {% if r.status=='open' %}badge-red{% else %}badge-green{% endif %}">{{ r.status }}</span></td><td>{% if r.status=='open' %}<form method="POST" action="/admin/report/resolve/{{ r.report_id }}"><button class="btn btn-secondary btn-sm">Resolve</button></form>{% else %}<span style="font-size:11px;color:var(--green-600);">✓ Resolved</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div></div>""" + JS_SIDEBAR + """</body></html>"""

ANALYTICS_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Analytics - EcoTrack</title>""" + BASE_STYLE + """<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script></head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">📊 Analytics & ML Predictions</div><button class="btn btn-primary btn-sm" onclick="runML()">🤖 Refresh ML</button></div><div class="page-content"><div class="grid-2 mb-24"><div class="card"><div class="card-header"><div class="card-title">📅 Peak Waste Days</div></div><div class="chart-container"><canvas id="peakChart"></canvas></div></div><div class="card"><div class="card-header"><div class="card-title">📈 Collection Efficiency</div></div><div class="chart-container"><canvas id="effChart"></canvas></div></div></div><div class="card"><div class="card-header"><div><div class="card-title">🔮 7-Day Predictions</div><div class="card-subtitle">ML risk forecast per zone</div></div></div><div class="table-wrap"><table><thead><tr><th>Zone</th><th>Date</th><th>Level</th><th>Confidence</th><th>Action</th></tr></thead><tbody>{% for p in preds %}<tr><td><strong>{{ p.zone_name }}</strong></td><td>{{ p.predicted_date }}</td><td><span class="risk-dot risk-{{ p.waste_level }}"></span> <span class="badge {% if p.waste_level=='high' %}badge-red{% elif p.waste_level=='medium' %}badge-yellow{% else %}badge-green{% endif %}">{{ p.waste_level }}</span></td><td><div class="progress" style="width:80px;height:6px;display:inline-block;vertical-align:middle;margin-right:8px;"><div class="progress-bar" style="width:{{ (p.confidence_score*100)|int }}%"></div></div>{{ (p.confidence_score*100)|int }}%</td><td style="font-size:12px;">{% if p.waste_level=='high' %}Alert residents{% elif p.waste_level=='medium' %}Monitor{% else %}Normal{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div></div>""" + JS_SIDEBAR + """<script>new Chart(document.getElementById('peakChart'),{type:'bar',data:{labels:{{ peak|tojson }}.map(d=>d.day),datasets:[{label:'Avg Volume (kg)',data:{{ peak|tojson }}.map(d=>d.avg),backgroundColor:{{ peak|tojson }}.map(d=>(d.day==='Fri'||d.day==='Sat')?'#ef4444':'#22c55e')}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}}}});new Chart(document.getElementById('effChart'),{type:'line',data:{labels:{{ eff|tojson }}.map(d=>d.d.slice(5)),datasets:[{label:'Efficiency %',data:{{ eff|tojson }}.map(d=>d.pct),borderColor:'#16a34a',backgroundColor:'rgba(34,197,94,0.1)',tension:0.4,fill:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'}}}}});function runML(){const b=event.target;b.disabled=true;b.innerHTML='⏳ Processing...';fetch('/api/run-ml',{method:'POST'}).then(r=>r.json()).then(d=>{b.disabled=false;b.innerHTML='🤖 Refresh ML';location.reload()})}</script></body></html>"""

NOTIF_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Notifications - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_ADMIN + """<div class="main-content"><div class="topbar"><div class="topbar-title">🔔 Notifications</div></div><div class="page-content"><div class="card"><div class="card-header"><div class="card-title">Recent Notifications</div></div><div class="table-wrap"><table><thead><tr><th>Recipient</th><th>Message</th><th>Type</th><th>Status</th><th>Sent</th></tr></thead><tbody>{% for n in notifs %}<tr><td><strong>{{ n.name }}</strong></td><td style="max-width:300px;font-size:12px;">{{ n.message[:80] }}</td><td><span class="badge {% if n.type=='web' %}badge-blue{% elif n.type=='email' %}badge-green{% else %}badge-yellow{% endif %}">{{ n.type }}</span></td><td><span class="badge {% if n.status=='sent' %}badge-green{% else %}badge-red{% endif %}">{{ n.status }}</span></td><td style="font-size:11px;">{{ n.sent_at[:16] }}</td></tr>{% endfor %}</tbody></table></div></div></div></div>""" + JS_SIDEBAR + """</body></html>"""

COLLECTOR_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Collector Dashboard - EcoTrack</title>""" + BASE_STYLE + """<script>function updateEstimate(){const c=parseInt(document.getElementById('est_bin_count').value)||0,t=document.getElementById('est_bin_type').value,f=document.getElementById('est_fill_level').value;const w={'small_bag':8,'medium_bag':15,'large_bag':25,'small_drum':30,'medium_drum':60,'large_drum':100,'small_bin':20,'large_bin':40};const m={'quarter':0.25,'half':0.5,'mostly':0.75,'full':1.0,'overflow':1.3};document.getElementById('estimated_result').textContent='Estimated: '+Math.round(c*(w[t]||15)*(m[f]||1.0))+' kg'}document.addEventListener('DOMContentLoaded',function(){['est_bin_count','est_bin_type','est_fill_level'].forEach(id=>{const el=document.getElementById(id);if(el){el.addEventListener('change',updateEstimate);el.addEventListener('input',updateEstimate)}});updateEstimate()});function togglePred(zoneId){const el=document.getElementById('pred-'+zoneId);if(el){el.style.display=el.style.display==='none'?'block':'none';}}</script></head><body>""" + MOBILE_HEADER + SIDEBAR_COLLECTOR + """<div class="main-content"><div class="topbar"><div class="topbar-title">🚛 Collector Dashboard</div><span style="font-size:13px;color:var(--text-muted);">{{ today }}'s Routes</span></div><div class="page-content"><div class="stats-grid mb-24">{% set ct=stats|selectattr('status','eq','collected')|list %}{% set mt=stats|selectattr('status','eq','missed')|list %}{% set dt=stats|selectattr('status','eq','delayed')|list %}<div class="stat-card"><div class="stat-icon green">✅</div><div class="stat-label">Collected</div><div class="stat-value">{{ ct[0].cnt if ct else 0 }}</div></div><div class="stat-card"><div class="stat-icon red">❌</div><div class="stat-label">Missed</div><div class="stat-value">{{ mt[0].cnt if mt else 0 }}</div></div><div class="stat-card"><div class="stat-icon yellow">⏳</div><div class="stat-label">Delayed</div><div class="stat-value">{{ dt[0].cnt if dt else 0 }}</div></div><div class="stat-card"><div class="stat-icon blue">🗺️</div><div class="stat-label">Zones</div><div class="stat-value">{{ assigned|length }}</div></div></div><div class="alert alert-info mb-24"><strong>📏 Estimation Guide:</strong> Small Bag (8kg) | Medium Bag (15kg) | Large Bag (25kg) | Small Drum (30kg) | Medium Drum (60kg) | Large Drum (100kg)</div><div class="grid-2 mb-24"><div class="card"><div class="card-header"><div class="card-title">📍 Today's Assigned Zones</div></div>{% if assigned %}{% for a in assigned %}<div style="background:var(--green-50);border:1px solid var(--green-200);border-radius:var(--radius-sm);padding:14px;margin-bottom:10px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><div><strong>{{ a.zone_name }}</strong></div><span style="font-family:'DM Mono';font-size:13px;color:var(--green-700);background:#fff;padding:3px 8px;border-radius:6px;">⏰ {{ a.collection_time }}</span></div>{% if zone_predictions.get(a.zone_id) %}<div style="margin-bottom:10px;"><button type="button" onclick="togglePred({{ a.zone_id }})" class="btn btn-secondary btn-sm" style="width:100%;justify-content:center;">🔮 View ML Predictions</button><div id="pred-{{ a.zone_id }}" style="display:none;margin-top:8px;background:#fff;border-radius:8px;padding:10px;border:1px solid var(--green-200);"><div style="font-size:11px;font-weight:700;color:var(--text-muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em;">7-Day Forecast</div><div style="display:flex;flex-wrap:wrap;gap:4px;">{% for pred in zone_predictions[a.zone_id] %}<span class="pred-pill pred-pill-{{ pred.waste_level }}"><span class="risk-dot risk-{{ pred.waste_level }}" style="width:7px;height:7px;"></span>{{ pred.predicted_date[5:] }} · {{ pred.waste_level }} · {{ (pred.confidence_score*100)|int }}%</span>{% endfor %}</div></div></div>{% endif %}<form method="POST" action="/collector/log"><input type="hidden" name="zone_id" value="{{ a.zone_id }}"><div class="form-group" style="margin-bottom:6px;"><label class="form-label" style="font-size:10px;">Number of Containers</label><input type="number" name="bin_count" class="form-control" value="2" min="0" max="20" style="padding:6px 10px;font-size:12px;" required></div><div class="form-group" style="margin-bottom:6px;"><label class="form-label" style="font-size:10px;">Container Type</label><select name="bin_type" class="form-control" style="padding:6px 10px;font-size:12px;"><option value="small_bag">Small Bag (8kg)</option><option value="medium_bag">Medium Bag (15kg)</option><option value="large_bag">Large Bag (25kg)</option><option value="small_drum">Small Drum (30kg)</option><option value="medium_drum" selected>Medium Drum (60kg)</option><option value="large_drum">Large Drum (100kg)</option></select></div><div class="form-group" style="margin-bottom:6px;"><label class="form-label" style="font-size:10px;">Fill Level</label><select name="fill_level" class="form-control" style="padding:6px 10px;font-size:12px;"><option value="quarter">25% - Quarter</option><option value="half">50% - Half</option><option value="mostly">75% - Mostly</option><option value="full" selected>100% - Full</option><option value="overflow">Overflowing</option></select></div><div class="form-group" style="margin-bottom:6px;"><label class="form-label" style="font-size:10px;">Status</label><select name="status" class="form-control" style="padding:6px 10px;font-size:12px;"><option value="collected">✅ Collected</option><option value="missed">❌ Missed</option><option value="delayed">⏳ Delayed</option></select></div><div class="form-group" style="margin-bottom:6px;"><label class="form-label" style="font-size:10px;">Remarks</label><input type="text" name="remarks" class="form-control" style="padding:6px 10px;font-size:12px;" placeholder="Optional..."></div><button type="submit" class="btn btn-primary btn-sm" style="width:100%;">📝 Log Collection</button></form></div>{% endfor %}{% else %}<div class="empty-state"><p>No collections scheduled today</p></div>{% endif %}</div><div><div class="card mb-20"><div class="card-header"><div><div class="card-title">🧮 Live Calculator</div></div></div><div class="form-group"><label class="form-label">Containers</label><input type="number" id="est_bin_count" class="form-control" value="3" min="0" max="20"></div><div class="form-group"><label class="form-label">Type</label><select id="est_bin_type" class="form-control"><option value="small_bag">Small Bag (8kg)</option><option value="medium_bag">Medium Bag (15kg)</option><option value="large_bag">Large Bag (25kg)</option><option value="small_drum">Small Drum (30kg)</option><option value="medium_drum" selected>Medium Drum (60kg)</option><option value="large_drum">Large Drum (100kg)</option></select></div><div class="form-group"><label class="form-label">Fill Level</label><select id="est_fill_level" class="form-control"><option value="quarter">25%</option><option value="half">50%</option><option value="mostly">75%</option><option value="full" selected>100%</option><option value="overflow">Overflow</option></select></div><div class="estimation-result" id="estimated_result">Estimated: -- kg</div></div><div class="card"><div class="card-header"><div class="card-title">📝 Manual Log Entry</div></div><form method="POST" action="/collector/log"><div class="form-group"><label class="form-label">Zone</label><select name="zone_id" class="form-control">{% for z in all_zones %}<option value="{{ z.zone_id }}">{{ z.zone_name }}</option>{% endfor %}</select></div><div class="form-group"><label class="form-label">Status</label><select name="status" class="form-control"><option value="collected">✅ Collected</option><option value="missed">❌ Missed</option><option value="delayed">⏳ Delayed</option></select></div><div class="form-group"><label class="form-label">Containers</label><input type="number" name="bin_count" class="form-control" value="2" min="0" required></div><div class="form-group"><label class="form-label">Type</label><select name="bin_type" class="form-control"><option value="medium_drum" selected>Medium Drum (60kg)</option><option value="large_drum">Large Drum (100kg)</option><option value="small_drum">Small Drum (30kg)</option></select></div><div class="form-group"><label class="form-label">Fill Level</label><select name="fill_level" class="form-control"><option value="full" selected>Full</option><option value="mostly">Mostly</option><option value="half">Half</option><option value="quarter">Quarter</option></select></div><div class="form-group"><label class="form-label">Remarks</label><textarea name="remarks" class="form-control" rows="2" placeholder="Optional..."></textarea></div><button type="submit" class="btn btn-primary" style="width:100%;">Submit Log</button></form></div></div></div><div class="card"><div class="card-header"><div class="card-title">📋 Recent Logs</div></div><div class="table-wrap"><table><thead><tr><th>Zone</th><th>Status</th><th>Volume</th><th>Remarks</th><th>Time</th></tr></thead><tbody>{% for l in recent_logs %}<tr><td><strong>{{ l.zone_name }}</strong></td><td><span class="badge {% if l.status=='collected' %}badge-green{% elif l.status=='missed' %}badge-red{% else %}badge-yellow{% endif %}">{{ l.status }}</span></td><td style="font-size:12px;">{% if l.bin_count %}{{ l.bin_count }}x {{ l.bin_type.replace('_',' ') }}{% else %}—{% endif %}</td><td style="font-size:12px;">{{ l.remarks or '—' }}</td><td style="font-size:11px;">{{ l.collected_at[:16] }}</td></tr>{% endfor %}</tbody></table></div></div></div></div>""" + JS_SIDEBAR + """</body></html>"""

RESIDENT_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>My Dashboard - EcoTrack</title>""" + BASE_STYLE + """</head><body>""" + MOBILE_HEADER + SIDEBAR_RESIDENT + """<div class="main-content"><div class="topbar"><div class="topbar-title">🏡 My Dashboard</div><span style="font-size:13px;color:var(--text-muted);">{{ today }}</span></div><div class="page-content">{% if household %}<div class="card mb-24" style="background:linear-gradient(135deg,var(--green-600),var(--green-800));color:#fff;border:none;"><div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;"><div style="font-size:40px;">🏠</div><div style="flex:1;"><div style="font-size:18px;font-weight:800;">{{ session.name }}'s Household</div><div style="opacity:.85;font-size:13px;">📍 {{ household.address }}</div><div style="opacity:.85;font-size:13px;">🗺️ {{ household.barangay_zone }}</div></div>{% if last_log %}<div style="background:rgba(255,255,255,.15);padding:12px 18px;border-radius:10px;text-align:center;"><div style="font-size:11px;opacity:.8;">Last Collection</div><div style="font-size:24px;">{% if last_log.status=='collected' %}✅{% elif last_log.status=='missed' %}❌{% else %}⏳{% endif %}</div><div style="font-size:13px;font-weight:700;text-transform:capitalize;">{{ last_log.status }}</div><div style="font-size:11px;opacity:.7;">{{ last_log.collected_at[:10] }}</div></div>{% endif %}</div></div>{% endif %}<div class="grid-2 mb-24"><div class="card"><div class="card-header"><div class="card-title">📅 My Collection Schedule</div></div>{% if schedule %}{% for s in schedule %}<div style="display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border);"><div><div style="font-weight:600;">{{ s.collection_day }}</div><div style="font-size:12px;color:var(--text-muted);">Weekly pickup</div></div><div style="text-align:right;"><div style="font-family:'DM Mono';font-size:15px;font-weight:700;color:var(--green-700);">{% if format_time_ampm %}{{ format_time_ampm(s.collection_time) }}{% else %}{{ s.collection_time }}{% endif %}</div><span class="badge badge-green">{{ s.status }}</span></div></div>{% endfor %}{% else %}<div class="empty-state"><p>No schedule found for your zone</p></div>{% endif %}</div><div class="card"><div class="card-header"><div><div class="card-title">📦 Collection History</div><div class="card-subtitle">Recent pickups in your zone</div></div></div>{% if recent_collections %}<div class="collection-timeline">{% for c in recent_collections %}<div class="collection-item"><div class="collection-icon">{% if c.status == 'collected' %}✅{% elif c.status == 'missed' %}❌{% else %}⏳{% endif %}</div><div class="collection-info"><div style="font-weight:600;font-size:13px;text-transform:capitalize;">{{ c.status }}</div>{% if c.bin_count %}<div style="font-size:11px;color:var(--text-muted);">{{ c.bin_count }}x {{ c.bin_type.replace('_',' ') if c.bin_type else '' }} · {{ c.fill_level }} fill</div>{% endif %}{% if c.remarks %}<div style="font-size:11px;color:var(--text-muted);">{{ c.remarks }}</div>{% endif %}</div><div class="collection-date">{{ c.collected_at[:10] }}</div></div>{% endfor %}</div>{% else %}<div class="empty-state"><p>No collection history yet.</p></div>{% endif %}</div></div><div class="grid-2 mb-24"><div class="card"><div class="card-header"><div class="card-title">🔔 Notifications</div><span class="badge badge-green">{{ notifs|length }}</span></div>{% if notifs %}{% for n in notifs %}<div style="padding:10px 0;border-bottom:1px solid var(--border);"><div style="font-size:13px;">{{ n.message }}</div><div style="font-size:11px;color:var(--text-muted);">{{ n.sent_at[:16] }}</div></div>{% endfor %}{% else %}<div class="empty-state"><p>No notifications yet</p></div>{% endif %}</div><div class="card"><div class="card-header"><div class="card-title">📢 Submit a Report</div></div><form method="POST" action="/resident/report"><div class="form-group"><label class="form-label">Issue Type</label><select name="issue_type" class="form-control"><option value="missed pickup">Missed Pickup</option><option value="overflow">Bin Overflow</option><option value="wrong schedule">Wrong Schedule</option><option value="other">Other</option></select></div><div class="form-group"><label class="form-label">Description</label><textarea name="description" class="form-control" rows="3" placeholder="Describe the issue..." required></textarea></div><button type="submit" class="btn btn-primary" style="width:100%;">Submit Report</button></form>{% if my_reports %}<div style="margin-top:16px;border-top:1px solid var(--border);padding-top:14px;"><div style="font-size:12px;font-weight:700;color:var(--text-muted);margin-bottom:8px;text-transform:uppercase;">My Reports</div>{% for r in my_reports %}<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);"><div style="font-size:12px;"><strong>{{ r.issue_type }}</strong><br><span style="color:var(--text-muted);">{{ r.created_at[:10] }}</span></div><span class="badge {% if r.status=='open' %}badge-red{% else %}badge-green{% endif %}">{{ r.status }}</span></div>{% endfor %}</div>{% endif %}</div></div></div></div>""" + JS_SIDEBAR + """</body></html>"""

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    run_ml_prediction()
    print("""
╔══════════════════════════════════════════════════════╗
║  ♻️  EcoTrack - Smart Barangay Waste Collection     ║
║  ────────────────────────────────────────────────    ║
║  Admin:     admin@barangay.gov / admin123            ║
║  Collector: collector@barangay.gov / collector123    ║
║  Resident:  resident@barangay.gov / resident123      ║
║  Running at: http://127.0.0.1:5000                   ║
╚══════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=5000)