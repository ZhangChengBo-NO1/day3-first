import json
import hashlib
import hmac
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class LogisticsError(Exception):
    """物流接口错误"""
    pass


class LogisticsAPIError(LogisticsError):
    """物流API调用错误"""
    def __init__(self, message: str, code: Optional[str] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.response_data = response_data


class LogisticsCompany(str, Enum):
    """物流公司枚举"""
    SF = "sf"                    # 顺丰
    YTO = "yto"                  # 圆通
    ZTO = "zto"                  # 中通
    STO = "sto"                  # 申通
    YD = "yd"                    # 韵达
    EMS = "ems"                  # EMS
    JD = "jd"                    # 京东物流
    BEST = "best"                # 百世快递
    DEBANG = "debang"            # 德邦
    JIAYUNMEI = "jiayunmei"      # 佳运美


@dataclass
class ShippingAddress:
    """收货地址"""
    receiver_name: str
    phone: str
    province: str
    city: str
    district: str
    detail_address: str
    zip_code: Optional[str] = None


@dataclass
class PackageInfo:
    """包裹信息"""
    weight: float                    # 重量(kg)
    length: Optional[float] = None   # 长(cm)
    width: Optional[float] = None    # 宽(cm)
    height: Optional[float] = None   # 高(cm)
    volume: Optional[float] = None   # 体积(m³)
    goods_type: str = "general"      # 商品类型
    declared_value: Optional[float] = None  # 声明价值


@dataclass
class ShippingOrder:
    """发货订单"""
    order_no: str
    logistics_company: LogisticsCompany
    sender_address: ShippingAddress
    receiver_address: ShippingAddress
    package: PackageInfo
    goods_description: str
    remark: Optional[str] = None


@dataclass
class ShippingResult:
    """发货结果"""
    success: bool
    tracking_no: Optional[str] = None
    waybill_url: Optional[str] = None
    estimated_delivery_time: Optional[datetime] = None
    freight: Optional[float] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None


@dataclass
class TrackingEvent:
    """物流跟踪事件"""
    time: datetime
    status: str
    description: str
    location: Optional[str] = None
    operator: Optional[str] = None


@dataclass
class TrackingResult:
    """物流跟踪结果"""
    success: bool
    tracking_no: str
    logistics_company: str
    status: str
    events: List[TrackingEvent]
    is_delivered: bool = False
    delivered_time: Optional[datetime] = None
    error_message: Optional[str] = None


class LogisticsClient:
    """物流客户端基类"""
    
    def __init__(
        self,
        api_url: str,
        api_key: str,
        api_secret: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        
        # 配置HTTP会话
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """生成请求签名"""
        if not self.api_secret:
            return ""
        
        # 按key排序并拼接
        sorted_params = sorted(params.items())
        sign_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
        sign_string = f"{sign_string}&key={self.api_secret}"
        
        return hashlib.md5(sign_string.encode()).hexdigest().upper()
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """发送HTTP请求"""
        url = f"{self.api_url}{endpoint}"
        
        # 添加通用参数
        if params is None:
            params = {}
        params['api_key'] = self.api_key
        params['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        params['sign'] = self._generate_signature(params)
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            else:
                response = self.session.post(
                    url, params=params, json=data, headers=headers, timeout=self.timeout
                )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('code') != '200':
                raise LogisticsAPIError(
                    message=result.get('message', 'Unknown error'),
                    code=result.get('code'),
                    response_data=result
                )
            
            return result
            
        except requests.exceptions.RequestException as e:
            raise LogisticsAPIError(f"Request failed: {str(e)}")
    
    def create_shipment(self, shipping_order: ShippingOrder) -> ShippingResult:
        """创建物流订单"""
        raise NotImplementedError
    
    def cancel_shipment(self, tracking_no: str, reason: str) -> bool:
        """取消物流订单"""
        raise NotImplementedError
    
    def get_tracking(self, tracking_no: str, logistics_company: Optional[str] = None) -> TrackingResult:
        """查询物流轨迹"""
        raise NotImplementedError
    
    def calculate_freight(
        self,
        logistics_company: LogisticsCompany,
        sender_address: ShippingAddress,
        receiver_address: ShippingAddress,
        package: PackageInfo
    ) -> float:
        """计算运费"""
        raise NotImplementedError


class MockLogisticsClient(LogisticsClient):
    """模拟物流客户端（用于开发和测试）"""
    
    _tracking_db: Dict[str, List[TrackingEvent]] = {}
    
    def create_shipment(self, shipping_order: ShippingOrder) -> ShippingResult:
        """创建模拟物流订单"""
        tracking_no = f"SF{datetime.now().strftime('%Y%m%d%H%M%S')}{hash(shipping_order.order_no) % 10000:04d}"
        
        # 模拟运费计算
        freight = self._calculate_mock_freight(shipping_order)
        
        # 初始化物流轨迹
        self._tracking_db[tracking_no] = [
            TrackingEvent(
                time=datetime.now(),
                status="已揽件",
                description="快递员已揽件",
                location=shipping_order.sender_address.city
            )
        ]
        
        return ShippingResult(
            success=True,
            tracking_no=tracking_no,
            waybill_url=f"https://logistics.example.com/waybill/{tracking_no}",
            estimated_delivery_time=datetime.now() + __import__('datetime').timedelta(days=2),
            freight=freight,
            raw_response={"tracking_no": tracking_no, "freight": freight}
        )
    
    def cancel_shipment(self, tracking_no: str, reason: str) -> bool:
        """取消模拟物流订单"""
        if tracking_no in self._tracking_db:
            del self._tracking_db[tracking_no]
            return True
        return False
    
    def get_tracking(self, tracking_no: str, logistics_company: Optional[str] = None) -> TrackingResult:
        """查询模拟物流轨迹"""
        events = self._tracking_db.get(tracking_no, [])
        
        if not events:
            return TrackingResult(
                success=False,
                tracking_no=tracking_no,
                logistics_company=logistics_company or "SF",
                status="未知",
                events=[],
                error_message="未找到物流信息"
            )
        
        # 模拟物流进度
        self._simulate_tracking_progress(tracking_no, events)
        
        is_delivered = events[-1].status == "已签收"
        delivered_time = events[-1].time if is_delivered else None
        
        return TrackingResult(
            success=True,
            tracking_no=tracking_no,
            logistics_company=logistics_company or "SF",
            status=events[-1].status,
            events=events,
            is_delivered=is_delivered,
            delivered_time=delivered_time
        )
    
    def calculate_freight(
        self,
        logistics_company: LogisticsCompany,
        sender_address: ShippingAddress,
        receiver_address: ShippingAddress,
        package: PackageInfo
    ) -> float:
        """计算模拟运费"""
        base_price = 12.0
        weight_price = max(0, package.weight - 1) * 5.0
        return base_price + weight_price
    
    def _calculate_mock_freight(self, shipping_order: ShippingOrder) -> float:
        """计算模拟运费"""
        return self.calculate_freight(
            shipping_order.logistics_company,
            shipping_order.sender_address,
            shipping_order.receiver_address,
            shipping_order.package
        )
    
    def _simulate_tracking_progress(self, tracking_no: str, events: List[TrackingEvent]):
        """模拟物流进度更新"""
        import random
        
        if len(events) < 2 and random.random() > 0.5:
            # 模拟运输中
            events.append(TrackingEvent(
                time=datetime.now(),
                status="运输中",
                description="快件已到达转运中心",
                location="转运中心"
            ))
        elif len(events) < 3 and random.random() > 0.7:
            # 模拟派送中
            events.append(TrackingEvent(
                time=datetime.now(),
                status="派送中",
                description="快递员正在派送中",
                location=events[0].location
            ))
        elif len(events) < 4 and random.random() > 0.8:
            # 模拟已签收
            events.append(TrackingEvent(
                time=datetime.now(),
                status="已签收",
                description="快件已签收",
                location=events[0].location,
                operator="收件人"
            ))


class SFLogisticsClient(LogisticsClient):
    """顺丰物流客户端"""
    
    def create_shipment(self, shipping_order: ShippingOrder) -> ShippingResult:
        """创建顺丰订单"""
        endpoint = "/api/v1/order"
        
        payload = {
            "orderId": shipping_order.order_no,
            "expressType": "1",  # 标准快递
            "payMethod": "1",    # 寄方付
            "sender": {
                "name": shipping_order.sender_address.receiver_name,
                "mobile": shipping_order.sender_address.phone,
                "province": shipping_order.sender_address.province,
                "city": shipping_order.sender_address.city,
                "district": shipping_order.sender_address.district,
                "address": shipping_order.sender_address.detail_address
            },
            "receiver": {
                "name": shipping_order.receiver_address.receiver_name,
                "mobile": shipping_order.receiver_address.phone,
                "province": shipping_order.receiver_address.province,
                "city": shipping_order.receiver_address.city,
                "district": shipping_order.receiver_address.district,
                "address": shipping_order.receiver_address.detail_address
            },
            "parcel": {
                "weight": shipping_order.package.weight,
                "length": shipping_order.package.length,
                "width": shipping_order.package.width,
                "height": shipping_order.package.height,
                "goodsDescription": shipping_order.goods_description
            },
            "remark": shipping_order.remark
        }
        
        try:
            result = self._make_request('POST', endpoint, data=payload)
            data = result.get('data', {})
            
            return ShippingResult(
                success=True,
                tracking_no=data.get('waybillNo'),
                waybill_url=data.get('waybillUrl'),
                estimated_delivery_time=datetime.fromisoformat(data.get('estimatedDeliveryTime'))
                    if data.get('estimatedDeliveryTime') else None,
                freight=data.get('freight'),
                raw_response=result
            )
        except LogisticsAPIError as e:
            return ShippingResult(
                success=False,
                error_message=e.message,
                raw_response=e.response_data
            )
    
    def cancel_shipment(self, tracking_no: str, reason: str) -> bool:
        """取消顺丰订单"""
        endpoint = "/api/v1/order/cancel"
        payload = {
            "waybillNo": tracking_no,
            "reason": reason
        }
        
        try:
            result = self._make_request('POST', endpoint, data=payload)
            return result.get('data', {}).get('success', False)
        except LogisticsAPIError:
            return False
    
    def get_tracking(self, tracking_no: str, logistics_company: Optional[str] = None) -> TrackingResult:
        """查询顺丰物流轨迹"""
        endpoint = "/api/v1/route"
        params = {"waybillNo": tracking_no}
        
        try:
            result = self._make_request('GET', endpoint, params=params)
            data = result.get('data', {})
            
            events = []
            for event in data.get('routes', []):
                events.append(TrackingEvent(
                    time=datetime.fromisoformat(event.get('acceptTime')),
                    status=event.get('remark'),
                    description=event.get('acceptAddress'),
                    location=event.get('acceptAddress')
                ))
            
            is_delivered = data.get('isDelivered', False)
            delivered_time = datetime.fromisoformat(data.get('deliveredTime')) \
                if data.get('deliveredTime') else None
            
            return TrackingResult(
                success=True,
                tracking_no=tracking_no,
                logistics_company="SF",
                status=data.get('status', '未知'),
                events=events,
                is_delivered=is_delivered,
                delivered_time=delivered_time
            )
        except LogisticsAPIError as e:
            return TrackingResult(
                success=False,
                tracking_no=tracking_no,
                logistics_company="SF",
                status="查询失败",
                events=[],
                error_message=e.message
            )
    
    def calculate_freight(
        self,
        logistics_company: LogisticsCompany,
        sender_address: ShippingAddress,
        receiver_address: ShippingAddress,
        package: PackageInfo
    ) -> float:
        """计算顺丰运费"""
        endpoint = "/api/v1/freight"
        payload = {
            "senderProvince": sender_address.province,
            "senderCity": sender_address.city,
            "receiverProvince": receiver_address.province,
            "receiverCity": receiver_address.city,
            "weight": package.weight,
            "volume": package.volume
        }
        
        try:
            result = self._make_request('POST', endpoint, data=payload)
            return result.get('data', {}).get('freight', 0.0)
        except LogisticsAPIError:
            return 0.0


class LogisticsService:
    """物流服务"""
    
    COMPANY_CLIENT_MAP = {
        LogisticsCompany.SF: SFLogisticsClient,
        # 可以添加其他物流公司的客户端映射
    }
    
    def __init__(
        self,
        api_url: str,
        api_key: str,
        api_secret: Optional[str] = None,
        use_mock: bool = False
    ):
        self.use_mock = use_mock
        self.api_url = api_url
        self.api_key = api_key
        self.api_secret = api_secret
        self._clients: Dict[LogisticsCompany, LogisticsClient] = {}
    
    def _get_client(self, company: LogisticsCompany) -> LogisticsClient:
        """获取物流公司客户端"""
        if company not in self._clients:
            if self.use_mock:
                self._clients[company] = MockLogisticsClient(
                    self.api_url, self.api_key, self.api_secret
                )
            else:
                client_class = self.COMPANY_CLIENT_MAP.get(
                    company, MockLogisticsClient
                )
                self._clients[company] = client_class(
                    self.api_url, self.api_key, self.api_secret
                )
        return self._clients[company]
    
    def create_shipment(
        self,
        order_no: str,
        logistics_company: str,
        sender_info: Dict,
        receiver_info: Dict,
        package_info: Dict,
        goods_description: str
    ) -> ShippingResult:
        """创建发货单"""
        company = LogisticsCompany(logistics_company)
        client = self._get_client(company)
        
        shipping_order = ShippingOrder(
            order_no=order_no,
            logistics_company=company,
            sender_address=ShippingAddress(**sender_info),
            receiver_address=ShippingAddress(**receiver_info),
            package=PackageInfo(**package_info),
            goods_description=goods_description
        )
        
        return client.create_shipment(shipping_order)
    
    def get_tracking(
        self,
        tracking_no: str,
        logistics_company: str
    ) -> TrackingResult:
        """查询物流轨迹"""
        company = LogisticsCompany(logistics_company)
        client = self._get_client(company)
        return client.get_tracking(tracking_no, logistics_company)
    
    def cancel_shipment(
        self,
        tracking_no: str,
        logistics_company: str,
        reason: str
    ) -> bool:
        """取消发货"""
        company = LogisticsCompany(logistics_company)
        client = self._get_client(company)
        return client.cancel_shipment(tracking_no, reason)
    
    def batch_get_tracking(
        self,
        tracking_nos: List[Dict[str, str]]
    ) -> List[TrackingResult]:
        """批量查询物流轨迹"""
        results = []
        for item in tracking_nos:
            result = self.get_tracking(
                item['tracking_no'],
                item['logistics_company']
            )
            results.append(result)
        return results


# ERP/CRM 对接接口

class ERPIntegrationClient:
    """ERP系统集成客户端"""
    
    def __init__(self, api_url: str, api_key: str, api_secret: Optional[str] = None):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
    
    def sync_order(self, order_data: Dict) -> bool:
        """同步订单到ERP"""
        endpoint = "/api/orders/sync"
        try:
            response = self.session.post(
                f"{self.api_url}{endpoint}",
                json=order_data,
                headers={"X-API-Key": self.api_key},
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def sync_inventory(self, inventory_data: List[Dict]) -> bool:
        """同步库存到ERP"""
        endpoint = "/api/inventory/sync"
        try:
            response = self.session.post(
                f"{self.api_url}{endpoint}",
                json={"items": inventory_data},
                headers={"X-API-Key": self.api_key},
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


class CRMIntegrationClient:
    """CRM系统集成客户端"""
    
    def __init__(self, api_url: str, api_key: str, api_secret: Optional[str] = None):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
    
    def sync_customer(self, customer_data: Dict) -> bool:
        """同步客户信息到CRM"""
        endpoint = "/api/customers/sync"
        try:
            response = self.session.post(
                f"{self.api_url}{endpoint}",
                json=customer_data,
                headers={"X-API-Key": self.api_key},
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def record_order_behavior(self, user_id: int, behavior_data: Dict) -> bool:
        """记录客户购买行为"""
        endpoint = "/api/behaviors/record"
        try:
            response = self.session.post(
                f"{self.api_url}{endpoint}",
                json={
                    "user_id": user_id,
                    **behavior_data
                },
                headers={"X-API-Key": self.api_key},
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
