from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional
from decimal import Decimal
import json

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.exceptions import HTTPException

from config import config
from order_models import (
    db, Order, OrderItem, Product, User, Category,
    PaymentRecord, AfterSales, AfterSalesType, AfterSalesStatus,
    OrderStatus, PaymentStatus, UserRole, SystemLog
)
from order_service import (
    OrderService, AfterSalesService, InventoryService,
    PaymentService, PermissionService, PermissionDenied,
    OrderException, InventoryException, PaymentException
)
from order_analytics import (
    SalesAnalytics, ProductAnalytics, CustomerAnalytics,
    OrderAnalytics, DashboardService, AnalyticsExporter, DateRange
)


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    db.init_app(app)
    CORS(app)
    jwt = JWTManager(app)
    
    with app.app_context():
        db.create_all()
    
    register_blueprints(app)
    register_error_handlers(app)
    
    return app


def register_blueprints(app):
    from flask import Blueprint
    
    auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
    order_bp = Blueprint('order', __name__, url_prefix='/api/orders')
    product_bp = Blueprint('product', __name__, url_prefix='/api/products')
    after_sales_bp = Blueprint('after_sales', __name__, url_prefix='/api/after-sales')
    analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
    admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')
    
    @auth_bp.route('/register', methods=['POST'])
    def register():
        data = request.get_json()
        
        if User.query.filter_by(username=data.get('username')).first():
            return jsonify({'error': '用户名已存在'}), 400
        
        if User.query.filter_by(email=data.get('email')).first():
            return jsonify({'error': '邮箱已存在'}), 400
        
        user = User(
            username=data.get('username'),
            email=data.get('email'),
            phone=data.get('phone'),
            role=UserRole.CUSTOMER
        )
        user.set_password(data.get('password'))
        
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            'message': '注册成功',
            'user': user.to_dict()
        }), 201
    
    @auth_bp.route('/login', methods=['POST'])
    def login():
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return jsonify({'error': '用户名或密码错误'}), 401
        
        if not user.is_active:
            return jsonify({'error': '账户已被禁用'}), 403
        
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        return jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': user.to_dict()
        })
    
    @auth_bp.route('/refresh', methods=['POST'])
    @jwt_required(refresh=True)
    def refresh():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user or not user.is_active:
            return jsonify({'error': '用户不存在或已被禁用'}), 401
        
        access_token = create_access_token(identity=user_id)
        return jsonify({'access_token': access_token})
    
    @auth_bp.route('/profile', methods=['GET'])
    @jwt_required()
    def get_profile():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        return jsonify(user.to_dict())
    
    @order_bp.route('', methods=['POST'])
    @jwt_required()
    def create_order():
        user_id = get_jwt_identity()
        data = request.get_json()
        
        items = data.get('items', [])
        shipping_info = data.get('shipping_info', {})
        payment_method = data.get('payment_method', 'alipay')
        remark = data.get('remark', '')
        
        try:
            order_service = OrderService(current_app.config)
            order = order_service.create_order(
                user_id=user_id,
                items=items,
                shipping_info=shipping_info,
                payment_method=payment_method,
                remark=remark,
                source='web',
                ip_address=request.remote_addr
            )
            
            payment_service = PaymentService(current_app.config)
            payment_info = payment_service.create_payment(order, payment_method)
            
            return jsonify({
                'message': '订单创建成功',
                'order': order.to_dict(),
                'payment': payment_info
            }), 201
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @order_bp.route('/<int:order_id>', methods=['GET'])
    @jwt_required()
    def get_order(order_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        
        if order.user_id != user_id and not user.has_permission(UserRole.OPERATOR):
            return jsonify({'error': '无权查看此订单'}), 403
        
        return jsonify(order.to_dict())
    
    @order_bp.route('', methods=['GET'])
    @jwt_required()
    def list_orders():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = Order.query
        
        if not user.has_permission(UserRole.OPERATOR):
            query = query.filter(Order.user_id == user_id)
        
        if status:
            try:
                status_enum = OrderStatus(status)
                query = query.filter(Order.status == status_enum)
            except ValueError:
                pass
        
        pagination = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page
        )
        
        return jsonify({
            'orders': [o.to_dict() for o in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
    
    @order_bp.route('/<int:order_id>/cancel', methods=['POST'])
    @jwt_required()
    def cancel_order(order_id):
        user_id = get_jwt_identity()
        data = request.get_json() or {}
        reason = data.get('reason', '')
        
        try:
            order_service = OrderService(current_app.config)
            order = order_service.cancel_order(order_id, user_id, reason)
            return jsonify({
                'message': '订单已取消',
                'order': order.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
        except PermissionDenied as e:
            return jsonify({'error': str(e)}), 403
    
    @order_bp.route('/<int:order_id>/confirm', methods=['POST'])
    @jwt_required()
    def confirm_order(order_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'confirm', 'order'):
            return jsonify({'error': '无权操作'}), 403
        
        try:
            order_service = OrderService(current_app.config)
            order = order_service.confirm_order(order_id, user_id)
            return jsonify({
                'message': '订单已确认',
                'order': order.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @order_bp.route('/<int:order_id>/ship', methods=['POST'])
    @jwt_required()
    def ship_order(order_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'ship', 'order'):
            return jsonify({'error': '无权操作'}), 403
        
        data = request.get_json() or {}
        logistics_company = data.get('logistics_company')
        tracking_number = data.get('tracking_number')
        
        if not logistics_company:
            return jsonify({'error': '请选择物流公司'}), 400
        
        try:
            order_service = OrderService(current_app.config)
            order = order_service.ship_order(
                order_id, user_id, logistics_company, tracking_number
            )
            return jsonify({
                'message': '订单已发货',
                'order': order.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @order_bp.route('/<int:order_id>/deliver', methods=['POST'])
    @jwt_required()
    def confirm_delivery(order_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'deliver', 'order'):
            return jsonify({'error': '无权操作'}), 403
        
        try:
            order_service = OrderService(current_app.config)
            order = order_service.confirm_delivery(order_id, user_id)
            return jsonify({
                'message': '订单已签收',
                'order': order.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @order_bp.route('/<int:order_id>/logistics', methods=['GET'])
    @jwt_required()
    def query_logistics(order_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        
        if order.user_id != user_id and not user.has_permission(UserRole.OPERATOR):
            return jsonify({'error': '无权查看'}), 403
        
        try:
            order_service = OrderService(current_app.config)
            result = order_service.query_logistics(order_id)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    
    @order_bp.route('/payment/callback', methods=['POST'])
    def payment_callback():
        data = request.get_json()
        
        try:
            payment_service = PaymentService(current_app.config)
            result = payment_service.process_callback(data)
            return jsonify(result)
        except PaymentException as e:
            return jsonify({'error': str(e)}), 400
    
    @product_bp.route('', methods=['GET'])
    def list_products():
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        category_id = request.args.get('category_id', type=int)
        keyword = request.args.get('keyword', '')
        
        query = Product.query.filter(Product.is_active == True)
        
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        if keyword:
            query = query.filter(
                Product.name.ilike(f'%{keyword}%') |
                Product.sku.ilike(f'%{keyword}%')
            )
        
        pagination = query.order_by(Product.created_at.desc()).paginate(
            page=page, per_page=per_page
        )
        
        return jsonify({
            'products': [p.to_dict() for p in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
    
    @product_bp.route('/<int:product_id>', methods=['GET'])
    def get_product(product_id):
        product = Product.query.get(product_id)
        if not product:
            return jsonify({'error': '商品不存在'}), 404
        return jsonify(product.to_dict())
    
    @product_bp.route('/<int:product_id>/inventory', methods=['GET'])
    @jwt_required()
    def check_inventory(product_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user.has_permission(UserRole.OPERATOR):
            return jsonify({'error': '无权查看'}), 403
        
        quantity = request.args.get('quantity', 1, type=int)
        available, current = InventoryService.check_inventory(product_id, quantity)
        
        return jsonify({
            'product_id': product_id,
            'requested_quantity': quantity,
            'available': available,
            'current_inventory': current
        })
    
    @after_sales_bp.route('', methods=['POST'])
    @jwt_required()
    def create_after_sales():
        user_id = get_jwt_identity()
        data = request.get_json()
        
        order_id = data.get('order_id')
        after_sales_type = data.get('type')
        reason = data.get('reason')
        description = data.get('description', '')
        order_item_id = data.get('order_item_id')
        evidence_urls = data.get('evidence_urls', [])
        
        try:
            after_sales_type = AfterSalesType(after_sales_type)
        except ValueError:
            return jsonify({'error': '无效的售后类型'}), 400
        
        try:
            after_sales_service = AfterSalesService(current_app.config)
            after_sales = after_sales_service.create_after_sales(
                order_id=order_id,
                user_id=user_id,
                after_sales_type=after_sales_type,
                reason=reason,
                description=description,
                order_item_id=order_item_id,
                evidence_urls=evidence_urls
            )
            return jsonify({
                'message': '售后申请已提交',
                'after_sales': after_sales.to_dict()
            }), 201
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @after_sales_bp.route('', methods=['GET'])
    @jwt_required()
    def list_after_sales():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = AfterSales.query
        
        if not user.has_permission(UserRole.OPERATOR):
            query = query.filter(AfterSales.user_id == user_id)
        
        if status:
            try:
                status_enum = AfterSalesStatus(status)
                query = query.filter(AfterSales.status == status_enum)
            except ValueError:
                pass
        
        pagination = query.order_by(AfterSales.created_at.desc()).paginate(
            page=page, per_page=per_page
        )
        
        return jsonify({
            'after_sales': [a.to_dict() for a in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
    
    @after_sales_bp.route('/<int:after_sales_id>/approve', methods=['POST'])
    @jwt_required()
    def approve_after_sales(after_sales_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'approve', 'after_sales'):
            return jsonify({'error': '无权操作'}), 403
        
        data = request.get_json() or {}
        approved_amount = data.get('approved_amount')
        remark = data.get('remark', '')
        
        if approved_amount:
            approved_amount = Decimal(str(approved_amount))
        
        try:
            after_sales_service = AfterSalesService(current_app.config)
            after_sales = after_sales_service.approve_after_sales(
                after_sales_id, user_id, approved_amount, remark
            )
            return jsonify({
                'message': '售后申请已批准',
                'after_sales': after_sales.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @after_sales_bp.route('/<int:after_sales_id>/reject', methods=['POST'])
    @jwt_required()
    def reject_after_sales(after_sales_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'reject', 'after_sales'):
            return jsonify({'error': '无权操作'}), 403
        
        data = request.get_json() or {}
        reason = data.get('reason', '')
        
        try:
            after_sales_service = AfterSalesService(current_app.config)
            after_sales = after_sales_service.reject_after_sales(
                after_sales_id, user_id, reason
            )
            return jsonify({
                'message': '售后申请已拒绝',
                'after_sales': after_sales.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @after_sales_bp.route('/<int:after_sales_id>/refund', methods=['POST'])
    @jwt_required()
    def process_refund(after_sales_id):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'process', 'after_sales'):
            return jsonify({'error': '无权操作'}), 403
        
        try:
            after_sales_service = AfterSalesService(current_app.config)
            after_sales = after_sales_service.process_refund(after_sales_id, user_id)
            return jsonify({
                'message': '退款已完成',
                'after_sales': after_sales.to_dict()
            })
        except OrderException as e:
            return jsonify({'error': str(e)}), 400
    
    @analytics_bp.route('/dashboard', methods=['GET'])
    @jwt_required()
    def get_dashboard():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        summary = DashboardService.get_dashboard_summary()
        return jsonify(summary)
    
    @analytics_bp.route('/sales/summary', methods=['GET'])
    @jwt_required()
    def get_sales_summary():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        period = request.args.get('period', 'today')
        
        if period == 'today':
            date_range = DateRange.today()
        elif period == 'yesterday':
            date_range = DateRange.yesterday()
        elif period == 'last_7_days':
            date_range = DateRange.last_7_days()
        elif period == 'last_30_days':
            date_range = DateRange.last_30_days()
        elif period == 'this_month':
            date_range = DateRange.this_month()
        elif period == 'this_year':
            date_range = DateRange.this_year()
        else:
            date_range = DateRange.today()
        
        summary = SalesAnalytics.get_sales_summary(date_range)
        return jsonify(summary)
    
    @analytics_bp.route('/sales/trend', methods=['GET'])
    @jwt_required()
    def get_sales_trend():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        period = request.args.get('period', 'day')
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        trend = SalesAnalytics.get_sales_by_period(date_range, period)
        return jsonify(trend)
    
    @analytics_bp.route('/sales/comparison', methods=['GET'])
    @jwt_required()
    def get_sales_comparison():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 7, type=int)
        comparison = SalesAnalytics.get_sales_comparison(days)
        return jsonify(comparison)
    
    @analytics_bp.route('/products/top', methods=['GET'])
    @jwt_required()
    def get_top_products():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        limit = request.args.get('limit', 10, type=int)
        sort_by = request.args.get('sort_by', 'sales')
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        products = ProductAnalytics.get_top_products(date_range, limit, sort_by)
        return jsonify(products)
    
    @analytics_bp.route('/products/category', methods=['GET'])
    @jwt_required()
    def get_category_sales():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        category_sales = ProductAnalytics.get_category_sales(date_range)
        return jsonify(category_sales)
    
    @analytics_bp.route('/products/inventory-alert', methods=['GET'])
    @jwt_required()
    def get_inventory_alert():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        alert = ProductAnalytics.get_inventory_alert()
        return jsonify(alert)
    
    @analytics_bp.route('/customers/summary', methods=['GET'])
    @jwt_required()
    def get_customer_summary():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        summary = CustomerAnalytics.get_customer_summary(date_range)
        return jsonify(summary)
    
    @analytics_bp.route('/customers/top', methods=['GET'])
    @jwt_required()
    def get_top_customers():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        limit = request.args.get('limit', 10, type=int)
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        customers = CustomerAnalytics.get_top_customers(date_range, limit)
        return jsonify(customers)
    
    @analytics_bp.route('/customers/segments', methods=['GET'])
    @jwt_required()
    def get_customer_segments():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        segments = CustomerAnalytics.get_customer_segments()
        return jsonify(segments)
    
    @analytics_bp.route('/orders/status', methods=['GET'])
    @jwt_required()
    def get_order_status():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        distribution = OrderAnalytics.get_order_status_distribution(date_range)
        return jsonify(distribution)
    
    @analytics_bp.route('/orders/fulfillment', methods=['GET'])
    @jwt_required()
    def get_fulfillment_metrics():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        metrics = OrderAnalytics.get_fulfillment_metrics(date_range)
        return jsonify(metrics)
    
    @analytics_bp.route('/after-sales/stats', methods=['GET'])
    @jwt_required()
    def get_after_sales_stats():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'analytics'):
            return jsonify({'error': '无权查看'}), 403
        
        days = request.args.get('days', 30, type=int)
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        stats = OrderAnalytics.get_after_sales_stats(date_range)
        return jsonify(stats)
    
    @analytics_bp.route('/export/sales', methods=['GET'])
    @jwt_required()
    def export_sales():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'export', 'analytics'):
            return jsonify({'error': '无权导出'}), 403
        
        days = request.args.get('days', 30, type=int)
        format = request.args.get('format', 'csv')
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        data = AnalyticsExporter.export_sales_report(date_range, format)
        
        if format == 'csv':
            return data, 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': 'attachment; filename=sales_report.csv'
            }
        return jsonify(data)
    
    @analytics_bp.route('/export/products', methods=['GET'])
    @jwt_required()
    def export_products():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'export', 'analytics'):
            return jsonify({'error': '无权导出'}), 403
        
        days = request.args.get('days', 30, type=int)
        format = request.args.get('format', 'csv')
        
        date_range = DateRange(
            datetime.utcnow() - timedelta(days=days),
            datetime.utcnow()
        )
        
        data = AnalyticsExporter.export_product_report(date_range, format)
        
        if format == 'csv':
            return data, 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': 'attachment; filename=product_report.csv'
            }
        return jsonify(data)
    
    @admin_bp.route('/users', methods=['GET'])
    @jwt_required()
    def list_users():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not PermissionService.check_permission(user, 'view', 'user'):
            return jsonify({'error': '无权查看'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        pagination = User.query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page
        )
        
        return jsonify({
            'users': [u.to_dict() for u in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        })
    
    @admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
    @jwt_required()
    def update_user_role(user_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        
        if not PermissionService.check_permission(current_user, 'update', 'user'):
            return jsonify({'error': '无权操作'}), 403
        
        data = request.get_json()
        new_role = data.get('role')
        
        try:
            role_enum = UserRole(new_role)
        except ValueError:
            return jsonify({'error': '无效的角色'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        user.role = role_enum
        db.session.commit()
        
        return jsonify({
            'message': '角色已更新',
            'user': user.to_dict()
        })
    
    @admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
    @jwt_required()
    def update_user_status(user_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        
        if not PermissionService.check_permission(current_user, 'update', 'user'):
            return jsonify({'error': '无权操作'}), 403
        
        data = request.get_json()
        is_active = data.get('is_active', True)
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        user.is_active = is_active
        db.session.commit()
        
        return jsonify({
            'message': '状态已更新',
            'user': user.to_dict()
        })
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(after_sales_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)


def register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'error': str(error)}), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': '未授权访问'}), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': '禁止访问'}), 403
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': '资源不存在'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return jsonify({'error': '服务器内部错误'}), 500
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return jsonify({'error': error.description}), error.code
        return jsonify({'error': str(error)}), 500


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
