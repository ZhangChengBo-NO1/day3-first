from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import enum
import json

db = SQLAlchemy()


class OrderStatus(enum.Enum):
    PENDING = 'pending'
    PAID = 'paid'
    CONFIRMED = 'confirmed'
    PROCESSING = 'processing'
    SHIPPED = 'shipped'
    DELIVERED = 'delivered'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'
    AFTER_SALES = 'after_sales'


class PaymentStatus(enum.Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    FAILED = 'failed'
    REFUNDED = 'refunded'


class AfterSalesStatus(enum.Enum):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    PROCESSING = 'processing'
    COMPLETED = 'completed'


class AfterSalesType(enum.Enum):
    RETURN = 'return'
    EXCHANGE = 'exchange'
    REFUND_ONLY = 'refund_only'
    REPAIR = 'repair'


class UserRole(enum.Enum):
    ADMIN = 'admin'
    MANAGER = 'manager'
    OPERATOR = 'operator'
    CUSTOMER = 'customer'


class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum(UserRole), default=UserRole.CUSTOMER, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    orders = db.relationship('Order', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, required_role):
        role_hierarchy = {
            UserRole.ADMIN: 4,
            UserRole.MANAGER: 3,
            UserRole.OPERATOR: 2,
            UserRole.CUSTOMER: 1
        }
        return role_hierarchy.get(self.role, 0) >= role_hierarchy.get(required_role, 0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role.value,
            'is_active': self.is_active,
            'phone': self.phone,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    cost_price = db.Column(db.Numeric(10, 2))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    inventory = db.Column(db.Integer, default=0, nullable=False)
    reserved_inventory = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)
    weight = db.Column(db.Numeric(8, 2))
    dimensions = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    category = db.relationship('Category', backref='products')
    order_items = db.relationship('OrderItem', backref='product', lazy='dynamic')
    
    @property
    def available_inventory(self):
        return self.inventory - self.reserved_inventory
    
    def to_dict(self):
        return {
            'id': self.id,
            'sku': self.sku,
            'name': self.name,
            'price': float(self.price),
            'inventory': self.inventory,
            'available_inventory': self.available_inventory,
            'category_id': self.category_id,
            'is_active': self.is_active
        }


class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    parent = db.relationship('Category', remote_side=[id], backref='children')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'parent_id': self.parent_id,
            'description': self.description
        }


class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(32), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    payment_status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    discount_amount = db.Column(db.Numeric(12, 2), default=0)
    shipping_fee = db.Column(db.Numeric(10, 2), default=0)
    tax_amount = db.Column(db.Numeric(10, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    
    recipient_name = db.Column(db.String(100), nullable=False)
    recipient_phone = db.Column(db.String(20), nullable=False)
    recipient_address = db.Column(db.String(500), nullable=False)
    province = db.Column(db.String(50))
    city = db.Column(db.String(50))
    district = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    
    payment_method = db.Column(db.String(50))
    payment_transaction_id = db.Column(db.String(100))
    payment_time = db.Column(db.DateTime)
    
    logistics_company = db.Column(db.String(50))
    tracking_number = db.Column(db.String(100))
    shipping_time = db.Column(db.DateTime)
    delivery_time = db.Column(db.DateTime)
    
    remark = db.Column(db.Text)
    internal_remark = db.Column(db.Text)
    
    source = db.Column(db.String(50), default='web')
    ip_address = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))
    
    items = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payment_records = db.relationship('PaymentRecord', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    after_sales = db.relationship('AfterSales', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    logistics_records = db.relationship('LogisticsRecord', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    
    def calculate_total(self):
        items_total = sum(item.subtotal for item in self.items)
        self.subtotal = items_total
        self.total_amount = items_total + self.shipping_fee + self.tax_amount - self.discount_amount
        return self.total_amount
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_no': self.order_no,
            'user_id': self.user_id,
            'status': self.status.value,
            'payment_status': self.payment_status.value,
            'subtotal': float(self.subtotal) if self.subtotal else 0,
            'discount_amount': float(self.discount_amount) if self.discount_amount else 0,
            'shipping_fee': float(self.shipping_fee) if self.shipping_fee else 0,
            'tax_amount': float(self.tax_amount) if self.tax_amount else 0,
            'total_amount': float(self.total_amount) if self.total_amount else 0,
            'recipient_name': self.recipient_name,
            'recipient_phone': self.recipient_phone,
            'recipient_address': self.recipient_address,
            'payment_method': self.payment_method,
            'logistics_company': self.logistics_company,
            'tracking_number': self.tracking_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'items': [item.to_dict() for item in self.items]
        }


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    sku = db.Column(db.String(50), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    product_image = db.Column(db.String(500))
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), default=0)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def calculate_subtotal(self):
        self.subtotal = self.quantity * self.unit_price - self.discount_amount
        return self.subtotal
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'sku': self.sku,
            'product_name': self.product_name,
            'quantity': self.quantity,
            'unit_price': float(self.unit_price),
            'discount_amount': float(self.discount_amount) if self.discount_amount else 0,
            'subtotal': float(self.subtotal)
        }


class PaymentRecord(db.Model):
    __tablename__ = 'payment_records'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    transaction_id = db.Column(db.String(100), unique=True, index=True)
    payment_method = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    
    gateway_response = db.Column(db.Text)
    error_message = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'transaction_id': self.transaction_id,
            'payment_method': self.payment_method,
            'amount': float(self.amount),
            'status': self.status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AfterSales(db.Model):
    __tablename__ = 'after_sales'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    type = db.Column(db.Enum(AfterSalesType), nullable=False)
    status = db.Column(db.Enum(AfterSalesStatus), default=AfterSalesStatus.PENDING)
    
    reason = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    evidence_urls = db.Column(db.Text)
    
    refund_amount = db.Column(db.Numeric(12, 2))
    approved_amount = db.Column(db.Numeric(12, 2))
    
    handler_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    handler_remark = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    order_item = db.relationship('OrderItem', backref='after_sales_records')
    handler = db.relationship('User', foreign_keys=[handler_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'type': self.type.value,
            'status': self.status.value,
            'reason': self.reason,
            'refund_amount': float(self.refund_amount) if self.refund_amount else None,
            'status': self.status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LogisticsRecord(db.Model):
    __tablename__ = 'logistics_records'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    
    logistics_company = db.Column(db.String(50))
    tracking_number = db.Column(db.String(100), index=True)
    
    status = db.Column(db.String(50))
    location = db.Column(db.String(200))
    description = db.Column(db.Text)
    
    occurred_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'logistics_company': self.logistics_company,
            'tracking_number': self.tracking_number,
            'status': self.status,
            'location': self.location,
            'description': self.description,
            'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None
        }


class InventoryLog(db.Model):
    __tablename__ = 'inventory_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))
    
    change_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    before_quantity = db.Column(db.Integer, nullable=False)
    after_quantity = db.Column(db.Integer, nullable=False)
    
    remark = db.Column(db.String(200))
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    product = db.relationship('Product', backref='inventory_logs')
    operator = db.relationship('User', backref='inventory_operations')
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'change_type': self.change_type,
            'quantity': self.quantity,
            'before_quantity': self.before_quantity,
            'after_quantity': self.after_quantity,
            'remark': self.remark,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ERPIntegration(db.Model):
    __tablename__ = 'erp_integrations'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, unique=True)
    erp_order_id = db.Column(db.String(100), index=True)
    sync_status = db.Column(db.String(20), default='pending')
    sync_data = db.Column(db.Text)
    error_message = db.Column(db.Text)
    synced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CRMIntegration(db.Model):
    __tablename__ = 'crm_integrations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))
    crm_customer_id = db.Column(db.String(100), index=True)
    sync_status = db.Column(db.String(20), default='pending')
    sync_data = db.Column(db.Text)
    error_message = db.Column(db.Text)
    synced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(50), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(50))
    target_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    ip_address = db.Column(db.String(50))
    request_data = db.Column(db.Text)
    response_data = db.Column(db.Text)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    user = db.relationship('User', backref='system_logs')
