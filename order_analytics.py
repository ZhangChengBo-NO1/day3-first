from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from collections import defaultdict
import json
import csv
import io

from flask import current_app
from sqlalchemy import func, case, extract, and_, or_, desc
from sqlalchemy.sql import label

from order_models import (
    db, Order, OrderItem, Product, User, Category,
    OrderStatus, PaymentStatus, AfterSales, AfterSalesStatus
)


class AnalyticsException(Exception):
    pass


class DateRange:
    
    def __init__(self, start_date: datetime, end_date: datetime):
        self.start_date = start_date
        self.end_date = end_date
    
    @classmethod
    def today(cls) -> 'DateRange':
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(today, datetime.utcnow())
    
    @classmethod
    def yesterday(cls) -> 'DateRange':
        yesterday = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return cls(yesterday, yesterday + timedelta(days=1))
    
    @classmethod
    def last_7_days(cls) -> 'DateRange':
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
        return cls(start, datetime.utcnow())
    
    @classmethod
    def last_30_days(cls) -> 'DateRange':
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
        return cls(start, datetime.utcnow())
    
    @classmethod
    def this_month(cls) -> 'DateRange':
        today = datetime.utcnow()
        start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return cls(start, datetime.utcnow())
    
    @classmethod
    def last_month(cls) -> 'DateRange':
        today = datetime.utcnow()
        first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        start = last_of_prev_month.replace(day=1)
        return cls(start, first_of_this_month)
    
    @classmethod
    def this_year(cls) -> 'DateRange':
        today = datetime.utcnow()
        start = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return cls(start, datetime.utcnow())


class SalesAnalytics:
    
    @staticmethod
    def get_sales_summary(date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.today()
        
        query = Order.query.filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        )
        
        total_orders = query.count()
        
        total_sales = query.with_entities(
            func.sum(Order.total_amount)
        ).scalar() or Decimal('0')
        
        total_items = db.session.query(
            func.sum(OrderItem.quantity)
        ).join(Order).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).scalar() or 0
        
        paid_orders = query.filter(
            Order.payment_status == PaymentStatus.SUCCESS
        ).count()
        
        avg_order_value = total_sales / total_orders if total_orders > 0 else Decimal('0')
        
        return {
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'total_orders': total_orders,
            'total_sales': float(total_sales),
            'total_items': total_items,
            'paid_orders': paid_orders,
            'average_order_value': float(avg_order_value),
            'conversion_rate': round(paid_orders / total_orders * 100, 2) if total_orders > 0 else 0
        }
    
    @staticmethod
    def get_sales_by_period(date_range: DateRange = None, period: str = 'day') -> List[Dict]:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        if period == 'hour':
            date_format = func.strftime('%Y-%m-%d %H:00', Order.created_at)
        elif period == 'day':
            date_format = func.strftime('%Y-%m-%d', Order.created_at)
        elif period == 'week':
            date_format = func.strftime('%Y-%W', Order.created_at)
        elif period == 'month':
            date_format = func.strftime('%Y-%m', Order.created_at)
        else:
            date_format = func.strftime('%Y-%m-%d', Order.created_at)
        
        results = db.session.query(
            date_format.label('period'),
            func.count(Order.id).label('order_count'),
            func.sum(Order.total_amount).label('total_sales'),
            func.sum(OrderItem.quantity).label('total_items')
        ).join(OrderItem).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by('period').order_by('period').all()
        
        return [{
            'period': r.period,
            'order_count': r.order_count,
            'total_sales': float(r.total_sales or 0),
            'total_items': r.total_items or 0
        } for r in results]
    
    @staticmethod
    def get_sales_comparison(days: int = 7) -> Dict:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        current_start = today - timedelta(days=days-1)
        previous_start = today - timedelta(days=days*2)
        previous_end = today - timedelta(days=days)
        
        current_range = DateRange(current_start, datetime.utcnow())
        previous_range = DateRange(previous_start, previous_end)
        
        current_summary = SalesAnalytics.get_sales_summary(current_range)
        previous_summary = SalesAnalytics.get_sales_summary(previous_range)
        
        def calc_change(current, previous):
            if previous == 0:
                return 100 if current > 0 else 0
            return round((current - previous) / previous * 100, 2)
        
        return {
            'current_period': current_summary,
            'previous_period': previous_summary,
            'changes': {
                'orders_change': calc_change(
                    current_summary['total_orders'],
                    previous_summary['total_orders']
                ),
                'sales_change': calc_change(
                    current_summary['total_sales'],
                    previous_summary['total_sales']
                ),
                'aov_change': calc_change(
                    current_summary['average_order_value'],
                    previous_summary['average_order_value']
                )
            }
        }


class ProductAnalytics:
    
    @staticmethod
    def get_top_products(date_range: DateRange = None, limit: int = 10, 
                         sort_by: str = 'sales') -> List[Dict]:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        query = db.session.query(
            Product.id,
            Product.sku,
            Product.name,
            Product.price,
            func.sum(OrderItem.quantity).label('total_quantity'),
            func.sum(OrderItem.subtotal).label('total_revenue'),
            func.count(func.distinct(Order.id)).label('order_count')
        ).join(OrderItem).join(Order).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by(Product.id)
        
        if sort_by == 'revenue':
            query = query.order_by(desc('total_revenue'))
        else:
            query = query.order_by(desc('total_quantity'))
        
        results = query.limit(limit).all()
        
        return [{
            'product_id': r.id,
            'sku': r.sku,
            'name': r.name,
            'price': float(r.price),
            'total_quantity': r.total_quantity,
            'total_revenue': float(r.total_revenue or 0),
            'order_count': r.order_count
        } for r in results]
    
    @staticmethod
    def get_category_sales(date_range: DateRange = None) -> List[Dict]:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        results = db.session.query(
            Category.id,
            Category.name,
            func.sum(OrderItem.quantity).label('total_quantity'),
            func.sum(OrderItem.subtotal).label('total_revenue'),
            func.count(func.distinct(Order.id)).label('order_count')
        ).join(Product).join(OrderItem).join(Order).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by(Category.id).order_by(desc('total_revenue')).all()
        
        total_revenue = sum(float(r.total_revenue or 0) for r in results)
        
        return [{
            'category_id': r.id,
            'category_name': r.name,
            'total_quantity': r.total_quantity,
            'total_revenue': float(r.total_revenue or 0),
            'order_count': r.order_count,
            'percentage': round(float(r.total_revenue or 0) / total_revenue * 100, 2) if total_revenue > 0 else 0
        } for r in results]
    
    @staticmethod
    def get_product_performance(product_id: int, date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        product = Product.query.get(product_id)
        if not product:
            raise AnalyticsException('商品不存在')
        
        stats = db.session.query(
            func.sum(OrderItem.quantity).label('total_quantity'),
            func.sum(OrderItem.subtotal).label('total_revenue'),
            func.count(func.distinct(Order.id)).label('order_count'),
            func.avg(Order.total_amount).label('avg_order_value')
        ).join(Order).filter(
            OrderItem.product_id == product_id,
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).first()
        
        daily_sales = db.session.query(
            func.strftime('%Y-%m-%d', Order.created_at).label('date'),
            func.sum(OrderItem.quantity).label('quantity'),
            func.sum(OrderItem.subtotal).label('revenue')
        ).join(OrderItem).filter(
            OrderItem.product_id == product_id,
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by('date').order_by('date').all()
        
        return {
            'product': product.to_dict(),
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'total_quantity': stats.total_quantity or 0,
            'total_revenue': float(stats.total_revenue or 0),
            'order_count': stats.order_count or 0,
            'average_order_value': float(stats.avg_order_value or 0),
            'daily_sales': [{
                'date': d.date,
                'quantity': d.quantity,
                'revenue': float(d.revenue or 0)
            } for d in daily_sales]
        }
    
    @staticmethod
    def get_inventory_alert() -> List[Dict]:
        low_stock = Product.query.filter(
            Product.is_active == True,
            Product.inventory <= Product.low_stock_threshold,
            Product.inventory > 0
        ).all()
        
        out_of_stock = Product.query.filter(
            Product.is_active == True,
            Product.inventory <= 0
        ).all()
        
        return {
            'low_stock': [{
                'product_id': p.id,
                'sku': p.sku,
                'name': p.name,
                'inventory': p.inventory,
                'threshold': p.low_stock_threshold
            } for p in low_stock],
            'out_of_stock': [{
                'product_id': p.id,
                'sku': p.sku,
                'name': p.name
            } for p in out_of_stock],
            'low_stock_count': len(low_stock),
            'out_of_stock_count': len(out_of_stock)
        }


class CustomerAnalytics:
    
    @staticmethod
    def get_customer_summary(date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        new_customers = User.query.filter(
            User.created_at >= date_range.start_date,
            User.created_at <= date_range.end_date
        ).count()
        
        active_customers = db.session.query(
            func.count(func.distinct(Order.user_id))
        ).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).scalar() or 0
        
        repeat_customers = db.session.query(
            func.count(func.distinct(Order.user_id))
        ).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by(Order.user_id).having(func.count(Order.id) > 1).count()
        
        total_customers = User.query.count()
        
        return {
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'new_customers': new_customers,
            'active_customers': active_customers,
            'repeat_customers': repeat_customers,
            'total_customers': total_customers,
            'repeat_rate': round(repeat_customers / active_customers * 100, 2) if active_customers > 0 else 0
        }
    
    @staticmethod
    def get_top_customers(date_range: DateRange = None, limit: int = 10) -> List[Dict]:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        results = db.session.query(
            User.id,
            User.username,
            User.email,
            func.count(Order.id).label('order_count'),
            func.sum(Order.total_amount).label('total_spent'),
            func.avg(Order.total_amount).label('avg_order_value')
        ).join(Order).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status != OrderStatus.CANCELLED
        ).group_by(User.id).order_by(desc('total_spent')).limit(limit).all()
        
        return [{
            'user_id': r.id,
            'username': r.username,
            'email': r.email,
            'order_count': r.order_count,
            'total_spent': float(r.total_spent or 0),
            'avg_order_value': float(r.avg_order_value or 0)
        } for r in results]
    
    @staticmethod
    def get_customer_segments() -> Dict:
        total_customers = User.query.count()
        
        segments = db.session.query(
            case([
                (func.count(Order.id) == 0, 'new'),
                (func.count(Order.id) <= 3, 'occasional'),
                (func.count(Order.id) <= 10, 'regular'),
                (func.count(Order.id) > 10, 'vip')
            ]).label('segment'),
            func.count(func.distinct(User.id)).label('count')
        ).outerjoin(Order).group_by('segment').all()
        
        segment_data = {s.segment: s.count for s in segments}
        
        return {
            'total_customers': total_customers,
            'segments': {
                'new': {
                    'count': segment_data.get('new', 0),
                    'percentage': round(segment_data.get('new', 0) / total_customers * 100, 2) if total_customers > 0 else 0,
                    'description': '未下单客户'
                },
                'occasional': {
                    'count': segment_data.get('occasional', 0),
                    'percentage': round(segment_data.get('occasional', 0) / total_customers * 100, 2) if total_customers > 0 else 0,
                    'description': '1-3单客户'
                },
                'regular': {
                    'count': segment_data.get('regular', 0),
                    'percentage': round(segment_data.get('regular', 0) / total_customers * 100, 2) if total_customers > 0 else 0,
                    'description': '4-10单客户'
                },
                'vip': {
                    'count': segment_data.get('vip', 0),
                    'percentage': round(segment_data.get('vip', 0) / total_customers * 100, 2) if total_customers > 0 else 0,
                    'description': '10单以上客户'
                }
            }
        }


class OrderAnalytics:
    
    @staticmethod
    def get_order_status_distribution(date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        results = db.session.query(
            Order.status,
            func.count(Order.id).label('count'),
            func.sum(Order.total_amount).label('total_amount')
        ).filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date
        ).group_by(Order.status).all()
        
        total_orders = sum(r.count for r in results)
        
        return {
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'total_orders': total_orders,
            'distribution': [{
                'status': r.status.value,
                'count': r.count,
                'total_amount': float(r.total_amount or 0),
                'percentage': round(r.count / total_orders * 100, 2) if total_orders > 0 else 0
            } for r in results]
        }
    
    @staticmethod
    def get_fulfillment_metrics(date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        orders = Order.query.filter(
            Order.created_at >= date_range.start_date,
            Order.created_at <= date_range.end_date,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.SHIPPED])
        ).all()
        
        processing_times = []
        shipping_times = []
        
        for order in orders:
            if order.confirmed_at and order.shipping_time:
                processing_times.append((order.shipping_time - order.confirmed_at).total_seconds() / 3600)
            if order.shipping_time and order.delivery_time:
                shipping_times.append((order.delivery_time - order.shipping_time).total_seconds() / 3600)
        
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        avg_shipping_time = sum(shipping_times) / len(shipping_times) if shipping_times else 0
        
        delivered_count = len([o for o in orders if o.status == OrderStatus.DELIVERED])
        
        return {
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'total_fulfilled': len(orders),
            'delivered_count': delivered_count,
            'shipped_count': len(orders) - delivered_count,
            'avg_processing_hours': round(avg_processing_time, 2),
            'avg_shipping_hours': round(avg_shipping_time, 2),
            'avg_total_hours': round(avg_processing_time + avg_shipping_time, 2)
        }
    
    @staticmethod
    def get_after_sales_stats(date_range: DateRange = None) -> Dict:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        total_requests = AfterSales.query.filter(
            AfterSales.created_at >= date_range.start_date,
            AfterSales.created_at <= date_range.end_date
        ).count()
        
        by_status = db.session.query(
            AfterSales.status,
            func.count(AfterSales.id).label('count')
        ).filter(
            AfterSales.created_at >= date_range.start_date,
            AfterSales.created_at <= date_range.end_date
        ).group_by(AfterSales.status).all()
        
        by_type = db.session.query(
            AfterSales.type,
            func.count(AfterSales.id).label('count'),
            func.sum(AfterSales.refund_amount).label('refund_amount')
        ).filter(
            AfterSales.created_at >= date_range.start_date,
            AfterSales.created_at <= date_range.end_date
        ).group_by(AfterSales.type).all()
        
        total_refund = db.session.query(
            func.sum(AfterSales.refund_amount)
        ).filter(
            AfterSales.created_at >= date_range.start_date,
            AfterSales.created_at <= date_range.end_date,
            AfterSales.status == AfterSalesStatus.COMPLETED
        ).scalar() or Decimal('0')
        
        return {
            'period': {
                'start': date_range.start_date.isoformat(),
                'end': date_range.end_date.isoformat()
            },
            'total_requests': total_requests,
            'total_refund': float(total_refund),
            'by_status': [{
                'status': s.status.value,
                'count': s.count
            } for s in by_status],
            'by_type': [{
                'type': t.type.value,
                'count': t.count,
                'refund_amount': float(t.refund_amount or 0)
            } for t in by_type]
        }


class AnalyticsExporter:
    
    @staticmethod
    def export_sales_report(date_range: DateRange = None, format: str = 'csv') -> Any:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        sales_data = SalesAnalytics.get_sales_by_period(date_range, 'day')
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['日期', '订单数', '销售额', '商品数量'])
            for row in sales_data:
                writer.writerow([
                    row['period'],
                    row['order_count'],
                    row['total_sales'],
                    row['total_items']
                ])
            
            return output.getvalue()
        
        elif format == 'json':
            return json.dumps(sales_data, ensure_ascii=False, indent=2)
        
        return sales_data
    
    @staticmethod
    def export_product_report(date_range: DateRange = None, format: str = 'csv') -> Any:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        products_data = ProductAnalytics.get_top_products(date_range, limit=100)
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['商品ID', 'SKU', '商品名称', '单价', '销售数量', '销售额', '订单数'])
            for row in products_data:
                writer.writerow([
                    row['product_id'],
                    row['sku'],
                    row['name'],
                    row['price'],
                    row['total_quantity'],
                    row['total_revenue'],
                    row['order_count']
                ])
            
            return output.getvalue()
        
        elif format == 'json':
            return json.dumps(products_data, ensure_ascii=False, indent=2)
        
        return products_data
    
    @staticmethod
    def export_customer_report(date_range: DateRange = None, format: str = 'csv') -> Any:
        if not date_range:
            date_range = DateRange.last_30_days()
        
        customers_data = CustomerAnalytics.get_top_customers(date_range, limit=100)
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['客户ID', '用户名', '邮箱', '订单数', '消费总额', '平均订单金额'])
            for row in customers_data:
                writer.writerow([
                    row['user_id'],
                    row['username'],
                    row['email'],
                    row['order_count'],
                    row['total_spent'],
                    row['avg_order_value']
                ])
            
            return output.getvalue()
        
        elif format == 'json':
            return json.dumps(customers_data, ensure_ascii=False, indent=2)
        
        return customers_data


class DashboardService:
    
    @staticmethod
    def get_dashboard_summary() -> Dict:
        today_summary = SalesAnalytics.get_sales_summary(DateRange.today())
        yesterday_summary = SalesAnalytics.get_sales_summary(DateRange.yesterday())
        
        today_orders = today_summary['total_orders']
        today_sales = today_summary['total_sales']
        yesterday_orders = yesterday_summary['total_orders']
        yesterday_sales = yesterday_summary['total_sales']
        
        order_change = round((today_orders - yesterday_orders) / yesterday_orders * 100, 2) if yesterday_orders > 0 else 0
        sales_change = round((today_sales - yesterday_sales) / yesterday_sales * 100, 2) if yesterday_sales > 0 else 0
        
        pending_orders = Order.query.filter_by(status=OrderStatus.PENDING).count()
        processing_orders = Order.query.filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.CONFIRMED, OrderStatus.PROCESSING])
        ).count()
        shipped_orders = Order.query.filter_by(status=OrderStatus.SHIPPED).count()
        
        pending_after_sales = AfterSales.query.filter_by(status=AfterSalesStatus.PENDING).count()
        
        inventory_alert = ProductAnalytics.get_inventory_alert()
        
        top_products = ProductAnalytics.get_top_products(DateRange.today(), limit=5)
        
        recent_orders = Order.query.order_by(desc(Order.created_at)).limit(5).all()
        
        return {
            'today': {
                'orders': today_orders,
                'sales': today_sales,
                'order_change': order_change,
                'sales_change': sales_change
            },
            'order_status': {
                'pending': pending_orders,
                'processing': processing_orders,
                'shipped': shipped_orders
            },
            'after_sales': {
                'pending': pending_after_sales
            },
            'inventory': {
                'low_stock_count': inventory_alert['low_stock_count'],
                'out_of_stock_count': inventory_alert['out_of_stock_count']
            },
            'top_products': top_products,
            'recent_orders': [o.to_dict() for o in recent_orders]
        }
