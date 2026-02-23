#!/usr/bin/env python3
"""
TES-Universe Trading Platform — Full UI Implementation v1.0
============================================================
"What You See Is What You Trade"

실행: python tes_platform_ui.py
필요 패키지: pip install PySide6 pyqtgraph numpy
선택 패키지: pip install lightweight-charts  (차트 고급 기능)

이 파일 하나로 전체 UI 레이아웃 + 더미 데이터 실시간 갱신이 동작합니다.
플랫폼 전환(VB.NET/C#) 시 이 레이아웃을 그대로 재현하면 됩니다.
"""

import sys
import random
import time
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

# ─── PySide6 Imports ───
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QSplitter, QTabWidget, QDockWidget, QMdiArea,
    QMdiSubWindow, QTreeWidget, QTreeWidgetItem, QTableView,
    QHeaderView, QLabel, QFrame, QPushButton, QToolBar, QMenuBar,
    QMenu, QStatusBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QComboBox, QTextEdit, QProgressBar, QSizePolicy,
    QAbstractItemView, QStyle, QStyleFactory
)
from PySide6.QtCore import (
    Qt, QTimer, QSettings, QByteArray, Signal as QtSignal,
    QAbstractTableModel, QModelIndex, QSize, QElapsedTimer, Slot
)
from PySide6.QtGui import (
    QColor, QFont, QPalette, QAction, QIcon, QPainter, QBrush,
    QPen, QLinearGradient
)

import pyqtgraph as pg
import numpy as np


# ═══════════════════════════════════════════════════════════════════
# SECTION 0: 테마 & 상수 (불변)
# ═══════════════════════════════════════════════════════════════════

class Theme:
    """플랫폼 독립 색상 체계 — VB.NET/C# 전환 시 동일 값 사용"""
    # ── 배경 ──
    BG_PRIMARY = "#0d1117"
    BG_SECONDARY = "#161b22"
    BG_TERTIARY = "#21262d"
    BG_CARD = "#1c2128"

    # ── 텍스트 ──
    TEXT_PRIMARY = "#e6edf3"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#484f58"

    # ── 강세/약세 ──
    BULL = "#ef4444"        # 한국시장 상승 = 빨강
    BEAR = "#3b82f6"        # 한국시장 하락 = 파랑
    BULL_BG = "#3b1515"
    BEAR_BG = "#152040"

    # ── 상태 ──
    STATUS_OK = "#22c55e"
    STATUS_WARN = "#eab308"
    STATUS_ERROR = "#ef4444"
    STATUS_OFF = "#484f58"

    # ── 강조 ──
    ACCENT = "#58a6ff"
    ACCENT_SECONDARY = "#bc8cff"
    GOLD = "#f0b429"

    # ── 축 점수 색상 ──
    AXIS1_HMS = "#f97316"   # 주황
    AXIS2_BMS = "#06b6d4"   # 청록
    AXIS3_SLS = "#a855f7"   # 보라

    # ── 폰트 ──
    FONT_FAMILY = "Malgun Gothic"
    FONT_MONO = "Consolas"
    FONT_SIZE_S = 9
    FONT_SIZE_M = 10
    FONT_SIZE_L = 12
    FONT_SIZE_XL = 16
    FONT_SIZE_XXL = 24

    @staticmethod
    def apply_dark_palette(app: QApplication):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(Theme.BG_PRIMARY))
        palette.setColor(QPalette.WindowText, QColor(Theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Base, QColor(Theme.BG_SECONDARY))
        palette.setColor(QPalette.AlternateBase, QColor(Theme.BG_TERTIARY))
        palette.setColor(QPalette.ToolTipBase, QColor(Theme.BG_CARD))
        palette.setColor(QPalette.ToolTipText, QColor(Theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Text, QColor(Theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Button, QColor(Theme.BG_TERTIARY))
        palette.setColor(QPalette.ButtonText, QColor(Theme.TEXT_PRIMARY))
        palette.setColor(QPalette.BrightText, QColor(Theme.ACCENT))
        palette.setColor(QPalette.Link, QColor(Theme.ACCENT))
        palette.setColor(QPalette.Highlight, QColor(Theme.ACCENT))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)

    STYLESHEET = f"""
        QMainWindow {{ background-color: {BG_PRIMARY}; }}
        QDockWidget {{ 
            color: {TEXT_PRIMARY}; 
            titlebar-close-icon: none;
            font-size: {FONT_SIZE_M}px;
        }}
        QDockWidget::title {{
            background: {BG_TERTIARY};
            padding: 6px;
            border-bottom: 1px solid #30363d;
        }}
        QTabWidget::pane {{ border: 1px solid #30363d; background: {BG_SECONDARY}; }}
        QTabBar::tab {{
            background: {BG_TERTIARY}; color: {TEXT_SECONDARY};
            padding: 6px 16px; border: 1px solid #30363d;
            border-bottom: none; border-top-left-radius: 4px;
            border-top-right-radius: 4px; margin-right: 2px;
        }}
        QTabBar::tab:selected {{ 
            background: {BG_SECONDARY}; color: {TEXT_PRIMARY};
            border-bottom: 2px solid {ACCENT};
        }}
        QTreeWidget {{ 
            background: {BG_SECONDARY}; color: {TEXT_PRIMARY};
            border: none; font-size: {FONT_SIZE_M}px;
        }}
        QTreeWidget::item {{ padding: 3px 0px; }}
        QTreeWidget::item:selected {{ background: {BG_TERTIARY}; }}
        QTableView {{
            background: {BG_SECONDARY}; color: {TEXT_PRIMARY};
            gridline-color: #21262d; border: none;
            selection-background-color: {BG_TERTIARY};
            font-size: {FONT_SIZE_M}px;
        }}
        QHeaderView::section {{
            background: {BG_TERTIARY}; color: {TEXT_SECONDARY};
            padding: 4px 8px; border: none;
            border-right: 1px solid #30363d;
            border-bottom: 1px solid #30363d;
            font-weight: bold; font-size: {FONT_SIZE_S}px;
        }}
        QGroupBox {{
            color: {TEXT_SECONDARY}; border: 1px solid #30363d;
            border-radius: 6px; margin-top: 12px; padding-top: 16px;
            font-weight: bold;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
        QLabel {{ color: {TEXT_PRIMARY}; }}
        QPushButton {{
            background: {BG_TERTIARY}; color: {TEXT_PRIMARY};
            border: 1px solid #30363d; border-radius: 4px;
            padding: 5px 12px; font-size: {FONT_SIZE_M}px;
        }}
        QPushButton:hover {{ background: #30363d; border-color: {ACCENT}; }}
        QPushButton:pressed {{ background: #0d1117; }}
        QPushButton#emergencyBtn {{ background: #7f1d1d; border-color: {STATUS_ERROR}; }}
        QPushButton#emergencyBtn:hover {{ background: {STATUS_ERROR}; }}
        QTextEdit {{
            background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
            border: 1px solid #30363d; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_S}px;
        }}
        QProgressBar {{
            background: {BG_TERTIARY}; border: none; border-radius: 3px;
            text-align: center; color: {TEXT_PRIMARY}; height: 8px;
        }}
        QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
        QStatusBar {{ background: {BG_TERTIARY}; color: {TEXT_SECONDARY}; }}
        QMenuBar {{ background: {BG_TERTIARY}; color: {TEXT_PRIMARY}; }}
        QMenuBar::item:selected {{ background: #30363d; }}
        QMenu {{ background: {BG_SECONDARY}; color: {TEXT_PRIMARY}; border: 1px solid #30363d; }}
        QMenu::item:selected {{ background: {BG_TERTIARY}; }}
        QToolBar {{ background: {BG_TERTIARY}; border-bottom: 1px solid #30363d; spacing: 4px; }}
        QSplitter::handle {{ background: #30363d; }}
        QMdiArea {{ background: {BG_PRIMARY}; }}
        QMdiSubWindow {{ background: {BG_SECONDARY}; }}
        QDoubleSpinBox, QSpinBox, QComboBox {{
            background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
            border: 1px solid #30363d; border-radius: 3px; padding: 3px;
        }}
        QScrollBar:vertical {{
            background: {BG_PRIMARY}; width: 8px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #30363d; border-radius: 4px; min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


# ═══════════════════════════════════════════════════════════════════
# SECTION 1: 데이터 모델 (불변 — 모든 패널이 참조)
# ═══════════════════════════════════════════════════════════════════

class UniverseTableModel(QAbstractTableModel):
    """유니버스 종목 그리드 — 50종목 × 15컬럼 실시간 갱신"""
    COLUMNS = [
        'FRS순위', '코드', '종목명', '현재가', '등락률%', '거래대금(억)',
        'TES', 'UCS', 'FRS', 'R1', 'R2', 'R3',
        '축수', '상태', '섹터'
    ]
    COL_WIDTHS = [50, 70, 100, 80, 70, 85, 60, 55, 55, 50, 50, 50, 40, 60, 80]

    def __init__(self):
        super().__init__()
        self._data: List[list] = []
        self._colors: Dict[int, Dict[int, QColor]] = {}

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole:
            val = self._data[row][col]
            if col == 3:  # 현재가
                return f"{val:,.0f}"
            elif col == 4:  # 등락률
                return f"{val:+.2f}%"
            elif col == 5:  # 거래대금
                return f"{val:,.1f}"
            elif col in (6, 7, 8):  # TES/UCS/FRS
                return f"{val:.3f}"
            elif col in (9, 10, 11):  # R1/R2/R3
                return f"{val:.2f}"
            return val
        elif role == Qt.ForegroundRole:
            if col == 4:  # 등락률 색상
                val = self._data[row][col]
                return QColor(Theme.BULL if val > 0 else Theme.BEAR if val < 0 else Theme.TEXT_MUTED)
            if col == 13:  # 상태 색상
                status = self._data[row][col]
                if status == 'ENTRY': return QColor(Theme.BULL)
                elif status == 'WATCH': return QColor(Theme.STATUS_WARN)
                elif status == 'EXIT': return QColor(Theme.BEAR)
                return QColor(Theme.TEXT_MUTED)
        elif role == Qt.TextAlignmentRole:
            if col in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        elif role == Qt.BackgroundRole:
            if row in self._colors and col in self._colors[row]:
                return self._colors[row][col]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def bulk_update(self, new_data: List[list], highlights: Dict = None):
        self.beginResetModel()
        self._data = new_data
        self._colors = highlights or {}
        self.endResetModel()

    def get_stock_code(self, row: int) -> str:
        if 0 <= row < len(self._data):
            return self._data[row][1]
        return ""


class PositionTableModel(QAbstractTableModel):
    """보유현황 모델"""
    COLUMNS = [
        '코드', '종목명', '수량', '평균단가', '현재가', '수익률%',
        '평가손익', '손절가', '익절단계', 'TES현재'
    ]

    def __init__(self):
        super().__init__()
        self._data: List[list] = []

    def rowCount(self, parent=QModelIndex()): return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole:
            val = self._data[row][col]
            if col in (3, 4, 7):
                return f"{val:,.0f}"
            elif col == 5:
                return f"{val:+.2f}%"
            elif col == 6:
                return f"{val:+,.0f}"
            elif col == 9:
                return f"{val:.3f}"
            return val
        elif role == Qt.ForegroundRole:
            if col in (5, 6):
                val = self._data[row][col]
                return QColor(Theme.BULL if val > 0 else Theme.BEAR if val < 0 else Theme.TEXT_MUTED)
        elif role == Qt.TextAlignmentRole:
            if col in (2, 3, 4, 5, 6, 7, 9):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def bulk_update(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()


class PendingTableModel(QAbstractTableModel):
    """미체결 모델"""
    COLUMNS = ['주문번호', '코드', '종목명', '구분', '주문가', '주문수량', '미체결', '상태']

    def __init__(self):
        super().__init__()
        self._data: List[list] = []

    def rowCount(self, parent=QModelIndex()): return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        if role == Qt.DisplayRole:
            val = self._data[index.row()][index.column()]
            if index.column() in (4,):
                return f"{val:,.0f}"
            return val
        elif role == Qt.ForegroundRole:
            if index.column() == 3:
                val = self._data[index.row()][3]
                return QColor(Theme.BULL if val == '매수' else Theme.BEAR)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def bulk_update(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()


# ═══════════════════════════════════════════════════════════════════
# SECTION 2: 커스텀 위젯 (불변)
# ═══════════════════════════════════════════════════════════════════

class StatusIndicator(QWidget):
    """연결 상태 원형 표시등"""
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._status = 'off'
        self.setFixedSize(110, 32)

    def set_status(self, status: str):
        self._status = status
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = {
            'ok': Theme.STATUS_OK, 'warn': Theme.STATUS_WARN,
            'error': Theme.STATUS_ERROR, 'off': Theme.STATUS_OFF
        }
        color = QColor(colors.get(self._status, Theme.STATUS_OFF))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(6, 10, 12, 12)
        painter.setPen(QColor(Theme.TEXT_PRIMARY))
        painter.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S))
        painter.drawText(24, 6, 80, 20, Qt.AlignLeft | Qt.AlignVCenter, self._label)
        painter.end()


class ScoreGauge(QWidget):
    """TES/UCS/FRS 수직 게이지 바"""
    def __init__(self, label: str, color: str, max_val: float = 3.0, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._max = max_val
        self.setFixedSize(60, 90)

    def set_value(self, val: float):
        self._value = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bar_x, bar_w = 18, 24
        bar_top, bar_bottom = 8, h - 22
        bar_h = bar_bottom - bar_top

        # 배경 바
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Theme.BG_TERTIARY))
        painter.drawRoundedRect(bar_x, bar_top, bar_w, bar_h, 3, 3)

        # 값 바
        ratio = min(self._value / self._max, 1.0) if self._max > 0 else 0
        fill_h = int(bar_h * ratio)
        painter.setBrush(QColor(self._color))
        painter.drawRoundedRect(bar_x, bar_bottom - fill_h, bar_w, fill_h, 3, 3)

        # 값 텍스트
        painter.setPen(QColor(Theme.TEXT_PRIMARY))
        painter.setFont(QFont(Theme.FONT_MONO, 8, QFont.Bold))
        painter.drawText(0, bar_top - 2, w, 12, Qt.AlignHCenter, f"{self._value:.2f}")

        # 라벨
        painter.setFont(QFont(Theme.FONT_FAMILY, 7))
        painter.setPen(QColor(Theme.TEXT_SECONDARY))
        painter.drawText(0, h - 16, w, 14, Qt.AlignHCenter, self._label)
        painter.end()


class PhaseTimeline(QWidget):
    """장중 Phase 진행 바"""
    PHASES = ['Pre', '09:00', '09:15\nPhase1', '09:30\nPhase2', 'Active', '14:30', '15:30\nClose']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self.setFixedHeight(48)
        self.setMinimumWidth(300)

    def set_phase(self, idx: int):
        self._current = idx
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self.PHASES)
        step = (w - 40) / (n - 1)

        # 라인
        y = 16
        painter.setPen(QPen(QColor(Theme.TEXT_MUTED), 2))
        painter.drawLine(20, y, w - 20, y)

        # 활성 라인
        if self._current > 0:
            painter.setPen(QPen(QColor(Theme.ACCENT), 3))
            painter.drawLine(20, y, int(20 + step * self._current), y)

        # 노드
        for i, phase in enumerate(self.PHASES):
            x = int(20 + step * i)
            if i < self._current:
                painter.setBrush(QColor(Theme.ACCENT))
            elif i == self._current:
                painter.setBrush(QColor(Theme.GOLD))
            else:
                painter.setBrush(QColor(Theme.BG_TERTIARY))
            painter.setPen(QPen(QColor(Theme.ACCENT if i <= self._current else Theme.TEXT_MUTED), 2))
            painter.drawEllipse(x - 6, y - 6, 12, 12)

            painter.setPen(QColor(Theme.TEXT_PRIMARY if i == self._current else Theme.TEXT_SECONDARY))
            painter.setFont(QFont(Theme.FONT_FAMILY, 7))
            lines = phase.split('\n')
            for li, line in enumerate(lines):
                painter.drawText(x - 30, y + 10 + li * 11, 60, 12, Qt.AlignHCenter, line)
        painter.end()


class InfoCard(QFrame):
    """대시보드 정보 카드"""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            InfoCard {{ 
                background: {Theme.BG_CARD}; 
                border: 1px solid #30363d; 
                border-radius: 8px; 
            }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S))
        self._title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._layout.addWidget(self._title)

        self._content_layout = QVBoxLayout()
        self._content_layout.setSpacing(2)
        self._layout.addLayout(self._content_layout)

    def add_value_label(self, name: str) -> QLabel:
        lbl = QLabel("--")
        lbl.setObjectName(name)
        lbl.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_L, QFont.Bold))
        self._content_layout.addWidget(lbl)
        return lbl

    def add_sub_label(self, name: str) -> QLabel:
        lbl = QLabel("")
        lbl.setObjectName(name)
        lbl.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S))
        lbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._content_layout.addWidget(lbl)
        return lbl


# ═══════════════════════════════════════════════════════════════════
# SECTION 3: 패널 구현 (불변)
# ═══════════════════════════════════════════════════════════════════

class DashboardBar(QWidget):
    """[C] 메인 대시보드 상단 바"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # ── 시장현황 ──
        self.market_card = InfoCard("시장 현황")
        self.lbl_kospi = self.market_card.add_value_label("kospi")
        self.lbl_kosdaq = self.market_card.add_sub_label("kosdaq")
        self.lbl_market_detail = self.market_card.add_sub_label("market_detail")
        layout.addWidget(self.market_card, 2)

        # ── TES 상위 5 ──
        self.tes_card = InfoCard("TES 상위 5종목")
        self.tes_labels: List[QLabel] = []
        for i in range(5):
            lbl = QLabel(f"#{i+1}  ------  ---  TES:---")
            lbl.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
            self.tes_card._content_layout.addWidget(lbl)
            self.tes_labels.append(lbl)
        layout.addWidget(self.tes_card, 3)

        # ── 시스템 상태 ──
        self.system_card = InfoCard("시스템 상태")
        status_row = QHBoxLayout()
        self.ind_cybos = StatusIndicator("CybosPlus")
        self.ind_kiwoom = StatusIndicator("Kiwoom")
        self.ind_db = StatusIndicator("MySQL DB")
        status_row.addWidget(self.ind_cybos)
        status_row.addWidget(self.ind_kiwoom)
        status_row.addWidget(self.ind_db)
        self.system_card._content_layout.addLayout(status_row)
        self.lbl_api_calls = self.system_card.add_sub_label("api_calls")
        layout.addWidget(self.system_card, 2)

        # ── P&L 요약 ──
        self.pnl_card = InfoCard("당일 P&L")
        self.lbl_pnl_total = self.pnl_card.add_value_label("pnl_total")
        self.lbl_pnl_detail = self.pnl_card.add_sub_label("pnl_detail")
        self.lbl_pnl_winrate = self.pnl_card.add_sub_label("pnl_winrate")
        layout.addWidget(self.pnl_card, 2)

        # ── Phase 타임라인 ──
        self.phase_card = InfoCard("Phase")
        self.phase_timeline = PhaseTimeline()
        self.phase_card._content_layout.addWidget(self.phase_timeline)
        self.lbl_phase_time = self.phase_card.add_sub_label("phase_time")
        layout.addWidget(self.phase_card, 3)


class UniverseTree(QWidget):
    """[B] 유니버스 트리 네비게이션"""
    stock_selected = QtSignal(str)  # stock_code

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 상단 요약
        self.lbl_summary = QLabel("유니버스: 0종목 | 매매대상: 0종목")
        self.lbl_summary.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S, QFont.Bold))
        self.lbl_summary.setStyleSheet(
            f"background: {Theme.BG_TERTIARY}; padding: 6px; color: {Theme.TEXT_PRIMARY};")
        layout.addWidget(self.lbl_summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['종목/그룹', '등락률', 'TES', 'UCS'])
        self.tree.setColumnWidth(0, 130)
        self.tree.setColumnWidth(1, 55)
        self.tree.setColumnWidth(2, 50)
        self.tree.setColumnWidth(3, 45)
        self.tree.setIndentation(16)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

        # 주도섹터 영역
        self.sector_group = QGroupBox("주도 섹터/테마")
        sector_layout = QVBoxLayout(self.sector_group)
        self.sector_labels: List[QLabel] = []
        for _ in range(3):
            lbl = QLabel("--")
            lbl.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S))
            sector_layout.addWidget(lbl)
            self.sector_labels.append(lbl)
        layout.addWidget(self.sector_group)

    def _on_item_clicked(self, item, column):
        code = item.data(0, Qt.UserRole)
        if code:
            self.stock_selected.emit(code)

    def update_tree(self, universe_data: List[dict]):
        self.tree.clear()
        # 매매 대상
        target_root = QTreeWidgetItem(self.tree, ['▸ 매매대상 (상위 N)', '', '', ''])
        target_root.setFont(0, QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_S, QFont.Bold))
        target_root.setForeground(0, QColor(Theme.GOLD))

        # 축별 분류
        axis3 = QTreeWidgetItem(self.tree, ['▸ 3축 통과', '', '', ''])
        axis2 = QTreeWidgetItem(self.tree, ['▸ 2축 통과', '', '', ''])
        axis1 = QTreeWidgetItem(self.tree, ['▸ 1축 통과', '', '', ''])

        target_count = 0
        a3, a2, a1 = 0, 0, 0
        for d in sorted(universe_data, key=lambda x: x.get('frs', 0), reverse=True):
            item = QTreeWidgetItem([
                f"{d['code']} {d['name'][:6]}",
                f"{d['change']:+.1f}%",
                f"{d.get('tes', 0):.2f}",
                f"{d.get('ucs', 0):.2f}"
            ])
            item.setData(0, Qt.UserRole, d['code'])
            # 등락률 색
            item.setForeground(1, QColor(
                Theme.BULL if d['change'] > 0 else Theme.BEAR))

            axes = d.get('axes', 0)
            if d.get('is_target', False):
                target_root.addChild(item)
                target_count += 1
            elif axes >= 3:
                axis3.addChild(item)
                a3 += 1
            elif axes >= 2:
                axis2.addChild(item)
                a2 += 1
            else:
                axis1.addChild(item)
                a1 += 1

        target_root.setText(0, f'▸ 매매대상 ({target_count})')
        axis3.setText(0, f'▸ 3축 통과 ({a3})')
        axis2.setText(0, f'▸ 2축 통과 ({a2})')
        axis1.setText(0, f'▸ 1축 통과 ({a1})')

        total = target_count + a3 + a2 + a1
        self.lbl_summary.setText(f"유니버스: {total}종목 | 매매대상: {target_count}종목")

        self.tree.expandAll()


class StockDetailPanel(QWidget):
    """[E] 종목정보 + 분석 패널"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── 기본정보 ──
        info_group = QGroupBox("기본정보")
        info_layout = QGridLayout(info_group)
        info_layout.setSpacing(4)

        self.lbl_code = QLabel("------")
        self.lbl_code.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_XL, QFont.Bold))
        info_layout.addWidget(self.lbl_code, 0, 0, 1, 2)

        self.lbl_name = QLabel("종목명")
        self.lbl_name.setFont(QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_L))
        info_layout.addWidget(self.lbl_name, 1, 0, 1, 2)

        labels = ['현재가', '등락률', '시가총액', '거래대금']
        self.info_values = {}
        for i, l in enumerate(labels):
            r = 2 + i // 2
            c = (i % 2) * 2
            lbl = QLabel(l)
            lbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_S}px;")
            val = QLabel("--")
            val.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_M, QFont.Bold))
            info_layout.addWidget(lbl, r, c)
            info_layout.addWidget(val, r, c + 1)
            self.info_values[l] = val
        layout.addWidget(info_group)

        # ── 120틱 TES 분석 ──
        tes_group = QGroupBox("120틱 TES 분석")
        tes_layout = QVBoxLayout(tes_group)

        # 게이지 행
        gauge_row = QHBoxLayout()
        self.gauge_tes = ScoreGauge("TES", Theme.ACCENT, 3.0)
        self.gauge_ucs = ScoreGauge("UCS", Theme.ACCENT_SECONDARY, 1.0)
        self.gauge_frs = ScoreGauge("FRS", Theme.GOLD, 2.0)
        gauge_row.addWidget(self.gauge_tes)
        gauge_row.addWidget(self.gauge_ucs)
        gauge_row.addWidget(self.gauge_frs)
        gauge_row.addStretch()
        tes_layout.addLayout(gauge_row)

        # 수치 그리드
        tes_grid = QGridLayout()
        tes_fields = [
            ('AVG5D', '--'), ('PREV_D', '--'), ('TODAY_15M', '--'),
            ('R1', '--'), ('R2', '--'), ('R3', '--'),
            ('시가대비', '--'), ('TES Z', '--'), ('ATR₁₄', '--'),
        ]
        self.tes_values = {}
        for i, (label, default) in enumerate(tes_fields):
            r, c = i // 3, (i % 3) * 2
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_S}px;")
            val = QLabel(default)
            val.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
            tes_grid.addWidget(lbl, r, c)
            tes_grid.addWidget(val, r, c + 1)
            self.tes_values[label] = val
        tes_layout.addLayout(tes_grid)
        layout.addWidget(tes_group)

        # ── 3축 UCS 상세 ──
        ucs_group = QGroupBox("3축 UCS 상세")
        ucs_layout = QVBoxLayout(ucs_group)
        self.axis_bars = {}
        for axis_name, axis_color, axis_label in [
            ('HMS', Theme.AXIS1_HMS, '축1: 강세이력'),
            ('BMS', Theme.AXIS2_BMS, '축2: 돌파모멘텀'),
            ('SLS', Theme.AXIS3_SLS, '축3: 섹터주도'),
        ]:
            row = QHBoxLayout()
            name_lbl = QLabel(axis_label)
            name_lbl.setFixedWidth(90)
            name_lbl.setStyleSheet(f"color: {axis_color}; font-size: {Theme.FONT_SIZE_S}px; font-weight: bold;")
            row.addWidget(name_lbl)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFixedHeight(14)
            bar.setStyleSheet(f"""
                QProgressBar {{ background: {Theme.BG_TERTIARY}; border: none; border-radius: 3px; }}
                QProgressBar::chunk {{ background: {axis_color}; border-radius: 3px; }}
            """)
            row.addWidget(bar, 1)

            val_lbl = QLabel("0.00")
            val_lbl.setFixedWidth(40)
            val_lbl.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
            row.addWidget(val_lbl)

            ucs_layout.addLayout(row)
            self.axis_bars[axis_name] = (bar, val_lbl)
        layout.addWidget(ucs_group)

        # ── 재무/수급 ──
        fund_group = QGroupBox("재무·수급")
        fund_layout = QGridLayout(fund_group)
        fund_fields = ['EPS', 'PER', '컨센서스', '기관5일', '외인5일']
        self.fund_values = {}
        for i, f in enumerate(fund_fields):
            r, c = i // 2, (i % 2) * 2
            lbl = QLabel(f)
            lbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_S}px;")
            val = QLabel("--")
            val.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
            fund_layout.addWidget(lbl, r, c)
            fund_layout.addWidget(val, r, c + 1)
            self.fund_values[f] = val
        layout.addWidget(fund_group)

        layout.addStretch()

    def update_stock(self, data: dict):
        self.lbl_code.setText(data.get('code', '------'))
        self.lbl_name.setText(data.get('name', '--'))
        price = data.get('price', 0)
        change = data.get('change', 0)
        self.info_values['현재가'].setText(f"{price:,.0f}")
        self.info_values['현재가'].setStyleSheet(
            f"color: {Theme.BULL if change > 0 else Theme.BEAR}; font-weight: bold;")
        self.info_values['등락률'].setText(f"{change:+.2f}%")
        self.info_values['등락률'].setStyleSheet(
            f"color: {Theme.BULL if change > 0 else Theme.BEAR};")
        self.info_values['시가총액'].setText(data.get('market_cap', '--'))
        self.info_values['거래대금'].setText(data.get('trade_value', '--'))

        self.gauge_tes.set_value(data.get('tes', 0))
        self.gauge_ucs.set_value(data.get('ucs', 0))
        self.gauge_frs.set_value(data.get('frs', 0))

        for key in ('AVG5D', 'PREV_D', 'TODAY_15M', 'R1', 'R2', 'R3', '시가대비', 'TES Z', 'ATR₁₄'):
            if key in data and key in self.tes_values:
                self.tes_values[key].setText(str(data[key]))

        for axis in ('HMS', 'BMS', 'SLS'):
            if axis in data:
                val = data[axis]
                bar, lbl = self.axis_bars[axis]
                bar.setValue(int(min(val * 100, 100)))
                lbl.setText(f"{val:.2f}")


class BottomPanel(QTabWidget):
    """[F] 하단 탭 패널"""
    def __init__(self, parent=None):
        super().__init__(parent)

        # F-1: 보유현황
        self.position_model = PositionTableModel()
        self.position_view = self._make_table(self.position_model)
        self.addTab(self.position_view, "보유현황")

        # F-2: 미체결
        self.pending_model = PendingTableModel()
        self.pending_view = self._make_table(self.pending_model)
        self.addTab(self.pending_view, "미체결")

        # F-3: 체결이력
        self.execution_log = QTextEdit()
        self.execution_log.setReadOnly(True)
        self.addTab(self.execution_log, "체결이력")

        # F-4: 실시간로그
        self.realtime_log = QTextEdit()
        self.realtime_log.setReadOnly(True)
        self.addTab(self.realtime_log, "실시간로그")

        # F-5: 설정
        self.settings_widget = self._build_settings()
        self.addTab(self.settings_widget, "설정")

        # F-6: 결과
        self.result_widget = self._build_result()
        self.addTab(self.result_widget, "결과")

    def _make_table(self, model) -> QTableView:
        tv = QTableView()
        tv.setModel(model)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SingleSelection)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.verticalHeader().setDefaultSectionSize(24)
        tv.verticalHeader().setVisible(False)
        return tv

    def _build_settings(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        # TES 파라미터
        tes_grp = QGroupBox("TES 파라미터")
        tes_form = QFormLayout(tes_grp)
        self.spin_w1 = QDoubleSpinBox(); self.spin_w1.setRange(0, 1); self.spin_w1.setValue(0.40); self.spin_w1.setSingleStep(0.05)
        self.spin_w2 = QDoubleSpinBox(); self.spin_w2.setRange(0, 1); self.spin_w2.setValue(0.25); self.spin_w2.setSingleStep(0.05)
        self.spin_w3 = QDoubleSpinBox(); self.spin_w3.setRange(0, 1); self.spin_w3.setValue(0.15); self.spin_w3.setSingleStep(0.05)
        self.spin_w4 = QDoubleSpinBox(); self.spin_w4.setRange(0, 1); self.spin_w4.setValue(0.20); self.spin_w4.setSingleStep(0.05)
        tes_form.addRow("W1 (R1 가중)", self.spin_w1)
        tes_form.addRow("W2 (R2 가중)", self.spin_w2)
        tes_form.addRow("W3 (R3 가중)", self.spin_w3)
        tes_form.addRow("W4 (가격모멘텀)", self.spin_w4)
        layout.addWidget(tes_grp)

        # 유니버스 파라미터
        uni_grp = QGroupBox("유니버스 필터")
        uni_form = QFormLayout(uni_grp)
        self.spin_ucs_min = QDoubleSpinBox(); self.spin_ucs_min.setRange(0, 1); self.spin_ucs_min.setValue(0.45); self.spin_ucs_min.setSingleStep(0.05)
        self.spin_min_trade = QSpinBox(); self.spin_min_trade.setRange(10, 500); self.spin_min_trade.setValue(30); self.spin_min_trade.setSuffix("억")
        self.spin_n_stocks = QSpinBox(); self.spin_n_stocks.setRange(1, 20); self.spin_n_stocks.setValue(5)
        uni_form.addRow("UCS 최소", self.spin_ucs_min)
        uni_form.addRow("거래대금 최소", self.spin_min_trade)
        uni_form.addRow("상위 N종목", self.spin_n_stocks)
        layout.addWidget(uni_grp)

        # 리스크 파라미터
        risk_grp = QGroupBox("리스크 관리")
        risk_form = QFormLayout(risk_grp)
        self.spin_stop_loss = QDoubleSpinBox(); self.spin_stop_loss.setRange(0.5, 10); self.spin_stop_loss.setValue(2.0); self.spin_stop_loss.setSuffix("%")
        self.spin_take1 = QDoubleSpinBox(); self.spin_take1.setRange(1, 30); self.spin_take1.setValue(7.0); self.spin_take1.setSuffix("%")
        self.spin_take2 = QDoubleSpinBox(); self.spin_take2.setRange(1, 50); self.spin_take2.setValue(10.0); self.spin_take2.setSuffix("%")
        self.spin_atr_mult = QDoubleSpinBox(); self.spin_atr_mult.setRange(0.5, 5); self.spin_atr_mult.setValue(2.0); self.spin_atr_mult.setSingleStep(0.1)
        self.spin_max_daily_loss = QDoubleSpinBox(); self.spin_max_daily_loss.setRange(1, 10); self.spin_max_daily_loss.setValue(3.0); self.spin_max_daily_loss.setSuffix("%")
        risk_form.addRow("손절 기본", self.spin_stop_loss)
        risk_form.addRow("1차 익절", self.spin_take1)
        risk_form.addRow("2차 익절", self.spin_take2)
        risk_form.addRow("ATR 배수", self.spin_atr_mult)
        risk_form.addRow("일일 최대 손실", self.spin_max_daily_loss)
        layout.addWidget(risk_grp)

        return w

    def _build_result(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # 성과 차트 (pyqtgraph)
        self.result_chart = pg.PlotWidget()
        self.result_chart.setBackground(Theme.BG_SECONDARY)
        self.result_chart.setTitle("당일 누적 손익", color=Theme.TEXT_PRIMARY, size="10pt")
        self.result_chart.setLabel('left', '손익(원)', color=Theme.TEXT_SECONDARY)
        self.result_chart.setLabel('bottom', '시간', color=Theme.TEXT_SECONDARY)
        self.result_chart.showGrid(x=True, y=True, alpha=0.1)
        self.pnl_curve = self.result_chart.plot(pen=pg.mkPen(Theme.ACCENT, width=2))
        self.pnl_data_x = []
        self.pnl_data_y = []
        layout.addWidget(self.result_chart, 2)

        # 성과 지표 요약
        metrics_row = QHBoxLayout()
        self.result_labels = {}
        for name in ['CAGR', 'MDD', 'Sharpe', '승률', '총거래', '평균손익']:
            card = InfoCard(name)
            lbl = card.add_value_label(name)
            metrics_row.addWidget(card)
            self.result_labels[name] = lbl
        layout.addLayout(metrics_row, 1)
        return w

    def append_log(self, level: str, msg: str):
        colors = {'INFO': Theme.TEXT_PRIMARY, 'WARN': Theme.STATUS_WARN,
                  'ERROR': Theme.STATUS_ERROR, 'SIGNAL': Theme.ACCENT,
                  'TRADE': Theme.GOLD}
        color = colors.get(level, Theme.TEXT_PRIMARY)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self.realtime_log.append(
            f'<span style="color:{Theme.TEXT_MUTED}">{timestamp}</span> '
            f'<span style="color:{color}">[{level}]</span> '
            f'<span style="color:{Theme.TEXT_PRIMARY}">{msg}</span>'
        )

    def append_execution(self, msg: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.execution_log.append(f'{timestamp}  {msg}')


# ═══════════════════════════════════════════════════════════════════
# SECTION 4: MDI 워크스페이스 + 차트 (불변)
# ═══════════════════════════════════════════════════════════════════

class ChartSubWindow(QMdiSubWindow):
    """120틱/일봉 캔들차트 서브윈도우 (pyqtgraph 기반)"""
    def __init__(self, stock_code: str, chart_type: str = "120tick", parent=None):
        super().__init__(parent)
        self.stock_code = stock_code
        self.chart_type = chart_type
        self.setWindowTitle(f"{stock_code} [{chart_type}]")
        self.setMinimumSize(400, 300)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 상단 정보 바
        info_bar = QHBoxLayout()
        self.lbl_info = QLabel(f"{stock_code} | {chart_type}")
        self.lbl_info.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S, QFont.Bold))
        self.lbl_price = QLabel("--")
        self.lbl_price.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_M, QFont.Bold))
        self.lbl_change = QLabel("--")
        self.lbl_change.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
        info_bar.addWidget(self.lbl_info)
        info_bar.addStretch()
        info_bar.addWidget(self.lbl_price)
        info_bar.addWidget(self.lbl_change)
        layout.addLayout(info_bar)

        # 캔들 차트 (pyqtgraph)
        self.chart_widget = pg.PlotWidget()
        self.chart_widget.setBackground(Theme.BG_PRIMARY)
        self.chart_widget.showGrid(x=True, y=True, alpha=0.08)
        self.chart_widget.setLabel('right', '가격', color=Theme.TEXT_SECONDARY)
        self.chart_widget.hideAxis('left')

        # 캔들스틱 데이터
        self._candles = []
        self._candle_items = []
        self._max_candles = 240
        layout.addWidget(self.chart_widget, 4)

        # 거래량 차트
        self.volume_widget = pg.PlotWidget()
        self.volume_widget.setBackground(Theme.BG_PRIMARY)
        self.volume_widget.setMaximumHeight(80)
        self.volume_widget.showGrid(x=True, y=False, alpha=0.08)
        self.volume_widget.hideAxis('left')
        self.volume_bars = pg.BarGraphItem(x=[], height=[], width=0.6, brush=Theme.ACCENT)
        self.volume_widget.addItem(self.volume_bars)
        layout.addWidget(self.volume_widget, 1)

        # 지표 오버레이 (이동평균)
        self.ma_lines = {}
        for period, color in [(5, '#ef4444'), (20, '#eab308'), (60, '#22c55e')]:
            pen = pg.mkPen(color, width=1)
            line = self.chart_widget.plot(pen=pen, name=f"MA{period}")
            self.ma_lines[period] = {'line': line, 'data': []}

        # 매매 마커
        self.entry_markers = pg.ScatterPlotItem(size=10, symbol='t1',
                                                 brush=pg.mkBrush(Theme.BULL))
        self.exit_markers = pg.ScatterPlotItem(size=10, symbol='t',
                                                brush=pg.mkBrush(Theme.BEAR))
        self.chart_widget.addItem(self.entry_markers)
        self.chart_widget.addItem(self.exit_markers)

        self.setWidget(container)

    def add_candle(self, o, h, l, c, v, idx):
        """캔들 추가 (실시간)"""
        self._candles.append({'o': o, 'h': h, 'l': l, 'c': c, 'v': v, 'idx': idx})

        color = Theme.BULL if c >= o else Theme.BEAR
        # 심지
        wick = pg.PlotDataItem([idx, idx], [l, h],
                               pen=pg.mkPen(color, width=1))
        # 몸통
        body_bottom = min(o, c)
        body_top = max(o, c)
        body = pg.BarGraphItem(x=[idx], height=[body_top - body_bottom],
                               width=0.6, y0=body_bottom,
                               brush=pg.mkBrush(color))
        self.chart_widget.addItem(wick)
        self.chart_widget.addItem(body)
        self._candle_items.append((wick, body))

        while len(self._candles) > self._max_candles:
            self._candles.pop(0)
            old_wick, old_body = self._candle_items.pop(0)
            self.chart_widget.removeItem(old_wick)
            self.chart_widget.removeItem(old_body)

        # 거래량
        self.volume_bars.setOpts(
            x=[c_['idx'] for c_ in self._candles],
            height=[c_['v'] for c_ in self._candles],
            width=0.6
        )

        # MA 갱신
        closes = [c_['c'] for c_ in self._candles]
        for period, ma_info in self.ma_lines.items():
            if len(closes) >= period:
                ma_vals = np.convolve(closes, np.ones(period) / period, 'valid')
                x_vals = list(range(period - 1, len(closes)))
                ma_info['line'].setData(x_vals, ma_vals)

        # 가격 표시 갱신
        self.lbl_price.setText(f"{c:,.0f}")
        change_pct = (c - o) / o * 100 if o != 0 else 0
        self.lbl_change.setText(f"{change_pct:+.2f}%")
        self.lbl_change.setStyleSheet(
            f"color: {Theme.BULL if change_pct > 0 else Theme.BEAR};")

    def add_entry_marker(self, idx, price):
        spots = list(self.entry_markers.data['data']) if self.entry_markers.data.size else []
        self.entry_markers.addPoints([{'pos': (idx, price), 'size': 12,
                                       'symbol': 't1', 'brush': pg.mkBrush(Theme.BULL)}])

    def add_exit_marker(self, idx, price):
        self.exit_markers.addPoints([{'pos': (idx, price), 'size': 12,
                                      'symbol': 't', 'brush': pg.mkBrush(Theme.BEAR)}])


class TESHeatmapWindow(QMdiSubWindow):
    """TES 히트맵 서브윈도우"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TES Heatmap")
        self.setMinimumSize(500, 300)

        container = QWidget()
        layout = QVBoxLayout(container)

        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        layout.addWidget(self.image_view)
        self.setWidget(container)

    def update_heatmap(self, data: np.ndarray, labels: List[str] = None):
        self.image_view.setImage(data.T, autoRange=True, autoLevels=True)


# ═══════════════════════════════════════════════════════════════════
# SECTION 5: 더미 데이터 시뮬레이터 (테스트용 — 실전에서 Redis로 교체)
# ═══════════════════════════════════════════════════════════════════

class DummyDataSimulator:
    """50종목 실시간 더미 데이터 생성"""
    STOCK_NAMES = [
        '현대에이치티', '삼성전자', 'SK하이닉스', '에코프로', 'NAVER',
        '카카오', 'LG에너지', '셀트리온', '포스코홀딩', '삼성SDI',
        '기아', '현대차', 'KB금융', '신한지주', 'LG화학',
        '삼성바이오', '크래프톤', '현대모비스', '하이브', 'LG전자',
        '엔씨소프트', '두산에너빌', 'HD한국조선', '한화에어로', '레인보우로보',
        'HLB', '알테오젠', '리가켐바이오', '클래시스', '파마리서치',
        '에이피알', '씨앤씨인터', '한미반도체', 'ISC', '넥스틴',
        'HPSP', '유진테크', '피엔티', '테크윙', '이오테크닉스',
        '고영', '원익IPS', '주성엔지니어', '솔브레인', '동진쎄미',
        '리노공업', '코미코', '하나마이크론', '에스티아이', '월덱스',
    ]
    SECTORS = [
        '반도체', '반도체', '반도체', '2차전지', 'IT',
        'IT', '2차전지', '바이오', '철강', '2차전지',
        '자동차', '자동차', '금융', '금융', '화학',
        '바이오', '게임', '자동차', '엔터', '전자',
        '게임', '에너지', '조선', '방산', '로봇',
        '바이오', '바이오', '바이오', '의료기기', '바이오',
        '뷰티', '뷰티', '반도체장비', '반도체장비', '반도체장비',
        '반도체장비', '반도체장비', '반도체장비', '반도체장비', '반도체장비',
        '반도체장비', '반도체장비', '반도체장비', '반도체소재', '반도체소재',
        '반도체장비', '반도체소재', '반도체', '반도체장비', '반도체장비',
    ]

    def __init__(self, n=50):
        self.n = n
        self.stocks = []
        for i in range(n):
            base = random.randint(5000, 200000)
            self.stocks.append({
                'code': f'{60000 + i * 10:06d}',
                'name': self.STOCK_NAMES[i] if i < len(self.STOCK_NAMES) else f'종목{i}',
                'sector': self.SECTORS[i] if i < len(self.SECTORS) else '기타',
                'base_price': base,
                'price': base,
                'open_price': base,
                'volume_acc': 0,
                'tick_count': 0,
                'avg5d': random.randint(800, 2200),
                'prev_d': random.randint(700, 2500),
                'tes': random.uniform(0.3, 2.8),
                'ucs': random.uniform(0.2, 0.95),
                'frs': random.uniform(0.3, 1.8),
                'hms': random.uniform(0, 1),
                'bms': random.uniform(0, 1),
                'sls': random.uniform(0, 1),
                'axes': random.choice([1, 1, 2, 2, 2, 3, 3]),
                'candle_idx': 0,
            })
        # 상위 종목은 강세로 설정
        for s in self.stocks[:8]:
            s['tes'] = random.uniform(1.5, 3.0)
            s['ucs'] = random.uniform(0.6, 0.95)
            s['frs'] = random.uniform(1.0, 2.0)
            s['axes'] = 3

    def tick(self):
        """한 사이클 시뮬레이션"""
        for s in self.stocks:
            # 가격 랜덤워크
            change = random.gauss(0, 0.003)  # 0.3% std
            s['price'] = max(100, s['price'] * (1 + change))
            s['volume_acc'] += random.randint(100, 5000)
            s['tick_count'] += random.randint(0, 3)

            # TES/UCS 미세 변동
            s['tes'] = max(0, s['tes'] + random.gauss(0, 0.02))
            s['ucs'] = max(0, min(1, s['ucs'] + random.gauss(0, 0.005)))
            s['frs'] = max(0, s['frs'] + random.gauss(0, 0.015))

    def get_universe_grid(self) -> List[list]:
        """유니버스 그리드 데이터"""
        rows = []
        sorted_stocks = sorted(self.stocks, key=lambda x: x['frs'], reverse=True)
        for rank, s in enumerate(sorted_stocks, 1):
            change_pct = (s['price'] - s['open_price']) / s['open_price'] * 100
            trade_value = s['volume_acc'] * s['price'] / 1e8  # 억 단위
            r1 = s['tick_count'] / max(1, s['avg5d'] * 0.0385) if s['avg5d'] > 0 else 0
            r2 = s['tick_count'] / max(1, s['prev_d'] * 0.0385) if s['prev_d'] > 0 else 0
            r3 = s['prev_d'] / max(1, s['avg5d'])
            rows.append([
                rank, s['code'], s['name'], s['price'], change_pct,
                trade_value, s['tes'], s['ucs'], s['frs'],
                r1, r2, r3, s['axes'],
                'ENTRY' if rank <= 5 else 'WATCH' if rank <= 15 else 'IDLE',
                s['sector']
            ])
        return rows

    def get_universe_tree(self) -> List[dict]:
        result = []
        sorted_stocks = sorted(self.stocks, key=lambda x: x['frs'], reverse=True)
        for rank, s in enumerate(sorted_stocks, 1):
            change_pct = (s['price'] - s['open_price']) / s['open_price'] * 100
            result.append({
                'code': s['code'],
                'name': s['name'],
                'change': change_pct,
                'tes': s['tes'],
                'ucs': s['ucs'],
                'frs': s['frs'],
                'axes': s['axes'],
                'is_target': rank <= 5,
                'sector': s['sector'],
            })
        return result

    def get_stock_detail(self, code: str) -> dict:
        s = next((s for s in self.stocks if s['code'] == code), None)
        if not s:
            return {}
        change_pct = (s['price'] - s['open_price']) / s['open_price'] * 100
        return {
            'code': s['code'], 'name': s['name'],
            'price': s['price'], 'change': change_pct,
            'market_cap': f"{random.randint(500, 50000):,}억",
            'trade_value': f"{s['volume_acc'] * s['price'] / 1e8:,.1f}억",
            'tes': s['tes'], 'ucs': s['ucs'], 'frs': s['frs'],
            'AVG5D': f"{s['avg5d']:,}", 'PREV_D': f"{s['prev_d']:,}",
            'TODAY_15M': f"{s['tick_count']}", 'R1': f"{random.uniform(0.5, 3):.2f}",
            'R2': f"{random.uniform(0.5, 2.5):.2f}", 'R3': f"{random.uniform(0.6, 1.5):.2f}",
            '시가대비': f"{change_pct:+.2f}%", 'TES Z': f"{s['tes']:.3f}",
            'ATR₁₄': f"{random.uniform(100, 2000):.0f}",
            'HMS': s['hms'], 'BMS': s['bms'], 'SLS': s['sls'],
        }

    def get_positions(self) -> List[list]:
        positions = []
        for s in self.stocks[:3]:  # 상위 3종목 보유 시뮬
            avg = s['open_price'] * random.uniform(0.97, 1.03)
            qty = random.randint(10, 100)
            pnl_pct = (s['price'] - avg) / avg * 100
            pnl = (s['price'] - avg) * qty
            positions.append([
                s['code'], s['name'], qty, avg, s['price'],
                pnl_pct, pnl, avg * 0.97, '1차(50%)', s['tes']
            ])
        return positions

    def get_pending(self) -> List[list]:
        return [
            ['ORD001', self.stocks[3]['code'], self.stocks[3]['name'], '매수',
             self.stocks[3]['price'] * 0.99, 50, 50, '대기중'],
        ]

    def generate_candle(self, stock_idx: int):
        """차트용 캔들 생성"""
        s = self.stocks[stock_idx]
        s['candle_idx'] += 1
        o = s['price']
        h = o * random.uniform(1.0, 1.015)
        l = o * random.uniform(0.985, 1.0)
        c = random.uniform(l, h)
        v = random.randint(1000, 50000)
        s['price'] = c
        return o, h, l, c, v, s['candle_idx']


# ═══════════════════════════════════════════════════════════════════
# SECTION 6: 메인 윈도우 (불변 셸)
# ═══════════════════════════════════════════════════════════════════

class TESMainWindow(QMainWindow):
    """TES-Universe 트레이딩 플랫폼 메인 윈도우"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TES-Universe Trading Platform v1.0  |  What You See Is What You Trade")
        self.resize(1920, 1080)

        # 시뮬레이터
        self.sim = DummyDataSimulator(50)
        self.selected_stock = self.sim.stocks[0]['code']
        self.chart_windows: Dict[str, ChartSubWindow] = {}

        # 성능 측정
        self.perf_timer = QElapsedTimer()
        self.frame_times = []

        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()
        self._build_panels()
        self._setup_timers()

        # 초기 데이터 로드
        self._refresh_all()

    # ── 메뉴 ──
    def _build_menubar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("파일(&F)")
        file_menu.addAction("워크스페이스 저장", self._save_workspace)
        file_menu.addAction("워크스페이스 로드", self._load_workspace)
        file_menu.addSeparator()
        file_menu.addAction("종료", self.close)

        conn_menu = mb.addMenu("연결(&C)")
        conn_menu.addAction("Cybos 연결")
        conn_menu.addAction("Kiwoom 연결")
        conn_menu.addAction("DB 연결")

        strat_menu = mb.addMenu("전략(&S)")
        strat_menu.addAction("전략 로드")
        strat_menu.addAction("전략 편집기")
        strat_menu.addSeparator()
        strat_menu.addAction("백테스트 실행")

        uni_menu = mb.addMenu("유니버스(&U)")
        uni_menu.addAction("유니버스 편집")
        uni_menu.addAction("조건검색 동기화")

        trade_menu = mb.addMenu("매매(&T)")
        self.act_auto_start = trade_menu.addAction("자동매매 시작")
        self.act_auto_stop = trade_menu.addAction("자동매매 중지")
        self.act_auto_stop.setEnabled(False)
        trade_menu.addSeparator()
        trade_menu.addAction("수동매매 패널")
        trade_menu.addSeparator()
        act_emergency = trade_menu.addAction("긴급 전체청산")
        act_emergency.setShortcut("Ctrl+Shift+X")

        view_menu = mb.addMenu("보기(&V)")
        view_menu.addAction("기본 레이아웃", self._reset_layout)
        view_menu.addAction("차트 중심 레이아웃")
        view_menu.addSeparator()
        view_menu.addAction("야간모드 토글")

        tool_menu = mb.addMenu("도구(&O)")
        tool_menu.addAction("성능 모니터")
        tool_menu.addAction("데이터 무결성 검사")
        tool_menu.addAction("DB 유지보수")

    # ── 툴바 ──
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)

        tb.addWidget(QLabel("  모드: "))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["시뮬레이션", "페이퍼", "실전"])
        self.combo_mode.setFixedWidth(100)
        tb.addWidget(self.combo_mode)

        tb.addSeparator()
        self.btn_start = QPushButton("▶ 시작")
        self.btn_start.setStyleSheet(f"background: #14532d; color: {Theme.STATUS_OK}; font-weight: bold;")
        tb.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■ 중지")
        self.btn_stop.setStyleSheet(f"background: #7f1d1d; color: {Theme.STATUS_ERROR}; font-weight: bold;")
        self.btn_stop.setEnabled(False)
        tb.addWidget(self.btn_stop)

        tb.addSeparator()
        self.btn_emergency = QPushButton("긴급 전체청산")
        self.btn_emergency.setObjectName("emergencyBtn")
        tb.addWidget(self.btn_emergency)

        tb.addSeparator()
        tb.addWidget(QLabel("  차트: "))
        self.btn_add_chart = QPushButton("+ 120틱")
        self.btn_add_chart.clicked.connect(lambda: self._open_chart(self.selected_stock, "120tick"))
        tb.addWidget(self.btn_add_chart)

        self.btn_add_daily = QPushButton("+ 일봉")
        self.btn_add_daily.clicked.connect(lambda: self._open_chart(self.selected_stock, "daily"))
        tb.addWidget(self.btn_add_daily)

        self.btn_heatmap = QPushButton("+ 히트맵")
        self.btn_heatmap.clicked.connect(self._open_heatmap)
        tb.addWidget(self.btn_heatmap)

        tb.addSeparator()
        self.btn_tile = QPushButton("타일")
        self.btn_tile.clicked.connect(lambda: self.mdi_area.tileSubWindows())
        tb.addWidget(self.btn_tile)

        self.btn_cascade = QPushButton("캐스케이드")
        self.btn_cascade.clicked.connect(lambda: self.mdi_area.cascadeSubWindows())
        tb.addWidget(self.btn_cascade)

        self.btn_tab_mode = QPushButton("탭 모드")
        self.btn_tab_mode.clicked.connect(self._toggle_mdi_mode)
        tb.addWidget(self.btn_tab_mode)

        # 오른쪽 정렬: 성능 표시
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.lbl_perf = QLabel("PERF: --ms")
        self.lbl_perf.setFont(QFont(Theme.FONT_MONO, Theme.FONT_SIZE_S))
        self.lbl_perf.setStyleSheet(f"color: {Theme.STATUS_OK};")
        tb.addWidget(self.lbl_perf)

    # ── 상태바 ──
    def _build_statusbar(self):
        sb = self.statusBar()
        self.lbl_status_time = QLabel("")
        self.lbl_status_phase = QLabel("Phase: Pre-market")
        self.lbl_status_universe = QLabel("Universe: 0")
        self.lbl_status_target = QLabel("Target: 0")
        sb.addWidget(self.lbl_status_time, 1)
        sb.addWidget(self.lbl_status_phase)
        sb.addWidget(self.lbl_status_universe)
        sb.addWidget(self.lbl_status_target)

    # ── 패널 조립 ──
    def _build_panels(self):
        # [C] 대시보드 상단 (Dock)
        self.dashboard = DashboardBar()
        dock_dashboard = QDockWidget("대시보드", self)
        dock_dashboard.setObjectName("dock_dashboard")
        dock_dashboard.setWidget(self.dashboard)
        dock_dashboard.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.TopDockWidgetArea, dock_dashboard)

        # [B] 유니버스 트리 (좌측 Dock)
        self.universe_tree = UniverseTree()
        self.universe_tree.stock_selected.connect(self._on_stock_selected)
        dock_universe = QDockWidget("유니버스", self)
        dock_universe.setObjectName("dock_universe")
        dock_universe.setWidget(self.universe_tree)
        dock_universe.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_universe)

        # [D] MDI Workspace (중앙)
        self.mdi_area = QMdiArea()
        self.mdi_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mdi_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mdi_area.setBackground(QBrush(QColor(Theme.BG_PRIMARY)))
        self.setCentralWidget(self.mdi_area)

        # 초기 차트 2개
        self._open_chart(self.sim.stocks[0]['code'], "120tick")
        self._open_chart(self.sim.stocks[1]['code'], "120tick")
        QTimer.singleShot(100, self.mdi_area.tileSubWindows)

        # [E] 종목 상세 (우측 Dock)
        self.stock_detail = StockDetailPanel()
        dock_detail = QDockWidget("종목 분석", self)
        dock_detail.setObjectName("dock_detail")
        dock_detail.setWidget(self.stock_detail)
        dock_detail.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_detail)

        # [F] 하단 패널 (하단 Dock)
        self.bottom_panel = BottomPanel()
        dock_bottom = QDockWidget("매매·로그·설정", self)
        dock_bottom.setObjectName("dock_bottom")
        dock_bottom.setWidget(self.bottom_panel)
        dock_bottom.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock_bottom)

        # 유니버스 그리드 (MDI 내부 또는 독립)
        self.universe_model = UniverseTableModel()
        self.universe_grid = QTableView()
        self.universe_grid.setModel(self.universe_model)
        self.universe_grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.universe_grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.universe_grid.horizontalHeader().setStretchLastSection(True)
        self.universe_grid.verticalHeader().setDefaultSectionSize(22)
        self.universe_grid.verticalHeader().setVisible(False)
        self.universe_grid.setAlternatingRowColors(True)
        self.universe_grid.clicked.connect(self._on_grid_clicked)
        # 컬럼 폭 설정
        for i, w in enumerate(UniverseTableModel.COL_WIDTHS):
            self.universe_grid.setColumnWidth(i, w)

        dock_grid = QDockWidget("유니버스 그리드", self)
        dock_grid.setObjectName("dock_grid")
        dock_grid.setWidget(self.universe_grid)
        dock_grid.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock_grid)

        # 하단 독 탭화
        self.tabifyDockWidget(dock_bottom, dock_grid)
        dock_bottom.raise_()

    # ── 타이머 설정 ──
    def _setup_timers(self):
        # 그리드/대시보드: 200ms (초당 5회)
        self.timer_grid = QTimer()
        self.timer_grid.timeout.connect(self._update_grid)
        self.timer_grid.start(200)

        # 차트 캔들: 300ms
        self.timer_chart = QTimer()
        self.timer_chart.timeout.connect(self._update_charts)
        self.timer_chart.start(300)

        # 대시보드: 500ms
        self.timer_dashboard = QTimer()
        self.timer_dashboard.timeout.connect(self._update_dashboard)
        self.timer_dashboard.start(500)

        # 하단 패널: 1초
        self.timer_bottom = QTimer()
        self.timer_bottom.timeout.connect(self._update_bottom)
        self.timer_bottom.start(1000)

        # 상태바: 1초
        self.timer_status = QTimer()
        self.timer_status.timeout.connect(self._update_statusbar)
        self.timer_status.start(1000)

        # 트리: 2초
        self.timer_tree = QTimer()
        self.timer_tree.timeout.connect(self._update_tree)
        self.timer_tree.start(2000)

        # 성능 표시: 3초
        self.timer_perf = QTimer()
        self.timer_perf.timeout.connect(self._report_perf)
        self.timer_perf.start(3000)

        # 로그 메시지: 5초
        self.timer_log = QTimer()
        self.timer_log.timeout.connect(self._generate_log)
        self.timer_log.start(5000)

    # ── 데이터 갱신 ──
    def _refresh_all(self):
        self.sim.tick()
        self._update_grid()
        self._update_tree()
        self._update_dashboard()
        self._update_stock_detail()

    def _update_grid(self):
        self.perf_timer.start()
        self.sim.tick()
        data = self.sim.get_universe_grid()
        self.universe_model.bulk_update(data)
        elapsed = self.perf_timer.elapsed()
        self.frame_times.append(elapsed)

    def _update_charts(self):
        for code, cw in self.chart_windows.items():
            idx = next((i for i, s in enumerate(self.sim.stocks) if s['code'] == code), None)
            if idx is not None:
                o, h, l, c, v, ci = self.sim.generate_candle(idx)
                cw.add_candle(o, h, l, c, v, ci)

    def _update_dashboard(self):
        # 시장현황
        kospi = 2650 + random.uniform(-20, 20)
        kosdaq = 870 + random.uniform(-10, 10)
        self.dashboard.lbl_kospi.setText(f"KOSPI {kospi:,.2f}")
        self.dashboard.lbl_kospi.setStyleSheet(
            f"color: {Theme.BULL if random.random() > 0.5 else Theme.BEAR}; font-weight: bold;")
        self.dashboard.lbl_kosdaq.setText(
            f"KOSDAQ {kosdaq:,.2f}  ({random.uniform(-1.5, 1.5):+.2f}%)")
        self.dashboard.lbl_market_detail.setText(
            f"상승 {random.randint(400, 600)} | 하락 {random.randint(300, 500)} | "
            f"거래대금 {random.randint(8, 18):,}조")

        # TES 상위 5
        sorted_stocks = sorted(self.sim.stocks, key=lambda x: x['frs'], reverse=True)
        top_n = min(len(sorted_stocks), len(self.dashboard.tes_labels), 5)
        for i in range(top_n):
            s = sorted_stocks[i]
            change = (s['price'] - s['open_price']) / s['open_price'] * 100
            self.dashboard.tes_labels[i].setText(
                f"#{i+1}  {s['code']}  {s['name'][:6]:>6s}  "
                f"{change:+5.1f}%  TES:{s['tes']:.2f}")
            self.dashboard.tes_labels[i].setStyleSheet(
                f"color: {Theme.BULL if change > 0 else Theme.BEAR}; "
                f"font-family: {Theme.FONT_MONO};")
        for i in range(top_n, min(len(self.dashboard.tes_labels), 5)):
            self.dashboard.tes_labels[i].setText(f"#{i+1}  --  ------   +0.0%  TES:0.00")
            self.dashboard.tes_labels[i].setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO};")

        # 시스템 상태
        self.dashboard.ind_cybos.set_status('ok')
        self.dashboard.ind_kiwoom.set_status('ok')
        self.dashboard.ind_db.set_status('ok')
        self.dashboard.lbl_api_calls.setText(f"API: {random.randint(20, 80)}/100 (잔여: {random.randint(20, 80)})")

        # P&L
        pnl = random.uniform(-300000, 500000)
        self.dashboard.lbl_pnl_total.setText(f"{pnl:+,.0f}원")
        self.dashboard.lbl_pnl_total.setStyleSheet(
            f"color: {Theme.BULL if pnl > 0 else Theme.BEAR}; font-weight: bold;")
        self.dashboard.lbl_pnl_detail.setText(
            f"실현: {random.uniform(-100000, 200000):+,.0f}  미실현: {random.uniform(-200000, 300000):+,.0f}")
        self.dashboard.lbl_pnl_winrate.setText(f"승률: {random.uniform(40, 75):.1f}%  ({random.randint(3, 8)}전)")

        # Phase
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        if hour < 9:
            phase_idx = 0
        elif hour == 9 and minute < 15:
            phase_idx = 2
        elif hour == 9 and minute < 30:
            phase_idx = 3
        elif hour < 14 or (hour == 14 and minute < 30):
            phase_idx = 4
        elif hour < 15 or (hour == 15 and minute < 30):
            phase_idx = 5
        else:
            phase_idx = 6
        # 시뮬레이션: 4단계로 고정
        self.dashboard.phase_timeline.set_phase(4)
        self.dashboard.lbl_phase_time.setText(f"{now.strftime('%H:%M:%S')} | Active Trading")

        # 결과 차트 갱신
        self.bottom_panel.pnl_data_x.append(len(self.bottom_panel.pnl_data_x))
        self.bottom_panel.pnl_data_y.append(
            (self.bottom_panel.pnl_data_y[-1] if self.bottom_panel.pnl_data_y else 0)
            + random.uniform(-20000, 30000))
        self.bottom_panel.pnl_curve.setData(
            self.bottom_panel.pnl_data_x, self.bottom_panel.pnl_data_y)

    def _update_tree(self):
        tree_data = self.sim.get_universe_tree()
        self.universe_tree.update_tree(tree_data)
        # 섹터 정보 갱신
        sectors = {}
        for d in tree_data:
            sec = d.get('sector', '기타')
            if sec not in sectors:
                sectors[sec] = {'count': 0, 'total_change': 0}
            sectors[sec]['count'] += 1
            sectors[sec]['total_change'] += d['change']
        top_sectors = sorted(sectors.items(),
                             key=lambda x: x[1]['total_change'] / max(x[1]['count'], 1),
                             reverse=True)[:3]
        for i, (name, info) in enumerate(top_sectors):
            avg = info['total_change'] / max(info['count'], 1)
            self.universe_tree.sector_labels[i].setText(
                f"  {name} ({info['count']}종목) 평균 {avg:+.1f}%")
            self.universe_tree.sector_labels[i].setStyleSheet(
                f"color: {Theme.BULL if avg > 0 else Theme.BEAR};")

    def _update_bottom(self):
        self.bottom_panel.position_model.bulk_update(self.sim.get_positions())
        self.bottom_panel.pending_model.bulk_update(self.sim.get_pending())

    def _update_stock_detail(self):
        data = self.sim.get_stock_detail(self.selected_stock)
        if data:
            self.stock_detail.update_stock(data)

    def _update_statusbar(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.lbl_status_time.setText(f"  {now}")
        self.lbl_status_phase.setText(f"Phase: Active")
        total = len(self.sim.stocks)
        target = sum(1 for s in self.sim.stocks
                     if sorted(self.sim.stocks, key=lambda x: x['frs'], reverse=True).index(s) < 5)
        self.lbl_status_universe.setText(f"Universe: {total}")
        self.lbl_status_target.setText(f"Target: 5  ")

    def _report_perf(self):
        if self.frame_times:
            avg = sum(self.frame_times) / len(self.frame_times)
            p95 = sorted(self.frame_times)[int(len(self.frame_times) * 0.95)] if len(self.frame_times) > 1 else avg
            status = "PASS" if p95 <= 16 else "WARN" if p95 <= 50 else "FAIL"
            color = Theme.STATUS_OK if status == "PASS" else Theme.STATUS_WARN if status == "WARN" else Theme.STATUS_ERROR
            self.lbl_perf.setText(f"PERF avg:{avg:.1f}ms p95:{p95:.1f}ms [{status}]")
            self.lbl_perf.setStyleSheet(f"color: {color};")
            self.frame_times.clear()

    def _generate_log(self):
        levels = ['INFO', 'INFO', 'SIGNAL', 'WARN', 'TRADE']
        messages = [
            "유니버스 갱신 완료 (42종목)",
            "TES 재계산 완료 — 상위: 060000 (2.34)",
            "Phase2 진입 시그널: 060010 +4.2% TES=2.15",
            "API 호출 잔여 22/100 — 조절 필요",
            "매수 체결: 060000 현대에이치티 50주 @ 9,850",
        ]
        level = random.choice(levels)
        msg = random.choice(messages)
        self.bottom_panel.append_log(level, msg)

    # ── 이벤트 핸들러 ──
    def _on_stock_selected(self, code: str):
        self.selected_stock = code
        self._update_stock_detail()

    def _on_grid_clicked(self, index: QModelIndex):
        code = self.universe_model.get_stock_code(index.row())
        if code:
            self.selected_stock = code
            self._update_stock_detail()

    def _open_chart(self, code: str, chart_type: str):
        key = f"{code}_{chart_type}"
        if key not in self.chart_windows:
            cw = ChartSubWindow(code, chart_type)
            self.mdi_area.addSubWindow(cw)
            cw.show()
            self.chart_windows[key] = cw
            # 초기 캔들 50개 생성
            idx = next((i for i, s in enumerate(self.sim.stocks) if s['code'] == code), 0)
            for _ in range(50):
                o, h, l, c, v, ci = self.sim.generate_candle(idx)
                cw.add_candle(o, h, l, c, v, ci)
        else:
            self.chart_windows[key].setFocus()

    def _open_heatmap(self):
        hm = TESHeatmapWindow()
        self.mdi_area.addSubWindow(hm)
        hm.show()
        # 더미 히트맵 데이터
        data = np.random.rand(10, 5) * 3
        hm.update_heatmap(data)

    def _toggle_mdi_mode(self):
        if self.mdi_area.viewMode() == QMdiArea.SubWindowView:
            self.mdi_area.setViewMode(QMdiArea.TabbedView)
            self.mdi_area.setTabsClosable(True)
            self.mdi_area.setTabsMovable(True)
        else:
            self.mdi_area.setViewMode(QMdiArea.SubWindowView)

    # ── 워크스페이스 저장/복원 ──
    def _save_workspace(self):
        settings = QSettings("TES_Platform", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        self.bottom_panel.append_log("INFO", "워크스페이스 저장 완료")

    def _load_workspace(self):
        settings = QSettings("TES_Platform", "MainWindow")
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        self.bottom_panel.append_log("INFO", "워크스페이스 로드 완료")

    def _reset_layout(self):
        # 기본 레이아웃으로 리셋 — 모든 독 위젯을 원래 위치로
        for dock in self.findChildren(QDockWidget):
            dock.setFloating(False)
            dock.show()
        self.bottom_panel.append_log("INFO", "레이아웃 리셋 완료")

    def closeEvent(self, event):
        self._save_workspace()
        event.accept()


# ═══════════════════════════════════════════════════════════════════
# SECTION 7: 엔트리포인트
# ═══════════════════════════════════════════════════════════════════

def main():
    # OpenGL 가속 활성화 (pyqtgraph)
    pg.setConfigOptions(
        antialias=True,
        useOpenGL=True,
        enableExperimental=True
    )

    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    Theme.apply_dark_palette(app)
    app.setStyleSheet(Theme.STYLESHEET)

    # 폰트 설정
    font = QFont(Theme.FONT_FAMILY, Theme.FONT_SIZE_M)
    app.setFont(font)

    window = TESMainWindow()
    window.show()

    print("=" * 60)
    print("  TES-Universe Trading Platform v1.0")
    print("  'What You See Is What You Trade'")
    print("=" * 60)
    print("  [INFO] 더미 데이터 시뮬레이터 가동 중")
    print("  [INFO] 그리드: 200ms | 차트: 300ms | 대시보드: 500ms")
    print("  [INFO] 성능 측정이 툴바 우측에 표시됩니다")
    print("  [INFO] Ctrl+Shift+X: 긴급 전체청산")
    print("=" * 60)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
