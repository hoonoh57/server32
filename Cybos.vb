Imports System.Runtime.InteropServices
Imports CPSYSDIBLib
Imports CPUTILLib
Imports DSCBO1Lib
Imports System.Diagnostics

Public Class Cybos
    ' ⚠️ COM 객체는 멤버 변수로 두지 않고, 각 함수에서 매번 새로 생성 : test
    Private WithEvents _cpCybos As New CpCybos()
    Private _stockCode As New CPUTILLib.CpStockCode

    Public Sub New()
        ' Cybos 클래스 자체는 싱글톤으로 사용
        ' COM 객체는 각 함수 내에서 매번 생성
        If IsCybosConnected() = False Then
            'MsgBox("Cybos 연결 에러! Cybos를 재기동하세요!")
            'Application.Exit()
            Console.WriteLine("Cybos 연결 안됨")
        Else
            Debug.Print("Cybos is ready!")
        End If
    End Sub
    Public Function IsCybosConnected() As Boolean
        Return _cpCybos.IsConnect = 1
    End Function

    Public Function getStockCode(stockName As String) As String
        Dim code As String = _stockCode.NameToCode(stockName)
        If code <> "" Then
            Return code.Substring(1)
        End If
        Return ""
    End Function
    Public Function getStockCodes(stockNames As List(Of String)) As List(Of String)
        Dim codeList As New List(Of String)
        For Each sname As String In stockNames
            Dim code As String = _stockCode.NameToCode(sname)
            If code <> "" Then
                code = code.Substring(1)
            End If
            codeList.Add(code)
        Next
        Return codeList
    End Function

    ''' <summary>
    ''' 기간을 지정해서 분/틱 캔들을 다운로드한다.
    ''' timeframe 예시: "m1", "m3", "T1" 등 (첫 글자는 구분, 이후는 주기 숫자)
    ''' fromDate/toDate: "yyyyMMdd" 또는 "yyyyMMddHHmm"까지 지정 가능
    ''' </summary>
    Public Async Function DownloadCandlesByPeriod(stockCode As String,
                                                  timeframe As String,
                                                  fromDate As String,
                                                  toDate As String) As Task(Of List(Of Candle))

        Dim candles As New List(Of Candle)

        If String.IsNullOrWhiteSpace(timeframe) Then
            Return candles
        End If

        Dim tfChar As Char = timeframe(0) ' D/W/M/m/T 등
        Dim tickUnit As Integer = 1
        If timeframe.Length > 1 Then
            Integer.TryParse(timeframe.Substring(1), tickUnit)
            If tickUnit <= 0 Then tickUnit = 1
        End If

        If fromDate Is Nothing OrElse fromDate.Length < 8 Then
            Return candles
        End If
        If toDate Is Nothing OrElse toDate.Length < 8 Then
            Return candles
        End If

        Dim fromCutoff As DateTime = ParseYmdOptionalHhmm(fromDate, "0900")
        Dim toCutoff As DateTime = ParseYmdOptionalHhmm(toDate, "0900")
        If fromCutoff = DateTime.MinValue OrElse toCutoff = DateTime.MinValue Then
            Return candles
        End If

        Dim fromYmd As String = fromDate.Substring(0, 8)
        Dim toYmd As String = Util.GetAdjustedDate() ' toDate.Substring(0, 8)

        Dim code As String = If(Not stockCode.StartsWith("A") AndAlso Not stockCode.StartsWith("U") AndAlso Not stockCode.StartsWith("J"), "A" & stockCode, stockCode)

        Dim chart As New StockChart()
        Dim fields() As Integer = {0, 1, 2, 3, 4, 5, 8} ' date, time, OHLC, volume
        Dim maxBlock As Integer = 2000                  ' max rows per request

        chart.SetInputValue(0, code)
        chart.SetInputValue(5, fields)
        chart.SetInputValue(6, AscW(tfChar))
        If tfChar = "m"c OrElse tfChar = "T"c Then
            chart.SetInputValue(7, tickUnit)
        End If
        chart.SetInputValue(9, AscW("1"c))
        chart.SetInputValue(10, AscW("4"c)) ' Include extended hours
        chart.SetInputValue(11, AscW("Y"c)) ' 8:45 minute chart interval rule

        ' Set initial period request range
        chart.SetInputValue(1, AscW("1"c))       ' period mode
        chart.SetInputValue(2, CLng(toYmd))      ' end date
        chart.SetInputValue(3, CLng(fromYmd))    ' start date
        chart.SetInputValue(4, maxBlock)         ' max rows per request

        Dim loopCount As Integer = 0

        Do
            Dim ret = chart.BlockRequest()
            If ret <> 0 Then
                Console.WriteLine($"BlockRequest 오류: {ret}")
                Exit Do
            End If

            Dim rows = chart.GetHeaderValue(3)
            If rows = 0 Then Exit Do

            For i As Integer = 0 To rows - 1
                Dim d As String = chart.GetDataValue(0, i)
                Dim t As String = CInt(chart.GetDataValue(1, i)).ToString("0000")

                Dim yyyy As Integer = d.Substring(0, 4)
                Dim mmm As Integer = d.Substring(4, 2)
                Dim dd As Integer = d.Substring(6, 2)
                Dim hh As Integer = t.Substring(0, 2)
                Dim mm As Integer = t.Substring(2, 2)

                Dim dt As New DateTime(yyyy, mmm, dd, hh, mm, 0)

                If dt < fromCutoff Then
                    Exit Do
                End If

                If dt > toCutoff Then
                    Continue For
                End If

                candles.Add(New Candle With {
                    .Timestamp = dt,
                    .Open = chart.GetDataValue(2, i),
                    .High = chart.GetDataValue(3, i),
                    .Low = chart.GetDataValue(4, i),
                    .Close = chart.GetDataValue(5, i),
                    .Volume = chart.GetDataValue(6, i)
                })
            Next

            If chart.Continue <> 1 Then Exit Do

            loopCount += 1
            Await Task.Delay(200)

            ' Max Loop Safety
            If loopCount > 3000 Then Exit Do
        Loop

        ' Cybos returns Recent->Past order?
        ' BlockRequest(Period mode) usually returns Recent->Past.
        ' We want Recent first? Or Past First?
        ' Client expects: list of dicts. Order?
        ' Kiwoom OPT10080 returns Recent->Past.
        ' So we should keep Recent->Past.
        ' My code above adds to list.
        ' If API returns Recent->Past, then list is Recent->Past.
        ' The provided UpdateViews in Python handles `draw_data = data[::-1]` which implies input data is Recent->Past.
        ' So we don'T Reverse if we want Recent->Past.
        ' Wait, the user provided code had `candles.Reverse()`. This means it converted Recent->Past to Past->Recent.
        ' BUT tester_ui.py expects Recent->Past (see update_views: `draw_data = data[::-1]` -> means it flips it to Past->Recent for drawing).
        ' So Python expects Recent->Past. 
        ' If Cybos returns Recent->Past, and we Reverse, we get Past->Recent. 
        ' Python UpdateViews: `d['t']` logic handles keys.
        ' Let's look at `candles.Add`: It appends. 
        ' If Cybos gives Recent first, list is [Recent, ..., Past].
        ' If we Reverse, list is [Past, ..., Recent].
        ' User code had Reverse().
        ' Let's comment out Reverse to give Recent...Past (Kiwoom Standard).

        ' candles.Reverse() 

        Debug.Print($"기간 요청 {loopCount + 1}회, 수신 {candles.Count}건")
        Return candles
    End Function

    Private Function ParseYmdOptionalHhmm(dateText As String, defaultHhmm As String) As DateTime
        Try
            Dim trimmed = dateText.Trim()
            If trimmed.Length < 8 Then Return DateTime.MinValue
            Dim ymd = trimmed.Substring(0, 8)
            Dim hhmm As String = If(trimmed.Length >= 12, trimmed.Substring(8, 4), defaultHhmm)
            Dim yyyy = Integer.Parse(ymd.Substring(0, 4))
            Dim mm = Integer.Parse(ymd.Substring(4, 2))
            Dim dd = Integer.Parse(ymd.Substring(6, 2))
            Dim hh = Integer.Parse(hhmm.Substring(0, 2))
            Dim mi = Integer.Parse(hhmm.Substring(2, 2))
            Return New DateTime(yyyy, mm, dd, hh, mi, 0)
        Catch
            Return DateTime.MinValue
        End Try
    End Function
End Class

Public Class Candle
    Public Property Timestamp As DateTime
    Public Property Open As Double
    Public Property High As Double
    Public Property Low As Double
    Public Property Close As Double
    Public Property Volume As Double
End Class
