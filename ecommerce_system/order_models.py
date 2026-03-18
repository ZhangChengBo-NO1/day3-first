from datetime import datetime, timedelta
from enum import Enum as PyEnum
from typing import List, Optional
import uuid

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum, Index, Numeric, Text, ForeignKey, String, Integer, DateTime, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.dialects.mysql import DECIMAL


db = SQLAlchemy()


class OrderStatus(str, PyEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    RETURNED = "returned"


class PaymentStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class LogisticsStatus(str, PyEnum):
    PENDING = "pending"
    PICKED = "picked"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class AfterSalesType(str, PyEnum):
    REFUND = "refund"
    RETURN_REFUND = "return_refund"
    EXCHANGE = "exchange"
    REPAIR = "repair"


class AfterSalesStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CLOSED = "closed"


class UserRole(str, PyEnum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    ADMIN = "admin"
    LOGISTICS = "logistics"


class User(db.Model):
    __tablename__ = 'users'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CUSTOMER)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="user")
    addresses: Mapped[List["Address"]] = relationship("Address", back_populates="user")


class Address(db.Model):
    __tablename__ = 'addresses'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    receiver_name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str] = mapped_column(String(50), nullable=False)
    district: Mapped[str] = mapped_column(String(50), nullable=False)
    detail_address: Mapped[str] = mapped_column(Text, nullable=False)
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    user: Mapped["User"] = relationship("User", back_populates="addresses")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="shipping_address")


class Product(db.Model):
    __tablename__ = 'products'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    cost_price: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2))
    stock_quantity: Mapped[int] = mapped_column(default=0)
    reserved_quantity: Mapped[int] = mapped_column(default=0)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    weight: Mapped[Optional[float]] = mapped_column(default=0.0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    
    category: Mapped[Optional["Category"]] = relationship("Category", back_populates="products")
    order_items: Mapped[List["OrderItem"]] = relationship("OrderItem", back_populates="product")
    inventory_logs: Mapped[List["InventoryLog"]] = relationship("InventoryLog", back_populates="product")


class Category(db.Model):
    __tablename__ = 'categories'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    level: Mapped[int] = mapped_column(default=1)
    
    products: Mapped[List["Product"]] = relationship("Product", back_populates="category")
    children: Mapped[List["Category"]] = relationship("Category", backref="parent", remote_side=[id])


class Order(db.Model):
    __tablename__ = 'orders'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    address_id: Mapped[int] = mapped_column(ForeignKey("addresses.id"), nullable=False)
    
    # Amounts
    subtotal_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    discount_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), default=0)
    shipping_fee: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), default=0)
    tax_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), default=0)
    total_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    
    # Status
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    payment_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    logistics_status: Mapped[LogisticsStatus] = mapped_column(Enum(LogisticsStatus), default=LogisticsStatus.PENDING)
    
    # Payment
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    payment_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    paid_amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), default=0)
    
    # Logistics
    logistics_company: Mapped[Optional[str]] = mapped_column(String(50))
    tracking_no: Mapped[Optional[str]] = mapped_column(String(50))
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Timestamps
    expire_at: Mapped[datetime] = mapped_column(default=lambda: datetime.utcnow() + timedelta(minutes=30))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Notes
    buyer_note: Mapped[Optional[str]] = mapped_column(Text)
    seller_note: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="orders")
    shipping_address: Mapped["Address"] = relationship("Address", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment_logs: Mapped[List["PaymentLog"]] = relationship("PaymentLog", back_populates="order")
    logistics_logs: Mapped[List["LogisticsLog"]] = relationship("LogisticsLog", back_populates="order")
    after_sales: Mapped[List["AfterSales"]] = relationship("AfterSales", back_populates="order")
    operation_logs: Mapped[List["OrderOperationLog"]] = relationship("OrderOperationLog", back_populates="order")
    
    __table_args__ = (
        Index('idx_order_user_id', 'user_id'),
        Index('idx_order_status', 'status'),
        Index('idx_order_created_at', 'created_at'),
    )
    
    @staticmethod
    def generate_order_no() -> str:
        return datetime.now().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:6].upper()


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    total_price: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    
    order: Mapped["Order"] = relationship("Order", back_populates="items")
    product: Mapped["Product"] = relationship("Product", back_populates="order_items")


class PaymentLog(db.Model):
    __tablename__ = 'payment_logs'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    transaction_no: Mapped[str] = mapped_column(String(64), unique=True)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[decimal.Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), nullable=False)
    request_data: Mapped[Optional[str]] = mapped_column(Text)
    response_data: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    order: Mapped["Order"] = relationship("Order", back_populates="payment_logs")


class LogisticsLog(db.Model):
    __tablename__ = 'logistics_logs'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    status: Mapped[LogisticsStatus] = mapped_column(Enum(LogisticsStatus), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    order: Mapped["Order"] = relationship("Order", back_populates="logistics_logs")


class AfterSales(db.Model):
    __tablename__ = 'after_sales'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    type: Mapped[AfterSalesType] = mapped_column(Enum(AfterSalesType), nullable=False)
    status: Mapped[AfterSalesStatus] = mapped_column(Enum(AfterSalesStatus), default=AfterSalesStatus.PENDING)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    refund_amount: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2))
    images: Mapped[Optional[str]] = mapped_column(Text)
    
    # Logistics for return
    return_logistics_company: Mapped[Optional[str]] = mapped_column(String(50))
    return_tracking_no: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Audit
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    approval_note: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    order: Mapped["Order"] = relationship("Order", back_populates="after_sales")
    items: Mapped[List["AfterSalesItem"]] = relationship("AfterSalesItem", back_populates="after_sales")


class AfterSalesItem(db.Model):
    __tablename__ = 'after_sales_items'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    after_sales_id: Mapped[int] = mapped_column(ForeignKey("after_sales.id"), nullable=False)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    
    after_sales: Mapped["AfterSales"] = relationship("AfterSales", back_populates="items")


class InventoryLog(db.Model):
    __tablename__ = 'inventory_logs'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_change: Mapped[int] = mapped_column(nullable=False)
    quantity_before: Mapped[int] = mapped_column(nullable=False)
    quantity_after: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    operator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    product: Mapped["Product"] = relationship("Product", back_populates="inventory_logs")


class OrderOperationLog(db.Model):
    __tablename__ = 'order_operation_logs'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    before_status: Mapped[Optional[str]] = mapped_column(String(20))
    after_status: Mapped[Optional[str]] = mapped_column(String(20))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    order: Mapped["Order"] = relationship("Order", back_populates="operation_logs")


class Cart(db.Model):
    __tablename__ = 'carts'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(default=1)
    selected: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_cart_user_id', 'user_id'),
    )


import decimal
