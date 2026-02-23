Imports System.Windows.Forms
Imports AxKHOpenAPILib

Public Class ApiHostForm
    Inherits Form
    Friend ReadOnly Property ApiControl As AxKHOpenAPILib.AxKHOpenAPI
        Get
            Return Me.AxKHOpenAPI1
        End Get
    End Property
End Class
