from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session, make_response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from models import User, Product, Category, Order, OrderItem, Cart, Wishlist, Payment, ProductImage, Address
from utils import admin_required, super_admin_required, generate_unique_code, allowed_file
import os
from datetime import datetime, timedelta
from sqlalchemy import func, desc
from app import supabase_client
import io
from supabase.lib.client_options import ClientOptions
import uuid # Import the uuid module
import json # Import the json module
import csv # Import the csv module
# import requests # Removed as EmailJS is no longer used for backend
from flask_mail import Message
from app import mail # Import the mail instance

main_bp = Blueprint('main', __name__)

def get_authenticated_supabase_client(): # Removed use_service_role parameter
    from supabase import create_client
    supabase_url = current_app.config["SUPABASE_URL"]
    supabase_key = current_app.config["SUPABASE_KEY"]
    
    jwt = session.get('supabase_jwt')
    refresh_token = session.get('supabase_refresh_token')
    current_app.logger.debug(f"Initial Supabase JWT: {jwt[:10] + '...' if jwt else 'None'}, Refresh Token: {refresh_token[:10] + '...' if refresh_token else 'None'}")

    if not jwt and not refresh_token:
        current_app.logger.error("Supabase session not found. Both JWT and Refresh Token are missing.")
        flash('Supabase session not found. Please log in again.', 'error')
        return None

    # Attempt to refresh session if JWT is missing or potentially expired
    if not jwt and refresh_token:
        current_app.logger.info("Attempting to refresh Supabase session...")
        try:
            refresh_response = supabase_client.auth.refresh_session(refresh_token)
            if refresh_response.user and refresh_response.session:
                session['supabase_jwt'] = refresh_response.session.access_token
                session['supabase_refresh_token'] = refresh_response.session.refresh_token
                jwt = session['supabase_jwt'] # Update jwt with the new token
                current_app.logger.info(f"Supabase session refreshed successfully. New JWT: {jwt[:10] + '...'}, New Refresh Token: {session['supabase_refresh_token'][:10] + '...'}")
            else:
                current_app.logger.error(f"Supabase session refresh failed: {refresh_response.raw_response}")
                flash('Supabase session expired. Please log in again.', 'error')
                return None
        except Exception as e:
            current_app.logger.error(f"Exception during Supabase session refresh: {e}")
            flash('Supabase session expired. Please log in again.', 'error')
            return None
    
    # If still no JWT after refresh attempt, return None
    if not jwt:
        current_app.logger.error("Supabase session could not be established after refresh attempt. JWT is still missing.")
        flash('Supabase session could not be established. Please log in again.', 'error')
        return None

    current_app.logger.debug(f"Final JWT used for Supabase client: {jwt[:10] + '...'}")
    # Use ClientOptions to pass headers correctly
    options = ClientOptions()
    options.headers = {"Authorization": f"Bearer {jwt}"}
    return create_client(supabase_url, supabase_key, options=options)


@main_bp.route('/')
def index():
    # Get featured products (latest 8 products)
    featured_products = Product.query.filter_by(is_active=True).order_by(desc(Product.created_at)).limit(8).all()
    categories = Category.query.filter(Category.name != 'Handmade').all()
    
    # Get slider images
    slider_folder = os.path.join(current_app.root_path, 'static', 'Slider')
    slider_images = []
    if os.path.exists(slider_folder):
        for filename in os.listdir(slider_folder):
            if filename.lower().endswith( ('.png', '.jpg', '.jpeg', '.gif') ):
                slider_images.append(url_for('static', filename=f'Slider/{filename}'))

    # Get category icon images
    category_icons_folder = os.path.join(current_app.root_path, 'static', 'Cat')
    category_icon_map = {}
    if os.path.exists(category_icons_folder):
        for filename in os.listdir(category_icons_folder):
            if filename.lower().endswith( ('.png', '.jpg', '.jpeg', '.gif') ):
                # Assuming image filename matches category name (e.g., "Electronics.png" for "Electronics")
                category_name_from_file = os.path.splitext(filename)[0].replace(' ', '_').replace('&', 'and') # Normalize for matching
                category_icon_map[category_name_from_file] = url_for('static', filename=f'Cat/{filename}')

    # Attach icon URLs to categories
    categories_with_icons = []
    for category in categories:
        normalized_category_name = category.name.replace(' ', '_').replace('&', 'and')
        category_dict = {
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'icon_url': category_icon_map.get(normalized_category_name),
            'image_url': category_icon_map.get(normalized_category_name),
            'product_count': 1000 + category.id * 100 # Mock product count
        }
        categories_with_icons.append(category_dict)

    return render_template('index.html', 
                           featured_products=featured_products, 
                           categories=categories_with_icons,
                           slider_images=slider_images)

# Admin Routes
@main_bp.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    # Analytics data
    total_orders = Order.query.count()
    total_revenue = db.session.query(func.sum(Order.total_amount)).scalar() or 0
    total_users = User.query.filter_by(role='customer').count()
    total_super_admins = User.query.filter_by(role='super_admin').count()

    # Get time period from request, default to 'month'
    time_period = request.args.get('time_period', 'month')
    
    # Get monthly revenue for the chart from admin_revenue function with selected time_period
    monthly_revenue_data = admin_revenue_data_fetch(time_period) 

    # Only extract relevant data for the chart from monthly_revenue_data
    monthly_revenue_labels = [item['period'] for item in monthly_revenue_data]
    monthly_revenue_values = [item['revenue'] for item in monthly_revenue_data]
    
    # Top selling products
    top_products = db.session.query(
        Product.name, func.sum(OrderItem.quantity).label('total_sold')
    ).join(OrderItem).group_by(Product.id).order_by(desc('total_sold')).limit(5).all()
    top_products = [{ "name": p, "total_sold": s } for p, s in top_products]

    # Not Selling Products (sales_count is 0)
    not_selling_products = Product.query.filter_by(sales_count=0, is_active=True).limit(5).all()

    # Products by Category for the pie chart
    category_product_counts = db.session.query(Category.name, func.count(Product.id)) \
                                   .join(Product) \
                                   .group_by(Category.name).all()
    category_pie_labels = [data[0] for data in category_product_counts]
    category_pie_values = [data[1] for data in category_product_counts]

    # Create a zipped list of categories and their counts
    category_data = list(zip(category_pie_labels, category_pie_values))

    print(f"Category Pie Labels: {category_pie_labels}")
    print(f"Category Pie Values: {category_pie_values}")

    # Recent orders
    recent_orders = Order.query.order_by(desc(Order.created_at)).limit(10).all()
    recent_orders = [order.to_dict() for order in recent_orders] # Assuming Order model has a to_dict method

    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         total_revenue=total_revenue,
                         total_users=total_users,
                         total_super_admins=total_super_admins,
                         monthly_revenue_labels=monthly_revenue_labels, # Pass labels separately
                         monthly_revenue_values=monthly_revenue_values, # Pass values separately
                         top_products=top_products,
                         not_selling_products=not_selling_products,
                         category_data=category_data,
                         recent_orders=recent_orders,
                         time_period=time_period) # Pass time_period to template

def admin_revenue_data_fetch(time_period='month'):
    today = datetime.now().date()
    revenue_data = []

    if time_period == 'week':
        for i in range(7): # Last 7 days
            date = today - timedelta(days=i)
            day_start = datetime.combine(date, datetime.min.time())
            day_end = datetime.combine(date, datetime.max.time())
            
            revenue = db.session.query(func.sum(Payment.amount)).filter(
                Payment.payment_status == 'paid',
                Payment.created_at >= day_start,
                Payment.created_at <= day_end
            ).scalar() or 0
            
            revenue_data.append({
                'period': date.strftime('%Y-%m-%d'),
                'revenue': float(revenue)
            })
        revenue_data.reverse() # Show recent days first
    elif time_period == 'month':
        for i in range(30): # Last 30 days
            date = today - timedelta(days=i)
            day_start = datetime.combine(date, datetime.min.time())
            day_end = datetime.combine(date, datetime.max.time())
            
            revenue = db.session.query(func.sum(Payment.amount)).filter(
                Payment.payment_status == 'paid',
                Payment.created_at >= day_start,
                Payment.created_at <= day_end
            ).scalar() or 0
            
            revenue_data.append({
                'period': date.strftime('%Y-%m-%d'),
                'revenue': float(revenue)
            })
        revenue_data.reverse() # Show recent days first
    elif time_period == 'year':
        for i in range(12): # Last 12 months
            # Correct way to get the first day of the month 'i' months ago
            current_month = today.month
            current_year = today.year
            
            # Calculate target month and year
            target_month_num = current_month - i
            target_year_num = current_year
            while target_month_num <= 0:
                target_month_num += 12
                target_year_num -= 1
            
            target_month_start = datetime(target_year_num, target_month_num, 1)
            
            # Calculate the last day of the target month
            if target_month_num == 12:
                target_month_end = datetime(target_year_num + 1, 1, 1) - timedelta(microseconds=1)
            else:
                target_month_end = datetime(target_year_num, target_month_num + 1, 1) - timedelta(microseconds=1)

            revenue = db.session.query(func.sum(Payment.amount)).filter(
                Payment.payment_status == 'paid',
                Payment.created_at >= target_month_start,
                Payment.created_at <= target_month_end
            ).scalar() or 0
            
            revenue_data.append({
                'period': target_month_start.strftime('%Y-%m'),
                'revenue': float(revenue)
            })
        revenue_data.reverse() # Show recent months first

    return revenue_data


@main_bp.route('/admin/revenue')
@login_required
@admin_required
def admin_revenue():
    time_period = request.args.get('time_period', 'month') # Default to month
    
    revenue_data = admin_revenue_data_fetch(time_period)
    
    # Calculate total revenue for display
    overall_total_revenue = sum(item['revenue'] for item in revenue_data)

    return render_template('admin/revenue.html', 
                           revenue_data=revenue_data, # Pass the dynamic data
                           total_revenue=overall_total_revenue,
                           time_period=time_period) # Pass time_period for active state

@main_bp.route('/admin/super_admins')
@login_required
@admin_required
def admin_super_admins():
    super_admins = User.query.filter_by(role='super_admin').all()
    # Eagerly load categories for each super admin to prevent N+1 queries
    for super_admin in super_admins:
        super_admin.categories_list = list(super_admin.categories)
    categories = Category.query.all() # Fetch all categories
    return render_template('admin/super_admins.html', super_admins=super_admins, categories=categories)

@main_bp.route('/admin/download-revenue-csv')
@login_required
@admin_required
def download_revenue_csv():
    time_period = request.args.get('time_period', 'month')
    
    # Re-use the data fetching logic from admin_revenue_data_fetch
    revenue_data = admin_revenue_data_fetch(time_period)
    
    # Create CSV content in memory
    si = io.StringIO()
    cw = csv.writer(si)
    
    # Write headers
    cw.writerow(['Period', 'Revenue'])
    
    # Write data rows
    for item in revenue_data:
        cw.writerow([item['period'], f"{item['revenue']:.2f}"])
    
    output = si.getvalue()
    
    response = make_response(output)
    response.headers["Content-Disposition"] = f"attachment; filename=revenue_{time_period}.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@main_bp.route('/admin/create-super-admin', methods=['POST'])
@login_required
@admin_required
def create_super_admin():
    username = request.form.get('username')
    email = request.form.get('email')
    selected_category_ids = request.form.getlist('categories') # Get list of selected category IDs
    
    if not all([username, email, selected_category_ids]):
        flash('Please fill in all fields.', 'error')
        return redirect(url_for('main.admin_super_admins'))
    
    # Check if email already exists
    if User.query.filter_by(email=email).first():
        flash('Email already exists.', 'error')
        return redirect(url_for('main.admin_super_admins'))
    
    # Generate unique code
    unique_code = generate_unique_code()
    
    # Create admin user with unique code (they will register later)
    admin_user = User(
        id=str(uuid.uuid4()), # Generate a UUID for the super admin user
        name=username,
        email=email,
        password_hash='',  # Will be set during registration
        role='super_admin', # Ensure the role is super_admin
        unique_code=unique_code,
        is_active=False  # Will be activated after registration
    )
    
    # Associate selected categories with the super admin
    for category_id in selected_category_ids:
        category = Category.query.get(int(category_id))
        if category:
            admin_user.categories.append(category)
    
    try:
        db.session.add(admin_user)
        db.session.commit()
        flash(f'Super Admin created successfully! Unique code: {unique_code}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Failed to create Super Admin.', 'error')
    
    return redirect(url_for('main.admin_super_admins'))

@main_bp.route('/admin/toggle-super-admin/<string:user_id>')
@login_required
@admin_required
def toggle_super_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'super_admin':
        user.is_active = not user.is_active
        db.session.commit()
        status = 'activated' if user.is_active else 'deactivated'
        flash(f'Super Admin {status} successfully.', 'success')
    return redirect(url_for('main.admin_super_admins'))

@main_bp.route('/admin/super-admin/view/<string:user_id>')
@login_required
@admin_required
def admin_view_super_admin(user_id):
    super_admin = User.query.get_or_404(user_id)
    return render_template('admin/view_super_admin.html', super_admin=super_admin)

@main_bp.route('/admin/super-admin/delete/<string:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_super_admin(user_id):
    super_admin = User.query.get_or_404(user_id)
    if super_admin.role == 'super_admin':
        try:
            db.session.delete(super_admin)
            db.session.commit()
            flash('Super Admin deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to delete Super Admin: {str(e)}', 'error')
    else:
        flash('User is not a Super Admin.', 'error')
    return redirect(url_for('main.admin_super_admins'))

@main_bp.route('/admin/super-admin/edit/<string:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_super_admin(user_id):
    super_admin = User.query.get_or_404(user_id)
    all_categories = Category.query.all()

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        selected_category_ids = request.form.getlist('categories')
        is_active = request.form.get('is_active') == 'on'

        if not all([username, email, selected_category_ids]):
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('main.admin_edit_super_admin', user_id=user_id))
        
        # Check if email is taken by another user
        existing_user = User.query.filter_by(email=email).first()
        if existing_user and existing_user.id != super_admin.id:
            flash('Email already taken by another user.', 'error')
            return redirect(url_for('main.admin_edit_super_admin', user_id=user_id))
        
        super_admin.name = username
        super_admin.email = email
        super_admin.is_active = is_active
        
        # Update assigned categories
        super_admin.categories.clear()
        for cat_id in selected_category_ids:
            category = Category.query.get(int(cat_id))
            if category:
                super_admin.categories.append(category)
        
        try:
            db.session.commit()
            flash('Super Admin updated successfully!', 'success')
            return redirect(url_for('main.admin_super_admins'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to update Super Admin: {str(e)}', 'error')
            
    return render_template('admin/edit_super_admin.html', super_admin=super_admin, all_categories=all_categories)

# Super Admin Routes
@main_bp.route('/super-admin/dashboard')
@login_required
@super_admin_required
def super_admin_dashboard():
    # Get super admin's products and stats
    products_count = Product.query.filter_by(super_admin_id=current_user.id).count()
    
    # Orders for super admin's products
    orders_count = db.session.query(Order).join(OrderItem).join(Product).filter(
        Product.super_admin_id == current_user.id
    ).count()
    
    # Revenue from super admin's products
    revenue = db.session.query(func.sum(OrderItem.price * OrderItem.quantity)).join(Product).filter(
        Product.super_admin_id == current_user.id
    ).scalar() or 0
    
    # Low stock products (less than 10)
    low_stock_products = Product.query.filter_by(
        super_admin_id=current_user.id
    ).filter(Product.stock < 10).all()
    
    # Recent orders for super admin's products
    recent_orders = db.session.query(Order).join(OrderItem).join(Product).filter(
        Product.super_admin_id == current_user.id
    ).order_by(desc(Order.created_at)).limit(10).all()

    # High Demand Products (e.g., top 5 by sales_count)
    high_demand_products = Product.query.filter_by(super_admin_id=current_user.id) \
                                       .order_by(desc(Product.sales_count)) \
                                       .limit(5).all()

    # Products by Category for the graph
    category_data = db.session.query(Category.name, func.count(Product.id)) \
                            .join(Product) \
                            .filter(Product.super_admin_id == current_user.id) \
                            .group_by(Category.name).all()

    category_labels = [data[0] for data in category_data]
    category_values = [data[1] for data in category_data]

    return render_template('super_admin/dashboard.html',
                         products_count=products_count,
                         orders_count=orders_count,
                         revenue=revenue,
                         low_stock_products=low_stock_products,
                         recent_orders=recent_orders,
                         high_demand_products=high_demand_products,
                         category_labels=category_labels,
                         category_values=category_values)

@main_bp.route('/super-admin/products')
@login_required
@super_admin_required
def super_admin_products():
    sort_category = request.args.get('sort_category') # Get sort_category parameter

    query = Product.query.filter_by(super_admin_id=current_user.id)

    if sort_category:
        # Ensure we are filtering by a valid category assigned to the super admin
        category = Category.query.filter_by(name=sort_category).first()
        if category and category in current_user.categories:
            query = query.filter_by(category_id=category.id)
        else:
            flash(f'Category {sort_category} not found or not assigned to you.', 'warning')
            sort_category = None # Reset sort_category if invalid

    # Order by category name (if category is selected or default) then by product name
    products = query.join(Category).order_by(Category.name.asc(), Product.name.asc()).all()

    # Fetch all categories assigned to the current super admin for the filter dropdown
    categories = current_user.categories
    
    print(f"Products loaded for super admin: {[p.id for p in products]}") # Log loaded product IDs
    return render_template('super_admin/products.html', products=products, categories=categories, sort_category=sort_category)

@main_bp.route('/super-admin/add-product', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_product():
    authenticated_supabase_client = get_authenticated_supabase_client()
    if not authenticated_supabase_client:
        return redirect(url_for('auth.login')) # Redirect to login if no JWT

    # Fetch only categories assigned to the current super admin
    categories = current_user.categories
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        stock = request.form.get('stock')
        category_id = request.form.get('category_id')
        original_price = request.form.get('original_price')
        brand = request.form.get('brand')
        dimensions = request.form.get('dimensions')
        ratings = request.form.get('ratings')
        num_ratings = request.form.get('num_ratings')
        sales_count = request.form.get('sales_count')
        
        if not all([name, price, stock, category_id]):
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('main.add_product')) # Redirect on validation error
        
        # Validate that the selected category belongs to the super admin
        if int(category_id) not in [cat.id for cat in current_user.categories]:
            flash('Selected category is not assigned to you.', 'error')
            return redirect(url_for('main.add_product'))
        
        try:
            product = Product(
                name=name,
                description=description,
                price=float(price),
                stock=int(stock),
                category_id=int(category_id),
                super_admin_id=current_user.id,
                original_price=float(original_price) if original_price else None,
                brand=brand,
                dimensions=dimensions,
                ratings=float(ratings) if ratings else 0.0,
                num_ratings=int(num_ratings) if num_ratings else 0,
                sales_count=int(sales_count) if sales_count else 0
            )
            
            # Handle multiple image uploads
            files = request.files.getlist('images')
            uploaded_image_urls = []
            if files:
                for i, file in enumerate(files):
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
                        
                        # Upload to Supabase Storage
                        try:
                            bucket_name = current_app.config["SUPABASE_PRODUCTS_BUCKET"]
                            with io.BytesIO(file.read()) as data:
                                res = authenticated_supabase_client.storage.from_(bucket_name).upload(filename, data.getvalue(), {"content-type": file.content_type})
                            
                            # Supabase upload response is usually a dictionary on success with 'Key' or 'path', or raises exception on error
                            # Check if res is a dictionary and contains an error key (though client library usually raises exceptions for errors)
                            if isinstance(res, dict) and res.get('error'):
                                upload_error = res['error'].get('message', 'Unknown Supabase upload error')
                                current_app.logger.error(f"Supabase upload error for {filename}: {upload_error}")
                                raise Exception(upload_error)
                            
                            # Get public URL
                            public_url_response = authenticated_supabase_client.storage.from_(bucket_name).get_public_url(filename)
                            
                            image_url = public_url_response
                            uploaded_image_urls.append(image_url)
                        except Exception as e:
                            flash(f'Failed to upload image to Supabase: {str(e)}', 'error')
                            current_app.logger.error(f"Supabase upload exception: {e}")
                            # Optionally, skip this image and continue or return early
                            continue

                        # file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        # file.save(file_path)
                        # image_url = f"/static/uploads/{filename}"
                        
                        product_image = ProductImage(
                            image_url=image_url,
                            is_primary=(i == 0) # Set the first image as primary
                        )
                        product.product_images.append(product_image)

                if uploaded_image_urls:
                    product.image_url = uploaded_image_urls[0] # Set the primary image URL in the Product model
            
            db.session.add(product)
            db.session.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('main.super_admin_products'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to add product: {str(e)}', 'error')
    
    return render_template('super_admin/add_product.html', categories=categories)

@main_bp.route('/super-admin/edit-product/<string:product_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_product(product_id):
    authenticated_supabase_client = get_authenticated_supabase_client()
    if not authenticated_supabase_client:
        return redirect(url_for('auth.login')) # Redirect to login if no JWT

    product = Product.query.filter_by(id=product_id, super_admin_id=current_user.id).first_or_404()
    categories = current_user.categories # Fetch only categories assigned to the current super admin
    
    if request.method == 'POST':
        try:
            product.name = request.form.get('name')
            product.description = request.form.get('description')
            product.price = float(request.form.get('price'))
            product.stock = int(request.form.get('stock'))
            
            new_category_id = int(request.form.get('category_id'))
            # Validate that the selected category belongs to the super admin
            if new_category_id not in [cat.id for cat in current_user.categories]:
                flash('Selected category is not assigned to you.', 'error')
                return redirect(url_for('main.edit_product', product_id=product.id))
            
            product.category_id = new_category_id
            product.original_price = float(request.form.get('original_price')) if request.form.get('original_price') else None
            product.brand = request.form.get('brand')
            product.dimensions = request.form.get('dimensions')
            product.ratings = float(request.form.get('ratings')) if request.form.get('ratings') else 0.0
            product.num_ratings = int(request.form.get('num_ratings')) if request.form.get('num_ratings') else 0
            product.sales_count = int(request.form.get('sales_count')) if request.form.get('sales_count') else 0

            # Handle multiple image uploads for existing product
            files = request.files.getlist('images')
            if files:
                for i, file in enumerate(files):
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
                        
                        # Upload to Supabase Storage
                        try:
                            bucket_name = current_app.config["SUPABASE_PRODUCTS_BUCKET"]
                            with io.BytesIO(file.read()) as data:
                                res = authenticated_supabase_client.storage.from_(bucket_name).upload(filename, data.getvalue(), {"content-type": file.content_type})
                                    
                            if isinstance(res, dict) and res.get('error'):
                                upload_error = res['error'].get('message', 'Unknown Supabase upload error during edit')
                                current_app.logger.error(f"Supabase upload error for {filename} during edit: {upload_error}")
                                raise Exception(upload_error)

                            # Get public URL
                            public_url_response = authenticated_supabase_client.storage.from_(bucket_name).get_public_url(filename)
                            image_url = public_url_response
                        except Exception as e:
                            flash(f'Failed to upload image to Supabase: {str(e)}', 'error')
                            current_app.logger.error(f"Supabase upload exception during edit: {str(e)}")
                            continue

                        # file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        # file.save(file_path)
                        # image_url = f"/static/uploads/{filename}"
                        
                        product_image = ProductImage(
                            product_id=product.id,
                            image_url=image_url,
                            is_primary=(len(product.product_images) == 0 and i == 0) # Set as primary if no images exist and it's the first upload
                        )
                        db.session.add(product_image)
                        if len(product.product_images) == 0 and i == 0:
                            product.image_url = image_url # Update primary image if none existed

            
            db.session.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('main.super_admin_products')) # Redirect to products list after successful update
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to update product: {str(e)}', 'error')
    
    return render_template('super_admin/edit_product.html', product=product, categories=categories) # Render template for GET requests

@main_bp.route('/super-admin/delete-product/<int:product_id>')
@login_required
@super_admin_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, super_admin_id=current_user.id).first_or_404()
    print(f"Attempting to delete product with ID: {product.id}") # Log product ID
    
    try:
        db.session.delete(product)
        db.session.flush() # Added to ensure changes are pushed to the database
        db.session.commit()
        print(f"Product with ID: {product.id} deleted successfully.") # Log successful deletion
        flash('Product deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Failed to delete product with ID: {product.id}. Error: {str(e)}") # Log detailed error
        flash(f'Failed to delete product: {str(e)}', 'error') # More detailed error message
    
    return redirect(url_for('main.super_admin_products'))

@main_bp.route('/super-admin/orders')
@login_required
@super_admin_required
def super_admin_orders():
    # Get orders containing super admin's products
    orders = db.session.query(Order).join(OrderItem).join(Product).filter(
        Product.super_admin_id == current_user.id
    ).distinct().order_by(desc(Order.created_at)).all()
    
    return render_template('super_admin/orders.html', orders=orders)

@main_bp.route('/super-admin/update-order-status/<int:order_id>')
@login_required
@super_admin_required
def update_order_status(order_id):
    status = request.args.get('status')
    order = Order.query.get_or_404(order_id)
    
    if status in ['processing', 'shipped', 'delivered']:
        order.status = status
        db.session.commit()
        flash('Order status updated successfully!', 'success')
    else:
        flash('Invalid status.', 'error')
    
    return redirect(url_for('main.super_admin_orders'))

# Customer Routes
@main_bp.route('/products')
def products():
    category_id = request.args.get('category')
    search = request.args.get('search')
    sort_by = request.args.get('sort_by') # Get the sort_by parameter
    
    query = Product.query.filter_by(is_active=True)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if search:
        query = query.filter(Product.name.contains(search))
        
    # If no category or search is specified, order randomly
    if not category_id and not search:
        query = query.order_by(func.random())

    # Apply sorting based on sort_by parameter
    if sort_by == 'price_asc':
        query = query.order_by(Product.price.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(Product.price.desc())
    elif sort_by == 'name_asc':
        query = query.order_by(Product.name.asc())
    elif sort_by == 'name_desc':
        query = query.order_by(Product.name.desc())
    
    products = query.limit(20).all() # Limit the number of products fetched
    categories = Category.query.all()

    user_wishlist_ids = []
    if current_user.is_authenticated and current_user.role == 'customer':
        user_wishlist_ids = [item.product_id for item in Wishlist.query.filter_by(user_id=current_user.id).all()]
    
    return render_template('customer/products.html', 
                           products=products, 
                           categories=categories,
                           user_wishlist_ids=user_wishlist_ids)

@main_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    return render_template('customer/product_detail.html', product=product)

@main_bp.route('/add-to-cart/<int:product_id>')
@login_required
def add_to_cart(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    
    # Check if item already in cart
    cart_item = Cart.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    
    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = Cart(user_id=current_user.id, product_id=product_id, quantity=1)
        db.session.add(cart_item)
    
    db.session.commit()
    flash('Product added to cart!', 'success')
    return redirect(url_for('main.product_detail', product_id=product_id))

@main_bp.route('/cart')
@login_required
def cart():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in cart_items)
    return render_template('customer/cart.html', cart_items=cart_items, total=total)

@main_bp.route('/update-cart/<int:cart_id>')
@login_required
def update_cart(cart_id):
    action = request.args.get('action')
    cart_item = Cart.query.filter_by(id=cart_id, user_id=current_user.id).first_or_404()
    
    if action == 'increase':
        cart_item.quantity += 1
    elif action == 'decrease':
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
        else:
            db.session.delete(cart_item)
    elif action == 'remove':
        db.session.delete(cart_item)
    
    db.session.commit()
    return redirect(url_for('main.cart'))

@main_bp.route('/add-to-wishlist/<int:product_id>')
@login_required
def add_to_wishlist(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    
    # Check if already in wishlist
    existing = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('Product removed from wishlist!', 'success')
    else:
        wishlist_item = Wishlist(user_id=current_user.id, product_id=product_id)
        db.session.add(wishlist_item)
        db.session.commit()
        flash('Product added to wishlist!', 'success')
    
    return redirect(url_for('main.products')) # Redirect back to the products page

@main_bp.route('/wishlist')
@login_required
def wishlist():
    wishlist_items = Wishlist.query.filter_by(user_id=current_user.id).all()
    return render_template('customer/wishlist.html', wishlist_items=wishlist_items)

@main_bp.route('/remove-from-wishlist/<int:wishlist_id>')
@login_required
def remove_from_wishlist(wishlist_id):
    wishlist_item = Wishlist.query.filter_by(id=wishlist_id, user_id=current_user.id).first_or_404()
    db.session.delete(wishlist_item)
    db.session.commit()
    flash('Product removed from wishlist!', 'success')
    return redirect(url_for('main.wishlist'))

@main_bp.route('/checkout')
@login_required
def checkout():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('main.cart'))
    
    total = sum(item.product.price * item.quantity for item in cart_items)
    addresses = Address.query.filter_by(user_id=current_user.id).all()
    return render_template('customer/checkout.html', cart_items=cart_items, total=total, addresses=addresses)

@main_bp.route('/place-order', methods=['POST'])
@login_required
def place_order():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('main.cart'))
    
    selected_address_id = request.form.get('selected_address_id')
    payment_method = request.form.get('payment_method')

    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    address = request.form.get('address')
    city = request.form.get('city')
    state = request.form.get('state')
    zip_code = request.form.get('zip_code')

    # If user selected a saved address, override fields
    if selected_address_id:
        saved = Address.query.filter_by(id=int(selected_address_id), user_id=current_user.id).first()
        if saved:
            full_name = saved.full_name
            phone = saved.phone
            address = saved.address_line
            city = saved.city
            state = saved.state
            zip_code = saved.zip_code
    
    if not all([full_name, address, city, state, zip_code, phone, payment_method]):
        flash('Please fill in all required fields.', 'error')
        return redirect(url_for('main.checkout'))
    
    total = sum(item.product.price * item.quantity for item in cart_items)
    
    # Create order
    order = Order(
        customer_id=current_user.id,
        total_amount=total,
        payment_method=payment_method,
        shipping_address=f"{full_name}\n{address}\n{city}, {state} {zip_code}",
        phone=phone
    )
    
    if payment_method == 'online':
        order.payment_status = 'paid'  # Simulate successful payment
    
    db.session.add(order)
    db.session.flush()  # Get order ID
    
    # Create order items
    for cart_item in cart_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=cart_item.product_id,
            quantity=cart_item.quantity,
            price=cart_item.product.price
        )
        db.session.add(order_item)
        
        # Update product stock
        cart_item.product.stock -= cart_item.quantity
    
    # Create payment record
    payment = Payment(
        order_id=order.id,
        payment_method=payment_method,
        payment_status='paid' if payment_method == 'online' else 'pending',
        amount=total,
        transaction_id=f"TXN{order.id}{datetime.now().strftime('%Y%m%d%H%M%S')}" if payment_method == 'online' else None
    )
    db.session.add(payment)
    
    # Optionally save address
    if request.form.get('save_address') == 'on' and not selected_address_id:
        label = request.form.get('address_label') or 'Home'
        address_model = Address(
            user_id=current_user.id,
            label=label,
            full_name=full_name,
            phone=phone,
            address_line=address,
            city=city,
            state=state,
            zip_code=zip_code,
            is_default=False
        )
        db.session.add(address_model)

    # Clear cart
    Cart.query.filter_by(user_id=current_user.id).delete()
    
    db.session.commit()
    
    flash('Order placed successfully!', 'success')
    
    # Send confirmation email using Flask-Mail
    try:
        # Prepare order items for the email template
        detailed_order_items = []
        for item in cart_items:
            detailed_order_items.append({
                'product_name': item.product.name,
                'quantity': item.quantity,
                'price': float(item.product.price)
            })

        # Get current year for the template
        current_year = datetime.now().year

        # Render the HTML email template
        html_body = render_template('emails/order_confirmation.html',
            customer_name=current_user.name,
            order_id=order.id,
            order_date=order.created_at.strftime('%Y-%m-%d %H:%M'),
            total_amount=float(order.total_amount),
            payment_method=order.payment_method,
            shipping_address=order.shipping_address.replace('\n', ', '),
            expected_delivery_date=order.expected_delivery_date.strftime('%Y-%m-%d'),
            order_items=detailed_order_items,
            current_year=current_year
        )

        msg = Message(
            subject=f"Order Confirmation - MSR Shop Order #{order.id}",
            recipients=[current_user.email],
            html=html_body, # Send as HTML
            sender=current_app.config['MAIL_DEFAULT_SENDER']
        )
        mail.send(msg)
        current_app.logger.info(f"Flask-Mail confirmation email sent to {current_user.email} for order {order.id}")
    except Exception as e:
        current_app.logger.error(f"Error sending Flask-Mail confirmation email: {e}")

    return redirect(url_for('main.orders'))


@main_bp.route('/payment/razorpay', methods=['POST'])
@login_required
def razorpay_payment():
    """Dummy Razorpay step: show a confirmation page and then forward to place_order with same form data."""
    # Recompute total from cart to prevent tampering
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('main.cart'))

    total = sum(item.product.price * item.quantity for item in cart_items)

    # Keep the original form fields to forward to place_order
    original_fields = request.form.to_dict(flat=True)

    return render_template('customer/razorpay.html', total=total, original_fields=original_fields)

@main_bp.route('/orders')
@login_required
def orders():
    user_orders = Order.query.filter_by(customer_id=current_user.id).order_by(desc(Order.created_at)).all()
    return render_template('customer/orders.html', orders=user_orders)

@main_bp.route('/profile')
@login_required
def profile():
    return render_template('customer/profile.html')

@main_bp.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    name = request.form.get('name')
    email = request.form.get('email')
    
    if not all([name, email]):
        flash('Please fill in all fields.', 'error')
        return redirect(url_for('main.profile'))
    
    # Check if email is taken by another user
    existing_user = User.query.filter_by(email=email).first()
    if existing_user and existing_user.id != current_user.id:
        flash('Email already taken by another user.', 'error')
        return redirect(url_for('main.profile'))
    
    current_user.name = name
    current_user.email = email
    
    try:
        db.session.commit()
        flash('Profile updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Failed to update profile.', 'error')
    
    return redirect(url_for('main.profile'))

@main_bp.route('/cancel-order/<int:order_id>')
@login_required
def cancel_order(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    
    if order.status not in ['pending', 'processing']:
        flash('Order cannot be cancelled at this stage.', 'error')
        return redirect(url_for('main.orders'))
    
    try:
        order.status = 'cancelled'
        
        # Restore product stock
        for item in order.order_items:
            product = Product.query.get(item.product_id)
            if product:
                product.stock += item.quantity
        
        db.session.commit()
        flash('Order cancelled successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Order cancellation error: {e}")
        flash('Failed to cancel order. Please try again.', 'error')
        
    return redirect(url_for('main.orders'))
