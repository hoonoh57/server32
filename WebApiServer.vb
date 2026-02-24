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

    ' ── 종목명↔코드 변환용 CpStockCode ──
    Private ReadOnly _stockCode As New CPUTILLib.CpStockCode

    Public Sub New(apiSvc As KiwoomApiService, rtSvc As RealtimeDataService, execHub As ExecutionHub, logger As SimpleLogger)
        _apiService = apiSvc
        _realtimeService = rtSvc
        _execHub = execHub
        _logger = logger
    End Sub

    ''' <summary>
    ''' 종목명 → 종목코드 (A접두사 제거, 못찾으면 빈문자열)
    ''' </summary>
    Public Function GetStockCode(stockName As String) As String
        Dim code As String = _stockCode.NameToCode(stockName)
        If code <> "" Then
            Return code.Substring(1)   ' "A106450" → "106450"
        End If
        Return ""
    End Function

    Public Sub Start(url As String)
        Try
            _baseUrl = url.TrimEnd("/"c)
            Dim port As Integer = New Uri(url).Port
            _httpServer = New HttpServer(port)

            _httpServer.AddWebSocketService(Of RealtimeWebSocketBehavior)("/ws/realtime", Function() New RealtimeWebSocketBehavior(_realtimeService))
            _httpServer.AddWebSocketService(Of ExecutionWebSocketBehavior)("/ws/execution", Function() New ExecutionWebSocketBehavior(_execHub))

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

    Private Async Sub ProcessApiRequest(sender As Object, e As HttpRequestEventArgs)
        Dim req = e.Request
        Dim res = e.Response
        Dim path = req.Url.AbsolutePath.ToLower()

        _logger.Info($"[API] {req.HttpMethod} {path}")

        ' CORS
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

        ' Help HTML (별도 처리)
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
                        resp = Await _apiService.LoginAsync()

                    Case "/api/status", "/api/system/status"
                        resp = ApiResponse.Ok(_apiService.GetStatus())

                    Case "/api/conditions"
                        resp = Await _apiService.LoadConditionsAsync()

                    Case "/api/conditions/search"
                        Dim nm = req.QueryString("name")
                        Dim ix = Integer.Parse(If(req.QueryString("index"), "0"))
                        resp = Await _apiService.SearchConditionAsync(nm, ix)

                    Case "/api/conditions/start"
                        Dim nm = req.QueryString("name")
                        Dim ix = Integer.Parse(If(req.QueryString("index"), "0"))
                        Dim scr = If(req.QueryString("screen"), "9001")
                        resp = Await _apiService.StartConditionStreamAsync(nm, ix, scr)

                    Case "/api/conditions/stop"
                        Dim nm = req.QueryString("name")
                        Dim ix = Integer.Parse(If(req.QueryString("index"), "0"))
                        Dim scr = If(req.QueryString("screen"), "9001")
                        resp = _apiService.StopConditionStream(nm, ix, scr)

                    Case "/api/dashboard"
                        resp = _apiService.GetDashboardSnapshot()

                    Case "/api/dashboard/refresh"
                        resp = Await _apiService.RefreshDashboardDataAsync()

                    Case "/api/accounts/balance"
                        Dim acc = req.QueryString("accountNo")
                        Dim pw = req.QueryString("pass")
                        resp = Await _apiService.GetAccountBalanceAsync(acc, pw)

                    Case "/api/accounts/deposit"
                        Dim acc = req.QueryString("accountNo")
                        Dim pw = req.QueryString("pass")
                        resp = Await _apiService.GetDepositInfoAsync(acc, pw)

                    Case "/api/accounts/orders"
                        Dim acc = req.QueryString("accountNo")
                        Dim code = req.QueryString("code")
                        resp = Await _apiService.GetOutstandingOrdersAsync(acc, code)

                    Case "/api/market/candles/daily"
                        Dim code = req.QueryString("code")
                        Dim dt = req.QueryString("date")
                        If String.IsNullOrEmpty(dt) Then dt = DateTime.Now.ToString("yyyyMMdd")
                        Dim stopDate = req.QueryString("stopDate")
                        If String.IsNullOrEmpty(stopDate) Then stopDate = "20200101"
                        resp = Await _apiService.GetDailyCandlesAsync(code, dt, stopDate)

                    Case "/api/market/candles/minute"
                        Dim code = req.QueryString("code")
                        Dim tick = If(req.QueryString("tick"), "1")
                        Dim stopTime = req.QueryString("stopTime")
                        If String.IsNullOrEmpty(stopTime) Then stopTime = DateTime.Now.AddDays(-1).ToString("yyyyMMdd") & "090000"
                        resp = Await _apiService.GetMinuteCandlesAsync(code, CInt(tick), stopTime)

                    Case "/api/market/candles/tick"
                        Dim code = req.QueryString("code")
                        Dim tick = If(req.QueryString("tick"), "1")
                        Dim stopTime = req.QueryString("stopTime")
                        If String.IsNullOrEmpty(stopTime) Then stopTime = DateTime.Now.AddDays(-1).ToString("yyyyMMdd") & "090000"
                        resp = Await _apiService.GetTickCandlesAsync(code, CInt(tick), stopTime)

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

                        ' ── 프로그램매매 ──────────────────────────

                    Case "/api/market/program/time"
                        Dim code = req.QueryString("code")
                        Dim exchange = req.QueryString("exchange")
                        If String.IsNullOrEmpty(exchange) Then exchange = "A"
                        If String.IsNullOrEmpty(code) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Await _apiService.GetProgramTradeByTimeAsync(code, exchange)
                        End If

                    Case "/api/market/program/daily"
                        Dim code = req.QueryString("code")
                        Dim period = req.QueryString("period")
                        If String.IsNullOrEmpty(period) Then period = "2"
                        If String.IsNullOrEmpty(code) Then
                            resp = ApiResponse.Err("code required", 400)
                        Else
                            resp = Await _apiService.GetProgramTradeByDayAsync(code, period)
                        End If

                    Case "/api/market/program/subscribe"
                        Dim codesRaw = req.QueryString("codes")
                        If String.IsNullOrEmpty(codesRaw) Then
                            resp = ApiResponse.Err("codes required", 400)
                        Else
                            Dim codes = codesRaw.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                            resp = Await _apiService.SubscribeProgramTradeAsync(codes)
                        End If

                    Case "/api/market/program/unsubscribe"
                        Dim codesRaw = req.QueryString("codes")
                        Dim codes As String()
                        If String.IsNullOrEmpty(codesRaw) Then
                            codes = New String() {"ALL"}
                        Else
                            codes = codesRaw.Split({";"c, ","c}, StringSplitOptions.RemoveEmptyEntries)
                        End If
                        resp = Await _apiService.UnsubscribeProgramTradeAsync(codes)

                        ' ── 실시간 (Kiwoom) ──────────────────────

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

                Using r As New StreamReader(CType(req.InputStream, Stream))
                    Dim body = r.ReadToEnd()

                    If path = "/api/orders" Then
                        Dim orq = JsonConvert.DeserializeObject(Of OrderRequest)(body)
                        resp = Await _apiService.SendOrderAsync(orq)

                    ElseIf path = "/api/auth/login" Then
                        resp = Await _apiService.LoginAsync()

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

        ' ── 응답 전송 (클라이언트 이탈 방어) ──
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

    Private Sub WriteRawResponse(res As HttpListenerResponse, contentType As String, buf As Byte(), statusCode As Integer)
        If res Is Nothing Then Return
        Try
            res.StatusCode = statusCode
            res.ContentType = contentType
            res.ContentLength64 = buf.Length
            res.OutputStream.Write(buf, 0, buf.Length)
            res.OutputStream.Close()
        Catch
            ' 클라이언트 이탈, 이미 전송됨 등 모든 경우 무시
        End Try
    End Sub


End Class
