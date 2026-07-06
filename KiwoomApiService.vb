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
    '///신규삽입
    'Private ReadOnly _conditionRequestLock As New Object()
    'Private Shared _conditionSearchScreenSeq As Integer = 9100
    Private Shared _conditionStreamScreenSeq As Integer = 9200

    Private _isLoggedIn As Boolean = False
    Private _accountNo As String = ""
    Private ReadOnly _dashboardLock As New Object()
    Private _lastDashboard As AccountSnapshot = Nothing
    Private Shared _kwRqSeq As Integer = 0
    Private Shared _trRqSeq As Integer = 0
    Private ReadOnly _defaultAccountPassword As String = ""

    '/////////////////////
    Private ReadOnly _conditionRequestLock As New Object()
    Private ReadOnly _conditionCacheLock As New Object()

    Private Shared _conditionSearchScreenSeq As Integer = 9100
    Private Const ConditionScreenReuseDelaySeconds As Integer = 60
    Private Const ConditionCacheTtlSeconds As Integer = 60

    Private Class ConditionCacheEntry
        Public Codes As String()
        Public FetchedAt As DateTime
    End Class

    Private ReadOnly _conditionCache As New Dictionary(Of String, ConditionCacheEntry)(StringComparer.OrdinalIgnoreCase)
    Private ReadOnly _conditionScreenLastUsed As New Dictionary(Of String, DateTime)(StringComparer.OrdinalIgnoreCase)



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

    '///신규추가

    Private Function BuildConditionCacheKey(name As String, index As Integer) As String
        Return index.ToString() & "|" & If(name, String.Empty).Trim()
    End Function

    Private Function TryGetConditionCache(name As String, index As Integer, ByRef codes As String()) As Boolean
        Dim key As String = BuildConditionCacheKey(name, index)

        SyncLock _conditionCacheLock
            Dim entry As ConditionCacheEntry = Nothing
            If Not _conditionCache.TryGetValue(key, entry) Then Return False
            If entry Is Nothing Then Return False

            Dim ageSeconds As Double = (DateTime.Now - entry.FetchedAt).TotalSeconds
            If ageSeconds > ConditionCacheTtlSeconds Then Return False

            codes = If(entry.Codes, Array.Empty(Of String)())
            Return True
        End SyncLock
    End Function

    Private Sub SaveConditionCache(name As String, index As Integer, codes As String())
        Dim key As String = BuildConditionCacheKey(name, index)

        SyncLock _conditionCacheLock
            _conditionCache(key) = New ConditionCacheEntry With {
            .Codes = If(codes, Array.Empty(Of String)()),
            .FetchedAt = DateTime.Now
        }
        End SyncLock
    End Sub

    Private Function NextConditionSearchScreen() As String
        Dim attempt As Integer

        For attempt = 0 To 99
            Dim seq As Integer = Threading.Interlocked.Increment(_conditionSearchScreenSeq)
            If seq > 9199 Then
                _conditionSearchScreenSeq = 9101
                seq = 9101
            End If

            Dim scr As String = seq.ToString()
            Dim canUse As Boolean = True

            SyncLock _conditionRequestLock
                Dim lastUsed As DateTime = DateTime.MinValue
                If _conditionScreenLastUsed.TryGetValue(scr, lastUsed) Then
                    If (DateTime.Now - lastUsed).TotalSeconds < ConditionScreenReuseDelaySeconds Then
                        canUse = False
                    End If
                End If

                If canUse Then
                    _conditionScreenLastUsed(scr) = DateTime.Now
                    Return scr
                End If
            End SyncLock
        Next

        Return "9000"
    End Function

    Private Sub ClearConditionResultTcs(expected As TaskCompletionSource(Of String()))
        SyncLock _conditionRequestLock
            If Object.ReferenceEquals(_condResultTcs, expected) Then
                _condResultTcs = Nothing
            End If
        End SyncLock
    End Sub


    Private Function UiInvokeAsync(Of T)(func As Func(Of T)) As Task(Of T)
        Dim tcs As New TaskCompletionSource(Of T)(TaskCreationOptions.RunContinuationsAsynchronously)

        If _api.InvokeRequired Then
            _api.BeginInvoke(New MethodInvoker(Sub()
                                                   Try
                                                       Dim value As T = func()
                                                       tcs.TrySetResult(value)
                                                   Catch ex As Exception
                                                       tcs.TrySetException(ex)
                                                   End Try
                                               End Sub))
        Else
            Try
                Dim value As T = func()
                tcs.TrySetResult(value)
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

    '///신규추가(2026/07/06)
    'Private Function NextConditionSearchScreen() As String
    '    Dim seq As Integer = Threading.Interlocked.Increment(_conditionSearchScreenSeq)
    '    If seq > 9199 Then
    '        _conditionSearchScreenSeq = 9101
    '        seq = 9101
    '    End If
    '    Return seq.ToString()
    'End Function

    Private Function NextConditionStreamScreen() As String
        Dim seq As Integer = Threading.Interlocked.Increment(_conditionStreamScreenSeq)
        If seq > 9299 Then
            _conditionStreamScreenSeq = 9201
            seq = 9201
        End If
        Return seq.ToString()
    End Function

    Private Function NormalizeConditionCodeList(raw As String) As String()
        If String.IsNullOrWhiteSpace(raw) Then Return Array.Empty(Of String)()

        Return raw.Split(";"c).
        Select(Function(s) If(s, String.Empty).Trim()).
        Where(Function(s) s.Length > 0).
        Select(Function(s)
                   If s.StartsWith("A", StringComparison.OrdinalIgnoreCase) AndAlso s.Length = 7 Then
                       Return s.Substring(1)
                   End If
                   Return s
               End Function).
        ToArray()
    End Function

    'Private Sub ClearConditionResultTcs(expected As TaskCompletionSource(Of String()))
    '    SyncLock _conditionRequestLock
    '        If Object.ReferenceEquals(_condResultTcs, expected) Then
    '            _condResultTcs = Nothing
    '        End If
    '    End SyncLock
    'End Sub

    Private Sub StopConditionSafe(screen As String, name As String, index As Integer)
        Try
            UiInvoke(Of Object)(Function()
                                    _api.SendConditionStop(screen, name, index)
                                    Return Nothing
                                End Function)
        Catch ex As Exception
            _logger.Warn($"[Condition] SendConditionStop failed. screen={screen}, name={name}, index={index}, error={ex.Message}")
        End Try
    End Sub
    '/////////////////////////////


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

    '///신규교체
    Public Async Function SearchConditionAsync(name As String, index As Integer) As Task(Of ApiResponse)
        If String.IsNullOrWhiteSpace(name) Then
            Return ApiResponse.Err("Condition name is required", 400)
        End If

        Dim cachedCodes As String() = Nothing
        If TryGetConditionCache(name, index, cachedCodes) Then
            Dim cachedPayload = New With {
            .Codes = cachedCodes,
            .Stocks = New List(Of Dictionary(Of String, String))(),
            .Cached = True,
            .CacheTtlSeconds = ConditionCacheTtlSeconds
        }

            Return ApiResponse.Ok(cachedPayload, "OK (cached)")
        End If

        Dim scr As String = NextConditionSearchScreen()
        Dim localTcs As New TaskCompletionSource(Of String())(TaskCreationOptions.RunContinuationsAsynchronously)

        SyncLock _conditionRequestLock
            If _condResultTcs IsNot Nothing Then
                Return ApiResponse.Err("Another condition search is already pending", 429)
            End If

            _condResultTcs = localTcs
        End SyncLock

        Dim sendRet As Integer = -1

        Try
            Await UiInvokeAsync(Sub()
                                    sendRet = _api.SendCondition(scr, name, index, 0)
                                End Sub)

            If sendRet <> 1 Then
                ClearConditionResultTcs(localTcs)
                Return ApiResponse.Err(
                $"SendCondition failed. name={name}, index={index}, screen={scr}, ret={sendRet}. Possible Kiwoom screen reuse/state issue.",
                502)
            End If

            Dim done As Task = Await Task.WhenAny(localTcs.Task, Task.Delay(30000))

            If done IsNot localTcs.Task Then
                ClearConditionResultTcs(localTcs)
                Return ApiResponse.Err(
                $"SearchCondition Timeout. name={name}, index={index}, screen={scr}, ret={sendRet}",
                504)
            End If

            If localTcs.Task.IsFaulted Then
                ClearConditionResultTcs(localTcs)
                Dim msg As String = localTcs.Task.Exception.GetBaseException().Message
                Return ApiResponse.Err(
                $"SearchCondition result exception. name={name}, index={index}, screen={scr}, error={msg}",
                500)
            End If

            Dim codes As String() = localTcs.Task.Result
            If codes Is Nothing Then codes = Array.Empty(Of String)()

            ClearConditionResultTcs(localTcs)
            SaveConditionCache(name, index, codes)

            Dim payload = New With {
            .Codes = codes,
            .Stocks = New List(Of Dictionary(Of String, String))(),
            .Cached = False,
            .Screen = scr,
            .CacheTtlSeconds = ConditionCacheTtlSeconds
        }

            Return ApiResponse.Ok(payload)

        Catch ex As Exception
            ClearConditionResultTcs(localTcs)
            Return ApiResponse.Err(
            $"SearchCondition exception. name={name}, index={index}, screen={scr}, ret={sendRet}, error={ex.Message}",
            500)
        End Try
    End Function

    'Public Async Function SearchConditionAsync(name As String, index As Integer) As Task(Of ApiResponse)
    '    If String.IsNullOrWhiteSpace(name) Then
    '        Return ApiResponse.Err("Condition name is required", 400)
    '    End If

    '    Dim scr As String = GetNextConditionScreen()
    '    Dim localTcs As New TaskCompletionSource(Of String())(TaskCreationOptions.RunContinuationsAsynchronously)

    '    _condResultTcs = localTcs

    '    Dim sendRet As Integer = -1

    '    Try
    '        sendRet = Await UiInvokeAsync(Function()
    '                                          Return _api.SendCondition(scr, name, index, 0)
    '                                      End Function)

    '        If sendRet <> 1 Then
    '            Return ApiResponse.Err($"SendCondition failed. name={name}, index={index}, screen={scr}, ret={sendRet}", 502)
    '        End If

    '        Dim done = Await Task.WhenAny(localTcs.Task, Task.Delay(30000))

    '        If done IsNot localTcs.Task Then
    '            Try
    '                Await UiInvokeAsync(Sub() _api.SendConditionStop(scr, name, index))
    '            Catch ex As Exception
    '                _logger.Warn($"[Condition] SendConditionStop failed after timeout: {ex.Message}")
    '            End Try

    '            Return ApiResponse.Err($"SearchCondition Timeout. name={name}, index={index}, screen={scr}, ret={sendRet}", 504)
    '        End If

    '        Dim codes As String() = localTcs.Task.Result
    '        If codes Is Nothing Then codes = Array.Empty(Of String)()

    '        Dim payload = New With {
    '        .Codes = codes,
    '        .Stocks = New List(Of Dictionary(Of String, String))()
    '    }

    '        Try
    '            Await UiInvokeAsync(Sub() _api.SendConditionStop(scr, name, index))
    '        Catch ex As Exception
    '            _logger.Warn($"[Condition] SendConditionStop failed after success: {ex.Message}")
    '        End Try

    '        Return ApiResponse.Ok(payload)

    '    Catch ex As Exception
    '        Try
    '            Await UiInvokeAsync(Sub() _api.SendConditionStop(scr, name, index))
    '        Catch
    '        End Try

    '        Return ApiResponse.Err($"SearchCondition exception. name={name}, index={index}, screen={scr}, ret={sendRet}, error={ex.Message}", 500)
    '    Finally
    '        If Object.ReferenceEquals(_condResultTcs, localTcs) Then
    '            _condResultTcs = Nothing
    '        End If
    '    End Try
    'End Function

    Private _conditionScreenSeq As Integer = 9100

    Private Function GetNextConditionScreen() As String
        _conditionScreenSeq += 1
        If _conditionScreenSeq > 9199 Then _conditionScreenSeq = 9101
        Return _conditionScreenSeq.ToString()
    End Function

    '///신규교체
    Public Async Function StartConditionStreamAsync(name As String, index As Integer, screen As String) As Task(Of ApiResponse)
        If String.IsNullOrWhiteSpace(name) Then
            Return ApiResponse.Err("Condition name is required", 400)
        End If

        Dim scr As String = If(String.IsNullOrWhiteSpace(screen), NextConditionStreamScreen(), screen.Trim())

        Dim sendTask As Task(Of Integer) = UiInvokeAsync(Of Integer)(Function()
                                                                         Return _api.SendCondition(scr, name, index, 1)
                                                                     End Function)

        Dim sendDone As Task = Await Task.WhenAny(sendTask, Task.Delay(5000))

        If sendDone IsNot sendTask Then
            StopConditionSafe(scr, name, index)
            Return ApiResponse.Err($"SendCondition stream call timeout. name={name}, index={index}, screen={scr}", 504)
        End If

        If sendTask.IsFaulted Then
            StopConditionSafe(scr, name, index)

            Dim msg As String = sendTask.Exception.GetBaseException().Message
            Return ApiResponse.Err($"SendCondition stream exception. name={name}, index={index}, screen={scr}, error={msg}", 500)
        End If

        Dim sendRet As Integer = sendTask.Result

        If sendRet <> 1 Then
            StopConditionSafe(scr, name, index)
            Return ApiResponse.Err($"SendCondition stream failed. name={name}, index={index}, screen={scr}, ret={sendRet}", 502)
        End If

        Dim payload = New With {
        .Name = name,
        .Index = index,
        .Screen = scr,
        .Ret = sendRet
    }

        Return ApiResponse.Ok(payload, $"Condition stream started: {name} ({index}) @ {scr}")
    End Function



    'Public Async Function StartConditionStreamAsync(name As String, index As Integer, screen As String) As Task(Of ApiResponse)
    '    Dim scr = If(String.IsNullOrWhiteSpace(screen), "9001", screen)
    '    Await UiInvokeAsync(Sub() _api.SendCondition(scr, name, index, 1))
    '    Return ApiResponse.Ok(Nothing, $"Condition stream started: {name} ({index}) @ {scr}")
    'End Function

    '///신규교체
    Public Function StopConditionStream(name As String, index As Integer, screen As String) As ApiResponse
        If String.IsNullOrWhiteSpace(name) Then
            Return ApiResponse.Err("Condition name is required", 400)
        End If

        Dim scr As String = If(String.IsNullOrWhiteSpace(screen), "9001", screen.Trim())

        Try
            UiInvoke(Of Object)(Function()
                                    _api.SendConditionStop(scr, name, index)
                                    Return Nothing
                                End Function)

            Dim payload = New With {
            .Name = name,
            .Index = index,
            .Screen = scr
        }

            Return ApiResponse.Ok(payload, $"Condition stream stopped: {name} ({index}) @ {scr}")

        Catch ex As Exception
            Return ApiResponse.Err($"StopConditionStream exception. name={name}, index={index}, screen={scr}, error={ex.Message}", 500)
        End Try
    End Function

    'Public Function StopConditionStream(name As String, index As Integer, screen As String) As ApiResponse
    '    Dim scr = If(String.IsNullOrWhiteSpace(screen), "9001", screen)
    '    UiInvoke(Of Object)(Function()
    '                            _api.SendConditionStop(scr, name, index)
    '                            Return Nothing
    '                        End Function)
    '    Return ApiResponse.Ok(Nothing, $"Condition stream stopped: {name} ({index})")
    'End Function

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
        Dim account As String = GetChejanValue(raw, "9201")
        If String.IsNullOrWhiteSpace(account) OrElse Not String.Equals(account.Trim(), _accountNo) Then Return Nothing

        Dim code As String = NormalizeStockCode(GetChejanValue(raw, "9001"))
        If String.IsNullOrEmpty(code) Then Return Nothing

        Dim name As String = GetChejanValue(raw, "302")
        Dim qty As Double = ParseNumericValue(GetChejanValue(raw, "930"))
        Dim availQty As Double = ParseNumericValue(GetChejanValue(raw, "933"))
        Dim currentPrice As Double = ParseNumericValue(GetChejanValue(raw, "10"))
        Dim purchaseAmount As Double = ParseNumericValue(GetChejanValue(raw, "932"))
        Dim purchasePrice As Double = ParseNumericValue(GetChejanValue(raw, "931"))
        Dim pnlRate As Double = ParseNumericValue(GetChejanValue(raw, "8019"))
        Dim deposit As Double = ParseNumericValue(GetChejanValue(raw, "951"))

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
            Dim snap As AccountSnapshot = EnsureDashboardSnapshot()
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


    '///신규교체
    Private Sub OnReceiveTrCondition(sender As Object, e As _DKHOpenAPIEvents_OnReceiveTrConditionEvent)
        Try
            Dim codes As String() = NormalizeConditionCodeList(e.strCodeList)

            Dim tcs As TaskCompletionSource(Of String()) = Nothing
            SyncLock _conditionRequestLock
                tcs = _condResultTcs
            End SyncLock

            If tcs IsNot Nothing Then
                tcs.TrySetResult(codes)
            Else
                _logger.Info($"[Condition] OnReceiveTrCondition without pending search. name={e.strConditionName}, index={e.nIndex}, count={codes.Length}")
            End If

        Catch ex As Exception
            Dim tcs As TaskCompletionSource(Of String()) = Nothing
            SyncLock _conditionRequestLock
                tcs = _condResultTcs
            End SyncLock

            If tcs IsNot Nothing Then
                tcs.TrySetException(ex)
            End If

            _logger.Errors($"[Condition] OnReceiveTrCondition failed: {ex.Message}")
        End Try
    End Sub

    'Private Sub OnReceiveTrCondition(sender As Object, e As _DKHOpenAPIEvents_OnReceiveTrConditionEvent)
    '    Dim codes = If(e.strCodeList, "").Split(";"c).Where(Function(s) s.Length > 0).ToArray()
    '    _condResultTcs?.TrySetResult(codes)
    'End Sub

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
    '///Private Shared ReadOnly _cybosCandleSlots As New SemaphoreSlim(3, 3)
    Private Shared ReadOnly _cybosCandleSlots As New SemaphoreSlim(1, 1)

    '///새 로직
    Private Shared Async Function RunCybosCandleRequestAsync(code As String,
                                                        timeframe As String,
                                                        fromDate As String,
                                                        toDate As String) As Task(Of List(Of Candle))
        Await _cybosCandleSlots.WaitAsync().ConfigureAwait(False)

        Try
            Return Await RunOnStaThreadAsync(Function()
                                                 Dim cybosClient As New Cybos()
                                                 Return cybosClient.DownloadCandlesByPeriod(code, timeframe, fromDate, toDate)
                                             End Function).ConfigureAwait(False)

        Catch ex As Exception
            Throw New InvalidOperationException(
            $"Cybos candle request failed. code={code}, timeframe={timeframe}, fromDate={fromDate}, toDate={toDate}, error={ex.Message}",
            ex)

        Finally
            _cybosCandleSlots.Release()
        End Try
    End Function

    'Private Shared Async Function RunCybosCandleRequestAsync(code As String,
    '                                                        timeframe As String,
    '                                                        fromDate As String,
    '                                                        toDate As String) As Task(Of List(Of Candle))
    '    Await _cybosCandleSlots.WaitAsync().ConfigureAwait(False)
    '    Try
    '        Return Await RunOnStaThreadAsync(Function()
    '                                             Dim cybosClient As New Cybos()
    '                                             Return cybosClient.DownloadCandlesByPeriod(code, timeframe, fromDate, toDate)
    '                                         End Function).ConfigureAwait(False)
    '    Finally
    '        _cybosCandleSlots.Release()
    '    End Try
    'End Function

    Private Shared Function RunOnStaThreadAsync(Of T)(work As Func(Of T)) As Task(Of T)
        Dim tcs As New TaskCompletionSource(Of T)()
        Dim worker As New Thread(Sub()
                                     Try
                                         tcs.SetResult(work())
                                     Catch ex As Exception
                                         tcs.SetException(ex)
                                     End Try
                                 End Sub)
        worker.IsBackground = True
        worker.SetApartmentState(ApartmentState.STA)
        worker.Start()
        Return tcs.Task
    End Function

    ' 일봉: date(최신, YYYYMMDD) -> stopDate(과거)
    Public Async Function GetDailyCandlesAsync(code As String, [date] As String, stopDate As String) As Task(Of ApiResponse)
        Try
            ' Cybos Period: From(Past) ~ To(Recent)
            ' Kiwoom Req: StopDate(Past) ~ Date(Recent)
            ' So From = StopDate, To = Date (or Now)
            Dim toDate As String = If(String.IsNullOrEmpty([date]), DateTime.Now.ToString("yyyyMMdd"), [date])
            Dim fromDate As String = stopDate

            Dim candles = Await RunCybosCandleRequestAsync(code, "D", fromDate, toDate)

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
                d("거래대금") = c.TradingValue.ToString()
                d("등락률") = c.ChangeRate.ToString()
                d("대비부호") = c.ChangeSign.ToString()
                d("상장주식수") = c.SharesOutstanding.ToString()
                d("시가총액") = c.MarketCap.ToString()
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

            Dim candles = Await RunCybosCandleRequestAsync(code, "m" & tick, fromDate, toDate)

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

            Dim candles = Await RunCybosCandleRequestAsync(code, "T" & tick, fromDate, toDate)

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

    '$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$

    '///////////MarketEye / StockMember / InvestorTrend / Keyframe 핸들러 삽입 시작/////

    ''' <summary>MarketEye 일괄 수급 조회 (최대 200종목)</summary>
    Public Async Function GetMarketEyeSupplyAsync(codes As String()) As Task(Of ApiResponse)
        Try
            If codes Is Nothing OrElse codes.Length = 0 Then
                Return ApiResponse.Err("codes required", 400)
            End If

            Dim items As List(Of Cybos.MarketEyeItem) = Nothing

            Await UiInvokeAsync(Sub()
                                    items = _cybos.FetchMarketEyeSupply(codes)
                                End Sub)

            If items Is Nothing Then items = New List(Of Cybos.MarketEyeItem)

            Dim result As New List(Of Dictionary(Of String, Object))
            For Each item As Cybos.MarketEyeItem In items
                Dim d As New Dictionary(Of String, Object)
                d("종목코드") = item.Code
                d("종목명") = item.StockName
                d("현재가") = item.CurrentPrice
                d("대비부호") = item.DiffSign
                d("전일대비") = item.Diff
                d("시가") = item.Open
                d("고가") = item.High
                d("저가") = item.Low
                d("거래량") = item.Volume
                d("거래대금_원") = item.TradeValue
                d("전일거래량") = item.PrevVolume
                d("체결강도") = item.Intensity
                d("총매도호가잔량") = item.TotalAskRemain
                d("총매수호가잔량") = item.TotalBidRemain
                d("외국인보유비율") = item.ForeignHoldRatio
                d("외국인순매매_주") = item.ForeignNetShares
                d("프로그램순매수") = item.ProgramNet
                d("당일외국인잠정구분") = item.ForeignConfirm
                d("당일외국인순매수") = item.ForeignNetToday
                d("당일기관잠정구분") = item.InstConfirm
                d("당일기관순매수") = item.InstNetToday
                d("당일개인잠정구분") = item.IndividualConfirm
                d("당일개인순매수") = item.IndividualNetToday
                d("신용잔고율") = item.CreditRatio
                ' 파생 지표
                d("호가잔량비율") = If(item.TotalAskRemain > 0,
                    Math.Round(CDbl(item.TotalBidRemain) / CDbl(item.TotalAskRemain), 3), 0.0)
                result.Add(d)
            Next

            Return ApiResponse.Ok(result, $"MarketEye {items.Count}종목 조회 완료")
        Catch ex As Exception
            _logger.Errors($"[GetMarketEyeSupply] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>5대 매매창구 (단일 종목)</summary>
    Public Async Function GetStockMemberTop5Async(code As String) As Task(Of ApiResponse)
        Try
            If String.IsNullOrWhiteSpace(code) Then
                Return ApiResponse.Err("code required", 400)
            End If

            Dim memberResult As Cybos.StockMemberResult = Nothing
            Await UiInvokeAsync(Sub()
                                    memberResult = _cybos.FetchStockMemberTop5(code)
                                End Sub)

            If memberResult Is Nothing Then
                Return ApiResponse.Err("StockMember data not available")
            End If

            Dim d As New Dictionary(Of String, Object)
            d("종목코드") = memberResult.Code
            d("시각") = memberResult.Timestamp
            d("액면가") = memberResult.FaceValue
            d("매수상위5합계") = memberResult.Top5BuyTotal
            d("매도상위5합계") = memberResult.Top5SellTotal

            Dim membersList As New List(Of Dictionary(Of String, Object))
            For Each m As Cybos.StockMemberItem In memberResult.Members
                membersList.Add(New Dictionary(Of String, Object) From {
                    {"순위", m.Rank},
                    {"매도거래원", m.SellMemberName},
                    {"매수거래원", m.BuyMemberName},
                    {"매도수량", m.SellQty},
                    {"매수수량", m.BuyQty}
                })
            Next
            d("거래원목록") = membersList

            Return ApiResponse.Ok(d, $"5대창구 {memberResult.Members.Count}건")
        Catch ex As Exception
            _logger.Errors($"[GetStockMemberTop5] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>5대 창구 일괄 조회 (복수 종목, 종목당 200ms 간격)</summary>
    Public Async Function GetStockMemberBatchAsync(codes As String()) As Task(Of ApiResponse)
        Try
            If codes Is Nothing OrElse codes.Length = 0 Then
                Return ApiResponse.Err("codes required", 400)
            End If

            Dim allResults As New List(Of Dictionary(Of String, Object))

            For Each code As String In codes
                If String.IsNullOrWhiteSpace(code) Then Continue For

                Dim memberResult As Cybos.StockMemberResult = Nothing
                Await UiInvokeAsync(Sub()
                                        memberResult = _cybos.FetchStockMemberTop5(code.Trim())
                                    End Sub)

                If memberResult Is Nothing OrElse memberResult.Members.Count = 0 Then Continue For

                Dim d As New Dictionary(Of String, Object)
                d("종목코드") = memberResult.Code
                d("매수상위5합계") = memberResult.Top5BuyTotal
                d("매도상위5합계") = memberResult.Top5SellTotal

                Dim membersList As New List(Of Dictionary(Of String, Object))
                For Each m As Cybos.StockMemberItem In memberResult.Members
                    membersList.Add(New Dictionary(Of String, Object) From {
                        {"순위", m.Rank},
                        {"매도거래원", m.SellMemberName},
                        {"매수거래원", m.BuyMemberName},
                        {"매도수량", m.SellQty},
                        {"매수수량", m.BuyQty}
                    })
                Next
                d("거래원목록") = membersList
                allResults.Add(d)

                Await Task.Delay(200)
            Next

            Return ApiResponse.Ok(allResults, $"5대창구 일괄조회 {allResults.Count}종목")
        Catch ex As Exception
            _logger.Errors($"[GetStockMemberBatch] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>투자자별 매매동향 잠정 (CpSvr7210d)</summary>
    Public Async Function GetInvestorTrendAsync(investType As Integer,
                                                 Optional marketType As String = "0",
                                                 Optional valueType As String = "0",
                                                 Optional sortOrder As String = "0") As Task(Of ApiResponse)
        Try
            Dim items As List(Of Cybos.InvestorTrendItem) = Nothing
            Await UiInvokeAsync(Sub()
                                    items = _cybos.FetchInvestorTrend(investType, marketType, valueType, sortOrder)
                                End Sub)

            If items Is Nothing Then items = New List(Of Cybos.InvestorTrendItem)

            Dim result As New List(Of Dictionary(Of String, Object))
            For Each item As Cybos.InvestorTrendItem In items
                result.Add(New Dictionary(Of String, Object) From {
                    {"종목코드", item.Code},
                    {"종목명", item.Name},
                    {"현재가", item.CurrentPrice},
                    {"전일대비", item.Diff},
                    {"대비율", item.DiffRate},
                    {"거래량", item.Volume},
                    {"외국인순매수", item.ForeignNet},
                    {"기관순매수", item.InstNet},
                    {"보험기타순매수", item.InsuranceNet},
                    {"투신순매수", item.TrustNet},
                    {"은행순매수", item.BankNet},
                    {"연기금순매수", item.PensionNet},
                    {"국가지자체순매수", item.GovNet},
                    {"기타법인순매수", item.EtcCorpNet}
                })
            Next

            Dim investName As String = ""
            Select Case investType
                Case 0 : investName = "종합"
                Case 1 : investName = "외국인"
                Case 2 : investName = "기관계"
                Case 3 : investName = "보험기타"
                Case 4 : investName = "투신"
                Case 5 : investName = "은행"
                Case 6 : investName = "연기금"
                Case 7 : investName = "기타법인"
                Case 8 : investName = "개인"
                Case Else : investName = $"유형{investType}"
            End Select

            Return ApiResponse.Ok(result, $"투자자동향({investName}) {items.Count}건")
        Catch ex As Exception
            _logger.Errors($"[GetInvestorTrend] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    ''' <summary>키프레임 통합 캡처 (MarketEye + 5대창구 + 프로그램매매)</summary>
    Public Async Function CaptureKeyframeAsync(code As String) As Task(Of ApiResponse)
        Try
            If String.IsNullOrWhiteSpace(code) Then
                Return ApiResponse.Err("code required", 400)
            End If

            Dim cleanCode = code.Trim()
            Dim keyframe As New Dictionary(Of String, Object)
            keyframe("capture_time") = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff")
            keyframe("종목코드") = cleanCode

            ' 1) MarketEye 수급 데이터
            Dim supplyItems As List(Of Cybos.MarketEyeItem) = Nothing
            Await UiInvokeAsync(Sub()
                                    supplyItems = _cybos.FetchMarketEyeSupply({cleanCode})
                                End Sub)

            If supplyItems IsNot Nothing AndAlso supplyItems.Count > 0 Then
                Dim s = supplyItems(0)
                Dim supplyData As New Dictionary(Of String, Object)
                supplyData("종목명") = s.StockName
                supplyData("현재가") = s.CurrentPrice
                supplyData("시가") = s.Open
                supplyData("고가") = s.High
                supplyData("저가") = s.Low
                supplyData("거래량") = s.Volume
                supplyData("거래대금_원") = s.TradeValue
                supplyData("체결강도") = s.Intensity
                supplyData("총매도호가잔량") = s.TotalAskRemain
                supplyData("총매수호가잔량") = s.TotalBidRemain
                supplyData("호가잔량비율") = If(s.TotalAskRemain > 0,
                    Math.Round(CDbl(s.TotalBidRemain) / CDbl(s.TotalAskRemain), 3), 0.0)
                supplyData("외국인보유비율") = s.ForeignHoldRatio
                supplyData("외국인순매매_주") = s.ForeignNetShares
                supplyData("프로그램순매수") = s.ProgramNet
                supplyData("당일외국인순매수") = s.ForeignNetToday
                supplyData("당일외국인잠정구분") = s.ForeignConfirm
                supplyData("당일기관순매수") = s.InstNetToday
                supplyData("당일기관잠정구분") = s.InstConfirm
                supplyData("당일개인순매수") = s.IndividualNetToday
                supplyData("신용잔고율") = s.CreditRatio
                keyframe("supply") = supplyData
            Else
                keyframe("supply") = Nothing
            End If

            Await Task.Delay(200) ' Rate limit 방어

            ' 2) 5대 창구 데이터
            Dim memberResult As Cybos.StockMemberResult = Nothing
            Await UiInvokeAsync(Sub()
                                    memberResult = _cybos.FetchStockMemberTop5(cleanCode)
                                End Sub)

            If memberResult IsNot Nothing AndAlso memberResult.Members.Count > 0 Then
                Dim memberData As New Dictionary(Of String, Object)
                memberData("매수상위5합계") = memberResult.Top5BuyTotal
                memberData("매도상위5합계") = memberResult.Top5SellTotal

                Dim membersList As New List(Of Dictionary(Of String, Object))
                For Each m As Cybos.StockMemberItem In memberResult.Members
                    membersList.Add(New Dictionary(Of String, Object) From {
                        {"순위", m.Rank},
                        {"매도거래원", m.SellMemberName},
                        {"매수거래원", m.BuyMemberName},
                        {"매도수량", m.SellQty},
                        {"매수수량", m.BuyQty}
                    })
                Next
                memberData("거래원목록") = membersList

                If supplyItems IsNot Nothing AndAlso supplyItems.Count > 0 AndAlso supplyItems(0).Volume > 0 Then
                    memberData("매수집중도") = Math.Round(
                        CDbl(memberResult.Top5BuyTotal) / CDbl(supplyItems(0).Volume), 4)
                End If
                keyframe("members") = memberData
            Else
                keyframe("members") = Nothing
            End If

            Await Task.Delay(200)

            ' 3) 프로그램매매 시간대별 (최신 데이터)
            Dim pgmItems As List(Of Cybos.ProgramTradeByTime) = Nothing
            Await UiInvokeAsync(Sub()
                                    pgmItems = _cybos.DownloadProgramTradeByTimeSync(cleanCode, "A")
                                End Sub)

            If pgmItems IsNot Nothing AndAlso pgmItems.Count > 0 Then
                Dim latest = pgmItems(0)
                keyframe("program") = New Dictionary(Of String, Object) From {
                    {"시간", latest.Time},
                    {"프로그램매수수량", latest.PgmBuyQty},
                    {"프로그램매도수량", latest.PgmSellQty},
                    {"프로그램순매수수량", latest.PgmNetQty},
                    {"프로그램순매수수량증감", latest.PgmNetQtyChange},
                    {"프로그램매수금액_천원", latest.PgmBuyAmt},
                    {"프로그램매도금액_천원", latest.PgmSellAmt},
                    {"프로그램순매수금액_천원", latest.PgmNetAmt},
                    {"프로그램순매수금액증감_천원", latest.PgmNetAmtChange}
                }
            Else
                keyframe("program") = Nothing
            End If

            Return ApiResponse.Ok(keyframe, $"키프레임 캡처 완료: {cleanCode}")
        Catch ex As Exception
            _logger.Errors($"[CaptureKeyframe] {ex.Message}")
            Return ApiResponse.Err(ex.Message, 500)
        End Try
    End Function

    '///////////MarketEye / StockMember / InvestorTrend / Keyframe 핸들러 삽입 완료/////



    '$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$








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
