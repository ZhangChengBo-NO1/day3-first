from functools import wraps
from datetime import datetime
from typing import Optional, Dict, Any

from flask import request, jsonify, current_app
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    get_jwt_identity, jwt_required, verify_jwt_in_request,
    get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash

from order_models import User, UserRole, db


jwt = JWTManager()


class AuthError(Exception):
    """认证错误"""
    pass


class PermissionDeniedError(AuthError):
    """权限不足错误"""
    pass


def init_auth(app):
    """初始化认证模块"""
    jwt.init_app(app)
    
    @jwt.user_identity_loader
    def user_identity_lookup(user):
        return {
            'id': user.id,
            'username': user.username,
            'role': user.role.value
        }
    
    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data["sub"]
        return User.query.filter_by(id=identity['id']).first()
    
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({
            'success': False,
            'message': 'Token已过期',
            'error': 'token_expired'
        }), 401
    
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({
            'success': False,
            'message': '无效的Token',
            'error': 'invalid_token'
        }), 401
    
    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({
            'success': False,
            'message': '缺少认证Token',
            'error': 'authorization_required'
        }), 401


class AuthService:
    """认证服务"""
    
    @staticmethod
    def register(
        username: str,
        email: str,
        password: str,
        phone: Optional[str] = None,
        role: UserRole = UserRole.CUSTOMER
    ) -> User:
        """用户注册"""
        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            raise AuthError("用户名已存在")
        
        # 检查邮箱是否已存在
        if User.query.filter_by(email=email).first():
            raise AuthError("邮箱已被注册")
        
        # 创建用户
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            phone=phone,
            role=role
        )
        db.session.add(user)
        db.session.commit()
        
        return user
    
    @staticmethod
    def login(username_or_email: str, password: str) -> Dict[str, Any]:
        """用户登录"""
        # 支持用户名或邮箱登录
        user = User.query.filter(
            db.or_(
                User.username == username_or_email,
                User.email == username_or_email
            )
        ).first()
        
        if not user:
            raise AuthError("用户不存在")
        
        if not user.is_active:
            raise AuthError("账户已被禁用")
        
        if not check_password_hash(user.password_hash, password):
            raise AuthError("密码错误")
        
        # 生成Token
        access_token = create_access_token(identity=user)
        refresh_token = create_refresh_token(identity=user)
        
        return {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role.value,
                'phone': user.phone
            },
            'access_token': access_token,
            'refresh_token': refresh_token
        }
    
    @staticmethod
    def change_password(user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码"""
        user = User.query.get(user_id)
        if not user:
            raise AuthError("用户不存在")
        
        if not check_password_hash(user.password_hash, old_password):
            raise AuthError("原密码错误")
        
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        return True
    
    @staticmethod
    def get_current_user() -> Optional[User]:
        """获取当前登录用户"""
        try:
            verify_jwt_in_request()
            identity = get_jwt_identity()
            return User.query.get(identity['id'])
        except:
            return None


def role_required(*allowed_roles: UserRole):
    """角色权限装饰器"""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()
            user_role = identity.get('role')
            
            if user_role not in [r.value for r in allowed_roles]:
                return jsonify({
                    'success': False,
                    'message': '权限不足',
                    'error': 'permission_denied'
                }), 403
            
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(fn):
    """管理员权限装饰器"""
    return role_required(UserRole.ADMIN)(fn)


def merchant_required(fn):
    """商家权限装饰器"""
    return role_required(UserRole.MERCHANT, UserRole.ADMIN)(fn)


def customer_required(fn):
    """客户权限装饰器"""
    return role_required(UserRole.CUSTOMER, UserRole.MERCHANT, UserRole.ADMIN)(fn)


def owner_or_admin_required(get_owner_id_func):
    """
    资源所有者或管理员权限装饰器
    
    Args:
        get_owner_id_func: 函数，用于从请求参数中获取资源所有者ID
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()
            user_id = identity['id']
            user_role = identity['role']
            
            # 管理员直接通过
            if user_role == UserRole.ADMIN.value:
                return fn(*args, **kwargs)
            
            # 检查是否是资源所有者
            owner_id = get_owner_id_func(*args, **kwargs)
            if user_id != owner_id:
                return jsonify({
                    'success': False,
                    'message': '无权访问此资源',
                    'error': 'permission_denied'
                }), 403
            
            return fn(*args, **kwargs)
        return wrapper
    return decorator


class Permission:
    """权限常量"""
    ORDER_VIEW = 'order:view'
    ORDER_CREATE = 'order:create'
    ORDER_CANCEL = 'order:cancel'
    ORDER_MANAGE = 'order:manage'
    
    PRODUCT_VIEW = 'product:view'
    PRODUCT_CREATE = 'product:create'
    PRODUCT_UPDATE = 'product:update'
    PRODUCT_DELETE = 'product:delete'
    
    INVENTORY_VIEW = 'inventory:view'
    INVENTORY_MANAGE = 'inventory:manage'
    
    ANALYTICS_VIEW = 'analytics:view'
    ANALYTICS_EXPORT = 'analytics:export'
    
    USER_VIEW = 'user:view'
    USER_MANAGE = 'user:manage'
    
    LOGISTICS_VIEW = 'logistics:view'
    LOGISTICS_MANAGE = 'logistics:manage'
    
    AFTER_SALES_VIEW = 'after_sales:view'
    AFTER_SALES_PROCESS = 'after_sales:process'


# 角色权限映射
ROLE_PERMISSIONS = {
    UserRole.CUSTOMER: [
        Permission.ORDER_VIEW,
        Permission.ORDER_CREATE,
        Permission.ORDER_CANCEL,
        Permission.PRODUCT_VIEW,
        Permission.LOGISTICS_VIEW,
        Permission.AFTER_SALES_VIEW,
    ],
    UserRole.MERCHANT: [
        Permission.ORDER_VIEW,
        Permission.ORDER_CREATE,
        Permission.ORDER_CANCEL,
        Permission.ORDER_MANAGE,
        Permission.PRODUCT_VIEW,
        Permission.PRODUCT_CREATE,
        Permission.PRODUCT_UPDATE,
        Permission.PRODUCT_DELETE,
        Permission.INVENTORY_VIEW,
        Permission.INVENTORY_MANAGE,
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.LOGISTICS_VIEW,
        Permission.LOGISTICS_MANAGE,
        Permission.AFTER_SALES_VIEW,
        Permission.AFTER_SALES_PROCESS,
    ],
    UserRole.LOGISTICS: [
        Permission.ORDER_VIEW,
        Permission.LOGISTICS_VIEW,
        Permission.LOGISTICS_MANAGE,
    ],
    UserRole.ADMIN: [
        Permission.ORDER_VIEW,
        Permission.ORDER_CREATE,
        Permission.ORDER_CANCEL,
        Permission.ORDER_MANAGE,
        Permission.PRODUCT_VIEW,
        Permission.PRODUCT_CREATE,
        Permission.PRODUCT_UPDATE,
        Permission.PRODUCT_DELETE,
        Permission.INVENTORY_VIEW,
        Permission.INVENTORY_MANAGE,
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.USER_VIEW,
        Permission.USER_MANAGE,
        Permission.LOGISTICS_VIEW,
        Permission.LOGISTICS_MANAGE,
        Permission.AFTER_SALES_VIEW,
        Permission.AFTER_SALES_PROCESS,
    ]
}


def permission_required(permission: str):
    """细粒度权限检查装饰器"""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()
            user_role = UserRole(identity.get('role'))
            
            # 获取角色权限
            permissions = ROLE_PERMISSIONS.get(user_role, [])
            
            # 检查是否有权限
            if permission not in permissions:
                return jsonify({
                    'success': False,
                    'message': f'缺少权限: {permission}',
                    'error': 'permission_denied'
                }), 403
            
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def audit_log(action: str):
    """审计日志装饰器"""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # 获取当前用户
            user = AuthService.get_current_user()
            user_info = f"用户 {user.username}(ID:{user.id})" if user else "匿名用户"
            
            # 记录请求
            current_app.logger.info(
                f"[AUDIT] {user_info} 执行 {action} - "
                f"Method: {request.method}, Path: {request.path}, "
                f"IP: {request.remote_addr}"
            )
            
            # 执行原函数
            response = fn(*args, **kwargs)
            
            return response
        return wrapper
    return decorator
