# recipient.py
from flask import (Blueprint, render_template, session, redirect,url_for, flash, request, jsonify, current_app)
from functools import wraps
import mysql.connector
import math
from math import ceil
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests
from math import radians, cos, sin, asin, sqrt
from math import radians, cos, sin, sqrt, atan2
recipient_bp = Blueprint( "recipient",__name__,template_folder="../templates/recipient",url_prefix="/recipient")

# ---------------- DB Connection ----------------
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="7842557971",
        database="food_db",
        autocommit=False
    )
# -----------------allowed file------------------------------
def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'pdf'})

# ---------------- Role protection ----------------
def recipient_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access your account.", "warning")
            return redirect(url_for("auth.login_page"))

        # Get roles from session
        roles = session.get("role", [])

        # Ensure roles is always a list
        if isinstance(roles, str):
            roles = [roles]
        elif isinstance(roles, set):
            roles = list(roles)  # convert set to list just in case

        # Save back to session to prevent serialization issues
        session["role"] = roles

        # Check if recipient role exists
        if "Recipient" not in roles:
            flash("Access denied", "danger")
            return redirect(url_for("auth.login_page"))

        return f(*args, **kwargs)
    return wrapper

# ====================== DASHBOARD ======================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * (2*math.atan2(math.sqrt(a), math.sqrt(1-a)))

#======================nearby ==================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c
# ---------------- Get user location dynamically ----------------
def get_user_location(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id=%s", (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user and user['latitude'] is not None and user['longitude'] is not None:
        return user['latitude'], user['longitude']
    return None, None
# ---------------- Get nearby donors ----------------
def get_nearby_donors(user_lat, user_lon, max_distance=50):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, first_name, latitude, longitude FROM users")
    donors = cursor.fetchall()
    conn.close()

    nearby = []
    for donor in donors:
        if donor['latitude'] is None or donor['longitude'] is None:
            continue
        distance = haversine(user_lat, user_lon, donor['latitude'], donor['longitude'])
        if distance <= max_distance:
            nearby.append(donor)
    return nearby

@recipient_bp.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # --- Small helper to restructure results ---
    def restructure(rows, period_key="period"):
        data = {}
        for row in rows:
            period = str(row[period_key])
            if period not in data:
                data[period] = {"approved": 0, "rejected": 0, "pending": 0}
            data[period][row["status"].lower()] = row["total"]

        return {
            "labels": list(data.keys()),
            "approved": [v["approved"] for v in data.values()],
            "rejected": [v["rejected"] for v in data.values()],
            "pending":  [v["pending"] for v in data.values()],
        }

    # 1️⃣ Total Approved Requests
    cursor.execute("""
        SELECT COUNT(*) as total_requests 
        FROM request_to 
        WHERE recipient_id=%s AND status='Approved'
    """, (user_id,))
    total_requests = cursor.fetchone()["total_requests"]

    # 2️⃣ Available Donations
    cursor.execute("SELECT COUNT(*) as available_food FROM donations WHERE status='OPEN'")
    available_food = cursor.fetchone()["available_food"]

    # 3️⃣ Total Food Requests
    cursor.execute("SELECT COUNT(*) as total_food_requests FROM request_to WHERE recipient_id = %s", (user_id,))
    total_food_requests = cursor.fetchone()["total_food_requests"]

    # 4️⃣ Recipient Location
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id=%s", (user_id,))
    recipient = cursor.fetchone()
    rec_lat, rec_lon = recipient["latitude"], recipient["longitude"]

    # 5️⃣ Nearby Donors
    cursor.execute("SELECT * FROM users WHERE role='Donor' AND status='Active'")
    donors = cursor.fetchall()
    nearby_donors = []
    for d in donors:
        if d["latitude"] and d["longitude"]:
            distance = haversine(rec_lat, rec_lon, d["latitude"], d["longitude"])
            d["distance_km"] = round(distance, 2)
            if distance <= 50:
                nearby_donors.append(d)
        else:
            d["distance_km"] = None
    near_donors_count = len(nearby_donors)

    # 📈 Food Requests Trend
    cursor.execute("""
        SELECT DATE(created_at) as req_date, COUNT(*) as total 
        FROM request_to 
        WHERE recipient_id=%s 
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
    """, (user_id,))
    food_requests = cursor.fetchall()
    request_labels = [str(row["req_date"]) for row in food_requests]
    request_values = [row["total"] for row in food_requests]

    # 🥗 Food Categories Pie
    cursor.execute("""
        SELECT food_type, COUNT(*) AS total_requests
        FROM request_to
        WHERE recipient_id = %s AND is_deleted = 0
        GROUP BY food_type
    """, (user_id,))
    food_categories = cursor.fetchall()
    categories_labels = [row["food_type"] for row in food_categories]
    categories_values = [row["total_requests"] for row in food_categories]

    # 🍲 Latest Donations
    cursor.execute("""
        SELECT d.donation_id, d.description, d.food_type, d.quantity, u.first_name, u.last_name
        FROM donations d
        JOIN users u ON d.donor_id=u.user_id
        WHERE d.status='OPEN'
        ORDER BY d.prepared_at DESC 
        LIMIT 5
    """)
    latest_donations = cursor.fetchall()

    # 📊 Status per Day
    cursor.execute("""
        SELECT DATE(created_at) AS period, status, COUNT(*) AS total
        FROM request_to
        WHERE recipient_id = %s
        GROUP BY DATE(created_at), status
        ORDER BY period ASC;
    """, (user_id,))
    status_daily = restructure(cursor.fetchall())

    # 📊 Status per Week
    cursor.execute("""
        SELECT YEARWEEK(created_at, 1) AS period, status, COUNT(*) AS total
        FROM request_to
        WHERE recipient_id = %s
        GROUP BY YEARWEEK(created_at, 1), status
        ORDER BY period ASC;
    """, (user_id,))
    status_weekly = restructure(cursor.fetchall())

    # 📊 Status per Month
    cursor.execute("""
        SELECT DATE_FORMAT(created_at, '%Y-%m') AS period, status, COUNT(*) AS total
        FROM request_to
        WHERE recipient_id = %s
        GROUP BY DATE_FORMAT(created_at, '%Y-%m'), status
        ORDER BY period ASC;
    """, (user_id,))
    status_monthly = restructure(cursor.fetchall())

    # ✅ Food Taken (Approved only)
    cursor.execute("""
        SELECT DATE(created_at) AS day, SUM(quantity) AS total_food
        FROM request_to
        WHERE recipient_id = %s AND status = 'Approved'
        GROUP BY DATE(created_at)
        ORDER BY day
    """, (user_id,))
    rows = cursor.fetchall()
    food_taken_labels = [row["day"].strftime("%Y-%m-%d") for row in rows]
    food_taken_values = [row["total_food"] for row in rows]

    cursor.close()
    conn.close()

    return render_template(
        "recipient/dashboard.html",
        total_requests=total_requests,
        available_food=available_food,
        total_food_requests=total_food_requests,
        request_labels=request_labels,
        request_values=request_values,
        categories_labels=categories_labels,
        categories_values=categories_values,
        latest_donations=latest_donations,
        donors=donors,
        nearby_donors=nearby_donors,
        food_taken_labels=food_taken_labels,
        food_taken_values=food_taken_values,
        near_donors_count=near_donors_count,
        status_daily=status_daily,
        status_weekly=status_weekly,
        status_monthly=status_monthly
    )


#=========== near donor =====================
@recipient_bp.route('/nearby_donors')
def nearby_donors_page():
    user_id = session.get('user_id', 1)
    user_lat, user_lon = get_user_location(user_id)
    if user_lat is None:
        donors = []
    else:
        donors = get_nearby_donors(user_lat, user_lon)

    return render_template('recipient/nearby_donor.html', donors=donors)


# ---------------- NEW FOOD REQUEST ----------------
def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two lat/lon points"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

@recipient_bp.route("/donations")
def available_donations():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    page = request.args.get("page", 1, type=int)
    per_page = 9   # donations per page
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        UPDATE donations
        SET status = 'EXPIRED'
        WHERE status = 'OPEN' AND expired_at IS NOT NULL AND expired_at < NOW()
    """)
    conn.commit()
    # recipient location
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id=%s", (user_id,))
    recipient = cursor.fetchone()
    rec_lat, rec_lon = recipient["latitude"], recipient["longitude"]

    # total donations count
    cursor.execute("SELECT COUNT(*) AS total FROM donations WHERE status='OPEN'")
    total_donations = cursor.fetchone()["total"]

    # fetch paginated donations with donor info
    cursor.execute("""
        SELECT d.donation_id, d.description, d.food_type, d.quantity, d.status, d.food_img, 
               d.prepared_at, u.first_name, u.last_name, u.latitude, u.longitude
        FROM donations d
        JOIN users u ON d.donor_id=u.user_id
        WHERE d.status='OPEN'
        ORDER BY d.prepared_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    donations = cursor.fetchall()

    # calculate distance for each donation
    for d in donations:
        if d["latitude"] and d["longitude"] and rec_lat and rec_lon:
            d["distance_km"] = round(haversine(rec_lat, rec_lon, d["latitude"], d["longitude"]), 2)
        else:
            d["distance_km"] = None

    cursor.close()
    conn.close()

    total_pages = (total_donations + per_page - 1) // per_page  # ceil division

    return render_template(
        "recipient/available_donations.html",
        latest_donations=donations,
        recipient=recipient,
        page=page,
        total_pages=total_pages
    )

# ========================= view single donation ==============
def haversine(lat1, lon1, lat2, lon2):
    # convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    
    # haversine formula
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    km = 6371 * c
    return round(km, 2)

@recipient_bp.route('/donation/<int:donation_id>')
def view_donation(donation_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    
    page = request.args.get('page', 1, type=int)
    per_page = 4
    offset = (page - 1) * per_page
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch donation
    cursor.execute("SELECT * FROM donations WHERE donation_id = %s", (donation_id,))
    donation = cursor.fetchone()
    if not donation:
        cursor.close()
        conn.close()
        return "Donation not found", 404

    # Donor info
    cursor.execute("SELECT first_name, last_name, latitude, longitude FROM users WHERE user_id = %s", (donation['donor_id'],))
    donor = cursor.fetchone()

    # Recipient info
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id = %s", (user_id,))
    recipient = cursor.fetchone()

    # Calculate distance
    if donor['latitude'] and donor['longitude'] and recipient['latitude'] and recipient['longitude']:
        distance_km = haversine(recipient['latitude'], recipient['longitude'], donor['latitude'], donor['longitude'])
    else:
        distance_km = None

    cursor.close()
    conn.close()

    return render_template(
        "recipient/donation_view.html",
        donation=donation,
        user=donor,
        recipient=recipient,
        distance_km=distance_km
    )
# =================== search food =====================
@recipient_bp.route('/donations/search')
def search_donations():
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 6  # Donations per page

    if not query:
        flash("Please enter a search term.", "warning")
        return redirect(url_for('recipient.available_donations'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Count total matching donations
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM donations d
            JOIN users u ON d.donor_id = u.user_id
            WHERE d.food_type LIKE %s OR d.food LIKE %s OR d.description LIKE %s OR 
                  CONCAT(u.first_name, ' ', u.last_name) LIKE %s
        """, (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
        total_results = cursor.fetchone()['total']

        # Pagination offset
        offset = (page - 1) * per_page

        # Fetch donations for current page
        cursor.execute("""
            SELECT d.*, u.first_name, u.last_name, u.latitude, u.longitude
            FROM donations d
            JOIN users u ON d.donor_id = u.user_id
            WHERE d.food_type LIKE %s OR d.food LIKE %s OR d.description LIKE %s OR 
                  CONCAT(u.first_name, ' ', u.last_name) LIKE %s
            ORDER BY d.prepared_at DESC
            LIMIT %s OFFSET %s
        """, (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%', per_page, offset))
        results = cursor.fetchall()

        total_pages = ceil(total_results / per_page)

    except Exception as e:
        flash(f"Error searching donations: {e}", "danger")
        results = []
        total_pages = 0

    finally:
        cursor.close()
        conn.close()

    return render_template('recipient/search_result.html', donations=results, query=query, page=page, total_pages=total_pages)

# ====================== Food Requests ======================
# ---------------- My Requests Page ----------------
@recipient_bp.route('/my_requests')
def my_requests():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login_page'))

    page = request.args.get('page', 1, type=int)
    per_page = 8
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Recipient details
    cursor.execute("SELECT latitude, longitude, address FROM users WHERE user_id=%s", (user_id,))
    recipient = cursor.fetchone()

    # Recipient requests (from request_to table)
    cursor.execute("""
        SELECT r.*, u.first_name, u.last_name, d.food_type AS donation_food_type, d.quantity AS donation_quantity
        FROM request_to r
        LEFT JOIN users u ON r.recipient_id = u.user_id
        LEFT JOIN donations d ON r.donation_id = d.donation_id
        WHERE r.recipient_id = %s
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
    """, (user_id, per_page, offset))
    requests_list = cursor.fetchall()

    # Total pages
    cursor.execute("SELECT COUNT(*) as total FROM request_to WHERE recipient_id=%s", (user_id,))
    total_requests = cursor.fetchone()['total']
    total_pages = (total_requests + per_page - 1) // per_page

    cursor.close()
    conn.close()

    return render_template(
        'my_requests.html',
        requests=requests_list,
        recipient=recipient,
        per_page=per_page,
        page=page,
        total_pages=total_pages
    )

# ---------------- New Request ----------------
@recipient_bp.route("/request_food/<int:donation_id>", methods=["GET", "POST"])
def request_food(donation_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch donation details
    cursor.execute("""
        SELECT donor_id, food_type, quantity, latitude, longitude, food 
        FROM donations 
        WHERE donation_id=%s AND status='OPEN'
    """, (donation_id,))
    donation = cursor.fetchone()

    if not donation:
        flash("Donation not available.", "error")
        return redirect(url_for("recipient.dashboard"))

    if request.method == "POST":
        # Get recipient-provided address
        address = request.form.get("address")
        if not address:
            flash("Please provide an address.", "error")
            return redirect(url_for("recipient.request_food", donation_id=donation_id))

        # Insert request
        cursor.execute("""
            INSERT INTO request_to 
            (recipient_id, donor_id, donation_id, food_type, quantity, address, latitude, longitude, food, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
        """, (user_id, donation["donor_id"], donation_id, donation["food_type"], donation["quantity"],
              address, donation["latitude"], donation["longitude"], donation["food"]))
        conn.commit()

        # After inserting the request and getting request_id
        request_id = cursor.lastrowid

        # Insert notification for donor
        cursor.execute("""
            INSERT INTO notifications 
            (reference_user_id, reference_request_id, role, message, type, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (donation["donor_id"], request_id, 'Donor', 'New food request received.', 'info', 'Pending'))
        conn.commit()


        cursor.close()
        conn.close()
        flash("Food request submitted!", "success")
        return redirect(url_for("recipient.dashboard"))

    cursor.close()
    conn.close()
    return render_template("recipient/request_food.html", donation=donation)

# --------------------delete ----------------------
@recipient_bp.route("/requests/<int:request_id>/delete", methods=["POST"])
def delete_request(request_id):
    if 'user_id' not in session:
        flash("Please login first", "danger")
        return redirect(url_for("auth.login_page"))

    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Ensure request belongs to this user
        cursor.execute("SELECT * FROM requests_to WHERE request_id=%s AND recipient_id=%s AND is_deleted=0", 
                       (request_id, user_id))
        req = cursor.fetchone()

        if not req:
            flash("Request not found or already deleted.", "danger")
            return redirect(url_for("recipient.my_requests"))

        # Soft delete (mark as deleted + timestamp)
        cursor.execute("""
            UPDATE requests_to
            SET is_deleted = 1 
            WHERE request_id = %s
        """, (request_id,))
        conn.commit()

        flash("Request deleted successfully.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error deleting request: {str(e)}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("recipient.my_requests"))

# ====================== Profile ======================
@recipient_bp.route('/profile')
def profile():
    """View complete recipient profile"""
    user_id = session.get('user_id')
    if not user_id:
        flash("Please login first!", "warning")
        return redirect(url_for('auth.login_page'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # ---------------- FETCH USER ----------------
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for('auth.login_page'))
        print(user)
        # ---------------- PARSE ROLES ----------------
        roles_raw = user.get('role') or ""
        if isinstance(roles_raw, str):
            role_list = [r.strip().capitalize() for r in roles_raw.split(",") if r.strip()]
        elif isinstance(roles_raw, (list, set)):
            role_list = [str(r).strip().capitalize() for r in roles_raw if r and str(r).strip()]
        else:
            role_list = []

        role_display = ", ".join(role_list)
        print(role_display)
        # ---------------- LOCATION NAMES ----------------
        country_name = get_country_name(user.get('country')) if user.get('country') else ''
        state_name = get_state_name(user.get('country'), user.get('state')) if user.get('state') else ''
        city_name = get_city_name(user.get('country'), user.get('state'), user.get('city')) if user.get('city') else ''

        # ---------------- FETCH PROFILES ----------------
        donor_profile, recipient_profile = None, None

        # Donor profile (optional)
        if 'Donor' in role_list:
            cursor.execute("SELECT * FROM donors_profile WHERE donor_id=%s", (user_id,))
            donor_profile = cursor.fetchone()

        # Recipient profile
        if 'Recipient' in role_list:
            cursor.execute("""
                SELECT recipient_profile_id, org_name, org_type, org_profile, description,
                       tax_proof, food_safety_licience, address_proof, org_capacity, avg_rating
                FROM recipient_profile
                WHERE recipient_id=%s AND (is_deleted IS NULL OR is_deleted=0)
            """, (user_id,))
            recipient_profile = cursor.fetchone()

        # ---------------- LATEST REQUEST STATUS ----------------
        cursor.execute("""
            SELECT status FROM user_requests
            WHERE user_id=%s 
            ORDER BY created_at DESC 
            LIMIT 1
        """, (user_id,))
        request_status_row = cursor.fetchone()
        request_status = request_status_row['status'] if request_status_row else "Pending"

        return render_template(
            'recipient/profile.html',
            user=user,
            role_display=role_display,
            donor_profile=donor_profile,
            recipient_profile=recipient_profile,
            country_name=country_name,
            state_name=state_name,
            city_name=city_name,
            request_status=request_status
        )

    finally:
        cursor.close()
        conn.close()



# -----------update profile--------------------
api_id = "bkgwS1F2bFhGOHVBeUJLUUtiZEZiemtydmtuMk8xbGV1Nlo4UEVoYQ=="
base_url = 'https://api.countrystatecity.in/v1'
headers = {'X-CSCAPI-KEY': api_id}

# ------------ API ROUTES ------------
@recipient_bp.route('/api/countries')
def get_countries():
    try:
        response = requests.get(f"{base_url}/countries", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@recipient_bp.route('/api/countries/<country_code>/states')
def get_states(country_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@recipient_bp.route('/api/countries/<country_code>/states/<state_code>/cities')
def get_cities(country_code, state_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}/cities", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------ API HELPERS ------------
def get_country_name(country_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}", headers=headers)
        if response.status_code == 200:
            return response.json().get('name', 'Unknown Country')
        return 'Unknown Country'
    except:
        return 'Unknown Country'

def get_state_name(country_code, state_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}", headers=headers)
        if response.status_code == 200:
            return response.json().get('name', 'Unknown State')
        return 'Unknown State'
    except:
        return 'Unknown State'

def get_city_name(country_code, state_code, city_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states/{state_code}/cities", headers=headers)
        if response.status_code == 200:
            cities = response.json()
            if isinstance(cities, list):
                for city in cities:
                    if (str(city.get('id')) == str(city_code) or 
                        str(city.get('iso2')) == str(city_code) or 
                        city.get('name') == city_code):
                        return city.get('name', 'Unknown City')
            return 'Unknown City'
        return 'Unknown City'
    except Exception as e:
        print(f"Exception in get_city_name: {e}")
        return 'Unknown City'
#####################################################################
@recipient_bp.route("/update_profile", methods=["GET", "POST"])
def update_profile():
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first!", "warning")
        return redirect(url_for("auth.login_page"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    def get_form_or_existing(form, field_name, existing_value, default=None):
        value = form.get(field_name)
        if value and value.strip() != "":
            return value.strip()
        elif existing_value is not None:
            return existing_value
        else:
            return default

    try:
        # ---------------- FETCH USER ----------------
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("User not found!", "danger")
            return redirect(url_for("auth.login_page"))

        # ---------------- DETERMINE ROLES ----------------
        roles_raw = user.get("role", "")
        if isinstance(roles_raw, str):
            roles = [r.strip().capitalize() for r in roles_raw.split(",") if r.strip()]
        elif isinstance(roles_raw, (list, set)):
            roles = [str(r).strip().capitalize() for r in roles_raw if r and str(r).strip()]
        else:
            roles = []

        # ---------------- FETCH EXISTING PROFILES ----------------
        donor_profile, recipient_profile = None, None
        if "Donor" in roles:
            cursor.execute("SELECT * FROM donors_profile WHERE donor_id=%s", (user_id,))
            donor_profile = cursor.fetchone()
        if "Recipient" in roles:
            cursor.execute("SELECT * FROM recipient_profile WHERE recipient_id=%s", (user_id,))
            recipient_profile = cursor.fetchone()

        # ---------------- LOCATION NAMES ----------------
        country_name = get_country_name(user.get('country')) if user.get('country') else ''
        state_name = get_state_name(user.get('country'), user.get('state')) if user.get('state') else ''
        city_name = user.get('city') or ''

        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(upload_folder, exist_ok=True)

        if request.method == "POST":
            # ---------------- BASIC USER FIELDS ----------------
            firstname = get_form_or_existing(request.form, "first_name", user.get("first_name"), "")
            lastname = get_form_or_existing(request.form, "last_name", user.get("last_name"), "")
            phone = get_form_or_existing(request.form, "phone", user.get("phone"), "")
            address = get_form_or_existing(request.form, "address", user.get("address"), "")
            zipcode = get_form_or_existing(request.form, "zip_code", user.get("zip_code"), "")
            country_id = get_form_or_existing(request.form, "country_code", user.get("country"), "")
            state_id = get_form_or_existing(request.form, "state_code", user.get("state"), "")
            city_code = request.form.get("city_id", "").strip()
            if city_code:
                city_name = get_city_name(country_id, state_id, city_code)
            else:
                city_name = user.get("city") or ""
            latitude = request.form.get("latitude") or user.get("latitude")
            longitude = request.form.get("longitude") or user.get("longitude")

            # ---------------- PASSWORD ----------------
            old_password = request.form.get("old_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            if old_password:
                if not check_password_hash(user["password"], old_password):
                    flash("Old password is incorrect!", "danger")
                    return redirect(url_for("recipient.update_profile"))
                if new_password != confirm_password:
                    flash("New passwords do not match!", "danger")
                    return redirect(url_for("recipient.update_profile"))
                hashed_password = generate_password_hash(new_password)
            else:
                hashed_password = user["password"]

            # ---------------- USER PROFILE PHOTO ----------------
            profile_photo_file = request.files.get("profile_photo")
            if profile_photo_file and profile_photo_file.filename != "" and allowed_file(profile_photo_file.filename):
                user_profile_filename = secure_filename(profile_photo_file.filename)
                profile_photo_file.save(os.path.join(upload_folder, user_profile_filename))
            else:
                user_profile_filename = user.get("user_profile")  # keep existing

            # ---------------- UPDATE USERS TABLE ----------------
            cursor.execute("""
                UPDATE users
                SET user_profile=%s, first_name=%s, last_name=%s, password=%s,
                    address=%s, zip_code=%s, country=%s, state=%s, city=%s,
                    phone=%s, latitude=%s, longitude=%s
                WHERE user_id=%s
            """, (user_profile_filename, firstname, lastname, hashed_password,
                  address, zipcode, country_id, state_id, city_name,
                  phone, latitude, longitude, user_id))

            # ---------------- DONOR PROFILE ----------------
            if "Donor" in roles:
                org_name = get_form_or_existing(request.form, "org_name", donor_profile.get("org_name") if donor_profile else "", "")
                org_type = get_form_or_existing(request.form, "org_type", donor_profile.get("org_type") if donor_profile else "NGO", "NGO")
                licence_file = request.files.get("licence")
                licence_filename = donor_profile.get("licience") if donor_profile and donor_profile.get("licience") else ""
                if licence_file and licence_file.filename != "" and allowed_file(licence_file.filename):
                    licence_filename = secure_filename(licence_file.filename)
                    licence_file.save(os.path.join(upload_folder, licence_filename))

                if donor_profile:
                    cursor.execute("""
                        UPDATE donors_profile
                        SET org_name=%s, org_type=%s, licience=%s
                        WHERE donor_id=%s
                    """, (org_name, org_type, licence_filename, user_id))
                else:
                    cursor.execute("""
                        INSERT INTO donors_profile (donor_id, org_name, org_type, licience)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, org_name, org_type, licence_filename))

            # ---------------- RECIPIENT PROFILE ----------------
            if "Recipient" in roles:
                org_name = get_form_or_existing(request.form, "org_name", recipient_profile.get("org_name") if recipient_profile else "", "")
                org_type = get_form_or_existing(request.form, "org_type", recipient_profile.get("org_type") if recipient_profile else "", "")
                org_profile = get_form_or_existing(request.form, "org_profile", recipient_profile.get("org_profile") if recipient_profile else "", "")

                def handle_file(field_name, existing_filename):
                    file = request.files.get(field_name)
                    filename = existing_filename if existing_filename else ""
                    if file and file.filename != "" and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        file.save(os.path.join(upload_folder, filename))
                    return filename

                tax_filename = handle_file("tax_proof", recipient_profile.get("tax_proof") if recipient_profile else "")
                food_safety_filename = handle_file("food_safety_licience", recipient_profile.get("food_safety_licience") if recipient_profile else "")
                address_filename = handle_file("address_proof", recipient_profile.get("address_proof") if recipient_profile else "")

                # Use user_profile as recipient_profile_id
                recipient_profile_id = user_profile_filename
                recipient_id = user_id

                if recipient_profile:  # UPDATE
                    cursor.execute("""
                        UPDATE recipient_profile
                        SET recipient_profile_id=%s, org_name=%s, org_type=%s, org_profile=%s,
                            tax_proof=%s, food_safety_licience=%s, address_proof=%s
                        WHERE recipient_id=%s
                    """, (recipient_profile_id, org_name, org_type, org_profile,
                          tax_filename, food_safety_filename, address_filename, recipient_id))
                else:  # INSERT
                    cursor.execute("""
                        INSERT INTO recipient_profile (recipient_profile_id, recipient_id, org_name, org_type, org_profile,
                                                      tax_proof, food_safety_licience, address_proof)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (recipient_profile_id, recipient_id, org_name, org_type, org_profile,
                          tax_filename, food_safety_filename, address_filename))

            conn.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("recipient.profile"))

        # ---------------- GET: RENDER TEMPLATE ----------------
        return render_template(
            "recipient/update_profile.html",
            user=user,
            role=roles,
            donor_profile=donor_profile,
            recipient_profile=recipient_profile,
            country_name=country_name,
            state_name=state_name,
            city_name=city_name
        )

    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("recipient.profile"))
    finally:
        cursor.close()
        conn.close()

# ========== BECOME DONOR =============
@recipient_bp.route("/become_donor")
def become_donor():
    user_id = session.get("user_id")
    if not user_id:
        flash("You must be logged in as a recipient first.", "warning")
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1️⃣ Update role in users table
    cursor.execute("""
        UPDATE users 
        SET role = 'Donor'
        WHERE user_id = %s
    """, (user_id,))
    conn.commit()

    # 2️⃣ Update session role
    session["role"] = "Donor"

    # 3️⃣ Redirect to donor dashboard
    return redirect(url_for("donor.dashboard"))

@recipient_bp.route("/switch_to_donor")
def switch_to_donor():
    """Switch a recipient account fully to donor (replace role)"""
    user_id = session.get("user_id")
    if not user_id:
        flash("You must be logged in first.", "warning")
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 🔹 Overwrite role with Donor
        cursor.execute("UPDATE users SET role=%s WHERE user_id=%s", ("Donor", user_id))
        conn.commit()

        # 🔹 Update session
        session["role"] = "Donor"

        flash("Your role has been switched to Donor!", "success")
        return redirect(url_for("donor.dashboard"))

    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("recipient.dashboard"))
    finally:
        cursor.close()
        conn.close()

#================ NOTIFICATINS =============
@recipient_bp.route('/notifications/read/<int:notif_id>')
def mark_notification_read(notif_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Mark the notification as read
    cursor.execute(
        "UPDATE notifications SET is_read = 1 WHERE notification_id = %s AND reference_user_id = %s",
        (notif_id, user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()

    flash("Notification marked as read!", "success")
    return redirect(url_for('recipient.all_notifications'))


# -------------------- View All Notifications --------------------
# ================== VIEW ALL NOTIFICATIONS ==================
@recipient_bp.route('/notifications')
def all_notifications():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login_page'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch ALL notifications for this recipient (both read + unread)
    cursor.execute("""
        SELECT notification_id, message, type, is_read, status, created_at
        FROM notifications
        WHERE reference_user_id = %s AND role = 'Recipient'
        ORDER BY created_at DESC
    """, (user_id,))
    notifications = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("recipient/all_notifications.html", notifications=notifications)

# ----------CANCEL REQUEST --------------
@recipient_bp.route('/cancel_request/<int:request_id>', methods=['GET', 'POST'])
def cancel_request(request_id):
    """Recipient cancels their request"""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1️⃣ Update request status if still pending/approved
    cursor.execute("""
        UPDATE request_to 
        SET status='Cancelled', cancelled_at=NOW()
        WHERE request_id=%s AND recipient_id=%s AND status IN ('Pending','Approved')
    """, (request_id, user_id))
    conn.commit()

    # 2️⃣ Insert notification for recipient (the one who cancelled)
    cursor.execute("""
        INSERT INTO notifications (user_id, role, message, type, status, reference_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        user_id,
        'Recipient',
        'You cancelled your request.',
        'alert',
        'Unread',   # 👈 matches ENUM('Approved','Rejected','Pending','Read','Unread')
        request_id
    ))
    conn.commit()

    # 3️⃣ Optionally notify donor (if one was assigned)
    cursor.execute("SELECT donor_id FROM request_to WHERE request_id=%s", (request_id,))
    row = cursor.fetchone()
    if row and row[0]:
        donor_id = row[0]
        cursor.execute("""
            INSERT INTO notifications (user_id, role, message, type, status, reference_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            donor_id,
            'Donor',
            'A recipient cancelled their request.',
            'alert',
            'Unread',
            request_id
        ))
        conn.commit()

    cursor.close()
    conn.close()

    flash("Request cancelled successfully.", "success")
    return redirect(url_for("recipient.my_requests"))

# -----------COMPLETE REQUEST-----------------
@recipient_bp.route("/request/<int:request_id>/complete", methods=["POST","GET"])
def complete_request(request_id):
    """Recipient confirms food received → COMPLETED"""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        UPDATE request_to 
        SET status='COMPLETED', completed_at=NOW()
        WHERE request_id=%s AND recipient_id=%s AND status='APPROVED'
    """, (request_id, user_id))
    conn.commit()

    # Notify donor
    cursor.execute("SELECT donor_id FROM request_to WHERE request_id=%s", (request_id,))
    row = cursor.fetchone()
    if row and row["donor_id"]:
        cursor.execute("""
            INSERT INTO notifications (user_id, role, message, type, status, reference_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            row["donor_id"],
            'Donor',
            'Recipient confirmed food received.',
            'thank_you',     # ✅ notification type
            'Unread',        # ✅ valid status
            request_id
        ))
        conn.commit()


    cursor.close()
    flash("Marked as completed. Thank you!", "success")
    return redirect(url_for("recipient.my_requests"))

# =============== TIME LINE ============
# ----------- TIME LINE---------------
@recipient_bp.route('/request/<int:request_id>/timeline')
def request_timeline(request_id):
    """Show request timeline for a recipient"""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get request details with donor info
    cursor.execute("""
        SELECT r.request_id, r.status, r.feedback_given,
               r.requested_at, r.approved_at, r.rejected_at,
               r.completed_at, r.cancelled_at,
               r.food_type, r.quantity, r.address,
               d.donation_id, u.first_name AS donor_name, u.address AS donor_address, d.donor_id
        FROM request_to r
        LEFT JOIN donations d ON r.donation_id = d.donation_id
        LEFT JOIN users u ON d.donor_id = u.user_id
        WHERE r.request_id = %s AND r.recipient_id = %s
    """, (request_id, user_id))
    req = cursor.fetchone()

    if not req:
        cursor.close()
        conn.close()
        return render_template("errors/404.html"), 404

    # Build timeline based on timestamps
    timeline = []
    if req["requested_at"]:
        timeline.append({"status": "Requested", "updated_at": req["requested_at"]})
    if req["approved_at"]:
        timeline.append({"status": "Approved", "updated_at": req["approved_at"]})
    if req["rejected_at"]:
        timeline.append({"status": "Rejected", "updated_at": req["rejected_at"]})
    if req["completed_at"]:
        timeline.append({"status": "Completed", "updated_at": req["completed_at"]})
    if req["cancelled_at"]:
        timeline.append({"status": "Cancelled", "updated_at": req["cancelled_at"]})

    cursor.close()
    conn.close()

    return render_template("recipient/request_timeline.html",
                           request=req, timeline=timeline)

# ---------------- Feedback Submission -----------------
@recipient_bp.route('/request/<int:request_id>/feedback', methods=['POST','GET'])
def submit_feedback(request_id):
    """Recipient submits feedback after completion"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json()
    rating = data.get("rating")
    message = data.get("message")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Verify request
    cursor.execute("SELECT donation_id, donor_id, recipient_id, status FROM request_to WHERE request_id=%s", (request_id,))
    req = cursor.fetchone()

    if not req or req["recipient_id"] != user_id or req["status"] != "COMPLETED":
        cursor.close()
        conn.close()
        return jsonify(success=False, message="Invalid request or not completed"), 403

    # Insert feedback
    cursor.execute("""
        INSERT INTO feedback (request_id, donor_id, recipient_id, donation_id, rating, message)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (request_id, req["donor_id"], req["recipient_id"], req["donation_id"], rating, message))

    # Mark request as feedback_given
    cursor.execute("UPDATE request_to SET feedback_given=1 WHERE request_id=%s", (request_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify(success=True, message="Feedback submitted successfully!")
