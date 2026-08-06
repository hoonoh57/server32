Imports System.Globalization
Imports System.IO
Imports System.Linq
Imports System.Security.Cryptography
Imports System.Text
Imports MySqlConnector
Imports Newtonsoft.Json

Public Class StockPoolResolveRequest
    <JsonProperty("names")>
    Public Property Names As List(Of String)
End Class

Public Class StockPoolResolvedSymbol
    <JsonProperty("name")>
    Public Property Name As String

    <JsonProperty("code")>
    Public Property Code As String

    <JsonProperty("market")>
    Public Property Market As String
End Class

Public Class StockPoolRejectedSymbol
    <JsonProperty("input_index")>
    Public Property InputIndex As Integer

    <JsonProperty("name")>
    Public Property Name As String

    <JsonProperty("reason")>
    Public Property Reason As String
End Class

Public Class StockPoolResolveData
    <JsonProperty("resolved")>
    Public Property Resolved As List(Of StockPoolResolvedSymbol)

    <JsonProperty("rejected")>
    Public Property Rejected As List(Of StockPoolRejectedSymbol)

    <JsonProperty("resolved_count")>
    Public Property ResolvedCount As Integer

    <JsonProperty("rejected_count")>
    Public Property RejectedCount As Integer

    <JsonProperty("source")>
    Public Property Source As String
End Class

Public Class StockPoolCohortMemberRequest
    <JsonProperty("code")>
    Public Property Code As String

    <JsonProperty("name")>
    Public Property Name As String

    <JsonProperty("market")>
    Public Property Market As String

    <JsonProperty("return_1m_label")>
    Public Property Return1mLabel As Nullable(Of Decimal)

    <JsonProperty("return_3m_label")>
    Public Property Return3mLabel As Nullable(Of Decimal)

    <JsonProperty("return_7h_label")>
    Public Property Return7hLabel As Nullable(Of Decimal)

    <JsonProperty("maximum_return_label")>
    Public Property MaximumReturnLabel As Nullable(Of Decimal)

    <JsonProperty("capture_volume")>
    Public Property CaptureVolume As Nullable(Of Long)

    <JsonProperty("other_label")>
    Public Property OtherLabel As Nullable(Of Decimal)
End Class

Public Class StockPoolCohortCreateRequest
    <JsonProperty("source_type")>
    Public Property SourceType As String

    <JsonProperty("condition_name")>
    Public Property ConditionName As String

    <JsonProperty("trading_date")>
    Public Property TradingDate As String

    <JsonProperty("capture_time")>
    Public Property CaptureTime As String

    <JsonProperty("timeframe_minutes")>
    Public Property TimeframeMinutes As Integer

    <JsonProperty("members")>
    Public Property Members As List(Of StockPoolCohortMemberRequest)
End Class

Public Class StockPoolCohortCreateData
    <JsonProperty("cohort_id")>
    Public Property CohortId As Long

    <JsonProperty("member_count")>
    Public Property MemberCount As Integer

    <JsonProperty("rejected")>
    Public Property Rejected As List(Of StockPoolRejectedSymbol)

    <JsonProperty("raw_import_hash")>
    Public Property RawImportHash As String

    <JsonProperty("source")>
    Public Property Source As String
End Class

Friend NotInheritable Class StockPoolDbSettings
    Public Property Host As String
    Public Property Port As UInteger
    Public Property User As String
    Public Property Password As String
    Public Property Database As String

    Public Shared Function Load() As StockPoolDbSettings
        Dim values As New Dictionary(Of String, String)(StringComparer.OrdinalIgnoreCase)

        For Each candidate As String In EnvironmentFileCandidates()
            LoadEnvironmentFile(candidate, values)
        Next

        OverrideFromProcessEnvironment(values, "MYSQL_HOST")
        OverrideFromProcessEnvironment(values, "MYSQL_PORT")
        OverrideFromProcessEnvironment(values, "MYSQL_USER")
        OverrideFromProcessEnvironment(values, "MYSQL_PASSWORD")
        OverrideFromProcessEnvironment(values, "MYSQL_DATABASE")

        Dim rawPort As String = GetValue(values, "MYSQL_PORT", "3306")
        Dim portValue As UInteger
        If Not UInteger.TryParse(rawPort, NumberStyles.None, CultureInfo.InvariantCulture, portValue) OrElse
           portValue = 0UI OrElse portValue > 65535UI Then
            Throw New InvalidOperationException("MYSQL_PORT 값이 올바르지 않습니다: " & rawPort)
        End If

        Return New StockPoolDbSettings With {
            .Host = GetValue(values, "MYSQL_HOST", "127.0.0.1"),
            .Port = portValue,
            .User = GetValue(values, "MYSQL_USER", "root"),
            .Password = GetValue(values, "MYSQL_PASSWORD", String.Empty),
            .Database = GetValue(values, "MYSQL_DATABASE", "gate3")
        }
    End Function

    Public Function BuildConnectionString() As String
        Dim builder As New MySqlConnectionStringBuilder With {
            .Server = Host,
            .Port = Port,
            .UserID = User,
            .Password = Password,
            .Database = Database,
            .CharacterSet = "utf8mb4",
            .SslMode = MySqlSslMode.None,
            .Pooling = True,
            .ConnectionTimeout = 5UI,
            .DefaultCommandTimeout = 30UI
        }
        Return builder.ConnectionString
    End Function

    Private Shared Function EnvironmentFileCandidates() As IEnumerable(Of String)
        Dim result As New List(Of String)()
        Dim explicitFile As String = Environment.GetEnvironmentVariable("SERVER32_ENV_FILE")
        If Not String.IsNullOrWhiteSpace(explicitFile) Then
            result.Add(explicitFile.Trim())
        End If

        result.Add(Path.Combine(Environment.CurrentDirectory, ".env"))

        Dim directory As New DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory)
        For level As Integer = 0 To 5
            If directory Is Nothing Then Exit For
            result.Add(Path.Combine(directory.FullName, ".env"))
            directory = directory.Parent
        Next

        Return result.Distinct(StringComparer.OrdinalIgnoreCase)
    End Function

    Private Shared Sub LoadEnvironmentFile(
        path As String,
        values As IDictionary(Of String, String))

        If String.IsNullOrWhiteSpace(path) OrElse Not File.Exists(path) Then Return

        For Each rawLine As String In File.ReadAllLines(path, Encoding.UTF8)
            Dim line As String = rawLine.Trim()
            If line.Length = 0 OrElse line.StartsWith("#", StringComparison.Ordinal) Then
                Continue For
            End If

            Dim equalsIndex As Integer = line.IndexOf("="c)
            If equalsIndex <= 0 Then Continue For

            Dim key As String = line.Substring(0, equalsIndex).Trim()
            Dim value As String = line.Substring(equalsIndex + 1).Trim()
            If value.Length >= 2 Then
                Dim firstCharacter As Char = value(0)
                Dim lastCharacter As Char = value(value.Length - 1)
                Dim doubleQuote As Char = ChrW(34)
                If (firstCharacter = doubleQuote AndAlso lastCharacter = doubleQuote) OrElse
                   (firstCharacter = "'"c AndAlso lastCharacter = "'"c) Then
                    value = value.Substring(1, value.Length - 2)
                End If
            End If

            If key.Length > 0 Then values(key) = value
        Next
    End Sub

    Private Shared Sub OverrideFromProcessEnvironment(
        values As IDictionary(Of String, String),
        key As String)

        Dim value As String = Environment.GetEnvironmentVariable(key)
        If value IsNot Nothing Then values(key) = value
    End Sub

    Private Shared Function GetValue(
        values As IDictionary(Of String, String),
        key As String,
        fallback As String) As String

        Dim value As String = Nothing
        If values.TryGetValue(key, value) Then Return value
        Return fallback
    End Function
End Class

Public NotInheritable Class StockPoolRepository
    Private Const MaximumNames As Integer = 500
    Private ReadOnly _logger As SimpleLogger

    Public Sub New(logger As SimpleLogger)
        _logger = logger
    End Sub

    Public Function ResolveSymbols(request As StockPoolResolveRequest) As ApiResponse
        If request Is Nothing OrElse request.Names Is Nothing Then
            Return ApiResponse.Err("names 배열이 필요합니다.", 400)
        End If
        If request.Names.Count = 0 OrElse request.Names.Count > MaximumNames Then
            Return ApiResponse.Err($"names는 1~{MaximumNames}개여야 합니다.", 400)
        End If

        Try
            Dim settings As StockPoolDbSettings = StockPoolDbSettings.Load()
            Dim rejected As New List(Of StockPoolRejectedSymbol)()
            Dim firstInputIndex As New Dictionary(Of String, Integer)(StringComparer.Ordinal)
            Dim uniqueNames As New List(Of String)()

            For index As Integer = 0 To request.Names.Count - 1
                Dim name As String = If(request.Names(index), String.Empty).Trim()
                If name.Length = 0 Then
                    rejected.Add(New StockPoolRejectedSymbol With {
                        .InputIndex = index,
                        .Name = name,
                        .Reason = "blank_name"
                    })
                ElseIf firstInputIndex.ContainsKey(name) Then
                    rejected.Add(New StockPoolRejectedSymbol With {
                        .InputIndex = index,
                        .Name = name,
                        .Reason = "duplicate_input"
                    })
                Else
                    firstInputIndex(name) = index
                    uniqueNames.Add(name)
                End If
            Next

            Dim databaseMatches As Dictionary(Of String, List(Of StockPoolResolvedSymbol)) =
                ReadSymbolsByExactName(settings, uniqueNames)
            Dim resolved As New List(Of StockPoolResolvedSymbol)()

            For Each name As String In uniqueNames
                Dim matches As List(Of StockPoolResolvedSymbol) = Nothing
                If Not databaseMatches.TryGetValue(name, matches) OrElse matches.Count = 0 Then
                    rejected.Add(New StockPoolRejectedSymbol With {
                        .InputIndex = firstInputIndex(name),
                        .Name = name,
                        .Reason = "exact_name_not_found"
                    })
                ElseIf matches.Count <> 1 Then
                    rejected.Add(New StockPoolRejectedSymbol With {
                        .InputIndex = firstInputIndex(name),
                        .Name = name,
                        .Reason = "exact_name_ambiguous"
                    })
                Else
                    resolved.Add(matches(0))
                End If
            Next

            Dim data As New StockPoolResolveData With {
                .Resolved = resolved,
                .Rejected = rejected.OrderBy(Function(item) item.InputIndex).ToList(),
                .ResolvedCount = resolved.Count,
                .RejectedCount = rejected.Count,
                .Source = settings.Database & ".g3_symbol_master"
            }
            Return ApiResponse.Ok(data)
        Catch ex As Exception
            _logger.Errors("[StockPool] symbol resolve failed: " & ex.Message)
            Return ApiResponse.Err("종목마스터 조회 실패: " & ex.Message, 500)
        End Try
    End Function

    Public Function CreateCohort(request As StockPoolCohortCreateRequest) As ApiResponse
        If request Is Nothing OrElse request.Members Is Nothing Then
            Return ApiResponse.Err("cohort 요청과 members 배열이 필요합니다.", 400)
        End If
        If request.Members.Count = 0 OrElse request.Members.Count > MaximumNames Then
            Return ApiResponse.Err($"members는 1~{MaximumNames}개여야 합니다.", 400)
        End If

        Dim tradingDate As DateTime
        If Not TryParseTradingDate(request.TradingDate, tradingDate) Then
            Return ApiResponse.Err(
                "trading_date 형식은 yyyy-MM-dd 또는 yyyyMMdd여야 합니다.",
                400)
        End If

        Dim captureTime As TimeSpan
        If Not TryParseCaptureTime(request.CaptureTime, captureTime) Then
            Return ApiResponse.Err(
                "capture_time 형식은 HH:mm, HHmm 또는 HH:mm:ss여야 합니다.",
                400)
        End If

        If String.IsNullOrWhiteSpace(request.ConditionName) Then
            Return ApiResponse.Err("condition_name이 필요합니다.", 400)
        End If
        If request.TimeframeMinutes <= 0 OrElse request.TimeframeMinutes > 240 Then
            Return ApiResponse.Err("timeframe_minutes는 1~240이어야 합니다.", 400)
        End If

        Try
            Dim settings As StockPoolDbSettings = StockPoolDbSettings.Load()
            Dim rejected As New List(Of StockPoolRejectedSymbol)()
            Dim validated As List(Of StockPoolCohortMemberRequest) =
                ValidateCohortMembers(settings, request.Members, rejected)

            If validated.Count = 0 Then
                Return ApiResponse.Err(
                    "저장 가능한 종목이 없습니다.",
                    400,
                    New With {.rejected = rejected})
            End If

            Dim sourceType As String = If(request.SourceType, String.Empty).Trim()
            If sourceType.Length = 0 Then sourceType = "kiwoom_1516_clipboard"
            Dim conditionName As String = request.ConditionName.Trim()
            Dim rawImportHash As String = ComputeImportHash(
                sourceType,
                conditionName,
                tradingDate,
                captureTime,
                request.TimeframeMinutes,
                validated)

            Using connection As New MySqlConnection(settings.BuildConnectionString())
                connection.Open()
                EnsureSchema(connection)

                Using transaction As MySqlTransaction = connection.BeginTransaction()
                    Dim cohortId As Long = UpsertCohort(
                        connection,
                        transaction,
                        sourceType,
                        conditionName,
                        tradingDate,
                        captureTime,
                        request.TimeframeMinutes,
                        rawImportHash)

                    Using deleteCommand As MySqlCommand = connection.CreateCommand()
                        deleteCommand.Transaction = transaction
                        deleteCommand.CommandText =
                            "DELETE FROM stock_pool_cohort_member " &
                            "WHERE cohort_id = @cohort_id"
                        deleteCommand.Parameters.AddWithValue("@cohort_id", cohortId)
                        deleteCommand.ExecuteNonQuery()
                    End Using

                    For index As Integer = 0 To validated.Count - 1
                        InsertCohortMember(
                            connection,
                            transaction,
                            cohortId,
                            index,
                            validated(index))
                    Next

                    transaction.Commit()

                    Dim data As New StockPoolCohortCreateData With {
                        .CohortId = cohortId,
                        .MemberCount = validated.Count,
                        .Rejected = rejected.OrderBy(Function(item) item.InputIndex).ToList(),
                        .RawImportHash = rawImportHash,
                        .Source = settings.Database & ".stock_pool_cohort"
                    }
                    Return ApiResponse.Ok(data, "Frozen Cohort 저장 완료")
                End Using
            End Using
        Catch ex As Exception
            _logger.Errors("[StockPool] cohort save failed: " & ex.Message)
            Return ApiResponse.Err("Frozen Cohort 저장 실패: " & ex.Message, 500)
        End Try
    End Function

    Private Shared Function ReadSymbolsByExactName(
        settings As StockPoolDbSettings,
        names As IList(Of String)) As Dictionary(Of String, List(Of StockPoolResolvedSymbol))

        Dim result As New Dictionary(Of String, List(Of StockPoolResolvedSymbol))(
            StringComparer.Ordinal)
        If names Is Nothing OrElse names.Count = 0 Then Return result

        Using connection As New MySqlConnection(settings.BuildConnectionString())
            connection.Open()
            Using command As MySqlCommand = connection.CreateCommand()
                Dim placeholders As New List(Of String)()
                For index As Integer = 0 To names.Count - 1
                    Dim parameterName As String =
                        "@name" & index.ToString(CultureInfo.InvariantCulture)
                    placeholders.Add(parameterName)
                    command.Parameters.AddWithValue(parameterName, names(index))
                Next

                command.CommandText =
                    "SELECT code, name, COALESCE(market, '') " &
                    "FROM g3_symbol_master " &
                    "WHERE delisted = 0 AND BINARY name IN (" &
                    String.Join(",", placeholders) & ") " &
                    "ORDER BY name, code"

                Using reader As MySqlDataReader = command.ExecuteReader()
                    While reader.Read()
                        Dim item As New StockPoolResolvedSymbol With {
                            .Code = reader.GetString(0).Trim(),
                            .Name = reader.GetString(1).Trim(),
                            .Market = If(
                                reader.IsDBNull(2),
                                String.Empty,
                                reader.GetString(2).Trim())
                        }

                        Dim matches As List(Of StockPoolResolvedSymbol) = Nothing
                        If Not result.TryGetValue(item.Name, matches) Then
                            matches = New List(Of StockPoolResolvedSymbol)()
                            result(item.Name) = matches
                        End If
                        matches.Add(item)
                    End While
                End Using
            End Using
        End Using

        Return result
    End Function

    Private Shared Function ValidateCohortMembers(
        settings As StockPoolDbSettings,
        members As IList(Of StockPoolCohortMemberRequest),
        rejected As IList(Of StockPoolRejectedSymbol)) As List(Of StockPoolCohortMemberRequest)

        Dim uniqueCodes As New List(Of String)()
        Dim firstCodeIndex As New Dictionary(Of String, Integer)(StringComparer.Ordinal)

        For index As Integer = 0 To members.Count - 1
            Dim code As String = If(members(index).Code, String.Empty).Trim()
            If code.Length = 0 Then
                rejected.Add(New StockPoolRejectedSymbol With {
                    .InputIndex = index,
                    .Name = If(members(index).Name, String.Empty),
                    .Reason = "blank_code"
                })
            ElseIf firstCodeIndex.ContainsKey(code) Then
                rejected.Add(New StockPoolRejectedSymbol With {
                    .InputIndex = index,
                    .Name = If(members(index).Name, String.Empty),
                    .Reason = "duplicate_code"
                })
            Else
                firstCodeIndex(code) = index
                uniqueCodes.Add(code)
            End If
        Next

        Dim masterByCode As Dictionary(Of String, StockPoolResolvedSymbol) =
            ReadSymbolsByCode(settings, uniqueCodes)
        Dim validated As New List(Of StockPoolCohortMemberRequest)()

        For Each code As String In uniqueCodes
            Dim index As Integer = firstCodeIndex(code)
            Dim input As StockPoolCohortMemberRequest = members(index)
            Dim master As StockPoolResolvedSymbol = Nothing

            If Not masterByCode.TryGetValue(code, master) Then
                rejected.Add(New StockPoolRejectedSymbol With {
                    .InputIndex = index,
                    .Name = If(input.Name, String.Empty),
                    .Reason = "code_not_found"
                })
                Continue For
            End If

            Dim inputName As String = If(input.Name, String.Empty).Trim()
            If Not String.Equals(inputName, master.Name, StringComparison.Ordinal) Then
                rejected.Add(New StockPoolRejectedSymbol With {
                    .InputIndex = index,
                    .Name = inputName,
                    .Reason = "code_name_mismatch"
                })
                Continue For
            End If

            input.Code = master.Code
            input.Name = master.Name
            input.Market = master.Market
            validated.Add(input)
        Next

        Return validated
    End Function

    Private Shared Function ReadSymbolsByCode(
        settings As StockPoolDbSettings,
        codes As IList(Of String)) As Dictionary(Of String, StockPoolResolvedSymbol)

        Dim result As New Dictionary(Of String, StockPoolResolvedSymbol)(StringComparer.Ordinal)
        If codes Is Nothing OrElse codes.Count = 0 Then Return result

        Using connection As New MySqlConnection(settings.BuildConnectionString())
            connection.Open()
            Using command As MySqlCommand = connection.CreateCommand()
                Dim placeholders As New List(Of String)()
                For index As Integer = 0 To codes.Count - 1
                    Dim parameterName As String =
                        "@code" & index.ToString(CultureInfo.InvariantCulture)
                    placeholders.Add(parameterName)
                    command.Parameters.AddWithValue(parameterName, codes(index))
                Next

                command.CommandText =
                    "SELECT code, name, COALESCE(market, '') " &
                    "FROM g3_symbol_master " &
                    "WHERE delisted = 0 AND code IN (" &
                    String.Join(",", placeholders) & ")"

                Using reader As MySqlDataReader = command.ExecuteReader()
                    While reader.Read()
                        Dim item As New StockPoolResolvedSymbol With {
                            .Code = reader.GetString(0).Trim(),
                            .Name = reader.GetString(1).Trim(),
                            .Market = If(
                                reader.IsDBNull(2),
                                String.Empty,
                                reader.GetString(2).Trim())
                        }
                        result(item.Code) = item
                    End While
                End Using
            End Using
        End Using

        Return result
    End Function

    Private Shared Sub EnsureSchema(connection As MySqlConnection)
        Dim statements As String() = {
            "CREATE TABLE IF NOT EXISTS stock_pool_cohort (" &
            "cohort_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT," &
            "source_type VARCHAR(40) NOT NULL," &
            "condition_name VARCHAR(160) NOT NULL," &
            "trading_date DATE NOT NULL," &
            "capture_time TIME NOT NULL," &
            "timeframe_minutes INT NOT NULL," &
            "raw_import_hash CHAR(64) CHARACTER SET ascii NOT NULL," &
            "created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)," &
            "PRIMARY KEY (cohort_id)," &
            "UNIQUE KEY uq_stock_pool_cohort_import " &
            "(source_type, condition_name, trading_date, capture_time, raw_import_hash)," &
            "KEY ix_stock_pool_cohort_lookup " &
            "(trading_date, condition_name, capture_time)" &
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci",
            "CREATE TABLE IF NOT EXISTS stock_pool_cohort_member (" &
            "cohort_id BIGINT UNSIGNED NOT NULL," &
            "member_ordinal INT NOT NULL," &
            "code VARCHAR(16) CHARACTER SET ascii NOT NULL," &
            "name VARCHAR(160) NOT NULL," &
            "market VARCHAR(32) NULL," &
            "return_1m_label DECIMAL(12,6) NULL," &
            "return_3m_label DECIMAL(12,6) NULL," &
            "return_7h_label DECIMAL(12,6) NULL," &
            "maximum_return_label DECIMAL(12,6) NULL," &
            "capture_volume BIGINT NULL," &
            "other_label DECIMAL(18,6) NULL," &
            "created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)," &
            "PRIMARY KEY (cohort_id, code)," &
            "UNIQUE KEY uq_stock_pool_cohort_member_ordinal " &
            "(cohort_id, member_ordinal)," &
            "CONSTRAINT fk_stock_pool_cohort_member_cohort " &
            "FOREIGN KEY (cohort_id) REFERENCES stock_pool_cohort(cohort_id) " &
            "ON DELETE CASCADE" &
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        }

        For Each statement As String In statements
            Using command As MySqlCommand = connection.CreateCommand()
                command.CommandText = statement
                command.ExecuteNonQuery()
            End Using
        Next
    End Sub

    Private Shared Function UpsertCohort(
        connection As MySqlConnection,
        transaction As MySqlTransaction,
        sourceType As String,
        conditionName As String,
        tradingDate As DateTime,
        captureTime As TimeSpan,
        timeframeMinutes As Integer,
        rawImportHash As String) As Long

        Using command As MySqlCommand = connection.CreateCommand()
            command.Transaction = transaction
            command.CommandText =
                "INSERT INTO stock_pool_cohort " &
                "(source_type, condition_name, trading_date, capture_time, " &
                "timeframe_minutes, raw_import_hash) " &
                "VALUES (@source_type, @condition_name, @trading_date, " &
                "@capture_time, @timeframe_minutes, @raw_import_hash) " &
                "ON DUPLICATE KEY UPDATE cohort_id = LAST_INSERT_ID(cohort_id)"
            command.Parameters.AddWithValue("@source_type", sourceType)
            command.Parameters.AddWithValue("@condition_name", conditionName)
            command.Parameters.AddWithValue("@trading_date", tradingDate.Date)
            command.Parameters.AddWithValue("@capture_time", captureTime)
            command.Parameters.AddWithValue("@timeframe_minutes", timeframeMinutes)
            command.Parameters.AddWithValue("@raw_import_hash", rawImportHash)
            command.ExecuteNonQuery()

            Dim cohortId As Long = command.LastInsertedId
            If cohortId <= 0 Then
                Throw New InvalidOperationException("cohort_id를 확인하지 못했습니다.")
            End If
            Return cohortId
        End Using
    End Function

    Private Shared Sub InsertCohortMember(
        connection As MySqlConnection,
        transaction As MySqlTransaction,
        cohortId As Long,
        ordinal As Integer,
        member As StockPoolCohortMemberRequest)

        Using command As MySqlCommand = connection.CreateCommand()
            command.Transaction = transaction
            command.CommandText =
                "INSERT INTO stock_pool_cohort_member " &
                "(cohort_id, member_ordinal, code, name, market, " &
                "return_1m_label, return_3m_label, return_7h_label, " &
                "maximum_return_label, capture_volume, other_label) " &
                "VALUES (@cohort_id, @member_ordinal, @code, @name, @market, " &
                "@return_1m, @return_3m, @return_7h, @maximum_return, " &
                "@capture_volume, @other_label)"
            command.Parameters.AddWithValue("@cohort_id", cohortId)
            command.Parameters.AddWithValue("@member_ordinal", ordinal)
            command.Parameters.AddWithValue("@code", member.Code)
            command.Parameters.AddWithValue("@name", member.Name)
            command.Parameters.AddWithValue(
                "@market",
                If(
                    String.IsNullOrWhiteSpace(member.Market),
                    CType(DBNull.Value, Object),
                    member.Market))
            command.Parameters.AddWithValue("@return_1m", NullableDbValue(member.Return1mLabel))
            command.Parameters.AddWithValue("@return_3m", NullableDbValue(member.Return3mLabel))
            command.Parameters.AddWithValue("@return_7h", NullableDbValue(member.Return7hLabel))
            command.Parameters.AddWithValue(
                "@maximum_return",
                NullableDbValue(member.MaximumReturnLabel))
            command.Parameters.AddWithValue(
                "@capture_volume",
                NullableDbValue(member.CaptureVolume))
            command.Parameters.AddWithValue("@other_label", NullableDbValue(member.OtherLabel))
            command.ExecuteNonQuery()
        End Using
    End Sub

    Private Shared Function NullableDbValue(Of T As Structure)(
        value As Nullable(Of T)) As Object

        If value.HasValue Then Return value.Value
        Return DBNull.Value
    End Function

    Private Shared Function TryParseTradingDate(
        value As String,
        ByRef result As DateTime) As Boolean

        Return DateTime.TryParseExact(
            If(value, String.Empty).Trim(),
            {"yyyy-MM-dd", "yyyyMMdd"},
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            result)
    End Function

    Private Shared Function TryParseCaptureTime(
        value As String,
        ByRef result As TimeSpan) As Boolean

        Dim parsed As DateTime
        If DateTime.TryParseExact(
                If(value, String.Empty).Trim(),
                {"HH:mm", "HHmm", "HH:mm:ss"},
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                parsed) Then
            result = parsed.TimeOfDay
            Return True
        End If
        Return False
    End Function

    Private Shared Function ComputeImportHash(
        sourceType As String,
        conditionName As String,
        tradingDate As DateTime,
        captureTime As TimeSpan,
        timeframeMinutes As Integer,
        members As IEnumerable(Of StockPoolCohortMemberRequest)) As String

        Dim builder As New StringBuilder()
        builder.Append(sourceType).Append("|").Append(conditionName).Append("|")
        builder.Append(
            tradingDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).Append("|")
        builder.Append(captureTime.ToString()).Append("|")
        builder.Append(timeframeMinutes.ToString(CultureInfo.InvariantCulture)).AppendLine()

        For Each member As StockPoolCohortMemberRequest In members
            builder.Append(member.Code).Append("|")
            builder.Append(member.Name).Append("|")
            builder.Append(member.Market).Append("|")
            AppendNullable(builder, member.Return1mLabel)
            AppendNullable(builder, member.Return3mLabel)
            AppendNullable(builder, member.Return7hLabel)
            AppendNullable(builder, member.MaximumReturnLabel)
            If member.CaptureVolume.HasValue Then
                builder.Append(
                    member.CaptureVolume.Value.ToString(CultureInfo.InvariantCulture))
            End If
            builder.Append("|")
            AppendNullable(builder, member.OtherLabel)
            builder.AppendLine()
        Next

        Using sha As SHA256 = SHA256.Create()
            Dim hash As Byte() = sha.ComputeHash(Encoding.UTF8.GetBytes(builder.ToString()))
            Return BitConverter.ToString(hash).Replace("-", String.Empty).ToLowerInvariant()
        End Using
    End Function

    Private Shared Sub AppendNullable(
        builder As StringBuilder,
        value As Nullable(Of Decimal))

        If value.HasValue Then
            builder.Append(value.Value.ToString("0.######", CultureInfo.InvariantCulture))
        End If
        builder.Append("|")
    End Sub
End Class
