# 电商订单履约与数据分析系统

## 系统概述

这是一个全功能的电商订单履约与数据分析系统，基于 Flask 框架开发，支持订单全生命周期管理、库存管理、物流对接、售后处理和多维度数据分析。

## 核心功能

### 1. 订单管理
- 订单创建 / 取消
- 库存扣减与预留
- 支付验证
- 订单状态流转（待支付 → 已支付 → 已发货 → 已送达 → 已完成）

### 2. 物流对接
- 多物流公司支持（顺丰、圆通、中通等）
- 物流订单创建
- 物流轨迹查询
- 发货管理

### 3. 售后处理
- 退款申请
- 退货退款
- 换货
- 维修

### 4. 数据分析
- 销售汇总统计
- 时间维度销售分析
- 产品销售排行
- 分类销售统计
- 客户分析
- 订单转化漏斗
- 销售预测

### 5. 权限控制
- JWT Token 认证
- 角色权限管理（客户、商家、物流、管理员）
- 细粒度权限控制
- 审计日志

## 项目结构

```
ecommerce_system/
├── config.py              # 配置文件
├── order_models.py        # 数据模型定义
├── order_service.py       # 订单核心业务逻辑
├── logistics_client.py    # 物流对接客户端
├── order_analytics.py     # 数据分析模块
├── web_interface.py       # Web API 接口
├── auth.py                # 权限控制模块
├── init_db.py             # 数据库初始化脚本
├── run.py                 # 应用启动脚本
├── requirements.txt       # 依赖包列表
└── .env.example           # 环境变量示例
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置数据库连接等信息
```

### 3. 初始化数据库

```bash
python init_db.py
```

### 4. 启动应用

```bash
python run.py
```

应用将在 http://localhost:5000 启动

## API 接口文档

### 认证相关

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /api/auth/register | 用户注册 |
| POST | /api/auth/login | 用户登录 |
| POST | /api/auth/refresh | 刷新Token |
| POST | /api/auth/change-password | 修改密码 |

### 订单相关

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /api/orders | 创建订单 |
| GET | /api/orders | 获取订单列表 |
| GET | /api/orders/{id} | 获取订单详情 |
| POST | /api/orders/{id}/cancel | 取消订单 |
| POST | /api/orders/{id}/pay | 支付订单 |
| POST | /api/orders/{id}/ship | 订单发货 |
| POST | /api/orders/{id}/confirm-delivery | 确认收货 |

### 售后相关

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /api/orders/{id}/after-sales | 申请售后 |
| POST | /api/after-sales/{id}/approve | 审批售后 |

### 物流相关

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/logistics/tracking/{no} | 查询物流轨迹 |

### 数据分析

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/analytics/summary | 销售汇总 |
| GET | /api/analytics/sales-by-time | 时间维度销售分析 |
| GET | /api/analytics/top-products | 产品销售排行 |
| GET | /api/analytics/category-sales | 分类销售统计 |
| GET | /api/analytics/dashboard | 实时仪表盘 |
| GET | /api/analytics/export | 导出报告 |

### 库存管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /api/inventory/check | 检查库存 |
| POST | /api/inventory/adjust | 调整库存 |

### 商品管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/products | 获取商品列表 |
| GET | /api/products/{id} | 获取商品详情 |

## 默认用户

系统初始化后会创建以下默认用户：

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 商家 | merchant | merchant123 |
| 客户 | customer | customer123 |

## 数据库设计

### 核心表结构

- **users**: 用户表
- **orders**: 订单表
- **order_items**: 订单项表
- **products**: 商品表
- **categories**: 分类表
- **addresses**: 地址表
- **payment_logs**: 支付日志表
- **logistics_logs**: 物流日志表
- **after_sales**: 售后申请表
- **inventory_logs**: 库存日志表

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| DATABASE_URL | 数据库连接URL | mysql+pymysql://root:password@localhost/ecommerce_db |
| SECRET_KEY | Flask密钥 | your-secret-key |
| JWT_SECRET_KEY | JWT密钥 | your-jwt-secret |
| REDIS_URL | Redis连接URL | redis://localhost:6379/0 |
| LOGISTICS_API_URL | 物流API地址 | https://api.logistics.example.com |
| LOGISTICS_API_KEY | 物流API密钥 | - |

## 开发说明

### 添加新的物流公司支持

在 `logistics_client.py` 中：

1. 创建新的物流公司客户端类，继承 `LogisticsClient`
2. 实现 `create_shipment`, `cancel_shipment`, `get_tracking` 方法
3. 在 `LogisticsService.COMPANY_CLIENT_MAP` 中注册

### 添加新的数据分析维度

在 `order_analytics.py` 中：

1. 在 `OrderAnalytics` 类中添加新的分析方法
2. 在 `web_interface.py` 中添加对应的API接口

## 测试

```bash
# 运行测试
pytest

# 生成测试报告
pytest --cov=./ --cov-report=html
```

## 部署

### 使用 Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:5000 web_interface:app
```

### 使用 Docker

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "run.py"]
```

## 许可证

MIT License
