# Stock-Pool Data Gateway API

## Boundary

`KiwoomServer.exe` owns MySQL access for the isolated C++ stock-pool workbench.
The workbench must not load `mysql.exe`, `libmysql.dll`, or a vcpkg MySQL package.

```text
stock_pool_workbench.exe
    -> HTTP JSON
KiwoomServer.exe (server32)
    -> managed MySqlConnector
MySQL gate3
```

The existing detailed chart executable remains outside this contract.

## Configuration

Copy `.env.example` to `.env` in the server32 repository or executable-parent search path.

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=...
MYSQL_DATABASE=gate3
```

Process environment values override `.env`. `SERVER32_ENV_FILE` may point to an explicit environment file.

## Resolve symbols

```http
POST /api/stock-pool/symbols/resolve
Content-Type: application/json; charset=utf-8
```

```json
{
  "names": ["아로마티카", "져스텍", "금호타이어"]
}
```

The repository performs one parameterized batch query against `g3_symbol_master`:

```sql
SELECT code, name, COALESCE(market, '')
FROM g3_symbol_master
WHERE delisted = 0
  AND BINARY name IN (...)
ORDER BY name, code;
```

Only one exact active match is accepted. Rejection reasons are explicit:

- `blank_name`
- `duplicate_input`
- `exact_name_not_found`
- `exact_name_ambiguous`

## Persist 1516 Frozen Cohort

```http
POST /api/stock-pool/cohorts
Content-Type: application/json; charset=utf-8
```

```json
{
  "source_type": "kiwoom_1516_clipboard",
  "condition_name": "다량어",
  "trading_date": "2026-08-06",
  "capture_time": "09:00",
  "timeframe_minutes": 1,
  "members": [
    {
      "code": "000000",
      "name": "아로마티카",
      "market": "KOSDAQ",
      "return_1m_label": 6.81,
      "return_3m_label": 3.61,
      "return_7h_label": 24.31,
      "maximum_return_label": 24.31,
      "capture_volume": 53841,
      "other_label": 14.86
    }
  ]
}
```

Before writing, every code/name pair is revalidated against the active symbol master. The cohort and all accepted members are written in one transaction. Identical imports are idempotent through `raw_import_hash`.

Tables are created on first successful save:

```text
stock_pool_cohort
stock_pool_cohort_member
```

The 7-hour return and maximum return are future labels. They may be stored and used for post-analysis evaluation, but must never enter causal intraday ranking calculations.

## Failure policy

- DB connection/query failure returns HTTP 500 and no UI cohort is committed.
- Invalid request returns HTTP 400 with an explicit reason.
- A member rejected during server-side validation is not persisted.
- The C++ workbench confirms its in-memory Frozen Cohort only after the DB transaction succeeds.
