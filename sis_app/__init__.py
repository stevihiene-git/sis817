from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate  # ADD THIS IMPORT
from werkzeug.security import generate_password_hash
import os
import secrets
import logging
from datetime import timedelta

# Create the core application instance and extensions
app = Flask(__name__, template_folder='templates')
# app.config["SQLALCHEMY_DATABASE_URI"]= "postgresql://neondb_owner:npg_v7RP1oKYmFwM@ep-bold-mud-adroxeim-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
app.config["SQLALCHEMY_DATABASE_URI"]= "postgresql://neondb_owner:npg_0pkAG6wWIQej@ep-bold-mud-adroxeim-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()  # # Initialize Migrate

# Configuration
app.config['SECRET_KEY'] =  "2d2c5c6476929240e999d4487136ecf06f223dc9e7c381272bf7ae4eaf0c13ab" #  os.environ.get('SECRET_KEY') or secrets.token_hex(32)
# app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///sis.db'
app.config["SQLALCHEMY_DATABASE_URI"]= "postgresql://neondb_owner:npg_0pkAG6wWIQej@ep-bold-mud-adroxeim-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_PROTECTION'] = 'strong'
app.config['WTF_CSRF_ENABLED'] = True

# Initialize app extensions
db.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'
login_manager.session_protection = 'strong'
login_manager.init_app(app)
csrf.init_app(app)
migrate.init_app(app, db)  # ADD THIS LINE - CRUCIAL!

# Import models to define them before creating tables
from . import models

# CRITICAL: Add the user_loader function
@login_manager.user_loader
def load_user(user_id):
    """This function is required by Flask-Login to load a user from the user ID"""
    try:
        return db.session.get(models.User, int(user_id))
    except Exception as e:
        logging.error(f"Error loading user {user_id}: {str(e)}")
        return None

# Import and regi
# ster blueprints
from .auth import auth_bp
from .views import views_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(views_bp, url_prefix='/')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return "Internal server error", 500

# Context processors
@app.context_processor
def inject_user():
    """Make current_user available to all templates"""
    from flask_login import current_user
    return dict(current_user=current_user)

@app.context_processor
def inject_roles():
    """Make roles available to all templates"""
    return dict(roles=['Admin', 'Student', 'Lecturer', 'Finance'])

# --- Database Initialization ---
def init_db():
    """Initialize the database with required data"""
    with app.app_context():
        try:
            logging.info("Creating database tables")
            db.create_all()
            logging.info("Database tables created")

            # Create Super Admin if not exists
            if not models.User.query.filter_by(unique_id='SUPERADMIN').first():
                super_admin = models.User(
                    email='superadmin@sis.edu',
                    password_hash=generate_password_hash('Admin123!'),
                    name='Super Administrator',
                    role='Admin',
                    unique_id='SUPERADMIN',
                    is_active=True,
                    must_change_password=False,
                    faculty='Administration',
                    department='System Administration'
                )
                db.session.add(super_admin)
                db.session.commit()
                logging.info("Super admin created")

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error initializing database: {str(e)}")
            raise


@app.route('/debug/secret-key')
def debug_secret_key():
    import os
    current_key = os.environ.get('SECRET_KEY') or "Not set in environment"
    generated_key = "Would generate: " + secrets.token_hex(32) if not os.environ.get('SECRET_KEY') else ""
    return f"""
    <h1>Secret Key Debug</h1>
    <p>Environment SECRET_KEY: <strong>{current_key}</strong></p>
    <p>{generated_key}</p>
    <p>App config SECRET_KEY: <strong>{app.config['SECRET_KEY']}</strong></p>
    """

# Initialize database when app starts
init_db()
