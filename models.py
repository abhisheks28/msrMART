from datetime import datetime, timedelta
import uuid
from app import db
from flask_login import UserMixin
from sqlalchemy import func, Table, Column, Integer, ForeignKey

# Association table for Super Admins and Categories
super_admin_categories = db.Table('super_admin_categories',
    db.Column('user_id', db.String(36), db.ForeignKey('users.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())) # Generate UUID for primary key
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='customer')  # admin, super_admin, customer
    unique_code = db.Column(db.String(50), unique=True, nullable=True)  # For super admin registration
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    products = db.relationship('Product', backref='owner', lazy=True)
    orders = db.relationship('Order', backref='customer', lazy=True)
    cart_items = db.relationship('Cart', backref='user', lazy=True)
    wishlist_items = db.relationship('Wishlist', backref='user', lazy=True)
    categories = db.relationship('Category', secondary=super_admin_categories, backref='super_admins', lazy='dynamic')
    addresses = db.relationship('Address', backref='user', lazy=True, cascade='all, delete-orphan')

class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', backref='category', lazy=True)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    original_price = db.Column(db.Numeric(10, 2), nullable=True) # For discount pricing
    stock = db.Column(db.Integer, nullable=False, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    super_admin_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False) # Changed to String to store UUID
    image_url = db.Column(db.String(200), default=None) # Primary image
    brand = db.Column(db.String(100), nullable=True)
    dimensions = db.Column(db.String(200), nullable=True) # e.g., "Large: 35.5x25.4x3.8 cm, Medium: ..."
    ratings = db.Column(db.Numeric(2, 1), default=0.0)
    num_ratings = db.Column(db.Integer, default=0)
    sales_count = db.Column(db.Integer, default=0) # For "200+ bought in past month"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    product_images = db.relationship('ProductImage', backref='product', lazy=True, cascade='all, delete-orphan')
    order_items = db.relationship('OrderItem', backref='product', lazy=True, cascade='all, delete-orphan')
    cart_items = db.relationship('Cart', backref='product', lazy=True, cascade='all, delete-orphan')
    wishlist_items = db.relationship('Wishlist', backref='product', lazy=True, cascade='all, delete-orphan')

class ProductImage(db.Model):
    __tablename__ = 'product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    image_url = db.Column(db.String(200), nullable=False)
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False) # Changed to String to store UUID
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='pending')  # pending, processing, shipped, delivered, cancelled
    payment_method = db.Column(db.String(50), nullable=False)  # cod, online
    payment_status = db.Column(db.String(50), nullable=False, default='pending')  # pending, paid, failed
    shipping_address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expected_delivery_date = db.Column(db.DateTime)
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='order', uselist=False, cascade='all, delete-orphan')
    
    def __init__(self, **kwargs):
        super(Order, self).__init__(**kwargs)
        # Set expected delivery date to 5 days from order date
        self.expected_delivery_date = datetime.utcnow() + timedelta(days=5)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'total_amount': float(self.total_amount),
            'status': self.status,
            'payment_method': self.payment_method,
            'payment_status': self.payment_status,
            'shipping_address': self.shipping_address,
            'phone': self.phone,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expected_delivery_date': self.expected_delivery_date.isoformat() if self.expected_delivery_date else None,
            'order_items': [item.to_dict() for item in self.order_items] if self.order_items else [],
            'customer_name': self.customer.name if self.customer else None # Include customer name
        }

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)  # Price at the time of order

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'price': float(self.price),
            'product_name': self.product.name if self.product else None  # Assuming a relationship to Product model
        }

class Cart(db.Model):
    __tablename__ = 'cart'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False) # Changed to String to store UUID
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Wishlist(db.Model):
    __tablename__ = 'wishlist'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False) # Changed to String to store UUID
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.String(100))
    payment_status = db.Column(db.String(50), nullable=False, default='pending')
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Address(db.Model):
    __tablename__ = 'addresses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    label = db.Column(db.String(20), nullable=False, default='Home') # Home, Work, Other
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address_line = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    zip_code = db.Column(db.String(20), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
