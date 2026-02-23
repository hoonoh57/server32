Imports System
Imports System.Collections.Generic
Imports System.Text

Public Module ApiHelpDocs
    Public Function BuildApiHelp(baseUrl As String, wsBase As String, defaultRealtimeFids As String) As Dictionary(Of String, Object)
        Dim endpoints As New List(Of Object) From {
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/status"}, {"purpose", "Server/Kiwoom login status"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/auth/login"}, {"purpose", "Trigger Kiwoom login"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/conditions"}, {"purpose", "Load condition list"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/conditions/search?name={name}&index={index}"}, {"purpose", "Condition search"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/conditions/start?name={name}&index={index}&screen=9001"}, {"purpose", "Condition realtime start"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/conditions/stop?name={name}&index={index}&screen=9001"}, {"purpose", "Condition realtime stop"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/dashboard"}, {"purpose", "Latest account snapshot"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/dashboard/refresh"}, {"purpose", "Refresh dashboard snapshot"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/accounts/balance?accountNo={acc}&pass={pw}"}, {"purpose", "Account holdings"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/accounts/deposit?accountNo={acc}&pass={pw}"}, {"purpose", "Deposit info"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/accounts/orders?accountNo={acc}&code={optional}"}, {"purpose", "Outstanding orders"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/market/candles/daily?code={code}&date=yyyyMMdd&stopDate=yyyyMMdd"}, {"purpose", "Daily candles"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/market/candles/minute?code={code}&tick=1&stopTime=yyyyMMddHHmmss"}, {"purpose", "Minute candles"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/market/candles/tick?code={code}&tick=1&stopTime=yyyyMMddHHmmss"}, {"purpose", "Tick candles"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/market/symbol?code={code}"}, {"purpose", "Symbol master info"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/realtime/subscribe?codes={005930;000660}&screen=1000&fids=" & defaultRealtimeFids}, {"purpose", "Realtime subscribe"}},
            New Dictionary(Of String, Object) From {{"method", "GET"}, {"path", "/api/realtime/unsubscribe?screen=1000&code=ALL"}, {"purpose", "Realtime unsubscribe"}},
            New Dictionary(Of String, Object) From {{"method", "POST"}, {"path", "/api/orders"}, {"purpose", "Place order"}}
        }

        Return New Dictionary(Of String, Object) From {
            {"name", "KIWOOM / CYBOS HELP"},
            {"base_url", baseUrl},
            {"websocket_base", wsBase},
            {"common_response", New Dictionary(Of String, Object) From {{"Success", "Boolean"}, {"Message", "String"}, {"Data", "Object|Array|Null"}}},
            {"endpoints", endpoints},
            {"ws_types", New Dictionary(Of String, Object) From {{"realtime", "tick|hoga|condition"}, {"execution", "order|balance|dashboard"}}}
        }
    End Function

    Public Function BuildHelpHtml(baseUrl As String, wsBase As String, defaultRealtimeFids As String) As String
        Dim sb As New StringBuilder()

        sb.AppendLine("<!doctype html>")
        sb.AppendLine("<html><head><meta charset=""utf-8""><title>KIWOOM / CYBOS HELP</title>")
        sb.AppendLine("<style>")
        sb.AppendLine("body{font-family:Segoe UI,Arial,sans-serif;margin:18px;line-height:1.45;background:#f4f7fb;color:#1f2937}")
        sb.AppendLine("h2,h3{margin:10px 0}")
        sb.AppendLine(".card{background:#fff;border:1px solid #d5deea;border-radius:10px;padding:14px;margin-bottom:14px}")
        sb.AppendLine(".grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}")
        sb.AppendLine("button{margin-right:6px;margin-bottom:6px;padding:8px 10px;border:1px solid #8da7d0;background:#eaf1ff;border-radius:8px;cursor:pointer}")
        sb.AppendLine("input,textarea{width:100%;box-sizing:border-box;padding:8px;border:1px solid #b8c7df;border-radius:6px;margin-top:4px;margin-bottom:8px}")
        sb.AppendLine("code{background:#eef2f7;padding:2px 4px;border-radius:4px}")
        sb.AppendLine("pre{background:#0b1730;color:#e2e8f0;padding:12px;border-radius:8px;overflow:auto}")
        sb.AppendLine("table{width:100%;border-collapse:collapse}")
        sb.AppendLine("th,td{border:1px solid #d5deea;padding:8px;vertical-align:top;text-align:left}")
        sb.AppendLine("th{background:#edf3ff}")
        sb.AppendLine(".mono{font-family:Consolas,monospace;white-space:pre-wrap}")
        sb.AppendLine(".small{font-size:12px;color:#45556f}")
        sb.AppendLine("@media (max-width:900px){.grid{grid-template-columns:1fr}}")
        sb.AppendLine("</style></head><body>")

        sb.AppendLine("<h2>KIWOOM / CYBOS CONSOLE GUIDE (WEB VERSION)</h2>")
        sb.AppendLine("<div class=""card""><b>Base URL</b>: <code>" & baseUrl & "</code><br><b>Realtime WS</b>: <code>" & wsBase & "/ws/realtime</code><br><b>Execution WS</b>: <code>" & wsBase & "/ws/execution</code><br><b>Machine-readable API Help</b>: <code>" & baseUrl & "/api/help</code></div>")

        sb.AppendLine("<div class=""card""><h3>[1] First-Time Checklist (No Prior Knowledge Needed)</h3><ol><li>Open this page.</li><li>Click GET /api/status and GET /api/auth/login.</li><li>Connect /ws/realtime then subscribe.</li><li>Check JSON in output panel.</li></ol></div>")
        sb.AppendLine("<div class=""card""><h3>[2] Connection Flow (Kiwoom)</h3><ol><li>Run Kiwoom OpenAPI+ and login.</li><li>Start server.</li><li>Call GET /api/auth/login or GET /api/system/login.</li><li>Verify GET /api/status => IsLoggedIn=True.</li></ol></div>")

        sb.AppendLine("<div class=""card""><h3>[3] REST Request Methods</h3>")
        sb.AppendLine("<div class=""grid""><div>")
        sb.AppendLine("<label>accountNo</label><input id=""accountNo"" value="""">")
        sb.AppendLine("<label>pass</label><input id=""pass"" value="""">")
        sb.AppendLine("<label>code</label><input id=""code"" value=""005930"" />")
        sb.AppendLine("<label>codes (; separated)</label><input id=""codes"" value=""005930;000660"" />")
        sb.AppendLine("<label>screen</label><input id=""screen"" value=""1000"" />")
        sb.AppendLine("<label>fids</label><input id=""fids"" value=""" & defaultRealtimeFids & """ />")
        sb.AppendLine("</div><div>")
        sb.AppendLine("<label>condition name</label><input id=""condName"" value="""">")
        sb.AppendLine("<label>condition index</label><input id=""condIndex"" value=""0"" />")
        sb.AppendLine("<label>tick</label><input id=""tick"" value=""1"" />")
        sb.AppendLine("<label>date (yyyyMMdd)</label><input id=""date"" value=""" & DateTime.Now.ToString("yyyyMMdd") & """ />")
        sb.AppendLine("<label>stopDate (yyyyMMdd)</label><input id=""stopDate"" value=""20200101"" />")
        sb.AppendLine("<label>stopTime (yyyyMMddHHmmss)</label><input id=""stopTime"" value=""" & DateTime.Now.AddDays(-1).ToString("yyyyMMdd") & "090000"" />")
        sb.AppendLine("</div></div>")

        sb.AppendLine("<table><tr><th>Method</th><th>Path</th><th>Run</th></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/status</td><td><button onclick=""runStatus()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/auth/login</td><td><button onclick=""runLogin()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/conditions</td><td><button onclick=""runConditions()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/conditions/search?name={name}&amp;index={index}</td><td><button onclick=""runCondSearch()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/conditions/start?name={name}&amp;index={index}&amp;screen=9001</td><td><button onclick=""runCondStart()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/conditions/stop?name={name}&amp;index={index}&amp;screen=9001</td><td><button onclick=""runCondStop()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/dashboard</td><td><button onclick=""runDashboard()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/dashboard/refresh</td><td><button onclick=""runDashboardRefresh()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/accounts/balance?accountNo={acc}&amp;pass={pw}</td><td><button onclick=""runBalance()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/accounts/deposit?accountNo={acc}&amp;pass={pw}</td><td><button onclick=""runDeposit()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/accounts/orders?accountNo={acc}&amp;code={optional}</td><td><button onclick=""runOrders()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/market/candles/daily?code={code}&amp;date=yyyyMMdd&amp;stopDate=yyyyMMdd</td><td><button onclick=""runDaily()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/market/candles/minute?code={code}&amp;tick=1&amp;stopTime=yyyyMMddHHmmss</td><td><button onclick=""runMinute()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/market/candles/tick?code={code}&amp;tick=1&amp;stopTime=yyyyMMddHHmmss</td><td><button onclick=""runTick()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/market/symbol?code={code}</td><td><button onclick=""runSymbol()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/realtime/subscribe?codes={005930;000660}&amp;screen=1000</td><td><button onclick=""runSub()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>GET</td><td>/api/realtime/unsubscribe?screen=1000&amp;code=ALL</td><td><button onclick=""runUnsub()"">Run</button></td></tr>")
        sb.AppendLine("<tr><td>POST</td><td>/api/orders</td><td><button onclick=""runOrder()"">Run</button></td></tr>")
        sb.AppendLine("</table></div>")

        sb.AppendLine("<div class=""card""><h3>Scenario A: 000660 캔들 900개 검증 (일/분/틱)</h3>")
        sb.AppendLine("<p>목적: 클라이언트가 캔들 API를 쓰기 전에 <b>성공 여부</b>, <b>개수</b>, <b>필드구조</b>를 즉시 확인.</p>")
        sb.AppendLine("<button onclick=""scenarioCandle900()"">Run Scenario A</button>")
        sb.AppendLine("<div class=""small"">기준: 000660, 일봉/분봉/틱 각각 rows>=900 이면 PASS.</div>")
        sb.AppendLine("</div>")

        sb.AppendLine("<div class=""card""><h3>Scenario B: 조건식 로드/실행 및 종목정보 구조 검증</h3>")
        sb.AppendLine("<p>목적: 조건식 API의 실제 활용 가능성(조건식 목록 조회, 실행, 종목정보 구조)을 즉시 확인.</p>")
        sb.AppendLine("<button onclick=""scenarioConditionFlow()"">Run Scenario B</button>")
        sb.AppendLine("<div class=""small"">기준: conditions 목록 존재 + 검색 응답의 Codes/Stocks 구조 확인.</div>")
        sb.AppendLine("</div>")

        sb.AppendLine("<div class=""card""><h3>[4] Common REST Response Format (ApiResponse)</h3><pre>{""Success"":true|false,""Message"":""OK""|""error text"",""Data"":object|array|null}</pre></div>")
        sb.AppendLine("<div class=""card""><h3>[5] POST /api/orders Body</h3><textarea id=""orderBody"" rows=""9"">{&quot;AccountNo&quot;:&quot;1234567890&quot;,&quot;StockCode&quot;:&quot;005930&quot;,&quot;OrderType&quot;:1,&quot;Quantity&quot;:1,&quot;Price&quot;:70000,&quot;QuoteType&quot;:&quot;00&quot;}</textarea><div class=""small"">AccountNo is auto-filled from accountNo input when placeholder value is used.</div></div>")

        sb.AppendLine("<div class=""card""><h3>[6] WebSocket Browser Test (Easy)</h3><pre class=""mono"">const rt = new WebSocket('" & wsBase & "/ws/realtime');\nrt.onopen = () => console.log('realtime connected');\nrt.onmessage = (e) => console.log('realtime', JSON.parse(e.data));\nfetch('" & baseUrl & "/api/realtime/subscribe?codes=005930&screen=1000').then(r=>r.json()).then(console.log);\n\nconst ex = new WebSocket('" & wsBase & "/ws/execution');\nex.onopen = () => console.log('execution connected');\nex.onmessage = (e) => console.log('execution', JSON.parse(e.data));</pre><button onclick=""openRealtime()"">Connect /ws/realtime</button><button onclick=""closeRealtime()"">Close /ws/realtime</button><button onclick=""openExecution()"">Connect /ws/execution</button><button onclick=""closeExecution()"">Close /ws/execution</button></div>")
        sb.AppendLine("<div class=""card""><h3>[7] WebSocket Result Format</h3><p>Realtime (/ws/realtime)</p><pre>{""type"":""tick|hoga|condition"",""code"":""005930"",""timestamp"":""yyyyMMddHHmmss"",""data"":{...}}</pre><p>Execution (/ws/execution)</p><pre>{""type"":""order|balance|dashboard"",""timestamp"":""yyyyMMddHHmmss"",""data"":{...}}</pre></div>")
        sb.AppendLine("<div class=""card""><h3>[8] Parsing Tips</h3><ul><li>Check REST Success first, then parse Data.</li><li>Use message type for WS routing.</li><li>Normalize numeric text values if needed.</li><li>Use timestamp as event ordering key.</li></ul></div>")
        sb.AppendLine("<div class=""card""><h3>[9] CYBOS Connection Hints</h3><ul><li>Check connection via Cybos.IsCybosConnected().</li><li>Candle entrypoint: Cybos.DownloadCandlesByPeriod(code,timeframe,fromDate,toDate).</li><li>timeframe examples: m1, m3, T1, D1.</li><li>date format: yyyyMMdd or yyyyMMddHHmm.</li></ul></div>")
        sb.AppendLine("<div class=""card""><h3>[10] Quick Start Example</h3><ol><li>GET /api/auth/login</li><li>GET /api/status</li><li>Connect realtime WS</li><li>Subscribe and confirm events</li><li>Unsubscribe to stop registration</li></ol><button onclick=""runLogin()"">1) Login</button><button onclick=""runStatus()"">2) Status</button><button onclick=""openRealtime()"">3) WS Connect</button><button onclick=""runSub()"">4) Subscribe</button><button onclick=""runUnsub()"">5) Unsubscribe</button></div>")

        sb.AppendLine("<div class=""card""><h3>Output</h3><pre id=""out"">Ready.</pre></div>")

        sb.AppendLine("<script>")
        sb.AppendLine("const BASE='" & baseUrl & "';")
        sb.AppendLine("const RT_URL='" & wsBase & "/ws/realtime';")
        sb.AppendLine("const EX_URL='" & wsBase & "/ws/execution';")
        sb.AppendLine("let rt=null, ex=null;")
        sb.AppendLine("const out=document.getElementById('out');")
        sb.AppendLine("const v=(id)=>document.getElementById(id).value;")
        sb.AppendLine("function log(x){ const t=(typeof x==='string')?x:JSON.stringify(x,null,2); out.textContent += '\n'+t; out.scrollTop=out.scrollHeight; }")
        sb.AppendLine("async function callJson(path, method='GET', body=null){ const opt={method:method, headers:{'Content-Type':'application/json'}}; if(body) opt.body=JSON.stringify(body); log('REQUEST: '+method+' '+path+(body?'\\n'+JSON.stringify(body,null,2):'')); const r=await fetch(BASE+path,opt); const j=await r.json(); log('RESPONSE: '+JSON.stringify(j,null,2)); return j; }")
        sb.AppendLine("function q(path){ return callJson(path,'GET'); }")
        sb.AppendLine("function runStatus(){ return q('/api/status'); }")
        sb.AppendLine("function runLogin(){ return q('/api/auth/login'); }")
        sb.AppendLine("function runConditions(){ return q('/api/conditions'); }")
        sb.AppendLine("function runCondSearch(){ return q('/api/conditions/search?name='+encodeURIComponent(v('condName'))+'&index='+encodeURIComponent(v('condIndex'))); }")
        sb.AppendLine("function runCondStart(){ return q('/api/conditions/start?name='+encodeURIComponent(v('condName'))+'&index='+encodeURIComponent(v('condIndex'))+'&screen=9001'); }")
        sb.AppendLine("function runCondStop(){ return q('/api/conditions/stop?name='+encodeURIComponent(v('condName'))+'&index='+encodeURIComponent(v('condIndex'))+'&screen=9001'); }")
        sb.AppendLine("function runDashboard(){ return q('/api/dashboard'); }")
        sb.AppendLine("function runDashboardRefresh(){ return q('/api/dashboard/refresh'); }")
        sb.AppendLine("function runBalance(){ return q('/api/accounts/balance?accountNo='+encodeURIComponent(v('accountNo'))+'&pass='+encodeURIComponent(v('pass'))); }")
        sb.AppendLine("function runDeposit(){ return q('/api/accounts/deposit?accountNo='+encodeURIComponent(v('accountNo'))+'&pass='+encodeURIComponent(v('pass'))); }")
        sb.AppendLine("function runOrders(){ return q('/api/accounts/orders?accountNo='+encodeURIComponent(v('accountNo'))+'&code='+encodeURIComponent(v('code'))); }")
        sb.AppendLine("function runDaily(){ return q('/api/market/candles/daily?code='+encodeURIComponent(v('code'))+'&date='+encodeURIComponent(v('date'))+'&stopDate='+encodeURIComponent(v('stopDate'))); }")
        sb.AppendLine("function runMinute(){ return q('/api/market/candles/minute?code='+encodeURIComponent(v('code'))+'&tick='+encodeURIComponent(v('tick'))+'&stopTime='+encodeURIComponent(v('stopTime'))); }")
        sb.AppendLine("function runTick(){ return q('/api/market/candles/tick?code='+encodeURIComponent(v('code'))+'&tick='+encodeURIComponent(v('tick'))+'&stopTime='+encodeURIComponent(v('stopTime'))); }")
        sb.AppendLine("function runSymbol(){ return q('/api/market/symbol?code='+encodeURIComponent(v('code'))); }")
        sb.AppendLine("function runSub(){ return q('/api/realtime/subscribe?codes='+encodeURIComponent(v('codes'))+'&screen='+encodeURIComponent(v('screen'))+'&fids='+encodeURIComponent(v('fids'))); }")
        sb.AppendLine("function runUnsub(){ return q('/api/realtime/unsubscribe?screen='+encodeURIComponent(v('screen'))+'&code=ALL'); }")
        sb.AppendLine("async function runOrder(){ let body=JSON.parse(v('orderBody')); if(!body.AccountNo || body.AccountNo==='1234567890'){ body.AccountNo=v('accountNo'); } return callJson('/api/orders','POST',body); }")
        sb.AppendLine("function summarizeRows(label, rows){")
        sb.AppendLine("  const arr = Array.isArray(rows)?rows:[];")
        sb.AppendLine("  const count = arr.length;")
        sb.AppendLine("  const pass900 = count >= 900;")
        sb.AppendLine("  const fields = count>0 ? Object.keys(arr[0]) : [];")
        sb.AppendLine("  log({scenario:label, success:true, row_count:count, pass_900:pass900, fields:fields, sample_first:arr[0]||null, sample_last:arr[count-1]||null});")
        sb.AppendLine("}")
        sb.AppendLine("async function scenarioCandle900(){")
        sb.AppendLine("  log('=== Scenario A START: 000660 candle 900 validation ===');")
        sb.AppendLine("  const daily = await q('/api/market/candles/daily?code=000660&date=20260209&stopDate=20180101');")
        sb.AppendLine("  if(daily && daily.Success){ summarizeRows('daily_000660', daily.Data); }")
        sb.AppendLine("  const minute = await q('/api/market/candles/minute?code=000660&tick=1&stopTime=20180101090000');")
        sb.AppendLine("  if(minute && minute.Success){ summarizeRows('minute_000660', minute.Data); }")
        sb.AppendLine("  const tick = await q('/api/market/candles/tick?code=000660&tick=1&stopTime=20180101090000');")
        sb.AppendLine("  if(tick && tick.Success){ summarizeRows('tick_000660', tick.Data); }")
        sb.AppendLine("  log('=== Scenario A END ===');")
        sb.AppendLine("}")
        sb.AppendLine("async function scenarioConditionFlow(){")
        sb.AppendLine("  log('=== Scenario B START: condition load/search validation ===');")
        sb.AppendLine("  const cond = await q('/api/conditions');")
        sb.AppendLine("  if(!cond || !cond.Success || !Array.isArray(cond.Data) || cond.Data.length===0){")
        sb.AppendLine("    log({scenario:'condition_load', success:false, reason:'no conditions available'});")
        sb.AppendLine("    log('=== Scenario B END ===');")
        sb.AppendLine("    return;")
        sb.AppendLine("  }")
        sb.AppendLine("  const first = cond.Data[0];")
        sb.AppendLine("  log({scenario:'condition_load', success:true, total_conditions:cond.Data.length, first_condition:first});")
        sb.AppendLine("  const name = encodeURIComponent(first.Name || '');")
        sb.AppendLine("  const index = encodeURIComponent(first.Index || 0);")
        sb.AppendLine("  const res = await q('/api/conditions/search?name='+name+'&index='+index);")
        sb.AppendLine("  if(res && res.Success){")
        sb.AppendLine("    const data = res.Data || {};")
        sb.AppendLine("    const codes = Array.isArray(data.Codes)?data.Codes:[];")
        sb.AppendLine("    const stocks = Array.isArray(data.Stocks)?data.Stocks:[];")
        sb.AppendLine("    const stockFields = stocks.length>0 ? Object.keys(stocks[0]) : [];")
        sb.AppendLine("    log({scenario:'condition_search', success:true, condition:first, codes_count:codes.length, stocks_count:stocks.length, stock_fields:stockFields, sample_stock:stocks[0]||null});")
        sb.AppendLine("  }")
        sb.AppendLine("  log('=== Scenario B END ===');")
        sb.AppendLine("}")
        sb.AppendLine("function openRealtime(){ if(rt && rt.readyState===1){ log('Realtime already connected'); return; } log('REQUEST: WS CONNECT '+RT_URL); rt=new WebSocket(RT_URL); rt.onopen=()=>log('WS OPEN: realtime connected'); rt.onmessage=(e)=>{ try{ log({stream:'realtime', event:JSON.parse(e.data)}); } catch(err){ log({stream:'realtime', raw:e.data}); } }; rt.onerror=()=>log('WS ERROR realtime'); rt.onclose=()=>log('WS CLOSE realtime'); }")
        sb.AppendLine("function closeRealtime(){ if(rt){ rt.close(); rt=null; log('REQUEST: WS CLOSE /ws/realtime'); } }")
        sb.AppendLine("function openExecution(){ if(ex && ex.readyState===1){ log('Execution already connected'); return; } log('REQUEST: WS CONNECT '+EX_URL); ex=new WebSocket(EX_URL); ex.onopen=()=>log('WS OPEN: execution connected'); ex.onmessage=(e)=>{ try{ log({stream:'execution', event:JSON.parse(e.data)}); } catch(err){ log({stream:'execution', raw:e.data}); } }; ex.onerror=()=>log('WS ERROR execution'); ex.onclose=()=>log('WS CLOSE execution'); }")
        sb.AppendLine("function closeExecution(){ if(ex){ ex.close(); ex=null; log('REQUEST: WS CLOSE /ws/execution'); } }")
        sb.AppendLine("</script></body></html>")

        Return sb.ToString()
    End Function
End Module
