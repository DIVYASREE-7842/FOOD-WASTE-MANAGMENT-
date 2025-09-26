from flask import Flask, render_template,session,g,url_for,jsonify,request
from flask_mail import Mail
import mysql.connector
import os
# import request
from mysql.connector import Error
# ---------------- BLUEPRINT IMPORTS ----------------
from auth import auth_bp
from admin import admin_bp
from donors.donors import donor_bp
from recipient import recipient_bp

# ---------------- APP INITIALIZATION ----------------
app = Flask(__name__)

# ---------------- SECRET KEY ----------------
app.config['SECRET_KEY'] = 'supersecretkey'   # change in production

# ---------------- DATABASE CONNECTION ----------------
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="7842557971",
        database="food_db"
    )
get_db=get_db_connection()
cursor = get_db.cursor(dictionary=True)

# ---------------- MAIL CONFIG ----------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'lovelydivya977@gmail.com'
app.config['MAIL_PASSWORD'] = 'mwfy rurs axrd puhz'  


# Initialize Flask-Mail
mail = Mail(app)
app.extensions['mail'] = mail
# ---------------- FILE UPLOAD CONFIG ----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# ---------------- BLUEPRINT REGISTRATION ----------------
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(donor_bp, url_prefix="/donor")
app.register_blueprint(recipient_bp, url_prefix="/recipient")

# ---------------- ROUTES ----------------
@app.route('/')
def home():
    get_db=get_db_connection()
    cursor=get_db.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS active_donors FROM users WHERE role LIKE '%Donor%' AND status='Active' AND is_deleted=0")
    active_donors = cursor.fetchone()['active_donors']
    cursor.execute("SELECT COUNT(*) AS active_recipients FROM users WHERE role= 'Recipient' AND status='Active' AND is_deleted=0")
    active_recipients = cursor.fetchone()['active_recipients']
    cursor.execute("""
        SELECT DATE(prepared_at) AS save_date, 
               SUM(quantity) AS total_saved
        FROM donations
        WHERE status='open' AND is_deleted = 0
        GROUP BY DATE(prepared_at)
        ORDER BY save_date
    """)
    saved_rows = cursor.fetchall()
    saved_labels = [r['save_date'].strftime("%Y-%m-%d") for r in saved_rows]
    saved_values = [r['total_saved'] for r in saved_rows]
    print("active re",active_recipients)
    print("activedonor",active_donors)
    print("saved",saved_rows)
    # print("saved labels",saved_labels)
    # print("saved_values",saved_values)
    return render_template(
        "index.html",
        # total_donors=total_donors,
        # total_recipients=total_recipients,
        active_donors=active_donors,
        active_recipients=active_recipients,
        saved_labels=saved_labels,
        saved_values=saved_values,
        saved_data=saved_rows,
    )
@app.route('/about')
def about():
    return render_template('about.html')


# ---------- NOTIFICATIONS GLOABALY ---------------
@app.context_processor
def inject_notifications():
    user_id = session.get('user_id')
    roles = session.get('role', [])
    g.roles = roles  # optional

    if not user_id:
        return dict(notifications=[], unread_count=0, roles=roles)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    notifications = []
    unread_count = 0

    if 'Donor' in roles:
        # Donor notifications from notifications table
        cursor.execute("""
            SELECT notification_id, message, is_read, created_at, reference_request_id
            FROM notifications
            WHERE reference_user_id=%s AND is_read=0
            ORDER BY created_at DESC
        """, (user_id,))
        notif_data = cursor.fetchall()

        # Pending requests
        cursor.execute("""
            SELECT r.request_id AS notification_id,
                   r.request_id AS request_id,
                   CONCAT('New request from recipient: ', u.first_name, ': ', r.quantity, ' ', r.food_type) AS message,
                   0 AS is_read,
                   r.created_at
            FROM request_to r
            JOIN users u ON r.recipient_id = u.user_id
            WHERE r.donor_id=%s AND r.status='PENDING'
        """, (user_id,))
        request_data = cursor.fetchall()

        # Add URLs
        for n in notif_data + request_data:
            # unify request_id key
            if 'reference_request_id' in n:
                n['request_id'] = n['reference_request_id']

            n['url'] = url_for('donor.mark_notification_read', notif_id=n['notification_id'])

        notifications = notif_data + request_data

    elif 'Recipient' in roles:
        # Recipient notifications
        cursor.execute("""
            SELECT notification_id, message, created_at, is_read, reference_request_id
            FROM notifications
            WHERE reference_user_id=%s AND is_read=0
            ORDER BY created_at DESC
        """, (user_id,))
        notifications = cursor.fetchall()

        # unify request_id key
        for n in notifications:
            if 'reference_request_id' in n:
                n['request_id'] = n['reference_request_id']
            n['notif_id'] = n['notification_id']
            n['url'] = url_for('recipient.mark_notification_read', notif_id=n['notif_id'])

    # Sort and count unread
    notifications.sort(key=lambda x: x['created_at'], reverse=True)
    unread_count = sum(1 for n in notifications if n['is_read'] == 0)

    cursor.close()
    conn.close()
    return dict(notifications=notifications[:4], unread_count=unread_count, roles=roles)

# 
@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/contact')
def contact():
    return render_template('contactus.html')


# Route to handle form submission
@app.route('/submit_contact', methods=['POST'])
def submit_contact():
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        subject = request.form.get('subject')
        message = request.form.get('message')

        # Basic server-side validation
        if not name or not email or not subject or not message:
            return jsonify({'success': False, 'message': 'Please fill in all required fields.'})

        # Save to database
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO contacts (name, email, phone, subject, message)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (name, email, phone, subject, message))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Message submitted successfully!'})

    except Error as e:
        print("Database Error:", e)
        return jsonify({'success': False, 'message': 'Database error occurred. Please try again.'})


# ---------------- MAIN ----------------
if __name__ == '__main__':
    app.run(debug=True)
