Imports System.Collections.Concurrent
Imports System.Threading.Tasks
Imports AxKHOpenAPILib
Imports Newtonsoft.Json
Imports WebSocketSharp
Imports WebSocketSharp.Server

Public Class ExecutionWebSocketBehavior
    Inherits WebSocketBehavior

    Private ReadOnly _hub As ExecutionHub

    Public Sub New(hub As ExecutionHub)
        _hub = hub
    End Sub

    Protected Overrides Sub OnOpen()
        _hub.Add(ID, Me)
    End Sub

    Protected Overrides Sub OnClose(e As CloseEventArgs)
        _hub.Remove(ID)
    End Sub
End Class

Public Class ExecutionHub
    Private ReadOnly _api As AxKHOpenAPILib.AxKHOpenAPI
    Private ReadOnly _logger As SimpleLogger
    Private ReadOnly _sessions As New ConcurrentDictionary(Of String, ExecutionWebSocketBehavior)
    Private ReadOnly _apiService As KiwoomApiService
    Private _lastDashboardPayload As String = Nothing

    ' 수집할 FID 목록 (체결/잔고 관련)
    Private Shared ReadOnly ChejanFIDs As Integer() = {
        9201, 9203, 9001, 913, 302, 900, 901, 911, 10,
        930, 931, 932, 933, 950, 951, 952, 8019,
        9205, 908, 905, 909, 925, 926
    }

    Public Sub New(apiControl As AxKHOpenAPILib.AxKHOpenAPI, logger As SimpleLogger, apiService As KiwoomApiService)
        _api = apiControl
        _logger = logger
        _apiService = apiService
        AddHandler _api.OnReceiveChejanData, AddressOf OnReceiveChejanData
        StartInitialDashboardLoad()
    End Sub

    Public Sub Add(id As String, beh As ExecutionWebSocketBehavior)
        _sessions(id) = beh
        _logger.Info($"[EXEC-CONN] Client connected: {id}")
        Task.Run(Function() PushDashboardSnapshotAsync(False, beh))
    End Sub

    Public Sub Remove(id As String)
        Dim d As ExecutionWebSocketBehavior = Nothing
        _sessions.TryRemove(id, d)
        _logger.Info($"[EXEC-DISC] Client disconnected: {id}")
    End Sub

    Private Sub OnReceiveChejanData(sender As Object, e As _DKHOpenAPIEvents_OnReceiveChejanDataEvent)
        Try
            ' gubun: 0(접수/체결/확인), 1(잔고), 4(파생잔고)
            Dim gubun As String = e.sGubun

            Dim rawData As New Dictionary(Of String, String)
            rawData("gubun") = gubun

            For Each fid As Integer In ChejanFIDs
                Dim val = _api.GetChejanData(fid.ToString())
                If Not String.IsNullOrEmpty(val) Then
                    rawData(fid.ToString()) = val.Trim()
                End If
            Next

            ' Standard JSON Structure
            Dim stdType As String = "unknown"
            If gubun = "0" Then
                stdType = "order" ' 체결/접수/취소
            ElseIf gubun = "1" Then
                stdType = "balance" ' 잔고
            End If

            Dim payload = New With {
                .type = stdType,
                .timestamp = DateTime.Now.ToString("yyyyMMddHHmmss"),
                .data = rawData
            }

            Dim jsonStr = JsonConvert.SerializeObject(payload)
            Broadcast(jsonStr)

            _logger.Info($"[EXEC-PUSH] {stdType} -> {jsonStr.Length} chars")
            If stdType = "order" Then
                Task.Run(Function() PushDashboardSnapshotAsync(True))
            ElseIf stdType = "balance" Then
                Dim snapshotOverride = _apiService.ApplyBalanceChejan(rawData)
                Dim forceRefresh = snapshotOverride Is Nothing
                Task.Run(Function() PushDashboardSnapshotAsync(forceRefresh, Nothing, snapshotOverride))
            End If

        Catch ex As Exception
            _logger.Errors($"[EXEC-ERR] Parsing Chejan: {ex.Message}")
        End Try
    End Sub

    Private Sub Broadcast(msg As String)
        For Each s As ExecutionWebSocketBehavior In _sessions.Values
            Try
                s.Context.WebSocket.Send(msg)
            Catch
            End Try
        Next
    End Sub

    Private Sub StartInitialDashboardLoad()
        Task.Run(Async Function()
                     Try
                         Await PushDashboardSnapshotAsync(True)
                     Catch ex As Exception
                         _logger.Warn("[EXEC] Initial dashboard load error: " & ex.Message)
                     End Try
                 End Function)
    End Sub

    Private Async Function PushDashboardSnapshotAsync(forceRefresh As Boolean, Optional target As ExecutionWebSocketBehavior = Nothing, Optional snapshotOverride As AccountSnapshot = Nothing) As Task
        Dim resp As ApiResponse = Nothing
        If snapshotOverride IsNot Nothing Then
            resp = ApiResponse.Ok(snapshotOverride)
        Else
            Try
                If forceRefresh Then
                    resp = Await _apiService.RefreshDashboardDataAsync()
                Else
                    resp = _apiService.GetDashboardSnapshot()
                End If
            Catch ex As Exception
                _logger.Warn("[EXEC] Dashboard snapshot error: " & ex.Message)
                Return
            End Try
        End If

        If resp Is Nothing OrElse Not resp.Success OrElse resp.Data Is Nothing Then
            If forceRefresh AndAlso resp IsNot Nothing Then
                _logger.Warn("[EXEC] Dashboard refresh failed: " & resp.Message)
            End If
            Return
        End If

        Dim payload = New With {
            .type = "dashboard",
            .timestamp = DateTime.Now.ToString("yyyyMMddHHmmss"),
            .data = resp.Data
        }
        Dim jsonStr = JsonConvert.SerializeObject(payload)

        If target IsNot Nothing Then
            Try
                target.Context.WebSocket.Send(jsonStr)
            Catch
            End Try
        Else
            If _lastDashboardPayload IsNot Nothing AndAlso _lastDashboardPayload = jsonStr Then
                Return
            End If
            _lastDashboardPayload = jsonStr
            Broadcast(jsonStr)
        End If
    End Function
End Class
