import tkinter as tk
from tkinter import ttk, scrolledtext
import asyncio
import threading
import json
import datetime
import copy
from client_kit import KiwoomClientKit
from app_state import AppState

class ServerTesterUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Kiwoom Server Verification Kit (Full)")
        self.root.geometry("1100x850")
        
        self.font_mono = ("Consolas", 9)
        self.font_bold = ("Segoe UI", 10, "bold")
        
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.start_loop, args=(self.loop,), daemon=True)
        self.thread.start()
        
        self.kit = KiwoomClientKit("http://localhost:8082")
        self.state = AppState()
        self.is_realtime_running = False
        self.is_exec_running = False
        self.account_no = "" # Auto detected
        self.condition_map = {}
        self.condition_stream_active = False
        self.condition_stream_info = {"name": "", "index": None, "screen": "9101"}
        self.dashboard_data = None
        self.order_filter_top_n = 10
        self.selected_order_codes = set()
        self.condition_rt_codes = []
        self.rt_subscribed_codes = set()
        self.rt_listener_task = None
        self.condition_row_iids = {}
        self.order_row_iids = {}
        self.candle_dataset = []
        self.candle_indicators = {}
        self.candle_strategy_targets = {}
        self.chart_overlays = []
        self.strategy_markers = []
        self.candle_pipeline_state = {}
        self.strategy_running = False
        self.strategy_targets = {}
        self.strategy_mode_map = {"수동": "manual", "매수": "buy", "매도": "sell", "양방향": "both"}
        self.chart_layout = None
        self.crosshair_items = {key: None for key in ("h", "v", "x_text", "y_text", "x_bg", "y_bg")}

        self.setup_ui()
        self.state.register_condition_listener(self.on_condition_rows_updated)
        self.state.register_symbol_listener(self.on_symbol_updated)
        self.state.register_dashboard_listener(self.on_dashboard_updated)
        self.log("Server Tester Started.")
        self.log(f"Target: {self.kit.host}")

    def start_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()
        
    def run_async(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def setup_ui(self):
        main_h = ttk.PanedWindow(self.root, orient="horizontal")
        main_h.pack(fill="both", expand=True, padx=5, pady=5)
        
        left_panel = ttk.Frame(main_h, width=420)
        main_h.add(left_panel, weight=1)
        
        right_panel = ttk.Frame(main_h)
        main_h.add(right_panel, weight=4) # Chart/data side
        
        # Multi-tab tester workbench
        self.workbench = ttk.Notebook(left_panel)
        self.workbench.pack(fill="both", expand=True)
        
        self.tab_dashboard = ttk.Frame(self.workbench)
        self.tab_watchlist = ttk.Frame(self.workbench)
        self.tab_candles = ttk.Frame(self.workbench)
        self.tab_orders = ttk.Frame(self.workbench)
        self.tab_diagnostics = ttk.Frame(self.workbench)
        
        self.workbench.add(self.tab_dashboard, text="Dashboard")
        self.workbench.add(self.tab_watchlist, text="Watchlist/Realtime")
        self.workbench.add(self.tab_candles, text="Candles")
        self.workbench.add(self.tab_orders, text="Orders")
        self.workbench.add(self.tab_diagnostics, text="Diagnostics")

        self.setup_dashboard_tab(self.tab_dashboard)
        self.setup_watchlist_tab(self.tab_watchlist)
        self.setup_candle_tab(self.tab_candles)
        self.setup_order_tab(self.tab_orders)
        self.setup_diag_tab(self.tab_diagnostics)
        
        # --- Right Panel (Tabs + Log) ---
        right_split = ttk.PanedWindow(right_panel, orient="vertical")
        right_split.pack(fill="both", expand=True)

        # 1. Notebook (Grid & Chart)
        self.notebook = ttk.Notebook(right_split)
        right_split.add(self.notebook, weight=3)

        # Tab 1: Grid
        self.tab_grid = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_grid, text="Data Grid")
        
        cols = ("time", "open", "high", "low", "close", "volume")
        self.tree = ttk.Treeview(self.tab_grid, columns=cols, show="headings")
        
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=80, anchor="e")
        self.tree.heading("time", text="TIME")
        self.tree.column("time", width=140, anchor="c")
        
        vsb = ttk.Scrollbar(self.tab_grid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Tab 2: Chart
        self.tab_chart = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chart, text="Chart")
        
        self.canvas = tk.Canvas(self.tab_chart, bg="white")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw_chart_if_exists())
        self.canvas.bind("<Motion>", self.on_chart_mouse_move)
        self.canvas.bind("<Leave>", lambda e: self.clear_crosshair())
        self.current_chart_data = []

        # 2. Log Area
        self.txt_log = scrolledtext.ScrolledText(right_split, font=self.font_mono, state="disabled", height=10)
        right_split.add(self.txt_log, weight=1)
        
        self.txt_log.tag_config("INFO", foreground="black")
        self.txt_log.tag_config("API", foreground="blue")
        self.txt_log.tag_config("WS", foreground="green")
        self.txt_log.tag_config("ERR", foreground="red")
        self.txt_log.tag_config("ORDER", foreground="purple")

    def setup_dashboard_tab(self, parent):
        grp_api = ttk.LabelFrame(parent, text="Server & Account", padding=5)
        grp_api.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(grp_api, text="[GET] 로그인 상태 & 계좌감지", command=lambda: self.run_async(self.check_login())).pack(fill="x", pady=2)
        ttk.Button(grp_api, text="[GET] 계좌 잔고 (Balance)", command=lambda: self.run_async(self.get_balance())).pack(fill="x", pady=2)
        ttk.Button(grp_api, text="대시보드 새로고침", command=lambda: self.run_async(self.load_dashboard_snapshot(force=True))).pack(fill="x", pady=2)
        
        grp_status = ttk.LabelFrame(parent, text="Status", padding=5)
        grp_status.pack(fill="x", padx=5, pady=5)
        self.lbl_account = ttk.Label(grp_status, text="Account: -")
        self.lbl_account.pack(anchor="w")
        self.lbl_rt = ttk.Label(grp_status, text="Realtime WS: Stopped")
        self.lbl_rt.pack(anchor="w")
        self.lbl_exec = ttk.Label(grp_status, text="Execution WS: Stopped")
        self.lbl_exec.pack(anchor="w")
        ttk.Button(grp_status, text="체결/잔고 실시간 연결", command=self.toggle_execution).pack(fill="x", pady=3)

        grp_summary = ttk.LabelFrame(parent, text="Account Summary", padding=5)
        grp_summary.pack(fill="x", padx=5, pady=5)
        self.lbl_total_purchase = ttk.Label(grp_summary, text="총매입금액: -")
        self.lbl_total_purchase.pack(anchor="w")
        self.lbl_total_eval = ttk.Label(grp_summary, text="총평가금액: -")
        self.lbl_total_eval.pack(anchor="w")
        self.lbl_total_pnl = ttk.Label(grp_summary, text="총손익: - (0.00%)")
        self.lbl_total_pnl.pack(anchor="w")
        self.lbl_realized = ttk.Label(grp_summary, text="실현손익: -")
        self.lbl_realized.pack(anchor="w")
        self.lbl_deposit = ttk.Label(grp_summary, text="주문가능/출금가능: - / -")
        self.lbl_deposit.pack(anchor="w")

        grp_holdings = ttk.LabelFrame(parent, text="보유 종목", padding=5)
        grp_holdings.pack(fill="both", expand=True, padx=5, pady=5)
        hold_cols = ["code", "name", "qty", "eval", "pnl", "rate"]
        self.tree_holdings = ttk.Treeview(grp_holdings, columns=hold_cols, show="headings", height=6)
        headings = {
            "code": "종목코드",
            "name": "종목명",
            "qty": "보유수량",
            "eval": "평가금액",
            "pnl": "평가손익",
            "rate": "손익률"
        }
        widths = {"code":80,"name":120,"qty":80,"eval":100,"pnl":100,"rate":70}
        for col in hold_cols:
            self.tree_holdings.heading(col, text=headings[col])
            self.tree_holdings.column(col, width=widths[col], anchor="e" if col not in ("code","name") else ("c" if col=="code" else "w"))
        hold_scroll = ttk.Scrollbar(grp_holdings, orient="vertical", command=self.tree_holdings.yview)
        self.tree_holdings.configure(yscrollcommand=hold_scroll.set)
        self.tree_holdings.pack(side="left", fill="both", expand=True)
        hold_scroll.pack(side="right", fill="y")

        grp_out = ttk.LabelFrame(parent, text="미체결", padding=5)
        grp_out.pack(fill="both", expand=True, padx=5, pady=5)
        out_cols = ["ordno","code","type","price","qty","remain","status"]
        self.tree_outstanding = ttk.Treeview(grp_out, columns=out_cols, show="headings", height=5)
        out_headings = {
            "ordno":"주문번호",
            "code":"종목코드",
            "type":"구분",
            "price":"주문가",
            "qty":"주문수량",
            "remain":"미체결",
            "status":"상태"
        }
        out_widths = {"ordno":90,"code":80,"type":70,"price":80,"qty":70,"remain":70,"status":80}
        for col in out_cols:
            self.tree_outstanding.heading(col, text=out_headings[col])
            self.tree_outstanding.column(col, width=out_widths[col], anchor="e" if col in ("price","qty","remain") else "c")
        out_scroll = ttk.Scrollbar(grp_out, orient="vertical", command=self.tree_outstanding.yview)
        self.tree_outstanding.configure(yscrollcommand=out_scroll.set)
        self.tree_outstanding.pack(side="left", fill="both", expand=True)
        out_scroll.pack(side="right", fill="y")

    def setup_watchlist_tab(self, parent):
        grp_cond = ttk.LabelFrame(parent, text="조건검색", padding=5)
        grp_cond.pack(fill="both", expand=True, padx=5, pady=5)

        f_cond = ttk.Frame(grp_cond)
        f_cond.pack(fill="x", pady=2)
        ttk.Button(f_cond, text="목록갱신", width=8, command=lambda: self.run_async(self.get_conditions())).pack(side="left", padx=1)
        self.cb_cond = ttk.Combobox(f_cond, state="readonly", width=15)
        self.cb_cond.pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(f_cond, text="조건실행", width=8, command=lambda: self.run_async(self.run_condition())).pack(side="left", padx=1)

        cond_frame = ttk.Frame(grp_cond)
        cond_frame.pack(fill="both", expand=True, pady=4)
        cond_cols = [
            ("code", "종목코드", 70, "c"),
            ("name", "종목명", 120, "w"),
            ("price", "현재가", 80, "e"),
            ("diff", "전일대비", 80, "e"),
            ("rate", "등락율", 70, "e"),
            ("power", "체결강도", 80, "e"),
            ("volratio", "전일비", 70, "e"),
        ]
        self.cond_tree = ttk.Treeview(cond_frame, columns=[c[0] for c in cond_cols], show="headings", height=10)
        for col_id, heading, width, anchor in cond_cols:
            self.cond_tree.heading(col_id, text=heading)
            self.cond_tree.column(col_id, width=width, anchor=anchor)
        cond_vsb = ttk.Scrollbar(cond_frame, orient="vertical", command=self.cond_tree.yview)
        self.cond_tree.configure(yscrollcommand=cond_vsb.set)
        self.cond_tree.pack(side="left", fill="both", expand=True)
        cond_vsb.pack(side="right", fill="y")
        self.cond_tree.bind("<<TreeviewSelect>>", self.on_watchlist_select)

        grp_realtime = ttk.LabelFrame(parent, text="Realtime Controls", padding=5)
        grp_realtime.pack(fill="x", padx=5, pady=5)
        self.btn_rt = ttk.Button(grp_realtime, text="▶ 실시간 구독 (현재 Code)", command=self.toggle_realtime)
        self.btn_rt.pack(fill="x", pady=2)
        self.btn_cond_stream = ttk.Button(grp_realtime, text="▶ 조건 실시간 시작", command=lambda: self.run_async(self.toggle_condition_stream()))
        self.btn_cond_stream.pack(fill="x", pady=2)
        self.lbl_cond_stream = ttk.Label(grp_realtime, text="조건 실시간: OFF")
        self.lbl_cond_stream.pack(anchor="w")

    def setup_candle_tab(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        grp_ext = ttk.LabelFrame(container, text="Step 1. Candle Download (Server)", padding=5)
        grp_ext.pack(fill="x", padx=5, pady=5)
        
        f_row1 = ttk.Frame(grp_ext)
        f_row1.pack(fill="x", pady=2)
        ttk.Label(f_row1, text="Code:").pack(side="left")
        self.ent_code = ttk.Entry(f_row1, width=8)
        self.ent_code.insert(0, "005930")
        self.ent_code.pack(side="left", padx=5)
        ttk.Label(f_row1, text="TF:").pack(side="left")
        self.cb_tf = ttk.Combobox(f_row1, width=7, state="readonly")
        tf_values = [
            'm1','m3','m5','m10','m15','m30','m60','m240',
            'T1','T3','T5','T10','T15','T30','T60','T120',
            'D1','W1','M1'
        ]
        self.cb_tf['values'] = tf_values
        self.cb_tf.current(5)
        self.cb_tf.pack(side="left", padx=2)
        
        f_row2 = ttk.Frame(grp_ext)
        f_row2.pack(fill="x", pady=2)
        ttk.Label(f_row2, text="Stop:").pack(side="left")
        self.ent_date = ttk.Entry(f_row2, width=18)
        init_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d090000")
        self.ent_date.insert(0, init_date)
        self.ent_date.pack(side="left", padx=2, fill="x", expand=True)
        
        f_row3 = ttk.Frame(grp_ext)
        f_row3.pack(fill="x", pady=2)
        ttk.Button(f_row3, text="[GET] Download Candles", command=lambda: self.run_async(self.download_candles())).pack(side="left", fill="x", expand=True, padx=1)
        ttk.Button(f_row3, text="[GET] Symbol Info", command=lambda: self.run_async(self.get_symbol())).pack(side="left", padx=1)
        
        grp_indicator = ttk.LabelFrame(container, text="Step 2. Indicator Builder", padding=5)
        grp_indicator.pack(fill="x", padx=5, pady=5)
        ind_row = ttk.Frame(grp_indicator)
        ind_row.pack(fill="x", pady=2)
        ttk.Label(ind_row, text="Indicator:").pack(side="left")
        self.indicator_type_var = tk.StringVar(value="SMA")
        self.cmb_indicator = ttk.Combobox(ind_row, textvariable=self.indicator_type_var, state="readonly", width=10, values=("SMA", "EMA", "RSI"))
        self.cmb_indicator.pack(side="left", padx=2)
        self.cmb_indicator.bind("<<ComboboxSelected>>", lambda e: self.on_indicator_type_change())
        self.lbl_indicator_param1 = ttk.Label(ind_row, text="Param1:")
        self.lbl_indicator_param1.pack(side="left", padx=(10,2))
        self.ent_indicator_param1 = ttk.Entry(ind_row, width=6)
        self.ent_indicator_param1.pack(side="left")
        self.ent_indicator_param1.insert(0, "5")
        self.lbl_indicator_param2 = ttk.Label(ind_row, text="Param2:")
        self.lbl_indicator_param2.pack(side="left", padx=(10,2))
        self.ent_indicator_param2 = ttk.Entry(ind_row, width=6)
        self.ent_indicator_param2.pack(side="left")
        self.ent_indicator_param2.insert(0, "20")
        ttk.Button(grp_indicator, text="Compute Indicator", command=self.run_indicator_builder).pack(side="left", padx=2, pady=2)
        self.lbl_indicator_status = ttk.Label(grp_indicator, text="지표 대기중", foreground="gray")
        self.lbl_indicator_status.pack(anchor="w")

        grp_strategy = ttk.LabelFrame(container, text="Step 3. Strategy Simulation", padding=5)
        grp_strategy.pack(fill="x", padx=5, pady=5)
        strat_row = ttk.Frame(grp_strategy)
        strat_row.pack(fill="x", pady=2)
        ttk.Label(strat_row, text="Strategy:").pack(side="left")
        self.candle_strategy_type_var = tk.StringVar(value="SMA Cross")
        self.cmb_candle_strategy = ttk.Combobox(strat_row, textvariable=self.candle_strategy_type_var, state="readonly", width=12, values=("SMA Cross", "RSI Band"))
        self.cmb_candle_strategy.pack(side="left", padx=2)
        self.cmb_candle_strategy.bind("<<ComboboxSelected>>", lambda e: self.on_candle_strategy_change())
        self.lbl_candle_param1 = ttk.Label(strat_row, text="Param1:")
        self.lbl_candle_param1.pack(side="left", padx=(10,2))
        self.ent_candle_param1 = ttk.Entry(strat_row, width=6)
        self.ent_candle_param1.pack(side="left")
        self.ent_candle_param1.insert(0, "5")
        self.lbl_candle_param2 = ttk.Label(strat_row, text="Param2:")
        self.lbl_candle_param2.pack(side="left", padx=(10,2))
        self.ent_candle_param2 = ttk.Entry(strat_row, width=6)
        self.ent_candle_param2.pack(side="left")
        self.ent_candle_param2.insert(0, "20")
        ttk.Button(grp_strategy, text="Run Strategy", command=self.run_candle_strategy).pack(side="left", padx=2, pady=2)
        self.lbl_candle_strategy_status = ttk.Label(grp_strategy, text="전략 대기중", foreground="gray")
        self.lbl_candle_strategy_status.pack(anchor="w")

        grp_chart_ctrl = ttk.LabelFrame(container, text="Step 4. Chart Controls", padding=5)
        grp_chart_ctrl.pack(fill="x", padx=5, pady=5)
        self.show_overlays_var = tk.BooleanVar(value=True)
        self.show_markers_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp_chart_ctrl, text="지표선 표시", variable=self.show_overlays_var, command=self.draw_candle_chart).pack(side="left", padx=4)
        ttk.Checkbutton(grp_chart_ctrl, text="전략 마커 표시", variable=self.show_markers_var, command=self.draw_candle_chart).pack(side="left", padx=4)
        ttk.Button(grp_chart_ctrl, text="차트 새로고침", command=self.draw_candle_chart).pack(side="left", padx=4)
        ttk.Button(grp_chart_ctrl, text="오버레이 초기화", command=self.clear_chart_overlays).pack(side="left", padx=4)

        grp_pipeline = ttk.LabelFrame(container, text="Pipeline Status", padding=5)
        grp_pipeline.pack(fill="both", expand=True, padx=5, pady=5)
        cols = ("step", "status", "detail")
        self.tree_pipeline = ttk.Treeview(grp_pipeline, columns=cols, show="headings", height=3)
        self.tree_pipeline.heading("step", text="단계")
        self.tree_pipeline.heading("status", text="상태")
        self.tree_pipeline.heading("detail", text="메모")
        self.tree_pipeline.column("step", width=160, anchor="w")
        self.tree_pipeline.column("status", width=90, anchor="center")
        self.tree_pipeline.column("detail", anchor="w")
        self.tree_pipeline.pack(fill="both", expand=True)

        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=5)
        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x", padx=5, pady=5)
        ttk.Button(btn_row, text="[GET] 예수금 (Deposit)", command=lambda: self.run_async(self.get_deposit())).pack(side="left", padx=2)
        ttk.Button(btn_row, text="[GET] 미체결 (Outstanding)", command=lambda: self.run_async(self.get_outstanding())).pack(side="left", padx=2)

        self._init_candle_pipeline()
        self.on_indicator_type_change()
        self.on_candle_strategy_change()

    def _init_candle_pipeline(self):
        self.candle_pipeline_rows = [
            ("download", "1. 데이터 다운로드"),
            ("indicator", "2. 지표 계산"),
            ("strategy", "3. 전략 시뮬레이션")
        ]
        self.candle_pipeline_state = {
            key: {"status": "대기", "detail": "-"} for key, _ in self.candle_pipeline_rows
        }
        self._render_candle_pipeline()

    def _render_candle_pipeline(self):
        if not hasattr(self, "tree_pipeline"):
            return
        self.tree_pipeline.delete(*self.tree_pipeline.get_children())
        for key, label in self.candle_pipeline_rows:
            info = self.candle_pipeline_state.get(key, {"status": "-", "detail": ""})
            self.tree_pipeline.insert("", "end", values=(label, info.get("status", "-"), info.get("detail", "")))

    def _set_pipeline_status(self, key, status, detail=""):
        if not hasattr(self, "candle_pipeline_state") or key not in self.candle_pipeline_state:
            return
        self.candle_pipeline_state[key]["status"] = status
        self.candle_pipeline_state[key]["detail"] = detail
        self._render_candle_pipeline()

    def clear_chart_overlays(self):
        self.chart_overlays = []
        self.strategy_markers = []
        self.lbl_indicator_status.config(text="지표 초기화", foreground="gray")
        self.lbl_candle_strategy_status.config(text="전략 초기화", foreground="gray")
        self._set_pipeline_status("indicator", "대기", "지표 선택")
        self._set_pipeline_status("strategy", "대기", "전략 선택")
        self.draw_candle_chart()

    def on_indicator_type_change(self):
        indicator = getattr(self, "indicator_type_var", None)
        name = indicator.get() if indicator else "SMA"
        if name == "RSI":
            self.lbl_indicator_param1.config(text="기간:")
            self.lbl_indicator_param2.config(text="옵션:")
            if not self.ent_indicator_param1.get():
                self.ent_indicator_param1.insert(0, "14")
        else:
            self.lbl_indicator_param1.config(text="Param1:")
            self.lbl_indicator_param2.config(text="Param2:")

    def on_candle_strategy_change(self):
        strategy = getattr(self, "candle_strategy_type_var", None)
        name = strategy.get() if strategy else "SMA Cross"
        if name == "SMA Cross":
            self.lbl_candle_param1.config(text="Fast:")
            self.lbl_candle_param2.config(text="Slow:")
            if not self.ent_candle_param2.get():
                self.ent_candle_param2.insert(0, "20")
        else:
            self.lbl_candle_param1.config(text="Period/Low:")
            self.lbl_candle_param2.config(text="High:")
            if not self.ent_candle_param1.get():
                self.ent_candle_param1.insert(0, "14")
            if not self.ent_candle_param2.get():
                self.ent_candle_param2.insert(0, "70")

    def setup_order_tab(self, parent):
        grp_filter = ttk.LabelFrame(parent, text="감시 종목", padding=5)
        grp_filter.pack(fill="both", expand=True, padx=5, pady=5)

        top_bar = ttk.Frame(grp_filter)
        top_bar.pack(fill="x", pady=2)
        ttk.Label(top_bar, text="Top N:").pack(side="left")
        self.order_filter_entry = ttk.Entry(top_bar, width=5)
        self.order_filter_entry.insert(0, str(self.order_filter_top_n))
        self.order_filter_entry.pack(side="left", padx=2)
        ttk.Button(top_bar, text="필터 적용", command=self.apply_order_filter).pack(side="left", padx=2)
        ttk.Button(top_bar, text="전체 선택", command=lambda: self.update_order_selection(all_check=True)).pack(side="left", padx=2)
        ttk.Button(top_bar, text="선택 해제", command=lambda: self.update_order_selection(all_check=False)).pack(side="left", padx=2)
        ttk.Button(top_bar, text="자동매매 (준비중)", state="disabled").pack(side="right")

        columns = ["sel", "code", "name", "price", "qty", "pnl", "rate"]
        self.order_tree = ttk.Treeview(grp_filter, columns=columns, show="headings", height=10)
        headings = {
            "sel": "선택",
            "code": "종목코드",
            "name": "종목명",
            "price": "현재가",
            "qty": "보유수량",
            "pnl": "평가손익",
            "rate": "손익률(%)"
        }
        widths = {"sel":50,"code":90,"name":140,"price":90,"qty":80,"pnl":90,"rate":90}
        anchors = {"sel":"c","code":"c","name":"w","price":"e","qty":"e","pnl":"e","rate":"e"}
        for col in columns:
            self.order_tree.heading(col, text=headings[col])
            self.order_tree.column(col, width=widths[col], anchor=anchors[col])
        order_scroll = ttk.Scrollbar(grp_filter, orient="vertical", command=self.order_tree.yview)
        self.order_tree.configure(yscrollcommand=order_scroll.set)
        self.order_tree.pack(side="left", fill="both", expand=True)
        order_scroll.pack(side="right", fill="y")
        self.order_tree.bind("<Button-1>", self.on_order_tree_click)

        grp_trade = ttk.LabelFrame(parent, text="주문 설정", padding=5)
        grp_trade.pack(fill="x", padx=5, pady=5)

        symbol_frame = ttk.Frame(grp_trade)
        symbol_frame.pack(fill="x", pady=2)
        ttk.Label(symbol_frame, text="종목코드:").pack(side="left")
        self.order_code_var = tk.StringVar()
        self.ent_order_code = ttk.Entry(symbol_frame, textvariable=self.order_code_var, width=12)
        self.ent_order_code.pack(side="left", padx=(2, 8))
        self.ent_order_code.bind("<FocusOut>", lambda e: self.on_manual_order_code_change())
        initial_code = self.ent_code.get().strip() if hasattr(self, "ent_code") else ""
        if initial_code:
            self.order_code_var.set(initial_code)
        ttk.Label(symbol_frame, text="종목명:").pack(side="left")
        self.order_name_var = tk.StringVar(value="-")
        self.lbl_order_name = ttk.Label(symbol_frame, textvariable=self.order_name_var, width=20)
        self.lbl_order_name.pack(side="left", padx=2)
        if initial_code:
            name_guess = self._resolve_symbol_name(initial_code)
            if name_guess:
                self.order_name_var.set(name_guess)

        type_frame = ttk.Frame(grp_trade)
        type_frame.pack(fill="x", pady=2)
        self.order_type_var = tk.StringVar(value="limit")
        self.order_type_var.trace_add("write", lambda *args: self.update_order_type_ui())
        ttk.Radiobutton(type_frame, text="지정가", variable=self.order_type_var, value="limit").pack(side="left", padx=4)
        ttk.Radiobutton(type_frame, text="시장가", variable=self.order_type_var, value="market").pack(side="left", padx=4)
        ttk.Radiobutton(type_frame, text="스탑지정가", variable=self.order_type_var, value="stop").pack(side="left", padx=4)

        side_frame = ttk.Frame(grp_trade)
        side_frame.pack(fill="x", pady=2)
        ttk.Label(side_frame, text="주문 방향:").pack(side="left")
        self.trade_side_var = tk.StringVar(value="buy")
        ttk.Radiobutton(side_frame, text="매수", variable=self.trade_side_var, value="buy", command=self.on_trade_side_changed).pack(side="left", padx=4)
        ttk.Radiobutton(side_frame, text="매도", variable=self.trade_side_var, value="sell", command=self.on_trade_side_changed).pack(side="left", padx=4)

        price_frame = ttk.Frame(grp_trade)
        price_frame.pack(fill="x", pady=2)
        ttk.Label(price_frame, text="가격선택:").pack(side="left")
        self.cmb_price = ttk.Combobox(price_frame, width=25, state="readonly")
        self.cmb_price.pack(side="left", padx=2)
        ttk.Label(price_frame, text="직접입력:").pack(side="left")
        self.ent_limit_price = ttk.Entry(price_frame, width=12)
        self.ent_limit_price.pack(side="left", padx=2)
        ttk.Label(price_frame, text="수량:").pack(side="left")
        self.ent_qty = ttk.Entry(price_frame, width=8)
        self.ent_qty.insert(0, "1")
        self.ent_qty.pack(side="left", padx=2)

        stop_frame = ttk.Frame(grp_trade)
        stop_frame.pack(fill="x", pady=2)
        ttk.Label(stop_frame, text="스탑가격:").pack(side="left")
        self.ent_stop = ttk.Entry(stop_frame, width=12)
        self.ent_stop.pack(side="left", padx=2)

        action_frame = ttk.Frame(grp_trade)
        action_frame.pack(fill="x", pady=2)
        ttk.Button(action_frame, text="선택 매수", command=lambda: self.trigger_submit_orders(1)).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(action_frame, text="선택 매도", command=lambda: self.trigger_submit_orders(2)).pack(side="left", fill="x", expand=True, padx=2)

        self.update_order_type_ui()

        grp_strategy = ttk.LabelFrame(parent, text="전략 매매", padding=5)
        grp_strategy.pack(fill="x", padx=5, pady=5)
        ttk.Label(grp_strategy, text="전략 유형:").pack(side="left", padx=(0, 4))
        self.strategy_mode_var = tk.StringVar(value="수동")
        self.cmb_strategy = ttk.Combobox(
            grp_strategy,
            textvariable=self.strategy_mode_var,
            width=18,
            state="readonly",
            values=("수동", "매수", "매도", "양방향")
        )
        self.cmb_strategy.pack(side="left", padx=2)
        self.cmb_strategy.bind("<<ComboboxSelected>>", lambda e: self.update_strategy_ui())
        self.btn_strategy = ttk.Button(grp_strategy, text="전략 실행", command=self.toggle_strategy_execution)
        self.btn_strategy.pack(side="left", padx=6)
        self.lbl_strategy_status = ttk.Label(grp_strategy, text="대기중", foreground="gray")
        self.lbl_strategy_status.pack(side="left", padx=4)
        self.update_strategy_ui()

        grp_ex = ttk.LabelFrame(parent, text="Execution Hub (WS)", padding=5)
        grp_ex.pack(fill="x", padx=5, pady=5)
        self.btn_ex = ttk.Button(grp_ex, text="▶ 체결/잔고 수신", command=self.toggle_execution)
        self.btn_ex.pack(fill="x", pady=2)

    def setup_diag_tab(self, parent):
        grp_diag = ttk.LabelFrame(parent, text="Diagnostics", padding=5)
        grp_diag.pack(fill="both", expand=True, padx=5, pady=5)
        ttk.Label(grp_diag, text="실시간 로그 및 상태는 오른쪽 Log 창에서 확인하세요. 향후 별도 뷰 추가 예정.").pack(fill="x")

    # --- Methods ---

    def setup_grid_columns(self, cols):
        """Reconfigure treeview columns. cols = list of (id, heading, width, anchor)"""
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = [c[0] for c in cols]
        for col_id, heading, width, anchor in cols:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, anchor=anchor)

    async def ensure_account(self):
        if self.account_no: return True
        await self.check_login()
        if self.account_no: return True
        self.log("계좌 정보를 찾을 수 없습니다. 로그인 상태를 확인하세요.", "ERR")
        return False

    async def check_login(self):
        self.log(">>> Checking Server Status...", "INFO")
        res = await self.kit.get_server_status()
        
        if res.get('Success', False):
            data = res.get('Data', {})
            is_logged = data.get('IsLoggedIn', False)
            acc = data.get('AccountNo', "")
            
            if is_logged:
                self.log(f"✅ Logged In. Account: {acc}", "INFO")
                self.account_no = acc
                self.root.title(f"Kiwoom Verifier - Connected [{acc}]")
                self.lbl_account.config(text=f"Account: {acc}") if hasattr(self, "lbl_account") else None
                self.run_async(self.load_dashboard_snapshot())
            else:
                self.log("⚠️ Server Connected but NOT Logged In.", "ERR")
                self.log(">>> Requesting Login Window...", "INFO")
                await self.kit.request_login()
        else:
             self.log(f"❌ Server Connection Failed: {res.get('Message')}", "ERR")

    async def load_dashboard_snapshot(self, force=False):
        try:
            res = await (self.kit.refresh_dashboard_snapshot() if force else self.kit.get_dashboard_snapshot())
        except Exception as e:
            self.log(f"대시보드 조회 실패: {e}", "ERR")
            return

        if not res.get('Success') or not res.get('Data'):
            if not force:
                self.log("대시보드 스냅샷이 아직 준비되지 않아 새로고침을 시도합니다.", "INFO")
                await self.load_dashboard_snapshot(force=True)
            else:
                self.log(f"대시보드 조회 실패: {res.get('Message')}", "ERR")
            return

        data = res.get('Data') or {}
        changed = self.state.set_dashboard_snapshot(data)
        if changed:
            self.log("대시보드 정보를 갱신했습니다.", "INFO")

    def on_dashboard_updated(self, snapshot):
        self.render_dashboard(snapshot)

    def render_dashboard(self, data):
        if not data:
            return
        self.dashboard_data = copy.deepcopy(data)
        def fmt(num):
            try:
                val = num
                if isinstance(val, str):
                    val = val.replace(",", "")
                return f"{float(val):,.0f}"
            except Exception:
                return str(num)

        total_purchase = data.get('TotalPurchase', 0)
        total_eval = data.get('TotalEvaluation', 0)
        total_pnl = data.get('TotalPnL', 0)
        total_rate = data.get('TotalPnLRate', 0)
        realized = data.get('RealizedPnL', 0)
        dep_avail = data.get('DepositAvailable', 0)
        dep_with = data.get('DepositWithdrawable', 0)

        if hasattr(self, "lbl_total_purchase"):
            self.lbl_total_purchase.config(text=f"총매입금액: {fmt(total_purchase)}")
            self.lbl_total_eval.config(text=f"총평가금액: {fmt(total_eval)}")
            self.lbl_total_pnl.config(text=f"총손익: {fmt(total_pnl)} ({total_rate:.2f}%)")
            self.lbl_realized.config(text=f"실현손익: {fmt(realized)}")
            self.lbl_deposit.config(text=f"주문가능/출금가능: {fmt(dep_avail)} / {fmt(dep_with)}")

        holdings = data.get('Holdings') or []
        if hasattr(self, "tree_holdings"):
            self._populate_tree(self.tree_holdings, [
                (
                    row.get('종목코드', ''),
                    row.get('종목명', ''),
                    row.get('보유수량', ''),
                    row.get('평가금액', row.get('현재가', '')),
                    row.get('평가손익', ''),
                    row.get('손익률', '')
                ) for row in holdings
            ], key_index=0)

        outstanding = data.get('Outstanding') or []
        if hasattr(self, "tree_outstanding"):
            self._populate_tree(self.tree_outstanding, [
                (
                    row.get('주문번호', ''),
                    row.get('종목코드', ''),
                    row.get('주문구분', ''),
                    row.get('주문가격', ''),
                    row.get('주문수량', ''),
                    row.get('미체결수량', ''),
                    row.get('주문상태', '')
                ) for row in outstanding
            ], key_index=0)
        self.render_order_grid()

    def _populate_tree(self, tree, rows, key_index: int = 0):
        if not tree:
            return
        rows = rows or []
        if not rows:
            tree.delete(*tree.get_children())
            return

        keyed_rows = [
            tuple(values)
            for values in rows
            if isinstance(values, (list, tuple)) and len(values) > key_index and values[key_index]
        ]
        if len(keyed_rows) != len(rows):
            tree.delete(*tree.get_children())
            for values in rows:
                tree.insert("", "end", values=values)
            return

        existing = {}
        for iid in tree.get_children():
            vals = tree.item(iid, "values")
            if not vals or len(vals) <= key_index:
                continue
            key = vals[key_index]
            if key:
                existing[key] = iid

        seen = set()
        for values in keyed_rows:
            key = values[key_index]
            if key in existing:
                tree.item(existing[key], values=values)
            else:
                iid = key if key and key not in existing else ""
                new_iid = tree.insert("", "end", iid=iid if iid and iid not in tree.get_children() else "", values=values)
                if key:
                    existing[key] = new_iid
            seen.add(key)

        for key, iid in list(existing.items()):
            if key not in seen:
                tree.delete(iid)

    def apply_order_filter(self):
        try:
            val = int(self.order_filter_entry.get())
            if val <= 0:
                raise ValueError
            self.order_filter_top_n = val
        except Exception:
            self.log("Top N 값이 올바르지 않습니다.", "ERR")
            return
        self.render_order_grid()

    def render_order_grid(self):
        if not hasattr(self, "order_tree"):
            return
        holdings = (self.dashboard_data or {}).get("Holdings") or []
        holdings_map = {h.get("종목코드"): h for h in holdings if h.get("종목코드")}
        source = self.state.condition_hits if self.state.condition_hits else holdings
        rows = []
        seen = set()
        for row in source:
            code = row.get("종목코드")
            if not code or code in seen:
                continue
            seen.add(code)
            sym = self.state.symbols.get(code) if hasattr(self.state, "symbols") else None
            hold = holdings_map.get(code, {})
            current = row.get("현재가") or hold.get("현재가")
            if not current and sym and sym.last_price:
                current = f"{sym.last_price:,.0f}"
            qty = hold.get("보유수량") or row.get("보유수량", "")
            pnl = hold.get("평가손익") or row.get("평가손익", "")
            rate = hold.get("손익률") or row.get("손익률", "")
            rows.append({
                "code": code,
                "name": row.get("종목명") or hold.get("종목명", ""),
                "price": self._format_abs_number(current),
                "qty": qty,
                "pnl": pnl,
                "rate": rate
            })

        self.order_tree.delete(*self.order_tree.get_children())
        self.order_row_iids = {}
        if not rows:
            return

        rows.sort(key=lambda r: self._to_float(r.get("price")), reverse=True)
        limit = self.order_filter_top_n if self.order_filter_top_n > 0 else len(rows)
        view = rows[:limit]

        for row in view:
            code = row.get("code", "")
            mark = "■" if code in self.selected_order_codes else "□"
            iid = self.order_tree.insert(
                "",
                "end",
                values=(
                    mark,
                    code,
                    row.get("name", ""),
                    row.get("price", ""),
                    row.get("qty", ""),
                    row.get("pnl", ""),
                    row.get("rate", "")
                )
            )
            if code:
                self.order_row_iids[code] = iid

        if view and not self.order_code_var.get():
            first = view[0]
            self.set_order_symbol_context(first.get("code"), name=first.get("name"), price=first.get("price"))

    def update_order_selection(self, all_check=True):
        holdings = (self.dashboard_data or {}).get("Holdings") or []
        codes = [row.get("종목코드", "") for row in holdings]
        if all_check:
            self.selected_order_codes = set(filter(None, codes))
        else:
            self.selected_order_codes.clear()
        self.render_order_grid()

    def on_order_tree_click(self, event):
        if not hasattr(self, "order_tree"):
            return
        row_id = self.order_tree.identify_row(event.y)
        column = self.order_tree.identify_column(event.x)
        if not row_id:
            return
        code = self.order_tree.set(row_id, "code")
        name = self.order_tree.set(row_id, "name")
        price = self.order_tree.set(row_id, "price")
        if column == "#1" and code:
            if code in self.selected_order_codes:
                self.selected_order_codes.remove(code)
            else:
                self.selected_order_codes.add(code)
            self.render_order_grid()
            self.set_order_symbol_context(code, name=name, price=price)
            return "break"
        else:
            if code:
                self.set_order_symbol_context(code, name=name, price=price)

    def update_price_combo_from_code(self, code, base_price=None):
        if not hasattr(self, "cmb_price"):
            return
        if not code:
            return
        if base_price is None:
            base_price = self._resolve_symbol_price(code)
        if base_price is None or base_price <= 0:
            return
        tick = self._calc_tick_unit(base_price)
        side_value = getattr(self, "trade_side_var", None)
        current_side = side_value.get() if side_value else "buy"
        offsets = self._build_offsets_for_side(current_side)
        options = []
        for offset in offsets:
            value = max(base_price + offset * tick, tick)
            label = f"{self._format_abs_number(value)} ({offset:+d}호가)"
            options.append(label)
        self.cmb_price["values"] = options
        if options:
            self.cmb_price.set(options[0])
        self._set_price_entries(base_price)

    def get_selected_order_codes(self):
        if self.selected_order_codes:
            return list(self.selected_order_codes)
        fallback = ""
        if hasattr(self, "order_code_var"):
            fallback = self.order_code_var.get().strip()
        if not fallback and hasattr(self, "ent_code"):
            fallback = self.ent_code.get().strip()
        return [fallback] if fallback else []

    def _to_float(self, value):
        if value in (None, ""):
            return 0
        try:
            if isinstance(value, str):
                value = value.replace(",", "").replace("+", "").strip()
            return float(value)
        except Exception:
            return 0

    def _calc_tick_unit(self, price):
        if price >= 1000000:
            return 1000
        if price >= 500000:
            return 500
        if price >= 100000:
            return 100
        if price >= 50000:
            return 100
        if price >= 10000:
            return 50
        if price >= 2000:
            return 10
        if price >= 1000:
            return 5
        if price >= 500:
            return 1
        return 1

    def _build_offsets_for_side(self, side):
        if side == "sell":
            return list(range(1, 11))
        return list(range(-1, -11, -1))

    def _resolve_symbol_name(self, code):
        holdings = (self.dashboard_data or {}).get("Holdings") or []
        target = next((h for h in holdings if h.get("종목코드") == code), None)
        if target and target.get("종목명"):
            return target.get("종목명")
        sym = getattr(self.state, "symbols", {}).get(code) if hasattr(self.state, "symbols") else None
        return getattr(sym, "name", "")

    def _resolve_symbol_price(self, code, fallback=None):
        if fallback is not None:
            base = self._to_float(fallback)
            if base > 0:
                return base
        holdings = (self.dashboard_data or {}).get("Holdings") or []
        target = next((h for h in holdings if h.get("종목코드") == code), None)
        if target:
            price_val = self._to_float(target.get("현재가") or target.get("평가단가"))
            if price_val > 0:
                return price_val
        sym = getattr(self.state, "symbols", {}).get(code) if hasattr(self.state, "symbols") else None
        if sym and getattr(sym, "last_price", 0) > 0:
            return float(sym.last_price)
        return None

    def _set_price_entries(self, price_value):
        if not hasattr(self, "ent_limit_price"):
            return
        if price_value is None:
            return
        formatted = self._format_abs_number(price_value)
        if formatted:
            self.ent_limit_price.delete(0, tk.END)
            self.ent_limit_price.insert(0, formatted)
            if hasattr(self, "ent_stop"):
                self.ent_stop.delete(0, tk.END)
                self.ent_stop.insert(0, formatted)

    def set_order_symbol_context(self, code, name=None, price=None):
        if not code:
            return
        if hasattr(self, "order_code_var"):
            self.order_code_var.set(code)
        if hasattr(self, "ent_order_code"):
            self.ent_order_code.delete(0, tk.END)
            self.ent_order_code.insert(0, code)
        if hasattr(self, "ent_code"):
            self.ent_code.delete(0, tk.END)
            self.ent_code.insert(0, code)
        resolved_name = name or self._resolve_symbol_name(code)
        if resolved_name:
            self.order_name_var.set(resolved_name)
        base_price = self._resolve_symbol_price(code, price)
        if base_price:
            self.update_price_combo_from_code(code, base_price)

    def on_manual_order_code_change(self):
        if not hasattr(self, "order_code_var"):
            return
        code = self.order_code_var.get().strip()
        if not code:
            return
        self.set_order_symbol_context(code)

    def update_order_type_ui(self):
        if not hasattr(self, "order_type_var"):
            return
        mode = self.order_type_var.get()
        if hasattr(self, "cmb_price"):
            combo_state = "disabled" if mode == "market" else "readonly"
            self.cmb_price.configure(state=combo_state)
        if hasattr(self, "ent_limit_price"):
            self.ent_limit_price.configure(state="normal" if mode != "market" else "disabled")
        if hasattr(self, "ent_stop"):
            self.ent_stop.configure(state="normal")

    def on_trade_side_changed(self):
        code = self.order_code_var.get().strip() if hasattr(self, "order_code_var") else ""
        if code:
            self.update_price_combo_from_code(code)

    def update_strategy_ui(self):
        if not hasattr(self, "btn_strategy"):
            return
        if self.strategy_running:
            self.btn_strategy.config(text="전략 중지")
            display = self.strategy_mode_var.get() if hasattr(self, "strategy_mode_var") else ""
            status = f"{display} 실행중 ({len(self.strategy_targets)}종목)"
            self.lbl_strategy_status.config(text=status, foreground="green")
        else:
            self.btn_strategy.config(text="전략 실행")
            self.lbl_strategy_status.config(text="대기중", foreground="gray")

    def toggle_strategy_execution(self):
        if not hasattr(self, "strategy_mode_var"):
            return
        if self.strategy_running:
            self.strategy_running = False
            self.strategy_targets.clear()
            self.update_strategy_ui()
            self.log("전략 매매를 중지했습니다.", "ORDER")
            return
        selection = self.strategy_mode_var.get()
        mode = self.strategy_mode_map.get(selection, "manual")
        if mode == "manual":
            self.log("전략 유형을 선택하세요.", "ERR")
            return
        targets = self.get_selected_order_codes()
        if not targets:
            self.log("전략을 적용할 종목이 없습니다.", "ERR")
            return
        qty_str = self.ent_qty.get().strip() if hasattr(self, "ent_qty") else "0"
        if not qty_str.isdigit():
            self.log("전략 수량을 숫자로 입력하세요.", "ERR")
            return
        qty = int(qty_str)
        if qty <= 0:
            self.log("전략 수량은 1 이상이어야 합니다.", "ERR")
            return
        manual_price = self.ent_limit_price.get().strip() if hasattr(self, "ent_limit_price") else ""
        ref_price = self._parse_price_value(manual_price)
        if ref_price is None:
            combo_text = self.cmb_price.get() if hasattr(self, "cmb_price") else ""
            ref_price = self._parse_price_value(combo_text)
        if ref_price is None:
            self.log("전략 기준 가격이 필요합니다.", "ERR")
            return
        stop_text = self.ent_stop.get().strip() if hasattr(self, "ent_stop") else ""
        sell_price = self._parse_price_value(stop_text)
        if sell_price is None:
            sell_price = ref_price
        self.strategy_targets = {
            code: {
                "mode": mode,
                "qty": qty,
                "buy_price": ref_price,
                "sell_price": sell_price,
                "executed_buy": False,
                "executed_sell": False
            } for code in targets
        }
        self.strategy_running = True
        self.update_strategy_ui()
        self.log(f"전략 '{mode}' 실행: {targets}", "ORDER")

    def _evaluate_strategy_signal(self, code, symbol):
        plan = self.strategy_targets.get(code)
        if not plan:
            return
        last_price = getattr(symbol, "last_price", None)
        if last_price is None:
            last_price = self._resolve_symbol_price(code)
        if last_price is None:
            return
        triggered = False
        if plan["mode"] in ("buy", "both") and not plan.get("executed_buy") and last_price <= plan["buy_price"]:
            self.run_async(self.place_order(1, code, plan["qty"], mode="limit", price_value=plan["buy_price"]))
            plan["executed_buy"] = True
            triggered = True
        if plan["mode"] in ("sell", "both") and not plan.get("executed_sell") and last_price >= plan["sell_price"]:
            self.run_async(self.place_order(2, code, plan["qty"], mode="limit", price_value=plan["sell_price"]))
            plan["executed_sell"] = True
            triggered = True
        if triggered:
            self.log(f"전략 트리거 {code}: 현재가 {self._format_abs_number(last_price)}", "ORDER")
        done = False
        if plan["mode"] == "buy" and plan.get("executed_buy"):
            done = True
        elif plan["mode"] == "sell" and plan.get("executed_sell"):
            done = True
        elif plan["mode"] == "both" and plan.get("executed_buy") and plan.get("executed_sell"):
            done = True
        if done:
            self.strategy_targets.pop(code, None)
        if self.strategy_running and not self.strategy_targets:
            self.strategy_running = False
            self.update_strategy_ui()
            self.log("전략 대상이 모두 실행되어 자동 종료되었습니다.", "ORDER")

    @staticmethod
    def _is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _parse_float_value(self, value, abs_value=False):
        if value in (None, ""):
            return None
        try:
            if isinstance(value, str):
                text = value.replace(",", "").strip()
                if not text:
                    return None
                text = text.split()[0]
                if not text:
                    return None
                sign = 1
                if text[0] in "+-":
                    sign = -1 if text[0] == "-" else 1
                    text = text[1:]
                if text and text[-1] in "+-":
                    text = text[:-1]
                if not text:
                    return None
                num = float(text) * sign
            else:
                num = float(value)
            if abs_value:
                num = abs(num)
            return num
        except Exception:
            return None

    def _format_abs_number(self, value, decimals=0):
        num = self._parse_float_value(value, abs_value=True)
        if num is None:
            return ""
        if decimals <= 0:
            return format(num, ",.0f")
        return format(num, f",.{decimals}f")

    async def get_balance(self):
        self.log(">>> Balance...", "INFO")
        if not await self.ensure_account(): return
        acc = self.account_no
        res = await self.kit.get_account_balance(acc) if hasattr(self.kit, 'get_account_balance') else await self.kit.get_balance_snapshot(acc)
        self.log_json(res, "API")

    async def get_conditions(self):
        self.log(">>> 조건검색 목록 조회...", "INFO")
        res = await self.kit.get_condition_list()
        
        if res.get('Success'):
            data = res.get('Data', [])
            # data structure: [{'Index': 0, 'Name': '...'}, ...]
            self.condition_map = {item['Name']: item['Index'] for item in data}
            names = list(self.condition_map.keys())
            
            self.cb_cond['values'] = names
            if names: self.cb_cond.current(0)
            
            self.log(f"✅ Loaded {len(names)} conditions: {names}", "INFO")
        else:
            self.log(f"Error: {res.get('Message')}", "ERR")

    async def run_condition(self):
        name = self.cb_cond.get()
        if not name:
            self.log("조건식을 선택하세요.", "ERR")
            return
            
        idx = self.condition_map.get(name)
        if idx is None:
            self.log("조건식 인덱스를 찾을 수 없습니다.", "ERR")
            return
            
        self.log(f">>> 조건식 실행: {name} (Idx: {idx})", "INFO")
        res = await self.kit.search_condition(idx, name)
        
        if res.get('Success'):
            payload = res.get('Data') or {}
            stocks = []
            codes = []

            if isinstance(payload, dict):
                codes = payload.get('Codes') or payload.get('codes') or []
                stocks = payload.get('Stocks') or payload.get('stocks') or payload.get('Rows') or []
            else:
                codes = payload or []

            if not codes and stocks:
                codes = [row.get('종목코드', '') for row in stocks if row.get('종목코드')]

            if stocks:
                count = len(stocks)
                self.log(f"✅ 포착된 종목수: {count}", "INFO")
                self.log_json(stocks[:5], "COND-DETAIL")
                self.state.set_condition_hits(stocks)
                await self.subscribe_condition_realtime(codes)
                self.log("좌측 조건 그리드에 상세 데이터를 출력했습니다.", "INFO")
            elif codes:
                self.log(f"✅ 포착된 종목수: {len(codes)} (상세데이터 미수신, 종목코드만 표시)", "INFO")
                fallback_rows = [{"종목코드": c} for c in codes]
                self.state.set_condition_hits(fallback_rows)
                await self.subscribe_condition_realtime(codes)
            else:
                self.state.set_condition_hits([])
                self.log("포착된 종목이 없습니다.", "INFO")
        else:
            self.log(f"Error: {res.get('Message')}", "ERR")

    async def subscribe_condition_realtime(self, codes):
        await self.subscribe_realtime_codes(codes, screen_base=9200)
        self.condition_rt_codes = list(self.rt_subscribed_codes)
        await self.ensure_realtime_listener(auto=True)

    async def subscribe_realtime_codes(self, codes, screen_base=9300):
        added = []
        new_codes = [
            c.strip() for c in codes
            if c and c.strip() and c.strip() not in self.rt_subscribed_codes
        ]
        if not new_codes:
            return added
        chunk_size = 50
        for idx in range(0, len(new_codes), chunk_size):
            chunk = new_codes[idx:idx + chunk_size]
            screen = f"{screen_base + idx // chunk_size:04d}"
            try:
                res = await self.kit.subscribe_realtime(";".join(chunk), screen=screen)
                self.log_json(res, "RT-SUB")
                self.rt_subscribed_codes.update(chunk)
                added.extend(chunk)
                preview = ", ".join(chunk[:3])
                self.log(f"실시간 구독 등록: {preview}... ({len(chunk)}종목, Screen {screen})", "WS")
            except Exception as e:
                self.log(f"실시간 구독 실패: {e}", "ERR")
        return added

    async def ensure_realtime_listener(self, auto=False):
        if not self.rt_subscribed_codes:
            self.log("실시간 구독 대상 코드가 없습니다. 먼저 조건식이나 코드를 등록하세요.", "ERR")
            return
        if self.rt_listener_task and not self.rt_listener_task.done():
            if not self.is_realtime_running:
                self._update_realtime_ui_state(True)
            return
        if auto:
            self.log("Realtime WS가 정지 상태여서 자동으로 재시작합니다.", "WS")
        self._update_realtime_ui_state(True)
        loop = asyncio.get_running_loop()
        self.rt_listener_task = loop.create_task(self.ws_flow_rt())

    def on_condition_rows_updated(self, rows):
        current_codes = {row.get("종목코드") for row in rows if isinstance(row, dict) and row.get("종목코드")}
        if self.selected_order_codes:
            self.selected_order_codes = {code for code in self.selected_order_codes if code in current_codes}
        self._render_condition_rows(rows)
        self.render_order_grid()

    def on_symbol_updated(self, symbol):
        code = getattr(symbol, "code", "")
        if not code:
            return
        self._update_condition_row(symbol)
        self._update_order_tree_row(symbol)
        if self.strategy_running and code in self.strategy_targets:
            self._evaluate_strategy_signal(code, symbol)

    def refresh_condition_views(self):
        self._render_condition_rows(self.state.condition_hits)
        self.render_order_grid()

    def _render_condition_rows(self, rows):
        if not hasattr(self, "cond_tree"):
            return
        for iid in self.cond_tree.get_children():
            self.cond_tree.delete(iid)
        self.condition_row_iids = {}
        if not rows:
            return

        for row in rows:
            values = self._format_condition_row(row)
            iid = self.cond_tree.insert("", "end", values=values)
            code = row.get("종목코드") if isinstance(row, dict) else None
            if code:
                self.condition_row_iids[code] = iid

    def _format_condition_row(self, row, symbol=None):
        if not isinstance(row, dict):
            return ("", str(row), "", "", "", "", "")
        code = row.get("종목코드") or ""
        sym = symbol
        if sym is None and hasattr(self.state, "symbols"):
            sym = self.state.symbols.get(code)

        def fallback(value, supplier=None):
            if not self._is_empty(value):
                return value
            if supplier:
                supplied = supplier()
                if not self._is_empty(supplied):
                    return supplied
            return ""

        name = fallback(row.get("종목명"), lambda: getattr(sym, "name", ""))

        raw_price = row.get("현재가")
        if self._is_empty(raw_price) and sym and sym.last_price:
            raw_price = sym.last_price
        current = self._format_abs_number(raw_price)

        change = fallback(row.get("전일대비"), lambda: f"{sym.change:+,.0f}" if sym and sym.change else "")

        rate = fallback(row.get("등락율"), lambda: f"{sym.change_rate:+.2f}" if sym and sym.change_rate else "")

        power = fallback(row.get("체결강도"), lambda: f"{sym.strength:.2f}" if sym and sym.strength else "")

        volratio = row.get("전일대비거래량비율") or row.get("전일비 거래량 대비(%)")
        if self._is_empty(volratio) and sym and sym.prev_volume_ratio:
            volratio = f"{sym.prev_volume_ratio:.2f}"

        return (
            code,
            name or "",
            current or "",
            change or "",
            rate or "",
            power or "",
            volratio or ""
        )

    def _find_condition_row(self, code):
        for row in self.state.condition_hits or []:
            if isinstance(row, dict) and row.get("종목코드") == code:
                return row
        return None

    def _update_condition_row(self, symbol):
        if not hasattr(self, "cond_tree"):
            return
        code = getattr(symbol, "code", "")
        if not code:
            return
        iid = self.condition_row_iids.get(code)
        if not iid:
            return
        row = self._find_condition_row(code)
        if not row:
            return
        values = self._format_condition_row(row, symbol)
        self.cond_tree.item(iid, values=values)

    def _update_order_tree_row(self, symbol):
        if not hasattr(self, "order_tree"):
            return
        code = getattr(symbol, "code", "")
        if not code:
            return
        iid = self.order_row_iids.get(code)
        if not iid:
            return
        holdings = (self.dashboard_data or {}).get("Holdings") or []
        hold = next((h for h in holdings if h.get("종목코드") == code), None)
        cond_row = self._find_condition_row(code)

        name = ""
        if cond_row:
            name = cond_row.get("종목명") or ""
        if self._is_empty(name) and hold:
            name = hold.get("종목명") or ""
        if self._is_empty(name) and getattr(symbol, "name", ""):
            name = symbol.name

        price = cond_row.get("현재가") if cond_row else None
        if self._is_empty(price) and hold:
            price = hold.get("현재가")
        if self._is_empty(price) and getattr(symbol, "last_price", None):
            price = symbol.last_price
        price_display = self._format_abs_number(price)

        qty = hold.get("보유수량") if hold else ""
        pnl = hold.get("평가손익") if hold else ""
        rate = hold.get("손익률") if hold else ""
        mark = "■" if code in self.selected_order_codes else "□"

        self.order_tree.item(
            iid,
            values=(
                mark,
                code,
                name or "",
                price_display or "",
                qty or "",
                pnl or "",
                rate or ""
            )
        )

    def on_watchlist_select(self, event):
        if not hasattr(self, "cond_tree"):
            return
        selected_items = self.cond_tree.selection()
        codes = set()
        for item in selected_items:
            code = self.cond_tree.set(item, "code")
            if code:
                codes.add(code)
        if codes:
            self.selected_order_codes = codes
        else:
            self.selected_order_codes.clear()
        self.render_order_grid()

    async def download_candles(self):
        code = self.ent_code.get()
        tf = self.cb_tf.get() # e.g. "m30", "T1", "D1"
        stop_val_raw = self.ent_date.get().strip()
        
        if not code or not tf:
            self.log("Please enter Code and TimeFrame.", "ERR")
            return
            
        type_char = tf[0] # m, T, D, W, M
        interval_str = tf[1:]
        interval = int(interval_str) if interval_str.isdigit() else 1
        
        # Format Cleanup
        import re
        nums = re.sub(r"[^0-9]", "", stop_val_raw)
        
        # Daily Logic (Client-Side Paging)
        if type_char in ['D', 'W', 'M']:
            # Ensure YYYYMMDD
            stop_date = nums[:8]
            if len(stop_date) < 8:
                stop_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y%m%d")
            
            self.log(f">>> [Daily] Fetching {code} until {stop_date}...", "INFO")
            
            all_rows = []
            curr_date = "" # Empty means Today
            page = 0
            
            while True:
                page += 1
                self.log(f"  Fetching Page {page} (Date: {curr_date or 'Latest'})...", "INFO")
                res = await self.kit.get_daily_candles(code, date=curr_date, stop_date=stop_date)
                
                if not res.get('Success'):
                    self.log(f"Available/Error at page {page}: {res.get('Message')}", "ERR")
                    break
                    
                rows = res.get('Data', [])
                if not rows:
                    break
                    
                all_rows.extend(rows)
                last_row_date = rows[-1].get('일자', '')
                
                # Check Stop Condition
                if not last_row_date or last_row_date <= stop_date:
                    self.log("  Reached Stop Date.", "INFO")
                    break
                    
                # Prepare Next Page (Next date = last_date - 1 day, roughly handled by API using strictly less than?)
                # Actually OPT10081 'Criteria Date' returns candles BEFORE that date if modified price is used?
                # Kiwoom OPT10081: Input 'Date' -> Returns data STARTING from that date BACKWARDS.
                # So if we got data until 20230101, next request should be 20221231.
                # However, client_kit.get_daily_candles uses 'date' param.
                
                # Let's calculate prev day
                try:
                    dt = datetime.datetime.strptime(last_row_date, "%Y%m%d")
                    prev_dt = dt - datetime.timedelta(days=1)
                    curr_date = prev_dt.strftime("%Y%m%d")
                except:
                    break
                    
                await asyncio.sleep(0.2) # Safety delay
                
                if page > 50: # Client side safety limit (50 * 600 = 30000 days)
                    self.log("  Client Page Limit Reached (50).", "INFO")
                    break
            
            # Filter strictly
            final_rows = [r for r in all_rows if r.get('일자', '99999999') >= stop_date]
            count = len(final_rows)
            if count > 0:
                self.log(f"✅ Total {count} Daily Candles Downloaded.", "INFO")
                f = final_rows[0]['일자']
                l = final_rows[-1]['일자']
                self.log(f"📅 Range: {f} ~ {l}", "INFO")
                
            self.update_views(final_rows)
            self.state.set_candles(code, tf, final_rows)
            self.log_json(final_rows[:2], "Top 2")
            return

        # Minute/Tick Logic (Server Smart Paging)
        # Ensure YYYYMMDDHHMMSS
        stop_time = nums
        if len(stop_time) < 14:
            # Pad with 090000 or similar if short
            if len(stop_time) == 8: stop_time += "090000"
            else: stop_time = stop_time.ljust(14, '0')
        
        self.log(f">>> [Intraday] {code} {tf} (Intv:{interval}) Stop:{stop_time}...", "INFO")
        
        res = None
        if type_char == 'm':
            res = await self.kit.get_minute_candles(code, tick=interval, stop_time=stop_time)
        elif type_char == 'T':
            res = await self.kit.get_tick_candles(code, tick=interval, stop_time=stop_time)
        
        if res and res.get('Success'):
            rows = res['Data']
            count = len(rows)
            if count > 0:
                first = rows[0].get('체결시간', '?')
                last = rows[-1].get('체결시간', '?')
                self.log(f"✅ Downloaded {count} Candles ({tf}).", "INFO")
                self.log(f"📅 Range: {first} (Latest) ~ {last} (Oldest)", "INFO")
                
                if last > stop_time:
                    self.log(f"ℹ️ Oldest candle ({last}) is newer than stop time ({stop_time}).", "INFO")
                    self.log("   (This may be due to data gaps or market close. Verify via Grid.)", "INFO")
                    
            self.update_views(rows)
            self.state.set_candles(code, tf, rows)
            self.log_json(rows[:2], "Top 2")
        else:
            self.log_json(res, "ERR")

    def run_indicator_builder(self):
        if not self.current_chart_data:
            self.log("먼저 캔들을 다운로드하세요.", "ERR")
            return
        indicator = self.indicator_type_var.get()
        try:
            p1 = int(self.ent_indicator_param1.get() or 0)
            p2 = int(self.ent_indicator_param2.get() or 0)
        except ValueError:
            self.log("지표 파라미터는 숫자여야 합니다.", "ERR")
            return

        closes = [d['c'] for d in self.current_chart_data]
        label = indicator
        color = "#1abc9c"

        if indicator == "SMA":
            period = max(1, p1 or 5)
            values = self._calc_sma(closes, period)
            label = f"SMA({period})"
            color = "#1abc9c"
            self._store_overlay(f"sma_{period}", label, values, color)
        elif indicator == "EMA":
            period = max(1, p1 or 5)
            values = self._calc_ema(closes, period)
            label = f"EMA({period})"
            color = "#e67e22"
            self._store_overlay(f"ema_{period}", label, values, color)
        elif indicator == "RSI":
            period = max(2, p1 or 14)
            values = self._calc_rsi(closes, period)
            self.candle_indicators["RSI"] = values
            latest = next((v for v in reversed(values) if v is not None), None)
            msg = f"RSI({period}) 최근값 {latest:.2f}" if latest is not None else f"RSI({period}) 계산완료"
            self.lbl_indicator_status.config(text=msg, foreground="green")
            self._set_pipeline_status("indicator", "완료", f"RSI({period})")
            self.log(msg, "INFO")
            self.draw_candle_chart()
            return
        else:
            self.log(f"지원하지 않는 지표: {indicator}", "ERR")
            return

        self.lbl_indicator_status.config(text=f"{label} 계산완료", foreground="green")
        self._set_pipeline_status("indicator", "완료", label)
        self.log(f"{label} calculated.", "INFO")
        self.draw_candle_chart()

    def _store_overlay(self, key, label, values, color):
        if not values:
            return
        overlay = {"key": key, "label": label, "values": values, "color": color}
        self.chart_overlays = [o for o in self.chart_overlays if o.get("key") != key]
        self.chart_overlays.append(overlay)
        self.candle_indicators[key] = values

    def run_candle_strategy(self):
        if not self.current_chart_data:
            self.log("전략을 실행하려면 캔들이 필요합니다.", "ERR")
            return
        strategy = self.candle_strategy_type_var.get()
        try:
            param1 = int(self.ent_candle_param1.get() or 0)
            param2 = int(self.ent_candle_param2.get() or 0)
        except ValueError:
            self.log("전략 파라미터는 숫자여야 합니다.", "ERR")
            return

        closes = [d['c'] for d in self.current_chart_data]
        markers = []
        summary = ""

        if strategy == "SMA Cross":
            fast = max(1, param1 or 5)
            slow = max(fast + 1, param2 or 20)
            fast_series = self._calc_sma(closes, fast)
            slow_series = self._calc_sma(closes, slow)
            prev_state = None
            for idx in range(len(closes)):
                f = fast_series[idx]
                s = slow_series[idx]
                if f is None or s is None:
                    continue
                curr_state = "above" if f > s else "below" if f < s else prev_state
                if prev_state and curr_state != prev_state:
                    if curr_state == "above":
                        markers.append({"index": idx, "price": closes[idx], "type": "buy"})
                    elif curr_state == "below":
                        markers.append({"index": idx, "price": closes[idx], "type": "sell"})
                prev_state = curr_state
            self._store_overlay(f"sma_{fast}", f"SMA({fast})", fast_series, "#16a085")
            self._store_overlay(f"sma_{slow}", f"SMA({slow})", slow_series, "#c0392b")
            summary = f"{len(markers)} crossover"
        elif strategy == "RSI Band":
            period = max(2, param1 or 14)
            over = max(10, min(90, param2 or 70))
            under = max(5, 100 - over)
            rsi = self._calc_rsi(closes, period)
            for idx, val in enumerate(rsi):
                if val is None:
                    continue
                if val <= under:
                    markers.append({"index": idx, "price": closes[idx], "type": "buy"})
                elif val >= over:
                    markers.append({"index": idx, "price": closes[idx], "type": "sell"})
            self.candle_indicators["RSI"] = rsi
            summary = f"{len(markers)} RSI signals"
        else:
            self.log(f"지원하지 않는 전략: {strategy}", "ERR")
            return

        self.strategy_markers = markers
        status_text = f"{strategy}: {summary}"
        status_color = "green" if markers else "orange"
        self.lbl_candle_strategy_status.config(text=status_text, foreground=status_color)
        self._set_pipeline_status("strategy", "완료" if markers else "확인", summary)
        self.log(status_text, "ORDER")
        self.draw_candle_chart()

    def _calc_sma(self, series, period):
        values = []
        if period <= 0:
            period = 1
        for idx in range(len(series)):
            if idx + 1 < period:
                values.append(None)
                continue
            window = series[idx - period + 1: idx + 1]
            values.append(sum(window) / period)
        return values

    def _calc_ema(self, series, period):
        values = []
        if period <= 0:
            period = 1
        multiplier = 2 / (period + 1)
        ema_value = None
        for idx, price in enumerate(series):
            if idx + 1 < period:
                values.append(None)
                continue
            if ema_value is None:
                window = series[idx - period + 1: idx + 1]
                ema_value = sum(window) / period
            else:
                ema_value = (price - ema_value) * multiplier + ema_value
            values.append(ema_value)
        return values

    def _calc_rsi(self, series, period):
        rsi = [None] * len(series)
        if len(series) <= period:
            return rsi
        gains = []
        losses = []
        for i in range(1, len(series)):
            diff = series[i] - series[i - 1]
            gains.append(max(diff, 0))
            losses.append(abs(min(diff, 0)))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        if avg_loss == 0:
            rsi_val = 100
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100 - (100 / (1 + rs))
        rsi[period] = rsi_val
        for i in range(period + 1, len(series)):
            gain = gains[i - 1]
            loss = losses[i - 1]
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period
            if avg_loss == 0:
                rsi_val = 100
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100 - (100 / (1 + rs))
            rsi[i] = rsi_val
        return rsi

    async def get_symbol(self):
        code = self.ent_code.get()
        self.log(f">>> {code} Symbol Info...", "INFO")
        res = await self.kit.get_symbol_info(code)
        self.log_json(res, "API")

    async def get_deposit(self):
        if not await self.ensure_account(): return
        acc = self.account_no
        self.log(f">>> Deposit ({acc})...", "INFO")
        res = await self.kit.get_deposit(acc)
        self.log_json(res, "API")

    async def get_outstanding(self):
        if not await self.ensure_account(): return
        acc = self.account_no
        self.log(f">>> Outstanding Orders ({acc})...", "INFO")
        res = await self.kit.get_outstanding_orders(acc)
        self.log_json(res, "API")

    def trigger_submit_orders(self, order_side):
        side_value = "buy" if order_side == 1 else "sell"
        if hasattr(self, "trade_side_var"):
            self.trade_side_var.set(side_value)
        code = self.order_code_var.get().strip() if hasattr(self, "order_code_var") else ""
        if code:
            self.set_order_symbol_context(code)
        self.run_async(self.submit_orders(order_side))
        
    async def submit_orders(self, order_side):
        targets = self.get_selected_order_codes()
        if not targets:
            self.log("선택된 종목이 없습니다.", "ERR")
            return
        qty_str = self.ent_qty.get().strip()
        if not qty_str.isdigit():
            self.log("수량을 숫자로 입력하세요.", "ERR")
            return
        qty = int(qty_str)
        if qty <= 0:
            self.log("수량은 1 이상이어야 합니다.", "ERR")
            return

        selected_price = self.cmb_price.get() if hasattr(self, "cmb_price") else ""
        manual_price_text = self.ent_limit_price.get().strip() if hasattr(self, "ent_limit_price") else ""
        price_value = self._parse_price_value(manual_price_text) if manual_price_text else self._parse_price_value(selected_price)
        order_mode = self.order_type_var.get()
        stop_price_text = self.ent_stop.get().strip() if hasattr(self, "ent_stop") else ""
        stop_price_value = self._parse_price_value(stop_price_text) if stop_price_text else None

        for code in targets:
            await self.place_order(order_side, code, qty, order_mode, price_value, stop_price_value)

    def _parse_price_value(self, text):
        if not text:
            return None
        value = self._parse_float_value(text)
        if value is None:
            return None
        return int(round(value))

    async def place_order(self, order_side, code, quantity, mode="limit", price_value=None, stop_price=None):
        if not await self.ensure_account(): return
        code = code.strip()
        if not code:
            self.log("종목코드가 없습니다.", "ERR")
            return

        quote_type = "00"
        price = 0

        if mode == "market":
            quote_type = "03"
        elif mode == "stop":
            quote_type = "07"
            if stop_price is None:
                self.log("스탑가를 입력하세요.", "ERR")
                return
            if price_value:
                price = price_value
        else:
            if price_value is None:
                self.log("지정가 가격을 선택하세요.", "ERR")
                return
            price = price_value

        stop_payload = None
        if stop_price is not None:
            stop_payload = int(stop_price)

        type_str = "매수" if order_side == 1 else "매도"
        detail = f"{type_str} {code} {quantity}주 @ {price if mode!='market' else '시장가'} ({quote_type})"
        if stop_payload is not None:
            detail += f" / Stop {stop_payload:,}"
        self.log(f">>> 주문 전송: {detail}", "ORDER")

        try:
            url = f"{self.kit.host}/api/orders"
            payload = {
                "accountNo": self.account_no,
                "stockCode": code,
                "quantity": quantity,
                "price": price,
                "orderType": order_side,
                "quoteType": quote_type
            }
            if stop_payload is not None:
                payload["stopPrice"] = stop_payload
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    res = await resp.json()
                    self.log_json(res, "ORDER")
        except Exception as e:
            self.log(f"Order Error: {e}", "ERR")

    # --- WS ---
    def toggle_realtime(self):
        if not self.is_realtime_running:
            manual_codes = list(self.rt_subscribed_codes) if self.rt_subscribed_codes else [self.ent_code.get().strip()]
            manual_codes = [c for c in manual_codes if c]
            if not manual_codes:
                self.log("실시간 구독할 종목이 없습니다. 조건검색을 실행하거나 코드를 입력하세요.", "ERR")
                return
            self.run_async(self.start_manual_realtime(manual_codes))
        else:
            self.run_async(self.stop_realtime_listener("사용자 중지"))

    async def start_manual_realtime(self, codes):
        added = await self.subscribe_realtime_codes(codes, screen_base=9100)
        if not added and self.rt_listener_task and not self.rt_listener_task.done():
            self.log("이미 구독 중인 종목입니다. 실시간 WS 상태만 점검합니다.", "INFO")
        if not self.rt_listener_task or self.rt_listener_task.done():
            self.log("수동 요청으로 Realtime WS를 시작합니다.", "WS")
        await self.ensure_realtime_listener()

    async def stop_realtime_listener(self, reason=""):
        if not self.rt_listener_task:
            self._update_realtime_ui_state(False)
            return
        self._update_realtime_ui_state(False)
        self.rt_listener_task.cancel()
        try:
            await self.rt_listener_task
        except asyncio.CancelledError:
            pass
        self.rt_listener_task = None
        if reason:
            self.log(f"Realtime WS 중지: {reason}", "WS")

    async def ws_flow_rt(self):
        restart_required = False
        try:
            await self.kit.listen_realtime(self.on_rt_data)
        except asyncio.CancelledError:
            self.log("Realtime WS listener가 사용자 요청으로 중지되었습니다.", "WS")
            raise
        except Exception as e:
            restart_required = True
            self.log(f"Realtime WS listener 오류: {e}", "ERR")
        finally:
            self.rt_listener_task = None
            self._update_realtime_ui_state(False)
            if restart_required and self.rt_subscribed_codes:
                loop = asyncio.get_running_loop()
                loop.create_task(self.ensure_realtime_listener(auto=True))

    async def on_rt_data(self, data):
        data_type = data.get("type")
        if data_type == "condition":
            cond = data.get("data", {})
            state = cond.get("state")
            code = data.get("code")
            self.state.apply_condition_event(code, state or "", {"종목명": cond.get("condition_name"), "condition_name": cond.get("condition_name")})
            await self.subscribe_realtime_codes([code], screen_base=9250)
            self.log(f"[조건] {cond.get('condition_name')} {state} {code}", "WS")
            return
        if not self.is_realtime_running:
            return
        code = data.get("code")
        payload = data.get("data", {})
        if code and payload:
            sym_input = {"종목코드": code}
            price = payload.get("current_price")
            if price is not None:
                sym_input["현재가"] = price
            diff = payload.get("diff")
            if diff is not None:
                sym_input["전일대비"] = diff
            rate = payload.get("rate")
            if rate is not None:
                sym_input["등락율"] = rate
            intensity = payload.get("intensity")
            if intensity is not None:
                sym_input["체결강도"] = intensity
            volume = payload.get("volume")
            if volume is not None:
                sym_input["거래량"] = volume
            self.state.update_symbol(sym_input)
        log_price = payload.get("current_price")
        if log_price in (None, 0):
            fallback_price = payload.get("ask_price_1") or payload.get("bid_price_1")
            self.log(f"[Tick] code={code} price={log_price} fallback={fallback_price} type={data_type}", "WS")

    def toggle_execution(self):
        if not self.is_exec_running:
            self.is_exec_running = True
            self.btn_ex.config(text="■ 중지")
            self.run_async(self.ws_flow_ex())
            if hasattr(self, "lbl_exec"):
                self.lbl_exec.config(text="Execution WS: Running")
            self.run_async(self.load_dashboard_snapshot())
        else:
            self.is_exec_running = False
            self.btn_ex.config(text="▶ 체결/잔고 수신")
            if hasattr(self, "lbl_exec"):
                self.lbl_exec.config(text="Execution WS: Stopped")

    async def toggle_condition_stream(self):
        name = self.cb_cond.get()
        if not name:
            self.log("조건식을 선택하세요.", "ERR")
            return
        idx = self.condition_map.get(name)
        if idx is None:
            self.log("조건식 인덱스를 찾을 수 없습니다.", "ERR")
            return

        screen = self.condition_stream_info.get("screen", "9101")
        desired_start = True

        if self.condition_stream_active and (self.condition_stream_info.get("index") != idx or self.condition_stream_info.get("name") != name):
            self.log("기존 조건 실시간을 중지합니다.", "INFO")
            await self.kit.stop_condition_stream(self.condition_stream_info.get("index"), self.condition_stream_info.get("name"), screen)
            self.condition_stream_active = False

        if self.condition_stream_active:
            desired_start = False

        if desired_start:
            res = await self.kit.start_condition_stream(idx, name, screen)
            if res.get("Success"):
                self.condition_stream_active = True
                self.condition_stream_info.update({"name": name, "index": idx, "screen": screen})
                self.log(f"조건 실시간 등록 시작: {name}", "INFO")
            else:
                self.log(f"조건 실시간 등록 실패: {res.get('Message')}", "ERR")
        else:
            res = await self.kit.stop_condition_stream(self.condition_stream_info.get("index"), self.condition_stream_info.get("name"), screen)
            if res.get("Success"):
                self.condition_stream_active = False
                self.log("조건 실시간이 중지되었습니다.", "INFO")
                self.state.set_condition_hits([])
                self.condition_rt_codes = []
            else:
                self.log(res.get("Message"), "ERR")

        self.update_condition_stream_label()

    def update_condition_stream_label(self):
        if hasattr(self, "lbl_cond_stream"):
            state = "ON" if self.condition_stream_active else "OFF"
            target = self.condition_stream_info.get("name") if self.condition_stream_active else "-"
            self.lbl_cond_stream.config(text=f"조건 실시간: {state} ({target})")
        if hasattr(self, "btn_cond_stream"):
            self.btn_cond_stream.config(text="■ 조건 실시간 중지" if self.condition_stream_active else "▶ 조건 실시간 시작")

    async def ws_flow_ex(self):
        await self.kit.listen_execution(self.on_ex_data)

    def _update_realtime_ui_state(self, running: bool):
        self.is_realtime_running = running
        if hasattr(self, "lbl_rt"):
            self.lbl_rt.config(text="Realtime WS: Running" if running else "Realtime WS: Stopped")
        if hasattr(self, "btn_rt"):
            self.btn_rt.config(text="■ 실시간 중지" if running else "▶ 실시간 구독 (현재 Code)")

    async def on_ex_data(self, data):
        data_type = data.get("type")
        if data_type == "dashboard":
            snap = data.get("data")
            if snap:
                updated = self.state.set_dashboard_snapshot(snap)
                if updated:
                    self.log("대시보드가 실시간으로 갱신되었습니다.", "WS")
            return
        if data_type in ("order", "balance"):
            self.log_json(data, "WS-EXEC")
            await self.load_dashboard_snapshot(force=True)
            return
        if not self.is_exec_running:
            return
        self.log_json(data, "WS-EXEC")

    # --- Log ---
    def log(self, msg, tag="INFO"):
        self.txt_log.config(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{ts}] ", "INFO")
        self.txt_log.insert("end", f"{msg}\n", tag)
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def log_json(self, obj, tag="INFO"):
        try:
            s = json.dumps(obj, indent=2, ensure_ascii=False)
            self.log(s, tag)
        except:
            self.log(str(obj), tag)

    def update_views(self, data):
        # 1. Restore candle columns & clear views
        self.setup_grid_columns([
            ("time", "TIME", 140, "c"),
            ("open", "OPEN", 80, "e"),
            ("high", "HIGH", 80, "e"),
            ("low", "LOW", 80, "e"),
            ("close", "CLOSE", 80, "e"),
            ("volume", "VOLUME", 80, "e"),
        ])
        self.canvas.delete("all")
        self.current_chart_data = []
        self.candle_dataset = data or []
        self.chart_overlays = []
        self.strategy_markers = []
        self.candle_indicators = {}
        if hasattr(self, "lbl_indicator_status"):
            self.lbl_indicator_status.config(text="지표 대기중", foreground="gray")
        if hasattr(self, "lbl_candle_strategy_status"):
            self.lbl_candle_strategy_status.config(text="전략 대기중", foreground="gray")
        if data:
            self._set_pipeline_status("download", "완료", f"{len(data)}건")
        else:
            self._set_pipeline_status("download", "대기", "데이터 없음")
            self._set_pipeline_status("indicator", "대기", "지표 선택")
            self._set_pipeline_status("strategy", "대기", "전략 선택")
            return
        self._set_pipeline_status("indicator", "대기", "지표 선택")
        self._set_pipeline_status("strategy", "대기", "전략 선택")

        # 2. Normalize Data
        norm_data = []
        for row in data:
            # Time: Handle daily '일자' or minute '체결시간'
            t = row.get('일자') or row.get('체결시간') or "?"
            
            # Helper to parse price (handle string and negative)
            def p(key):
                val = row.get(key, 0)
                if isinstance(val, str): val = val.strip()
                return abs(int(val)) if val else 0
            
            # Kiwoom keys vary by TR
            o = p('시가')
            h = p('고가')
            l = p('저가')
            c = p('현재가') if '현재가' in row else p('종가')
            v = p('거래량')
            
            norm_data.append({'t': t, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v})

        # 3. Update Grid
        for d in norm_data:
            self.tree.insert("", "end", values=(d['t'], d['o'], d['h'], d['l'], d['c'], d['v']))
            
        # 4. Update Chart Data & Draw
        self.current_chart_data = norm_data
        self.draw_candle_chart()
        
        # Focus Notebook to Chart if desired, or stay
        # self.notebook.select(self.tab_grid) 

    def draw_candle_chart(self):
        data = self.current_chart_data
        if not data: return
        
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50: return # wait for resize
        
        self.canvas.delete("all")
        self.chart_layout = None
        self.clear_crosshair()
        
        # Margins
        mt, mb, ml, mr = 20, 30, 10, 50
        cw = w - ml - mr
        ch = h - mt - mb
        plot_left = ml
        plot_right = ml + cw
        plot_top = mt
        plot_bottom = mt + ch
        
        # Data is Latest -> Oldest. Reverse for chart (Left=Old, Right=New)
        draw_data = data[::-1]
        cnt = len(draw_data)
        
        # Find Min/Max Price
        min_p = min(d['l'] for d in draw_data)
        max_p = max(d['h'] for d in draw_data)
        
        if min_p == max_p:
            min_p *= 0.99
            max_p *= 1.01
        
        price_range = max_p - min_p
        
        # Calculate X Step
        # Ensure candles fit in width
        step_x = cw / cnt
        
        # Gap between candles
        bar_w = max(1, step_x * 0.8)
        
        def get_y(price):
            ratio = (price - min_p) / price_range
            return mt + ch * (1 - ratio)
        
        for i, d in enumerate(draw_data):
            x_center = ml + (i * step_x) + (step_x / 2)
            
            yo = get_y(d['o'])
            yh = get_y(d['h'])
            yl = get_y(d['l'])
            yc = get_y(d['c'])
            
            color = "#ff3333" if d['c'] >= d['o'] else "#3333ff" # Red/Blue
            
            # Wick
            self.canvas.create_line(x_center, yh, x_center, yl, fill=color)
            
            # Body
            x1 = x_center - (bar_w / 2)
            x2 = x_center + (bar_w / 2)
            
            if abs(yo - yc) < 1:
                self.canvas.create_line(x1, yo, x2, yo, fill=color)
            else:
                self.canvas.create_rectangle(x1, yo, x2, yc, fill=color, outline=color)

        # Axes
        self.canvas.create_line(plot_left, plot_bottom, plot_right, plot_bottom, fill="#b0b0b0")
        self.canvas.create_line(plot_right, plot_top, plot_right, plot_bottom, fill="#b0b0b0")
        self.canvas.create_line(plot_left, plot_top, plot_left, plot_bottom, fill="#e0e0e0")
        self.canvas.create_line(plot_left, plot_top, plot_right, plot_top, fill="#f0f0f0")

        if getattr(self, "show_overlays_var", True) and self.chart_overlays:
            legend_y = mt + 5
            for overlay in self.chart_overlays:
                values = overlay.get("values", [])[::-1]
                prev_point = None
                for idx, val in enumerate(values):
                    if val is None:
                        prev_point = None
                        continue
                    x_center = ml + (idx * step_x) + (step_x / 2)
                    y_val = get_y(val)
                    if prev_point:
                        self.canvas.create_line(prev_point[0], prev_point[1], x_center, y_val, fill=overlay.get("color", "#2ecc71"), width=1.4)
                    prev_point = (x_center, y_val)
                self.canvas.create_text(ml + 5, legend_y, text=overlay.get("label", "Indicator"), anchor="nw", fill=overlay.get("color", "#2ecc71"), font=("Arial", 8))
                legend_y += 12

        if getattr(self, "show_markers_var", True) and self.strategy_markers:
            data_len = len(self.current_chart_data)
            for mark in self.strategy_markers:
                idx_latest = mark.get("index", 0)
                draw_idx = data_len - 1 - idx_latest
                if draw_idx < 0 or draw_idx >= len(draw_data):
                    continue
                price = mark.get("price", draw_data[draw_idx]['c'])
                x_center = ml + (draw_idx * step_x) + (step_x / 2)
                y_price = get_y(price)
                size = max(4, step_x * 0.3)
                if mark.get("type") == "buy":
                    color = "#e74c3c"
                    points = [x_center, y_price - size, x_center - size, y_price + size, x_center + size, y_price + size]
                else:
                    color = "#2980b9"
                    points = [x_center, y_price + size, x_center - size, y_price - size, x_center + size, y_price - size]
                self.canvas.create_polygon(points, fill=color, outline="")

        # Draw Labels (Min/Max Price)
        self.canvas.create_text(w-5, mt, text=str(max_p), anchor="ne", font=("Arial", 8))
        self.canvas.create_text(w-5, h-mb, text=str(min_p), anchor="se", font=("Arial", 8))
        
        # Draw Time Labels (Start/End)
        self.canvas.create_text(ml, h-5, text=draw_data[0]['t'], anchor="sw", font=("Arial", 8))
        self.canvas.create_text(w-mr, h-5, text=draw_data[-1]['t'], anchor="se", font=("Arial", 8))
        
        self.chart_layout = {
            "ml": ml,
            "mr": mr,
            "mt": mt,
            "mb": mb,
            "cw": cw,
            "ch": ch,
            "step_x": step_x,
            "draw_data": draw_data,
            "min_p": min_p,
            "max_p": max_p,
            "price_range": price_range,
            "plot_left": plot_left,
            "plot_right": plot_right,
            "plot_top": plot_top,
            "plot_bottom": plot_bottom,
            "w": w,
            "h": h
        }

    def redraw_chart_if_exists(self):
        if self.current_chart_data:
            self.draw_candle_chart()

    def on_chart_mouse_move(self, event):
        layout = getattr(self, "chart_layout", None)
        if not layout:
            return
        plot_left = layout["plot_left"]
        plot_right = layout["plot_right"]
        plot_top = layout["plot_top"]
        plot_bottom = layout["plot_bottom"]
        if event.x < plot_left or event.x > plot_right or event.y < plot_top or event.y > plot_bottom:
            self.clear_crosshair()
            return

        x = min(max(event.x, plot_left), plot_right)
        y = min(max(event.y, plot_top), plot_bottom)
        step_x = layout["step_x"]
        if step_x <= 0:
            return
        idx = int((x - plot_left) / step_x)
        idx = max(0, min(len(layout["draw_data"]) - 1, idx))
        candle = layout["draw_data"][idx]

        price_range = layout["price_range"] if layout["price_range"] else 1
        ratio = 1 - ((y - plot_top) / layout["ch"])
        ratio = min(max(ratio, 0), 1)
        price = layout["min_p"] + (ratio * price_range)

        self._update_crosshair_line("h", plot_left, y, plot_right, y)
        self._update_crosshair_line("v", x, plot_top, x, plot_bottom)

        price_text = f"{price:,.0f}"
        y_axis_x = min(layout["w"] - 5, plot_right + 5)
        self._update_crosshair_label("y", y_axis_x, y, price_text, anchor="w")

        time_text = candle.get("t", "")
        x_axis_y = plot_bottom + 12
        self._update_crosshair_label("x", x, x_axis_y, time_text, anchor="n")

    def _update_crosshair_line(self, key, x1, y1, x2, y2):
        if not hasattr(self, "crosshair_items"):
            self.crosshair_items = {k: None for k in ("h", "v", "x_text", "y_text", "x_bg", "y_bg")}
        line_id = self.crosshair_items.get(key)
        if line_id:
            self.canvas.coords(line_id, x1, y1, x2, y2)
        else:
            line_id = self.canvas.create_line(x1, y1, x2, y2, fill="#888888", dash=(4, 2))
            self.crosshair_items[key] = line_id
        self.canvas.tag_raise(line_id)

    def _update_crosshair_label(self, axis, x, y, text, anchor="w"):
        if not hasattr(self, "crosshair_items"):
            self.crosshair_items = {k: None for k in ("h", "v", "x_text", "y_text", "x_bg", "y_bg")}
        text_key = "y_text" if axis == "y" else "x_text"
        bg_key = "y_bg" if axis == "y" else "x_bg"
        font = ("Consolas", 9)
        if self.crosshair_items.get(text_key):
            self.canvas.coords(self.crosshair_items[text_key], x, y)
            self.canvas.itemconfig(self.crosshair_items[text_key], text=text, anchor=anchor, font=font)
        else:
            self.crosshair_items[text_key] = self.canvas.create_text(x, y, text=text, anchor=anchor, font=font, fill="#111111")
        bbox = self.canvas.bbox(self.crosshair_items[text_key])
        if bbox:
            pad_x, pad_y = 4, 2
            coords = (bbox[0]-pad_x, bbox[1]-pad_y, bbox[2]+pad_x, bbox[3]+pad_y)
            if self.crosshair_items.get(bg_key):
                self.canvas.coords(self.crosshair_items[bg_key], *coords)
            else:
                self.crosshair_items[bg_key] = self.canvas.create_rectangle(*coords, fill="#fffff0", outline="#999999")
            self.canvas.tag_lower(self.crosshair_items[bg_key], self.crosshair_items[text_key])

    def clear_crosshair(self):
        keys = ("h", "v", "x_text", "y_text", "x_bg", "y_bg")
        if not hasattr(self, "crosshair_items"):
            self.crosshair_items = {k: None for k in keys}
            return
        if not hasattr(self, "canvas"):
            self.crosshair_items = {k: None for k in keys}
            return
        for key in keys:
            item = self.crosshair_items.get(key)
            if item:
                try:
                    self.canvas.delete(item)
                except tk.TclError:
                    pass
        self.crosshair_items = {k: None for k in keys}

if __name__ == "__main__":
    root = tk.Tk()
    ServerTesterUI(root)
    root.mainloop()
