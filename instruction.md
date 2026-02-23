# New KiwoomServer (Immutable Edition)

이 폴더(`e:\server\kiwoom32`)에는 **"절대 건드리지 않아도 되는"** 완전한 형태의 키움 API 서버가 구축되어 있습니다.
서버는 오직 하부 인프라(로그인, TR, 소켓 중계)만 담당하며, 모든 비즈니스 로직은 파이썬 클라이언트에서 구현하면 됩니다.

## 1. 서버 아키텍처

- **KiwoomApiService.vb**: REST API (로그인, 계좌조회, 주문, 조건검색) 담당. TR 요청만 처리하며 실시간 로직은 없습니다.
- **RealtimeDataService.vb**: `/ws/realtime` 소켓 담당. 주식체결(Tick) 및 호가(Hoga) 데이터를 표준 JSON으로 송출합니다.
- **ExecutionHub.vb**: `/ws/execution` 소켓 담당. **주문체결, 잔고변경, 미체결정보**를 표준 JSON으로 즉시 송출합니다. (가장 중요)
- **WebApiServer.vb**: HTTP/WebSocket 라우팅을 담당합니다.

## 2. 빌드 및 실행 방법

이 서버는 **32비트(x86)** 환경에서 실행되어야 합니다. (키움 API 제약)

### 필수 요구사항
- .NET Framework 4.8
- MSBuild (Visual Studio Build Tools)
- NuGet.exe (패키지 복원용)

### 빌드 단계 (터미널)

1. **NuGet 패키지 복원**
   ```cmd
   nuget install packages.config -OutputDirectory packages
   ```

2. **빌드**
   ```cmd
   "C:\Windows\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe" KiwoomServer.vbproj /p:Configuration=Debug /p:Platform=AnyCPU
   ```
   *(참고: 최신 Visual Studio가 설치되어 있다면 `MSBuild.exe` 위치가 다를 수 있습니다. 예: `C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe`)*

3. **실행**
   ```cmd
   bin\Debug\KiwoomServer.exe
   ```
   - 실행 시 트레이 아이콘영역에 Open API 아이콘이 나타나며 로그인이 진행됩니다.
   - 콘솔 창에 `Server is ready at http://localhost:8082`가 뜨면 성공입니다.

## 3. 검증 및 테스트 (Tester UI)

서버가 정상 작동하는지 확인하기 위해 **Tester UI**를 제공합니다.

1. 필수 라이브러리 설치:
   ```cmd
   pip install aiohttp websockets
   ```
2. 실행:
   ```cmd
   python tester_ui.py
   ```
3. 기능 확인:
   - **[GET] 로그인 상태**: 버튼 클릭으로 서버 연결 확인.
   - **[GET] 계좌 잔고**: 계좌 번호와 잔고 JSON 출력 확인.
   - **실시간 구독**: 종목코드 입력 후 "시작" -> 틱 데이터가 로그창에 실시간으로 흐르는지 확인.

## 4. 파이썬 연결 방법 (Client Kit)

동봉된 `client_kit.py`를 사용하면 즉시 연결할 수 있습니다.

```python
from client_kit import KiwoomClientKit

kit = KiwoomClientKit()

# 1. 잔고 스냅샷 조회
balance = await kit.get_balance_snapshot(account_no, password)

# 2. 실시간 체결/잔고 수신 (이벤트 드리븐)
async def on_execution_event(data):
    # data = { "type": "order"|"balance", "data": { ... } }
    print("내 계좌 변동:", data)

asyncio.create_task(kit.listen_execution(on_execution_event))
```

## 4. 데이터 포맷 (표준)

모든 소켓 메시지는 다음 형식을 따릅니다.

```json
{
  "type": "tick" | "hoga" | "order" | "balance",
  "code": "005930",  // (order/balance인 경우 없을 수 있음)
  "timestamp": "20240205120000",
  "data": {
      "current_price": 70000,
      "volume": 100,
      ...
  }
}
```

이제 서버 코드는 잊으십시오. 오직 `client_kit.py`를 통해 파이썬에서 자유롭게 매매 시스템을 구축/수정하시면 됩니다.
