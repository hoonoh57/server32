Imports System.Diagnostics
Imports System.IO
Imports System.Text
Imports System.Threading.Tasks
Imports Newtonsoft.Json
Imports Newtonsoft.Json.Linq
Imports WebSocketSharp.Net
Imports WebSocketSharp.Server

Public Class WebApiServer
    Private ReadOnly _apiService As KiwoomApiService
    Private ReadOnly _realtimeService As RealtimeDataService
    Private ReadOnly _execHub As ExecutionHub
    Private ReadOnly _logger As SimpleLogger
    Private _httpServer As HttpServer
    Private _baseUrl As String = "http://localhost:8082"
    Private Const DefaultRealtimeFids As String = "10;11;12;13;15;16;17;18;20;41;42;43;44;45;51;52;53;54;55;61;62;63;64;65;71;72;73;74;75;121;125;228"

    Private _stockCode As CPUTILLib.CpStockCode = Nothing
    Private ReadOnly _stockCodeLock As New Object()

    Public Sub New(apiSvc As KiwoomApiService, rtSvc As RealtimeDataService, execHub As ExecutionHub, logger As SimpleLogger)
        _apiService = apiSvc
        _realtimeService = rtSvc
        _execHub = execHub
        _logger = logger
    End Sub

    Private Shared Function ParseIntQuery(req As HttpListenerRequest, key As String, defaultValue As Integer) As Integer
        Dim raw As String = req.QueryString(key)
        If String.IsNullOrWhiteSpace(raw) Then Return defaultValue
        Dim parsed As Integer
        If Integer.TryParse(raw, parsed) Then Return parsed
        Return defaultValue
    End Function

    Public Function GetStockCode(stockName As String) As String
        If String.IsNullOrWhiteSpace(stockName) Then Return ""

        Try
            SyncLock _stockCodeLock
                If _stockCode Is Nothing Then
                    _stockCode = New CPUTILLib.CpStockCode()
                End If

                Dim code As String = _stockCode.NameToCode(stockName.Trim())
                If String.IsNullOrWhiteSpace(code) Then Return ""

                If code.StartsWith("A", StringComparison.OrdinalIgnoreCase) AndAlso code.Length > 1 Then
                    Return code.Substring(1)
                End If

                Return code
            End SyncLock
        Catch ex As Exception
            Debug.Print("[GetStockCode] CpStockCode 실패: " & ex.Message)
            Return ""
        End Try
    End Function

    Public Sub Start(url As String)
        Try
            _baseUrl = url.TrimEnd("/"c)
            Dim port As Integer = New Uri(url).Port
            _httpServer = New HttpServer(port)

            _httpServer.AddWebSocketService(Of RealtimeWebSocketBehavior)(
                "/ws/realtime",
                Function() New RealtimeWebSocketBehavior With {.Service = _realtimeService})
            _httpServer.AddWebSocketService(Of ExecutionWebSocketBehavior)(
                "/ws/execution",
                Function() New ExecutionWebSocketBehavior With {.Hub = _execHub})

            AddHandler _httpServer.OnGet, AddressOf ProcessApiRequest
            AddHandler _httpServer.OnPost, AddressOf ProcessApiRequest
            AddHandler _httpServer.OnOptions, AddressOf ProcessApiRequest

            _httpServer.Start()
            _logger.Info($"KiwoomServer Listening on {url}")
        Catch ex As Exception
            _logger.Errors("CRITICAL: Failed to start web server. Port might be in use. Error: " & ex.Message)
            Throw
        End Try
    End Sub

    Private Sub ProcessApiRequest(sender As Object, e As HttpRequestEventArgs)
        Dim req As HttpListenerRequest = e.Request
        Dim res As HttpListenerResponse = e.Response
        Dim path As String = req.Url.AbsolutePath.ToLower()

        _logger.Info($"[API] {req.HttpMethod} {path}")

        Try
            res.Headers.Add("Access-Control-Allow-Origin", "*")
            res.Headers.Add("Access-Control-Allow-Headers", "content-type")
            res.Headers.Add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        Catch ex As ObjectDisposedException
            Return
        End Try

        If req.HttpMethod = "OPTIONS" Then
            Try : res.StatusCode = 204 : res.Close() : Catch : End Try
            Return
        End If

        If req.HttpMethod = "GET" AndAlso (path = "/help" OrElse path = "/help/realtime") Then
            Try
                Dim wsBase = $"ws://localhost:{New Uri(_baseUrl).Port}"
                Dim html = ApiHelpDocs.BuildHelpHtml(_baseUrl, wsBase, DefaultRealtimeFids)
                WriteRawResponse(res, "text/html; charset=utf-8", Encoding.UTF8.GetBytes(html), 200)
            Catch ex As ObjectDisposedException
                _logger.Warn("[HTTP] Help page: client disconnected")
            End Try
            Return
        End If

        Dim resp As ApiResponse = Nothing

        Try
            If req.HttpMethod = "GET" Then
                Select Case path
                    Case "/api/help"
                        Dim wsBase = $"ws://localhost:{New Uri(_baseUrl).Port}"
                        resp = ApiResponse.Ok(ApiHelpDocs.BuildApiHelp(_baseUrl, wsBase, DefaultRealtimeFids))

                    Case "/api/auth/login", "/api/system/login"
                        resp = Resolve(_apiService.LoginAsync())

                    Case "/api/status", "/api/system/status"
                        resp = ApiResponse.Ok(_apiService.GetStatus())

                    Case "/api/conditions"
                        resp = Resolve(_apiService.LoadConditionsAsync())

                    Case "/api/conditions/search"
                        Dim nm As String = req.QueryString("name")
                        Dim ix As Integer = ParseIntQuery(req, "index", 0)
                        If String.IsNullOrWhiteSpace(nm) Then
                            resp = ApiResponse.Err("name is required", 400)
                        Else
                            resp = Resolve(_apiService.SearchConditionAsync(nm, ix))
                        End If

                    Case "/api/conditions/start"
                        Dim nm As String = req.QueryString("name")
                        Dim ix As Integer = ParseIntQuery(req, "index", 0)
                        Dim scr As String = If(req.QueryString("screen"), "9001")
                        If String.IsNullOrWhiteSpace(nm) Then
                            resp = ApiResponse.Err("name is required", 400)
                        Else
                            resp = Resolve(_apiService.StartConditionStreamAsync(nm, ix, scr))
                        End If

                    Case "/api/conditions/stop"
                        Dim nm As String = req.QueryString("name")
                        Dim ix As Integer = ParseIntQuery(req, "index", 0)
                        Dim scr As String = If(req.QueryString("screen"), "9001")
                        If String.IsNullOrWhiteSpace(nm) Then
                            resp = ApiResponse.Err("name is required", 400)
                        Else
                            resp = _apiService.StopConditionStream(nm, ix, scr)
                        End If

                    Case "/api/dashboard"
                        resp = _apiService.GetDashboardSnapshot()

                    Case "/api/dashboard/refresh"
                        resp = Resolve(_apiService.RefreshDashboardDataAsync())

                    Case "/api/accounts/balance"
                        Dim acc = req.QueryString("accountNo")
                        Dim pw = req.QueryString("pass")
                        resp = Resolve(_apiService.GetAccountBalanceAsync(acc, pw))

                    Case "/api/accounts/deposit"
                        Dim acc = req.QueryString("accountNo")
                        Dim pw = req.QueryString("pass")
                        resp = Resolve(_apiService.GetDepositInfoAsync(acc, pw))

                    Case "/api/accounts/orders"
                        Dim acc = req.QueryString("accountNo")
                        Dim code = req.QueryString("code")
                        resp = Resolve(_apiService.GetOutstandingOrdersAsync(acc, code))

                    Case "/api/market/candles/daily"
                        Dim code = req.QueryString("code")
                        Dim dt = req.QueryString("date")
                        If String.IsNullOrEmpty(dt) Then dt = DateTime.Now.ToString("yyyyMMdd")
                        Dim stopDate = req.QueryString("stopDate")
                        If String.IsNullOrEmpty(stopDate) Then stopDate = "20200101"
                        resp = Resolve(_apiService.GetDailyCandlesAsync(code, dt, stopDate))

                    Case "/api/market/candles/minute"
                        Dim code = req.QueryString("code")
                        Dim tick = If(req.QueryString("tick"), "1")
                        Dim stopTime = req.QueryString("stopTime")
                        If String.IsNullOrEmpty(stopTime) Then
                            stopTime = Util.GetAdjustedPreviousDate & "140000"
                        End If
                        resp = Resolve(_apiService.GetMinuteCandlesAsync(code, CInt(tick), stopTime))

                    Case "/api/market/candles/tick"
                        Dim code = req.QueryString("code")
                        Dim tick = If(req.QueryString("tick"), "1")
                        Dim stopTime = req.QueryString("stopTime")
                        If String.IsNullOrEmpty(stopTime) Then stopTime = DateTime.Now.AddDays(-1).ToString("yyyyMMdd") & "090000"
                        resp = Resolve(_apiService.GetTickCandlesAsync(code, CInt(tick), stopTime))

                    Case "/api/market/symbol"
                        Dim code = req.QueryString("code")
                        Dim name = _apiService.GetMasterName(code)
                        Dim last = _apiService.GetMasterLastPrice(code)
                        Dim state = _apiService.GetMasterState(code)
                        resp = ApiResponse.Ok(New With {.code = code, .name = name, .last_price = last, .state = state})

                    Case "/api/market/name_to_code"
                        Dim stockName As String = req.QueryString("name")
                        If String.IsNullOrEmpty(stockName) Then
                            resp = ApiResponse.Err("name 파라미터 필요")
                        Else
                            Dim code As String = GetStockCode(stockName.Trim())
                            If code <> "" Then
                                resp = ApiResponse.Ok(New With {.code = code, .name = stockName.Trim()})
                            Else
                                resp = ApiResponse.Err($"'{stockName}' 종목코드 미발견")
                            End If
                        End If

                    Case "/api/market/program/time"
                        Dim code = req.QueryString("code")
                        Dim exchange = req.QueryString("exchange")
                        If String.IsNullOrEmpty(exchange) Then exchange = "A"
                        If String.IsNullOrEmpty(code) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Resolve(_apiService.GetProgramTradeByTimeAsync(code, exchange))
                        End If

                    Case "/api/market/program/daily"
                        Dim code = req.QueryString("code")
                        Dim period = req.QueryString("period")
                        If String.IsNullOrEmpty(period) Then period = "2"
                        If String.IsNullOrEmpty(code) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Resolve(_apiService.GetProgramTradeByDayAsync(code, period))
                        End If

                    Case "/api/market/program/subscribe"
                        Dim codesRaw = req.QueryString("codes")
                        If String.IsNullOrEmpty(codesRaw) Then
                            resp = ApiResponse.Err("codes required", 400)
                        Else
                            Dim codes = codesRaw.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                            resp = Resolve(_apiService.SubscribeProgramTradeAsync(codes))
                        End If

                    Case "/api/market/program/unsubscribe"
                        Dim codesRaw = req.QueryString("codes")
                        Dim codes As String()
                        If String.IsNullOrEmpty(codesRaw) Then
                            codes = New String() {"ALL"}
                        Else
                            codes = codesRaw.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                        End If
                        resp = Resolve(_apiService.UnsubscribeProgramTradeAsync(codes))

                    Case "/api/cybos/trade-strength-series"
                        Dim tsCode = req.QueryString("code")
                        Dim tsCount = ParseIntQuery(req, "count", 150)
                        If String.IsNullOrEmpty(tsCode) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Resolve(_apiService.GetTradeStrengthSeriesAsync(tsCode.Trim(), tsCount))
                        End If

                    Case "/api/cybos/marketeye/supply"
                        Dim codesRaw2 = req.QueryString("codes")
                        If String.IsNullOrEmpty(codesRaw2) Then
                            resp = ApiResponse.Err("codes required (semicolon separated)", 400)
                        Else
                            Dim codeArr = codesRaw2.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                            resp = Resolve(_apiService.GetMarketEyeSupplyAsync(codeArr))
                        End If

                    Case "/api/cybos/member/top5"
                        Dim mCode = req.QueryString("code")
                        If String.IsNullOrEmpty(mCode) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Resolve(_apiService.GetStockMemberTop5Async(mCode.Trim()))
                        End If

                    Case "/api/cybos/member/batch"
                        Dim bCodesRaw = req.QueryString("codes")
                        If String.IsNullOrEmpty(bCodesRaw) Then
                            resp = ApiResponse.Err("codes required", 400)
                        Else
                            Dim bCodes = bCodesRaw.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                            resp = Resolve(_apiService.GetStockMemberBatchAsync(bCodes))
                        End If

                    Case "/api/cybos/investor/trend"
                        Dim investType = ParseIntQuery(req, "type", 2)
                        Dim mktType = If(req.QueryString("market"), "0")
                        Dim valType = If(req.QueryString("value"), "0")
                        Dim srtOrder = If(req.QueryString("sort"), "0")
                        resp = Resolve(_apiService.GetInvestorTrendAsync(investType, mktType, valType, srtOrder))

                    Case "/api/cybos/keyframe/capture"
                        Dim kfCode = req.QueryString("code")
                        If String.IsNullOrEmpty(kfCode) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Resolve(_apiService.CaptureKeyframeAsync(kfCode.Trim()))
                        End If

                    Case "/api/realtime/subscribe"
                        Dim codes = req.QueryString("codes")
                        Dim screen = If(req.QueryString("screen"), "1000")
                        Dim fids = If(req.QueryString("fids"), DefaultRealtimeFids)
                        If String.IsNullOrEmpty(codes) Then
                            resp = ApiResponse.Err("codes required")
                        Else
                            _realtimeService.Subscribe(screen, codes, fids, "0")
                            resp = ApiResponse.Ok(Nothing, $"Subscribed: {codes}")
                        End If

                    Case "/api/realtime/unsubscribe"
                        Dim code = If(req.QueryString("code"), "ALL")
                        Dim screen = If(req.QueryString("screen"), "ALL")
                        _realtimeService.Unsubscribe(screen, code)
                        resp = ApiResponse.Ok(New With {.screen = screen, .code = code}, "Realtime unsubscribed")

                    Case Else
                        resp = ApiResponse.Err("Not Found", 404)
                End Select

            ElseIf req.HttpMethod = "POST" Then
                Using r As New StreamReader(CType(req.InputStream, Stream), Encoding.UTF8)
                    Dim body As String = r.ReadToEnd()

                    If path = "/api/orders" Then
                        Dim orq = JsonConvert.DeserializeObject(Of OrderRequest)(body)
                        resp = Resolve(_apiService.SendOrderAsync(orq))

                    ElseIf path = "/api/auth/login" Then
                        resp = Resolve(_apiService.LoginAsync())

                    ElseIf path = "/api/stock-pool/symbols/resolve" Then
                        Dim request = JsonConvert.DeserializeObject(Of StockPoolResolveRequest)(body)
                        Dim repository As New StockPoolRepository(_logger)
                        resp = repository.ResolveSymbols(request)

                    ElseIf path = "/api/stock-pool/cohorts" Then
                        Dim request = JsonConvert.DeserializeObject(Of StockPoolCohortCreateRequest)(body)
                        Dim repository As New StockPoolRepository(_logger)
                        resp = repository.CreateCohort(request)

                    ElseIf path = "/api/market/names_to_codes" Then
                        Try
                            Dim jObj As JObject = JObject.Parse(body)
                            Dim namesArr As JArray = CType(jObj("names"), JArray)
                            Dim results As New List(Of Object)()
                            Dim found As Integer = 0

                            For Each nameToken As JToken In namesArr
                                Dim sname As String = nameToken.ToString().Trim()
                                Dim code As String = GetStockCode(sname)
                                results.Add(New With {.name = sname, .code = code})
                                If code <> "" Then found += 1
                            Next

                            resp = ApiResponse.Ok(New With {
                                .items = results,
                                .total = namesArr.Count,
                                .found = found,
                                .missing = namesArr.Count - found
                            })
                        Catch ex As Exception
                            resp = ApiResponse.Err("JSON 파싱 오류: " & ex.Message)
                        End Try
                    Else
                        resp = ApiResponse.Err("Not Found", 404)
                    End If
                End Using
            Else
                resp = ApiResponse.Err("Method Not Allowed", 405)
            End If
        Catch ex As Exception
            _logger.Errors($"[API] Error processing {path}: {ex.Message}")
            resp = ApiResponse.Err(ex.Message, 500)
        End Try

        If resp Is Nothing Then resp = ApiResponse.Err("Not Found", 404)

        Try
            Dim json = JsonConvert.SerializeObject(resp)
            Dim buf = Encoding.UTF8.GetBytes(json)
            WriteRawResponse(res, "application/json; charset=utf-8", buf, resp.StatusCode)
        Catch ex As ObjectDisposedException
            _logger.Warn($"[HTTP] Client disconnected before response: {path}")
        Catch ex As Exception
            _logger.Warn($"[HTTP] Response send error ({path}): {ex.Message}")
        End Try
    End Sub

    Private Shared Function Resolve(Of T)(tt As Task(Of T)) As T
        Return tt.ConfigureAwait(False).GetAwaiter().GetResult()
    End Function

    Private Sub WriteRawResponse(res As HttpListenerResponse, contentType As String, buf As Byte(), statusCode As Integer)
        If res Is Nothing Then Return
        If buf Is Nothing Then buf = Array.Empty(Of Byte)()

        Try
            res.StatusCode = statusCode
            res.ContentType = contentType
            res.ContentLength64 = buf.Length
        Catch ex As Exception
            Debug.Print($"[WriteRawResponse] 헤더 설정 실패: {ex.Message}")
            SafeCloseResponse(res)
            Return
        End Try

        Try
            If buf.Length > 0 Then
                res.OutputStream.Write(buf, 0, buf.Length)
            End If
        Catch ex As HttpListenerException
            Debug.Print($"[WriteRawResponse] 클라이언트 연결 끊김(write): {ex.Message}")
            SafeCloseResponse(res)
            Return
        Catch ex As System.IO.IOException
            Debug.Print($"[WriteRawResponse] IO 예외(write, 무시): {ex.Message}")
            SafeCloseResponse(res)
            Return
        Catch ex As ObjectDisposedException
            Debug.Print($"[WriteRawResponse] 응답 스트림 이미 종료(write): {ex.Message}")
            Return
        Catch ex As Exception
            Debug.Print($"[WriteRawResponse] write 예외: {ex.Message}")
            SafeCloseResponse(res)
            Return
        End Try

        SafeCloseResponse(res)
    End Sub

    Private Sub SafeCloseResponse(res As HttpListenerResponse)
        If res Is Nothing Then Return

        Try
            res.OutputStream.Close()
        Catch ex As HttpListenerException
            Debug.Print($"[WriteRawResponse] 클라이언트 연결 끊김(close): {ex.Message}")
        Catch ex As System.IO.IOException
            Debug.Print($"[WriteRawResponse] IO 예외(close, 무시): {ex.Message}")
        Catch ex As ObjectDisposedException
            Debug.Print($"[WriteRawResponse] 응답 스트림 이미 종료(close): {ex.Message}")
        Catch ex As Exception
            Debug.Print($"[WriteRawResponse] close 예외: {ex.Message}")
        End Try

        Try
            res.Close()
        Catch ex As HttpListenerException
            Debug.Print($"[WriteRawResponse] 응답 close 중 연결 끊김: {ex.Message}")
        Catch ex As System.IO.IOException
            Debug.Print($"[WriteRawResponse] 응답 close IO 예외: {ex.Message}")
        Catch ex As ObjectDisposedException
            Debug.Print($"[WriteRawResponse] 응답 이미 종료: {ex.Message}")
        Catch ex As Exception
            Debug.Print($"[WriteRawResponse] 응답 close 예외: {ex.Message}")
        End Try
    End Sub
End Class
