"""API client for LSTech Balance integration."""
import logging
import hashlib
import time
import requests
import json
import random
from urllib.parse import urlparse, parse_qsl
from datetime import datetime
from .const import API_DOMAIN
from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

class LSTechAPI:
    """API client for LSTech Balance."""
    appId = "129836377288"
    platform = "android"
    version = "v1"
    timeZone = "Asia/Shanghai"
    appVersion = "3.0.1401"
    APP_SECRET = "pOsgYHfmYNQzTbnTJXGpfYhvkRSsByBw"


    def __init__(self):
        """Initialize the API client."""
        self.access_token = None
        self.refresh_token = None
        self.access_token_expire = 0
        self.refresh_token_expire = 0
        self.uid = None
        self.member_id = None
        self.nickname = None
        self.last_updated = 0
        self.last_token_refresh = 0
        self.last_login_time = 0
        self.error_state = None
        self.error_time = None
        self.auth_error = False  # 标记严重认证错误
    
    def getSign(self, params):
        query_str = "&".join(k + "=" + params[k] for k in sorted(params))
        query_str += "&APP_SECRET=" + self.APP_SECRET
        return hashlib.md5(query_str.encode('utf-8')).hexdigest().upper()
    
    def _request(self, method, url, params=None, data=None, token=None, userId=None):
        """Make an API request."""
        try:
            # 解析URL中的查询参数
            parsed_url = urlparse(url)
            query_params = {k: v for k, v in parse_qsl(parsed_url.query)}
                        
            t = str(int(time.time() * 1000))
            Sign = {**query_params}
            Sign['appId'] = self.appId
            Sign['platform'] = self.platform
            Sign['timestamp'] = t
            Sign['version'] = self.version
            if token and userId:
                Sign['timeZone'] = self.timeZone
                Sign['token'] = token
                Sign['userId'] = userId
                Sign['appVersion'] = self.appVersion
            Signed = self.getSign(Sign)
            
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'okhttp/5.0.0-alpha.2',
                **Sign, 
                'sign': Signed
            }
            
            # 发送请求
            if method == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=10)
            else:
                response = requests.get(url, headers=headers, timeout=10)
                
            # 返回JSON响应
            try:
                result = response.json()
                
                ## 检查API返回的错误代码
                #if result.get("code") != "0":
                #    self.error_state = f"API error: {result.get('msg', 'Unknown error')}"
                #    self.error_time = datetime.now().isoformat()
                #    self.auth_error = True
                #    raise Exception(f"Authentication failed: {result.get('msg')}")
                    
                return result
            except json.JSONDecodeError:
                self.error_state = "Invalid JSON response"
                self.error_time = datetime.now().isoformat()
                return {"code": "-1", "msg": "Invalid JSON response"}
        
        except requests.exceptions.RequestException as err:
            self.error_state = f"Network error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            return {"code": "-1", "msg": f"Network error: {str(err)}"}
        except Exception as err:
            self.error_state = f"Unexpected error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            return {"code": "-1", "msg": f"Unexpected error: {str(err)}"}
    
    def send_verification_code(self, phone):
        """Send verification code to phone."""
        url = f"{API_DOMAIN}/account/verificationMsg?phoneNumber={phone}"
        return self._request("GET", url)
    
    def generate_deviceId(self, seed_str):
        seed_value = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
        rng = random.Random(seed_value)
        
        letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        alphanumeric = letters + "0123456789"
        
        part_a = ''.join(rng.choices(letters, k=9))
        part_b = ''.join(rng.choices(alphanumeric, k=31))
        part_c = rng.randint(11, 99)
        return f"{part_a}_{part_b}_{part_c}"

    def login(self, account, password):
        """Login with phone and verification code."""
        try:
            self.auth_error = False  # 重置认证错误标志
            
            device_id = self.generate_deviceId(account)
            data = {
                "appId": self.appId,
                "deviceId": device_id,
                "password": hashlib.md5(password.encode('utf-8')).hexdigest().upper()
            }
            if '@' in account:
                data['email'] = account
            elif len(account) == 11:
                data['phoneNumber'] = account
            
            response = self._request("POST", f"{API_DOMAIN}/account/login", data=data)
            
            if response.get("code") == "0":
                data = response["data"]
                self.access_token = data.get("accessToken")
                self.refresh_token = data.get("refreshToken")
                self.access_token_expire = int(data.get("accessTokenExpire", 0))
                self.refresh_token_expire = int(data.get("refreshTokenExpire", 0))
                self.uid = data.get("uid")
                self.nickname = data.get("nickname")
                self.last_token_refresh = time.time()
                self.last_login_time = time.time()
                
                # 查找用户对应的memberId
                for member in data.get("memberList", []):
                    if member.get("myself") == "1":
                        self.member_id = member.get("memberId")
                        break
            
            return response
        
        except Exception as err:
            self.error_state = f"Login failed: {str(err)}"
            self.error_time = datetime.now().isoformat()
            self.auth_error = True
            return {"code": "-1", "msg": str(err)}

    def quickLogin(self, phone, verification_code):
        """Login with phone and verification code."""
        try:
            self.auth_error = False  # 重置认证错误标志
            
            device_id = self.generate_deviceId(phone)
            data = {
                "appId": self.appId,
                "deviceId": device_id,
                "phoneNumber": phone,
                "verificationCode": verification_code
            }
            
            response = self._request("POST", f"{API_DOMAIN}/account/quickLogin", data=data)
            
            if response.get("code") == "0":
                data = response["data"]
                self.access_token = data.get("accessToken")
                self.refresh_token = data.get("refreshToken")
                self.access_token_expire = int(data.get("accessTokenExpire", 0))
                self.refresh_token_expire = int(data.get("refreshTokenExpire", 0))
                self.uid = data.get("uid")
                self.nickname = data.get("nickname")
                self.last_token_refresh = time.time()
                self.last_login_time = time.time()
                
                # 查找用户对应的memberId
                for member in data.get("memberList", []):
                    if member.get("myself") == "1":
                        self.member_id = member.get("memberId")
                        break
            
            return response
        
        except Exception as err:
            self.error_state = f"Login failed: {str(err)}"
            self.error_time = datetime.now().isoformat()
            self.auth_error = True
            return {"code": "-1", "msg": str(err)}

    def refresh_access_token(self, bForce=False):
        """Refresh access token using refresh token."""
        try:
            if time.time() > (self.last_login_time + self.refresh_token_expire - 30):
                self.error_state = "RefreshToken expired"
                self.error_time = datetime.now().isoformat()
                self.auth_error = True
                raise ConfigEntryAuthFailed("RefreshToken expired")
            # 检查是否真的需要刷新
            if not bForce and time.time() < (self.last_token_refresh + self.access_token_expire - 300):
                return True
                
            data = {
                "refreshToken": self.refresh_token,
                "uid": self.uid
            }
            
            response = self._request("POST", f"{API_DOMAIN}/account/refreshToken", data=data)
            if response.get("code") == "0":
                token_data = response["data"]
                self.access_token = token_data.get("accessToken")
                self.access_token_expire = int(token_data.get("accessTokenExpire", 0))
                self.last_token_refresh = time.time()
                self.error_state = None  # 清除错误状态
                return True
           
            if response.get("code") in ["2000"]:
                # 刷新token失败
                self.error_state = response.get('msg', 'Unknown error')
                self.error_time = datetime.now().isoformat()
                self.auth_error = True
                raise ConfigEntryAuthFailed(f"Authentication failed: {self.error_state}")

            return False
        except ConfigEntryAuthFailed as err:
            raise
        except Exception as err:
            raise
    
    def get_weight_data(self):
        """Get weight data from API."""
        try:
            # 重置临时错误状态
            self.error_state = None
            self.auth_error = False
            
            # 检查是否需要刷新token
            if not self.refresh_access_token():
                # 刷新失败，抛出异常让coordinator处理
                raise Exception("Token refresh failed")
            
            data = {"memberId": str(self.member_id)}  # 确保memberId是字符串
            response = self._request(
                "POST", 
                f"{API_DOMAIN}/balance/claim/data/get", 
                data=data, 
                token=self.access_token,
                userId=str(self.uid)  # 确保user_id是字符串
            )
            
            if response.get("code") == "0":
                if response.get("data"):
                    self.last_updated = time.time()
                    # 返回最新的体重数据（列表中的第一条）
                    return response["data"][0] if response["data"] else None
                else:
                    return None
            
            # 处理API返回的错误
            error_msg = response.get("msg", "Unknown error")
            self.error_state = f"API error: {error_msg}"
            self.error_time = datetime.now().isoformat()
            
            # token失效
            if response.get("code") in ["2000"]:
                self.refresh_access_token(True)
            
            return None
        
        except Exception as err:
            # 保存错误信息
            self.error_state = f"Data fetch error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            raise  # 重新抛出异常让coordinator处理
            
    def own_data(self, rawDataId):
        try:
            # 重置临时错误状态
            self.error_state = None
            self.auth_error = False
            
            # 检查是否需要刷新token
            if not self.refresh_access_token():
                # 刷新失败，抛出异常让coordinator处理
                raise Exception("Token refresh failed")
            
            data = {
                "memberId": str(self.member_id),
                "rawDataId": str(rawDataId)
            }
            response = self._request(
                "POST", 
                f"{API_DOMAIN}/balance/claim/data/own", 
                data=data, 
                token=self.access_token,
                userId=str(self.uid)  # 确保user_id是字符串
            )
            if response.get("code") == "0":
                return True
            
            # 处理API返回的错误
            error_msg = response.get("msg", "Unknown error")
            self.error_state = f"API error: {error_msg}"
            self.error_time = datetime.now().isoformat()
            
            # token失效
            if response.get("code") in ["2000"]:
                self.refresh_access_token(True)
            
            return False
        
        except Exception as err:
            # 保存错误信息
            self.error_state = f"Data fetch error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            raise  # 重新抛出异常让coordinator处理
            
    def get_history(self):
        try:
            # 重置临时错误状态
            self.error_state = None
            self.auth_error = False
            
            # 检查是否需要刷新token
            if not self.refresh_access_token():
                # 刷新失败，抛出异常让coordinator处理
                raise Exception("Token refresh failed")
            
            data = {
                "currentLatestTimestamp": -1,
                "memberId": self.member_id
            }
            response = self._request(
                "POST", 
                f"{API_DOMAIN}/balance/history/data/get", 
                data=data, 
                token=self.access_token,
                userId=str(self.uid)  # 确保user_id是字符串
            )
            if response.get("code") == "0":
                if response.get("data") and response.get("data").get("historyDataBeanList"):
                    self.last_updated = time.time()
                    return response["data"]["historyDataBeanList"][0]
                else:
                    return None
            
            # 处理API返回的错误
            error_msg = response.get("msg", "Unknown error")
            self.error_state = f"API error: {error_msg}"
            self.error_time = datetime.now().isoformat()
            
            # token失效
            if response.get("code") in ["2000"]:
                self.refresh_access_token(True)
            
            return None
        
        except Exception as err:
            # 保存错误信息
            self.error_state = f"Data fetch error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            raise  # 重新抛出异常让coordinator处理
            
            
    def get_detail(self, measureId):
        try:            
            headers = {
                'appId': str(self.appId),
                'sec-ch-ua-platform': '"Android"',
                'timestamp': str(int(time.time() * 1000)),
                'timeZone': 'Asia/Shanghai',
                'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Android WebView";v="138"',
                'sec-ch-ua-mobile': '?1',
                'appVersion': '3.0.1406',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.7204.181 Mobile Safari/537.36lsTech',
                'userId': str(self.uid),
                'LAISIH5': 'LAISIH5',
                'version': 'v1',
                'platform': 'android',
                'Accept': '*/*',
                'X-Requested-With': 'com.lstech.rehealth',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': f"{API_DOMAIN}/h5/h5V3/balance/bodydetail.html?measureId={measureId}&memberId={self.member_id}&userId={self.uid}&deviceType=balance",
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7'
            }
            url = f"{API_DOMAIN}/balance/share/h5/data/share?memberId={self.member_id}&measureId={measureId}&userId={self.uid}"
            res = requests.get(url, headers=headers, timeout=10)

            try:
                response = res.json()
                if response.get("code") == "0":
                    if response.get("data"):
                        self.last_updated = time.time()
                        return response["data"]
                    else:
                        return None

                error_msg = response.get("msg", "Unknown error")
                self.error_state = f"API error: {error_msg}"
                self.error_time = datetime.now().isoformat() 
                return None
            except json.JSONDecodeError:
                self.error_state = "Invalid JSON response"
                self.error_time = datetime.now().isoformat()
                return {"code": "-1", "msg": "Invalid JSON response"}
        except requests.exceptions.RequestException as err:
            self.error_state = f"Network error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            return {"code": "-1", "msg": f"Network error: {str(err)}"}
        except Exception as err:
            self.error_state = f"Unexpected error: {str(err)}"
            self.error_time = datetime.now().isoformat()
            return {"code": "-1", "msg": f"Unexpected error: {str(err)}"}
