Imports System
Imports System.Collections.Concurrent
Imports System.Threading.Tasks
Imports System.Threading
Imports System.Linq
Imports System.Windows.Forms
Imports System.ComponentModel
Imports AxKHOpenAPILib
Imports System.Globalization
Imports System.Configuration
Imports System.Diagnostics

Public Class KiwoomApiService
    Private ReadOnly _api As AxKHOpenAPILib.AxKHOpenAPI
    Private ReadOnly _logger As SimpleLogger

    ' TR States: Key=RQName, Value=TaskCompletionSource returning (DataRows, PrevNext)
    ' DataRows is List of Dictionary
    ' PrevNext is String ("0" or "2")
    Private ReadOnly _pendingTr As New ConcurrentDictionary(Of String, TaskCompletionSource(Of TrResult))()

    Private _loginTcs As TaskCompletionSource(Of ApiResponse)
    Private _condLoadTcs As TaskCompletionSource(Of List(Of ConditionInfo))
    Private _condResultTcs As TaskCompletionSource(Of String())

    Private _isLoggedIn As Boolean = False
    Private _accountNo As String = ""
    Private ReadOnly _dashboardLock As New Object()
    Private _lastDashboard As AccountSnapshot = Nothing
    Private Shared _kwRqSeq As Integer = 0
    Private Shared _trRqSeq As Integer = 0
    Private ReadOnly _defaultAccountPassword As String = ""

    Public Class TrResult
        Public Rows As List(Of Dictionary(Of String, String))
        Public PrevNext As String
    End Class

    Public Sub New(apiControl As AxKHOpenAPILib.AxKHOpenAPI, logger As SimpleLogger)
        _api = apiControl
        _logger = logger
        _defaultAccountPassword = ConfigurationManager.AppSettings("AccountPassword")

        AddHandler _api.OnEventConnect, AddressOf OnEventConnect
        AddHandler _api.OnReceiveTrData, AddressOf OnReceiveTrData
        AddHandler _api.OnReceiveConditionVer, AddressOf OnReceiveConditionVer
        AddHandler _api.OnReceiveTrCondition, AddressOf OnReceiveTrCondition
    End Sub

    '////program realtime
    ' KiwoomApiService 생성자 또는 별도 초기화 메서드에 추가
    Public Sub InitProgramTradeRealtimeBroadcast(realtimeHub As RealtimeDataService)
        AddHandler _cybos.ProgramTradeReceived, Sub(data As Cybos.ProgramTradeRealtime)
                                                    Try
                                                        Dim payload = New With {
                    .type = "program_trade",
                    .code = If(data.StockCode, "").Replace("A", ""),
                    .timestamp = DateTime.Now.ToString("yyyyMMddHHmmss"),
                    .data = New With {
                        .time = data.Time,
                        .price = data.Price,
                        .sign = data.SignChar,
                        .change = data.Change,
                        .change_rate = data.ChangeRate,
                        .volume = data.Volume,
                        .pgm_buy_qty = data.PgmBuyQty,
                        .pgm_sell_qty = data.PgmSellQty,
                        .pgm_net_qty = data.PgmNetQty,
                        .pgm_buy_amt = data.PgmBuyAmt,
                        .pgm_sell_amt = data.PgmSellAmt,
                        .pgm_net_amt = data.PgmNetAmt
                    }
                }
                                                        Dim json = Newtonsoft.Json.JsonConvert.SerializeObject(payload)
                                                        realtimeHub.BroadcastJson(json)
                                                    Catch ex As Exception
                                                        Debug.Print($"프로그램매매 실시간 브로드캐스트 오류: {ex.Message}")
                                                    End Try
                                                End Sub
    End Sub




    ' -------- UI Thread helpers (Based on Reference Code) --------
    Private Function UiInvokeAsync(action As Action) As Task
        Dim tcs As New TaskCompletionSource(Of Object)(TaskCreationOptions.RunContinuationsAsynchronously)
        If _api.InvokeRequired Then
            _api.BeginInvoke(New MethodInvoker(Sub()
                                                   Try
                                                       action()
                                                       tcs.TrySetResult(Nothing)
                                                   Catch ex As Exception
                                                       tcs.TrySetException(ex)
                                                   End Try
                                               End Sub))
        Else
            Try
                action()
                tcs.TrySetResult(Nothing)
            Catch ex As Exception
                tcs.TrySetException(ex)
            End Try
        End If
        Return tcs.Task
    End Function

    Private Function UiInvoke(Of T)(func As Func(Of T)) As T
        If _api.InvokeRequired Then
            Return CType(_api.Invoke(func), T)
        Else
            Return func()
        End If
    End Function

    ' ----- Login -----
    Public Async Function LoginAsync() As Task(Of ApiResponse)
        If _isLoggedIn Then Return ApiResponse.Ok(New With {.loggedIn = True, .account = _accountNo})
        _loginTcs = New TaskCompletionSource(Of ApiResponse)(TaskCreationOptions.RunContinuationsAsynchronously)

        Await UiInvokeAsync(Sub() _api.CommConnect())

        Dim done = Await Task.WhenAny(_loginTcs.Task, Task.Delay(30000))
        If done Is _loginTcs.Task Then Return _loginTcs.Task.Result
        Return ApiResponse.Err("Login Timeout", 504)
    End Function

    Private Sub OnEventConnect(sender As Object, e As _DKHOpenAPIEvents_OnEventConnectEvent)
        _logger.Info($"[OnEventConnect] ErrCode: {e.nErrCode}")
        If e.nErrCode = 0 Then
            Dim rawAcc = UiInvoke(Function() _api.GetLoginInfo("ACCNO"))
            _logger.Info($"[Logic] Raw Account Info: {rawAcc}")

            Dim accList = rawAcc.Split(";"c)
            If accList.Length > 0 Then
                _accountNo = accList(0).Trim()
            End If

            _logger.Info($"[Logic] Selected Account: {_accountNo}")
            _isLoggedIn = True ' [CRITICAL] Set True ONLY after account info is ready

            _loginTcs?.TrySetResult(ApiResponse.Ok(New With {.loggedIn = True, .account = _accountNo}))
            WarmupDashboardData()
        Else
            _loginTcs?.TrySetResult(ApiResponse.Err($"Login Failed: {e.nErrCode}"))
        End If
    End Sub

    ' ----- Conditions -----
    Public Async Function LoadConditionsAsync() As Task(Of ApiResponse)
        _condLoadTcs = New TaskCompletionSource(Of List(Of ConditionInfo))(TaskCreationOptions.RunContinuationsAsynchronously)
        Await UiInvokeAsync(Sub() _api.GetConditionLoad())
        Dim done = Await Task.WhenAny(_condLoadTcs.Task, Task.Delay(10000))
        If done Is _condLoadTcs.Task Then Return ApiResponse.Ok(_condLoadTcs.Task.Result)
        Return ApiResponse.Err("LoadConditions Timeout", 504)
    End Function

    Private Sub OnReceiveConditionVer(sender As Object, e As _DKHOpenAPIEvents_OnReceiveConditionVerEvent)
        Try
            Dim raw = UiInvoke(Function() _api.GetConditionNameList())
            Dim list As New List(Of ConditionInfo)
            If Not String.IsNullOrEmpty(raw) Then
                For Each s As String In raw.Split(";"c)
                    Dim parts = s.Split("^"c)
                    If parts.Length >= 2 Then
                        list.Add(New ConditionInfo With {.Index = CInt(parts(0)), .Name = parts(1)})
                    End If
                Next
            End If
            _condLoadTcs?.TrySetResult(list)
        Catch ex As Exception
            _condLoadTcs?.TrySetException(ex)
        End Try
    End Sub

    Public Async Function SearchConditionAsync(name As String, index As Integer) As Task(Of ApiResponse)
        _condResultTcs = New TaskCompletionSource(Of String())(TaskCreationOptions.RunContinuationsAsynchronously)
        Await UiInvokeAsync(Sub() _api.SendCondition("9000", name, index, 0))
        Dim done = Await Task.WhenAny(_condResultTcs.Task, Task.Delay(15000))
        If done IsNot _condResultTcs.Task Then
            Return ApiResponse.Err("SearchCondition Timeout", 504)
        End If

        Dim codes As String() = _condResultTcs.Task.Result
        Dim detailRows As List(Of Dictionary(Of String, String)) = New List(Of Dictionary(Of String, String))()

        If codes IsNot Nothing AndAlso codes.Length > 0 Then
            Try
                detailRows = Await FetchConditionStockInfoAsync(codes)
            Catch ex As Exception
                _logger.Warn($"[Condition] Failed to load KW data: {ex.Message}")
            End Try
        End If

        Dim payload = New With {
            .Codes = codes,
            .Stocks = detailRows
        }

        Return ApiResponse.Ok(payload)
    End Function

    Public Async Function StartConditionStreamAsync(name As String, index As Integer, screen As String) As Task(Of ApiResponse)
        Dim scr = If(String.IsNullOrWhiteSpace(screen), "9001", screen)
        Await UiInvokeAsync(Sub() _api.SendCondition(scr, name, index, 1))
        Return ApiResponse.Ok(Nothing, $"Condition stream started: {name} ({index}) @ {scr}")
    End Function

    Public Function StopConditionStream(name As String, index As Integer, screen As String) As ApiResponse
        Dim scr = If(String.IsNullOrWhiteSpace(screen), "9001", screen)
        UiInvoke(Of Object)(Function()
                                _api.SendConditionStop(scr, name, index)
                                Return Nothing
                            End Function)
        Return ApiResponse.Ok(Nothing, $"Condition stream stopped: {name} ({index})")
    End Function

    Public Function GetDashboardSnapshot() As ApiResponse
        SyncLock _dashboardLock
            If _lastDashboard Is Nothing Then
                Return ApiResponse.Err("Dashboard snapshot not ready", 404)
            End If
            Return ApiResponse.Ok(_lastDashboard)
        End SyncLock
    End Function

    Public Async Function RefreshDashboardDataAsync() As Task(Of ApiResponse)
        If Not _isLoggedIn Then Return ApiResponse.Err("Not Logged In")
        Dim acc = _accountNo

        Dim balanceRes = Await GetAccountBalanceAsync(acc, "")
        If Not balanceRes.Success Then Return balanceRes
        Dim depositRes = Await GetDepositInfoAsync(acc, "")
        If Not depositRes.Success Then Return depositRes
        Dim outstandingRes = Await GetOutstandingOrdersAsync(acc, "")
        If Not outstandingRes.Success Then Return outstandingRes

        Dim balanceRows = TryCast(balanceRes.Data, List(Of Dictionary(Of String, String)))
        Dim depositRows = TryCast(depositRes.Data, List(Of Dictionary(Of String, String)))
        Dim outstandingRows = TryCast(outstandingRes.Data, List(Of Dictionary(Of String, String)))

        Dim summary = FindSummaryRow(balanceRows)

        Dim totalPurchase = ParseDoubleRow(summary, "총매입금액")
        Dim totalEval = ParseDoubleRow(summary, "총평가금액")
        Dim totalPnl = ParseDoubleRow(summary, "총평가손익금액")
        Dim totalRate = ParseDoubleRow(summary, "총수익률(%)")
        Dim realized = ParseDoubleRow(summary, "실현손익")
        Dim depositAvail = ParseDoubleFromRows(depositRows, "주문가능금액")
        Dim depositWithdraw = ParseDoubleFromRows(depositRows, "출금가능금액")

        Dim snapshot As New AccountSnapshot With {
            .AccountNo = acc,
            .FetchedAt = DateTime.Now,
            .TotalPurchase = totalPurchase,
            .TotalEvaluation = totalEval,
            .TotalPnL = totalPnl,
            .TotalPnLRate = totalRate,
            .RealizedPnL = realized,
            .DepositAvailable = depositAvail,
            .DepositWithdrawable = depositWithdraw,
            .Holdings = FilterHoldings(balanceRows),
            .Outstanding = NormalizeOutstanding(outstandingRows),
            .RawBalance = balanceRows,
            .RawDeposit = depositRows,
            .RawOutstanding = outstandingRows
        }

        SyncLock _dashboardLock
            _lastDashboard = snapshot
        End SyncLock

        Return ApiResponse.Ok(snapshot)
    End Function

    Private Sub WarmupDashboardData()
        Task.Run(Async Function()
                     Try
                         Dim res = Await RefreshDashboardDataAsync()
                         If res.Success Then
                             _logger.Info("[Dashboard] Warmup completed.")
                         Else
                             _logger.Warn("[Dashboard] Warmup failed: " & res.Message)
                         End If
                     Catch ex As Exception
                         _logger.Warn("[Dashboard] Warmup exception: " & ex.Message)
                     End Try
                 End Function)
    End Sub

    Private Async Function FetchConditionStockInfoAsync(codes As IEnumerable(Of String)) As Task(Of List(Of Dictionary(Of String, String)))
        Dim rows As New List(Of Dictionary(Of String, String))()
        If codes Is Nothing Then Return rows

        Dim normalized As String() = codes.Where(Function(c) Not String.IsNullOrWhiteSpace(c)).Select(Function(c) c.Trim()).Where(Function(c) c.Length > 0).ToArray()
        If normalized.Length = 0 Then Return rows

        Const chunkSize As Integer = 100
        Dim index As Integer = 0

        While index < normalized.Length
            Dim chunk As String() = normalized.Skip(index).Take(chunkSize).ToArray()
            Dim tr = Await RequestKwDataAsync(chunk)
            If tr IsNot Nothing AndAlso tr.Rows IsNot Nothing AndAlso tr.Rows.Count > 0 Then
                rows.AddRange(tr.Rows)
            End If
            index += chunk.Length
            If index < normalized.Length Then
                Await Task.Delay(200)
            End If
        End While

        Return rows
    End Function

    Private Async Function RequestKwDataAsync(codeChunk As String()) As Task(Of TrResult)
        If codeChunk Is Nothing OrElse codeChunk.Length = 0 Then
            Return New TrResult With {.Rows = New List(Of Dictionary(Of String, String))(), .PrevNext = "0"}
        End If

        Dim rq = NextKwRqName()
        Dim tcs As New TaskCompletionSource(Of TrResult)(TaskCreationOptions.RunContinuationsAsynchronously)
        _pendingTr(rq) = tcs

        Await UiInvokeAsync(Sub()
                                Dim codeList = String.Join(";", codeChunk)
                                _api.CommKwRqData(codeList, 0, codeChunk.Length, 0, rq, "9200")
                            End Sub)

        If Await Task.WhenAny(tcs.Task, Task.Delay(10000)) Is tcs.Task Then
            Return tcs.Task.Result
        End If

        Dim dummy As TaskCompletionSource(Of TrResult) = Nothing
        _pendingTr.TryRemove(rq, dummy)
        Return New TrResult With {.Rows = New List(Of Dictionary(Of String, String))(), .PrevNext = "0"}
    End Function

    Private Function NextKwRqName() As String
        Dim seq = Threading.Interlocked.Increment(_kwRqSeq)
        seq = Math.Abs(seq Mod 10000)
        Return $"KW{seq:0000}"
    End Function

    Private Function FindSummaryRow(rows As List(Of Dictionary(Of String, String))) As Dictionary(Of String, String)
        If rows Is Nothing Then Return New Dictionary(Of String, String)()
        For Each r As Dictionary(Of String, String) In rows
            If r.ContainsKey("ROW_TYPE") AndAlso r("ROW_TYPE") = "SUMMARY" Then
                Return r
            End If
        Next
        If rows.Count > 0 Then Return rows(0)
        Return New Dictionary(Of String, String)()
    End Function

    Private Function ParseDoubleFromRows(rows As List(Of Dictionary(Of String, String)), key As String) As Double
        If rows Is Nothing OrElse rows.Count = 0 Then Return 0
        Return ParseDoubleRow(rows(0), key)
    End Function

    Private Function ParseDoubleRow(row As Dictionary(Of String, String), key As String) As Double
        If row Is Nothing Then Return 0
        If Not row.ContainsKey(key) Then Return 0
        Dim raw = row(key)
        Return ParseNumericValue(raw)
    End Function

    Private Function FilterHoldings(rows As List(Of Dictionary(Of String, String))) As List(Of Dictionary(Of String, String))
        Dim result As New List(Of Dictionary(Of String, String))()
        If rows Is Nothing Then Return result
        For Each row As Dictionary(Of String, String) In rows
            If row.ContainsKey("ROW_TYPE") Then Continue For
            Dim normalized As New Dictionary(Of String, String)
            Dim rawCode = GetRowValue(row, New String() {"종목번호", "종목코드"})
            normalized("종목코드") = NormalizeStockCode(rawCode)
            normalized("종목명") = GetRowValue(row, New String() {"종목명"})
            normalized("보유수량") = NormalizeNumericField("보유수량", GetRowValue(row, New String() {"보유수량"}))
            normalized("매입가") = NormalizeNumericField("매입가", GetRowValue(row, New String() {"매입가", "매입단가"}))
            normalized("매입금액") = NormalizeNumericField("매입금액", GetRowValue(row, New String() {"매입금액"}))
            normalized("평가금액") = NormalizeNumericField("평가금액", GetRowValue(row, New String() {"평가금액"}))
            normalized("평가손익") = NormalizeNumericField("평가손익", GetRowValue(row, New String() {"평가손익"}))

            Dim pnlRateRaw = GetRowValue(row, New String() {"수익률(%)", "손익률(%)", "손익률", "수익률"})
            Dim pnlRateValue = NormalizeNumericField("수익률(%)", pnlRateRaw)
            normalized("손익률") = pnlRateValue
            normalized("손익률(%)") = pnlRateValue

            For Each kvp As KeyValuePair(Of String, String) In row
                If Not normalized.ContainsKey(kvp.Key) Then
                    normalized(kvp.Key) = NormalizeNumericField(kvp.Key, kvp.Value)
                End If
            Next
            result.Add(normalized)
        Next
        Return result
    End Function

    Private Function NormalizeOutstanding(rows As List(Of Dictionary(Of String, String))) As List(Of Dictionary(Of String, String))
        Dim result As New List(Of Dictionary(Of String, String))()
        If rows Is Nothing Then Return result
        For Each row As Dictionary(Of String, String) In rows
            Dim normalized As New Dictionary(Of String, String)
            For Each kvp As KeyValuePair(Of String, String) In row
                normalized(kvp.Key) = NormalizeNumericField(kvp.Key, kvp.Value)
            Next
            result.Add(normalized)
        Next
        Return result
    End Function

    Public Function ApplyBalanceChejan(raw As Dictionary(Of String, String)) As AccountSnapshot
        If raw Is Nothing OrElse raw.Count = 0 Then Return Nothing
        Dim account = GetChejanValue(raw, "9201")
        If String.IsNullOrWhiteSpace(account) OrElse Not String.Equals(account.Trim(), _accountNo) Then Return Nothing

        Dim code = NormalizeStockCode(GetChejanValue(raw, "9001"))
        If String.IsNullOrEmpty(code) Then Return Nothing

        Dim name = GetChejanValue(raw, "302")
        Dim qty = ParseNumericValue(GetChejanValue(raw, "930"))
        Dim availQty = ParseNumericValue(GetChejanValue(raw, "933"))
        Dim currentPrice = ParseNumericValue(GetChejanValue(raw, "10"))
        Dim purchaseAmount = ParseNumericValue(GetChejanValue(raw, "932"))
        Dim purchasePrice = ParseNumericValue(GetChejanValue(raw, "931"))
        Dim pnlRate = ParseNumericValue(GetChejanValue(raw, "8019"))
        Dim deposit = ParseNumericValue(GetChejanValue(raw, "951"))

        Dim evalAmount As Double = If(currentPrice > 0 AndAlso qty > 0, currentPrice * qty, purchaseAmount)
        Dim pnlAmount As Double = evalAmount - purchaseAmount
        Dim normalized As New Dictionary(Of String, String) From {
            {"종목코드", code},
            {"종목명", name},
            {"보유수량", FormatValue(qty, 0)},
            {"주문가능수량", FormatValue(availQty, 0)},
            {"평가금액", FormatValue(evalAmount, 0)},
            {"평가손익", FormatValue(pnlAmount, 0)},
            {"손익률", FormatValue(pnlRate, 2)},
            {"평가단가", FormatValue(currentPrice, 0)},
            {"매입단가", FormatValue(purchasePrice, 0)},
            {"매입금액", FormatValue(purchaseAmount, 0)}
        }

        SyncLock _dashboardLock
            Dim snap = EnsureDashboardSnapshot()
            Dim replaced As Boolean = False
            If snap.Holdings Is Nothing Then
                snap.Holdings = New List(Of Dictionary(Of String, String))()
            End If

            For Each row As Dictionary(Of String, String) In snap.Holdings
                If row.ContainsKey("종목코드") AndAlso row("종목코드") = code Then
                    For Each kvp As KeyValuePair(Of String, String) In normalized
                        row(kvp.Key) = kvp.Value
                    Next
                    replaced = True
                    Exit For
                End If
            Next

            If Not replaced Then
                snap.Holdings.Add(normalized)
            End If

            If deposit > 0 Then
                snap.DepositAvailable = deposit
                If snap.DepositWithdrawable <= 0 Then
                    snap.DepositWithdrawable = deposit
                End If
            End If

            snap.TotalEvaluation = SumNumericField(snap.Holdings, "평가금액")
            snap.TotalPurchase = SumNumericField(snap.Holdings, "매입금액")
            snap.TotalPnL = snap.TotalEvaluation - snap.TotalPurchase
            snap.TotalPnLRate = If(snap.TotalPurchase > 0, Math.Round(snap.TotalPnL / snap.TotalPurchase * 100, 2), 0)
            snap.FetchedAt = DateTime.Now
            _lastDashboard = snap

            Return CloneSnapshot(snap)
        End SyncLock
    End Function

    Private Function NormalizeNumericField(key As String, value As String) As String
        If String.IsNullOrEmpty(value) Then Return "0"
        If IsTextualField(key) Then Return value.Trim()
        Dim decimals As Integer = If(key.Contains("??") OrElse key.Contains("(%)"), 2, 0)
        Return FormatNumericString(value, decimals)
    End Function

    Private Function FormatNumericString(raw As String, decimals As Integer) As String
        Dim val As Double
        If Not TryParseNumericValue(raw, val) Then
            Dim trimmed = If(raw, String.Empty)
            Return trimmed.Trim()
        End If
        Dim safeDecimals = Math.Max(0, Math.Min(6, decimals))
        Dim formatString = "N" & safeDecimals.ToString()
        Return val.ToString(formatString)
    End Function

    Private Function FormatValue(val As Double, decimals As Integer) As String
        Dim raw = val.ToString("0.################", Globalization.CultureInfo.InvariantCulture)
        Return FormatNumericString(raw, decimals)
    End Function

    Private Function ResolveAccountPassword(explicitPassword As String) As String
        If Not String.IsNullOrWhiteSpace(explicitPassword) Then Return explicitPassword
        If Not String.IsNullOrWhiteSpace(_defaultAccountPassword) Then Return _defaultAccountPassword
        Return ""
    End Function

    Private Function ParseNumericValue(raw As String) As Double
        Dim val As Double
        If TryParseNumericValue(raw, val) Then
            Return val
        End If
        Return 0
    End Function

    Private Function TryParseNumericValue(raw As String, ByRef value As Double) As Boolean
        value = 0
        If String.IsNullOrWhiteSpace(raw) Then Return False

        Dim cleaned = raw.Trim()
        cleaned = cleaned.Replace(",", "").Replace(" ", "")
        cleaned = cleaned.Replace("+", "")
        If cleaned.EndsWith("-") Then
            cleaned = "-" & cleaned.Substring(0, cleaned.Length - 1)
        End If

        If Double.TryParse(cleaned, Globalization.NumberStyles.Any, Globalization.CultureInfo.InvariantCulture, value) Then
            Return True
        End If

        Return Double.TryParse(cleaned, Globalization.NumberStyles.Any, Globalization.CultureInfo.CurrentCulture, value)
    End Function

    Private Function IsTextualField(key As String) As Boolean
        If String.IsNullOrEmpty(key) Then Return False
        Dim markers = New String() {"코드", "명", "번호", "상태", "구분"}
        For Each marker As String In markers
            If key.Contains(marker) Then
                Return True
            End If
        Next
        Return False
    End Function

    Private Function GetRowValue(row As Dictionary(Of String, String), candidates As String()) As String
        If row Is Nothing OrElse candidates Is Nothing Then Return String.Empty
        For Each key As String In candidates
            If row.ContainsKey(key) Then
                Return row(key)
            End If
        Next
        Return String.Empty
    End Function

    Private Function GetChejanValue(raw As Dictionary(Of String, String), key As String) As String
        If raw Is Nothing Then Return String.Empty
        Dim value As String = Nothing
        If raw.TryGetValue(key, value) Then
            Return value
        End If
        Return String.Empty
    End Function

    Private Function NormalizeStockCode(raw As String) As String
        If String.IsNullOrWhiteSpace(raw) Then Return String.Empty
        Dim code = raw.Trim()
        If code.StartsWith("A", StringComparison.OrdinalIgnoreCase) AndAlso code.Length = 7 Then
            code = code.Substring(1)
        End If
        Return code
    End Function

    Private Function SumNumericField(rows As List(Of Dictionary(Of String, String)), key As String) As Double
        If rows Is Nothing Then Return 0
        Dim total As Double = 0
        For Each row As Dictionary(Of String, String) In rows
            If row IsNot Nothing AndAlso row.ContainsKey(key) Then
                total += ParseNumericValue(row(key))
            End If
        Next
        Return total
    End Function

    Private Function EnsureDashboardSnapshot() As AccountSnapshot
        If _lastDashboard Is Nothing Then
            _lastDashboard = New AccountSnapshot With {
                .AccountNo = _accountNo,
                .FetchedAt = DateTime.Now,
                .TotalPurchase = 0,
                .TotalEvaluation = 0,
                .TotalPnL = 0,
                .TotalPnLRate = 0,
                .RealizedPnL = 0,
                .DepositAvailable = 0,
                .DepositWithdrawable = 0,
                .Holdings = New List(Of Dictionary(Of String, String))(),
                .Outstanding = New List(Of Dictionary(Of String, String))(),
                .RawBalance = New List(Of Dictionary(Of String, String))(),
                .RawDeposit = New List(Of Dictionary(Of String, String))(),
                .RawOutstanding = New List(Of Dictionary(Of String, String))()
            }
        End If
        Return _lastDashboard
    End Function

    Private Function CloneSnapshot(src As AccountSnapshot) As AccountSnapshot
        If src Is Nothing Then Return Nothing
        Dim clone As New AccountSnapshot With {
            .AccountNo = src.AccountNo,
            .FetchedAt = src.FetchedAt,
            .TotalPurchase = src.TotalPurchase,
            .TotalEvaluation = src.TotalEvaluation,
            .TotalPnL = src.TotalPnL,
            .TotalPnLRate = src.TotalPnLRate,
            .RealizedPnL = src.RealizedPnL,
            .DepositAvailable = src.DepositAvailable,
            .DepositWithdrawable = src.DepositWithdrawable,
            .RawBalance = If(src.RawBalance Is Nothing, Nothing, src.RawBalance.Select(Function(r) New Dictionary(Of String, String)(r)).ToList()),
            .RawDeposit = If(src.RawDeposit Is Nothing, Nothing, src.RawDeposit.Select(Function(r) New Dictionary(Of String, String)(r)).ToList()),
            .RawOutstanding = If(src.RawOutstanding Is Nothing, Nothing, src.RawOutstanding.Select(Function(r) New Dictionary(Of String, String)(r)).ToList())
        }

        If src.Holdings IsNot Nothing Then
            clone.Holdings = src.Holdings.Select(Function(r) New Dictionary(Of String, String)(r)).ToList()
        End If
        If src.Outstanding IsNot Nothing Then
            clone.Outstanding = src.Outstanding.Select(Function(r) New Dictionary(Of String, String)(r)).ToList()
        End If
        Return clone
    End Function

    Private Sub OnReceiveTrCondition(sender As Object, e As _DKHOpenAPIEvents_OnReceiveTrConditionEvent)
        Dim codes = If(e.strCodeList, "").Split(";"c).Where(Function(s) s.Length > 0).ToArray()
        _condResultTcs?.TrySetResult(codes)
    End Sub

    ' ----- Orders -----
    Public Async Function SendOrderAsync(req As OrderRequest) As Task(Of ApiResponse)
        Dim ret As Integer = -1
        Await UiInvokeAsync(Sub()
                                ret = _api.SendOrder("WebOrder", "8000", req.AccountNo, req.OrderType, req.StockCode, req.Quantity, req.Price, req.QuoteType, "")
                            End Sub)
        If ret = 0 Then Return ApiResponse.Ok("Order Sent")
        Return ApiResponse.Err($"Order Failed: {ret}")
    End Function

    ' =================================================================================
    '                          CORE TR LOGIC (SMART FETCH)
    ' =================================================================================

    Private Const TrTimeoutMs As Integer = 30000

    Private Async Function RequestTrAsync(trCode As String, inputs As Dictionary(Of String, String), prevNext As Integer) As Task(Of TrResult)
        Dim rq = NextTrRqName(trCode)
        Dim tcs As New TaskCompletionSource(Of TrResult)(TaskCreationOptions.RunContinuationsAsynchronously)
        _pendingTr(rq) = tcs
        Dim rqResult As Integer = -1

        Await UiInvokeAsync(Sub()
                                For Each kvp As KeyValuePair(Of String, String) In inputs
                                    _logger.Info($"[TR Input] {kvp.Key}='{kvp.Value}'")
                                    _api.SetInputValue(kvp.Key, kvp.Value)
                                Next
                                rqResult = _api.CommRqData(rq, trCode, prevNext, "1000")
                            End Sub)

        If rqResult <> 0 Then
            Dim dummy As TaskCompletionSource(Of TrResult) = Nothing
            _pendingTr.TryRemove(rq, dummy)
            Throw New InvalidOperationException($"CommRqData failed ({trCode}) => {rqResult}")
        End If

        If Await Task.WhenAny(tcs.Task, Task.Delay(TrTimeoutMs)) Is tcs.Task Then
            Return tcs.Task.Result
        Else
            Dim d As TaskCompletionSource(Of TrResult) = Nothing
            _pendingTr.TryRemove(rq, d)
            _logger.Warn($"[TR] Timeout waiting {trCode}/{rq}")
            Return New TrResult With {.Rows = New List(Of Dictionary(Of String, String)), .PrevNext = "0"}
        End If
    End Function

    Private Function NextTrRqName(trCode As String) As String
        Dim seq As Integer = Interlocked.Increment(_trRqSeq)
        seq = Math.Abs(seq Mod 10000)
        Return $"{trCode}_{seq:0000}"
    End Function

    ' ----- Smart Fetch Implementations -----

    Private _cybos As New Cybos()

    ' 일봉: date(최신, YYYYMMDD) -> stopDate(과거)
    Public Async Function GetDailyCandlesAsync(code As String, [date] As String, stopDate As String) As Task(Of ApiResponse)
        Try
            ' Cybos Period: From(Past) ~ To(Recent)
            ' Kiwoom Req: StopDate(Past) ~ Date(Recent)
            ' So From = StopDate, To = Date (or Now)
            Dim toDate As String = If(String.IsNullOrEmpty([date]), DateTime.Now.ToString("yyyyMMdd"), [date])
            Dim fromDate As String = stopDate

            Dim candles = Await _cybos.DownloadCandlesByPeriod(code, "D", fromDate, toDate)

            Dim rows As New List(Of Dictionary(Of String, String))
            For Each c As Candle In candles
                Dim d As New Dictionary(Of String, String)
                d("일자") = c.Timestamp.ToString("yyyyMMdd")
                d("시가") = c.Open.ToString()
                d("고가") = c.High.ToString()
                d("저가") = c.Low.ToString()
                d("현재가") = c.Close.ToString() ' 종가와 동일취급
                d("종가") = c.Close.ToString()
                d("거래량") = c.Volume.ToString()
                rows.Add(d)
            Next
            Return ApiResponse.Ok(rows)
        Catch ex As Exception
            _logger.Errors($"[GetDailyCandlesAsync] Failed: {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ' 분봉: tick(1,3,5...), stopTime(YYYYMMDDHHMMSS)
    Public Async Function GetMinuteCandlesAsync(code As String, tick As Integer, stopTime As String) As Task(Of ApiResponse)
        Try
            Dim fromDate As String = stopTime.Substring(0, 12) ' yyyyMMddHHmm
            Dim toDate As String = DateTime.Now.ToString("yyyyMMddHHmm")

            Dim candles = Await _cybos.DownloadCandlesByPeriod(code, "m" & tick, fromDate, toDate)

            Dim rows As New List(Of Dictionary(Of String, String))
            For Each c As Candle In candles
                Dim d As New Dictionary(Of String, String)
                d("체결시간") = c.Timestamp.ToString("yyyyMMddHHmmss")
                d("시가") = c.Open.ToString()
                d("고가") = c.High.ToString()
                d("저가") = c.Low.ToString()
                d("현재가") = c.Close.ToString()
                d("거래량") = c.Volume.ToString()
                rows.Add(d)
            Next
            Return ApiResponse.Ok(rows)
        Catch ex As Exception
            _logger.Errors($"[GetMinuteCandlesAsync] Failed: {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ' 틱: tick(1,3,10...), stopTime(YYYYMMDDHHMMSS)
    Public Async Function GetTickCandlesAsync(code As String, tick As Integer, stopTime As String) As Task(Of ApiResponse)
        Try
            Dim fromDate As String = stopTime.Substring(0, 12)
            Dim toDate As String = DateTime.Now.ToString("yyyyMMddHHmm")

            Dim candles = Await _cybos.DownloadCandlesByPeriod(code, "T" & tick, fromDate, toDate)

            Dim rows As New List(Of Dictionary(Of String, String))
            For Each c As Candle In candles
                Dim d As New Dictionary(Of String, String)
                d("체결시간") = c.Timestamp.ToString("yyyyMMddHHmmss")
                d("시가") = c.Open.ToString()
                d("고가") = c.High.ToString()
                d("저가") = c.Low.ToString()
                d("현재가") = c.Close.ToString()
                d("거래량") = c.Volume.ToString()
                rows.Add(d)
            Next
            Return ApiResponse.Ok(rows)
        Catch ex As Exception
            _logger.Errors($"[GetTickCandlesAsync] Failed: {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ' ----- Single Call Wrappers (Deposit, Orders, Balance) -----

    Public Async Function GetDepositInfoAsync(acc As String, pass As String) As Task(Of ApiResponse)
        If Not _isLoggedIn Then Return ApiResponse.Err("Not Logged In")
        Dim password = ResolveAccountPassword(pass)
        Dim res = Await RequestTrAsync("OPW00001", New Dictionary(Of String, String) From {
            {"계좌번호", acc}, {"비밀번호", password}, {"비밀번호입력매체구분", "00"}, {"조회구분", "2"}
        }, 0)
        Return ApiResponse.Ok(res.Rows)
    End Function

    Public Async Function GetOutstandingOrdersAsync(acc As String, code As String) As Task(Of ApiResponse)
        If Not _isLoggedIn Then Return ApiResponse.Err("Not Logged In")
        Dim password = ResolveAccountPassword("")
        Dim res = Await RequestTrAsync("OPT10075", New Dictionary(Of String, String) From {
            {"계좌번호", acc}, {"비밀번호", password}, {"비밀번호입력매체구분", "00"},
            {"전체종목구분", If(String.IsNullOrEmpty(code), "0", "1")},
            {"매매구분", "0"}, {"종목코드", code}, {"체결구분", "1"}
        }, 0)
        Return ApiResponse.Ok(res.Rows)
    End Function

    Public Async Function GetAccountBalanceAsync(acc As String, pass As String) As Task(Of ApiResponse)
        If Not _isLoggedIn Then Return ApiResponse.Err("Not Logged In")
        If String.IsNullOrWhiteSpace(acc) Then
            _logger.Errors("[GetAccountBalanceAsync] Account No is Empty!")
            Return ApiResponse.Err("Account Number Required", 400)
        End If
        Dim password = ResolveAccountPassword(pass)
        Dim res = Await RequestTrAsync("OPW00018", New Dictionary(Of String, String) From {
            {"계좌번호", acc},
            {"비밀번호", password},
            {"비밀번호입력매체구분", "00"},
            {"조회구분", "2"},
            {"거래소구분", "KRX"}
        }, 0)
        Return ApiResponse.Ok(res.Rows)
    End Function

    ' ----- Master Info -----
    Public Function GetMasterName(code As String) As String
        If Not _isLoggedIn Then Return ""
        Return UiInvoke(Function() _api.GetMasterCodeName(code))
    End Function

    Public Function GetMasterLastPrice(code As String) As Integer
        If Not _isLoggedIn Then Return 0
        Dim s = UiInvoke(Function() _api.GetMasterLastPrice(code))
        Dim v As Integer
        Integer.TryParse(s, v)
        Return v
    End Function

    Public Function GetMasterState(code As String) As String
        If Not _isLoggedIn Then Return ""
        Return UiInvoke(Function() _api.GetMasterStockState(code))
    End Function

    '//////////////////프로그램 순매수 정보  신규삽입//////////////////////////////////////////////////////////
    ' ============================================================
    '  프로그램매매 REST 핸들러 (UI 스레드 마샬링 적용)
    ' ============================================================

    ''' <summary>시간대별 프로그램매매</summary>
    Public Async Function GetProgramTradeByTimeAsync(code As String, Optional exchange As String = "A") As Task(Of ApiResponse)
        Try
            ' Cybos COM은 STA 스레드에서만 호출 가능 → UI 스레드로 마샬링
            Dim rows As List(Of Cybos.ProgramTradeByTime) = Nothing
            Await UiInvokeAsync(Sub()
                                    rows = _cybos.DownloadProgramTradeByTimeSync(code, exchange)
                                End Sub)

            ' ↑ 동기 버전이 필요하므로 Cybos에 동기 메서드 추가 필요
            ' 또는 아래처럼 Task.Run 대신 UI Invoke 내에서 완료
            If rows Is Nothing Then rows = New List(Of Cybos.ProgramTradeByTime)

            Dim result As New List(Of Dictionary(Of String, Object))
            For Each r As Cybos.ProgramTradeByTime In rows
                result.Add(New Dictionary(Of String, Object) From {
                    {"시간", r.Time},
                    {"현재가", r.Price},
                    {"대비부호", r.SignChar},
                    {"전일대비", r.Change},
                    {"대비율", r.ChangeRate},
                    {"거래량", r.Volume},
                    {"프로그램매수수량", r.PgmBuyQty},
                    {"프로그램매도수량", r.PgmSellQty},
                    {"프로그램순매수수량", r.PgmNetQty},
                    {"프로그램순매수수량증감", r.PgmNetQtyChange},
                    {"프로그램매수금액_천원", r.PgmBuyAmt},
                    {"프로그램매도금액_천원", r.PgmSellAmt},
                    {"프로그램순매수금액_천원", r.PgmNetAmt},
                    {"프로그램순매수금액증감_천원", r.PgmNetAmtChange}
                })
            Next
            Return ApiResponse.Ok(result, $"시간대별 {rows.Count}건")
        Catch ex As Exception
            _logger.Errors($"[GetProgramTradeByTime] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>일자별 프로그램매매</summary>
    Public Async Function GetProgramTradeByDayAsync(code As String, Optional period As String = "2") As Task(Of ApiResponse)
        Try
            Dim rows As List(Of Cybos.ProgramTradeByDay) = Nothing
            Await UiInvokeAsync(Sub()
                                    rows = _cybos.DownloadProgramTradeByDay(code, period)
                                End Sub)
            If rows Is Nothing Then rows = New List(Of Cybos.ProgramTradeByDay)

            Dim result As New List(Of Dictionary(Of String, Object))
            For Each r As Cybos.ProgramTradeByDay In rows
                result.Add(New Dictionary(Of String, Object) From {
                    {"일자", r.TradeDate},
                    {"현재가", r.Price},
                    {"전일대비", r.Change},
                    {"대비율", r.ChangeRate},
                    {"거래량", r.Volume},
                    {"매도량", r.SellQty},
                    {"매수량", r.BuyQty},
                    {"순매수증감수량", r.NetQtyChange},
                    {"순매수누적수량", r.NetQtyCumul},
                    {"매도금액_만원", r.SellAmt},
                    {"매수금액_만원", r.BuyAmt},
                    {"순매수증감금액_만원", r.NetAmtChange},
                    {"순매수누적금액_만원", r.NetAmtCumul}
                })
            Next
            Return ApiResponse.Ok(result, $"일자별 {rows.Count}건")
        Catch ex As Exception
            _logger.Errors($"[GetProgramTradeByDay] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>실시간 프로그램매매 구독</summary>
    Public Async Function SubscribeProgramTradeAsync(codes As String()) As Task(Of ApiResponse)
        Try
            Await UiInvokeAsync(Sub()
                                    For Each c As String In codes
                                        If Not String.IsNullOrWhiteSpace(c) Then
                                            _cybos.SubscribeProgramTrade(c.Trim())
                                        End If
                                    Next
                                End Sub)
            Return ApiResponse.Ok(Nothing, $"프로그램매매 실시간 구독: {String.Join(",", codes)}")
        Catch ex As Exception
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>실시간 프로그램매매 해지</summary>
    Public Async Function UnsubscribeProgramTradeAsync(codes As String()) As Task(Of ApiResponse)
        Try
            Await UiInvokeAsync(Sub()
                                    If codes Is Nothing OrElse codes.Length = 0 OrElse
                                       (codes.Length = 1 AndAlso codes(0).ToUpper() = "ALL") Then
                                        _cybos.UnsubscribeAllProgramTrade()
                                    Else
                                        For Each c As String In codes
                                            If Not String.IsNullOrWhiteSpace(c) Then
                                                _cybos.UnsubscribeProgramTrade(c.Trim())
                                            End If
                                        Next
                                    End If
                                End Sub)
            Return ApiResponse.Ok(Nothing, $"프로그램매매 구독 해지: {String.Join(",", codes)}")
        Catch ex As Exception
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function
    '///////////프로그램 순매수정보 삽입 완료/////////////////////////////


    ' ----- TR Event Handler (The Brain) -----
    Private Sub OnReceiveTrData(sender As Object, e As _DKHOpenAPIEvents_OnReceiveTrDataEvent)
        Dim rqName As String = If(e.sRQName, String.Empty).Trim()
        Dim tcs As TaskCompletionSource(Of TrResult) = Nothing
        If Not _pendingTr.TryGetValue(rqName, tcs) Then
            Dim altKey = _pendingTr.Keys.FirstOrDefault(Function(k) k.StartsWith(e.sTrCode & "_", StringComparison.OrdinalIgnoreCase))
            If altKey Is Nothing OrElse Not _pendingTr.TryGetValue(altKey, tcs) Then
                _logger.Warn($"[TR] Unknown RQName '{rqName}' for TR {e.sTrCode}")
                Return
            End If
            rqName = altKey
        End If

        Dim rows As New List(Of Dictionary(Of String, String))
        Dim cnt = _api.GetRepeatCnt(e.sTrCode, rqName)

        Dim keys As String() = {}
        Dim singleKeys As String() = {}

        Select Case e.sTrCode
            Case "OPT10081" ' 일봉
                keys = New String() {"일자", "시가", "고가", "저가", "현재가", "거래량"}
            Case "OPT10080" ' 분봉
                keys = New String() {"체결시간", "시가", "고가", "저가", "현재가", "거래량"}
            Case "OPT10079" ' 틱
                keys = New String() {"체결시간", "시가", "고가", "저가", "현재가", "거래량"}
            Case "OPW00018" ' 계좌평가잔고
                keys = New String() {
                    "종목명",
                    "종목번호",
                    "현재가",
                    "전일대비",
                    "전일대비기호",
                    "보유수량",
                    "주문가능수량",
                    "매입가",
                    "매입단가",
                    "매입금액",
                    "평가금액",
                    "평가손익",
                    "수익률(%)",
                    "손익률",
                    "손익률(%)"
                }
                singleKeys = New String() {
                    "총매입금액",
                    "총평가금액",
                    "총평가손익금액",
                    "총수익률(%)",
                    "추정예탁자산",
                    "실현손익",
                    "예수금"
                }
            Case "OPW00001" ' 예수금
                singleKeys = New String() {"예수금", "출금가능금액", "주문가능금액"}
            Case "OPT10075" ' 미체결
                keys = New String() {"주문번호", "종목코드", "주문구분", "주문가격", "주문수량", "미체결수량", "주문상태"}
            Case "OPTKWFID" ' 관심종목 정보 (조건검색 결과 상세)
                keys = New String() {"종목코드", "종목명", "현재가", "전일대비", "등락율", "거래량", "체결강도", "전일비 거래량 대비(%)", "시가", "고가", "저가"}
        End Select

        ' Multi Data
        If cnt > 0 AndAlso keys.Length > 0 Then
            For i As Integer = 0 To cnt - 1
                Dim d As New Dictionary(Of String, String)
                For Each k As String In keys
                    d(k) = _api.GetCommData(e.sTrCode, e.sRQName, i, k).Trim()
                Next
                rows.Add(d)
            Next
        End If

        ' Single Data
        If singleKeys.Length > 0 Then
            Dim sd As New Dictionary(Of String, String)
            For Each k As String In singleKeys
                sd(k) = _api.GetCommData(e.sTrCode, e.sRQName, 0, k).Trim()
            Next
            ' Add single data to result (Metadata style)
            If e.sTrCode = "OPW00018" Then
                sd("ROW_TYPE") = "SUMMARY"
                rows.Insert(0, sd)
            ElseIf e.sTrCode = "OPW00001" Then
                rows.Add(sd)
            End If
        End If

        ' Remove TCS
        Dim removed As TaskCompletionSource(Of TrResult) = Nothing
        _pendingTr.TryRemove(rqName, removed)

        ' Set Result (Rows + PrevNext)
        _logger.Info($"[TR] Completed {e.sTrCode}/{rqName} rows={rows.Count} prevNext={e.sPrevNext}")
        tcs.TrySetResult(New TrResult With {.Rows = rows, .PrevNext = e.sPrevNext})
    End Sub

    Public Function GetStatus() As KiwoomStatusData
        Return New KiwoomStatusData With {.IsLoggedIn = _isLoggedIn, .AccountNo = _accountNo}
    End Function
End Class
