#!/usr/bin/env python3
"""
数据库初始化脚本
用于创建数据库表结构和初始数据
"""

import os
import sys
from datetime import datetime, timedelta
import decimal

from werkzeug.security import generate_password_hash


def init_database():
    """初始化数据库"""
    from web_interface import create_app
    from order_models import (
        db, User, UserRole, Category, Product, Address,
        Order, OrderItem, OrderStatus, PaymentStatus, LogisticsStatus
    )
    
    app = create_app()
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Database tables created successfully!")
        
        # 检查是否已有数据
        if User.query.first():
            print("Database already initialized. Skipping seed data.")
            return
        
        print("Seeding initial data...")
        
        # 创建管理员用户
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            role=UserRole.ADMIN,
            phone='13800138000'
        )
        db.session.add(admin)
        
        # 创建商家用户
        merchant = User(
            username='merchant',
            email='merchant@example.com',
            password_hash=generate_password_hash('merchant123'),
            role=UserRole.MERCHANT,
            phone='13800138001'
        )
        db.session.add(merchant)
        
        # 创建普通用户
        customer = User(
            username='customer',
            email='customer@example.com',
            password_hash=generate_password_hash('customer123'),
            role=UserRole.CUSTOMER,
            phone='13800138002'
        )
        db.session.add(customer)
        
        db.session.flush()
        
        # 创建商品分类
        electronics = Category(name='电子产品', level=1)
        clothing = Category(name='服装', level=1)
        food = Category(name='食品', level=1)
        
        db.session.add_all([electronics, clothing, food])
        db.session.flush()
        
        # 创建子分类
        phones = Category(name='手机', parent_id=electronics.id, level=2)
        laptops = Category(name='笔记本电脑', parent_id=electronics.id, level=2)
        mens_clothing = Category(name='男装', parent_id=clothing.id, level=2)
        womens_clothing = Category(name='女装', parent_id=clothing.id, level=2)
        
        db.session.add_all([phones, laptops, mens_clothing, womens_clothing])
        db.session.flush()
        
        # 创建商品
        products = [
            Product(
                sku='PHONE-001',
                name='iPhone 15 Pro',
                description='最新款iPhone，搭载A17芯片',
                price=decimal.Decimal('7999.00'),
                cost_price=decimal.Decimal('6000.00'),
                stock_quantity=100,
                category_id=phones.id,
                weight=0.2
            ),
            Product(
                sku='PHONE-002',
                name='Samsung Galaxy S24',
                description='三星旗舰手机',
                price=decimal.Decimal('6999.00'),
                cost_price=decimal.Decimal('5200.00'),
                stock_quantity=80,
                category_id=phones.id,
                weight=0.2
            ),
            Product(
                sku='LAPTOP-001',
                name='MacBook Pro 14',
                description='专业级笔记本电脑',
                price=decimal.Decimal('14999.00'),
                cost_price=decimal.Decimal('11000.00'),
                stock_quantity=50,
                category_id=laptops.id,
                weight=1.6
            ),
            Product(
                sku='LAPTOP-002',
                name='Dell XPS 13',
                description='轻薄商务本',
                price=decimal.Decimal('8999.00'),
                cost_price=decimal.Decimal('6500.00'),
                stock_quantity=60,
                category_id=laptops.id,
                weight=1.2
            ),
            Product(
                sku='SHIRT-001',
                name='纯棉T恤',
                description='舒适透气纯棉T恤',
                price=decimal.Decimal('99.00'),
                cost_price=decimal.Decimal('35.00'),
                stock_quantity=500,
                category_id=mens_clothing.id,
                weight=0.3
            ),
            Product(
                sku='DRESS-001',
                name='连衣裙',
                description='时尚夏季连衣裙',
                price=decimal.Decimal('299.00'),
                cost_price=decimal.Decimal('120.00'),
                stock_quantity=200,
                category_id=womens_clothing.id,
                weight=0.4
            )
        ]
        
        db.session.add_all(products)
        db.session.flush()
        
        # 创建收货地址
        address = Address(
            user_id=customer.id,
            receiver_name='张三',
            phone='13800138002',
            province='广东省',
            city='深圳市',
            district='南山区',
            detail_address='科技园南路88号',
            zip_code='518000',
            is_default=True
        )
        db.session.add(address)
        
        # 创建示例订单
        sample_order = Order(
            order_no=Order.generate_order_no(),
            user_id=customer.id,
            address_id=address.id,
            subtotal_amount=decimal.Decimal('8098.00'),
            discount_amount=decimal.Decimal('20.00'),
            shipping_fee=decimal.Decimal('10.00'),
            tax_amount=decimal.Decimal('484.68'),
            total_amount=decimal.Decimal('8572.68'),
            status=OrderStatus.COMPLETED,
            payment_status=PaymentStatus.SUCCESS,
            logistics_status=LogisticsStatus.DELIVERED,
            payment_method='alipay',
            payment_time=datetime.utcnow() - timedelta(days=5),
            logistics_company='sf',
            tracking_no='SF1234567890',
            shipped_at=datetime.utcnow() - timedelta(days=4),
            delivered_at=datetime.utcnow() - timedelta(days=2),
            completed_at=datetime.utcnow() - timedelta(days=2),
            paid_amount=decimal.Decimal('8572.68')
        )
        db.session.add(sample_order)
        db.session.flush()
        
        # 创建订单项
        order_items = [
            OrderItem(
                order_id=sample_order.id,
                product_id=products[0].id,
                product_name=products[0].name,
                product_sku=products[0].sku,
                quantity=1,
                unit_price=products[0].price,
                total_price=products[0].price
            ),
            OrderItem(
                order_id=sample_order.id,
                product_id=products[4].id,
                product_name=products[4].name,
                product_sku=products[4].sku,
                quantity=1,
                unit_price=products[4].price,
                total_price=products[4].price
            )
        ]
        db.session.add_all(order_items)
        
        db.session.commit()
        print("Initial data seeded successfully!")
        
        print("\n" + "="*50)
        print("初始化完成！")
        print("="*50)
        print("\n默认用户:")
        print("  管理员 - 用户名: admin, 密码: admin123")
        print("  商家   - 用户名: merchant, 密码: merchant123")
        print("  客户   - 用户名: customer, 密码: customer123")
        print("\n" + "="*50)


def reset_database():
    """重置数据库（删除所有数据）"""
    from web_interface import create_app
    from order_models import db
    
    app = create_app()
    
    with app.app_context():
        print("Dropping all tables...")
        db.drop_all()
        print("All tables dropped!")
        
        print("Recreating tables...")
        db.create_all()
        print("Tables recreated!")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Database initialization script')
    parser.add_argument('--reset', action='store_true', help='Reset database (drop all tables)')
    parser.add_argument('--init', action='store_true', help='Initialize database with seed data')
    
    args = parser.parse_args()
    
    if args.reset:
        confirm = input("确定要重置数据库吗？所有数据将被删除！(yes/no): ")
        if confirm.lower() == 'yes':
            reset_database()
        else:
            print("操作已取消")
    elif args.init:
        init_database()
    else:
        # 默认执行初始化
        init_database()
