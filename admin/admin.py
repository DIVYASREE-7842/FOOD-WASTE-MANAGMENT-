# admin_bp.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app as app
import mysql.connector
from datetime import datetime, timedelta
from functools import wraps
import requests

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")

# ---------------- DB CONNECTION ----------------
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="7842557971",
        database="food_db"
    )

# -------------- admin decorator ------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in and is Admin
        if 'user_id' not in session or 'Admin' not in (session.get('role') or []):
            flash("Unauthorized access! Please log in as Admin.", "danger")
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated_function
# ---------------- ADMIN GUARD ----------------
def admin_required():
    return 'user_id' in session and 'Admin' in session.get('role', [])

# ---------------- FETCH PENDING REQUESTS ----------------
def fetch_pending_requests():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.request_id, u.first_name, u.last_name, r.message, r.created_at
        FROM user_requests r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.status='Pending' AND r.is_deleted=0
        ORDER BY r.created_at DESC
    """)
    pending = cursor.fetchall()
    cursor.close()
    db.close()
    return pending

# ---------------- Notifications helpers ----------------
def insert_notification(db_cursor, user_id, role, message, ntype='info'):
    db_cursor.execute("""
        INSERT INTO notifications (user_id, role, message, type, created_at)
        VALUES (%s, %s, %s, %s, NOW())
    """, (user_id, role, message, ntype))

def fetch_user_notifications(user_id, role, limit=100):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT notification_id, message, type, is_read, created_at
        FROM notifications
        WHERE user_id=%s AND role=%s
        ORDER BY created_at DESC
        LIMIT %s
    """, (user_id, role, limit))
    notifs = cursor.fetchall()
    cursor.close()
    conn.close()
    return notifs

# ---------------- DASHBOARD (unchanged logic kept) ----------------
@admin_bp.route("/dashboard")
def dashboard():
    if not admin_required():
        flash("Unauthorized access!", "danger")
        return redirect(url_for("auth.login_page"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # ---- Stats ----
    cursor.execute("SELECT COUNT(*) AS total_donors FROM users WHERE role LIKE '%Donor%' AND is_deleted=0")
    total_donors = cursor.fetchone()['total_donors']

    cursor.execute("SELECT COUNT(*) AS total_recipients FROM users WHERE role LIKE '%Recipient%' AND is_deleted=0")
    total_recipients = cursor.fetchone()['total_recipients']

    cursor.execute("SELECT COUNT(*) AS active_donors FROM users WHERE role LIKE '%Donor%' AND status='Active' AND is_deleted=0")
    active_donors = cursor.fetchone()['active_donors']

    cursor.execute("SELECT COUNT(*) AS active_recipients FROM users WHERE role LIKE '%Recipient%' AND status='Active' AND is_deleted=0")
    active_recipients = cursor.fetchone()['active_recipients']

    # ---- Donations Chart ----
    period = request.args.get("period", "daily")  # 👈 get from query string (default daily)

    if period == "daily":
        cursor.execute("""
            SELECT DATE(prepared_at) AS day, COUNT(*) AS total
            FROM donations
            WHERE is_deleted=0
            GROUP BY DATE(prepared_at)
            ORDER BY day ASC
        """)
        rows = cursor.fetchall()
        donation_labels = [r['day'].strftime("%Y-%m-%d") for r in rows]
        donation_values = [r['total'] for r in rows]

    elif period == "weekly":
        cursor.execute("""
            SELECT YEARWEEK(prepared_at, 1) AS week, COUNT(*) AS total
            FROM donations
            WHERE is_deleted=0
            GROUP BY YEARWEEK(prepared_at, 1)
            ORDER BY week ASC
        """)
        rows = cursor.fetchall()
        donation_labels = [f"Week {r['week']}" for r in rows]
        donation_values = [r['total'] for r in rows]

    elif period == "monthly":
        cursor.execute("""
            SELECT DATE_FORMAT(prepared_at, '%Y-%m') AS month, COUNT(*) AS total
            FROM donations
            WHERE is_deleted=0
            GROUP BY DATE_FORMAT(prepared_at, '%Y-%m')
            ORDER BY month ASC
        """)
        rows = cursor.fetchall()
        donation_labels = [r['month'] for r in rows]
        donation_values = [r['total'] for r in rows]

    else:
        # fallback to daily
        donation_labels, donation_values = [], []

    # ---- Food type distribution ----
    cursor.execute("""
        SELECT food_type, COUNT(*) AS total 
        FROM donations 
        WHERE is_deleted=0 
        GROUP BY food_type
    """)
    food_rows = cursor.fetchall()
    total_donations = sum(r['total'] for r in food_rows) if food_rows else 0
    food_labels = [r['food_type'] for r in food_rows]
    food_values = [
        round((r['total'] / total_donations) * 100, 2) if total_donations > 0 else 0
        for r in food_rows
    ]

    # ---- Food saved per day ----
    cursor.execute("""
        SELECT DATE(prepared_at) AS save_date, 
               SUM(quantity) AS total_saved
        FROM donations
        WHERE is_deleted = 0
        GROUP BY DATE(prepared_at)
        ORDER BY save_date
    """)
    saved_rows = cursor.fetchall()
    saved_labels = [r['save_date'].strftime("%Y-%m-%d") for r in saved_rows]
    saved_values = [r['total_saved'] for r in saved_rows]

    # ---- Pending requests ----
    pending_requests = fetch_pending_requests()
    pending_count = len(pending_requests)

    # ---- Lists ----
    cursor.execute("SELECT user_id, first_name, last_name FROM users WHERE role LIKE '%Donor%' AND status='ACTIVE' LIMIT 20")
    active_donor_list = cursor.fetchall()

    cursor.execute("SELECT user_id, first_name, last_name FROM users WHERE role='Recipient' AND status='ACTIVE' LIMIT 20")
    active_recipient_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin/dashboard.html",
        total_donors=total_donors,
        total_recipients=total_recipients,
        active_donors=active_donors,
        active_recipients=active_recipients,
        donation_labels=donation_labels,
        donation_values=donation_values,
        food_labels=food_labels,
        food_values=food_values,
        saved_labels=saved_labels,
        saved_values=saved_values,
        saved_data=saved_rows,
        pending_requests=pending_requests,
        pending_count=pending_count,
        active_donor_list=active_donor_list,
        active_recipient_list=active_recipient_list,
        period=period   # 👈 send period to template
    )

# ---------------- CSC API config (unchanged) ----------------
CSC_API_KEY = "bkgwS1F2bFhGOHVBeUJLUUtiZEZiemtydmtuMk8xbGV1Nlo4UEVoYQ=="
CSC_BASE = "https://api.countrystatecity.in/v1"
api_id = CSC_API_KEY
base_url = CSC_BASE
headers = {'X-CSCAPI-KEY': api_id}

@admin_bp.route('/api/countries')
def get_countries():
    try:
        response = requests.get(f"{base_url}/countries", headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/countries/<country_code>/states')
def get_states(country_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states", headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/countries/<country_code>/states/<state_code>/cities')
def get_cities(country_code, state_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}/cities", headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- Helper functions to get names from stored IDs ------------------
def get_country_name(country_code):
    if not country_code:
        return None
    try:
        r = requests.get(f"{base_url}/countries/{country_code}", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('name')
    except:
        pass
    return None

def get_state_name(country_code, state_code):
    if not country_code or not state_code:
        return None
    try:
        r = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('name')
    except:
        pass
    return None

def get_city_name(country_code, state_code, city_id):
    if not country_code or not state_code or not city_id:
        return None
    try:
        r = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}/cities", headers=headers, timeout=10)
        if r.status_code == 200:
            cities = r.json()
            if isinstance(cities, list):
                for city in cities:
                    if str(city.get('id')) == str(city_id) or str(city.get('iso2')) == str(city_id) or city.get('name') == city_id:
                        return city.get('name')
    except Exception as e:
        app.logger.error("get_city_name error: %s", e)
    return None

# ----------------- View single user request ------------------
@admin_bp.route('/request/view/<int:request_id>')
def view_request(request_id):
    if 'user_id' not in session:
        flash("Please log in to access your account.", "warning")
        return redirect(url_for('auth.login_page'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM user_requests WHERE request_id=%s", (request_id,))
        request_data = cursor.fetchone()
        if not request_data:
            flash("Request not found.", "danger")
            return redirect(url_for('admin.dashboard'))

        cursor.execute("SELECT * FROM users WHERE user_id=%s", (request_data['user_id'],))
        user = cursor.fetchone()
        if not user:
            flash("User not found for this request.", "danger")
            return redirect(url_for('admin.dashboard'))

        country_name = get_country_name(user.get('country'))
        state_name = get_state_name(user.get('country'), user.get('state'))
        city_name = get_city_name(user.get('country'), user.get('state'), user.get('city'))

        roles = user.get('role') or ""
        if isinstance(roles, str):
            role_list = [r.strip().capitalize() for r in roles.split(',') if r.strip()]
        else:
            role_list = list(roles)

        donor_profile, recipient_profile = None, None
        if 'Donor' in role_list:
            cursor.execute("SELECT org_name, org_type, licience FROM donors_profile WHERE donor_id=%s", (user['user_id'],))
            donor_profile = cursor.fetchone()
        if 'Recipient' in role_list:
            cursor.execute("SELECT org_name, org_type, tax_proof FROM recipient_profile WHERE recipient_id=%s", (user['user_id'],))
            recipient_profile = cursor.fetchone()

        cursor.execute("SELECT * FROM user_proofs WHERE request_id=%s", (request_id,))
        proofs = cursor.fetchall()

        return render_template(
            'admin/view_requests.html',
            request_data=request_data,
            user=user,
            country_name=country_name or '',
            state_name=state_name or '',
            city_name=city_name or '',
            role=role_list,
            donor_profile=donor_profile,
            recipient_profile=recipient_profile,
            proofs=proofs
        )
    finally:
        cursor.close()
        conn.close()

# ---------------- APPROVE REQUEST (no email, only DB + notification) ----------------
@admin_bp.route("/approve_request/<int:request_id>", methods=["POST"])
def approve_request(request_id):
    if not admin_required():
        flash("Unauthorized access!", "danger")
        return redirect(url_for("auth.login_page"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT r.user_id, u.first_name, u.role
            FROM user_requests r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.request_id=%s
        """, (request_id,))
        row = cursor.fetchone()
        if not row:
            flash("Request or user not found.", "danger")
            return redirect(url_for("admin.dashboard"))

        user_id = row['user_id']
        first_name = row.get('first_name', '')
        roles_raw = row.get('role') or ""
        if isinstance(roles_raw, str):
            role_list = [r.strip().capitalize() for r in roles_raw.split(',') if r.strip()]
        else:
            role_list = list(roles_raw)

        cursor.execute("UPDATE user_requests SET status='Approved' WHERE request_id=%s", (request_id,))
        cursor.execute("UPDATE users SET status='Active' WHERE user_id=%s", (user_id,))

        # Optional: If donor profile exists, mark verified
        cursor.execute("UPDATE donors_profile SET status='Verified' WHERE donor_id=%s", (user_id,))

        # Insert notifications for all user's roles found (if both donor & recipient, create for both)
        notified_roles = []
        for role in role_list:
            if role in ('Donor', 'Recipient'):
                insert_notification(cursor, user_id, role, f"Hi {first_name}, your request has been approved by admin.", 'thank_you')
                notified_roles.append(role)
        # fallback: if no role found, insert as Donor (previous behavior)
        if not notified_roles:
            insert_notification(cursor, user_id, 'Donor', f"Hi {first_name}, your request has been approved by admin.", 'thank_you')

        db.commit()
        flash("Request approved and notifications inserted.", "success")
    except Exception as e:
        db.rollback()
        app.logger.error("Approval error: %s", e)
        flash("Failed to approve request!", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for("admin.dashboard"))

# ---------------- REJECT REQUEST (no email) ----------------
@admin_bp.route("/reject_request/<int:request_id>", methods=["POST"])
def reject_request(request_id):
    if not admin_required():
        flash("Unauthorized access!", "danger")
        return redirect(url_for("auth.login_page"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT r.user_id, u.first_name, u.role, r.message
            FROM user_requests r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.request_id=%s
        """, (request_id,))
        row = cursor.fetchone()
        if not row:
            flash("Request or user not found.", "danger")
            return redirect(url_for("admin.dashboard"))

        user_id = row['user_id']
        first_name = row.get('first_name', '')
        reason = row.get('message', 'No message')
        roles_raw = row.get('role') or ""
        if isinstance(roles_raw, str):
            role_list = [r.strip().capitalize() for r in roles_raw.split(',') if r.strip()]
        else:
            role_list = list(roles_raw)

        cursor.execute("UPDATE user_requests SET status='Rejected' WHERE request_id=%s", (request_id,))

        # Insert notification(s)
        notified = False
        for role in role_list:
            if role in ('Donor', 'Recipient'):
                insert_notification(cursor, user_id, role, f"Hi {first_name}, your request has been rejected. Reason: {reason}", 'alert')
                notified = True
        if not notified:
            insert_notification(cursor, user_id, 'Donor', f"Hi {first_name}, your request has been rejected. Reason: {reason}", 'alert')

        db.commit()
        flash("Request rejected and notifications inserted.", "info")
    except Exception as e:
        db.rollback()
        app.logger.error("Reject error: %s", e)
        flash("Failed to reject request!", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for("admin.dashboard"))

# ---------------- Donors List (unchanged) ----------------
@admin_bp.route("/donors")
def donors():
    if not admin_required():
        flash("Unauthorized access!", "danger")
        return redirect(url_for("auth.login"))

    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Total donors
    cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role LIKE '%Donor%'")
    total_count = cursor.fetchone()['total']
    total_pages = (total_count // per_page) + (1 if total_count % per_page > 0 else 0)

    # Fetch current page donors
    cursor.execute(
        "SELECT * FROM users WHERE role LIKE '%Donor%' ORDER BY user_id DESC LIMIT %s OFFSET %s",
        (per_page, offset)
    )
    donors = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin/donors_list.html",
        donors=donors,
        page=page,
        total_pages=total_pages
    )

# ---------------- Block / Unblock Donor (now only DB + notification) ----------------
@admin_bp.route("/donors/<int:user_id>/toggle", methods=["POST"])
def toggle_donor(user_id):
    page = request.args.get('page', 1)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get donor info
    cursor.execute("SELECT * FROM users WHERE user_id=%s AND role LIKE '%Donor%'", (user_id,))
    donor = cursor.fetchone()
    if not donor:
        cursor.close()
        conn.close()
        flash("Donor not found!", "danger")
        return redirect(url_for("admin.donors", page=page))

    # Toggle block/unblock
    new_status = 1 if donor["is_deleted"] == 0 else 0
    cursor.execute("UPDATE users SET is_deleted=%s WHERE user_id=%s", (new_status, user_id))
    conn.commit()  # Commit **before notification**

    # Send notification
    if new_status == 1:
        message = f"Dear {donor['first_name']}, your donor account has been blocked by the Admin."
        ntype = "alert"
    else:
        message = f"Dear {donor['first_name']}, your donor account has been unblocked."
        ntype = "info"

    try:
        insert_notification(cursor, donor['user_id'], 'Donor', message, ntype)
        conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Notification failed: {e}")

    cursor.close()
    conn.close()

    flash(f"Donor {donor['first_name']} {donor['last_name']} has been {'blocked' if new_status == 1 else 'unblocked'}.", "success")
    return redirect(url_for("admin.donors", page=page))

# ---------------- Donor View (unchanged) ----------------
@admin_bp.route("/donor_view/<int:user_id>")
def donor_view(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT u.user_id, u.user_profile, u.first_name, u.last_name, u.email, u.address,
               u.latitude, u.longitude,
               d.donor_profile_id, d.licience, d.org_name, d.org_type, 
               d.description, d.status, d.avg_rating, d.total_food_saved
        FROM users u
        JOIN donors_profile d ON u.user_id = d.donor_id
        WHERE u.user_id = %s AND u.is_deleted = 0 AND d.is_deleted = 0
    """
    cursor.execute(query, (user_id,))
    donor = cursor.fetchone()
    if not donor:
        cursor.close()
        conn.close()
        flash("Donor profile not found", "danger")
        return redirect(url_for("admin.donors"))
    
    cursor.execute("""
        SELECT DATE(prepared_at) AS day, SUM(quantity) AS total_quantity
        FROM donations
        WHERE donor_id=%s
        GROUP BY DATE(prepared_at)
        ORDER BY day ASC
    """, (user_id,))
    food_saved_timeline = cursor.fetchall()
    food_saved_labels = [row["day"].strftime("%Y-%m-%d") for row in food_saved_timeline]
    food_saved_counts = [row["total_quantity"] if row["total_quantity"] else 0 for row in food_saved_timeline]

    cursor.execute("""
        SELECT food_type, COUNT(*) AS count
        FROM donations
        WHERE donor_id=%s
        GROUP BY food_type
    """, (user_id,))
    food_type_data = cursor.fetchall()
    food_labels = [row["food_type"] for row in food_type_data]
    food_counts = [row["count"] for row in food_type_data]

    cursor.execute("""
        SELECT DATE(prepared_at) as day, COUNT(*) as count
        FROM donations
        WHERE donor_id=%s
        GROUP BY DATE(prepared_at)
        ORDER BY day ASC
    """, (user_id,))
    donation_timeline = cursor.fetchall()
    donation_labels = [row["day"].strftime("%Y-%m-%d") for row in donation_timeline]
    donation_counts = [row["count"] for row in donation_timeline]

    cursor.execute("""
        SELECT DATE(d.prepared_at) AS day, AVG(p.avg_rating) AS avg_rating
        FROM donations d
        JOIN donors_profile p
        WHERE d.donor_id=%s AND p.avg_rating IS NOT NULL
        GROUP BY DATE(d.prepared_at)
        ORDER BY day ASC
    """, (user_id,))
    rating_data = cursor.fetchall()
    rating_labels = [row["day"].strftime("%Y-%m-%d") for row in rating_data]
    rating_values = [float(row["avg_rating"]) if row["avg_rating"] else 0 for row in rating_data]

    cursor.execute("SELECT * FROM recipient_profile WHERE recipient_id=%s AND is_deleted=0", (user_id,))
    recipient = cursor.fetchone()

    request_labels, request_counts, status_labels, status_counts, recipient_rating = [], [], [], [], 0
    if recipient:
        cursor.execute("""
          SELECT DATE(created_at) AS day, COUNT(*) AS count
    FROM request_to
    WHERE recipient_id = %s
    GROUP BY DATE(created_at)
    ORDER BY day ASC;
        """, (user_id,))
        requests_timeline = cursor.fetchall()
        request_labels = [row["day"].strftime("%Y-%m-%d") for row in requests_timeline]
        request_counts = [row["count"] for row in requests_timeline]

        cursor.execute("""
             SELECT status, COUNT(*) AS count
                FROM request_to
                WHERE recipient_id = %s
                GROUP BY status
        """, (user_id,))
        status_data = cursor.fetchall()
        status_labels = [row["status"] for row in status_data]
        status_counts = [row["count"] for row in status_data]

        recipient_rating = recipient.get("avg_rating", 0)
        
        # Example: Calculate weekly progress for donor
    cursor.execute("""
        SELECT SUM(quantity) AS total_saved
        FROM request_to
        WHERE donor_id=%s AND WEEK(created_at)=WEEK(CURDATE())
    """, (user_id,))
    result = cursor.fetchone()
    total_saved = result['total_saved'] or 0

    # Suppose your weekly target is 100 units
    weekly_target = 100
    weekly_progress = int((total_saved / weekly_target) * 100)

    cursor.close()
    conn.close()

    return render_template(
        "admin/view_donor.html",
        donor=donor,
        food_labels=food_labels, food_counts=food_counts, food_saved_counts=food_saved_counts,
        donation_labels=donation_labels, donation_counts=donation_counts, food_saved_labels=food_saved_labels,
        rating_labels=rating_labels, rating_values=rating_values,
        request_labels=request_labels, request_counts=request_counts,
        status_labels=status_labels, status_counts=status_counts,
        recipient_rating=recipient_rating,
        recipient=recipient,
        weekly_progress=weekly_progress,
        weekly_target=weekly_target
    )

# ---------------- RECIPIENTS LIST (new) ----------------
@admin_bp.route("/recipients")
def recipients():
    if not admin_required():
        flash("Unauthorized access!", "danger")
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    page = request.args.get("page", 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    # Total recipients count
    cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role ='Recipient'")
    total_count = cursor.fetchone()['total']
    total_pages = (total_count + per_page - 1) // per_page

    # Fetch recipients for current page
    cursor.execute("""
        SELECT *
        FROM users 
        WHERE role='Recipient'
        ORDER BY user_id DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    recipients = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin/recipients_list.html",
        recipients=recipients,
        page=page,
        total_pages=total_pages
    )

# ---------------- Block / Unblock Recipient (new) ----------------
@admin_bp.route("/recipients/<int:user_id>/toggle", methods=["POST"])
def toggle_recipient(user_id):
    page = request.args.get('page', 1)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get recipient info
    cursor.execute("SELECT * FROM users WHERE user_id=%s AND role='Recipient'", (user_id,))
    rec = cursor.fetchone()
    if not rec:
        cursor.close()
        conn.close()
        flash("Recipient not found!", "danger")
        return redirect(url_for("admin.recipients", page=page))

    # Toggle is_deleted status
    new_status = 1 if rec["is_deleted"] == 0 else 0
    cursor.execute("UPDATE users SET is_deleted=%s WHERE user_id=%s", (new_status, user_id))
    conn.commit()  # Commit **before notification**

    # Notification
    if new_status == 1:
        message = f"Dear {rec['first_name']}, your recipient account has been blocked by the Admin."
        ntype = "alert"
    else:
        message = f"Dear {rec['first_name']}, your recipient account has been unblocked. You can now access recipient features."
        ntype = "info"

    try:
        insert_notification(cursor, rec['user_id'], 'Recipient', message, ntype)
        conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Notification failed: {e}")

    cursor.close()
    conn.close()

    flash(f"Recipient {rec['first_name']} {rec['last_name']} has been {'blocked' if new_status == 1 else 'unblocked'}.", "success")
    return redirect(url_for("admin.recipients", page=page))

# ---------------- Recipient View (new) ----------------
@admin_bp.route("/recipient_view/<int:user_id>")
def recipient_view(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT u.user_id, u.user_profile, u.first_name, u.last_name, u.email, u.address,
               u.latitude, u.longitude,
               r.recipient_profile_id, r.org_name, r.org_type, r.tax_proof, r.description,
               r.status, r.avg_rating
        FROM users u
        JOIN recipient_profile r ON u.user_id = r.recipient_id
        WHERE u.user_id = %s AND u.is_deleted = 0 AND r.is_deleted = 0
    """, (user_id,))
    recipient = cursor.fetchone()
    if not recipient:
        cursor.close()
        conn.close()
        flash("Recipient profile not found", "danger")
        return redirect(url_for("admin.recipients"))

    # Requests per day for this recipient (timeline)
    cursor.execute("""
        SELECT DATE(created_at) AS day, COUNT(*) AS count
    FROM request_to
    WHERE recipient_id = %s
    GROUP BY DATE(created_at)
    ORDER BY day ASC
    """, (user_id,))
    requests_timeline = cursor.fetchall()
    request_labels = [row["day"].strftime("%Y-%m-%d") for row in requests_timeline]
    request_counts = [row["count"] for row in requests_timeline]

    # Requests by status
    cursor.execute("""
        SELECT status, COUNT(*) AS count
    FROM request_to
    WHERE recipient_id=%s
    GROUP BY status
    """, (user_id,))
    status_data = cursor.fetchall()
    status_labels = [row["status"] for row in status_data]
    status_counts = [row["count"] for row in status_data]
    
    # Requests by food type
    cursor.execute("""
       SELECT food_type, COUNT(*) AS count
    FROM request_to
    WHERE recipient_id=%s
    GROUP BY food_type
    """, (user_id,))
    food_data = cursor.fetchall()
    food_labels = [row["food_type"] for row in food_data]
    food_counts = [row["count"] for row in food_data]

    cursor.close()
    conn.close()

    return render_template(
        "admin/view_recipient.html",
        recipient=recipient,
        request_labels=request_labels,
        request_counts=request_counts,
        status_labels=status_labels,
        status_counts=status_counts,
        food_labels=food_labels,
        food_counts=food_counts
    )

##################################################################
# --------------------------- REQUESTTS--------------------
##################################################################
@admin_bp.route("/admin/requests/user/<int:user_id>")
def view_user_requests(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # User info
    cursor.execute("SELECT  email, first_name, last_name FROM users WHERE user_id=%s", (user_id,))
    user_info = cursor.fetchone()

    # Login requests
    cursor.execute("""
        SELECT request_id, message, status, created_at
        FROM user_requests
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (user_id,))
    login_requests = cursor.fetchall()

    # Food requests
    cursor.execute("""
        SELECT request_id, food_type, quantity, address, status, created_at
        FROM request_to
        WHERE recipient_id=%s
        ORDER BY created_at DESC
    """, (user_id,))
    food_requests = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("admin/user_request.html", user=user_info,
                           login_requests=login_requests, food_requests=food_requests)

###########################################################
#                    NOtifications 
###########################################################
# -----------login request-------------
def fetch_admin_login_requests(limit=5):
    """Fetches pending user registration requests for the admin."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT ur.request_id, ur.message, ur.created_at, u.first_name, u.last_name, ur.user_id
            FROM user_requests ur
            JOIN users u ON ur.user_id = u.user_id
            WHERE ur.status='Pending'
            ORDER BY ur.created_at DESC
            LIMIT %s
        """, (limit,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
        
def fetch_admin_food_requests(limit=5):
    """Fetches pending food requests for the admin."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT r.request_id, r.recipient_id,
                   CONCAT(u.first_name, ' requested ', r.quantity, ' of ', r.food_type) AS message,
                   r.created_at, u.first_name, u.last_name
            FROM request_to r
            JOIN users u ON r.recipient_id = u.user_id
            WHERE r.status='Pending' AND r.is_deleted=0
            ORDER BY r.created_at DESC
            LIMIT %st
        """, (limit,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

# @admin_bp.app_context_processor
# def inject_admin_notifications():
#     if 'user_id' in session and 'Admin' in session.get('role', []):
#         login_reqs = fetch_admin_login_requests(5)
#         food_reqs = fetch_admin_food_requests(5)
        
#         # Combine and sort all requests by creation date
#         all_requests = sorted(login_reqs + food_reqs, key=lambda x: x['created_at'], reverse=True)
        
#         pending_count = len(all_requests)

#         return dict(
#             admin_pending_requests=all_requests,
#             admin_pending_count=pending_count
#         )
#     return {}
# ---------------------Food requests----------------
@admin_bp.route('/food_details/<int:request_id>')
def food_details(request_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT 
            fr.request_id, 
            fr.quantity, 
            fr.address, 
            fr.food_type, 
            fr.status,
            fr.food,
            r.org_name
        FROM request_to fr 
        JOIN recipient_profile r ON r.recipient_id = fr.recipient_id  
        WHERE fr.request_id=%s
    """, (request_id,))
    food = cursor.fetchone()
    conn.close()
    return render_template('admin/food_details.html', food=food)