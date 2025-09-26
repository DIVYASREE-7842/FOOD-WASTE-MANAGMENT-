from flask import Blueprint, render_template, session, redirect, url_for, flash,request,current_app
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import mysql.connector
from datetime import datetime
import math
import os
import requests
from recipient.recipient import get_db_connection
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "supersecretkey"

donor_bp = Blueprint("donor", __name__, template_folder="../templates/donor")

# ---------------- Database Connection ----------------
def get_db():
    return mysql.connector.connect(
    host="localhost",
    user="root",
    password="7842557971",
    database="food_db"
)
conn=get_db()
cursor = conn.cursor(dictionary=True)
#####################################################
# ---------------- Decorator ----------------
def donor_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login first", "danger")
            return redirect(url_for("auth.login_page"))
        roles = session.get("role", [])
        if isinstance(roles, str):
            roles = [roles]
        if "Donor" not in roles:
            flash("Access denied. Donor role required.", "danger")
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return wrapper


# ---------------- Routes ----------------

# Show all donors and their status
@donor_bp.route("/donors")
def donors_list():
    cursor.execute("SELECT * FROM donors_profile WHERE is_deleted = 0")
    donors = cursor.fetchall()
    return render_template("admin/donors_list.html", donors=donors)

# Donor Profile (details + donations)
@donor_bp.route("/donor/<donor_profile_id>")
def donor_profile(donor_profile_id):
    cursor.execute("SELECT * FROM donors_profile WHERE donor_profile_id = %s", (donor_profile_id,))
    donor = cursor.fetchone()

    cursor.execute("SELECT * FROM donations WHERE donors_profile_id = %s AND is_deleted = 0", (donor_profile_id,))
    donations = cursor.fetchall()

    return render_template("donor/donor_profile.html", donor=donor, donations=donations)

# Update Donor Status (Admin Only)
@donor_bp.route("/donor/update_status/<donor_profile_id>", methods=["POST"])
def update_donor_status(donor_profile_id):
    new_status = request.form.get("status")
    cursor.execute("UPDATE donors_profile SET status = %s WHERE donor_profile_id = %s",
                   (new_status, donor_profile_id))
    get_db.commit()
    flash("Donor status updated successfully!", "success")
    return redirect(url_for("donor_profile", donor_profile_id=donor_profile_id))

# API to fetch donor JSON (optional)
@donor_bp.route("/api/donor/<donor_profile_id>")
def api_donor(donor_profile_id):
    cursor.execute("SELECT * FROM donors_profile WHERE donor_profile_id = %s", (donor_profile_id,))
    donor = cursor.fetchone()
    return jsonify(donor)

# ---------------- DISTANCE FUNCTION ----------------
def calculate_distance(lat1, lon1, lat2, lon2):
    if not (lat1 and lon1 and lat2 and lon2):
        return None
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 2)

# ---------------- JSON SAFE HELPER ----------------
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(i) for i in obj]
    elif isinstance(obj, set):
        return list(obj)
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        return obj

# ---------------- DASHBOARD ROUTE ----------------
@donor_bp.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("auth.login_page"))

    roles = session.get("role", [])
    if isinstance(roles, str):
        roles = [roles]
    if "Donor" not in roles:
        flash("Access denied. Donor role required.", "danger")
        return redirect(url_for("auth.login_page"))

    conn = get_db()  # your DB connection
    cursor = conn.cursor(dictionary=True)

    # Check user status
    cursor.execute("SELECT status FROM users WHERE user_id=%s", (session["user_id"],))
    user_status = cursor.fetchone()
    if not user_status:
        flash("User not found", "danger")
        return redirect(url_for("auth.login_page"))
    if user_status['status'] == 'Pending':
        flash("Admin approval required", "warning")
        return redirect(url_for('recipient.profile'))

    # Donor info
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (session["user_id"],))
    donor = cursor.fetchone()
    if not donor:
        flash("User not found", "danger")
        return redirect(url_for("auth.login_page"))

    # ---------------- Total Donations ----------------
    cursor.execute("SELECT COUNT(*) AS total FROM donations WHERE donor_id=%s AND is_deleted = 0 ", (donor["user_id"],))
    total_donations = cursor.fetchone()["total"]
    
    # ---------------- Total Food Saved (sum of quantity) ----------------
    cursor.execute("""
        SELECT COALESCE(SUM(quantity), 0) AS total_food
        FROM donations
        WHERE donor_id=%s AND is_deleted = 0 
    """, (donor["user_id"],))
    total_food_saved = cursor.fetchone()["total_food"]

    cursor.execute("""
    SELECT COUNT(DISTINCT recipient_id) AS active_recipients
    FROM request_to
    WHERE donor_id=%s AND is_deleted=0
    """, (donor["user_id"],))
    active_recipients = cursor.fetchone()["active_recipients"]

    # ---------------- Donations Over Time ----------------
    cursor.execute("""
        SELECT DATE(prepared_at) AS day, COUNT(*) AS count
        FROM donations
        WHERE donor_id=%s AND is_deleted = 0
        GROUP BY DATE(prepared_at)
        ORDER BY day
    """, (donor["user_id"],))
    donation_data = cursor.fetchall()
    donation_labels = [row["day"].strftime("%Y-%m-%d") for row in donation_data]
    donation_values = [row["count"] for row in donation_data]

    # ---------------- Category Chart ----------------
    cursor.execute("""
        SELECT food_type, COUNT(*) AS count
        FROM donations
        WHERE donor_id=%s AND is_deleted = 0
        GROUP BY food_type
    """, (donor["user_id"],))
    category_data = cursor.fetchall()
    category_labels = [row["food_type"] for row in category_data]
    category_values = [row["count"] for row in category_data]
    #  nearby 
    # ---------------- Recipients with Distance ----------------
    cursor.execute("""
        SELECT user_id, first_name, last_name, latitude, longitude 
        FROM users 
        WHERE role='Recipient' AND is_deleted=0
    """)
    recipients = cursor.fetchall()

    for r in recipients:
        r["name"] = f"{r['first_name']} {r['last_name']}"
        r["distance"] = calculate_distance(
            donor.get("latitude") or 0,
            donor.get("longitude") or 0,
            r.get("latitude") or 0,
            r.get("longitude") or 0
        )

    # ---------------- Pending Requests ----------------
    cursor.execute("""
    SELECT COUNT(*) AS pending_count
    FROM request_to
    WHERE donor_id=%s AND status='Pending' AND is_deleted=0
    """, (donor["user_id"],))
    pending_result = cursor.fetchone()
    donor_pending_count = pending_result["pending_count"] if pending_result else 0
    print("donor_pending_count", donor_pending_count)

    # ---------------- Recipients with Distance ----------------
    cursor.execute("SELECT user_id, first_name, last_name, latitude, longitude FROM users WHERE role='Recipient' AND is_deleted=0")
    recipients = cursor.fetchall()
    for r in recipients:
        r["name"] = f"{r['first_name']} {r['last_name']}"
        r["distance"] = calculate_distance(
            donor.get("latitude") or 0, 
            donor.get("longitude") or 0, 
            r.get("latitude") or 0, 
            r.get("longitude") or 0
        )
    # ---------------- Nearby Recipients ----------------
    nearby_recipients = [
        r for r in recipients
        if r["distance"] is not None and r["distance"] <= 50
    ]
    nearby_recipients_count = len(nearby_recipients)

    
    # ✅ 1. Get donor location
    cursor.execute("SELECT * FROM users WHERE user_id = %s ", (donor["user_id"],))
    donor = cursor.fetchone()
    if not donor:
        flash("Donor profile not found.", "error")
        return redirect(url_for('auth.login'))

    donor_lat, donor_lng = donor['latitude'], donor['longitude']
    cursor.execute("""
        SELECT u.user_id, CONCAT(u.first_name+u.last_name), u.city, u.phone, 
               (6371 * ACOS(
                   COS(RADIANS(%s)) * COS(RADIANS(u.latitude)) *
                   COS(RADIANS(u.longitude) - RADIANS(%s)) +
                   SIN(RADIANS(%s)) * SIN(RADIANS(u.latitude))
               )) AS distance
        FROM users u
        WHERE u.role = 'Recipient'
        HAVING distance <= 10
        ORDER BY distance ASC
    """, (donor_lat, donor_lng, donor_lat))

    nearby_recipients = cursor.fetchall()
    conn.close()

    # Make all objects JSON safe
    donor = make_json_safe(donor)
    recipients = make_json_safe(recipients)
    donation_labels = list(donation_labels)
    donation_values = list(donation_values)
    category_labels = list(category_labels)
    category_values = list(category_values)
    print("donor_pending_count",donor_pending_count)
    return render_template(
    "donor/dashboard.html",
    donor=donor,
    recipients=recipients,
    total_donations=total_donations,
    total_food_saved=total_food_saved,
    nearby_recipients_count=nearby_recipients_count,
    nearby_recipients=nearby_recipients,
    active_recipients=active_recipients,
    donation_labels=donation_labels,
    donation_values=donation_values,
    category_labels=category_labels,
    category_values=category_values,
    donor_pending_count=donor_pending_count
)



# ---------------ADD DNATION ---------------------------------
def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'pdf'})

@donor_bp.route('/add-donation', methods=['GET', 'POST'])
def add_donation():
    if 'user_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('auth.login_page'))
    
    roles = session.get('role', [])
    if isinstance(roles, str):
        roles = [roles]
    if 'Donor' not in roles:
        flash('Access denied. Donor role required.', 'danger')
        return redirect(url_for('home'))

    if request.method == 'GET':
        return render_template('donor/add_donation.html')

    # POST request
    conn = get_db()  # Initialize connection here
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session.get('user_id')
        quantity = int(request.form.get('quantity'))
        food_type = request.form.get('food_type')
        prepared_at = request.form.get('prepared_at')
        expired_at = request.form.get('expired_at')
        description = request.form.get('description', '')
        food_img=request.files.get('photo')
        food=request.form.get('food')
        latitude=request.form.get('latitude')
        longitude=request.form.get('longitude')
        food_img_name = None
        if food_img and food_img.filename:
            filename = secure_filename(food_img.filename)
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            food_img.save(filepath)
            food_img_name = filename  # Save only the filename to DB
        else:
            flash("No file selected", "warning")
        # Get donor profile id
        cursor.execute("SELECT donor_profile_id FROM donors_profile WHERE donor_id = %s AND is_deleted = 0", (user_id,))
        donor_profile = cursor.fetchone()
        print(donor_profile)
        if not donor_profile:
            flash('Donor profile not found', 'danger')
            return redirect(url_for('donor.dashboard'))
        donor_profile_id = donor_profile['donor_profile_id']

        # Insert donation
        cursor.execute("""
                INSERT INTO donations
                (donor_id, donors_profile_id, quantity, food_type, prepared_at, expired_at, description, status, food_img,food,latitude,longitude)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN', %s,%s,%s,%s)
        """, (user_id, donor_profile_id, quantity, food_type, prepared_at, expired_at, description, food_img_name,food,latitude,longitude))

        conn.commit()
        flash('Donation added successfully!', 'success')
        return redirect(url_for('donor.dashboard'))

    except Exception as e:
        conn.rollback()
        flash(f'Error adding donation: {str(e)}', 'danger')
        return render_template('donor/add_donation.html')
    finally:
        cursor.close()
        conn.close()
# ------------cancel--------------
@donor_bp.route('/donation/<int:donation_id>/cancel')
def cancel_donation(donation_id):
    if 'user_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('auth.login_page'))
    
    # Check if user has donor role
    roles = session.get('role', [])
    if isinstance(roles, str):
        roles = [roles]
    
    if 'Donor' not in roles:
        flash('Access denied. Donor role required.', 'danger')
        return redirect(url_for('home'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        user_id = session.get('user_id')
        
        # Check if donation exists and belongs to user
        cursor.execute("SELECT * FROM donations WHERE donation_id = %s AND donor_id = %s", (donation_id, user_id))
        donation = cursor.fetchone()
        
        if not donation:
            flash('Donation not found', 'danger')
            return redirect(url_for('donor.dashboard'))
        
        # Check if donation can be cancelled (only OPEN or RESERVED status)
        if donation['status'] not in ['OPEN', 'RESERVED']:
            flash('Only OPEN or RESERVED donations can be cancelled', 'warning')
            return redirect(url_for('donor.dashboard'))
        
        # Update donation status to CANCELLED
        cursor.execute("UPDATE donations SET status = 'CANCELLED' WHERE donation_id = %s", (donation_id,))
        conn.commit()
        
        flash('Donation cancelled successfully', 'success')
        return redirect(url_for('donor.dashboard'))
        
    except Exception as e:
        conn.rollback()
        flash(f'Error cancelling donation: {str(e)}', 'danger')
        return redirect(url_for('donor.dashboard'))
    finally:
        cursor.close()
        conn.close()

@donor_bp.route('/donations')
def my_donations():
    if 'user_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('auth.login_page'))
    
    # Check if user has donor role
    roles = session.get('role', [])
    if isinstance(roles, str):
        roles = [roles]
    
    if 'Donor' not in roles:
        flash('Access denied. Donor role required.', 'danger')
        return redirect(url_for('home'))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        user_id = session.get('user_id')
        page = request.args.get('page', 1, type=int)
        per_page = 4
        offset = (page - 1) * per_page
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM donations WHERE donor_id = %s AND is_deleted = 0", (user_id,))
        total_count = cursor.fetchone()['total']
        total_pages = (total_count + per_page - 1) // per_page
        
        # Get paginated donations
        cursor.execute("""
            SELECT d.*, dp.org_name 
            FROM donations d 
            LEFT JOIN donors_profile dp ON d.donors_profile_id = dp.donor_profile_id 
            WHERE d.donor_id = %s AND d.is_deleted = 0 
            ORDER BY d.prepared_at DESC 
            LIMIT %s OFFSET %s
        """, (user_id, per_page, offset))
        
        donations = cursor.fetchall()
        # cursor.execute("""
        #         SELECT COUNT(*) AS total
        #         FROM donations d
        #         WHERE d.donor_id = %s AND d.is_deleted = 0
        #     """, (user_id,))
        # total_donations = cursor.fetchone()['total']
        # print("total donations",total_donations)
        return render_template('donor/my_donations.html', 
                             donations=donations, 
                             page=page,
                             per_page=per_page, 
                             total_pages=total_pages)
        
    except Exception as e:
        flash(f'Error fetching donations: {str(e)}', 'danger')
        return render_template('donor/my_donations.html', donations=[], page=1, total_pages=1)
    finally:
        cursor.close()
        conn.close()
# == UPDATE DONATIONS =========
# @donor_bp.route('/donation/<int:donation_id>/complete', methods=['POST'])
# def complete_donation(donation_id):
#     user_id = session.get('user_id')
#     print("user_id in complete",user_id)
#     if not user_id:
#         flash('Login required', 'danger')
#         return redirect(url_for('auth.login_page'))

#     conn = get_db_connection()
#     cursor = conn.cursor(dictionary=True)   # ✅ Important fix

#     # ensure the donor owns this donation
#     cursor.execute("""
#         SELECT donor_id FROM donations WHERE donation_id = %s AND is_deleted = 0
#     """, (donation_id,))
#     row = cursor.fetchone()
#     if not row:
#         flash('Donation not found', 'danger')
#         cursor.close()
#         conn.close()
#         return redirect(url_for('donor.my_donations'))

#     if row['donor_id'] != user_id:
#         flash('Not authorized', 'danger')
#         cursor.close()
#         conn.close()
#         return redirect(url_for('donor.my_donations'))

#     cursor.execute("""
#         UPDATE donations SET status = 'COMPLETED' WHERE donation_id = %s
#     """, (donation_id,))
#     conn.commit()
#     cursor.close()
#     conn.close()

#     flash('Donation marked as completed.', 'success')
#     return redirect(url_for('donor.my_donations'))

# == UPDATE DONATIONS =========
@donor_bp.route('/donation/<int:donation_id>/complete', methods=['POST'])
def complete_donation(donation_id):
    if 'user_id' not in session:
        print("[DEBUG] No user in session, redirecting to login")
        return jsonify(success=False, message="Login required"), 401

    user_id = int(session['user_id'])   # ensure integer
    print(f"[DEBUG] Logged-in user_id: {user_id}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 🔹 Ensure donation exists and belongs to this donor
        cursor.execute("""
            SELECT donor_id FROM donations 
            WHERE donation_id = %s AND is_deleted = 0
        """, (donation_id,))
        row = cursor.fetchone()

        if not row:
            print(f"[DEBUG] Donation {donation_id} not found or already deleted")
            return jsonify(success=False, message="Donation not found"), 404

        db_donor_id = int(row['donor_id'])
        print(f"[DEBUG] Donation {donation_id} belongs to donor {db_donor_id}")

        if db_donor_id != user_id:
            print(f"[DEBUG] Unauthorized attempt: user {user_id} vs donor {db_donor_id}")
            return jsonify(success=False, message="Not authorized"), 403

        # 🔹 Mark as completed
        cursor.execute("""
            UPDATE donations SET status = 'COMPLETED' WHERE donation_id = %s
        """, (donation_id,))
        conn.commit()

        print(f"[INFO] Donation {donation_id} marked as COMPLETED by donor {user_id}")
        return jsonify(success=True, message="Donation marked as completed")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Complete donation failed: {e}")
        return jsonify(success=False, message=f"Server error: {str(e)}"), 500

    finally:
        cursor.close()
        conn.close()

# -------------deletion operation ----------------
@donor_bp.route('/donations/delete/<int:donation_id>', methods=['POST'])
def delete_donation(donation_id):
    # 🔹 1. Check login
    if 'user_id' not in session:
        return jsonify(success=False, message="Not authenticated"), 401

    user_id = int(session['user_id'])   # ensure integer
    print(f"[DEBUG] Logged-in user_id from session: {user_id}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 🔹 2. Check donation exists
        cursor.execute("SELECT donor_id FROM donations WHERE donation_id = %s", (donation_id,))
        row = cursor.fetchone()

        if not row:
            return jsonify(success=False, message="Donation not found"), 404

        db_donor_id = int(row['donor_id'])
        print(f"[DEBUG] Donation {donation_id} belongs to donor_id: {db_donor_id}")

        # 🔹 3. Authorization check
        if db_donor_id != user_id:
            return jsonify(success=False, message="Unauthorized: You cannot delete others' donations"), 403

        # 🔹 4. Soft delete
        cursor.execute("""
            UPDATE donations
            SET is_deleted = 1, deleted_at = NOW()
            WHERE donation_id = %s
        """, (donation_id,))
        conn.commit()

        print(f"[INFO] Donation {donation_id} deleted by donor {user_id}")
        return jsonify(success=True, message="Donation deleted", donation_id=donation_id)

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Delete failed: {e}")
        return jsonify(success=False, message=f"Server error: {str(e)}"), 500

    finally:
        cursor.close()
        conn.close()

    
# -------------- Donor profile-----------------------
@donor_bp.route('/profile')
def profile():
    """View user profile"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (session['user_id'],))
        user = cursor.fetchone()
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for('auth.login_page'))
        # print("roles",user)
        # ---------------- CLEAN ROLE LIST ----------------
        roles_raw = user.get('role') or ""
        # print("roles_raw",roles_raw)
        # If it's a set (MySQL SET type), convert to sorted list
        if isinstance(roles_raw, set):
            role_list = [r.strip().capitalize() for r in sorted(roles_raw)]
        elif isinstance(roles_raw, str):
            # If string (comma-separated), split it
            role_list = [r.strip().capitalize() for r in roles_raw.split(",") if r.strip()]
        elif isinstance(roles_raw, list):
            role_list = [str(r).strip().capitalize() for r in roles_raw if r and str(r).strip()]
        else:
            role_list = []

        # Join for display
        role_display = ", ".join(role_list)
        # print("role", role_display)

                # ---------------- LOCATION NAMES ----------------
        country_name = get_country_name(user.get('country')) if user.get('country') else ''
        state_name = get_state_name(user.get('country'), user.get('state')) if user.get('state') else ''
        city_name = get_city_name(user.get('country'), user.get('state'), user.get('city')) if user.get('city') else ''

        # ---------------- PROFILE DETAILS ----------------
        donor_profile, recipient_profile = None, None
        if 'Donor' in role_list:
            cursor.execute(
                "SELECT org_name, org_type, licience FROM donors_profile WHERE donor_id=%s",
                (session['user_id'],)
            )
            donor_profile = cursor.fetchone()
        if 'Recipient' in role_list:
            cursor.execute(
                "SELECT org_name, org_type, tax_proof FROM recipient_profile WHERE recipient_id=%s",
                (session['user_id'],)
            )
            recipient_profile = cursor.fetchone()

        # ---------------- LATEST REQUEST STATUS ----------------
        cursor.execute(
            "SELECT status FROM user_requests WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
            (session['user_id'],)
        )
        request_status_row = cursor.fetchone()
        request_status = request_status_row['status'] if request_status_row else "Pending"
        # print("role",role_display)
        return render_template(
            'donor/profile.html',
            user=user,
            role_display=role_display,  # Comma-separated roles
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
@donor_bp.route('/api/countries')
def get_countries():
    try:
        response = requests.get(f"{base_url}/countries", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@donor_bp.route('/api/countries/<country_code>/states')
def get_states(country_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@donor_bp.route('/api/countries/<country_code>/states/<state_code>/cities')
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
@donor_bp.route("/update_profile", methods=["GET", "POST"])
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
        # Fetch current user
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("User not found!", "danger")
            return redirect(url_for("auth.login_page"))

        # Determine roles
        roles = user["role"]
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(",")]
        elif isinstance(roles, set):
            roles = list(roles)

        # Fetch role profiles
        donor_profile, recipient_profile = None, None
        if "Donor" in roles:
            cursor.execute("SELECT * FROM donors_profile WHERE donor_id=%s", (user_id,))
            donor_profile = cursor.fetchone()
        if "Recipient" in roles:
            cursor.execute("SELECT * FROM recipient_profile WHERE recipient_id=%s", (user_id,))
            recipient_profile = cursor.fetchone()

        # Country/state/city names
        country_name = get_country_name(user.get('country')) if user.get('country') else ''
        state_name = get_state_name(user.get('country'), user.get('state')) if user.get('state') else ''
        city_name = user.get('city') or ''

        if request.method == "POST":
            # ---------------- BASIC FIELDS ----------------
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
                    return redirect(url_for("donor.update_profile"))
                if new_password != confirm_password:
                    flash("New passwords do not match!", "danger")
                    return redirect(url_for("donor.update_profile"))
                hashed_password = generate_password_hash(new_password)
            else:
                hashed_password = user["password"]

            # ---------------- PROFILE PHOTO ----------------
            profile_photo_file = request.files.get("profile_photo")
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
            os.makedirs(upload_folder, exist_ok=True)
            if profile_photo_file and profile_photo_file.filename != "" and allowed_file(profile_photo_file.filename):
                filename = secure_filename(profile_photo_file.filename)
                profile_photo_file.save(os.path.join(upload_folder, filename))
            else:
                filename = user.get("user_profile")

            # ---------------- UPDATE USERS TABLE ----------------
            cursor.execute("""
                UPDATE users
                SET user_profile=%s, first_name=%s, last_name=%s, password=%s,
                    address=%s, zip_code=%s, country=%s, state=%s, city=%s,
                    phone=%s, latitude=%s, longitude=%s
                WHERE user_id=%s
            """, (filename, firstname, lastname, hashed_password,
                  address, zipcode, country_id, state_id, city_name,
                  phone, latitude, longitude, user_id))

            # ---------------- DONOR PROFILE ----------------
            if "Donor" in roles:
                org_name = get_form_or_existing(request.form, "org_name", donor_profile.get("org_name") if donor_profile else "", "")
                org_type = get_form_or_existing(request.form, "org_type", donor_profile.get("org_type") if donor_profile else "NGO", "NGO")
                valid_org_types = ['NGO','Food Banks','Individuals','Shelters','RESTAURANT','HOTEL','HOUSEHOLD','EVENT']
                if org_type not in valid_org_types:
                    org_type = donor_profile.get("org_type") if donor_profile else "NGO"

                licence_file = request.files.get("licence")
                licence_filename = donor_profile.get("licience") if donor_profile and donor_profile.get("licience") else ""
                if licence_file and licence_file.filename != "" and allowed_file(licence_file.filename):
                    licence_filename = secure_filename(licence_file.filename)
                    licence_file.save(os.path.join(upload_folder, licence_filename))

                if donor_profile:  # UPDATE
                    cursor.execute("""
                        UPDATE donors_profile
                        SET org_name=%s, org_type=%s, licience=%s
                        WHERE donor_id=%s
                    """, (org_name, org_type, licence_filename, user_id))
                else:  # INSERT
                    cursor.execute("""
                        INSERT INTO donors_profile (donor_id, org_name, org_type, licience)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, org_name, org_type, licence_filename))

            # ---------------- RECIPIENT PROFILE ----------------
            if "Recipient" in roles:
                org_name = get_form_or_existing(request.form, "org_name", recipient_profile.get("org_name") if recipient_profile else "", "")
                org_type = get_form_or_existing(request.form, "org_type", recipient_profile.get("org_type") if recipient_profile else "", "")
                org_profile = get_form_or_existing(request.form, "org_profile", recipient_profile.get("org_profile") if recipient_profile else "", "")

                # Files
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

                if recipient_profile:  # UPDATE
                    cursor.execute("""
                        UPDATE recipient_profile
                        SET org_name=%s, org_type=%s, org_profile=%s,
                            tax_proof=%s, food_safety_licience=%s, address_proof=%s
                        WHERE recipient_id=%s
                    """, (org_name, org_type, org_profile, tax_filename, food_safety_filename, address_filename, user_id))
                else:  # INSERT
                    cursor.execute("""
                        INSERT INTO recipient_profile (recipient_id, org_name, org_type, org_profile,
                                                      tax_proof, food_safety_licience, address_proof)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (user_id, org_name, org_type, org_profile, tax_filename, food_safety_filename, address_filename))

            conn.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("donor.profile"))

        # GET request: render template
        return render_template(
            "donor/update_profile.html",
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
        return redirect(url_for("donor.update_profile"))
    finally:
        cursor.close()
        conn.close()


# =========== Become recipient =============
def normalize_roles(roles):
    """
    Convert any DB role format (str, set, list, {'Recipient'}) into a clean list
    """
    role_list = []
    if isinstance(roles, str):
        # Remove curly braces if present
        roles_clean = roles.replace("{", "").replace("}", "")
        role_list = [r.strip().capitalize() for r in roles_clean.split(",") if r.strip()]
    elif isinstance(roles, (set, list)):
        role_list = [str(r).strip().capitalize() for r in roles if r and str(r).strip()]
    return role_list

@donor_bp.route("/become_recipient")
def become_recipient():
    """Add Recipient role to an existing user (Donor → Donor+Recipient)"""
    user_id = session.get("user_id")
    if not user_id:
        flash("You must be logged in first.", "warning")
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 🔹 Fetch user
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("User not found!", "danger")
            return redirect(url_for("auth.login"))

        # 🔹 Normalize roles (string, set, list)
        roles = user.get("role", "")
        if isinstance(roles, str):
            role_list = [r.strip().capitalize() for r in roles.split(",") if r.strip()]
        elif isinstance(roles, (list, set)):
            role_list = [str(r).strip().capitalize() for r in roles if r and str(r).strip()]
        else:
            role_list = []

        # 🔹 Add Recipient role if missing
        if "Recipient" not in role_list:
            role_list.append("Recipient")
            new_roles = ",".join(role_list)
            cursor.execute("UPDATE users SET role=%s WHERE user_id=%s", (new_roles, user_id))
            conn.commit()
            # 🔹 Update session
            session["role"] = new_roles
            flash("Your role has been updated to include Recipient!", "success")
        else:
            flash("You already have the Recipient role.", "info")

        return redirect(url_for("donor.dashboard"))

    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("donor.dashboard"))
    finally:
        cursor.close()
        conn.close()

@donor_bp.route("/switch_to_recipient")
def switch_to_recipient():
    """Switch a donor account fully to Recipient"""
    user_id = session.get("user_id")
    if not user_id:
        flash("You must be logged in first.", "warning")
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Overwrite role
        cursor.execute("UPDATE users SET role=%s WHERE user_id=%s", ("Recipient", user_id))
        conn.commit()

        # Update session
        session["role"] = "Recipient"
        flash("Your role has been switched to Recipient!", "success")
        return redirect(url_for("recipient.dashboard"))

    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("donor.dashboard"))
    finally:
        cursor.close()
        conn.close()


# ================NOTIFICATION===========
@donor_bp.route('/notifications/read/<int:notif_id>')
def mark_notification_read(notif_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE notifications 
        SET is_read=1, status='Read' 
        WHERE notification_id=%s AND user_id=%s
    """, (notif_id, user_id))
    
    conn.commit()
    print("Rows updated:", cursor.rowcount)  # ✅ will tell how many rows changed
    
    cursor.close()
    conn.close()
   
    return redirect(request.referrer or url_for('donor.dashboard'))



# ================= ALL NOTIFICATIONS =================
@donor_bp.route('/notifications/all')
def all_notifications():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
    SELECT notification_id, message, type, is_read, status, created_at
    FROM notifications
    WHERE reference_user_id = %s AND role = 'Recipient' AND is_read = 0
    ORDER BY created_at DESC
    """, (user_id,))
    notifications = cursor.fetchall()

    # 2️⃣ Fetch related requests
    cursor.execute("""
        SELECT request_id AS id, request_id AS reference_id,
               CONCAT('Food request for ', food_type, ' (', quantity, ')') AS message,
               CASE WHEN status='Pending' THEN 0 ELSE 1 END AS is_read,
               created_at, 'request' AS type
        FROM request_to
        WHERE donor_id=%s
    """, (user_id,))
    requests = cursor.fetchall()

    cursor.close()
    conn.close()

    # 3️⃣ Merge and sort by created_at DESC
    combined = notifications + requests
    combined.sort(key=lambda x: x['created_at'], reverse=True)

    return render_template('donor/all_notification.html', combined=combined)


# ================= NOTIFICATION DETAILS =================
@donor_bp.route('/notifications/<int:notif_id>')
def notification_detail(notif_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Try fetching from notifications table (linked to request_to if any)
    cursor.execute("""
            SELECT n.notification_id, n.message, n.is_read, n.created_at, n.status,
                n.reference_request_id, r.food_type, r.quantity, r.address, r.status AS request_status
            FROM notifications n
            LEFT JOIN request_to r ON n.reference_request_id = r.request_id
            WHERE n.notification_id = %s AND n.reference_user_id = %s
        """, (notif_id, user_id))

    notif = cursor.fetchone()

    # If not found, try directly from request_to (clicked request-type notif)
    if not notif:
        cursor.execute("""
            SELECT r.request_id AS notification_id,
                   CONCAT('Food request for ', r.food_type, ' (', r.quantity, ')') AS message,
                   0 AS is_read, r.created_at,
                   NULL AS status,
                   r.request_id AS reference_id,
                   r.food_type, r.quantity, r.address, r.status AS request_status
            FROM request_to r
            WHERE r.request_id=%s AND r.donor_id=%s
        """, (notif_id, user_id))
        notif = cursor.fetchone()

    if not notif:
        cursor.close()
        conn.close()
        flash("Notification not found.", "danger")
        return redirect(url_for("donor.all_notifications"))

    # Mark as read if it's from notifications
    if "notification_id" in notif and not notif["is_read"]:
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE notification_id = %s", (notif["notification_id"],))
        conn.commit()

    cursor.close()
    conn.close()

    return render_template("donor/notification_detail.html", notif=notif)

# ================= APPROVE REQUEST =================
@donor_bp.route("/request/<int:request_id>/approve", methods=["POST"])
def approve_request(request_id):
    """Donor approves a request"""
    donor_id = session.get("user_id")
    if not donor_id:
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT recipient_id FROM request_to WHERE request_id=%s AND donor_id=%s", (request_id, donor_id))
    req = cursor.fetchone()
    if not req:
        flash("Unauthorized request.", "error")
        return redirect(url_for("donor.dashboard"))

    cursor.execute("""
        UPDATE request_to 
        SET status='APPROVED', approved_at=NOW()
        WHERE request_id=%s
    """, (request_id,))
    conn.commit()

    cursor.execute("""
        INSERT INTO notifications (reference_user_id,reference_request_id, role, message, type, status)
        VALUES (%s, %s, %s,%s, %s, %s)
    """, (req["recipient_id"], request_id, 'Recipient', 'Your request was approved by donor.', 'info', 'APPROVED'))
    conn.commit()

    cursor.close()
    conn.close()
    flash("Request approved.", "success")
    return redirect(url_for("donor.dashboard"))

# ---reject -----
@donor_bp.route("/request/<int:request_id>/reject", methods=["POST"])
def reject_request(request_id):
    """Donor rejects a request"""
    donor_id = session.get("user_id")
    if not donor_id:
        return redirect(url_for("auth.login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT recipient_id FROM request_to WHERE request_id=%s AND donor_id=%s", (request_id, donor_id))
    req = cursor.fetchone()
    if not req:
        flash("Unauthorized request.", "error")
        return redirect(url_for("donor.dashboard"))

    cursor.execute("""
        UPDATE request_to 
        SET status='REJECTED', rejected_at=NOW()
        WHERE request_id=%s
    """, (request_id,))
    conn.commit()

    cursor.execute("""
        INSERT INTO notifications (reference_user_id, reference_request_id, role, message, type, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (req["recipient_id"], request_id, 'Recipient', 'Your request was rejected by donor.', 'alert', 'REJECTED'))

    conn.commit()
    cursor.close()
    conn.close()
    flash("Request rejected.", "success")
    return redirect(url_for("donor.dashboard"))
