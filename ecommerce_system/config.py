import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'your-jwt-secret-key'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://root:password@localhost/ecommerce_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True
    }
    
    # Redis
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # Logistics API
    LOGISTICS_API_URL = os.environ.get('LOGISTICS_API_URL') or 'https://api.logistics.example.com'
    LOGISTICS_API_KEY = os.environ.get('LOGISTICS_API_KEY') or 'your-logistics-api-key'
    
    # Payment Gateway
    PAYMENT_GATEWAY_URL = os.environ.get('PAYMENT_GATEWAY_URL') or 'https://api.payment.example.com'
    PAYMENT_API_KEY = os.environ.get('PAYMENT_API_KEY') or 'your-payment-api-key'
    
    # ERP/CRM Integration
    ERP_API_URL = os.environ.get('ERP_API_URL') or 'https://api.erp.example.com'
    ERP_API_KEY = os.environ.get('ERP_API_KEY') or 'your-erp-api-key'
    CRM_API_URL = os.environ.get('CRM_API_URL') or 'https://api.crm.example.com'
    CRM_API_KEY = os.environ.get('CRM_API_KEY') or 'your-crm-api-key'
    
    # Order Settings
    ORDER_EXPIRE_MINUTES = 30
    INVENTORY_RESERVE_MINUTES = 15
    MAX_CANCEL_DAYS = 7
    
    # Pagination
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        'mysql+pymysql://root:password@localhost/ecommerce_dev'


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or \
        'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
