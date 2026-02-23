import asyncio
import websockets
import json
import aiohttp

class KiwoomClientKit:
    def __init__(self, host="http://localhost:8082"):
        self.host = host
        self.ws_host = host.replace("http", "ws")

    async def get_balance_snapshot(self, account_no, password=""):
        """최초 잔고 스냅샷 조회 (API)"""
        url = f"{self.host}/api/accounts/balance"
        params = {"accountNo": account_no, "pass": password}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def send_order(self, account_no, stock_code, quantity, price, order_type=1):
        """주문 전송 (API)"""
        url = f"{self.host}/api/orders"
        payload = {
            "accountNo": account_no,
            "stockCode": stock_code,
            "quantity": quantity,
            "price": price,
            "orderType": order_type,
            "quoteType": "00"  # 지정가
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return await resp.json()

    async def subscribe_realtime(self, codes, screen="1000"):
        """실시간 시세 종목 등록 (Server API)"""
        url = f"{self.host}/api/realtime/subscribe"
        params = {"codes": codes, "screen": screen}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    # --- Extended Features ---
    async def get_daily_candles(self, code, date="", stop_date=""):
        """일봉 차트 스마트 페이징 조회 (OPT10081)
           date: 기준일(최신) ex) 20240205
           stop_date: 종료일(과거) ex) 20230101
        """
        url = f"{self.host}/api/market/candles/daily"
        params = {"code": code, "date": date, "stopDate": stop_date}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_minute_candles(self, code, tick=1, stop_time=""):
        """분봉 차트 스마트 페이징 조회 (OPT10080)
           stop_time: 과거 종료시간 ex) 20240201090000
        """
        url = f"{self.host}/api/market/candles/minute"
        params = {"code": code, "tick": tick, "stopTime": stop_time}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_tick_candles(self, code, tick=1, stop_time=""):
        """틱 차트 스마트 페이징 조회 (OPT10079)"""
        url = f"{self.host}/api/market/candles/tick"
        params = {"code": code, "tick": tick, "stopTime": stop_time}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_deposit(self, account_no, password=""):
        """예수금 상세 조회 (OPW00001)"""
        url = f"{self.host}/api/accounts/deposit"
        params = {"accountNo": account_no, "pass": password}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_outstanding_orders(self, account_no, code=""):
        """미체결 내역 조회 (OPT10075)"""
        url = f"{self.host}/api/accounts/orders"
        params = {"accountNo": account_no, "code": code}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_symbol_info(self, code):
        """종목 마스터 정보 조회"""
        url = f"{self.host}/api/market/symbol"
        params = {"code": code}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    # --- System ---
    async def get_server_status(self):
        """서버 상태 및 로그인 여부 조회 (/api/system/status)"""
        try:
            url = f"{self.host}/api/system/status"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    return await resp.json()
        except Exception as e:
            return {"Success": False, "Message": str(e)}

    async def request_login(self):
        """서버에 로그인 창 띄우기 요청 (/api/system/login)"""
        url = f"{self.host}/api/system/login"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

    async def listen_execution(self, callback):
        """체결/잔고 실시간 스트림 (WebSocket)"""
        uri = f"{self.ws_host}/ws/execution"
        while True:
            try:
                async with websockets.connect(uri) as ws:
                    print(f"[Execution WS] Connected to {uri}")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        # data structure: { type: "order"|"balance", timestamp: "...", data: {...} }
                        await callback(data)
            except asyncio.CancelledError:
                print("[Execution WS] Listener cancelled.")
                raise
            except Exception as e:
                print(f"[Execution WS] Error: {e}")
                await asyncio.sleep(5)

    async def listen_realtime(self, callback):
        """틱/호가 실시간 스트림 (WebSocket)"""
        uri = f"{self.ws_host}/ws/realtime"
        while True:
            try:
                async with websockets.connect(uri) as ws:
                    print(f"[Realtime WS] Connected to {uri}")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        # data structure: { type: "tick"|"hoga", code: "...", data: {...} }
                        await callback(data)
            except asyncio.CancelledError:
                print("[Realtime WS] Listener cancelled.")
                raise
            except Exception as e:
                print(f"[Realtime WS] Error: {e}")
                await asyncio.sleep(5)

    async def get_condition_list(self):
        """조건검색식 목록 조회 (/api/conditions)"""
        url = f"{self.host}/api/conditions"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

    async def search_condition(self, index, name):
        """조건검색식 실행
           Returns ApiResponse where Data = {
                "Codes": [...],
                "Stocks": [ { "종목코드": "...", "종목명": "...", ... } ]
           }
        """
        url = f"{self.host}/api/conditions/search"
        params = {"index": index, "name": name}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def start_condition_stream(self, index, name, screen="9001"):
        """조건검색 실시간 등록"""
        url = f"{self.host}/api/conditions/start"
        params = {"index": index, "name": name, "screen": screen}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def stop_condition_stream(self, index, name, screen="9001"):
        """조건검색 실시간 해제"""
        url = f"{self.host}/api/conditions/stop"
        params = {"index": index, "name": name, "screen": screen}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()

    async def get_dashboard_snapshot(self):
        """대시보드 캐시 조회"""
        url = f"{self.host}/api/dashboard"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

    async def refresh_dashboard_snapshot(self):
        """대시보드 데이터 강제 갱신"""
        url = f"{self.host}/api/dashboard/refresh"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

# --- Example Usage ---
#async def my_callback(data):
#    print(data)
#
# kit = KiwoomClientKit()
# asyncio.create_task(kit.listen_execution(my_callback))
