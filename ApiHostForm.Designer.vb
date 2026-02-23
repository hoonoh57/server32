<Global.Microsoft.VisualBasic.CompilerServices.DesignerGenerated()> _
Partial Class ApiHostForm
    Inherits System.Windows.Forms.Form

    <System.Diagnostics.DebuggerNonUserCode()> _
    Protected Overrides Sub Dispose(ByVal disposing As Boolean)
        Try
            If disposing AndAlso components IsNot Nothing Then
                components.Dispose()
            End If
        Finally
            MyBase.Dispose(disposing)
        End Try
    End Sub

    Private components As System.ComponentModel.IContainer

    <System.Diagnostics.DebuggerStepThrough()> _
    Private Sub InitializeComponent()
        Dim resources As System.ComponentModel.ComponentResourceManager = New System.ComponentModel.ComponentResourceManager(GetType(ApiHostForm))
        Me.AxKHOpenAPI1 = New AxKHOpenAPILib.AxKHOpenAPI()
        CType(Me.AxKHOpenAPI1, System.ComponentModel.ISupportInitialize).BeginInit()
        Me.SuspendLayout()
        '
        'AxKHOpenAPI1
        '
        Me.AxKHOpenAPI1.Dock = System.Windows.Forms.DockStyle.Fill
        Me.AxKHOpenAPI1.Enabled = True
        Me.AxKHOpenAPI1.Location = New System.Drawing.Point(0, 0)
        Me.AxKHOpenAPI1.Name = "AxKHOpenAPI1"
        Me.AxKHOpenAPI1.OcxState = CType(resources.GetObject("AxKHOpenAPI1.OcxState"), System.Windows.Forms.AxHost.State)
        Me.AxKHOpenAPI1.Size = New System.Drawing.Size(218, 61)
        Me.AxKHOpenAPI1.TabIndex = 0
        '
        'ApiHostForm
        '
        Me.AutoScaleDimensions = New System.Drawing.SizeF(7.0!, 12.0!)
        Me.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font
        Me.ClientSize = New System.Drawing.Size(218, 61)
        Me.Controls.Add(Me.AxKHOpenAPI1)
        Me.Name = "ApiHostForm"
        Me.Text = "ApiHostForm"
        Me.WindowState = System.Windows.Forms.FormWindowState.Minimized
        CType(Me.AxKHOpenAPI1, System.ComponentModel.ISupportInitialize).EndInit()
        Me.ResumeLayout(False)

    End Sub

    Friend WithEvents AxKHOpenAPI1 As AxKHOpenAPILib.AxKHOpenAPI
End Class
