import decimal
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from order_models import (
    db, Order, OrderItem, Product, User, Address, Cart,
    OrderStatus, PaymentStatus, LogisticsStatus,
    AfterSales, AfterSalesType, AfterSalesStatus,
    InventoryLog, OrderOperationLog, PaymentLog
)


class OrderServiceError(Exception):
    pass


class InsufficientStockError(OrderServiceError):
    pass


class OrderNotFoundError(OrderServiceError):
    pass


class InvalidOrderStatusError(OrderServiceError):
    pass


class PaymentVerificationError(OrderServiceError):
    pass


class OrderService:
    
    def __init__(self, db_session=None):
        self.db = db_session or db.session
    
    @contextmanager
    def transaction(self):
        try:
            yield
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise e
    
    def create_order(
        self,
        user_id: int,
        address_id: int,
        cart_item_ids: Optional[List[int]] = None,
        items: Optional[List[Dict]] = None,
        buyer_note: Optional[str] = None
    ) -> Order:
        """
        创建订单
        
        Args:
            user_id: 用户ID
            address_id: 收货地址ID
            cart_item_ids: 购物车项ID列表（可选）
            items: 直接购买的商品列表 [{'product_id': int, 'quantity': int}]（可选）
            buyer_note: 买家备注
        """
        with self.transaction():
            # 验证用户和地址
            user = self.db.query(User).get(user_id)
            if not user:
                raise OrderServiceError(f"用户不存在: {user_id}")
            
            address = self.db.query(Address).filter_by(
                id=address_id, user_id=user_id
            ).first()
            if not address:
                raise OrderServiceError("收货地址不存在")
            
            # 准备订单商品
            order_items_data = []
            
            if cart_item_ids:
                # 从购物车创建
                cart_items = self.db.query(Cart).filter(
                    Cart.id.in_(cart_item_ids),
                    Cart.user_id == user_id
                ).all()
                
                for cart_item in cart_items:
                    product = self.db.query(Product).get(cart_item.product_id)
                    if not product or not product.is_active:
                        raise OrderServiceError(f"商品不存在或已下架: {cart_item.product_id}")
                    
                    order_items_data.append({
                        'product': product,
                        'quantity': cart_item.quantity,
                        'unit_price': product.price
                    })
            
            elif items:
                # 直接购买
                for item in items:
                    product = self.db.query(Product).get(item['product_id'])
                    if not product or not product.is_active:
                        raise OrderServiceError(f"商品不存在或已下架: {item['product_id']}")
                    
                    order_items_data.append({
                        'product': product,
                        'quantity': item['quantity'],
                        'unit_price': product.price
                    })
            else:
                raise OrderServiceError("必须提供购物车项或商品列表")
            
            if not order_items_data:
                raise OrderServiceError("订单商品不能为空")
            
            # 检查库存并预留
            for item_data in order_items_data:
                product = item_data['product']
                quantity = item_data['quantity']
                
                available_stock = product.stock_quantity - product.reserved_quantity
                if available_stock < quantity:
                    raise InsufficientStockError(
                        f"商品 {product.name} 库存不足，可用: {available_stock}, 需要: {quantity}"
                    )
                
                # 预留库存
                product.reserved_quantity += quantity
                
                # 记录库存日志
                inventory_log = InventoryLog(
                    product_id=product.id,
                    change_type='reserve',
                    quantity_change=-quantity,
                    quantity_before=product.stock_quantity,
                    quantity_after=product.stock_quantity,
                    reason=f"订单预留: 创建订单"
                )
                self.db.add(inventory_log)
            
            # 计算金额
            subtotal = sum(
                item['unit_price'] * item['quantity']
                for item in order_items_data
            )
            shipping_fee = self._calculate_shipping_fee(order_items_data, address)
            discount = self._calculate_discount(subtotal)
            tax = (subtotal - discount) * decimal.Decimal('0.06')  # 6%税率
            total = subtotal + shipping_fee + tax - discount
            
            # 创建订单
            order = Order(
                order_no=Order.generate_order_no(),
                user_id=user_id,
                address_id=address_id,
                subtotal_amount=subtotal,
                discount_amount=discount,
                shipping_fee=shipping_fee,
                tax_amount=tax,
                total_amount=total,
                status=OrderStatus.PENDING_PAYMENT,
                payment_status=PaymentStatus.PENDING,
                logistics_status=LogisticsStatus.PENDING,
                expire_at=datetime.utcnow() + timedelta(minutes=30),
                buyer_note=buyer_note
            )
            self.db.add(order)
            self.db.flush()  # 获取order.id
            
            # 创建订单项
            for item_data in order_items_data:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=item_data['product'].id,
                    product_name=item_data['product'].name,
                    product_sku=item_data['product'].sku,
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_price=item_data['unit_price'] * item_data['quantity']
                )
                self.db.add(order_item)
            
            # 记录操作日志
            self._log_operation(order.id, user_id, user.username, 'create_order', 
                              None, OrderStatus.PENDING_PAYMENT.value, "创建订单")
            
            # 删除购物车项
            if cart_item_ids:
                self.db.query(Cart).filter(
                    Cart.id.in_(cart_item_ids)
                ).delete(synchronize_session=False)
            
            return order
    
    def cancel_order(
        self,
        order_id: int,
        user_id: int,
        reason: str = "用户取消"
    ) -> Order:
        """取消订单"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.user_id != user_id:
                raise OrderServiceError("无权操作此订单")
            
            # 检查订单状态
            if order.status not in [OrderStatus.PENDING_PAYMENT, OrderStatus.PAID]:
                raise InvalidOrderStatusError(f"当前状态 {order.status.value} 不允许取消")
            
            # 如果已支付，需要退款
            if order.status == OrderStatus.PAID:
                # 调用退款逻辑
                self._process_refund(order, order.paid_amount, reason)
            
            # 释放库存
            for item in order.items:
                product = self.db.query(Product).get(item.product_id)
                if product:
                    product.reserved_quantity -= item.quantity
                    
                    inventory_log = InventoryLog(
                        product_id=product.id,
                        order_id=order.id,
                        change_type='release',
                        quantity_change=item.quantity,
                        quantity_before=product.stock_quantity,
                        quantity_after=product.stock_quantity,
                        reason=f"订单取消: {reason}"
                    )
                    self.db.add(inventory_log)
            
            # 更新订单状态
            old_status = order.status
            order.status = OrderStatus.CANCELLED
            order.cancelled_at = datetime.utcnow()
            order.payment_status = PaymentStatus.REFUNDED if old_status == OrderStatus.PAID else PaymentStatus.FAILED
            
            # 记录操作日志
            user = self.db.query(User).get(user_id)
            self._log_operation(order.id, user_id, user.username, 'cancel_order',
                              old_status.value, OrderStatus.CANCELLED.value, reason)
            
            return order
    
    def verify_payment(
        self,
        order_id: int,
        payment_method: str,
        transaction_no: str,
        amount: decimal.Decimal
    ) -> Order:
        """验证支付"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.status != OrderStatus.PENDING_PAYMENT:
                raise InvalidOrderStatusError(f"订单状态 {order.status.value} 不允许支付")
            
            if order.expire_at < datetime.utcnow():
                raise OrderServiceError("订单已过期")
            
            # 验证金额
            if amount != order.total_amount:
                raise PaymentVerificationError(f"支付金额不匹配: {amount} != {order.total_amount}")
            
            # 记录支付日志
            payment_log = PaymentLog(
                order_id=order.id,
                transaction_no=transaction_no,
                payment_method=payment_method,
                amount=amount,
                status=PaymentStatus.SUCCESS
            )
            self.db.add(payment_log)
            
            # 更新订单
            old_status = order.status
            order.status = OrderStatus.PAID
            order.payment_status = PaymentStatus.SUCCESS
            order.payment_method = payment_method
            order.payment_time = datetime.utcnow()
            order.paid_amount = amount
            
            # 扣减实际库存
            for item in order.items:
                product = self.db.query(Product).get(item.product_id)
                if product:
                    old_stock = product.stock_quantity
                    product.stock_quantity -= item.quantity
                    product.reserved_quantity -= item.quantity
                    
                    inventory_log = InventoryLog(
                        product_id=product.id,
                        order_id=order.id,
                        change_type='deduct',
                        quantity_change=-item.quantity,
                        quantity_before=old_stock,
                        quantity_after=product.stock_quantity,
                        reason="支付成功扣减库存"
                    )
                    self.db.add(inventory_log)
            
            # 记录操作日志
            self._log_operation(order.id, 0, "system", 'verify_payment',
                              old_status.value, OrderStatus.PAID.value,
                              f"支付成功: {payment_method}, 交易号: {transaction_no}")
            
            return order
    
    def ship_order(
        self,
        order_id: int,
        operator_id: int,
        logistics_company: str,
        tracking_no: str
    ) -> Order:
        """订单发货"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.status != OrderStatus.PAID:
                raise InvalidOrderStatusError(f"订单状态 {order.status.value} 不允许发货")
            
            # 更新订单
            old_status = order.status
            order.status = OrderStatus.SHIPPED
            order.logistics_status = LogisticsStatus.IN_TRANSIT
            order.logistics_company = logistics_company
            order.tracking_no = tracking_no
            order.shipped_at = datetime.utcnow()
            
            # 记录操作日志
            operator = self.db.query(User).get(operator_id)
            self._log_operation(order.id, operator_id, operator.username, 'ship_order',
                              old_status.value, OrderStatus.SHIPPED.value,
                              f"发货: {logistics_company}, 单号: {tracking_no}")
            
            return order
    
    def confirm_delivery(self, order_id: int, user_id: int) -> Order:
        """确认收货"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.user_id != user_id:
                raise OrderServiceError("无权操作此订单")
            
            if order.status != OrderStatus.SHIPPED:
                raise InvalidOrderStatusError(f"订单状态 {order.status.value} 不允许确认收货")
            
            old_status = order.status
            order.status = OrderStatus.DELIVERED
            order.logistics_status = LogisticsStatus.DELIVERED
            order.delivered_at = datetime.utcnow()
            
            user = self.db.query(User).get(user_id)
            self._log_operation(order.id, user_id, user.username, 'confirm_delivery',
                              old_status.value, OrderStatus.DELIVERED.value, "确认收货")
            
            return order
    
    def complete_order(self, order_id: int, operator_id: int) -> Order:
        """完成订单"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.status != OrderStatus.DELIVERED:
                raise InvalidOrderStatusError(f"订单状态 {order.status.value} 不允许完成")
            
            old_status = order.status
            order.status = OrderStatus.COMPLETED
            order.completed_at = datetime.utcnow()
            
            operator = self.db.query(User).get(operator_id)
            self._log_operation(order.id, operator_id, operator.username, 'complete_order',
                              old_status.value, OrderStatus.COMPLETED.value, "订单完成")
            
            return order
    
    def create_after_sales(
        self,
        order_id: int,
        user_id: int,
        type: AfterSalesType,
        reason: str,
        description: Optional[str] = None,
        refund_amount: Optional[decimal.Decimal] = None,
        item_ids: Optional[List[int]] = None
    ) -> AfterSales:
        """创建售后申请"""
        with self.transaction():
            order = self._get_order_with_lock(order_id)
            
            if order.user_id != user_id:
                raise OrderServiceError("无权操作此订单")
            
            if order.status not in [OrderStatus.PAID, OrderStatus.SHIPPED, 
                                   OrderStatus.DELIVERED, OrderStatus.COMPLETED]:
                raise InvalidOrderStatusError("当前订单状态不允许申请售后")
            
            # 检查是否已有进行中的售后
            existing = self.db.query(AfterSales).filter_by(
                order_id=order_id
            ).filter(
                AfterSales.status.in_([AfterSalesStatus.PENDING, AfterSalesStatus.PROCESSING])
            ).first()
            
            if existing:
                raise OrderServiceError("已有进行中的售后申请")
            
            # 计算退款金额
            if refund_amount is None:
                if item_ids:
                    items = self.db.query(OrderItem).filter(
                        OrderItem.id.in_(item_ids),
                        OrderItem.order_id == order_id
                    ).all()
                    refund_amount = sum(item.total_price for item in items)
                else:
                    refund_amount = order.total_amount
            
            after_sales = AfterSales(
                order_id=order_id,
                type=type,
                reason=reason,
                description=description,
                refund_amount=refund_amount,
                status=AfterSalesStatus.PENDING
            )
            self.db.add(after_sales)
            self.db.flush()
            
            # 添加售后商品项
            if item_ids:
                for item_id in item_ids:
                    order_item = self.db.query(OrderItem).filter_by(
                        id=item_id, order_id=order_id
                    ).first()
                    
                    if order_item:
                        after_sales_item = AfterSalesItem(
                            after_sales_id=after_sales.id,
                            order_item_id=item_id,
                            quantity=order_item.quantity
                        )
                        self.db.add(after_sales_item)
            
            # 记录操作日志
            user = self.db.query(User).get(user_id)
            self._log_operation(order.id, user_id, user.username, 'create_after_sales',
                              order.status.value, order.status.value,
                              f"申请售后: {type.value}, 原因: {reason}")
            
            return after_sales
    
    def approve_after_sales(
        self,
        after_sales_id: int,
        operator_id: int,
        approved: bool,
        note: Optional[str] = None
    ) -> AfterSales:
        """审批售后申请"""
        with self.transaction():
            after_sales = self.db.query(AfterSales).get(after_sales_id)
            if not after_sales:
                raise OrderServiceError("售后申请不存在")
            
            if after_sales.status != AfterSalesStatus.PENDING:
                raise OrderServiceError("售后申请状态不正确")
            
            after_sales.approved_by = operator_id
            after_sales.approved_at = datetime.utcnow()
            after_sales.approval_note = note
            
            if approved:
                after_sales.status = AfterSalesStatus.APPROVED
                
                # 如果是退款类型，执行退款
                if after_sales.type in [AfterSalesType.REFUND, AfterSalesType.RETURN_REFUND]:
                    order = self.db.query(Order).get(after_sales.order_id)
                    self._process_refund(order, after_sales.refund_amount, f"售后退款: {after_sales.reason}")
            else:
                after_sales.status = AfterSalesStatus.REJECTED
            
            return after_sales
    
    def get_order_detail(self, order_id: int) -> Optional[Order]:
        """获取订单详情"""
        return self.db.query(Order).options(
            joinedload(Order.items),
            joinedload(Order.shipping_address),
            joinedload(Order.user),
            joinedload(Order.payment_logs),
            joinedload(Order.logistics_logs),
            joinedload(Order.after_sales)
        ).get(order_id)
    
    def get_user_orders(
        self,
        user_id: int,
        status: Optional[OrderStatus] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[Order], int]:
        """获取用户订单列表"""
        query = self.db.query(Order).filter_by(user_id=user_id)
        
        if status:
            query = query.filter_by(status=status)
        
        total = query.count()
        orders = query.order_by(Order.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()
        
        return orders, total
    
    def _get_order_with_lock(self, order_id: int) -> Order:
        """获取订单并加锁"""
        order = self.db.query(Order).filter_by(id=order_id).with_for_update().first()
        if not order:
            raise OrderNotFoundError(f"订单不存在: {order_id}")
        return order
    
    def _calculate_shipping_fee(
        self,
        items: List[Dict],
        address: Address
    ) -> decimal.Decimal:
        """计算运费"""
        total_weight = sum(
            (item['product'].weight or 0) * item['quantity']
            for item in items
        )
        
        # 简化的运费计算逻辑
        if total_weight <= 1:
            return decimal.Decimal('10.00')
        elif total_weight <= 5:
            return decimal.Decimal('15.00')
        else:
            return decimal.Decimal('15.00') + decimal.Decimal('2.00') * (total_weight - 5)
    
    def _calculate_discount(self, subtotal: decimal.Decimal) -> decimal.Decimal:
        """计算折扣"""
        # 满减活动
        if subtotal >= decimal.Decimal('500'):
            return decimal.Decimal('50')
        elif subtotal >= decimal.Decimal('200'):
            return decimal.Decimal('20')
        return decimal.Decimal('0')
    
    def _process_refund(
        self,
        order: Order,
        amount: decimal.Decimal,
        reason: str
    ):
        """处理退款"""
        # 这里应该调用支付网关的退款接口
        # 简化实现，仅记录日志
        payment_log = PaymentLog(
            order_id=order.id,
            transaction_no=f"REFUND_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            payment_method=order.payment_method or "unknown",
            amount=-amount,
            status=PaymentStatus.REFUNDED,
            request_data=f"{{'reason': '{reason}'}}"
        )
        self.db.add(payment_log)
        order.payment_status = PaymentStatus.REFUNDED
    
    def _log_operation(
        self,
        order_id: int,
        operator_id: int,
        operator_name: str,
        operation: str,
        before_status: Optional[str],
        after_status: Optional[str],
        remark: Optional[str] = None
    ):
        """记录订单操作日志"""
        log = OrderOperationLog(
            order_id=order_id,
            operation=operation,
            operator_id=operator_id,
            operator_name=operator_name,
            before_status=before_status,
            after_status=after_status,
            remark=remark
        )
        self.db.add(log)


class InventoryService:
    """库存服务"""
    
    def __init__(self, db_session=None):
        self.db = db_session or db.session
    
    def check_stock(self, product_id: int, quantity: int) -> bool:
        """检查库存"""
        product = self.db.query(Product).get(product_id)
        if not product:
            return False
        available = product.stock_quantity - product.reserved_quantity
        return available >= quantity
    
    def adjust_stock(
        self,
        product_id: int,
        quantity_change: int,
        reason: str,
        operator_id: Optional[int] = None
    ) -> Product:
        """调整库存"""
        product = self.db.query(Product).get(product_id)
        if not product:
            raise OrderServiceError(f"商品不存在: {product_id}")
        
        old_stock = product.stock_quantity
        new_stock = old_stock + quantity_change
        
        if new_stock < 0:
            raise OrderServiceError("库存不能为负数")
        
        product.stock_quantity = new_stock
        
        log = InventoryLog(
            product_id=product_id,
            change_type='adjust',
            quantity_change=quantity_change,
            quantity_before=old_stock,
            quantity_after=new_stock,
            reason=reason,
            operator_id=operator_id
        )
        self.db.add(log)
        self.db.commit()
        
        return product
