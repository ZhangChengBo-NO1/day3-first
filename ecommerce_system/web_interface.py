import decimal
from datetime import datetime, timedelta
from typing import Optional, List

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token

from config import config
from order_models import (
    db, Order, OrderItem, Product, Category, User, Address, Cart,
    OrderStatus, PaymentStatus, LogisticsStatus,
    AfterSales, AfterSalesType, AfterSalesStatus
)
from order_service import OrderService, InventoryService, OrderServiceError
from logistics_client import LogisticsService, ERPIntegrationClient, CRMIntegrationClient
from order_analytics import OrderAnalytics, ReportGenerator
from auth import (
    init_auth, AuthService, role_required, admin_required,
    merchant_required, customer_required, permission_required,
    Permission, audit_log, owner_or_admin_required
)


def create_app(config_name='default'):
    """应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # 初始化扩展
    db.init_app(app)
    init_auth(app)
    CORS(app)
    
    return app


app = create_app()


# ==================== 响应辅助函数 ====================

def success_response(data=None, message='操作成功'):
    """成功响应"""
    response = {'success': True, 'message': message}
    if data is not None:
        response['data'] = data
    return jsonify(response)


def error_response(message, error_code='error', status_code=400):
    """错误响应"""
    return jsonify({
        'success': False,
        'message': message,
        'error': error_code
    }), status_code


def paginated_response(items, total, page, per_page):
    """分页响应"""
    return jsonify({
        'success': True,
        'data': {
            'items': items,
            'pagination': {
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page
            }
        }
    })


# ==================== 认证相关接口 ====================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    
    required_fields = ['username', 'email', 'password']
    for field in required_fields:
        if not data.get(field):
            return error_response(f'缺少必填字段: {field}')
    
    try:
        user = AuthService.register(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            phone=data.get('phone'),
            role=data.get('role', 'customer')
        )
        return success_response({
            'id': user.id,
            'username': user.username,
            'email': user.email
        }, '注册成功')
    except Exception as e:
        return error_response(str(e))


@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    
    username = data.get('username') or data.get('email')
    password = data.get('password')
    
    if not username or not password:
        return error_response('请提供用户名/邮箱和密码')
    
    try:
        result = AuthService.login(username, password)
        return success_response(result, '登录成功')
    except Exception as e:
        return error_response(str(e), 'login_failed', 401)


@app.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    """刷新访问令牌"""
    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity)
    return success_response({'access_token': access_token})


@app.route('/api/auth/change-password', methods=['POST'])
@jwt_required()
def change_password():
    """修改密码"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        AuthService.change_password(
            user_id=identity['id'],
            old_password=data.get('old_password'),
            new_password=data.get('new_password')
        )
        return success_response(message='密码修改成功')
    except Exception as e:
        return error_response(str(e))


# ==================== 订单相关接口 ====================

@app.route('/api/orders', methods=['POST'])
@jwt_required()
@permission_required(Permission.ORDER_CREATE)
@audit_log('创建订单')
def create_order():
    """创建订单"""
    data = request.get_json()
    identity = get_jwt_identity()
    user_id = identity['id']
    
    try:
        service = OrderService()
        order = service.create_order(
            user_id=user_id,
            address_id=data['address_id'],
            cart_item_ids=data.get('cart_item_ids'),
            items=data.get('items'),
            buyer_note=data.get('buyer_note')
        )
        
        return success_response({
            'order_id': order.id,
            'order_no': order.order_no,
            'total_amount': str(order.total_amount),
            'status': order.status.value,
            'expire_at': order.expire_at.isoformat()
        }, '订单创建成功')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders', methods=['GET'])
@jwt_required()
@permission_required(Permission.ORDER_VIEW)
def get_orders():
    """获取订单列表"""
    identity = get_jwt_identity()
    user_id = identity['id']
    
    # 查询参数
    status = request.args.get('status')
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 20)), 100)
    
    try:
        service = OrderService()
        
        # 管理员可以查看所有订单，其他用户只能查看自己的
        if identity['role'] == 'admin':
            query = Order.query
        else:
            query = Order.query.filter_by(user_id=user_id)
        
        if status:
            query = query.filter_by(status=OrderStatus(status))
        
        total = query.count()
        orders = query.order_by(Order.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()
        
        items = [{
            'id': o.id,
            'order_no': o.order_no,
            'total_amount': str(o.total_amount),
            'status': o.status.value,
            'payment_status': o.payment_status.value,
            'logistics_status': o.logistics_status.value,
            'created_at': o.created_at.isoformat(),
            'item_count': len(o.items)
        } for o in orders]
        
        return paginated_response(items, total, page, per_page)
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@permission_required(Permission.ORDER_VIEW)
def get_order_detail(order_id):
    """获取订单详情"""
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        order = service.get_order_detail(order_id)
        
        if not order:
            return error_response('订单不存在', 'order_not_found', 404)
        
        # 权限检查
        if identity['role'] != 'admin' and order.user_id != identity['id']:
            return error_response('无权访问此订单', 'permission_denied', 403)
        
        return success_response({
            'id': order.id,
            'order_no': order.order_no,
            'user': {
                'id': order.user.id,
                'username': order.user.username
            },
            'shipping_address': {
                'receiver_name': order.shipping_address.receiver_name,
                'phone': order.shipping_address.phone,
                'full_address': f"{order.shipping_address.province}{order.shipping_address.city}"
                               f"{order.shipping_address.district}{order.shipping_address.detail_address}"
            },
            'items': [{
                'product_id': item.product_id,
                'product_name': item.product_name,
                'product_sku': item.product_sku,
                'quantity': item.quantity,
                'unit_price': str(item.unit_price),
                'total_price': str(item.total_price)
            } for item in order.items],
            'amounts': {
                'subtotal': str(order.subtotal_amount),
                'discount': str(order.discount_amount),
                'shipping_fee': str(order.shipping_fee),
                'tax': str(order.tax_amount),
                'total': str(order.total_amount),
                'paid': str(order.paid_amount)
            },
            'status': {
                'order': order.status.value,
                'payment': order.payment_status.value,
                'logistics': order.logistics_status.value
            },
            'payment': {
                'method': order.payment_method,
                'time': order.payment_time.isoformat() if order.payment_time else None
            },
            'logistics': {
                'company': order.logistics_company,
                'tracking_no': order.tracking_no,
                'shipped_at': order.shipped_at.isoformat() if order.shipped_at else None,
                'delivered_at': order.delivered_at.isoformat() if order.delivered_at else None
            },
            'notes': {
                'buyer': order.buyer_note,
                'seller': order.seller_note
            },
            'created_at': order.created_at.isoformat(),
            'expire_at': order.expire_at.isoformat()
        })
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders/<int:order_id>/cancel', methods=['POST'])
@jwt_required()
@permission_required(Permission.ORDER_CANCEL)
@audit_log('取消订单')
def cancel_order(order_id):
    """取消订单"""
    data = request.get_json() or {}
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        order = service.cancel_order(
            order_id=order_id,
            user_id=identity['id'],
            reason=data.get('reason', '用户取消')
        )
        
        return success_response({
            'order_id': order.id,
            'status': order.status.value,
            'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else None
        }, '订单已取消')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders/<int:order_id>/pay', methods=['POST'])
@jwt_required()
@audit_log('支付订单')
def pay_order(order_id):
    """订单支付（模拟）"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        order = service.verify_payment(
            order_id=order_id,
            payment_method=data.get('payment_method', 'alipay'),
            transaction_no=data.get('transaction_no', f'TXN{datetime.now().strftime("%Y%m%d%H%M%S")}'),
            amount=decimal.Decimal(data.get('amount', '0'))
        )
        
        return success_response({
            'order_id': order.id,
            'status': order.status.value,
            'payment_status': order.payment_status.value,
            'paid_amount': str(order.paid_amount),
            'payment_time': order.payment_time.isoformat() if order.payment_time else None
        }, '支付成功')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders/<int:order_id>/ship', methods=['POST'])
@jwt_required()
@permission_required(Permission.ORDER_MANAGE)
@audit_log('订单发货')
def ship_order(order_id):
    """订单发货"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        order = service.ship_order(
            order_id=order_id,
            operator_id=identity['id'],
            logistics_company=data['logistics_company'],
            tracking_no=data['tracking_no']
        )
        
        return success_response({
            'order_id': order.id,
            'status': order.status.value,
            'logistics_company': order.logistics_company,
            'tracking_no': order.tracking_no,
            'shipped_at': order.shipped_at.isoformat() if order.shipped_at else None
        }, '发货成功')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/orders/<int:order_id>/confirm-delivery', methods=['POST'])
@jwt_required()
@audit_log('确认收货')
def confirm_delivery(order_id):
    """确认收货"""
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        order = service.confirm_delivery(
            order_id=order_id,
            user_id=identity['id']
        )
        
        return success_response({
            'order_id': order.id,
            'status': order.status.value,
            'delivered_at': order.delivered_at.isoformat() if order.delivered_at else None
        }, '确认收货成功')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


# ==================== 物流相关接口 ====================

@app.route('/api/logistics/tracking/<string:tracking_no>', methods=['GET'])
@jwt_required()
@permission_required(Permission.LOGISTICS_VIEW)
def get_logistics_tracking(tracking_no):
    """查询物流轨迹"""
    logistics_company = request.args.get('company', 'sf')
    
    try:
        service = LogisticsService(
            api_url=app.config['LOGISTICS_API_URL'],
            api_key=app.config['LOGISTICS_API_KEY'],
            use_mock=True  # 开发测试使用模拟
        )
        
        result = service.get_tracking(tracking_no, logistics_company)
        
        if not result.success:
            return error_response(result.error_message or '查询失败')
        
        return success_response({
            'tracking_no': result.tracking_no,
            'logistics_company': result.logistics_company,
            'status': result.status,
            'is_delivered': result.is_delivered,
            'delivered_time': result.delivered_time.isoformat() if result.delivered_time else None,
            'events': [{
                'time': e.time.isoformat(),
                'status': e.status,
                'description': e.description,
                'location': e.location,
                'operator': e.operator
            } for e in result.events]
        })
    except Exception as e:
        return error_response(str(e), status_code=500)


# ==================== 售后相关接口 ====================

@app.route('/api/orders/<int:order_id>/after-sales', methods=['POST'])
@jwt_required()
@permission_required(Permission.AFTER_SALES_VIEW)
@audit_log('申请售后')
def create_after_sales(order_id):
    """创建售后申请"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        after_sales = service.create_after_sales(
            order_id=order_id,
            user_id=identity['id'],
            type=AfterSalesType(data['type']),
            reason=data['reason'],
            description=data.get('description'),
            refund_amount=decimal.Decimal(data['refund_amount']) if data.get('refund_amount') else None,
            item_ids=data.get('item_ids')
        )
        
        return success_response({
            'after_sales_id': after_sales.id,
            'type': after_sales.type.value,
            'status': after_sales.status.value,
            'refund_amount': str(after_sales.refund_amount) if after_sales.refund_amount else None,
            'created_at': after_sales.created_at.isoformat()
        }, '售后申请已提交')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/after-sales/<int:after_sales_id>/approve', methods=['POST'])
@jwt_required()
@permission_required(Permission.AFTER_SALES_PROCESS)
@audit_log('审批售后')
def approve_after_sales(after_sales_id):
    """审批售后申请"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        service = OrderService()
        after_sales = service.approve_after_sales(
            after_sales_id=after_sales_id,
            operator_id=identity['id'],
            approved=data.get('approved', False),
            note=data.get('note')
        )
        
        return success_response({
            'after_sales_id': after_sales.id,
            'status': after_sales.status.value,
            'approved_by': after_sales.approved_by,
            'approved_at': after_sales.approved_at.isoformat() if after_sales.approved_at else None
        }, '审批完成')
    except OrderServiceError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(str(e), status_code=500)


# ==================== 数据分析接口 ====================

@app.route('/api/analytics/summary', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_VIEW)
def get_sales_summary():
    """获取销售汇总"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    try:
        analytics = OrderAnalytics()
        
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        summary = analytics.get_sales_summary(start, end)
        
        return success_response({
            'total_orders': summary.total_orders,
            'total_amount': str(summary.total_amount),
            'total_items': summary.total_items,
            'avg_order_value': str(summary.avg_order_value),
            'paid_orders': summary.paid_orders,
            'paid_amount': str(summary.paid_amount),
            'cancelled_orders': summary.cancelled_orders,
            'cancelled_amount': str(summary.cancelled_amount),
            'refund_amount': str(summary.refund_amount)
        })
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/analytics/sales-by-time', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_VIEW)
def get_sales_by_time():
    """按时间维度分析销售"""
    granularity = request.args.get('granularity', 'day')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    try:
        analytics = OrderAnalytics()
        
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        data = analytics.get_sales_by_time(granularity, start, end)
        
        return success_response([{
            'timestamp': d.timestamp.isoformat(),
            'orders_count': d.orders_count,
            'revenue': str(d.revenue),
            'items_count': d.items_count
        } for d in data])
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/analytics/top-products', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_VIEW)
def get_top_products():
    """产品销售排行"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    limit = int(request.args.get('limit', 20))
    
    try:
        analytics = OrderAnalytics()
        
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        products = analytics.get_product_sales(start, end, limit=limit)
        
        return success_response([{
            'product_id': p.product_id,
            'product_name': p.product_name,
            'sku': p.sku,
            'category': p.category_name,
            'quantity_sold': p.quantity_sold,
            'revenue': str(p.revenue),
            'orders_count': p.orders_count,
            'avg_price': str(p.avg_price)
        } for p in products])
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/analytics/category-sales', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_VIEW)
def get_category_sales():
    """分类销售统计"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    try:
        analytics = OrderAnalytics()
        
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        categories = analytics.get_category_sales(start, end)
        
        return success_response([{
            'category_id': c.category_id,
            'category_name': c.category_name,
            'quantity_sold': c.quantity_sold,
            'revenue': str(c.revenue),
            'orders_count': c.orders_count,
            'product_count': c.product_count,
            'avg_order_value': str(c.avg_order_value)
        } for c in categories])
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/analytics/dashboard', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_VIEW)
def get_dashboard():
    """获取实时仪表盘数据"""
    try:
        analytics = OrderAnalytics()
        dashboard = analytics.get_realtime_dashboard()
        
        return success_response({
            'today': {
                'orders': {
                    'total_orders': dashboard['today']['orders'].total_orders,
                    'total_amount': str(dashboard['today']['orders'].total_amount),
                    'paid_orders': dashboard['today']['orders'].paid_orders
                },
                'hourly_trend': [{
                    'timestamp': d.timestamp.isoformat(),
                    'orders': d.orders_count,
                    'revenue': str(d.revenue)
                } for d in dashboard['today']['hourly_trend']]
            },
            'pending_orders': dashboard['pending_orders'],
            'forecast': dashboard['forecast']
        })
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/analytics/export', methods=['GET'])
@jwt_required()
@permission_required(Permission.ANALYTICS_EXPORT)
def export_report():
    """导出分析报告"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    report_type = request.args.get('type', 'csv')
    
    try:
        analytics = OrderAnalytics()
        generator = ReportGenerator(analytics)
        
        start = datetime.fromisoformat(start_date) if start_date else datetime.now() - timedelta(days=30)
        end = datetime.fromisoformat(end_date) if end_date else datetime.now()
        
        if report_type == 'csv':
            csv_content = generator.generate_csv_report(start, end, 'orders')
            return Response(
                csv_content,
                mimetype='text/csv',
                headers={
                    'Content-Disposition': f'attachment; filename=sales_report_{start.strftime("%Y%m%d")}.csv'
                }
            )
        else:
            report = analytics.export_sales_report(start, end, 'full')
            return success_response(report)
    except Exception as e:
        return error_response(str(e), status_code=500)


# ==================== 库存管理接口 ====================

@app.route('/api/inventory/check', methods=['POST'])
@jwt_required()
@permission_required(Permission.INVENTORY_VIEW)
def check_inventory():
    """检查库存"""
    data = request.get_json()
    
    try:
        service = InventoryService()
        
        results = []
        for item in data.get('items', []):
            has_stock = service.check_stock(
                product_id=item['product_id'],
                quantity=item['quantity']
            )
            results.append({
                'product_id': item['product_id'],
                'requested': item['quantity'],
                'available': has_stock
            })
        
        return success_response({'items': results})
    except Exception as e:
        return error_response(str(e), status_code=500)


@app.route('/api/inventory/adjust', methods=['POST'])
@jwt_required()
@permission_required(Permission.INVENTORY_MANAGE)
@audit_log('调整库存')
def adjust_inventory():
    """调整库存"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    try:
        service = InventoryService()
        product = service.adjust_stock(
            product_id=data['product_id'],
            quantity_change=data['quantity_change'],
            reason=data['reason'],
            operator_id=identity['id']
        )
        
        return success_response({
            'product_id': product.id,
            'product_name': product.name,
            'current_stock': product.stock_quantity,
            'reserved_quantity': product.reserved_quantity
        }, '库存调整成功')
    except Exception as e:
        return error_response(str(e), status_code=500)


# ==================== 商品管理接口 ====================

@app.route('/api/products', methods=['GET'])
def get_products():
    """获取商品列表"""
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 20)), 100)
    category_id = request.args.get('category_id', type=int)
    
    query = Product.query.filter_by(is_active=True)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    total = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()
    
    items = [{
        'id': p.id,
        'sku': p.sku,
        'name': p.name,
        'description': p.description,
        'price': str(p.price),
        'stock_quantity': p.stock_quantity,
        'category_id': p.category_id,
        'weight': p.weight
    } for p in products]
    
    return paginated_response(items, total, page, per_page)


@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product_detail(product_id):
    """获取商品详情"""
    product = Product.query.get(product_id)
    
    if not product:
        return error_response('商品不存在', 'product_not_found', 404)
    
    return success_response({
        'id': product.id,
        'sku': product.sku,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'stock_quantity': product.stock_quantity,
        'category': {
            'id': product.category.id if product.category else None,
            'name': product.category.name if product.category else None
        },
        'weight': product.weight,
        'is_active': product.is_active
    })


# ==================== 地址管理接口 ====================

@app.route('/api/addresses', methods=['GET'])
@jwt_required()
def get_addresses():
    """获取用户地址列表"""
    identity = get_jwt_identity()
    
    addresses = Address.query.filter_by(user_id=identity['id']).all()
    
    return success_response([{
        'id': a.id,
        'receiver_name': a.receiver_name,
        'phone': a.phone,
        'province': a.province,
        'city': a.city,
        'district': a.district,
        'detail_address': a.detail_address,
        'zip_code': a.zip_code,
        'is_default': a.is_default
    } for a in addresses])


@app.route('/api/addresses', methods=['POST'])
@jwt_required()
def create_address():
    """创建收货地址"""
    data = request.get_json()
    identity = get_jwt_identity()
    
    address = Address(
        user_id=identity['id'],
        receiver_name=data['receiver_name'],
        phone=data['phone'],
        province=data['province'],
        city=data['city'],
        district=data['district'],
        detail_address=data['detail_address'],
        zip_code=data.get('zip_code'),
        is_default=data.get('is_default', False)
    )
    
    db.session.add(address)
    db.session.commit()
    
    return success_response({'id': address.id}, '地址创建成功')


# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    return error_response('接口不存在', 'not_found', 404)


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return error_response('服务器内部错误', 'internal_error', 500)


# ==================== 健康检查 ====================

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return success_response({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
