from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db, supabase_client # Import supabase_client
from models import User
import secrets
import string

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(email=email, is_active=True).first()
        
        if user and check_password_hash(user.password_hash, password):
            # Sign in with Flask-Login
            login_user(user)

            # Sign in with Supabase Auth
            try:
                supabase_response = supabase_client.auth.sign_in_with_password({
                    "email": email,
                    "password": password,
                })
                if supabase_response.user and supabase_response.session:
                    session['supabase_jwt'] = supabase_response.session.access_token
                    session['supabase_refresh_token'] = supabase_response.session.refresh_token
                    flash(f'Welcome back, {user.name}! Supabase session established.', 'success')
                else:
                    flash('Supabase login failed, but local login successful.', 'warning')
            except Exception as e:
                current_app.logger.error(f"Supabase login error: {e}")
                flash(f'Supabase login failed: {str(e)}', 'warning')

            # Redirect based on user role
            if user.role == 'admin':
                return redirect(url_for('main.admin_dashboard'))
            elif user.role == 'super_admin':
                return redirect(url_for('main.super_admin_dashboard'))
            else:
                return redirect(url_for('main.index'))
        else:
            flash('Invalid email or password.', 'error')
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        unique_code = request.form.get('unique_code', '').strip()
        
        # Validation
        if not all([name, email, password, confirm_password]):
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('register.html')
        
        # Initialize user object to None
        user_to_register = None

        # Handle super admin registration with unique code
        if unique_code:
            # Try to find a pre-registered, inactive super admin with matching email and unique code
            admin_user = User.query.filter_by(email=email, unique_code=unique_code, role='super_admin', is_active=False).first()
            if admin_user:
                user_to_register = admin_user
                user_to_register.is_active = True # Activate the account
                # Role is already 'super_admin', no need to set again
            else:
                flash('Invalid unique code or email combination for Super Admin registration.', 'error')
                return render_template('register.html')
        else:
            # Handle regular customer registration
            # Check if email already exists for an active user (customers are active by default)
            if User.query.filter_by(email=email, is_active=True).first():
                flash('Email already registered. Please use a different email.', 'error')
                return render_template('register.html')
            
            user_to_register = User(
                name=name,
                email=email,
                role='customer',
                is_active=True # Customers are active by default
            )
        
        # Set password for the user, whether new or pre-existing super admin
        if user_to_register:
            user_to_register.password_hash = generate_password_hash(password)
        else:
            # This case should ideally not be reached if validation is correct
            flash('Registration failed due to an unexpected error.', 'error')
            return render_template('register.html')

        try:
            db.session.add(user_to_register) # Add/update the user in the session
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            
            # Register user with Supabase Auth as well
            try:
                supabase_response = supabase_client.auth.sign_up({
                    "email": user_to_register.email,
                    "password": password,
                    "options": {
                        "data": {"name": name, "role": user_to_register.role}
                    }
                })
                if supabase_response.user and supabase_response.session:
                    session['supabase_jwt'] = supabase_response.session.access_token
                    session['supabase_refresh_token'] = supabase_response.session.refresh_token
                    flash('Registration successful with Supabase! Please log in.', 'success')
                else:
                    flash('Local registration successful, but Supabase registration failed.', 'warning')
            except Exception as e:
                current_app.logger.error(f"Supabase registration error: {e}")
                flash(f'Local registration successful, but Supabase registration failed: {str(e)}', 'warning')

            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {e}") # Log the actual error
            flash('Registration failed. Please try again.', 'error')
    
    return render_template('register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.index'))
