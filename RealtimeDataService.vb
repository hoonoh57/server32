Imports System
Imports System.Collections.Concurrent
Imports AxKHOpenAPILib
Imports Newtonsoft.Json
Imports WebSocketSharp
Imports WebSocketSharp.Server

Public Class RealtimeWebSocketBehavior
    Inherits WebSocketBehavior
    Private ReadOnly _svc As RealtimeDataService
    Public Sub New(svc As RealtimeDataService)
        _svc = svc
    End Sub
    Protected Overrides Sub OnOpen()
        _svc.AddSession(ID, Me)
    End Sub
    Protected Overrides Sub OnClose(e As CloseEventArgs)
        _svc.RemoveSession(ID)
    End Sub
End Class

Public Class RealtimeDataService
    Private ReadOnly _api As AxKHOpenAPILib.AxKHOpenAPI
    Private ReadOnly _logger As SimpleLogger
    Private ReadOnly _sessions As New ConcurrentDictionary(Of String, RealtimeWebSocketBehavior)
    Private ReadOnly _lastPrices As New ConcurrentDictionary(Of String, Integer)

    Public Sub New(apiControl As AxKHOpenAPILib.AxKHOpenAPI, logger As SimpleLogger)
        _api = apiControl
        _logger = logger
        AddHandler _api.OnReceiveRealData, AddressOf OnReceiveRealData
        AddHandler _api.OnReceiveRealCondition, AddressOf OnReceiveRealCondition
    End Sub

    Public Sub AddSession(id As String, beh As RealtimeWebSocketBehavior)
        _sessions(id) = beh
    End Sub

    Private Sub OnReceiveRealCondition(sender As Object, e As _DKHOpenAPIEvents_OnReceiveRealConditionEvent)
        If _sessions.IsEmpty Then Return
        Dim status As String = If(String.Equals(e.strType, "I", StringComparison.OrdinalIgnoreCase), "enter", "exit")
        Dim payload = New With {
            .type = "condition",
            .code = e.sTrCode,
            .timestamp = DateTime.Now.ToString("yyyyMMddHHmmss"),
            .data = New With {
                .condition_name = e.strConditionName,
                .condition_index = e.strConditionIndex,
                .state = status
            }
        }
        BroadcastPayload(payload)
    End Sub

    Public Sub RemoveSession(id As String)
        Dim d As RealtimeWebSocketBehavior = Nothing
        _sessions.TryRemove(id, d)
    End Sub

    Public Sub Subscribe(screenNo As String, codes As String, fids As String, realType As String)
        _api.SetRealReg(screenNo, codes, fids, realType)
        _logger.Info($"[RT-SUB] scr={screenNo} codes={codes} fids={fids}")
    End Sub

    Public Sub Unsubscribe(screenNo As String, code As String)
        Dim scr As String = If(String.IsNullOrWhiteSpace(screenNo), "ALL", screenNo.Trim())
        Dim cd As String = If(String.IsNullOrWhiteSpace(code), "ALL", code.Trim())
        _api.SetRealRemove(scr, cd)
        _logger.Info($"[RT-UNSUB] scr={scr} code={cd}")
    End Sub

    Private Sub OnReceiveRealData(sender As Object, e As _DKHOpenAPIEvents_OnReceiveRealDataEvent)
        If _sessions.IsEmpty Then Return

        Dim realType As String = e.sRealType
        Dim key As String = e.sRealKey ' 종목코드

        Dim stdType As String = "unknown"
        Dim dataMap As New Dictionary(Of String, Object)

        ' 공통 시간 (FID 20)
        Dim rawTime = _api.GetCommRealData(realType, 20)
        If Not String.IsNullOrWhiteSpace(rawTime) Then
            dataMap("time") = rawTime.Trim()
        End If

        ' 가격/거래량은 틱 타입에서만 존재할 수 있으므로 값이 있을 때만 채운다.
        Dim rawPrice = _api.GetCommRealData(realType, 10)
        If HasValue(rawPrice) Then dataMap("current_price") = ParseInt(rawPrice)

        Dim rawDiff = _api.GetCommRealData(realType, 11)
        If HasValue(rawDiff) Then dataMap("diff") = ParseSignedInt(rawDiff)

        Dim rawRate = _api.GetCommRealData(realType, 12)
        If HasValue(rawRate) Then dataMap("rate") = ParseSignedDouble(rawRate)

        Dim rawVol = _api.GetCommRealData(realType, 15)
        If HasValue(rawVol) Then dataMap("volume") = ParseLong(rawVol)

        Dim rawCum = _api.GetCommRealData(realType, 13)
        If HasValue(rawCum) Then dataMap("cum_volume") = ParseLong(rawCum)

        Dim typeName As String = If(realType, String.Empty)
        If typeName.Contains("체결") Then
            stdType = "tick"
            Dim rawOpen = _api.GetCommRealData(realType, 16)
            If HasValue(rawOpen) Then dataMap("open") = ParseInt(rawOpen)

            Dim rawHigh = _api.GetCommRealData(realType, 17)
            If HasValue(rawHigh) Then dataMap("high") = ParseInt(rawHigh)

            Dim rawLow = _api.GetCommRealData(realType, 18)
            If HasValue(rawLow) Then dataMap("low") = ParseInt(rawLow)

            Dim rawIntensity = _api.GetCommRealData(realType, 228)
            If HasValue(rawIntensity) Then dataMap("intensity") = ParseDouble(rawIntensity)

            Dim tickPrice As Integer = 0
            If dataMap.ContainsKey("current_price") Then
                tickPrice = Convert.ToInt32(dataMap("current_price"))
            End If
            If tickPrice > 0 Then
                _lastPrices.AddOrUpdate(key, tickPrice, Function(k, prev) tickPrice)
            End If
        ElseIf typeName.Contains("호가") Then
            stdType = "hoga"
            Dim totalAsk = _api.GetCommRealData(realType, 121)
            If HasValue(totalAsk) Then dataMap("total_ask_vol") = ParseLong(totalAsk)

            Dim totalBid = _api.GetCommRealData(realType, 125)
            If HasValue(totalBid) Then dataMap("total_bid_vol") = ParseLong(totalBid)

            For i As Integer = 1 To 5
                Dim askPrice = _api.GetCommRealData(realType, 40 + i)
                If HasValue(askPrice) Then dataMap($"ask_price_{i}") = ParseInt(askPrice)

                Dim askVol = _api.GetCommRealData(realType, 60 + i)
                If HasValue(askVol) Then dataMap($"ask_vol_{i}") = ParseLong(askVol)

                Dim bidPrice = _api.GetCommRealData(realType, 50 + i)
                If HasValue(bidPrice) Then dataMap($"bid_price_{i}") = ParseInt(bidPrice)

                Dim bidVol = _api.GetCommRealData(realType, 70 + i)
                If HasValue(bidVol) Then dataMap($"bid_vol_{i}") = ParseLong(bidVol)
            Next

            EnsureCurrentPriceFromFallback(key, dataMap)
        Else
            stdType = typeName
        End If

        ' [Standard Output]
        Dim payload = New With {
            .type = stdType,
            .code = key,
            .timestamp = DateTime.Now.ToString("yyyyMMddHHmmss"),
            .data = dataMap
        }

        BroadcastPayload(payload)
    End Sub

    Private Function HasValue(raw As String) As Boolean
        If String.IsNullOrWhiteSpace(raw) Then Return False
        Dim trimmed = raw.Trim()
        Return Not (trimmed = "+" OrElse trimmed = "-")
    End Function

    Private Function CleanUnsigned(raw As String) As String
        If String.IsNullOrWhiteSpace(raw) Then Return String.Empty
        Dim cleaned = raw.Trim()
        cleaned = cleaned.Replace(",", "").Replace(" ", "")
        cleaned = cleaned.Replace("+", "").Replace("-", "")
        Return cleaned
    End Function

    Private Function CleanSigned(raw As String, ByRef sign As Integer) As String
        sign = 1
        If String.IsNullOrWhiteSpace(raw) Then Return String.Empty
        Dim cleaned = raw.Trim().Replace(",", "").Replace(" ", "")
        If cleaned.StartsWith("+") Then
            cleaned = cleaned.Substring(1)
        ElseIf cleaned.StartsWith("-") Then
            sign = -1
            cleaned = cleaned.Substring(1)
        End If
        If cleaned.EndsWith("+") Then
            cleaned = cleaned.Substring(0, cleaned.Length - 1)
        ElseIf cleaned.EndsWith("-") Then
            sign *= -1
            cleaned = cleaned.Substring(0, cleaned.Length - 1)
        End If
        Return cleaned
    End Function

    Private Function ParseInt(s As String) As Integer
        Dim cleaned = CleanUnsigned(s)
        If String.IsNullOrEmpty(cleaned) Then Return 0
        Dim v As Integer
        Integer.TryParse(cleaned, v)
        Return v
    End Function

    Private Function ParseLong(s As String) As Long
        Dim cleaned = CleanUnsigned(s)
        If String.IsNullOrEmpty(cleaned) Then Return 0
        Dim v As Long
        Long.TryParse(cleaned, v)
        Return v
    End Function

    Private Function ParseDouble(s As String) As Double
        Dim cleaned = CleanUnsigned(s)
        If String.IsNullOrEmpty(cleaned) Then Return 0
        Dim v As Double
        Double.TryParse(cleaned, v)
        Return v
    End Function

    Private Function ParseSignedInt(raw As String) As Integer
        Dim sign As Integer = 1
        Dim cleaned = CleanSigned(raw, sign)
        If String.IsNullOrEmpty(cleaned) Then Return 0
        Dim v As Integer
        Integer.TryParse(cleaned, v)
        Return v * sign
    End Function

    Private Function ParseSignedDouble(raw As String) As Double
        Dim sign As Integer = 1
        Dim cleaned = CleanSigned(raw, sign)
        If String.IsNullOrEmpty(cleaned) Then Return 0
        Dim v As Double
        Double.TryParse(cleaned, v)
        Return v * sign
    End Function

    Private Sub EnsureCurrentPriceFromFallback(code As String, dataMap As Dictionary(Of String, Object))
        Dim current As Integer = 0
        If dataMap.ContainsKey("current_price") Then
            Integer.TryParse(Convert.ToString(dataMap("current_price")), current)
        End If

        If current <= 0 Then
            Dim fallbackKeys = New String() {"bid_price_1", "ask_price_1"}
            For Each fk As String In fallbackKeys
                If dataMap.ContainsKey(fk) Then
                    Dim candidate As Integer
                    If Integer.TryParse(Convert.ToString(dataMap(fk)), candidate) AndAlso candidate > 0 Then
                        current = candidate
                        Exit For
                    End If
                End If
            Next
        End If

        If current <= 0 Then
            Dim lastPrice As Integer = 0
            If _lastPrices.TryGetValue(code, lastPrice) AndAlso lastPrice > 0 Then
                current = lastPrice
            End If
        End If

        If current > 0 Then
            dataMap("current_price") = current
            _lastPrices.AddOrUpdate(code, current, Function(k, prev) current)
        End If
    End Sub

    Private Sub BroadcastPayload(payload As Object)
        If payload Is Nothing Then Return
        Dim jsonStr As String = JsonConvert.SerializeObject(payload)
        For Each entry As KeyValuePair(Of String, RealtimeWebSocketBehavior) In _sessions.ToArray()
            Dim sessionId = entry.Key
            Dim sess = entry.Value
            Dim ws As WebSocket = Nothing
            If sess IsNot Nothing AndAlso sess.Context IsNot Nothing Then
                ws = sess.Context.WebSocket
            End If
            If ws Is Nothing Then
                RemoveSession(sessionId)
                Continue For
            End If
            If ws.ReadyState <> WebSocketState.Open Then
                RemoveSession(sessionId)
                Continue For
            End If
            Try
                ws.Send(jsonStr)
            Catch ex As Exception
                If _logger IsNot Nothing Then
                    _logger.Warn($"[RT] Send failed ({sessionId}): {ex.Message}")
                End If
                RemoveSession(sessionId)
            End Try
        Next
    End Sub
    ''' <summary>
    ''' 외부에서 JSON 문자열을 직접 브로드캐스트할 수 있는 Public 메서드
    ''' (프로그램매매 실시간 등 Cybos 이벤트 중계용)
    ''' </summary>
    Public Sub BroadcastJson(jsonStr As String)
        If String.IsNullOrEmpty(jsonStr) Then Return
        If _sessions.IsEmpty Then Return

        For Each entry As KeyValuePair(Of String, RealtimeWebSocketBehavior) In _sessions.ToArray()
            Dim sessionId = entry.Key
            Dim sess = entry.Value
            Try
                If sess Is Nothing OrElse sess.Context Is Nothing Then
                    RemoveSession(sessionId)
                    Continue For
                End If
                Dim ws = sess.Context.WebSocket
                If ws Is Nothing OrElse ws.ReadyState <> WebSocketState.Open Then
                    RemoveSession(sessionId)
                    Continue For
                End If
                ws.Send(jsonStr)
            Catch ex As ObjectDisposedException
                RemoveSession(sessionId)
            Catch ex As Exception
                If _logger IsNot Nothing Then
                    _logger.Warn($"[RT-PGM] Send failed ({sessionId}): {ex.Message}")
                End If
                RemoveSession(sessionId)
            End Try
        Next
    End Sub


End Class
