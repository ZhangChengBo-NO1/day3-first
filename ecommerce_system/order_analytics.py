import decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict

import pandas as pd
import numpy as np
from sqlalchemy import func, and_, or_, extract
from sqlalchemy.orm import Session

from order_models import (
    Order, OrderItem, Product, Category, User,
    OrderStatus, PaymentStatus, db
)


@dataclass
class SalesSummary:
    """销售汇总数据"""
    total_orders: int
    total_amount: decimal.Decimal
    total_items: int
    avg_order_value: decimal.Decimal
    paid_orders: int
    paid_amount: decimal.Decimal
    cancelled_orders: int
    cancelled_amount: decimal.Decimal
    refund_amount: decimal.Decimal


@dataclass
class ProductSales:
    """产品销售数据"""
    product_id: int
    product_name: str
    sku: str
    category_name: str
    quantity_sold: int
    revenue: decimal.Decimal
    orders_count: int
    avg_price: decimal.Decimal


@dataclass
class CategorySales:
    """分类销售数据"""
    category_id: int
    category_name: str
    quantity_sold: int
    revenue: decimal.Decimal
    orders_count: int
    product_count: int
    avg_order_value: decimal.Decimal


@dataclass
class TimeSeriesData:
    """时间序列数据"""
    timestamp: datetime
    orders_count: int
    revenue: decimal.Decimal
    items_count: int


@dataclass
class CustomerAnalytics:
    """客户分析数据"""
    user_id: int
    username: str
    total_orders: int
    total_spent: decimal.Decimal
    avg_order_value: decimal.Decimal
    first_order_date: datetime
    last_order_date: datetime
    favorite_category: Optional[str]


class OrderAnalytics:
    """订单数据分析服务"""
    
    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session or db.session
    
    def get_sales_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> SalesSummary:
        """获取销售汇总"""
        query = self.db.query(Order)
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        
        # 总订单统计
        total_stats = query.with_entities(
            func.count(Order.id).label('total_orders'),
            func.coalesce(func.sum(Order.total_amount), 0).label('total_amount'),
            func.coalesce(func.sum(Order.total_amount), 0) / func.nullif(func.count(Order.id), 0)
                .label('avg_order_value')
        ).first()
        
        # 总商品数量
        items_query = self.db.query(OrderItem).join(Order)
        if start_date:
            items_query = items_query.filter(Order.created_at >= start_date)
        if end_date:
            items_query = items_query.filter(Order.created_at < end_date)
        
        total_items = items_query.with_entities(
            func.coalesce(func.sum(OrderItem.quantity), 0)
        ).scalar() or 0
        
        # 已支付订单
        paid_query = query.filter(Order.payment_status == PaymentStatus.SUCCESS)
        paid_stats = paid_query.with_entities(
            func.count(Order.id).label('count'),
            func.coalesce(func.sum(Order.paid_amount), 0).label('amount')
        ).first()
        
        # 已取消订单
        cancelled_query = query.filter(Order.status == OrderStatus.CANCELLED)
        cancelled_stats = cancelled_query.with_entities(
            func.count(Order.id).label('count'),
            func.coalesce(func.sum(Order.total_amount), 0).label('amount')
        ).first()
        
        # 退款金额
        refund_query = query.filter(Order.payment_status == PaymentStatus.REFUNDED)
        refund_amount = refund_query.with_entities(
            func.coalesce(func.sum(Order.paid_amount), 0)
        ).scalar() or 0
        
        return SalesSummary(
            total_orders=total_stats.total_orders or 0,
            total_amount=total_stats.total_amount or decimal.Decimal('0'),
            total_items=total_items,
            avg_order_value=total_stats.avg_order_value or decimal.Decimal('0'),
            paid_orders=paid_stats.count or 0,
            paid_amount=paid_stats.amount or decimal.Decimal('0'),
            cancelled_orders=cancelled_stats.count or 0,
            cancelled_amount=cancelled_stats.amount or decimal.Decimal('0'),
            refund_amount=refund_amount
        )
    
    def get_sales_by_time(
        self,
        granularity: str = 'day',
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[TimeSeriesData]:
        """
        按时间维度分析销售
        
        Args:
            granularity: 时间粒度 ('hour', 'day', 'week', 'month')
            start_date: 开始时间
            end_date: 结束时间
        """
        query = self.db.query(Order).filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED, 
                            OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        )
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        
        # 根据粒度选择时间格式
        if granularity == 'hour':
            time_format = func.date_format(Order.created_at, '%Y-%m-%d %H:00:00')
        elif granularity == 'day':
            time_format = func.date(Order.created_at)
        elif granularity == 'week':
            time_format = func.date_format(Order.created_at, '%Y-%u')
        elif granularity == 'month':
            time_format = func.date_format(Order.created_at, '%Y-%m')
        else:
            time_format = func.date(Order.created_at)
        
        # 子查询统计订单项数量
        items_subquery = self.db.query(
            OrderItem.order_id,
            func.sum(OrderItem.quantity).label('items_count')
        ).group_by(OrderItem.order_id).subquery()
        
        results = query.outerjoin(
            items_subquery, Order.id == items_subquery.c.order_id
        ).with_entities(
            time_format.label('time_period'),
            func.count(Order.id).label('orders_count'),
            func.coalesce(func.sum(Order.total_amount), 0).label('revenue'),
            func.coalesce(func.sum(items_subquery.c.items_count), 0).label('items_count')
        ).group_by('time_period').order_by('time_period').all()
        
        return [
            TimeSeriesData(
                timestamp=r.time_period if isinstance(r.time_period, datetime) 
                         else datetime.strptime(str(r.time_period), '%Y-%m-%d'),
                orders_count=r.orders_count,
                revenue=r.revenue,
                items_count=r.items_count
            )
            for r in results
        ]
    
    def get_product_sales(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category_id: Optional[int] = None,
        limit: int = 100
    ) -> List[ProductSales]:
        """获取产品销售排行"""
        query = self.db.query(
            OrderItem.product_id,
            OrderItem.product_name,
            OrderItem.product_sku,
            Category.name.label('category_name'),
            func.sum(OrderItem.quantity).label('quantity_sold'),
            func.sum(OrderItem.total_price).label('revenue'),
            func.count(func.distinct(OrderItem.order_id)).label('orders_count')
        ).join(
            Order, OrderItem.order_id == Order.id
        ).outerjoin(
            Product, OrderItem.product_id == Product.id
        ).outerjoin(
            Category, Product.category_id == Category.id
        ).filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED,
                            OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        )
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        results = query.group_by(
            OrderItem.product_id,
            OrderItem.product_name,
            OrderItem.product_sku,
            Category.name
        ).order_by(
            func.sum(OrderItem.total_price).desc()
        ).limit(limit).all()
        
        return [
            ProductSales(
                product_id=r.product_id,
                product_name=r.product_name,
                sku=r.product_sku,
                category_name=r.category_name or '未分类',
                quantity_sold=r.quantity_sold or 0,
                revenue=r.revenue or decimal.Decimal('0'),
                orders_count=r.orders_count or 0,
                avg_price=(r.revenue / r.quantity_sold) if r.quantity_sold 
                         else decimal.Decimal('0')
            )
            for r in results
        ]
    
    def get_category_sales(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[CategorySales]:
        """获取分类销售统计"""
        query = self.db.query(
            Category.id.label('category_id'),
            Category.name.label('category_name'),
            func.sum(OrderItem.quantity).label('quantity_sold'),
            func.sum(OrderItem.total_price).label('revenue'),
            func.count(func.distinct(OrderItem.order_id)).label('orders_count'),
            func.count(func.distinct(OrderItem.product_id)).label('product_count')
        ).join(
            Product, Category.id == Product.category_id
        ).join(
            OrderItem, Product.id == OrderItem.product_id
        ).join(
            Order, OrderItem.order_id == Order.id
        ).filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED,
                            OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        )
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        
        results = query.group_by(
            Category.id, Category.name
        ).order_by(
            func.sum(OrderItem.total_price).desc()
        ).all()
        
        return [
            CategorySales(
                category_id=r.category_id,
                category_name=r.category_name,
                quantity_sold=r.quantity_sold or 0,
                revenue=r.revenue or decimal.Decimal('0'),
                orders_count=r.orders_count or 0,
                product_count=r.product_count or 0,
                avg_order_value=(r.revenue / r.orders_count) if r.orders_count 
                               else decimal.Decimal('0')
            )
            for r in results
        ]
    
    def get_customer_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        min_orders: int = 1,
        limit: int = 100
    ) -> List[CustomerAnalytics]:
        """获取客户分析数据"""
        # 子查询：获取每个用户最喜欢的分类
        favorite_category_subquery = self.db.query(
            Order.user_id,
            Category.name.label('category_name'),
            func.row_number().over(
                partition_by=Order.user_id,
                order_by=func.sum(OrderItem.quantity).desc()
            ).label('rn')
        ).join(
            OrderItem, Order.id == OrderItem.order_id
        ).join(
            Product, OrderItem.product_id == Product.id
        ).join(
            Category, Product.category_id == Category.id
        ).filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED,
                            OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        ).group_by(
            Order.user_id, Category.name
        ).subquery()
        
        favorite_category = self.db.query(
            favorite_category_subquery.c.user_id,
            favorite_category_subquery.c.category_name
        ).filter(
            favorite_category_subquery.c.rn == 1
        ).subquery()
        
        # 主查询
        query = self.db.query(
            User.id.label('user_id'),
            User.username,
            func.count(Order.id).label('total_orders'),
            func.coalesce(func.sum(Order.total_amount), 0).label('total_spent'),
            func.min(Order.created_at).label('first_order_date'),
            func.max(Order.created_at).label('last_order_date'),
            favorite_category.c.category_name.label('favorite_category')
        ).join(
            Order, User.id == Order.user_id
        ).outerjoin(
            favorite_category, User.id == favorite_category.c.user_id
        ).filter(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED,
                            OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        )
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        
        results = query.group_by(
            User.id, User.username, favorite_category.c.category_name
        ).having(
            func.count(Order.id) >= min_orders
        ).order_by(
            func.sum(Order.total_amount).desc()
        ).limit(limit).all()
        
        return [
            CustomerAnalytics(
                user_id=r.user_id,
                username=r.username,
                total_orders=r.total_orders,
                total_spent=r.total_spent,
                avg_order_value=(r.total_spent / r.total_orders) if r.total_orders 
                               else decimal.Decimal('0'),
                first_order_date=r.first_order_date,
                last_order_date=r.last_order_date,
                favorite_category=r.favorite_category
            )
            for r in results
        ]
    
    def get_order_conversion_funnel(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """获取订单转化漏斗"""
        query = self.db.query(Order)
        
        if start_date:
            query = query.filter(Order.created_at >= start_date)
        if end_date:
            query = query.filter(Order.created_at < end_date)
        
        # 各状态订单数量
        status_counts = query.with_entities(
            Order.status,
            func.count(Order.id).label('count')
        ).group_by(Order.status).all()
        
        status_dict = {s.status.value: s.count for s in status_counts}
        
        total = sum(status_dict.values())
        paid = status_dict.get(OrderStatus.PAID.value, 0) + \
               status_dict.get(OrderStatus.SHIPPED.value, 0) + \
               status_dict.get(OrderStatus.DELIVERED.value, 0) + \
               status_dict.get(OrderStatus.COMPLETED.value, 0)
        completed = status_dict.get(OrderStatus.COMPLETED.value, 0)
        cancelled = status_dict.get(OrderStatus.CANCELLED.value, 0)
        
        return {
            'total_created': total,
            'paid': paid,
            'completed': completed,
            'cancelled': cancelled,
            'conversion_rates': {
                'created_to_paid': (paid / total * 100) if total else 0,
                'paid_to_completed': (completed / paid * 100) if paid else 0,
                'overall': (completed / total * 100) if total else 0
            },
            'cancellation_rate': (cancelled / total * 100) if total else 0
        }
    
    def get_sales_forecast(
        self,
        days_ahead: int = 7,
        historical_days: int = 30
    ) -> List[Dict[str, Any]]:
        """销售预测（基于历史数据）"""
        # 获取历史数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=historical_days)
        
        historical_data = self.get_sales_by_time(
            granularity='day',
            start_date=start_date,
            end_date=end_date
        )
        
        if len(historical_data) < 7:
            return []
        
        # 转换为pandas DataFrame
        df = pd.DataFrame([
            {
                'date': d.timestamp,
                'revenue': float(d.revenue),
                'orders': d.orders_count
            }
            for d in historical_data
        ])
        
        # 计算7日移动平均
        df['revenue_ma'] = df['revenue'].rolling(window=7).mean()
        df['orders_ma'] = df['orders'].rolling(window=7).mean()
        
        # 计算趋势
        revenue_trend = np.polyfit(range(len(df)), df['revenue'].fillna(df['revenue'].mean()), 1)[0]
        orders_trend = np.polyfit(range(len(df)), df['orders'].fillna(df['orders'].mean()), 1)[0]
        
        # 预测未来
        last_revenue = df['revenue_ma'].iloc[-1] if not pd.isna(df['revenue_ma'].iloc[-1]) else df['revenue'].mean()
        last_orders = df['orders_ma'].iloc[-1] if not pd.isna(df['orders_ma'].iloc[-1]) else df['orders'].mean()
        
        forecast = []
        for i in range(1, days_ahead + 1):
            forecast_date = end_date + timedelta(days=i)
            predicted_revenue = max(0, last_revenue + revenue_trend * i)
            predicted_orders = max(0, int(last_orders + orders_trend * i))
            
            forecast.append({
                'date': forecast_date.strftime('%Y-%m-%d'),
                'predicted_revenue': round(predicted_revenue, 2),
                'predicted_orders': predicted_orders,
                'confidence': max(0, 1 - i * 0.1)  # 置信度随时间递减
            })
        
        return forecast
    
    def export_sales_report(
        self,
        start_date: datetime,
        end_date: datetime,
        report_type: str = 'summary'
    ) -> Dict[str, Any]:
        """导出销售报告"""
        report = {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'generated_at': datetime.now().isoformat()
        }
        
        if report_type in ['summary', 'full']:
            report['summary'] = self.get_sales_summary(start_date, end_date)
        
        if report_type in ['daily', 'full']:
            report['daily_sales'] = self.get_sales_by_time(
                granularity='day',
                start_date=start_date,
                end_date=end_date
            )
        
        if report_type in ['products', 'full']:
            report['top_products'] = self.get_product_sales(
                start_date=start_date,
                end_date=end_date,
                limit=50
            )
        
        if report_type in ['categories', 'full']:
            report['category_sales'] = self.get_category_sales(
                start_date=start_date,
                end_date=end_date
            )
        
        if report_type == 'full':
            report['conversion_funnel'] = self.get_order_conversion_funnel(
                start_date=start_date,
                end_date=end_date
            )
            report['top_customers'] = self.get_customer_analytics(
                start_date=start_date,
                end_date=end_date,
                limit=20
            )
        
        return report
    
    def get_realtime_dashboard(self) -> Dict[str, Any]:
        """获取实时仪表盘数据"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        this_week = today - timedelta(days=today.weekday())
        this_month = today.replace(day=1)
        
        return {
            'today': {
                'orders': self.get_sales_summary(today, today + timedelta(days=1)),
                'hourly_trend': self.get_sales_by_time(
                    granularity='hour',
                    start_date=today,
                    end_date=today + timedelta(days=1)
                )
            },
            'yesterday': self.get_sales_summary(
                yesterday, yesterday + timedelta(days=1)
            ),
            'this_week': self.get_sales_summary(this_week, today + timedelta(days=1)),
            'this_month': self.get_sales_summary(this_month, today + timedelta(days=1)),
            'top_products_today': self.get_product_sales(
                start_date=today,
                end_date=today + timedelta(days=1),
                limit=10
            ),
            'pending_orders': self.db.query(Order).filter(
                Order.status.in_([OrderStatus.PENDING_PAYMENT, OrderStatus.PAID])
            ).count(),
            'forecast': self.get_sales_forecast(days_ahead=3)
        }


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, analytics: OrderAnalytics):
        self.analytics = analytics
    
    def generate_csv_report(
        self,
        start_date: datetime,
        end_date: datetime,
        report_type: str = 'orders'
    ) -> str:
        """生成CSV报告"""
        if report_type == 'orders':
            data = self.analytics.get_sales_by_time(
                granularity='day',
                start_date=start_date,
                end_date=end_date
            )
            df = pd.DataFrame([
                {
                    'Date': d.timestamp.strftime('%Y-%m-%d'),
                    'Orders': d.orders_count,
                    'Revenue': float(d.revenue),
                    'Items': d.items_count
                }
                for d in data
            ])
        
        elif report_type == 'products':
            data = self.analytics.get_product_sales(
                start_date=start_date,
                end_date=end_date
            )
            df = pd.DataFrame([
                {
                    'Product ID': p.product_id,
                    'Product Name': p.product_name,
                    'SKU': p.sku,
                    'Category': p.category_name,
                    'Quantity Sold': p.quantity_sold,
                    'Revenue': float(p.revenue),
                    'Orders Count': p.orders_count
                }
                for p in data
            ])
        
        else:
            raise ValueError(f"Unknown report type: {report_type}")
        
        return df.to_csv(index=False)
    
    def generate_excel_report(
        self,
        start_date: datetime,
        end_date: datetime,
        file_path: str
    ):
        """生成Excel多sheet报告"""
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # 销售汇总
            summary = self.analytics.get_sales_summary(start_date, end_date)
            summary_df = pd.DataFrame([{
                'Metric': 'Total Orders',
                'Value': summary.total_orders
            }, {
                'Metric': 'Total Revenue',
                'Value': float(summary.total_amount)
            }, {
                'Metric': 'Average Order Value',
                'Value': float(summary.avg_order_value)
            }, {
                'Metric': 'Paid Orders',
                'Value': summary.paid_orders
            }, {
                'Metric': 'Paid Amount',
                'Value': float(summary.paid_amount)
            }])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # 每日销售
            daily = self.analytics.get_sales_by_time(
                granularity='day',
                start_date=start_date,
                end_date=end_date
            )
            daily_df = pd.DataFrame([
                {
                    'Date': d.timestamp.strftime('%Y-%m-%d'),
                    'Orders': d.orders_count,
                    'Revenue': float(d.revenue),
                    'Items': d.items_count
                }
                for d in daily
            ])
            daily_df.to_excel(writer, sheet_name='Daily Sales', index=False)
            
            # 产品销售
            products = self.analytics.get_product_sales(
                start_date=start_date,
                end_date=end_date,
                limit=100
            )
            products_df = pd.DataFrame([
                {
                    'Product ID': p.product_id,
                    'Product Name': p.product_name,
                    'SKU': p.sku,
                    'Category': p.category_name,
                    'Quantity': p.quantity_sold,
                    'Revenue': float(p.revenue)
                }
                for p in products
            ])
            products_df.to_excel(writer, sheet_name='Products', index=False)
