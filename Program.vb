Imports System.Runtime.ExceptionServices

Public Module Program
    <STAThread>
    <HandleProcessCorruptedStateExceptions>
    Public Sub Main()
        Try
            Application.EnableVisualStyles()
            Application.SetCompatibleTextRenderingDefault(False)

            Dim form As New ApiHostForm()
            form.Show()
            Application.DoEvents()

            Dim logger As New SimpleLogger("KiwoomServer.log")
            logger.Info("Starting KiwoomServer (Stable Revision)...")
            IO.File.WriteAllText("DEBUG_BOOT.txt", "1. Form Shown" & vbCrLf)

            Dim apiSvc As New KiwoomApiService(form.ApiControl, logger)
            IO.File.AppendAllText("DEBUG_BOOT.txt", "2. ApiService Created" & vbCrLf)

            ' [CRITICAL] Trigger Login AFTER Service Creation (so event handlers are ready)
            form.AxKHOpenAPI1.CommConnect()

            Dim rtSvc As New RealtimeDataService(form.ApiControl, logger)
            Dim exeHub As New ExecutionHub(form.ApiControl, logger, apiSvc)
            Dim web As New WebApiServer(apiSvc, rtSvc, exeHub, logger)

            ' ★ 프로그램매매 실시간 → WebSocket 중계 연결
            apiSvc.InitProgramTradeRealtimeBroadcast(rtSvc)

            Dim portStr As String = System.Configuration.ConfigurationManager.AppSettings("Port")
            If String.IsNullOrEmpty(portStr) Then portStr = "8082"

            Dim url As String = $"http://localhost:{portStr}"

            web.Start(url)
            IO.File.AppendAllText("DEBUG_BOOT.txt", "3. WebServer Started" & vbCrLf)
            
            logger.Info($"Server is ready at {url}")
            ApiConsoleGuide.Print(url)
            
            Application.Run(form)
        Catch ex As Exception
            IO.File.WriteAllText("CRASH.txt", ex.ToString())
            MessageBox.Show("Fatal Startup Error: " & ex.ToString())
        End Try
    End Sub
End Module
