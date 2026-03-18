import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'ecommerce-order-fulfillment-secret-key-2024'
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///order_fulfillment.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-key-2024'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=2)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    
    LOGISTICS_API_URL = os.environ.get('LOGISTICS_API_URL', 'https://api.logistics.example.com')
    LOGISTICS_API_KEY = os.environ.get('LOGISTICS_API_KEY', 'logistics-api-key')
    
    PAYMENT_GATEWAY_URL = os.environ.get('PAYMENT_GATEWAY_URL', 'https://api.payment.example.com')
    PAYMENT_MERCHANT_ID = os.environ.get('PAYMENT_MERCHANT_ID', 'merchant-001')
    PAYMENT_SECRET_KEY = os.environ.get('PAYMENT_SECRET_KEY', 'payment-secret-key')
    
    ERP_API_URL = os.environ.get('ERP_API_URL', 'https://api.erp.example.com')
    ERP_API_KEY = os.environ.get('ERP_API_KEY', 'erp-api-key')
    
    CRM_API_URL = os.environ.get('CRM_API_URL', 'https://api.crm.example.com')
    CRM_API_KEY = os.environ.get('CRM_API_KEY', 'crm-api-key')
    
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    
    ORDER_AUTO_CANCEL_MINUTES = 30
    ORDER_AUTO_CONFIRM_DAYS = 7
    AFTER_SALES_DAYS_LIMIT = 15
    
    INVENTORY_LOW_THRESHOLD = 10
    INVENTORY_CRITICAL_THRESHOLD = 5


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
