Imports System
Imports System.Collections.Generic

Public Module ApiConsoleGuide
    Private Class EndpointDoc
        Public Property Key As String
        Public Property HttpMethod As String
        Public Property PathTemplate As String
        Public Property Purpose As String
        Public Property RequiredParams As String
        Public Property OptionalParams As String
        Public Property DataContract As String
        Public Property Sample As String
        Public Property Notes As String
    End Class

    Public Sub Print(baseUrl As String)
        Dim uri As New Uri(baseUrl)
        Dim wsBase As String = "ws://localhost:" & uri.Port.ToString()

        Console.WriteLine("")
        Console.WriteLine("================================================================================================================")
        Console.WriteLine(" KIWOOM / CYBOS FULL MANUAL (CONSOLE)")
        Console.WriteLine("================================================================================================================")
        Console.WriteLine("Base URL            : " & baseUrl)
        Console.WriteLine("Realtime WS         : " & wsBase & "/ws/realtime")
        Console.WriteLine("Execution WS        : " & wsBase & "/ws/execution")
        Console.WriteLine("Interactive Help    : " & baseUrl & "/help")
        Console.WriteLine("Machine JSON Manual : " & baseUrl & "/api/help")
        Console.WriteLine("")

        Console.WriteLine("[0] Global Rules")
        Console.WriteLine("  - Every REST response envelope:")
        Console.WriteLine("    { ""Success"": bool, ""Message"": string, ""Data"": object|array|null }")
        Console.WriteLine("  - Parser order: Success -> Message -> Data")
        Console.WriteLine("  - If Success=false: treat Message as error reason; Data may be null")
        Console.WriteLine("  - Key principle: implement parser by endpoint Data contract below")
        Console.WriteLine("")

        PrintWebSocketContracts(wsBase, baseUrl)

        Console.WriteLine("[2] REST Endpoint Contracts (All)")
        Console.WriteLine("  The following list is intended as a complete integration contract.")
        Console.WriteLine("")

        Dim docs = BuildEndpointDocs(baseUrl)
        Dim i As Integer = 1
        For Each d As EndpointDoc In docs
            Console.WriteLine(String.Format("  [{0:00}] {1} {2}{3}", i, d.HttpMethod, baseUrl, d.PathTemplate))
            Console.WriteLine("       key            : " & d.Key)
            Console.WriteLine("       purpose        : " & d.Purpose)
            Console.WriteLine("       required query : " & d.RequiredParams)
            Console.WriteLine("       optional query : " & d.OptionalParams)
            Console.WriteLine("       data contract  : " & d.DataContract)
            Console.WriteLine("       sample success : " & d.Sample)
            Console.WriteLine("       notes          : " & d.Notes)
            Console.WriteLine("")
            i += 1
        Next

        Console.WriteLine("[3] High-Value Ready-Made Checks")
        Console.WriteLine("  A) 000660 candle volume check (target >= 900)")
        Console.WriteLine("     - " & baseUrl & "/api/market/candles/daily?code=000660&date=20260209&stopDate=20180101")
        Console.WriteLine("     - " & baseUrl & "/api/market/candles/minute?code=000660&tick=1&stopTime=20180101090000")
        Console.WriteLine("     - " & baseUrl & "/api/market/candles/tick?code=000660&tick=1&stopTime=20180101090000")
        Console.WriteLine("     - pass rule: Success=true and Data.Count >= 900")

        Dim dailyhdr As String = "일자: 20260209, 시가:898000,고가:899000,저가:873000,현재가:887000,종가:887000,거래량:4228584"
        Dim mintickhdr As String = "체결시간:20260220153000,시가:949000,고가:949000,저가:949000,현재가:949000,거래량:427640"

        Console.WriteLine("          - daily  header ==>  " & dailyhdr)
        Console.WriteLine("          - minute and tick header  ==> " & mintickhdr)

        Console.WriteLine("  B) condition flow check")
        Console.WriteLine("     - " & baseUrl & "/api/conditions")
        Console.WriteLine("     - " & baseUrl & "/api/conditions/search?name={NameFromList}&index={IndexFromList}")
        Console.WriteLine("     - pass rule: Data.Codes exists and Data.Stocks exists")
        Console.WriteLine("")

        Console.WriteLine("[4] Order Request Body Contract")
        Console.WriteLine("  POST " & baseUrl & "/api/orders")
        Console.WriteLine("  {")
        Console.WriteLine("    ""AccountNo"": ""1234567890"",   // string")
        Console.WriteLine("    ""StockCode"": ""005930"",      // string")
        Console.WriteLine("    ""OrderType"": 1,              // int")
        Console.WriteLine("    ""Quantity"": 1,               // int")
        Console.WriteLine("    ""Price"": 70000,             // int")
        Console.WriteLine("    ""QuoteType"": ""00""          // string")
        Console.WriteLine("  }")
        Console.WriteLine("")

        Console.WriteLine("[5] Cybos Reference")
        Console.WriteLine("  - connection check : Cybos.IsCybosConnected()")
        Console.WriteLine("  - candle request   : Cybos.DownloadCandlesByPeriod(code,timeframe,fromDate,toDate)")
        Console.WriteLine("  - timeframe ex     : m1, m3, T1, D1")
        Console.WriteLine("  - date format      : yyyyMMdd or yyyyMMddHHmm")
        Console.WriteLine("")

        Console.WriteLine("[6] Minimal Production Integration Sequence")
        Console.WriteLine("  1) GET /api/auth/login")
        Console.WriteLine("  2) GET /api/status (must be IsLoggedIn=true)")
        Console.WriteLine("  3) REST data pull endpoints as needed")
        Console.WriteLine("  4) open /ws/realtime, then call /api/realtime/subscribe")
        Console.WriteLine("  5) parse realtime by type field")
        Console.WriteLine("  6) call /api/realtime/unsubscribe before shutdown")

        Console.WriteLine("================================================================================================================")
        Console.WriteLine("")
    End Sub

    Private Sub PrintWebSocketContracts(wsBase As String, baseUrl As String)
        Console.WriteLine("[1] WebSocket Contracts")
        Console.WriteLine("  A) Realtime stream")
        Console.WriteLine("     connect: " & wsBase & "/ws/realtime")
        Console.WriteLine("     subscribe trigger: " & baseUrl & "/api/realtime/subscribe?codes=005930;000660&screen=1000")
        Console.WriteLine("     payload: { ""type"": ""tick|hoga|condition"", ""code"": string, ""timestamp"": ""yyyyMMddHHmmss"", ""data"": object }")
        Console.WriteLine("     tick data typical keys: time,current_price,diff,rate,volume,cum_volume,open,high,low,intensity")
        Console.WriteLine("     hoga data typical keys: total_ask_vol,total_bid_vol,ask_price_1..5,ask_vol_1..5,bid_price_1..5,bid_vol_1..5")
        Console.WriteLine("     condition data keys    : condition_name, condition_index, state(enter|exit)")
        Console.WriteLine("  B) Execution stream")
        Console.WriteLine("     connect: " & wsBase & "/ws/execution")
        Console.WriteLine("     payload: { ""type"": ""order|balance|dashboard"", ""timestamp"": ""yyyyMMddHHmmss"", ""data"": object }")
        Console.WriteLine("     order/balance data: chejan fid-key dictionary strings")
        Console.WriteLine("     dashboard data   : AccountSnapshot object")
        Console.WriteLine("     stop realtime reg: " & baseUrl & "/api/realtime/unsubscribe?screen=1000&code=ALL")
        Console.WriteLine("")
    End Sub

    Private Function BuildEndpointDocs(baseUrl As String) As List(Of EndpointDoc)
        Return New List(Of EndpointDoc) From {
            New EndpointDoc With {
                .Key = "status",
                .HttpMethod = "GET",
                .PathTemplate = "/api/status",
                .Purpose = "Get login/session status",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "{ IsLoggedIn:Boolean, AccountNo:String, ServerName:String }",
                .Sample = "{ Success:true, Data:{ IsLoggedIn:true, AccountNo:'8118057011', ServerName:'...' } }",
                .Notes = "Use as health-check before all other requests"
            },
            New EndpointDoc With {
                .Key = "auth_login",
                .HttpMethod = "GET",
                .PathTemplate = "/api/auth/login",
                .Purpose = "Trigger Kiwoom login",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "{ loggedIn:Boolean, account:String }",
                .Sample = "{ Success:true, Data:{ loggedIn:true, account:'8118057011' } }",
                .Notes = "Equivalent route exists: /api/system/login"
            },
            New EndpointDoc With {
                .Key = "system_status",
                .HttpMethod = "GET",
                .PathTemplate = "/api/system/status",
                .Purpose = "Status alias",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "same as /api/status",
                .Sample = "{ Success:true, Data:{ IsLoggedIn:true,... } }",
                .Notes = "Use one of status routes consistently"
            },
            New EndpointDoc With {
                .Key = "conditions_load",
                .HttpMethod = "GET",
                .PathTemplate = "/api/conditions",
                .Purpose = "Load condition formula list",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "Data = ConditionInfo[] where ConditionInfo={ Index:Int32, Name:String }",
                .Sample = "{ Success:true, Data:[{ Index:22, Name:'가치투자-배지고려함' }, ...] }",
                .Notes = "Client should cache Index+Name mapping"
            },
            New EndpointDoc With {
                .Key = "conditions_search",
                .HttpMethod = "GET",
                .PathTemplate = "/api/conditions/search?name={name}&index={index}",
                .Purpose = "Execute one condition and get matched codes/details",
                .RequiredParams = "name,index",
                .OptionalParams = "none",
                .DataContract = "Data={ Codes:String[], Stocks:Object[] }",
                .Sample = "{ Success:true, Data:{ Codes:['005930','000660'], Stocks:[{ '종목코드':'005930', ...}] } }",
                .Notes = "Stocks field keys follow broker TR output; parse as dictionary/object"
            },
            New EndpointDoc With {
                .Key = "conditions_stream_start",
                .HttpMethod = "GET",
                .PathTemplate = "/api/conditions/start?name={name}&index={index}&screen=9001",
                .Purpose = "Start condition realtime stream",
                .RequiredParams = "name,index",
                .OptionalParams = "screen(default=9001)",
                .DataContract = "Data=null",
                .Sample = "{ Success:true, Message:'Condition stream started: ...' }",
                .Notes = "Realtime events delivered on /ws/realtime with type='condition'"
            },
            New EndpointDoc With {
                .Key = "conditions_stream_stop",
                .HttpMethod = "GET",
                .PathTemplate = "/api/conditions/stop?name={name}&index={index}&screen=9001",
                .Purpose = "Stop condition realtime stream",
                .RequiredParams = "name,index",
                .OptionalParams = "screen(default=9001)",
                .DataContract = "Data=null",
                .Sample = "{ Success:true, Message:'Condition stream stopped: ...' }",
                .Notes = "Stop when strategy unsubscribes"
            },
            New EndpointDoc With {
                .Key = "dashboard_cached",
                .HttpMethod = "GET",
                .PathTemplate = "/api/dashboard",
                .Purpose = "Get cached account dashboard snapshot",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "AccountSnapshot object",
                .Sample = "{ Success:true, Data:{ AccountNo:'...', Holdings:[...], Outstanding:[...] } }",
                .Notes = "Can return 404-like error if snapshot not ready"
            },
            New EndpointDoc With {
                .Key = "dashboard_refresh",
                .HttpMethod = "GET",
                .PathTemplate = "/api/dashboard/refresh",
                .Purpose = "Force refresh account dashboard",
                .RequiredParams = "none",
                .OptionalParams = "none",
                .DataContract = "AccountSnapshot object",
                .Sample = "{ Success:true, Data:{ TotalPurchase:..., TotalEvaluation:... } }",
                .Notes = "Requires logged-in account"
            },
            New EndpointDoc With {
                .Key = "accounts_balance",
                .HttpMethod = "GET",
                .PathTemplate = "/api/accounts/balance?accountNo={acc}&pass={pw}",
                .Purpose = "Query holdings rows",
                .RequiredParams = "accountNo",
                .OptionalParams = "pass(uses config default when empty)",
                .DataContract = "Data=Array<Dictionary<String,String>>",
                .Sample = "{ Success:true, Data:[{ '종목코드':'005930', '보유수량':'10', ...}] }",
                .Notes = "Field names are broker TR keys; parse as map"
            },
            New EndpointDoc With {
                .Key = "accounts_deposit",
                .HttpMethod = "GET",
                .PathTemplate = "/api/accounts/deposit?accountNo={acc}&pass={pw}",
                .Purpose = "Query deposit rows",
                .RequiredParams = "accountNo",
                .OptionalParams = "pass",
                .DataContract = "Data=Array<Dictionary<String,String>>",
                .Sample = "{ Success:true, Data:[{ '주문가능금액':'...', ...}] }",
                .Notes = "Parse needed keys by your account dashboard logic"
            },
            New EndpointDoc With {
                .Key = "accounts_orders",
                .HttpMethod = "GET",
                .PathTemplate = "/api/accounts/orders?accountNo={acc}&code={optional}",
                .Purpose = "Query outstanding orders",
                .RequiredParams = "accountNo",
                .OptionalParams = "code",
                .DataContract = "Data=Array<Dictionary<String,String>>",
                .Sample = "{ Success:true, Data:[{ '주문번호':'...', '미체결수량':'...', ...}] }",
                .Notes = "When code omitted, returns all symbols"
            },
            New EndpointDoc With {
                .Key = "candles_daily",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/candles/daily?code={code}&date=yyyyMMdd&stopDate=yyyyMMdd",
                .Purpose = "Daily candle history",
                .RequiredParams = "code,date,stopDate",
                .OptionalParams = "none",
                .DataContract = "Data=Array<CandleRowMap>",
                .Sample = "{ Success:true, Data:[{ '일자':'20260209','시가':'...','고가':'...','저가':'...','현재가':'...','거래량':'...' }] }",
                .Notes = "For 900 rows, widen date range by older stopDate"
            },
            New EndpointDoc With {
                .Key = "candles_minute",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/candles/minute?code={code}&tick=1&stopTime=yyyyMMddHHmmss",
                .Purpose = "Minute candle history",
                .RequiredParams = "code,tick,stopTime",
                .OptionalParams = "none",
                .DataContract = "Data=Array<CandleRowMap>",
                .Sample = "{ Success:true, Data:[{ '체결시간':'20260209152000','시가':'...','고가':'...','저가':'...','현재가':'...','거래량':'...' }] }",
                .Notes = "tick parameter = minute unit (1,3,5...)"
            },
            New EndpointDoc With {
                .Key = "candles_tick",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/candles/tick?code={code}&tick=60&stopTime=yyyyMMddHHmmss",
                .Purpose = "Tick candle history",
                .RequiredParams = "code,tick,stopTime",
                .OptionalParams = "none",
                .DataContract = "Data=Array<CandleRowMap>",
                .Sample = "{ Success:true, Data:[{ '체결시간':'20260220153000','시가':'...','고가':'...','저가':'...','현재가':'...','거래량':'...' }] }",
                .Notes = "tick parameter = tick interval"
            },
            New EndpointDoc With {
                .Key = "market_symbol",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/symbol?code={code}",
                .Purpose = "Master symbol metadata",
                .RequiredParams = "code",
                .OptionalParams = "none",
                .DataContract = "Data={ code:String, name:String, last_price:Int32, state:String }",
                .Sample = "{ Success:true, Data:{ code:'005930', name:'삼성전자', last_price:70000, state:'...' } }",
                .Notes = "Good for validation before candle/order"
            },
            New EndpointDoc With {
                .Key = "rt_subscribe",
                .HttpMethod = "GET",
                .PathTemplate = "/api/realtime/subscribe?codes={005930;000660}&screen=1000&fids={...}",
                .Purpose = "Register realtime symbols",
                .RequiredParams = "codes",
                .OptionalParams = "screen(default=1000), fids(default server set)",
                .DataContract = "Data=null",
                .Sample = "{ Success:true, Message:'Subscribed: 005930;000660', Data:null }",
                .Notes = "Open /ws/realtime before/after; events start when broker feed arrives"
            },
            New EndpointDoc With {
                .Key = "rt_unsubscribe",
                .HttpMethod = "GET",
                .PathTemplate = "/api/realtime/unsubscribe?screen=1000&code=ALL",
                .Purpose = "Remove realtime registration",
                .RequiredParams = "none",
                .OptionalParams = "screen(default=ALL), code(default=ALL)",
                .DataContract = "Data={ screen:String, code:String }",
                .Sample = "{ Success:true, Message:'Realtime unsubscribed', Data:{ screen:'1000', code:'ALL' } }",
                .Notes = "Use before reconnect / shutdown"
            },
                        New EndpointDoc With {
                .Key = "program_trade_time",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/program/time?code={code}&exchange=A",
                .Purpose = "종목별 프로그램매매 추이 (시간대별, 당일)",
                .RequiredParams = "code",
                .OptionalParams = "exchange (A=전체, K=KRX, N=NXT, default=A)",
                .DataContract = "Data = Array<{ 시간, 현재가, 대비부호, 전일대비, 대비율, 거래량, 프로그램매수수량, 프로그램매도수량, 프로그램순매수수량, 프로그램순매수수량증감, 프로그램매수금액_천원, 프로그램매도금액_천원, 프로그램순매수금액_천원, 프로그램순매수금액증감_천원 }>",
                .Sample = "{ Success:true, Data:[{ 시간:1430, 현재가:70000, 프로그램순매수수량:12500, ... }] }",
                .Notes = "연속 조회 지원. 금액 단위: 천원. CybosPlus CpSvrNew8119 기반."
            },
            New EndpointDoc With {
                .Key = "program_trade_daily",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/program/daily?code={code}&period=2",
                .Purpose = "종목별 프로그램매매 추이 (일자별)",
                .RequiredParams = "code",
                .OptionalParams = "period (0=최근5일, 1=한달, 2=3개월, 3=6개월, default=2)",
                .DataContract = "Data = Array<{ 일자, 현재가, 전일대비, 대비율, 거래량, 매도량, 매수량, 순매수증감수량, 순매수누적수량, 매도금액_만원, 매수금액_만원, 순매수증감금액_만원, 순매수누적금액_만원 }>",
                .Sample = "{ Success:true, Data:[{ 일자:20260223, 현재가:70000, 순매수누적수량:345000, ... }] }",
                .Notes = "단건 조회. 금액 단위: 만원. CybosPlus CpSvrNew8119Day 기반."
            },
            New EndpointDoc With {
                .Key = "program_trade_rt_subscribe",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/program/subscribe?codes={005930;000660}",
                .Purpose = "프로그램매매 실시간 구독 시작",
                .RequiredParams = "codes (;구분)",
                .OptionalParams = "none",
                .DataContract = "Data = null",
                .Sample = "{ Success:true, Message:'프로그램매매 실시간 구독: 005930,000660' }",
                .Notes = "실시간 데이터는 /ws/realtime 으로 type='program_trade'로 수신. CpSvr8119SCnld 기반."
            },
            New EndpointDoc With {
                .Key = "program_trade_rt_unsubscribe",
                .HttpMethod = "GET",
                .PathTemplate = "/api/market/program/unsubscribe?codes=ALL",
                .Purpose = "프로그램매매 실시간 구독 해지",
                .RequiredParams = "none",
                .OptionalParams = "codes (;구분, 생략 또는 ALL=전체해지)",
                .DataContract = "Data = null",
                .Sample = "{ Success:true, Message:'프로그램매매 전체 구독 해지' }",
                .Notes = "종료 전 반드시 해지 권장."
            },
            New EndpointDoc With {
                .Key = "orders_post",
                .HttpMethod = "POST",
                .PathTemplate = "/api/orders",
                .Purpose = "Send order",
                .RequiredParams = "JSON body: AccountNo, StockCode, OrderType, Quantity, Price, QuoteType",
                .OptionalParams = "none",
                .DataContract = "Data varies by broker return",
                .Sample = "{ Success:true, Message:'Order Sent', Data:'Order Sent' }",
                .Notes = "Execution details are pushed via /ws/execution"
            }
        }
    End Function
End Module
