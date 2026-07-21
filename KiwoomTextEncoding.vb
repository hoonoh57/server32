Imports System.Text

''' <summary>
''' Repairs Korean text at the Kiwoom COM boundary.
'''
''' Some OpenAPI installations expose CP949 bytes as one Unicode character per byte.
''' HTTP and JSON must receive the repaired Unicode value, never the byte-expanded text.
''' </summary>
Public NotInheritable Class KiwoomTextEncoding
    Private Shared ReadOnly StrictKorean As Encoding =
        Encoding.GetEncoding(949, EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback)
    Private Shared ReadOnly StrictUtf8 As New UTF8Encoding(False, True)
    Private Shared ReadOnly Windows1252ReverseMap As IReadOnlyDictionary(Of Char, Byte) =
        New Dictionary(Of Char, Byte) From {
            {ChrW(&H20AC), &H80}, {ChrW(&H201A), &H82}, {ChrW(&H192), &H83}, {ChrW(&H201E), &H84},
            {ChrW(&H2026), &H85}, {ChrW(&H2020), &H86}, {ChrW(&H2021), &H87}, {ChrW(&H2C6), &H88},
            {ChrW(&H2030), &H89}, {ChrW(&H160), &H8A}, {ChrW(&H2039), &H8B}, {ChrW(&H152), &H8C},
            {ChrW(&H17D), &H8E}, {ChrW(&H2018), &H91}, {ChrW(&H2019), &H92}, {ChrW(&H201C), &H93},
            {ChrW(&H201D), &H94}, {ChrW(&H2022), &H95}, {ChrW(&H2013), &H96}, {ChrW(&H2014), &H97},
            {ChrW(&H2DC), &H98}, {ChrW(&H2122), &H99}, {ChrW(&H161), &H9A}, {ChrW(&H203A), &H9B},
            {ChrW(&H153), &H9C}, {ChrW(&H17E), &H9E}, {ChrW(&H178), &H9F}
        }

    Private Sub New()
    End Sub

    Public Shared Function NormalizeKorean(value As String) As String
        If String.IsNullOrEmpty(value) Then Return value

        Dim bytes = TryReconstructSingleByteData(value)
        If bytes Is Nothing Then Return value

        Dim bestValue = value
        Dim bestHangulCount = CountHangul(value)
        ConsiderCandidate(TryDecode(StrictKorean, bytes), bestValue, bestHangulCount)
        ConsiderCandidate(TryDecode(StrictUtf8, bytes), bestValue, bestHangulCount)
        Return bestValue
    End Function

    Public Shared Function WasNormalized(original As String, normalized As String) As Boolean
        Return Not String.Equals(original, normalized, StringComparison.Ordinal)
    End Function

    Public Shared Sub VerifyOrThrow()
        Const sample As String = "한글 조건식"
        Dim encoded = StrictKorean.GetBytes(sample)
        Dim expanded(encoded.Length - 1) As Char
        For index As Integer = 0 To encoded.Length - 1
            expanded(index) = ChrW(encoded(index))
        Next

        Dim repaired = NormalizeKorean(New String(expanded))
        If Not String.Equals(repaired, sample, StringComparison.Ordinal) Then
            Throw New InvalidOperationException("Kiwoom CP949 boundary normalization self-test failed.")
        End If

        If Not String.Equals(NormalizeKorean(sample), sample, StringComparison.Ordinal) Then
            Throw New InvalidOperationException("Kiwoom Unicode preservation self-test failed.")
        End If
    End Sub

    Private Shared Function TryReconstructSingleByteData(value As String) As Byte()
        Dim bytes(value.Length - 1) As Byte
        For index As Integer = 0 To value.Length - 1
            Dim character = value(index)
            Dim code = AscW(character)
            If code >= 0 AndAlso code <= Byte.MaxValue Then
                bytes(index) = CByte(code)
                Continue For
            End If

            Dim mapped As Byte
            If Not Windows1252ReverseMap.TryGetValue(character, mapped) Then Return Nothing
            bytes(index) = mapped
        Next
        Return bytes
    End Function

    Private Shared Function TryDecode(encoding As Encoding, bytes As Byte()) As String
        Try
            Return encoding.GetString(bytes)
        Catch ex As DecoderFallbackException
            Return Nothing
        End Try
    End Function

    Private Shared Sub ConsiderCandidate(candidate As String, ByRef bestValue As String, ByRef bestHangulCount As Integer)
        If String.IsNullOrEmpty(candidate) Then Return
        Dim candidateHangulCount = CountHangul(candidate)
        If candidateHangulCount <= bestHangulCount Then Return
        bestValue = candidate
        bestHangulCount = candidateHangulCount
    End Sub

    Private Shared Function CountHangul(value As String) As Integer
        Dim count = 0
        For Each character As Char In value
            Dim code = AscW(character)
            If (code >= &HAC00 AndAlso code <= &HD7A3) OrElse
               (code >= &H1100 AndAlso code <= &H11FF) OrElse
               (code >= &H3130 AndAlso code <= &H318F) Then
                count += 1
            End If
        Next
        Return count
    End Function
End Class

