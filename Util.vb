Imports System
Imports System.Globalization
Imports System.Collections.Generic

Public Module Util
    ' [Time Standard] yyyyMMddHHmmss (14 digits)
    ' This ensures correct sorting and minute/second precision
    Public Const TimeFormat As String = "yyyyMMddHHmmss"


    ' 현재 영업일 반환
    Public Function GetAdjustedDate() As String
        Dim currentDate As DateTime = DateTime.Now
        Dim adjustedDate As DateTime = GetLastBusinessDay(currentDate)
        Return adjustedDate.ToString("yyyyMMdd")
    End Function

    ' 현재 영업일 보다 하루전 반환
    Public Function GetAdjustedPreviousDate() As String
        ' Get the adjusted date (마지막 영업일)
        Dim adjustedDate As DateTime = DateTime.ParseExact(GetAdjustedDate(), "yyyyMMdd", Nothing)

        ' 하루 전 날짜로 이동
        Dim previousDay As DateTime = adjustedDate.AddDays(-1)

        ' 공휴일 및 주말을 제외하고 영업일을 찾는 루프
        While IsHolidayOrWeekend(previousDay)
            previousDay = previousDay.AddDays(-1)
        End While

        ' 이전 영업일을 yyyyMMdd 형식으로 반환
        Return previousDay.ToString("yyyyMMdd")
    End Function
    Public Function toDate(yyyymmdd As String) As Date
        Dim newDate As Date = New Date(yyyymmdd.Substring(0, 4), yyyymmdd.Substring(4, 2), yyyymmdd.Substring(6, 2), 0, 0, 0)
        Return newDate
    End Function
    ' 공휴일 및 주말을 체크하는 함수
    Public Function IsHolidayOrWeekend(ByVal targetDate As DateTime) As Boolean
        ' 공휴일 리스트를 정의 (국가별 공휴일을 추가)
        Dim holidays As New List(Of Date) From {
        New Date(targetDate.Year, 1, 1),    ' 신정
        New Date(targetDate.Year, 5, 1),    ' 노동자의날
        New Date(targetDate.Year, 5, 5),    ' 어린이날
        New Date(targetDate.Year, 5, 6),    ' 대체공휴일
        New Date(targetDate.Year, 6, 3),    ' 대통령선거
        New Date(targetDate.Year, 9, 16),   ' 추석
        New Date(targetDate.Year, 9, 17),   ' 추석
        New Date(targetDate.Year, 9, 18),   ' 추석
        New Date(targetDate.Year, 10, 1),   ' 국군의날
        New Date(targetDate.Year, 10, 3),   ' 개천절
        New Date(targetDate.Year, 10, 9),   ' 한글날
        New Date(targetDate.Year, 12, 25)   ' 성탄절
    }

        ' 주말이거나 공휴일이면 True 반환
        Return targetDate.DayOfWeek = DayOfWeek.Saturday OrElse targetDate.DayOfWeek = DayOfWeek.Sunday OrElse holidays.Contains(targetDate.Date)
    End Function



    ' 지정한 일자 이전 영업일 반환 
    Public Function GetLastBusinessDay(ByVal targetDate As DateTime) As Date
        ' 공휴일 리스트 (여기에 국가별 공휴일을 추가)
        Dim holidays As New List(Of Date) From {
        New Date(targetDate.Year, 1, 1),    ' 신정
        New Date(targetDate.Year, 5, 1),    ' 노동자의날
        New Date(targetDate.Year, 5, 5),    ' 어린이날
        New Date(targetDate.Year, 5, 6),    ' 대체공휴일
        New Date(targetDate.Year, 6, 3),    ' 대통령선거
        New Date(targetDate.Year, 6, 6),    ' 현충일
        New Date(targetDate.Year, 9, 16),   ' 추석
        New Date(targetDate.Year, 9, 17),   ' 추석
        New Date(targetDate.Year, 9, 18),   ' 추석
        New Date(targetDate.Year, 10, 3),   ' 개천절
        New Date(targetDate.Year, 10, 9),   ' 한글날
        New Date(targetDate.Year, 12, 25)   ' 성탄절
    }

        ' 오늘 날짜를 기준으로 처리
        Dim currentDay As Date = targetDate.Date ' 날짜 부분만 추출하여 사용

        ' 09:00 이전이면 전날로 설정
        If targetDate.TimeOfDay < New TimeSpan(9, 0, 0) Then
            currentDay = currentDay.AddDays(-1)
        End If

        ' 공휴일 또는 주말을 확인하고, 공휴일이거나 주말이면 그 전날로 조정
        While holidays.Contains(currentDay) OrElse currentDay.DayOfWeek = DayOfWeek.Saturday OrElse currentDay.DayOfWeek = DayOfWeek.Sunday
            currentDay = currentDay.AddDays(-1)
        End While

        ' 마지막 영업일 반환
        Return currentDay
    End Function
    ' 지정한 일자 이후 영업일 반환 
    Public Function GetNextBusinessDay(ByVal targetDate As DateTime) As Date
        ' 공휴일 리스트 (여기에 국가별 공휴일을 추가)
        Dim holidays As New List(Of Date) From {
        New Date(targetDate.Year, 1, 1),    ' 신정
        New Date(targetDate.Year, 5, 1),    ' 노동자의날
        New Date(targetDate.Year, 5, 5),    ' 어린이날
        New Date(targetDate.Year, 5, 6),    ' 대체공휴일
        New Date(targetDate.Year, 6, 3),    ' 대통령선거
        New Date(targetDate.Year, 6, 6),    ' 현충일
        New Date(targetDate.Year, 9, 16),   ' 추석
        New Date(targetDate.Year, 9, 17),   ' 추석
        New Date(targetDate.Year, 9, 18),   ' 추석
        New Date(targetDate.Year, 10, 3),   ' 개천절
        New Date(targetDate.Year, 10, 9),   ' 한글날
        New Date(targetDate.Year, 12, 25)   ' 성탄절
}

        ' 다음날 설정
        Dim nextDay As Date = targetDate.Date.AddDays(1)

        ' 공휴일 또는 주말을 확인하고, 공휴일이거나 주말이면 그 다음날로 조정
        While holidays.Contains(nextDay) OrElse nextDay.DayOfWeek = DayOfWeek.Saturday OrElse nextDay.DayOfWeek = DayOfWeek.Sunday
            nextDay = nextDay.AddDays(1)
        End While

        ' 다음 영업일 반환
        Return nextDay
    End Function



    ' Convert Kiwoom Trade Time (HHmmss) to Standard Timestamp (yyyyMMddHHmmss)
    ' uses Today for Date part
    Public Function ToTimestamp(timeHHmmss As String) As String
        Dim now = DateTime.Now
        Return now.ToString("yyyyMMdd") & timeHHmmss
    End Function

    ' Convert DateTime to Standard Timestamp
    Public Function ToTimestamp(dt As DateTime) As String
        Return dt.ToString(TimeFormat)
    End Function

    ' Code Standardization (Remove "A", trim spaces)
    Public Function NormalizeCode(code As String) As String
        If String.IsNullOrEmpty(code) Then Return ""
        code = code.Trim()
        If code.StartsWith("A", StringComparison.OrdinalIgnoreCase) Then
            Return code.Substring(1)
        End If
        Return code
    End Function

    ' Convert internal code to Cybos format (Add "A" if needed)
    ' Most Cybos APIs expect "A" prefix for stocks
    Public Function ToCybosCode(code As String) As String
        Dim c = NormalizeCode(code)
        If String.IsNullOrEmpty(c) Then Return ""
        Return "A" & c
    End Function

    ' Format for display or logging
    Public Function FormatPrice(price As Double) As String
        Return price.ToString("#,##0")
    End Function

#Region "Math"

    Public Function stoi(s As String) As Integer
        Dim trimmed As String = s.Trim()
        Dim result As Integer
        If Integer.TryParse(trimmed, result) Then
            Return Math.Abs(result)
        Else
            Return 0
        End If
    End Function

    Public Function sTol(s As String, Optional signed As Boolean = False) As Long
        Dim trimmed As String = s.Trim()
        Dim result As Long
        If Long.TryParse(trimmed, result) Then
            Dim finalResult = If(signed, result, Math.Abs(result))
            ' Util.LogToFile($"Util.sTol: Input='{s}', Parsed='{result}', Signed='{signed}', Output='{finalResult}'")
            Return finalResult
        Else
            ' Util.LogToFile($"Util.sTol: FAILED to parse Input='{s}'")
            Return 0
        End If
    End Function

    Public Function sTod(s As String, Optional signed As Boolean = False) As Double
        Dim trimmed As String = s.Trim()
        Dim result As Double
        If Double.TryParse(trimmed, result) Then
            Return If(signed, result, Math.Abs(result))
        Else
            Return 0.0
        End If
    End Function
    Public Function sToDate(ByVal input As String, ByVal format As String) As DateTime
        Dim output As DateTime
        If DateTime.TryParseExact(input.Trim, format, CultureInfo.InvariantCulture, DateTimeStyles.None, output) Then
            Return output
        Else
            Return Nothing 'DateTime.MinValue ' or some other default value
        End If
    End Function
    Public Function sToDate(s As String) As DateTime
        Dim trimmed As String = s.Trim()
        Dim result As DateTime

        If trimmed.Length = 6 Then
            Dim currentDate As DateTime = DateTime.Now
            trimmed = currentDate.ToString("yyyyMMdd") & trimmed
        End If

        If DateTime.TryParseExact(trimmed, "yyyyMMddHHmmss", CultureInfo.InvariantCulture, DateTimeStyles.None, result) Then
            Return result
        Else
            Return DateTime.MinValue
        End If
    End Function

    Public Function sToSpan(timeString As String) As TimeSpan
        Try
            Dim hms As TimeSpan = TimeSpan.ParseExact(timeString, "hhmmss", CultureInfo.InvariantCulture)
            Return hms
        Catch ex As Exception
            Throw New FormatException("Invalid time format. Expected format is 'hhmmss'.", ex)
        End Try
    End Function

    Public Function ValidateTicker(s As String, length As Integer) As String
        Dim trimmed As String = s.Trim()
        If trimmed.Length = length Then
            Return trimmed
        Else
            Return String.Empty
        End If
    End Function

    Public Function ToDigit(value As Double, digits As Integer) As Double
        Return Math.Round(value, digits)
    End Function

#End Region

End Module
