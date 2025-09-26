from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, session
import requests
from werkzeug.utils import secure_filename
import mysql.connector
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
import random, string
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature


# ---------------- BLUEPRINT ----------------
auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')


# ---------------- DB CONNECTION HELPER ----------------
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="7842557971",
        database="food_db"
    )
# ------------login decoretor -----------------------
# ---------------- FILE UPLOAD HELPER ----------------
def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'pdf'})

# ---------------- API CONFIG ----------------
api_id = "bkgwS1F2bFhGOHVBeUJLUUtiZEZiemtydmtuMk8xbGV1Nlo4UEVoYQ=="
base_url = 'https://api.countrystatecity.in/v1'
headers = {'X-CSCAPI-KEY': api_id}

# ------------ API ROUTES ------------
@auth_bp.route('/api/countries')
def get_countries():
    try:
        response = requests.get(f"{base_url}/countries", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/api/countries/<country_code>/states')
def get_states(country_code):
    try:
        response = requests.get(f"{base_url}/countries/{country_code}/states", headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/api/countries/<country_code>/states/<state_code>/cities')
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

# ------------ REGISTER ROUTE -----------
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("auth/register.html")
    
    # POST request handling
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get form data
        firstname = request.form.get("firstname", "").strip()
        lastname = request.form.get("lastname", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        address = request.form.get("address", "").strip()
        zipcode = request.form.get("zipcode", "").strip()
        country = request.form.get("country", "").strip()
        state = request.form.get("state", "").strip()
        city = request.form.get("city", "").strip()
        role = request.form.getlist("roles")
        latitude = request.form.get("latitude") or None
        longitude = request.form.get("longitude") or None
        
        # Validate required fields
        if not all([firstname, lastname, email, phone, password, address, zipcode, country, state, city]):
            flash("Please fill in all required fields.", "danger")
            return render_template("auth/register.html", form=request.form)
            
        if password != confirm_password:
            flash("Passwords do not match!", "danger")
            return render_template("auth/register.html", form=request.form)
            
        if not role:
            flash("Please select at least one role.", "danger")
            return render_template("auth/register.html", form=request.form)
            
        # Handle profile photo
        profile_photo = request.files.get("profile_photo")
        if not profile_photo or profile_photo.filename == "":
            flash("Please upload a profile photo", "danger")
            return render_template("auth/register.html", form=request.form)
            
        if not allowed_file(profile_photo.filename):
            flash("Invalid file type for profile photo.", "danger")
            return render_template("auth/register.html", form=request.form)
            
        # Save profile photo
        filename = secure_filename(profile_photo.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        profile_photo.save(filepath)
        
        # Check if email already exists
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("This email is already registered!", "danger")
            return render_template("auth/register.html", form=request.form)
            
        # Hash password
        hashed_password = generate_password_hash(password)
        roles_str = ",".join(role)
        
        # Convert latitude/longitude
        try:
            lat = float(latitude) if latitude else None
            lng = float(longitude) if longitude else None
        except (ValueError, TypeError):
            lat = None
            lng = None
            
        # Insert user
        insert_user = """
            INSERT INTO users 
                (user_profile, first_name, last_name, email, password, role, address, country, city, state, zip_code, phone, latitude, longitude) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_user, (
            filename, firstname, lastname, email, hashed_password, roles_str,
            address, country, city, state, zipcode, phone, lat, lng
        ))
        user_id = cursor.lastrowid
        
        # Handle donor registration
        if "Donor" in role:
            donor_profile_id = str(uuid.uuid4())
            licence_file = request.files.get("licence")
            licence_filename = None
            if licence_file and licence_file.filename != "" and allowed_file(licence_file.filename):
                licence_filename = secure_filename(licence_file.filename)
                licence_filepath = os.path.join(upload_folder, licence_filename)
                licence_file.save(licence_filepath)
            org_name = request.form.get("org_name", "").strip()
            org_type = request.form.get("org_type", "").strip()
            description = request.form.get("description", "").strip()
            donor_org_file = request.files.get("org_profile")
            org_profile_filename = None
            if donor_org_file and donor_org_file.filename != "" and allowed_file(donor_org_file.filename):
                org_profile_filename = secure_filename(donor_org_file.filename)
                org_profile_path = os.path.join(upload_folder, org_profile_filename)
                donor_org_file.save(org_profile_path)
            insert_donor = """
                INSERT INTO donors_profile 
                    (donor_id, donor_profile_id, licience, org_name, org_type, org_profile, description, status) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_donor, (
                user_id, donor_profile_id, licence_filename, org_name, org_type, org_profile_filename, description, "Pending"
            ))
        
        # Handle recipient registration
        if "Recipient" in role:
            recipient_profile_id = str(uuid.uuid4())
            licence_file = request.files.get("licence")
            licence_filename = None
            if licence_file and licence_file.filename != "" and allowed_file(licence_file.filename):
                licence_filename = secure_filename(licence_file.filename)
                licence_filepath = os.path.join(upload_folder, licence_filename)
                licence_file.save(licence_filepath)
            org_name = request.form.get("org_name", "").strip()
            org_type = request.form.get("org_type", "").strip()
            description = request.form.get("description", "").strip()
            org_capacity = request.form.get("org_capacity", "").strip()
            tax_file = request.files.get("tax_proof")
            tax_filename = None
            if tax_file and tax_file.filename != "" and allowed_file(tax_file.filename):
                tax_filename = secure_filename(tax_file.filename)
                tax_filepath = os.path.join(upload_folder, tax_filename)
                tax_file.save(tax_filepath)
            food_safety_file = request.files.get("food_safety_licience")
            food_safety_filename = None
            if food_safety_file and food_safety_file.filename != "" and allowed_file(food_safety_file.filename):
                food_safety_filename = secure_filename(food_safety_file.filename)
                food_safety_filepath = os.path.join(upload_folder, food_safety_filename)
                food_safety_file.save(food_safety_filepath)
            address_file = request.files.get("address_proof")
            address_filename = None
            if address_file and address_file.filename != "" and allowed_file(address_file.filename):
                address_filename = secure_filename(address_file.filename)
                address_filepath = os.path.join(upload_folder, address_filename)
                address_file.save(address_filepath)
            recipient_org_file = request.files.get("recipient_org_profile")
            org_profile_filename = None
            if recipient_org_file and recipient_org_file.filename != "" and allowed_file(recipient_org_file.filename):
                org_profile_filename = secure_filename(recipient_org_file.filename)
                org_profile_path = os.path.join(upload_folder, org_profile_filename)
                recipient_org_file.save(org_profile_path)
            insert_recipient = """
                INSERT INTO recipient_profile 
                    (recipient_id, recipient_profile_id, licience, org_name, org_type, org_profile, description, status, 
                    tax_proof, food_safety_licience, address_proof, org_capacity) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_recipient, (
                user_id, recipient_profile_id, licence_filename, org_name, org_type, org_profile_filename, 
                description, "Pending", tax_filename, food_safety_filename, address_filename, org_capacity
            ))
        
        conn.commit()
        flash("Registration successful!", "success")
        return redirect(url_for("auth.login_page"))
        
    except mysql.connector.Error as e:
        conn.rollback()
        flash(f"Database error: {str(e)}", "danger")
        return render_template("auth/register.html", form=request.form)
    except Exception as e:
        conn.rollback()
        flash(f"An error occurred: {str(e)}", "danger")
        return render_template("auth/register.html", form=request.form)
    finally:
        cursor.close()
        conn.close()

# ---------------- CAPTCHA HELPER ----------------
def gen_captcha():
    return ''.join(random.choices(string.ascii_uppercase + string.digits + string.ascii_lowercase, k=5))

# ---------------- LOGIN PAGE ----------------
@auth_bp.route("/login", methods=["GET"])
def login_page():
    captcha_text = gen_captcha()
    session["captcha_text"] = captcha_text
    return render_template("auth/login.html", captcha_text=captcha_text)


@auth_bp.route("/captcha", methods=["GET"])
def refresh_captcha():
    captcha_text = gen_captcha()
    session["captcha_text"] = captcha_text
    return jsonify({"captcha": captcha_text})


# ---------------- LOGIN API ----------------
@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    captcha_input = data.get("captcha", "").strip().upper()

    # ---- Captcha ----
    if captcha_input != (session.get("captcha_text") or "").upper():
        return jsonify({"success": False, "message": "Invalid captcha"}), 400

    # ---- Admin login ----
    ADMIN_EMAIL = "admin@gmail.com"
    ADMIN_PASSWORD = "admin123"
    ADMIN_DISPLAY_NAME = "ADMIN"

    if email.lower() == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
        session.clear()
        session["user_id"] = "admin"
        session["username"] = ADMIN_DISPLAY_NAME
        session["role"] = ["Admin"]   # always a list
        return jsonify({
            "success": True,
            "message": "Login successful",
            "redirect": url_for("admin.dashboard")
        }), 200

    # ---- Normal user login ----
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if not user or not check_password_hash(user["password"], password):
            return jsonify({"success": False, "message": "Invalid email or password"}), 401

        # check user request status
        cursor.execute("SELECT status FROM user_requests WHERE user_id=%s", (user["user_id"],))
        req = cursor.fetchone()
        
        # ---- First-time login → create request ----
        if not req:
            cursor.execute(
                "INSERT INTO user_requests (user_id, message, status) VALUES (%s, %s, %s)",
                (user["user_id"], "New user login request", "Pending")
            )
            cursor.execute("UPDATE users SET status='Pending' WHERE user_id=%s", (user["user_id"],))
            conn.commit()

            session.clear()
            session["user_id"] = str(user["user_id"])
            session["username"] = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user["email"]
            session["user_profile"]=user["user_profile"]
            # ---- Convert SET/ENUM safely ----
            role_value = user.get("role")
            if isinstance(role_value, set):
                session["role"] = list(role_value)
            elif role_value:
                session["role"] = [str(role_value)]
            else:
                session["role"] = []

            return jsonify({
                "success": True,
                "message": "Your account is pending admin approval.",
                "redirect": url_for("recipient.profile")
            }), 200

        # ---- Pending ----
        if req["status"] == "Pending":
            session.clear()
            session["user_id"] = str(user["user_id"])
            session["username"] = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user["email"]
            session["user_profile"]=user["user_profile"]
            role_value = user.get("role")
            if isinstance(role_value, set):
                session["role"] = list(role_value)
            elif role_value:
                session["role"] = [str(role_value)]
            else:
                session["role"] = []

            return jsonify({
                "success": True,
                "message": "Your account is still pending admin approval. You can view your profile.",
                "redirect": url_for("recipient.profile")
            }), 200

        # ---- Approved → Active ----
        cursor.execute("UPDATE users SET status='Active' WHERE user_id=%s", (user["user_id"],))
        conn.commit()

        # ---- Determine roles dynamically ----
        roles = []

        cursor.execute("SELECT COUNT(*) AS c FROM donors_profile WHERE donor_id=%s AND is_deleted=0",
                       (user["user_id"],))
        if cursor.fetchone()["c"] > 0:
            roles.append("Donor")

        cursor.execute("SELECT COUNT(*) AS c FROM recipient_profile WHERE recipient_id=%s AND is_deleted=0",
                       (user["user_id"],))
        if cursor.fetchone()["c"] > 0:
            roles.append("Recipient")

        # fallback to users.role
        if not roles and user.get("role"):
            role_value = user["role"]
            if isinstance(role_value, set):
                roles.extend(list(role_value))
            else:
                roles.append(str(role_value))

        # make unique + ensure list
        roles = list(dict.fromkeys(roles))

        # ---- Session ----
        session.clear()
        session["user_id"] = str(user["user_id"])
        session["username"] = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user["email"]
        session["user_profile"]=user["user_profile"]
        session["role"] = roles   # always list
        
        # ---- Redirect ----
        if "Donor" in roles and "Recipient" in roles:
            dest = url_for("donor.dashboard")
        elif "Donor" in roles:
            dest = url_for("donor.dashboard")
        elif "Recipient" in roles:
            dest = url_for("recipient.dashboard")
        else:
            dest = url_for("home")

        return jsonify({
            "success": True,
            "message": "Login successful",
            "redirect": dest
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

    finally:
        cursor.close()
        conn.close()

# ---------------- LOGOUT ----------------
@auth_bp.route('/logout')
def logout():
    user_id = session.get("user_id")

    # Set status to Inactive for normal users
    if user_id and user_id != "admin":
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET status='Inactive' WHERE user_id=%s", (user_id,))
            conn.commit()
        except Exception as e:
            current_app.logger.error(f"Error setting user inactive: {e}")
        finally:
            cursor.close()
            conn.close()

    session.clear()
    flash("Logged out successfully!", "info")
    return redirect(url_for('auth.login_page'))
# -------------forget password --------------------------
@auth_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("auth/forgot_password.html")

    email = request.form.get("email", "").strip()
    if not email:
        flash("Please enter your email address.", "danger")
        return redirect(url_for("auth.forgot_password"))

    # check user exists
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not user:
        flash("Email not registered!", "danger")
        return redirect(url_for("auth.forgot_password"))

    # create serializer here using the app's secret key (not blueprint)
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = serializer.dumps(email, salt="password-reset-salt")
    reset_link = url_for("auth.reset_password", token=token, _external=True)

    # prepare email
    msg = Message(subject="Password Reset Request",
                  sender=current_app.config.get('MAIL_USERNAME'),
                  recipients=[email])
    msg.body = (
        f"Hello,\n\nClick the link below to reset your password:\n\n{reset_link}\n\n"
        "This link will expire in 1 hour.\n\nIf you didn't request this, ignore this email."
    )

    # get the mail instance created in app.py
    mail = current_app.extensions.get('mail')
    if mail is None:
        # Defensive fallback — should not be needed if app.py did Mail(app)
        from flask_mail import Mail
        mail = Mail(current_app)

    try:
        mail.send(msg)
        flash("Reset link has been sent to your email.", "success")
    except Exception as e:
        current_app.logger.error(f"Failed to send reset email: {e}")
        flash("Failed to send email. Please try again later.", "danger")

    return redirect(url_for("auth.login_page"))


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    # validate token inside request context
    try:
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        email = serializer.loads(token, salt="password-reset-salt", max_age=3600)
    except SignatureExpired:
        flash("The reset link has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("The reset link is invalid.", "danger")
        return redirect(url_for("auth.forgot_password"))
    except Exception:
        flash("The reset link is invalid.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not password or not confirm:
            flash("Please fill in all fields.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if password != confirm:
            flash("Passwords do not match!", "danger")
            return render_template("auth/reset_password.html", token=token)

        hashed = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET password = %s WHERE email = %s", (hashed, email))
            conn.commit()
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"DB error resetting password: {e}")
            flash("Server error. Please try again later.", "danger")
            return render_template("auth/reset_password.html", token=token)
        finally:
            cursor.close()
            conn.close()

        flash("Password reset successful! Please log in.", "success")
        return redirect(url_for("auth.login_page"))

    return render_template("auth/reset_password.html", token=token)