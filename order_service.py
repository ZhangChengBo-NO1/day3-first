import uuid
import json
import hashlib
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
import requests
import logging

from flask import current_app
from sqlalchemy import or_, and_, func
from sqlalchemy.exc import IntegrityError

from order_models import (
    db, Order, OrderItem, Product, User, PaymentRecord,
    AfterSales, AfterSalesStatus, AfterSalesType,
    LogisticsRecord, InventoryLog, ERPIntegration, CRMIntegration,
    SystemLog, OrderStatus, PaymentStatus, UserRole
)
from logistics_client import LogisticsService, LogisticsException

logger = logging.getLogger(__name__)


class OrderException(Exception):
    pass


class InventoryException(Exception):
    pass


class PaymentException(Exception):
    pass


class PermissionDenied(Exception):
    pass


class OrderNumberGenerator:
    
    @staticmethod
    def generate() -> str:
        date_str = datetime.now().strftime('%Y%m%d%H%M%S')
        random_str = uuid.uuid4().hex[:8].upper()
        return f'ORD{date_str}{random_str}'


class InventoryService:
    
    @staticmethod
    def check_inventory(product_id: int, quantity: int) -> Tuple[bool, int]:
        product = Product.query.get(product_id)
        if not product:
            return False, 0
        available = product.available_inventory
        return available >= quantity, available
    
    @staticmethod
    def reserve_inventory(product_id: int, quantity: int, order_id: int = None, operator_id: int = None) -> bool:
        product = Product.query.get(product_id)
        if not product:
            raise InventoryException(f'商品不存在: {product_id}')
        
        if product.available_inventory < quantity:
            raise InventoryException(f'库存不足: 可用库存 {product.available_inventory}, 需要 {quantity}')
        
        before_quantity = product.inventory
        product.reserved_inventory += quantity
        
        log = InventoryLog(
            product_id=product_id,
            order_id=order_id,
            change_type='reserve',
            quantity=quantity,
            before_quantity=before_quantity,
            after_quantity=product.inventory,
            remark=f'订单预留库存',
            operator_id=operator_id
        )
        db.session.add(log)
        
        return True
    
    @staticmethod
    def deduct_inventory(product_id: int, quantity: int, order_id: int = None, operator_id: int = None) -> bool:
        product = Product.query.get(product_id)
        if not product:
            raise InventoryException(f'商品不存在: {product_id}')
        
        before_quantity = product.inventory
        product.inventory -= quantity
        product.reserved_inventory -= quantity
        
        if product.inventory < 0:
            db.session.rollback()
            raise InventoryException(f'库存扣减失败: 库存不足')
        
        log = InventoryLog(
            product_id=product_id,
            order_id=order_id,
            change_type='deduct',
            quantity=quantity,
            before_quantity=before_quantity,
            after_quantity=product.inventory,
            remark=f'订单扣减库存',
            operator_id=operator_id
        )
        db.session.add(log)
        
        return True
    
    @staticmethod
    def release_inventory(product_id: int, quantity: int, order_id: int = None, operator_id: int = None) -> bool:
        product = Product.query.get(product_id)
        if not product:
            raise InventoryException(f'商品不存在: {product_id}')
        
        before_quantity = product.inventory
        release_qty = min(quantity, product.reserved_inventory)
        product.reserved_inventory -= release_qty
        
        log = InventoryLog(
            product_id=product_id,
            order_id=order_id,
            change_type='release',
            quantity=release_qty,
            before_quantity=before_quantity,
            after_quantity=product.inventory,
            remark=f'订单释放库存',
            operator_id=operator_id
        )
        db.session.add(log)
        
        return True
    
    @staticmethod
    def restock_inventory(product_id: int, quantity: int, order_id: int = None, operator_id: int = None, remark: str = '') -> bool:
        product = Product.query.get(product_id)
        if not product:
            raise InventoryException(f'商品不存在: {product_id}')
        
        before_quantity = product.inventory
        product.inventory += quantity
        
        log = InventoryLog(
            product_id=product_id,
            order_id=order_id,
            change_type='restock',
            quantity=quantity,
            before_quantity=before_quantity,
            after_quantity=product.inventory,
            remark=remark or '库存回滚',
            operator_id=operator_id
        )
        db.session.add(log)
        
        return True


class PaymentService:
    
    def __init__(self, config):
        self.gateway_url = config.PAYMENT_GATEWAY_URL
        self.merchant_id = config.PAYMENT_MERCHANT_ID
        self.secret_key = config.PAYMENT_SECRET_KEY
    
    def _generate_sign(self, data: Dict) -> str:
        sorted_keys = sorted(data.keys())
        sign_str = '&'.join([f'{k}={data[k]}' for k in sorted_keys])
        sign_str += f'&key={self.secret_key}'
        return hashlib.md5(sign_str.encode()).hexdigest().upper()
    
    def create_payment(self, order: Order, payment_method: str) -> Dict:
        transaction_id = f'TXN{int(time.time()*1000)}{uuid.uuid4().hex[:6].upper()}'
        
        record = PaymentRecord(
            order_id=order.id,
            transaction_id=transaction_id,
            payment_method=payment_method,
            amount=order.total_amount,
            status=PaymentStatus.PENDING
        )
        db.session.add(record)
        db.session.commit()
        
        payment_data = {
            'merchant_id': self.merchant_id,
            'order_no': order.order_no,
            'transaction_id': transaction_id,
            'amount': str(order.total_amount),
            'payment_method': payment_method,
            'notify_url': '/api/payment/callback',
            'return_url': '/order/payment/result',
            'timestamp': str(int(time.time()))
        }
        payment_data['sign'] = self._generate_sign(payment_data)
        
        return {
            'transaction_id': transaction_id,
            'payment_url': f'{self.gateway_url}/pay',
            'payment_data': payment_data
        }
    
    def verify_callback(self, callback_data: Dict) -> Tuple[bool, Optional[str]]:
        sign = callback_data.pop('sign', None)
        if not sign:
            return False, '缺少签名'
        
        expected_sign = self._generate_sign(callback_data)
        if sign != expected_sign:
            return False, '签名验证失败'
        
        return True, None
    
    def process_callback(self, callback_data: Dict) -> Dict:
        is_valid, error = self.verify_callback(callback_data.copy())
        if not is_valid:
            raise PaymentException(error)
        
        transaction_id = callback_data.get('transaction_id')
        status = callback_data.get('status')
        
        record = PaymentRecord.query.filter_by(transaction_id=transaction_id).first()
        if not record:
            raise PaymentException(f'支付记录不存在: {transaction_id}')
        
        order = Order.query.get(record.order_id)
        if not order:
            raise PaymentException(f'订单不存在')
        
        if status == 'success':
            record.status = PaymentStatus.SUCCESS
            record.gateway_response = json.dumps(callback_data)
            
            order.payment_status = PaymentStatus.SUCCESS
            order.payment_transaction_id = transaction_id
            order.payment_time = datetime.utcnow()
            order.status = OrderStatus.PAID
            
            db.session.commit()
            
            return {'success': True, 'order_no': order.order_no, 'status': 'paid'}
        else:
            record.status = PaymentStatus.FAILED
            record.error_message = callback_data.get('message', '支付失败')
            db.session.commit()
            
            return {'success': False, 'order_no': order.order_no, 'status': 'failed'}
    
    def refund(self, order: Order, amount: Decimal = None, reason: str = '') -> Dict:
        refund_amount = amount or order.total_amount
        
        refund_data = {
            'merchant_id': self.merchant_id,
            'order_no': order.order_no,
            'transaction_id': order.payment_transaction_id,
            'refund_amount': str(refund_amount),
            'reason': reason,
            'timestamp': str(int(time.time()))
        }
        refund_data['sign'] = self._generate_sign(refund_data)
        
        try:
            response = requests.post(
                f'{self.gateway_url}/refund',
                json=refund_data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('success'):
                order.payment_status = PaymentStatus.REFUNDED
                db.session.commit()
                return {'success': True, 'refund_id': result.get('refund_id')}
            else:
                raise PaymentException(result.get('message', '退款失败'))
        except requests.RequestException as e:
            raise PaymentException(f'退款请求失败: {str(e)}')


class ERPIntegrationService:
    
    def __init__(self, config):
        self.api_url = config.ERP_API_URL
        self.api_key = config.ERP_API_KEY
    
    def sync_order(self, order: Order) -> Dict:
        integration = ERPIntegration.query.filter_by(order_id=order.id).first()
        if not integration:
            integration = ERPIntegration(order_id=order.id)
            db.session.add(integration)
        
        order_data = {
            'order_no': order.order_no,
            'customer_id': order.user_id,
            'total_amount': str(order.total_amount),
            'status': order.status.value,
            'items': [item.to_dict() for item in order.items],
            'shipping_address': {
                'name': order.recipient_name,
                'phone': order.recipient_phone,
                'address': order.recipient_address
            }
        }
        
        try:
            response = requests.post(
                f'{self.api_url}/orders/sync',
                json=order_data,
                headers={'X-API-Key': self.api_key},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            integration.erp_order_id = result.get('erp_order_id')
            integration.sync_status = 'success'
            integration.synced_at = datetime.utcnow()
            integration.sync_data = json.dumps(order_data)
            db.session.commit()
            
            return {'success': True, 'erp_order_id': integration.erp_order_id}
        except Exception as e:
            integration.sync_status = 'failed'
            integration.error_message = str(e)
            db.session.commit()
            logger.error(f'ERP sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}


class CRMIntegrationService:
    
    def __init__(self, config):
        self.api_url = config.CRM_API_URL
        self.api_key = config.CRM_API_KEY
    
    def sync_customer(self, user: User) -> Dict:
        customer_data = {
            'customer_id': user.id,
            'username': user.username,
            'email': user.email,
            'phone': user.phone,
            'created_at': user.created_at.isoformat() if user.created_at else None
        }
        
        try:
            response = requests.post(
                f'{self.api_url}/customers/sync',
                json=customer_data,
                headers={'X-API-Key': self.api_key},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            return {'success': True, 'crm_customer_id': result.get('crm_customer_id')}
        except Exception as e:
            logger.error(f'CRM sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def sync_order(self, order: Order) -> Dict:
        integration = CRMIntegration.query.filter_by(
            user_id=order.user_id,
            order_id=order.id
        ).first()
        
        order_data = {
            'order_no': order.order_no,
            'customer_id': order.user_id,
            'total_amount': str(order.total_amount),
            'status': order.status.value,
            'created_at': order.created_at.isoformat() if order.created_at else None
        }
        
        try:
            response = requests.post(
                f'{self.api_url}/orders/sync',
                json=order_data,
                headers={'X-API-Key': self.api_key},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if integration:
                integration.sync_status = 'success'
                integration.synced_at = datetime.utcnow()
            db.session.commit()
            
            return {'success': True}
        except Exception as e:
            if integration:
                integration.sync_status = 'failed'
                integration.error_message = str(e)
                db.session.commit()
            logger.error(f'CRM order sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}


class OrderService:
    
    def __init__(self, config):
        self.config = config
        self.payment_service = PaymentService(config)
        self.logistics_service = LogisticsService(config)
        self.erp_service = ERPIntegrationService(config)
        self.crm_service = CRMIntegrationService(config)
    
    def create_order(self, user_id: int, items: List[Dict], shipping_info: Dict,
                     payment_method: str, remark: str = '', source: str = 'web',
                     ip_address: str = None) -> Order:
        
        user = User.query.get(user_id)
        if not user:
            raise OrderException('用户不存在')
        
        for item in items:
            product_id = item.get('product_id')
            quantity = item.get('quantity', 1)
            available, _ = InventoryService.check_inventory(product_id, quantity)
            if not available:
                product = Product.query.get(product_id)
                raise OrderException(f'商品 {product.name if product else product_id} 库存不足')
        
        order = Order(
            order_no=OrderNumberGenerator.generate(),
            user_id=user_id,
            status=OrderStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
            recipient_name=shipping_info.get('recipient_name'),
            recipient_phone=shipping_info.get('recipient_phone'),
            recipient_address=shipping_info.get('address'),
            province=shipping_info.get('province'),
            city=shipping_info.get('city'),
            district=shipping_info.get('district'),
            postal_code=shipping_info.get('postal_code'),
            payment_method=payment_method,
            remark=remark,
            source=source,
            ip_address=ip_address
        )
        db.session.add(order)
        db.session.flush()
        
        total_weight = Decimal('0')
        for item_data in items:
            product = Product.query.get(item_data['product_id'])
            if not product:
                db.session.rollback()
                raise OrderException(f'商品不存在: {item_data["product_id"]}')
            
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                sku=product.sku,
                product_name=product.name,
                product_image=item_data.get('image'),
                quantity=item_data['quantity'],
                unit_price=product.price,
                discount_amount=Decimal(str(item_data.get('discount', 0)))
            )
            item.calculate_subtotal()
            db.session.add(item)
            
            try:
                InventoryService.reserve_inventory(
                    product.id, item.quantity, order.id, user_id
                )
            except InventoryException as e:
                db.session.rollback()
                raise OrderException(str(e))
            
            if product.weight:
                total_weight += Decimal(str(product.weight)) * item.quantity
        
        order.calculate_total()
        
        shipping_fee_info = self.logistics_service.calculate_shipping_fee({
            'weight': float(total_weight),
            'province': shipping_info.get('province', '')
        })
        order.shipping_fee = Decimal(str(shipping_fee_info['total_fee']))
        order.calculate_total()
        
        db.session.commit()
        
        self._log_action('order', 'create', 'order', order.id, user_id, 
                        {'order_no': order.order_no})
        
        return order
    
    def cancel_order(self, order_id: int, user_id: int, reason: str = '') -> Order:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        user = User.query.get(user_id)
        if not user:
            raise PermissionDenied('用户不存在')
        
        if order.user_id != user_id and not user.has_permission(UserRole.OPERATOR):
            raise PermissionDenied('无权取消此订单')
        
        if order.status not in [OrderStatus.PENDING, OrderStatus.PAID]:
            raise OrderException(f'订单状态 {order.status.value} 不允许取消')
        
        for item in order.items:
            InventoryService.release_inventory(
                item.product_id, item.quantity, order.id, user_id
            )
        
        if order.payment_status == PaymentStatus.SUCCESS:
            try:
                self.payment_service.refund(order, reason=f'订单取消: {reason}')
            except PaymentException as e:
                logger.error(f'Refund failed for order {order.order_no}: {str(e)}')
        
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.utcnow()
        order.cancel_reason = reason
        
        db.session.commit()
        
        self._log_action('order', 'cancel', 'order', order.id, user_id,
                        {'order_no': order.order_no, 'reason': reason})
        
        return order
    
    def confirm_payment(self, order_id: int, payment_data: Dict) -> Order:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if order.status != OrderStatus.PENDING:
            raise OrderException('订单状态不正确')
        
        try:
            result = self.payment_service.process_callback(payment_data)
            if result.get('success'):
                order = Order.query.get(order_id)
                return order
            else:
                raise OrderException('支付处理失败')
        except PaymentException as e:
            raise OrderException(str(e))
    
    def confirm_order(self, order_id: int, operator_id: int) -> Order:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if order.status != OrderStatus.PAID:
            raise OrderException('订单状态不正确')
        
        for item in order.items:
            try:
                InventoryService.deduct_inventory(
                    item.product_id, item.quantity, order.id, operator_id
                )
            except InventoryException as e:
                db.session.rollback()
                raise OrderException(str(e))
        
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = datetime.utcnow()
        
        db.session.commit()
        
        self.erp_service.sync_order(order)
        
        self._log_action('order', 'confirm', 'order', order.id, operator_id,
                        {'order_no': order.order_no})
        
        return order
    
    def ship_order(self, order_id: int, operator_id: int, logistics_company: str,
                   tracking_number: str = None) -> Order:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if order.status not in [OrderStatus.CONFIRMED, OrderStatus.PROCESSING]:
            raise OrderException('订单状态不正确')
        
        if not tracking_number:
            try:
                shipping_info = {
                    'order_id': order.order_no,
                    'recipient_name': order.recipient_name,
                    'recipient_phone': order.recipient_phone,
                    'province': order.province,
                    'city': order.city,
                    'district': order.district,
                    'recipient_address': order.recipient_address,
                    'weight': sum(
                        float(item.product.weight or 0) * item.quantity 
                        for item in order.items
                    )
                }
                result = self.logistics_service.create_shipment(logistics_company, shipping_info)
                tracking_number = result.get('tracking_number')
            except LogisticsException as e:
                raise OrderException(f'创建运单失败: {str(e)}')
        
        order.status = OrderStatus.SHIPPED
        order.logistics_company = logistics_company
        order.tracking_number = tracking_number
        order.shipping_time = datetime.utcnow()
        
        logistics_record = LogisticsRecord(
            order_id=order.id,
            logistics_company=logistics_company,
            tracking_number=tracking_number,
            status='shipped',
            description='订单已发货',
            occurred_at=datetime.utcnow()
        )
        db.session.add(logistics_record)
        
        db.session.commit()
        
        self._log_action('order', 'ship', 'order', order.id, operator_id,
                        {'order_no': order.order_no, 'tracking_number': tracking_number})
        
        return order
    
    def confirm_delivery(self, order_id: int, operator_id: int = None) -> Order:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if order.status != OrderStatus.SHIPPED:
            raise OrderException('订单状态不正确')
        
        order.status = OrderStatus.DELIVERED
        order.delivery_time = datetime.utcnow()
        
        logistics_record = LogisticsRecord(
            order_id=order.id,
            logistics_company=order.logistics_company,
            tracking_number=order.tracking_number,
            status='delivered',
            description='订单已签收',
            occurred_at=datetime.utcnow()
        )
        db.session.add(logistics_record)
        
        db.session.commit()
        
        self.crm_service.sync_order(order)
        
        self._log_action('order', 'deliver', 'order', order.id, operator_id,
                        {'order_no': order.order_no})
        
        return order
    
    def query_logistics(self, order_id: int) -> Dict:
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if not order.tracking_number:
            return {'success': False, 'message': '暂无物流信息'}
        
        try:
            result = self.logistics_service.query_tracking(
                order.logistics_company, order.tracking_number
            )
            return result
        except LogisticsException as e:
            return {'success': False, 'message': str(e)}


class AfterSalesService:
    
    def __init__(self, config):
        self.config = config
        self.payment_service = PaymentService(config)
    
    def create_after_sales(self, order_id: int, user_id: int, after_sales_type: AfterSalesType,
                          reason: str, description: str = '', order_item_id: int = None,
                          evidence_urls: List[str] = None) -> AfterSales:
        
        order = Order.query.get(order_id)
        if not order:
            raise OrderException('订单不存在')
        
        if order.user_id != user_id:
            raise PermissionDenied('无权操作此订单')
        
        days_since_delivery = (datetime.utcnow() - order.delivery_time).days if order.delivery_time else 999
        if days_since_delivery > self.config.AFTER_SALES_DAYS_LIMIT:
            raise OrderException(f'已超过售后申请期限({self.config.AFTER_SALES_DAYS_LIMIT}天)')
        
        existing = AfterSales.query.filter_by(
            order_id=order_id,
            status=AfterSalesStatus.PENDING
        ).first()
        if existing:
            raise OrderException('该订单已有待处理的售后申请')
        
        after_sales = AfterSales(
            order_id=order_id,
            order_item_id=order_item_id,
            user_id=user_id,
            type=after_sales_type,
            status=AfterSalesStatus.PENDING,
            reason=reason,
            description=description,
            evidence_urls=json.dumps(evidence_urls) if evidence_urls else None
        )
        db.session.add(after_sales)
        
        order.status = OrderStatus.AFTER_SALES
        
        db.session.commit()
        
        return after_sales
    
    def approve_after_sales(self, after_sales_id: int, operator_id: int,
                           approved_amount: Decimal = None, remark: str = '') -> AfterSales:
        
        after_sales = AfterSales.query.get(after_sales_id)
        if not after_sales:
            raise OrderException('售后申请不存在')
        
        if after_sales.status != AfterSalesStatus.PENDING:
            raise OrderException('售后申请状态不正确')
        
        after_sales.status = AfterSalesStatus.APPROVED
        after_sales.handler_id = operator_id
        after_sales.handler_remark = remark
        after_sales.approved_amount = approved_amount
        after_sales.processed_at = datetime.utcnow()
        
        db.session.commit()
        
        return after_sales
    
    def reject_after_sales(self, after_sales_id: int, operator_id: int, reason: str) -> AfterSales:
        
        after_sales = AfterSales.query.get(after_sales_id)
        if not after_sales:
            raise OrderException('售后申请不存在')
        
        if after_sales.status != AfterSalesStatus.PENDING:
            raise OrderException('售后申请状态不正确')
        
        after_sales.status = AfterSalesStatus.REJECTED
        after_sales.handler_id = operator_id
        after_sales.handler_remark = reason
        after_sales.processed_at = datetime.utcnow()
        
        order = after_sales.order
        order.status = OrderStatus.DELIVERED
        
        db.session.commit()
        
        return after_sales
    
    def process_refund(self, after_sales_id: int, operator_id: int) -> AfterSales:
        
        after_sales = AfterSales.query.get(after_sales_id)
        if not after_sales:
            raise OrderException('售后申请不存在')
        
        if after_sales.status != AfterSalesStatus.APPROVED:
            raise OrderException('售后申请状态不正确')
        
        order = after_sales.order
        refund_amount = after_sales.approved_amount or order.total_amount
        
        try:
            self.payment_service.refund(order, refund_amount, f'售后退款: {after_sales.reason}')
        except PaymentException as e:
            raise OrderException(f'退款失败: {str(e)}')
        
        if after_sales.type in [AfterSalesType.RETURN, AfterSalesType.REFUND_ONLY]:
            for item in order.items:
                InventoryService.restock_inventory(
                    item.product_id, item.quantity, order.id, operator_id,
                    f'售后退货入库: {after_sales.type.value}'
                )
        
        after_sales.status = AfterSalesStatus.COMPLETED
        after_sales.refund_amount = refund_amount
        after_sales.completed_at = datetime.utcnow()
        
        order.status = OrderStatus.REFUNDED
        
        db.session.commit()
        
        return after_sales


class PermissionService:
    
    @staticmethod
    def check_permission(user: User, action: str, resource_type: str, resource_id: int = None) -> bool:
        if user.role == UserRole.ADMIN:
            return True
        
        permissions = {
            'order': {
                'view': UserRole.CUSTOMER,
                'create': UserRole.CUSTOMER,
                'cancel': UserRole.CUSTOMER,
                'confirm': UserRole.OPERATOR,
                'ship': UserRole.OPERATOR,
                'deliver': UserRole.OPERATOR,
                'list_all': UserRole.OPERATOR
            },
            'product': {
                'view': UserRole.CUSTOMER,
                'create': UserRole.MANAGER,
                'update': UserRole.MANAGER,
                'delete': UserRole.ADMIN
            },
            'after_sales': {
                'view': UserRole.CUSTOMER,
                'create': UserRole.CUSTOMER,
                'approve': UserRole.OPERATOR,
                'reject': UserRole.OPERATOR,
                'process': UserRole.OPERATOR
            },
            'analytics': {
                'view': UserRole.MANAGER,
                'export': UserRole.MANAGER
            },
            'user': {
                'view': UserRole.OPERATOR,
                'create': UserRole.ADMIN,
                'update': UserRole.ADMIN,
                'delete': UserRole.ADMIN
            }
        }
        
        required_role = permissions.get(resource_type, {}).get(action)
        if not required_role:
            return False
        
        return user.has_permission(required_role)
    
    @staticmethod
    def filter_by_permission(user: User, query, resource_type: str):
        if user.role == UserRole.ADMIN:
            return query
        
        if resource_type == 'order':
            if user.role == UserRole.CUSTOMER:
                return query.filter(Order.user_id == user.id)
        
        return query
