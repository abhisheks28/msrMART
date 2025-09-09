import os
from dotenv import load_dotenv
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from supabase import create_client, Client
import uuid # Import the uuid module
from flask_mail import Mail # Import Flask-Mail

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

# Initialize extensions
db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
mail = Mail() # Initialize Flask-Mail

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase_client: Client = create_client(supabase_url, supabase_key)

def create_app():
    # Create the app
    app = Flask(__name__)
    app.secret_key = os.environ.get("SESSION_SECRET")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Configure the database
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    
    # Configure Supabase credentials
    app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL")
    app.config["SUPABASE_KEY"] = os.environ.get("SUPABASE_KEY")
    app.config["SUPABASE_PRODUCTS_BUCKET"] = os.environ.get("SUPABASE_PRODUCTS_BUCKET", "product-images") # Default to 'product-images'
    app.config["SUPABASE_SERVICE_ROLE_KEY"] = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    # Configure Flask-Mail
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT' or 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app) # Initialize Flask-Mail with the app
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # Import and register blueprints
    from routes import main_bp
    from auth import auth_bp
    # from api import api_bp # Commented out as api.py not found or not in use
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    # from api import api_bp # Commented out as api.py not found or not in use
    # app.register_blueprint(api_bp) # Commented out as api.py not found or not in use

    @login_manager.user_loader
    def load_user(user_id):
        from models import User # Import User model inside to avoid circular imports
        return User.query.get(user_id)

    @app.context_processor
    def inject_global_data():
        from models import Category
        all_categories = Category.query.all()
        return dict(all_categories=all_categories)
    
    return app # Return the app instance for Gunicorn

def init_db_and_admin(app):
    with app.app_context():
        # Import models to ensure they are registered
        import models
        
        # Create tables
        db.create_all()
        
        # Add default categories if they don't exist
        from models import Category
        default_categories = [
            "Electronics", "Books", "Clothing", "Home & Kitchen", "Beauty & Personal Care",
            "Sports & Outdoors", "Toys & Games", "Automotive", "Pet Supplies", "Health & Household",
            "Movies & TV", "Music", "Video Games", "Garden & Outdoor", "Baby Products",
            "Office Products", "Industrial & Scientific", "Handmade", "Collectibles & Fine Art"
        ]
        for cat_name in default_categories:
            if not Category.query.filter_by(name=cat_name).first():
                category = Category(name=cat_name, description=f'{cat_name} products')
                db.session.add(category)
        db.session.commit()
        
        # Create default admin user if it doesn't exist
        from models import User
        from werkzeug.security import generate_password_hash
        
        admin_user = User.query.filter_by(email='admin@msrshop.com').first()
        if not admin_user:
            admin_user = User(
                id=str(uuid.uuid4()), # Generate a UUID for the admin user
                name='System Admin',
                email='admin@msrshop.com',
                password_hash=generate_password_hash('admin123'),
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()
            logging.info("Default admin user created: admin@msrshop.com / admin123")

if __name__ == '__main__':
    app = create_app()
    init_db_and_admin(app)
    app.run(debug=True)
