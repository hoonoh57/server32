Imports System
Imports System.IO
Imports Newtonsoft.Json

' [Immutable Models]
Public Class ApiResponse
    Public Property Success As Boolean
    Public Property Message As String
    Public Property Data As Object
    <JsonIgnore>
    Public Property StatusCode As Integer = 200

    Public Shared Function Ok(Optional data As Object = Nothing, Optional message As String = "OK", Optional status As Integer = 200) As ApiResponse
        Return New ApiResponse With {.Success = True, .Message = message, .Data = data, .StatusCode = status}
    End Function

    Public Shared Function Err(message As String, Optional status As Integer = 400, Optional data As Object = Nothing) As ApiResponse
        Return New ApiResponse With {.Success = False, .Message = message, .Data = data, .StatusCode = status}
    End Function
End Class

Public Class KiwoomStatusData
    Public Property IsLoggedIn As Boolean
    Public Property AccountNo As String
    Public Property ServerName As String
End Class

Public Class OrderRequest
    Public Property AccountNo As String
    Public Property StockCode As String
    Public Property OrderType As Integer 
    Public Property Quantity As Integer
    Public Property Price As Integer
    Public Property QuoteType As String
End Class

Public Class ConditionInfo
    Public Property Index As Integer
    Public Property Name As String
End Class

Public Class AccountSnapshot
    Public Property AccountNo As String
    Public Property FetchedAt As DateTime
    Public Property TotalPurchase As Double
    Public Property TotalEvaluation As Double
    Public Property TotalPnL As Double
    Public Property TotalPnLRate As Double
    Public Property RealizedPnL As Double
    Public Property DepositAvailable As Double
    Public Property DepositWithdrawable As Double
    Public Property Holdings As List(Of Dictionary(Of String, String))
    Public Property Outstanding As List(Of Dictionary(Of String, String))
    Public Property RawBalance As List(Of Dictionary(Of String, String))
    Public Property RawDeposit As List(Of Dictionary(Of String, String))
    Public Property RawOutstanding As List(Of Dictionary(Of String, String))
End Class

' [Logger]
' [Logger]
Public Class SimpleLogger
    Private ReadOnly _logDir As String
    Private ReadOnly _baseFileName As String
    Private Shared ReadOnly _lock As New Object()

    Public Sub New(fileName As String)
        _logDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Logs")
        _baseFileName = fileName
        
        Try
            Directory.CreateDirectory(_logDir)
            CleanupOldLogs()
        Catch
        End Try
    End Sub

    Public Sub Info(message As String)
        Log("INFO", message)
    End Sub

    Public Sub Warn(message As String)
        Log("WARN", message)
    End Sub

    Public Sub Errors(message As String)
        Log("ERROR", message)
    End Sub

    Private Sub Log(level As String, message As String)
        SyncLock _lock
            Dim line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{level}] {message}"
            Console.WriteLine(line)
            
            Try
                Dim dateStr = DateTime.Now.ToString("yyyy-MM-dd")
                Dim nameWoExt = Path.GetFileNameWithoutExtension(_baseFileName)
                Dim ext = Path.GetExtension(_baseFileName)
                Dim currentPath = Path.Combine(_logDir, $"{nameWoExt}_{dateStr}{ext}")
                
                File.AppendAllText(currentPath, line & Environment.NewLine)
            Catch
            End Try
        End SyncLock
    End Sub

    Private Sub CleanupOldLogs()
        Try
            Dim cutoff = DateTime.Now.AddDays(-7)
            Dim dirInfo As New DirectoryInfo(_logDir)
            For Each f As FileInfo In dirInfo.GetFiles()
                If f.LastWriteTime < cutoff Then
                    f.Delete()
                End If
            Next
        Catch
        End Try
    End Sub
End Class
