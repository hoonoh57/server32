Imports System.Runtime.InteropServices
'Imports CPSYSDIBLib
Imports CPUTILLib
Imports DSCBO1Lib
Imports System.Diagnostics
Imports CPSYSDIBLib
'Imports CPSYSDIBLib.CpSvr8119SCnld

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

    '///////////보조함수 삽입
    Private Function ChangeSignMultiplier(signCode As Object) As Integer?
        If signCode Is Nothing Then Return Nothing

        Dim text As String = signCode.ToString().Trim()

        Select Case text
            Case "1", "2", "6", "7", "+"
                Return 1
            Case "4", "5", "8", "9", "-"
                Return -1
            Case "0", "3"
                Return 0
        End Select

        If text.Contains("하락") OrElse text.Contains("하한") Then Return -1
        If text.Contains("상승") OrElse text.Contains("상한") Then Return 1
        If text.Contains("보합") OrElse text.Contains("거래무") Then Return 0

        Return Nothing
    End Function

    Private Function ApplyChangeSign(value As Object, signCode As Object) As Decimal?
        If value Is Nothing Then Return Nothing

        Dim number As Decimal
        If Not Decimal.TryParse(value.ToString().Replace(",", ""), number) Then
            Return Nothing
        End If

        Dim multiplier As Integer? = ChangeSignMultiplier(signCode)
        If Not multiplier.HasValue Then Return number
        If multiplier.Value = 0 Then Return 0D

        Return Math.Abs(number) * multiplier.Value
    End Function

    Private Function ToNullableLong(value As Object) As Long?
        If value Is Nothing Then Return Nothing

        Dim number As Long
        If Long.TryParse(value.ToString().Replace(",", ""), number) Then
            Return Math.Abs(number)
        End If

        Return Nothing
    End Function
    '/////////////////새로 삽입한 보조함수 끝///////////////////////////////////////

    '///////////// 새로 삽입한 다운로드 함수 시작

    ''' <summary>
    ''' 마지막 영업일자를 반환하는 함수
    ''' </summary>
    ''' <param name="targetYmd"></param>
    ''' <returns></returns>
    Private Function ResolveLastTradingYmdBySamsung(targetYmd As String) As String
        If String.IsNullOrWhiteSpace(targetYmd) OrElse targetYmd.Length < 8 Then
            Return targetYmd
        End If

        Dim targetDate As DateTime
        If Not DateTime.TryParseExact(targetYmd.Substring(0, 8),
                                  "yyyyMMdd",
                                  Nothing,
                                  Globalization.DateTimeStyles.None,
                                  targetDate) Then
            Return targetYmd
        End If

        Dim stopDate As String = targetDate.AddDays(-10).ToString("yyyyMMdd")
        Dim samsungCode As String = "A005930"

        Try
            Dim chart As New StockChart()
            Dim fields() As Integer = {0, 2, 3, 4, 5, 6, 8} ' date, OHLC, volume

            chart.SetInputValue(0, samsungCode)
            chart.SetInputValue(1, AscW("1"c))       ' period mode
            chart.SetInputValue(2, CLng(targetYmd))  ' end date
            chart.SetInputValue(3, CLng(stopDate))   ' start date
            chart.SetInputValue(4, 20)
            chart.SetInputValue(5, fields)
            chart.SetInputValue(6, AscW("D"c))
            chart.SetInputValue(9, AscW("1"c))
            chart.SetInputValue(10, AscW("1"c))
            chart.SetInputValue(12, AscW("A"c))

            Dim ret As Integer = CInt(chart.BlockRequest())
            If ret <> 0 Then Return targetYmd

            Dim rows As Integer = CInt(chart.GetHeaderValue(3))
            Dim bestYmd As String = ""

            For i As Integer = 0 To rows - 1
                Dim ymd As String = chart.GetDataValue(0, i).ToString()
                If String.IsNullOrWhiteSpace(ymd) OrElse ymd.Length < 8 Then Continue For
                If String.CompareOrdinal(ymd, targetYmd) > 0 Then Continue For

                Dim closePrice As Decimal = 0D
                Dim volume As Decimal = 0D

                Decimal.TryParse(chart.GetDataValue(4, i).ToString(), closePrice)
                Decimal.TryParse(chart.GetDataValue(6, i).ToString(), volume)

                If closePrice > 0D AndAlso volume > 0D Then
                    If bestYmd = "" OrElse String.CompareOrdinal(ymd, bestYmd) > 0 Then
                        bestYmd = ymd
                    End If
                End If
            Next

            If bestYmd <> "" Then Return bestYmd
        Catch
        End Try

        Return targetYmd
    End Function

    ''' <summary>
    ''' 기간을 지정해서 일/분/틱 캔들을 다운로드한다.
    ''' timeframe 예시: "D1", "m1", "m3", "T1"
    ''' fromDate/toDate: "yyyyMMdd" 또는 "yyyyMMddHHmm"
    ''' 반환 순서: 과거 -> 최신
    ''' </summary>
    Public Function DownloadCandlesByPeriod(stockCode As String,
                                              timeframe As String,
                                              fromDate As String,
                                              toDate As String) As List(Of Candle)

        Dim candles As New List(Of Candle)

        If String.IsNullOrWhiteSpace(timeframe) Then Return candles
        If fromDate Is Nothing OrElse fromDate.Length < 8 Then Return candles
        If toDate Is Nothing OrElse toDate.Length < 8 Then Return candles

        Dim tfChar As Char = timeframe(0)
        Dim tickUnit As Integer = 1
        If timeframe.Length > 1 Then
            Integer.TryParse(timeframe.Substring(1), tickUnit)
            If tickUnit <= 0 Then tickUnit = 1
        End If

        Dim isDaily As Boolean = (tfChar = "D"c)
        Dim fromCutoff As DateTime = ParseYmdOptionalHhmm(fromDate, If(isDaily, "0000", "0800"))
        Dim toCutoff As DateTime = ParseYmdOptionalHhmm(toDate, If(isDaily, "2359", "2000"))

        If fromCutoff = DateTime.MinValue OrElse toCutoff = DateTime.MinValue Then
            Return candles
        End If


        Dim fromYmd As String = fromDate.Substring(0, 8)
        Dim toYmd As String = toDate.Substring(0, 8)
        Dim requestToYmd As String = toYmd

        ' 분봉/틱봉에서 마지막 영업일자를 설정
        If Not isDaily Then
            requestToYmd = ResolveLastTradingYmdBySamsung(toYmd)
        End If


        Dim code As String = If(Not stockCode.StartsWith("A") AndAlso
                            Not stockCode.StartsWith("U") AndAlso
                            Not stockCode.StartsWith("J"),
                            "A" & stockCode,
                            stockCode)

        Dim chart As New StockChart()

        Dim fields() As Integer
        If isDaily Then
            'fields = New Integer() {0, 2, 3, 4, 5, 6, 8, 9, 12, 13, 23, 37}
            fields = New Integer() {0, 2, 3, 4, 5, 6, 8, 9, 12, 13, 37}
        Else
            fields = New Integer() {0, 1, 2, 3, 4, 5, 8, 9}
        End If

        chart.SetInputValue(0, code)
        chart.SetInputValue(1, AscW("1"c))
        '//chart.SetInputValue(2, CLng(toYmd))
        '//requestToYmd = "20260703"
        chart.SetInputValue(2, CLng(requestToYmd))

        chart.SetInputValue(3, CLng(fromYmd))
        chart.SetInputValue(4, 2000)
        chart.SetInputValue(5, fields)
        chart.SetInputValue(6, AscW(tfChar))

        If tfChar = "m"c OrElse tfChar = "T"c Then
            chart.SetInputValue(7, tickUnit)
        End If

        chart.SetInputValue(9, AscW("1"c))   ' 수정주가
        chart.SetInputValue(10, AscW("1"c))  ' 시간외거래량 모두 포함
        chart.SetInputValue(11, AscW("Y"c))  ' 8:45부터 분차트 주기 계산
        chart.SetInputValue(12, AscW("A"c))  ' 전체: KRX + NXT

        Dim loopCount As Integer = 0

        Do
            Dim ret As Integer = CInt(chart.BlockRequest())
            If ret <> 0 Then
                Console.WriteLine($"BlockRequest 오류: {ret}")
                Exit Do
            End If

            Dim rows As Integer = CInt(chart.GetHeaderValue(3))
            If rows = 0 Then Exit Do

            For i As Integer = 0 To rows - 1
                Dim d As String = chart.GetDataValue(0, i).ToString()
                Dim t As String = "0800"  '0000

                Dim idxOpen As Integer
                Dim idxHigh As Integer
                Dim idxLow As Integer
                Dim idxClose As Integer
                Dim idxVolume As Integer
                Dim idxTradingValue As Integer
                Dim idxPriceChange As Integer = -1
                Dim idxSharesOutstanding As Integer = -1
                Dim idxMarketCap As Integer = -1
                Dim idxChangeRate As Integer = -1
                Dim idxChangeSign As Integer = -1

                If isDaily Then
                    idxOpen = 1
                    idxHigh = 2
                    idxLow = 3
                    idxClose = 4
                    idxPriceChange = 5
                    idxVolume = 6
                    idxTradingValue = 7
                    idxSharesOutstanding = 8
                    idxMarketCap = 9
                    idxChangeSign = 10
                Else
                    t = CInt(chart.GetDataValue(1, i)).ToString("0000")
                    idxOpen = 2
                    idxHigh = 3
                    idxLow = 4
                    idxClose = 5
                    idxVolume = 6
                    idxTradingValue = 7
                End If

                Dim yyyy As Integer = CInt(d.Substring(0, 4))
                Dim mmDate As Integer = CInt(d.Substring(4, 2))
                Dim dd As Integer = CInt(d.Substring(6, 2))
                Dim hh As Integer = CInt(t.Substring(0, 2))
                Dim min As Integer = CInt(t.Substring(2, 2))

                Dim dt As New DateTime(yyyy, mmDate, dd, hh, min, 0)

                If dt < fromCutoff Then Exit Do
                If dt > toCutoff Then Continue For

                Dim signCode As String = "" '  rawSign.ToString()

                If idxChangeSign >= 0 Then
                    Dim rawSign = chart.GetDataValue(idxChangeSign, i)
                    signCode = rawSign.ToString()

                    If signCode = "50" Then signCode = "2"
                    If signCode = "53" Then signCode = "5"
                    If signCode = "51" Then signCode = "3"
                End If



                Dim tradingValue As Long = 0
                If idxTradingValue >= 0 Then
                    tradingValue = ToNullableLong(chart.GetDataValue(idxTradingValue, i))
                End If

                Dim priceChange As Integer = 0
                If idxPriceChange >= 0 Then
                    priceChange = ApplyChangeSign(chart.GetDataValue(idxPriceChange, i), signCode)
                End If

                Dim closePrice As Decimal = Convert.ToDecimal(chart.GetDataValue(idxClose, i))

                'Dim priceChange As Decimal = 0D
                If idxPriceChange >= 0 Then
                    Dim signedChange As Decimal? = ApplyChangeSign(chart.GetDataValue(idxPriceChange, i), signCode)
                    If signedChange.HasValue Then priceChange = signedChange.Value
                End If

                Dim changeRate As Decimal = 0D
                Dim prevClose As Decimal = closePrice - priceChange

                If prevClose <> 0D Then
                    changeRate = Math.Round(priceChange * 100D / prevClose, 2)
                End If

                Dim sharesOutstanding As Long? = Nothing
                If idxSharesOutstanding >= 0 Then
                    sharesOutstanding = ToNullableLong(chart.GetDataValue(idxSharesOutstanding, i))
                End If

                Dim marketCap As Long? = Nothing
                If idxMarketCap >= 0 Then
                    marketCap = ToNullableLong(chart.GetDataValue(idxMarketCap, i))
                End If

                candles.Add(New Candle With {
                .Timestamp = dt,
                .Open = chart.GetDataValue(idxOpen, i),
                .High = chart.GetDataValue(idxHigh, i),
                .Low = chart.GetDataValue(idxLow, i),
                .Close = chart.GetDataValue(idxClose, i),
                .Volume = chart.GetDataValue(idxVolume, i),
                .TradingValue = tradingValue,
                .PriceChange = priceChange,
                .ChangeRate = changeRate,
                .ChangeSign = signCode,
                .SharesOutstanding = sharesOutstanding,
                .MarketCap = marketCap
            })
            Next

            If chart.Continue <> 1 Then Exit Do

            loopCount += 1
            Threading.Thread.Sleep(200)

            If loopCount > 3000 Then Exit Do
        Loop

        candles.Reverse()

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

    '/////////////////////////////////
    ' 프로그램 매매정보 요청
    '////////////////////////////////
    ' ============================================================
    '  프로그램매매 데이터 모델
    ' ============================================================

    Public Class ProgramTradeByTime
        Public Property Time As ULong
        Public Property Price As ULong
        Public Property SignChar As String
        Public Property Change As Long
        Public Property ChangeRate As Single
        Public Property Volume As ULong
        Public Property PgmBuyQty As ULong
        Public Property PgmSellQty As ULong
        Public Property PgmNetQty As Long
        Public Property PgmNetQtyChange As Long
        Public Property PgmBuyAmt As ULong
        Public Property PgmSellAmt As ULong
        Public Property PgmNetAmt As Long
        Public Property PgmNetAmtChange As Long
    End Class

    Public Class ProgramTradeByDay
        Public Property TradeDate As Long
        Public Property Price As Long
        Public Property Change As Long
        Public Property ChangeRate As Double
        Public Property Volume As Long
        Public Property SellQty As Long
        Public Property BuyQty As Long
        Public Property NetQtyChange As Long
        Public Property NetQtyCumul As Long
        Public Property SellAmt As Long
        Public Property BuyAmt As Long
        Public Property NetAmtChange As Long
        Public Property NetAmtCumul As Long
    End Class

    Public Class ProgramTradeRealtime
        Public Property StockCode As String
        Public Property Time As ULong
        Public Property Price As ULong
        Public Property SignChar As String
        Public Property Change As Long
        Public Property ChangeRate As Single
        Public Property Volume As ULong
        Public Property PgmBuyQty As ULong
        Public Property PgmSellQty As ULong
        Public Property PgmNetQty As Long
        Public Property PgmBuyAmt As ULong
        Public Property PgmSellAmt As ULong
        Public Property PgmNetAmt As Long
    End Class

    ' ============================================================
    '  1) 시간대별 프로그램매매 추이 (DsCbo1.CpSvrNew8119, 연속 O)
    ' ============================================================
    Public Async Function DownloadProgramTradeByTime(stockCode As String,
                                                      Optional exchange As String = "A") As Task(Of List(Of ProgramTradeByTime))
        Dim result As New List(Of ProgramTradeByTime)
        Dim code As String = EnsurePrefix(stockCode)
        Dim exChar As Char = If(String.IsNullOrEmpty(exchange), "A"c, exchange(0))
        Dim loopCount As Integer = 0

        Dim cpObj As New DSCBO1Lib.CpSvrNew8119()
        cpObj.SetInputValue(0, code)
        cpObj.SetInputValue(1, AscW(exChar))

        Do
            Dim ret As Integer = CInt(cpObj.BlockRequest())
            If ret <> 0 Then
                Debug.Print($"CpSvrNew8119 BlockRequest 오류: {ret}")
                Exit Do
            End If

            Dim rowCount As Short = cpObj.GetHeaderValue(0)
            If rowCount = 0 Then Exit Do

            For i As Integer = 0 To rowCount - 1
                Dim item As New ProgramTradeByTime With {
                    .Time = CULng(cpObj.GetDataValue(0, i)),
                    .Price = CULng(cpObj.GetDataValue(1, i)),
                    .SignChar = CStr(cpObj.GetDataValue(2, i)),
                    .Change = CLng(cpObj.GetDataValue(3, i)),
                    .ChangeRate = CSng(cpObj.GetDataValue(4, i)),
                    .Volume = CULng(cpObj.GetDataValue(5, i)),
                    .PgmBuyQty = CULng(cpObj.GetDataValue(6, i)),
                    .PgmSellQty = CULng(cpObj.GetDataValue(7, i)),
                    .PgmNetQty = CLng(cpObj.GetDataValue(8, i)),
                    .PgmNetQtyChange = CLng(cpObj.GetDataValue(9, i)),
                    .PgmBuyAmt = CULng(cpObj.GetDataValue(10, i)),
                    .PgmSellAmt = CULng(cpObj.GetDataValue(11, i)),
                    .PgmNetAmt = CLng(cpObj.GetDataValue(12, i)),
                    .PgmNetAmtChange = CLng(cpObj.GetDataValue(13, i))
                }
                result.Add(item)
            Next

            If cpObj.Continue <> 1 Then Exit Do
            loopCount += 1
            Await Task.Delay(200)
            If loopCount > 500 Then Exit Do
        Loop

        Debug.Print($"프로그램매매(시간별) {code}: {loopCount + 1}회 요청, {result.Count}건 수신")
        Return result
    End Function

    ' ============================================================
    '  2) 일자별 프로그램매매 추이 (DsCbo1.CpSvrNew8119Day, 연속 X)
    ' ============================================================
    Public Function DownloadProgramTradeByDay(stockCode As String,
                                               Optional periodType As String = "2") As List(Of ProgramTradeByDay)
        Dim result As New List(Of ProgramTradeByDay)
        Dim code As String = EnsurePrefix(stockCode)
        Dim pChar As Char = If(String.IsNullOrEmpty(periodType), "2"c, periodType(0))

        Dim cpObj As New DSCBO1Lib.CpSvrNew8119Day()
        cpObj.SetInputValue(0, AscW(pChar))
        cpObj.SetInputValue(1, code)

        Dim ret As Integer = CInt(cpObj.BlockRequest())
        If ret <> 0 Then
            Debug.Print($"CpSvrNew8119Day BlockRequest 오류: {ret}")
            Return result
        End If

        Dim rowCount As Short = cpObj.GetHeaderValue(0)
        If rowCount = 0 Then Return result

        For i As Integer = 0 To rowCount - 1
            Dim item As New ProgramTradeByDay With {
                .TradeDate = CLng(cpObj.GetDataValue(0, i)),
                .Price = CLng(cpObj.GetDataValue(1, i)),
                .Change = CLng(cpObj.GetDataValue(2, i)),
                .ChangeRate = CDbl(cpObj.GetDataValue(3, i)),
                .Volume = CLng(cpObj.GetDataValue(4, i)),
                .SellQty = CLng(cpObj.GetDataValue(5, i)),
                .BuyQty = CLng(cpObj.GetDataValue(6, i)),
                .NetQtyChange = CLng(cpObj.GetDataValue(7, i)),
                .NetQtyCumul = CLng(cpObj.GetDataValue(8, i)),
                .SellAmt = CLng(cpObj.GetDataValue(9, i)),
                .BuyAmt = CLng(cpObj.GetDataValue(10, i)),
                .NetAmtChange = CLng(cpObj.GetDataValue(11, i)),
                .NetAmtCumul = CLng(cpObj.GetDataValue(12, i))
            }
            result.Add(item)
        Next

        Debug.Print($"프로그램매매(일별) {code}: {result.Count}건 (기간: {pChar})")
        Return result
    End Function

    ''' <summary>
    ''' 시간대별 프로그램매매 — 동기 버전 (UI 스레드에서 호출용)
    ''' 연속 조회 없이 첫 페이지만 반환 (당일 시간대 데이터 충분)
    ''' </summary>
    Public Function DownloadProgramTradeByTimeSync(stockCode As String,
                                                    Optional exchange As String = "A") As List(Of ProgramTradeByTime)
        Dim result As New List(Of ProgramTradeByTime)
        Dim code As String = EnsurePrefix(stockCode)
        Dim exChar As Char = If(String.IsNullOrEmpty(exchange), "A"c, exchange(0))

        Dim cpObj As New DSCBO1Lib.CpSvrNew8119()
        cpObj.SetInputValue(0, code)
        cpObj.SetInputValue(1, AscW(exChar))

        Dim loopCount As Integer = 0
        Do
            Dim ret As Integer = CInt(cpObj.BlockRequest())
            If ret <> 0 Then Exit Do

            Dim rowCount As Short = cpObj.GetHeaderValue(0)
            If rowCount = 0 Then Exit Do

            For i As Integer = 0 To rowCount - 1
                Dim item As New ProgramTradeByTime With {
                    .Time = CULng(cpObj.GetDataValue(0, i)),
                    .Price = CULng(cpObj.GetDataValue(1, i)),
                    .SignChar = CStr(cpObj.GetDataValue(2, i)),
                    .Change = CLng(cpObj.GetDataValue(3, i)),
                    .ChangeRate = CSng(cpObj.GetDataValue(4, i)),
                    .Volume = CULng(cpObj.GetDataValue(5, i)),
                    .PgmBuyQty = CULng(cpObj.GetDataValue(6, i)),
                    .PgmSellQty = CULng(cpObj.GetDataValue(7, i)),
                    .PgmNetQty = CLng(cpObj.GetDataValue(8, i)),
                    .PgmNetQtyChange = CLng(cpObj.GetDataValue(9, i)),
                    .PgmBuyAmt = CULng(cpObj.GetDataValue(10, i)),
                    .PgmSellAmt = CULng(cpObj.GetDataValue(11, i)),
                    .PgmNetAmt = CLng(cpObj.GetDataValue(12, i)),
                    .PgmNetAmtChange = CLng(cpObj.GetDataValue(13, i))
                }
                result.Add(item)
            Next

            If cpObj.Continue <> 1 Then Exit Do
            loopCount += 1
            Threading.Thread.Sleep(200)
            If loopCount > 500 Then Exit Do
        Loop

        Debug.Print($"프로그램매매(시간별/동기) {code}: {loopCount + 1}회, {result.Count}건")
        Return result
    End Function

    ' ============================================================
    '  3) 실시간 프로그램매매 구독 (CpSysDib.CpSvr8119SCnld)
    ' ============================================================
    'Private _pgmRtSubscriptions As New Dictionary(Of String, CPSYSDIBLib.CpSvr8119SCnld)
    Private _pgmRtSubscriptions As New Dictionary(Of String, CPSYSDIBLib.CpSvr8119S) 'Cnld)
    'CPSYSDIBLib.CpSvr8119SCnld
    Public Event ProgramTradeReceived(data As ProgramTradeRealtime)

    Public Sub SubscribeProgramTrade(stockCode As String)
        Dim code As String = EnsurePrefix(stockCode)
        If _pgmRtSubscriptions.ContainsKey(code) Then Return

        'Dim cpObj As New CPSYSDIBLib.CpSvr8119SCnld()
        Dim cpObj As New CPSYSDIBLib.CpSvr8119S

        cpObj.SetInputValue(0, code)

        AddHandler cpObj.Received, Sub()
                                       Try
                                           Dim item As New ProgramTradeRealtime With {
                                               .StockCode = CStr(cpObj.GetHeaderValue(0)),
                                               .Time = CULng(cpObj.GetHeaderValue(1)),
                                               .Price = CULng(cpObj.GetHeaderValue(2)),
                                               .SignChar = CStr(cpObj.GetHeaderValue(3)),
                                               .Change = CLng(cpObj.GetHeaderValue(4)),
                                               .ChangeRate = CSng(cpObj.GetHeaderValue(5)),
                                               .Volume = CULng(cpObj.GetHeaderValue(6)),
                                               .PgmBuyQty = CULng(cpObj.GetHeaderValue(7)),
                                               .PgmSellQty = CULng(cpObj.GetHeaderValue(8)),
                                               .PgmNetQty = CLng(cpObj.GetHeaderValue(9)),
                                               .PgmBuyAmt = CULng(cpObj.GetHeaderValue(10)),
                                               .PgmSellAmt = CULng(cpObj.GetHeaderValue(11)),
                                               .PgmNetAmt = CLng(cpObj.GetHeaderValue(12))
                                           }
                                           RaiseEvent ProgramTradeReceived(item)
                                       Catch ex As Exception
                                           Debug.Print($"프로그램매매 실시간 파싱 오류 ({code}): {ex.Message}")
                                       End Try
                                   End Sub

        cpObj.Subscribe()
        _pgmRtSubscriptions(code) = cpObj
        Debug.Print($"프로그램매매 실시간 구독: {code}")
    End Sub

    Public Sub UnsubscribeProgramTrade(stockCode As String)
        Dim code As String = EnsurePrefix(stockCode)
        If _pgmRtSubscriptions.ContainsKey(code) Then
            Try : _pgmRtSubscriptions(code).Unsubscribe() : Catch : End Try
            _pgmRtSubscriptions.Remove(code)
        End If
    End Sub

    Public Sub UnsubscribeAllProgramTrade()
        For Each kvp As Object In _pgmRtSubscriptions
            Try : kvp.Value.Unsubscribe() : Catch : End Try
        Next
        _pgmRtSubscriptions.Clear()
    End Sub

    '$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$

    ' ============================================================
    '  MarketEye 데이터 모델
    ' ============================================================
    Public Class MarketEyeItem
        Public Property Code As String
        Public Property StockName As String
        Public Property CurrentPrice As Long
        Public Property [Open] As Long
        Public Property High As Long
        Public Property Low As Long
        Public Property DiffSign As String
        Public Property Diff As Long
        Public Property Volume As Long
        Public Property TradeValue As Long
        Public Property PrevVolume As Long
        Public Property Intensity As Single
        Public Property TotalAskRemain As Long
        Public Property TotalBidRemain As Long
        Public Property ForeignHoldRatio As Single
        Public Property ForeignNetShares As Long
        Public Property ProgramNet As Long
        Public Property ForeignConfirm As String
        Public Property ForeignNetToday As Long
        Public Property InstConfirm As String
        Public Property InstNetToday As Long
        Public Property IndividualConfirm As String
        Public Property IndividualNetToday As Long
        Public Property CreditRatio As Single
    End Class

    ' ============================================================
    '  5대 창구(거래원) 데이터 모델
    ' ============================================================
    Public Class StockMemberItem
        Public Property Rank As Integer
        Public Property SellMemberName As String
        Public Property BuyMemberName As String
        Public Property SellQty As Long
        Public Property BuyQty As Long
    End Class

    Public Class StockMemberResult
        Public Property Code As String
        Public Property Timestamp As Long
        Public Property FaceValue As Long
        Public Property Members As List(Of StockMemberItem)
        Public Property Top5BuyTotal As Long
        Public Property Top5SellTotal As Long
    End Class

    ' ============================================================
    '  투자자별 매매동향(잠정) 데이터 모델
    ' ============================================================
    Public Class InvestorTrendItem
        Public Property Code As String
        Public Property Name As String
        Public Property CurrentPrice As Long
        Public Property Diff As Long
        Public Property DiffRate As Single
        Public Property Volume As Long
        Public Property ForeignNet As Long
        Public Property InstNet As Long
        Public Property InsuranceNet As Long
        Public Property TrustNet As Long
        Public Property BankNet As Long
        Public Property PensionNet As Long
        Public Property GovNet As Long
        Public Property EtcCorpNet As Long
    End Class

    ' ============================================================
    '  4) MarketEye 일괄 수급 조회 (CpSysDib.MarketEye)
    '     최대 200종목, 최대 64필드 동시 조회
    '     ★ 필드는 오름차순 정렬되어 반환됨에 주의
    ' ============================================================
    Public Function FetchMarketEyeSupply(stockCodes As String()) As List(Of MarketEyeItem)
        Dim result As New List(Of MarketEyeItem)
        If stockCodes Is Nothing OrElse stockCodes.Length = 0 Then Return result

        Try
            ' 요청 필드 (반드시 오름차순으로 정렬해야 GetDataValue index가 예측 가능)
            ' 필드번호:  0,  2,  3,  4,  5,  6,  7, 10, 11, 13, 14, 17, 21, 22, 24, 62,116,117,118,119,120,126,155,156
            ' 반환idx:   0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23
            Dim fields() As Integer = {
                0,   ' 종목코드        idx=0
                2,   ' 대비부호        idx=1
                3,   ' 전일대비        idx=2
                4,   ' 현재가          idx=3
                5,   ' 시가            idx=4
                6,   ' 고가            idx=5
                7,   ' 저가            idx=6
                10,  ' 거래량          idx=7
                11,  ' 거래대금(원)    idx=8
                13,  ' 총매도호가잔량  idx=9
                14,  ' 총매수호가잔량  idx=10
                17,  ' 종목명          idx=11
                21,  ' 외국인보유비율  idx=12
                22,  ' 전일거래량      idx=13
                24,  ' 체결강도        idx=14
                62,  ' 외국인순매매(주) idx=15
                116, ' 프로그램순매수  idx=16
                117, ' 당일외국인잠정  idx=17
                118, ' 당일외국인순매수 idx=18
                119, ' 당일기관잠정    idx=19
                120, ' 당일기관순매수  idx=20
                126, ' 신용잔고율      idx=21
                155, ' 당일개인잠정    idx=22
                156  ' 당일개인순매수  idx=23
            }

            ' 종목코드 A접두사 처리 (최대 200개)
            Dim maxLen As Integer = Math.Min(stockCodes.Length, 200)
            Dim codeArray(maxLen - 1) As String
            For i As Integer = 0 To maxLen - 1
                codeArray(i) = EnsurePrefix(stockCodes(i))
            Next

            Dim objMarketEye As New CPSYSDIBLib.MarketEye()
            objMarketEye.SetInputValue(0, fields)
            objMarketEye.SetInputValue(1, codeArray)
            objMarketEye.BlockRequest()

            Dim status As Integer = objMarketEye.GetDibStatus()
            If status <> 0 Then
                Debug.Print($"MarketEye 오류: status={status}, msg={objMarketEye.GetDibMsg1()}")
                Return result
            End If

            Dim stockCount As Integer = CInt(objMarketEye.GetHeaderValue(2))

            For i As Integer = 0 To stockCount - 1
                Dim item As New MarketEyeItem()
                item.Code = SafeStr(objMarketEye.GetDataValue(0, i))
                item.DiffSign = SafeStr(objMarketEye.GetDataValue(1, i))
                item.Diff = SafeLng(objMarketEye.GetDataValue(2, i))
                item.CurrentPrice = SafeLng(objMarketEye.GetDataValue(3, i))
                item.Open = SafeLng(objMarketEye.GetDataValue(4, i))
                item.High = SafeLng(objMarketEye.GetDataValue(5, i))
                item.Low = SafeLng(objMarketEye.GetDataValue(6, i))
                item.Volume = SafeLng(objMarketEye.GetDataValue(7, i))
                item.TradeValue = SafeLng(objMarketEye.GetDataValue(8, i))
                item.TotalAskRemain = SafeLng(objMarketEye.GetDataValue(9, i))
                item.TotalBidRemain = SafeLng(objMarketEye.GetDataValue(10, i))
                item.StockName = SafeStr(objMarketEye.GetDataValue(11, i))
                item.ForeignHoldRatio = SafeSng(objMarketEye.GetDataValue(12, i))
                item.PrevVolume = SafeLng(objMarketEye.GetDataValue(13, i))
                item.Intensity = SafeSng(objMarketEye.GetDataValue(14, i))
                item.ForeignNetShares = SafeLng(objMarketEye.GetDataValue(15, i))
                item.ProgramNet = SafeLng(objMarketEye.GetDataValue(16, i))
                item.ForeignConfirm = SafeCharStr(objMarketEye.GetDataValue(17, i))
                item.ForeignNetToday = SafeLng(objMarketEye.GetDataValue(18, i))
                item.InstConfirm = SafeCharStr(objMarketEye.GetDataValue(19, i))
                item.InstNetToday = SafeLng(objMarketEye.GetDataValue(20, i))
                item.CreditRatio = SafeSng(objMarketEye.GetDataValue(21, i))
                item.IndividualConfirm = SafeCharStr(objMarketEye.GetDataValue(22, i))
                item.IndividualNetToday = SafeLng(objMarketEye.GetDataValue(23, i))

                ' A접두사 제거
                If item.Code.StartsWith("A") Then
                    item.Code = item.Code.Substring(1)
                End If

                result.Add(item)
            Next

            Debug.Print($"MarketEye: {codeArray.Length}종목 요청, {result.Count}건 수신")

        Catch ex As Exception
            Debug.Print($"MarketEye 예외: {ex.Message}")
        End Try

        Return result
    End Function

    ' ============================================================
    '  5) 5대 매매창구 조회 (Dscbo1.StockMember1)
    ' ============================================================
    Public Function FetchStockMemberTop5(stockCode As String) As StockMemberResult
        Dim result As New StockMemberResult With {
            .Code = stockCode,
            .Members = New List(Of StockMemberItem),
            .Top5BuyTotal = 0,
            .Top5SellTotal = 0
        }

        Try
            Dim code As String = EnsurePrefix(stockCode)
            Dim objMember As New DSCBO1Lib.StockMember1()
            objMember.SetInputValue(0, code)
            objMember.BlockRequest()

            Dim status As Integer = objMember.GetDibStatus()
            If status <> 0 Then
                Debug.Print($"StockMember1 오류: status={status}, msg={objMember.GetDibMsg1()}")
                Return result
            End If

            result.Timestamp = SafeLng(objMember.GetHeaderValue(2))
            result.FaceValue = SafeLng(objMember.GetHeaderValue(3))

            Dim count As Integer = CInt(objMember.GetHeaderValue(1))
            Dim maxRows As Integer = Math.Min(count, 5)

            For i As Integer = 0 To maxRows - 1
                Dim member As New StockMemberItem With {
                    .Rank = i + 1,
                    .SellMemberName = SafeStr(objMember.GetDataValue(0, i)),
                    .BuyMemberName = SafeStr(objMember.GetDataValue(1, i)),
                    .SellQty = SafeLng(objMember.GetDataValue(2, i)),
                    .BuyQty = SafeLng(objMember.GetDataValue(3, i))
                }
                result.Members.Add(member)
                result.Top5BuyTotal += member.BuyQty
                result.Top5SellTotal += member.SellQty
            Next

            Debug.Print($"StockMember1 {code}: {result.Members.Count}건 수신")

        Catch ex As Exception
            Debug.Print($"StockMember1 예외: {ex.Message}")
        End Try

        Return result
    End Function

    ' ============================================================
    '  6) 투자자별 매매동향 잠정 (CpSysDib.CpSvr7210d)
    ' ============================================================
    Public Function FetchInvestorTrend(investFlag As Integer,
                                       Optional marketType As String = "0",
                                       Optional valueType As String = "0",
                                       Optional sortOrder As String = "0") As List(Of InvestorTrendItem)
        Dim result As New List(Of InvestorTrendItem)

        Try
            Dim objRq As New CPSYSDIBLib.CpSvr7210d()
            objRq.SetInputValue(0, AscW(If(marketType, "0")(0)))
            objRq.SetInputValue(1, AscW(If(valueType, "0")(0)))
            objRq.SetInputValue(2, investFlag)
            objRq.SetInputValue(3, AscW(If(sortOrder, "0")(0)))
            objRq.BlockRequest()

            Dim status As Integer = objRq.GetDibStatus()
            If status <> 0 Then
                Debug.Print($"CpSvr7210d 오류: status={status}, msg={objRq.GetDibMsg1()}")
                Return result
            End If

            Dim cnt As Integer = CInt(objRq.GetHeaderValue(0))

            For i As Integer = 0 To cnt - 1
                Dim item As New InvestorTrendItem With {
                    .Code = SafeStr(objRq.GetDataValue(0, i)),
                    .Name = SafeStr(objRq.GetDataValue(1, i)),
                    .CurrentPrice = SafeLng(objRq.GetDataValue(2, i)),
                    .Diff = SafeLng(objRq.GetDataValue(3, i)),
                    .DiffRate = SafeSng(objRq.GetDataValue(4, i)),
                    .Volume = SafeLng(objRq.GetDataValue(5, i)),
                    .ForeignNet = SafeLng(objRq.GetDataValue(6, i)),
                    .InstNet = SafeLng(objRq.GetDataValue(7, i)),
                    .InsuranceNet = SafeLng(objRq.GetDataValue(8, i)),
                    .TrustNet = SafeLng(objRq.GetDataValue(9, i)),
                    .BankNet = SafeLng(objRq.GetDataValue(10, i)),
                    .PensionNet = SafeLng(objRq.GetDataValue(11, i)),
                    .GovNet = SafeLng(objRq.GetDataValue(12, i)),
                    .EtcCorpNet = SafeLng(objRq.GetDataValue(13, i))
                }

                If item.Code.StartsWith("A") Then
                    item.Code = item.Code.Substring(1)
                End If

                result.Add(item)
            Next

            Debug.Print($"CpSvr7210d (투자자={investFlag}): {result.Count}건")

        Catch ex As Exception
            Debug.Print($"CpSvr7210d 예외: {ex.Message}")
        End Try

        Return result
    End Function

    ' ============================================================
    '  안전한 타입 변환 헬퍼 (COM 객체 반환값)
    ' ============================================================
    Private Function SafeStr(val As Object) As String
        If val Is Nothing Then Return ""
        Try : Return CStr(val).Trim() : Catch : Return "" : End Try
    End Function

    Private Function SafeCharStr(val As Object) As String
        If val Is Nothing Then Return ""
        Try
            Dim c = CStr(val).Trim()
            Select Case c
                Case "1" : Return "확정"
                Case "2" : Return "잠정"
                Case Else : Return c
            End Select
        Catch : Return "" : End Try
    End Function

    Private Function SafeLng(val As Object) As Long
        If val Is Nothing Then Return 0
        Try : Return CLng(val)
        Catch
            Try : Return CLng(CDbl(val)) : Catch : Return 0 : End Try
        End Try
    End Function

    Private Function SafeSng(val As Object) As Single
        If val Is Nothing Then Return 0
        Try : Return CSng(val) : Catch : Return 0 : End Try
    End Function




    '$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$


    ' 공통 헬퍼: 종목코드에 A 접두사 보장
    Private Function EnsurePrefix(stockCode As String) As String
        If String.IsNullOrEmpty(stockCode) Then Return "A000000"
        If stockCode.StartsWith("A") OrElse stockCode.StartsWith("U") OrElse stockCode.StartsWith("J") Then
            Return stockCode
        End If
        Return "A" & stockCode
    End Function

End Class

Public Class Candle
    Public Property Timestamp As DateTime
    Public Property Open As Double
    Public Property High As Double
    Public Property Low As Double
    Public Property Close As Double
    Public Property Volume As Double
    Public Property TradingValue As Long
    Public Property PriceChange As Integer?
    Public Property ChangeRate As Double?
    Public Property ChangeSign As String
    Public Property SharesOutstanding As Long?
    Public Property MarketCap As Long?
End Class

