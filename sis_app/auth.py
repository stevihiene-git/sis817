from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from .models import User, Student, Course, CourseRegistration, Score, Payment, is_financially_cleared, SecurityAudit
import re
import secrets

# Blueprint configuration
auth_bp = Blueprint('auth', __name__, template_folder='templates')  # Changed from 'public' to 'templates'


# Password validation function
def validate_password(password):
    """
    Validate password strength
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"

    return True, "Password is valid"


# Email validation function
def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


# ⚠️ IMPORTANT: Define log_login_attempt BEFORE it's used in the login function
def log_login_attempt(user, status):
    """Log login attempts for security auditing"""
    new_log = SecurityAudit(
        user_id=user.id if user else None,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else None,
        is_suspicious=(status == 'failed')  # Mark failed attempts as suspicious
    )
    db.session.add(new_log)
    db.session.commit()


# Helper function to get the appropriate dashboard route
def get_dashboard_route():
    """Return the appropriate dashboard route based on user role"""
    if not current_user.is_authenticated:
        return url_for('views.index')

    role_routes = {
        'Admin': 'views.admin_dashboard',
        'Student': 'views.student_dashboard',
        'Lecturer': 'views.lecturer_dashboard',
        'Finance': 'views.finance_dashboard'
    }

    return url_for(role_routes.get(current_user.role, 'views.index'))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(get_dashboard_route())

    if request.method == 'POST':
        unique_id = request.form.get('unique_id', '').strip()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        errors = []
        if not all([unique_id, name, email, password, confirm_password]):
            errors.append('All fields are required')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if not validate_email(email):
            errors.append('Please enter a valid email address')

        is_valid_password, password_error = validate_password(password)
        if not is_valid_password:
            errors.append(password_error)

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('signup.html', unique_id=unique_id, name=name, email=email)

        # Check if user exists
        user = User.query.filter_by(unique_id=unique_id).first()
        if not user:
            flash('Unique ID not found. Please contact admin to be added.', 'error')
            return render_template('signup.html', unique_id=unique_id, name=name, email=email)

        if user.is_active:
            flash('Account already activated. Please log in.', 'error')
            return redirect(url_for('auth.login'))

        if User.query.filter_by(email=email).first():
            flash('Email already in use by another account.', 'error')
            return render_template('signup.html', unique_id=unique_id, name=name, email=email)

        # Update user
        try:
            user.name = name
            user.email = email
            user.password_hash = generate_password_hash(password)
            user.is_active = True
            user.must_change_password = True

            # Create student record if needed
            if user.role == 'Student' and not Student.query.filter_by(user_id=user.id).first():
                student = Student(user_id=user.id, balance=0.0)
                db.session.add(student)

            db.session.commit()
            flash('Profile completed successfully! You can now log in.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            flash('Error completing profile. Please try again.', 'error')
            return render_template('signup.html', unique_id=unique_id, name=name, email=email)

    return render_template('signup.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(get_dashboard_route())

    if request.method == 'POST':
        unique_id = request.form.get('unique_id', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me') == 'on'

        if not unique_id or not password:
            flash('Unique ID and password are required', 'error')
            return render_template('login.html', unique_id=unique_id)

        user = User.query.filter_by(unique_id=unique_id).first()

        # Security: Use constant-time comparison to prevent timing attacks
        if user and user.is_active:
            if check_password_hash(user.password_hash, password):
                # 🔒 LOG SUCCESSFUL LOGIN ATTEMPT
                log_login_attempt(user, 'success')
                
                login_user(user, remember=remember_me)
                session.permanent = True
                session.modified = True
                session['_fresh'] = True

                if user.must_change_password:
                    flash('Please change your password for security reasons.', 'info')
                    return redirect(url_for('auth.change_password'))

                flash(f'Welcome back, {user.name}!', 'success')
                return redirect(get_dashboard_route())
            else:
                # 🔒 LOG FAILED LOGIN ATTEMPT (wrong password)
                log_login_attempt(user, 'failed')
        else:
            # 🔒 LOG FAILED LOGIN ATTEMPT (user not found or inactive)
            log_login_attempt(None, 'failed')

        # Generic error message to prevent user enumeration
        flash('Invalid credentials. Please check your Unique ID and password.', 'error')
        return render_template('login.html', unique_id=unique_id)

    return render_template('login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    user_name = current_user.name
    logout_user()
    session.clear()
    flash(f'Goodbye, {user_name}! You have been logged out successfully.', 'success')
    return redirect(url_for('views.index'))


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        errors = []

        if not all([current_password, new_password, confirm_password]):
            errors.append('All fields are required')

        if new_password != confirm_password:
            errors.append('New passwords do not match')

        is_valid_password, password_error = validate_password(new_password)
        if not is_valid_password:
            errors.append(password_error)

        # Verify current password
        if not check_password_hash(current_user.password_hash, current_password):
            errors.append('Current password is incorrect')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('change_password.html')

        # Update password
        try:
            user = db.session.get(User, current_user.id)
            user.password_hash = generate_password_hash(new_password)
            user.must_change_password = False
            db.session.commit()

            flash('Password changed successfully!', 'success')
            return redirect(get_dashboard_route())

        except Exception as e:
            db.session.rollback()
            flash('Error changing password. Please try again.', 'error')
            return render_template('change_password.html')

    return render_template('change_password.html')


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(get_dashboard_route())

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Email is required', 'error')
            return render_template('forgot_password.html', email=email)

        if not validate_email(email):
            flash('Please enter a valid email address', 'error')
            return render_template('forgot_password.html', email=email)

        user = User.query.filter_by(email=email, is_active=True).first()

        # Always show success message even if email doesn't exist
        # to prevent email enumeration attacks
        flash('If that email address is in our system, we have sent a password reset link.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')