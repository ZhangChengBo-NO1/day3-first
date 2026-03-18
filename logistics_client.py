import requests
import hashlib
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class LogisticsException(Exception):
    pass


class BaseLogisticsClient(ABC):
    
    @abstractmethod
    def create_shipment(self, order_info: Dict) -> Dict:
        pass
    
    @abstractmethod
    def query_tracking(self, tracking_number: str) -> Dict:
        pass
    
    @abstractmethod
    def cancel_shipment(self, tracking_number: str) -> Dict:
        pass
    
    @abstractmethod
    def get_companies(self) -> List[Dict]:
        pass


class SFExpressClient(BaseLogisticsClient):
    
    def __init__(self, api_url: str, partner_id: str, secret_key: str):
        self.api_url = api_url
        self.partner_id = partner_id
        self.secret_key = secret_key
        self.company_code = 'SF'
        self.company_name = '顺丰速运'
    
    def _generate_sign(self, data: Dict, timestamp: str) -> str:
        sorted_keys = sorted(data.keys())
        sign_str = ''
        for key in sorted_keys:
            sign_str += f'{key}={data[key]}&'
        sign_str += f'timestamp={timestamp}&secret={self.secret_key}'
        return hashlib.md5(sign_str.encode()).hexdigest().upper()
    
    def _make_request(self, endpoint: str, data: Dict) -> Dict:
        timestamp = str(int(time.time()))
        data['partner_id'] = self.partner_id
        sign = self._generate_sign(data, timestamp)
        
        headers = {
            'Content-Type': 'application/json',
            'X-Timestamp': timestamp,
            'X-Sign': sign
        }
        
        try:
            response = requests.post(
                f'{self.api_url}{endpoint}',
                json=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f'SF Express API error: {str(e)}')
            raise LogisticsException(f'物流接口调用失败: {str(e)}')
    
    def create_shipment(self, order_info: Dict) -> Dict:
        data = {
            'order_id': order_info.get('order_id'),
            'sender_name': order_info.get('sender_name', '电商仓库'),
            'sender_phone': order_info.get('sender_phone', '400-123-4567'),
            'sender_address': order_info.get('sender_address', '广东省深圳市南山区科技园'),
            'receiver_name': order_info.get('recipient_name'),
            'receiver_phone': order_info.get('recipient_phone'),
            'receiver_province': order_info.get('province'),
            'receiver_city': order_info.get('city'),
            'receiver_district': order_info.get('district'),
            'receiver_address': order_info.get('recipient_address'),
            'weight': order_info.get('weight', 1.0),
            'product_type': order_info.get('product_type', 1),
            'pay_method': 1,
            'remark': order_info.get('remark', '')
        }
        
        result = self._make_request('/order/create', data)
        
        if result.get('success'):
            return {
                'success': True,
                'tracking_number': result.get('mailno'),
                'company_code': self.company_code,
                'company_name': self.company_name,
                'estimated_delivery': result.get('estimated_delivery_time')
            }
        else:
            raise LogisticsException(result.get('msg', '创建运单失败'))
    
    def query_tracking(self, tracking_number: str) -> Dict:
        data = {'mailno': tracking_number}
        result = self._make_request('/route/query', data)
        
        if result.get('success'):
            routes = result.get('routes', [])
            return {
                'success': True,
                'tracking_number': tracking_number,
                'company': self.company_name,
                'status': routes[-1].get('status') if routes else 'unknown',
                'traces': [{
                    'time': r.get('time'),
                    'location': r.get('location'),
                    'status': r.get('status'),
                    'description': r.get('remark')
                } for r in routes]
            }
        else:
            raise LogisticsException(result.get('msg', '查询物流失败'))
    
    def cancel_shipment(self, tracking_number: str) -> Dict:
        data = {'mailno': tracking_number}
        result = self._make_request('/order/cancel', data)
        
        return {
            'success': result.get('success', False),
            'message': result.get('msg', '取消运单成功')
        }
    
    def get_companies(self) -> List[Dict]:
        return [{'code': self.company_code, 'name': self.company_name}]


class JDLogisticsClient(BaseLogisticsClient):
    
    def __init__(self, api_url: str, app_key: str, app_secret: str):
        self.api_url = api_url
        self.app_key = app_key
        self.app_secret = app_secret
        self.company_code = 'JD'
        self.company_name = '京东物流'
    
    def _generate_sign(self, data: Dict, timestamp: str) -> str:
        sign_str = f'{self.app_secret}{json.dumps(data, sort_keys=True)}{timestamp}{self.app_key}'
        return hashlib.sha256(sign_str.encode()).hexdigest().upper()
    
    def _make_request(self, endpoint: str, data: Dict) -> Dict:
        timestamp = str(int(time.time() * 1000))
        sign = self._generate_sign(data, timestamp)
        
        headers = {
            'Content-Type': 'application/json',
            'X-App-Key': self.app_key,
            'X-Timestamp': timestamp,
            'X-Sign': sign
        }
        
        try:
            response = requests.post(
                f'{self.api_url}{endpoint}',
                json=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f'JD Logistics API error: {str(e)}')
            raise LogisticsException(f'京东物流接口调用失败: {str(e)}')
    
    def create_shipment(self, order_info: Dict) -> Dict:
        data = {
            'orderId': order_info.get('order_id'),
            'senderInfo': {
                'name': order_info.get('sender_name', '电商仓库'),
                'phone': order_info.get('sender_phone', '400-123-4567'),
                'address': order_info.get('sender_address', '北京市大兴区京东仓库')
            },
            'receiverInfo': {
                'name': order_info.get('recipient_name'),
                'phone': order_info.get('recipient_phone'),
                'province': order_info.get('province'),
                'city': order_info.get('city'),
                'county': order_info.get('district'),
                'address': order_info.get('recipient_address')
            },
            'packageInfo': {
                'weight': order_info.get('weight', 1.0),
                'length': order_info.get('length', 20),
                'width': order_info.get('width', 15),
                'height': order_info.get('height', 10)
            }
        }
        
        result = self._make_request('/api/order/create', data)
        
        if result.get('code') == 200:
            return {
                'success': True,
                'tracking_number': result.get('data', {}).get('waybillCode'),
                'company_code': self.company_code,
                'company_name': self.company_name,
                'estimated_delivery': result.get('data', {}).get('promiseTime')
            }
        else:
            raise LogisticsException(result.get('msg', '创建运单失败'))
    
    def query_tracking(self, tracking_number: str) -> Dict:
        data = {'waybillCode': tracking_number}
        result = self._make_request('/api/track/query', data)
        
        if result.get('code') == 200:
            tracks = result.get('data', {}).get('tracks', [])
            return {
                'success': True,
                'tracking_number': tracking_number,
                'company': self.company_name,
                'status': tracks[-1].get('status') if tracks else 'unknown',
                'traces': [{
                    'time': t.get('time'),
                    'location': t.get('location'),
                    'status': t.get('status'),
                    'description': t.get('content')
                } for t in tracks]
            }
        else:
            raise LogisticsException(result.get('msg', '查询物流失败'))
    
    def cancel_shipment(self, tracking_number: str) -> Dict:
        data = {'waybillCode': tracking_number}
        result = self._make_request('/api/order/cancel', data)
        
        return {
            'success': result.get('code') == 200,
            'message': result.get('msg', '取消运单成功')
        }
    
    def get_companies(self) -> List[Dict]:
        return [{'code': self.company_code, 'name': self.company_name}]


class ZTOExpressClient(BaseLogisticsClient):
    
    def __init__(self, api_url: str, partner_id: str, secret_key: str):
        self.api_url = api_url
        self.partner_id = partner_id
        self.secret_key = secret_key
        self.company_code = 'ZTO'
        self.company_name = '中通快递'
    
    def _generate_sign(self, data: Dict) -> str:
        sign_str = f'{json.dumps(data, sort_keys=True)}{self.secret_key}'
        return hashlib.md5(sign_str.encode()).hexdigest().upper()
    
    def _make_request(self, endpoint: str, data: Dict) -> Dict:
        data['partner'] = self.partner_id
        sign = self._generate_sign(data)
        
        headers = {
            'Content-Type': 'application/json',
            'X-Sign': sign
        }
        
        try:
            response = requests.post(
                f'{self.api_url}{endpoint}',
                json=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f'ZTO Express API error: {str(e)}')
            raise LogisticsException(f'中通快递接口调用失败: {str(e)}')
    
    def create_shipment(self, order_info: Dict) -> Dict:
        data = {
            'orderid': order_info.get('order_id'),
            'sender': {
                'name': order_info.get('sender_name', '电商仓库'),
                'mobile': order_info.get('sender_phone', '400-123-4567'),
                'address': order_info.get('sender_address', '上海市青浦区中通快递')
            },
            'receiver': {
                'name': order_info.get('recipient_name'),
                'mobile': order_info.get('recipient_phone'),
                'province': order_info.get('province'),
                'city': order_info.get('city'),
                'district': order_info.get('district'),
                'address': order_info.get('recipient_address')
            },
            'weight': order_info.get('weight', 1.0)
        }
        
        result = self._make_request('/openapi/order', data)
        
        if result.get('status'):
            return {
                'success': True,
                'tracking_number': result.get('billcode'),
                'company_code': self.company_code,
                'company_name': self.company_name,
                'estimated_delivery': result.get('predict_time')
            }
        else:
            raise LogisticsException(result.get('message', '创建运单失败'))
    
    def query_tracking(self, tracking_number: str) -> Dict:
        data = {'billcode': tracking_number}
        result = self._make_request('/openapi/trace', data)
        
        if result.get('status'):
            traces = result.get('traces', [])
            return {
                'success': True,
                'tracking_number': tracking_number,
                'company': self.company_name,
                'status': traces[-1].get('status') if traces else 'unknown',
                'traces': [{
                    'time': t.get('time'),
                    'location': t.get('location'),
                    'status': t.get('status'),
                    'description': t.get('desc')
                } for t in traces]
            }
        else:
            raise LogisticsException(result.get('message', '查询物流失败'))
    
    def cancel_shipment(self, tracking_number: str) -> Dict:
        data = {'billcode': tracking_number}
        result = self._make_request('/openapi/cancel', data)
        
        return {
            'success': result.get('status', False),
            'message': result.get('message', '取消运单成功')
        }
    
    def get_companies(self) -> List[Dict]:
        return [{'code': self.company_code, 'name': self.company_name}]


class LogisticsClientFactory:
    
    _clients: Dict[str, BaseLogisticsClient] = {}
    
    @classmethod
    def register_client(cls, company_code: str, client: BaseLogisticsClient):
        cls._clients[company_code] = client
    
    @classmethod
    def get_client(cls, company_code: str) -> BaseLogisticsClient:
        client = cls._clients.get(company_code)
        if not client:
            raise LogisticsException(f'不支持的物流公司: {company_code}')
        return client
    
    @classmethod
    def get_all_companies(cls) -> List[Dict]:
        companies = []
        for code, client in cls._clients.items():
            companies.extend(client.get_companies())
        return companies


class LogisticsService:
    
    def __init__(self, config):
        self._init_clients(config)
    
    def _init_clients(self, config):
        sf_client = SFExpressClient(
            api_url=config.LOGISTICS_API_URL,
            partner_id='SF_PARTNER_ID',
            secret_key=config.LOGISTICS_API_KEY
        )
        LogisticsClientFactory.register_client('SF', sf_client)
        
        jd_client = JDLogisticsClient(
            api_url=config.LOGISTICS_API_URL,
            app_key='JD_APP_KEY',
            app_secret='JD_APP_SECRET'
        )
        LogisticsClientFactory.register_client('JD', jd_client)
        
        zto_client = ZTOExpressClient(
            api_url=config.LOGISTICS_API_URL,
            partner_id='ZTO_PARTNER_ID',
            secret_key=config.LOGISTICS_API_KEY
        )
        LogisticsClientFactory.register_client('ZTO', zto_client)
    
    def create_shipment(self, company_code: str, order_info: Dict) -> Dict:
        client = LogisticsClientFactory.get_client(company_code)
        return client.create_shipment(order_info)
    
    def query_tracking(self, company_code: str, tracking_number: str) -> Dict:
        client = LogisticsClientFactory.get_client(company_code)
        return client.query_tracking(tracking_number)
    
    def cancel_shipment(self, company_code: str, tracking_number: str) -> Dict:
        client = LogisticsClientFactory.get_client(company_code)
        return client.cancel_shipment(tracking_number)
    
    def get_available_companies(self) -> List[Dict]:
        return LogisticsClientFactory.get_all_companies()
    
    def calculate_shipping_fee(self, order_info: Dict) -> Dict:
        base_fee = 10.0
        weight = float(order_info.get('weight', 1.0))
        province = order_info.get('province', '')
        
        remote_provinces = ['新疆', '西藏', '青海', '内蒙古', '甘肃']
        is_remote = any(p in province for p in remote_provinces)
        
        if is_remote:
            base_fee = 20.0
            weight_fee = max(0, weight - 1) * 8
        else:
            weight_fee = max(0, weight - 1) * 3
        
        total_fee = base_fee + weight_fee
        
        return {
            'base_fee': base_fee,
            'weight_fee': weight_fee,
            'total_fee': round(total_fee, 2),
            'estimated_days': 5 if is_remote else 3
        }
