"""流光笺 主界面 — 毛玻璃亚克力风格 + 圆角分区 + 滚轮时间日期选择器"""
import calendar
import ctypes
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
import winsound
from ctypes import wintypes
from datetime import date, timedelta
from tkinter import messagebox, ttk
from typing import Optional

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

from app.config import THEMES, load_config, save_config
from app.models import Task
from app.storage import TaskStore

# ═══════════════════════════════════════════════════════════════════════════════
# Windows DWM 亚克力毛玻璃效果（ctypes 调用系统 API）
# ═══════════════════════════════════════════════════════════════════════════════

_ACCENT_ENABLE_ACRYLICBLURBEHIND = 3
_ACCENT_ENABLE_BLURBEHIND = 2
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_ACRYLIC = 4
_DWMSBT_MAINWINDOW = 2
_WCA_ACCENT_POLICY = 19
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_int),
        ("AnimationId", ctypes.c_int),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_ACCENTPOLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _enable_acrylic(hwnd: int, gradient_color: int = 0x40FFFFFF) -> bool:
    """为指定窗口启用亚克力毛玻璃效果。"""
    try:
        dwmapi = ctypes.windll.dwmapi
        backdrop = ctypes.c_int(_DWMSBT_ACRYLIC)
        ret = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(backdrop),
            ctypes.sizeof(backdrop),
        )
        if ret == 0:
            return True
    except Exception:
        pass

    try:
        accent = _ACCENTPOLICY()
        accent.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = gradient_color
        data = _WINCOMPATTRDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.pointer(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(
            wintypes.HWND(hwnd), ctypes.pointer(data))
        return True
    except Exception:
        return False


def _disable_acrylic(hwnd: int) -> None:
    """关闭亚克力效果。"""
    try:
        dwmapi = ctypes.windll.dwmapi
        default_val = ctypes.c_int(0)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(default_val),
            ctypes.sizeof(default_val),
        )
    except Exception:
        pass
    try:
        accent = _ACCENTPOLICY()
        accent.AccentState = 0
        data = _WINCOMPATTRDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.pointer(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(
            wintypes.HWND(hwnd), ctypes.pointer(data))
    except Exception:
        pass


def _apply_rounded_corners(hwnd: int, width: int, height: int, radius: int = 12) -> None:
    """为 overrideredirect 窗口应用圆角：优先 DWM 原生圆角（Win11 平滑），
    不支持时回退到 SetWindowRgn。"""
    # 方案一：Windows 11 DWM 原生圆角（抗锯齿，边缘平滑）
    try:
        pref = ctypes.c_int(_DWMWCP_ROUND)
        ret = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(_DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
        if ret == 0:
            return  # 成功，无需 SetWindowRgn
    except Exception:
        pass

    # 方案二：GDI SetWindowRgn 兜底（Win10，边缘可能有轻微锯齿）
    try:
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, width + 1, height + 1, radius * 2, radius * 2,
        )
        ctypes.windll.user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 自定义控件：可滚轮调节的数字输入框
# ═══════════════════════════════════════════════════════════════════════════════

class ScrollableEntry(ctk.CTkFrame):
    """可滚轮调节的数字输入框 —— 滚轮增减 + 可手动输入 + 上下箭头微调。"""

    def __init__(self, parent, min_val: int, max_val: int, width: int = 54,
                 default: str = "", on_change=None, show_arrows: bool = True,
                 **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.min_val = min_val
        self.max_val = max_val
        self._on_change = on_change
        self._var = tk.StringVar(value=default)

        self.entry = ctk.CTkEntry(
            self, width=width, height=32, corner_radius=8,
            textvariable=self._var, justify="center",
            font=ctk.CTkFont(size=13),
        )
        self.entry.pack(fill="both", expand=True)

        self.entry.bind("<MouseWheel>", self._on_mousewheel)
        self._var.trace_add("write", self._validate)
        if show_arrows:
            self._create_arrows()

    def _create_arrows(self):
        """在 entry 右侧叠加微小的上下箭头按钮。"""
        arrow_frame = ctk.CTkFrame(self, fg_color="transparent")
        arrow_frame.place(relx=0.82, rely=0.08, relwidth=0.16, relheight=0.84)

        up_btn = ctk.CTkButton(
            arrow_frame, text="▲", width=16, height=12,
            corner_radius=3, fg_color="transparent",
            text_color=("#666666", "#aaaaaa"),
            hover_color=("#e0e0e0", "#3a3a3a"),
            font=ctk.CTkFont(size=6),
            command=self._step_up,
        )
        up_btn.pack(fill="x", expand=True)

        down_btn = ctk.CTkButton(
            arrow_frame, text="▼", width=16, height=12,
            corner_radius=3, fg_color="transparent",
            text_color=("#666666", "#aaaaaa"),
            hover_color=("#e0e0e0", "#3a3a3a"),
            font=ctk.CTkFont(size=6),
            command=self._step_down,
        )
        down_btn.pack(fill="x", expand=True)

    def _on_mousewheel(self, event):
        if event.delta > 0:
            self._step_up()
        else:
            self._step_down()

    def _step_up(self):
        try:
            v = int(self._var.get())
        except ValueError:
            v = self.min_val - 1
        v = min(v + 1, self.max_val)
        self._var.set(str(v).zfill(2))
        self._notify()

    def _step_down(self):
        try:
            v = int(self._var.get())
        except ValueError:
            v = self.max_val + 1
        v = max(v - 1, self.min_val)
        self._var.set(str(v).zfill(2))
        self._notify()

    def _validate(self, *_):
        val = self._var.get()
        if val == "":
            return
        if not val.isdigit():
            filtered = "".join(c for c in val if c.isdigit())
            self._var.set(filtered)
            return
        self._notify()

    def _notify(self):
        if self._on_change:
            self._on_change(self.get())

    def get(self) -> str:
        val = self._var.get()
        if val == "":
            return ""
        try:
            v = int(val)
            v = max(self.min_val, min(v, self.max_val))
            return str(v).zfill(2)
        except ValueError:
            return ""

    def set(self, value: str):
        self._var.set(value)


# ═══════════════════════════════════════════════════════════════════════════════
# 时间选择器：HH : MM，中间强制 "："
# ═══════════════════════════════════════════════════════════════════════════════

class TimePicker(ctk.CTkFrame):
    """时间选择器 —— HH : MM，中间强制 '：'，支持滚轮和手打。"""

    def __init__(self, parent, on_change=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_change = on_change

        self.hour = ScrollableEntry(self, 0, 23, width=48, default="",
                                     on_change=self._emit, show_arrows=False)
        self.hour.pack(side="left")

        colon = ctk.CTkLabel(self, text="：", font=ctk.CTkFont(size=16, weight="bold"),
                             text_color=("#555555", "#cccccc"), width=18)
        colon.pack(side="left")

        self.minute = ScrollableEntry(self, 0, 59, width=48, default="",
                                       on_change=self._emit, show_arrows=False)
        self.minute.pack(side="left")

    def _emit(self, *_):
        if self._on_change:
            self._on_change(self.get())

    def get(self) -> str:
        h = self.hour.get()
        m = self.minute.get()
        if h and m:
            return f"{h}:{m}"
        return ""

    def set(self, time_str: str):
        if ":" in time_str:
            parts = time_str.split(":")
            self.hour.set(parts[0].zfill(2) if parts[0] else "")
            self.minute.set(parts[1].zfill(2) if len(parts) > 1 and parts[1] else "")
        else:
            self.hour.set("")
            self.minute.set("")


# ═══════════════════════════════════════════════════════════════════════════════
# 日期选择器：YYYY / MM / DD，滚轮 + 手打
# ═══════════════════════════════════════════════════════════════════════════════

class DatePicker(ctk.CTkFrame):
    """日期选择器 —— YYYY / MM / DD，滚轮 + 手打。"""

    def __init__(self, parent, on_change=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_change = on_change
        self._today = date.today()
        self._year = self._today.year
        self._month = self._today.month
        self._day = self._today.day

        self.year_spin = ScrollableEntry(self, 2020, 2099, width=60,
                                          default=str(self._year),
                                          on_change=self._on_date_change,
                                          show_arrows=False)
        self.year_spin.pack(side="left")

        sep1 = ctk.CTkLabel(self, text="/", font=ctk.CTkFont(size=14),
                            text_color=("#999999", "#777777"), width=12)
        sep1.pack(side="left")

        self.month_spin = ScrollableEntry(self, 1, 12, width=44,
                                           default=str(self._month).zfill(2),
                                           on_change=self._on_date_change,
                                           show_arrows=False)
        self.month_spin.pack(side="left")

        sep2 = ctk.CTkLabel(self, text="/", font=ctk.CTkFont(size=14),
                            text_color=("#999999", "#777777"), width=12)
        sep2.pack(side="left")

        self.day_spin = ScrollableEntry(self, 1, 31, width=44,
                                         default=str(self._day).zfill(2),
                                         on_change=self._on_date_change,
                                         show_arrows=False)
        self.day_spin.pack(side="left")

        self._update_day_range()

    def _on_date_change(self, *_):
        y = self._get_int(self.year_spin.get())
        m = self._get_int(self.month_spin.get())
        self._update_day_range()
        d = self._get_int(self.day_spin.get())

        if y and m:
            max_d = calendar.monthrange(y, m)[1]
            if d and d > max_d:
                self.day_spin.set(str(max_d).zfill(2))

        if self._on_change:
            self._on_change(self.get())

    def _update_day_range(self):
        y = self._get_int(self.year_spin.get()) or date.today().year
        m = self._get_int(self.month_spin.get()) or date.today().month
        max_d = calendar.monthrange(y, m)[1]
        self.day_spin.max_val = max_d

    @staticmethod
    def _get_int(s: str) -> Optional[int]:
        try:
            return int(s)
        except ValueError:
            return None

    def get(self) -> str:
        y = self.year_spin.get()
        m = self.month_spin.get()
        d = self.day_spin.get()
        if y and m and d:
            return f"{y}-{m}-{d}"
        return ""

    def set(self, date_str: str):
        if "-" in date_str:
            parts = date_str.split("-")
            if len(parts) >= 3:
                self.year_spin.set(parts[0])
                self.month_spin.set(parts[1].zfill(2))
                self.day_spin.set(parts[2].zfill(2))
                self._update_day_range()
        else:
            today = date.today()
            self.year_spin.set(str(today.year))
            self.month_spin.set(str(today.month).zfill(2))
            self.day_spin.set(str(today.day).zfill(2))


# ═══════════════════════════════════════════════════════════════════════════════
# 现代化方块式日历面板（填满分区的网格日历）
# ═══════════════════════════════════════════════════════════════════════════════

class ModernCalendar(ctk.CTkFrame):
    """方块式月历 —— 每格填满，柔和高亮。"""

    WEEKDAYS_CN = ["一", "二", "三", "四", "五", "六", "日"]

    def __init__(self, parent, on_date_selected, store: TaskStore = None,
                 on_right_click=None, **kwargs):
        super().__init__(parent, corner_radius=14, **kwargs)
        self.on_date_selected = on_date_selected
        self._store = store
        self._on_right_click = on_right_click
        self._year, self._month = date.today().year, date.today().month
        self._selected = date.today()
        self._today = date.today()
        self._cells: list[tuple[date, ctk.CTkFrame, ctk.CTkLabel]] = []
        self._task_labels: list[ctk.CTkLabel] = []
        self._build()

    def _build(self):
        # 月份导航栏
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=8, pady=(8, 2))

        self._prev_btn = ctk.CTkButton(
            nav, text="‹", width=28, height=28, corner_radius=14,
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color="transparent",
            text_color=("#555555", "#cccccc"),
            hover_color=("#e8e8e8", "#3a3a3a"),
            command=self._prev_month,
        )
        self._prev_btn.pack(side="left")

        self._month_label = ctk.CTkLabel(
            nav, text="", font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._month_label.pack(side="left", expand=True)

        self._next_btn = ctk.CTkButton(
            nav, text="›", width=28, height=28, corner_radius=14,
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color="transparent",
            text_color=("#555555", "#cccccc"),
            hover_color=("#e8e8e8", "#3a3a3a"),
            command=self._next_month,
        )
        self._next_btn.pack(side="right")

        # 星期标题行
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=(2, 2))
        for i in range(7):
            header.columnconfigure(i, weight=1, uniform="calcol")
        for i, wd in enumerate(self.WEEKDAYS_CN):
            lbl = ctk.CTkLabel(header, text=wd, font=ctk.CTkFont(size=10),
                               text_color=("#999999", "#666666"))
            lbl.grid(row=0, column=i, sticky="ew")

        # 日期网格容器（填满剩余空间）
        self._grid = ctk.CTkFrame(self, fg_color="transparent")
        self._grid.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        for r in range(6):
            self._grid.rowconfigure(r, weight=1, uniform="calrow")
        for c in range(7):
            self._grid.columnconfigure(c, weight=1, uniform="calcol")

        self._draw_calendar()

    def _draw_calendar(self):
        for _, frame, _ in self._cells:
            frame.destroy()
        self._cells.clear()
        for lbl in self._task_labels:
            lbl.destroy()
        self._task_labels.clear()

        y, m = self._year, self._month
        self._month_label.configure(text=f"{y} 年 {m} 月")

        first_wday = date(y, m, 1).weekday()
        days_in_month = calendar.monthrange(y, m)[1]

        row, col = 0, 0
        for _ in range(first_wday):
            empty = ctk.CTkFrame(self._grid, fg_color="transparent", corner_radius=6)
            empty.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            col += 1

        for d in range(1, days_in_month + 1):
            cur = date(y, m, d)
            is_today = (cur == self._today)
            is_sel = (cur == self._selected)

            if is_today:
                fg = "#0067c0"
                nf = "#ffffff"
            elif is_sel:
                fg = "#cce5ff"
                nf = ("#1a1a1a", "#ffffff")
            else:
                fg = "transparent"
                is_weekend = (col >= 5)
                nf = ("#c42b1c" if is_weekend else ("#1a1a1a", "#cccccc"))

            cell = ctk.CTkFrame(self._grid, fg_color=fg, corner_radius=6)
            cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)

            # 日期数字
            lbl = ctk.CTkLabel(cell, text=str(d), font=ctk.CTkFont(size=11),
                               text_color=nf)
            lbl.place(relx=0.08, rely=0.04)

            # 任务数量标识
            if self._store:
                tasks = self._store.list_tasks(day=cur.isoformat())
                count = len(tasks)
                if count > 0:
                    if is_today:
                        tc = "#ffffff"
                    elif is_sel:
                        tc = ("#333333", "#dddddd")
                    else:
                        tc = ("#0067c0", "#88bbff")
                    count_lbl = ctk.CTkLabel(
                        cell, text=f"📋 {count}项",
                        font=ctk.CTkFont(size=8),
                        text_color=tc,
                    )
                    count_lbl.place(relx=0.06, rely=0.28)
                    self._task_labels.append(count_lbl)

            # 左键选择，右键创建，双击查看任务
            cell.bind("<Button-1>", lambda e, dd=cur: self._select(dd))
            lbl.bind("<Button-1>", lambda e, dd=cur: self._select(dd))
            cell.bind("<Double-1>", lambda e, dd=cur: self._double_click_date(dd))
            lbl.bind("<Double-1>", lambda e, dd=cur: self._double_click_date(dd))
            cell.bind("<Button-3>", lambda e, dd=cur: self._right_click_date(dd))
            lbl.bind("<Button-3>", lambda e, dd=cur: self._right_click_date(dd))

            self._cells.append((cur, cell, lbl))
            col += 1
            if col >= 7:
                col = 0
                row += 1

        while row < 6:
            empty = ctk.CTkFrame(self._grid, fg_color="transparent", corner_radius=6)
            empty.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            col += 1
            if col >= 7:
                col = 0
                row += 1

    def _double_click_date(self, d: date):
        """双击日历格 → 弹出该日任务详情。"""
        self._select(d)
        if self._store:
            DayTasksDialog(self, self._store, d)

    def _right_click_date(self, d: date):
        if self._on_right_click:
            self._on_right_click(d.isoformat())

    def _select(self, d: date):
        if d == self._selected:
            return
        old = self._selected
        self._selected = d
        self._update_cell(old)
        self._update_cell(d)
        self.on_date_selected(d.isoformat())

    def _update_cell(self, d: date):
        for cur_date, frame, lbl in self._cells:
            if cur_date != d:
                continue
            is_today = (d == self._today)
            is_sel = (d == self._selected)
            first_wday = date(d.year, d.month, 1).weekday()
            col = (first_wday + d.day - 1) % 7
            is_weekend = (col >= 5)

            if is_today:
                fg, nf = "#0067c0", "#ffffff"
            elif is_sel:
                fg, nf = "#cce5ff", ("#1a1a1a", "#ffffff")
            else:
                fg = "transparent"
                nf = ("#c42b1c" if is_weekend else ("#1a1a1a", "#cccccc"))
            frame.configure(fg_color=fg)
            lbl.configure(text_color=nf)
            break

    def _prev_month(self):
        if self._month == 1:
            self._year -= 1
            self._month = 12
        else:
            self._month -= 1
        self._draw_calendar()

    def _next_month(self):
        if self._month == 12:
            self._year += 1
            self._month = 1
        else:
            self._month += 1
        self._draw_calendar()

    def set_selected(self, d: date):
        self._selected = d
        self._year, self._month = d.year, d.month
        self._draw_calendar()


# ═══════════════════════════════════════════════════════════════════════════════
# 某天任务详情弹窗
# ═══════════════════════════════════════════════════════════════════════════════

class DayTasksDialog(ctk.CTkToplevel):
    """双击日历格 → 展示该日所有任务列表，右键完成/编辑/删除。"""

    def __init__(self, parent, store: TaskStore, day: date):
        super().__init__(parent)
        self.title(f"{day.isoformat()} 任务")
        self.geometry("440x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._store = store
        self._day = day
        self._ctx_task: Optional[Task] = None

        # 预创建右键菜单（复用，避免多次 tk_popup 失败）
        self._ctx_menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 11),
                                 bg="#f5f5f5", fg="#1a1a1a",
                                 activebackground="#0067c0",
                                 activeforeground="#ffffff")
        self._ctx_menu.add_command(label="☐  完成", command=self._ctx_complete_current)
        self._ctx_menu.add_command(label="✎  编辑", command=self._ctx_edit_current)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="✕  删除", command=self._ctx_delete_current)

        # 标题
        ctk.CTkLabel(self, text="任务详情",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=24, pady=(20, 4))

        ctk.CTkLabel(self, text=f"📅 {day.isoformat()}",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=24, pady=(0, 12))

        tasks = store.list_tasks(day=day.isoformat())
        self._day_tasks = tasks  # 供重建使用
        self._scroll = None
        if not tasks:
            ctk.CTkLabel(self, text="暂无任务",
                         font=ctk.CTkFont(size=13),
                         text_color=("#999999", "#777777")).pack(
                anchor="center", expand=True)
        else:
            self._scroll = ctk.CTkScrollableFrame(self, height=320)
            self._scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            self._populate_scroll(self._scroll, tasks)

        # 存储引用供回调使用
        self._parent_app = parent

        # 关闭按钮
        self._close_btn = ctk.CTkButton(self, text="关闭", width=80, height=30,
                                        corner_radius=8,
                                        command=self.destroy)
        self._close_btn.pack(side="bottom", pady=(0, 16))

    def _populate_scroll(self, scroll: ctk.CTkScrollableFrame, tasks):
        """填充滚动列表中的任务行。"""
        for task in tasks:
            row = ctk.CTkFrame(scroll, fg_color=("gray95", "gray20"),
                               corner_radius=6)
            row.pack(fill="x", pady=2, padx=2)
            row.task_ref = task  # 挂载任务引用

            status = "☑" if task.completed else "☐"
            lbl_status = ctk.CTkLabel(row, text=status, font=ctk.CTkFont(size=13),
                                      width=30)
            lbl_status.pack(side="left", padx=(6, 0))

            title_text = task.title
            if task.due_time:
                title_text += f"  ⏰ {task.due_time}"
            lbl = ctk.CTkLabel(row, text=title_text, font=ctk.CTkFont(size=13),
                               anchor="w")
            if task.completed:
                lbl.configure(text_color=("#999999", "#777777"))
            lbl.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=6)

            # 右键菜单 —— 行本身和所有子元素都绑定
            row.bind("<Button-3>", lambda e, t=task: self._task_right_click(e, t))
            for child in row.winfo_children():
                child.bind("<Button-3>", lambda e, t=task: self._task_right_click(e, t))

    def _task_right_click(self, event, task: Task):
        """右键任务行弹出完成/编辑/删除菜单（复用预创建的菜单）。"""
        self._ctx_task = task
        # 根据完成状态更新菜单首项文字
        status_label = "☑ 取消完成" if task.completed else "☐  完成"
        self._ctx_menu.entryconfigure(0, label=status_label)
        self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _ctx_complete_current(self):
        if self._ctx_task:
            self._ctx_complete(self._ctx_task)

    def _ctx_edit_current(self):
        if self._ctx_task:
            self._ctx_edit(self._ctx_task)

    def _ctx_delete_current(self):
        if self._ctx_task:
            self._ctx_delete(self._ctx_task)

    def _ctx_complete(self, task: Task):
        if task.completed:
            self._store.uncomplete_task(task.id)
        else:
            self._store.complete_task(task.id)
        # 不关闭，仅刷新列表区域
        self._rebuild_tasks()

    def _ctx_edit(self, task: Task):
        main = self._find_main_app()
        if main:
            NewTaskDialog(main, self._store, on_saved=self._rebuild_tasks,
                          prefill_date=task.due_date,
                          prefill_task_id=task.id)

    def _ctx_delete(self, task: Task):
        if messagebox.askyesno("确认", f"确定删除「{task.title}」？"):
            self._store.delete_task(task.id)
            self._rebuild_tasks()

    def _rebuild_tasks(self):
        """原地重建任务列表（不关闭对话框）。"""
        # 先清理旧的"暂无任务"标签（如果有的话）
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkLabel) and child.cget("text") == "暂无任务":
                child.destroy()
        if self._scroll:
            self._scroll.destroy()
            self._scroll = None
        tasks = self._store.list_tasks(day=self._day.isoformat())
        # 刷新主界面
        main = self._find_main_app()
        self._main_refresh(main)
        if not tasks:
            ctk.CTkLabel(self, text="暂无任务",
                         font=ctk.CTkFont(size=13),
                         text_color=("#999999", "#777777")).pack(
                anchor="center", expand=True, pady=20)
        else:
            self._scroll = ctk.CTkScrollableFrame(self, height=260)
            self._scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            self._populate_scroll(self._scroll, tasks)

    def _find_main_app(self):
        """找到最顶层 TaskTrackerApp 窗口。"""
        p = self.master
        while p and not hasattr(p, "store"):
            try:
                p = p.master
            except AttributeError:
                break
        return p if p and hasattr(p, "store") else None

    def _get_main_window(self):
        return self._find_main_app()

    @staticmethod
    def _main_refresh(main):
        if main and hasattr(main, "refresh_tasks"):
            main.refresh_tasks()
        if main and hasattr(main, "_refresh_floating"):
            main._refresh_floating()
        if main and hasattr(main, "calendar"):
            main.calendar._draw_calendar()


# ═══════════════════════════════════════════════════════════════════════════════
# 新建任务弹窗
# ═══════════════════════════════════════════════════════════════════════════════

class NewTaskDialog(ctk.CTkToplevel):
    """新建任务弹窗对话框。"""

    def __init__(self, parent, store: TaskStore, on_saved=None,
                 prefill_date: str = "", prefill_task_id: Optional[int] = None):
        super().__init__(parent)
        self.title("新建任务")
        self.geometry("420x370")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._store = store
        self._on_saved = on_saved
        self._editing_id = prefill_task_id

        self._title_var = tk.StringVar()
        self._time_var = tk.StringVar()
        self._remind_var = tk.BooleanVar(value=False)

        # 预填日期
        today = date.today().isoformat()
        self._date_str = prefill_date or today

        # 如果是编辑模式，加载已有数据
        if prefill_task_id is not None:
            task = store.get_task(prefill_task_id)
            if task:
                self._title_var.set(task.title)
                self._time_var.set(task.due_time)
                self._date_str = task.due_date
                self._remind_var.set(task.remind)

        self._build()
        self.after(50, lambda: self._title_entry.focus_set())

    def _build(self):
        ctk.CTkLabel(self, text="新建任务",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=28, pady=(24, 16))

        # 标题
        ctk.CTkLabel(self, text="标题",
                     font=ctk.CTkFont(size=11),
                     text_color=("#777777", "#999999")).pack(
            anchor="w", padx=28, pady=(0, 2))
        self._title_entry = ctk.CTkEntry(
            self, textvariable=self._title_var,
            height=36, corner_radius=8,
            font=ctk.CTkFont(size=13),
            placeholder_text="输入任务标题...",
        )
        self._title_entry.pack(fill="x", padx=28, pady=(0, 12))

        # 日期 & 时间行
        dt_row = ctk.CTkFrame(self, fg_color="transparent")
        dt_row.pack(fill="x", padx=28, pady=(0, 8))

        date_col = ctk.CTkFrame(dt_row, fg_color="transparent")
        date_col.pack(side="left")
        ctk.CTkLabel(date_col, text="日期",
                     font=ctk.CTkFont(size=11),
                     text_color=("#777777", "#999999")).pack(anchor="w", pady=(0, 2))
        self._date_picker = DatePicker(date_col, on_change=self._on_date_pick)
        self._date_picker.pack()
        self._date_picker.set(self._date_str)

        time_col = ctk.CTkFrame(dt_row, fg_color="transparent")
        time_col.pack(side="left", padx=(24, 0))
        ctk.CTkLabel(time_col, text="时间",
                     font=ctk.CTkFont(size=11),
                     text_color=("#777777", "#999999")).pack(anchor="w", pady=(0, 2))
        self._time_picker = TimePicker(time_col, on_change=self._on_time_pick)
        self._time_picker.pack()
        self._time_picker.set(self._time_var.get())

        # 铃声提醒（仅当设置时间后可见）
        remind_row = ctk.CTkFrame(self, fg_color="transparent")
        remind_row.pack(fill="x", padx=28, pady=(4, 0))
        self._remind_check = ctk.CTkCheckBox(
            remind_row, text="🔔 铃声提醒（到时间弹出Win11通知）",
            variable=self._remind_var,
            font=ctk.CTkFont(size=12),
            checkbox_width=20, checkbox_height=20, corner_radius=6,
        )
        self._remind_check.pack(side="left")

        # 按钮行
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=28, pady=(16, 24))

        ctk.CTkButton(btn_row, text="取消", fg_color="transparent",
                      text_color=("#555555", "#aaaaaa"),
                      font=ctk.CTkFont(size=12),
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text="保存",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._save).pack(side="right")

    def _on_date_pick(self, date_str: str):
        if date_str:
            self._date_str = date_str

    def _on_time_pick(self, time_str: str):
        self._time_var.set(time_str)

    def _save(self):
        title = self._title_var.get().strip()
        if not title:
            messagebox.showwarning("提示", "请输入任务标题")
            return

        time_str = self._time_picker.get()
        if time_str and not re.match(r"^\d{2}:\d{2}$", time_str):
            messagebox.showwarning("提示", "时间格式不正确")
            return

        task = Task(
            id=self._editing_id,
            title=title,
            due_date=self._date_picker.get() or date.today().isoformat(),
            due_time=time_str,
            remind=bool(self._remind_var.get()) if time_str else False,
            completed=False,
        )

        if self._editing_id is None:
            self._store.add_task(task)
        else:
            self._store.update_task(task)

        if self._on_saved:
            self._on_saved()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# 设置弹窗
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsDialog(ctk.CTkToplevel):
    """主题设置对话框。"""

    def __init__(self, parent, current_theme: str, on_apply):
        super().__init__(parent)
        self.title("设置")
        self.geometry("340x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._on_apply = on_apply
        self._theme_var = tk.StringVar(value=current_theme)

        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="主题颜色",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=28, pady=(24, 16))

        for key, theme in THEMES.items():
            frame = ctk.CTkFrame(self, fg_color="transparent")
            frame.pack(fill="x", padx=28, pady=3)
            ctk.CTkRadioButton(
                frame, text=theme["name"],
                variable=self._theme_var, value=key,
                font=ctk.CTkFont(size=13),
            ).pack(side="left")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=28, pady=(20, 24))

        ctk.CTkButton(btn_frame, text="取消", fg_color="transparent",
                      text_color=("#555555", "#aaaaaa"),
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="应用", command=self._apply).pack(side="right")

    def _apply(self):
        theme_key = self._theme_var.get()
        config = load_config()
        config["theme"] = theme_key
        save_config(config)
        self._on_apply(theme_key)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# 主应用窗口
# ═══════════════════════════════════════════════════════════════════════════════

class TaskTrackerApp(ctk.CTk):
    """流光笺主窗口 —— 毛玻璃 + 侧边栏 + 圆角卡片布局。"""

    PAGE_HOME = "home"
    PAGE_CALENDAR = "calendar"
    PAGE_SETTINGS = "settings"

    def __init__(self, db_path: Optional[str] = None):
        super().__init__()

        self.title("流光笺")
        self.geometry("1060x680")
        self.minsize(940, 560)

        # ---- 亚克力毛玻璃 ----
        self._acrylic_enabled = False
        self._current_theme = load_config().get("theme", "transparent")
        self._init_acrylic()

        # ---- 数据库 ----
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "tasks.db")
        # PyInstaller 打包后改用 exe 同级 data 目录
        if getattr(sys, "frozen", False) and db_path is None:
            self.db_path = os.path.join(
                os.path.dirname(sys.executable), "data", "tasks.db")
        self.store = TaskStore(self.db_path)

        # ---- 状态 ----
        self.selected_task_id: Optional[int] = None
        self.editing_task_id: Optional[int] = None
        self._current_page = self.PAGE_HOME

        # ---- 变量 ----
        self.title_var = tk.StringVar()
        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.time_var = tk.StringVar()
        self.completed_var = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_tasks())

        # ---- 构建 UI ----
        self._build_sidebar()
        self._build_main_area()
        self.apply_theme(self._current_theme)
        self._create_floating_window()

        # ---- 初始数据 ----
        self.refresh_tasks()
        self._refresh_floating()
        # 铃声提醒定时器
        self._reminded_today: set[int] = set()
        self._start_reminder_timer()

        # ---- 系统托盘 ----
        self._tray_icon: Optional[pystray.Icon] = None
        self._setup_tray()

        # ---- 启动行为：显示悬浮窗，主窗口最小化到托盘 ----
        # 若上次为折叠状态，调整为折叠尺寸
        if self._float_collapsed:
            pos = load_config().get("float_pos", "40+40")
            self._floating_win.geometry(f"300x32+{pos}")
        self._floating_win.deiconify()
        self.after(200, self._apply_float_rounded)
        self.withdraw()  # 主窗口隐藏到托盘
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # 系统托盘
    # ==================================================================

    def _create_tray_icon_image(self):
        """用 Pillow 生成一个 64x64 蓝色圆角方块图标。"""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, 62, 62], radius=12, fill="#0067c0")
        draw.text((32, 28), "流", fill="white", anchor="mm")
        return img

    def _setup_tray(self):
        """创建系统托盘图标及右键菜单。"""
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self._restore_from_tray, default=True),
            pystray.MenuItem("切换悬浮窗", self._toggle_floating),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit_app),
        )
        self._tray_icon = pystray.Icon(
            "流光笺", self._create_tray_icon_image(), "流光笺", menu,
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _restore_from_tray(self, *_):
        """从托盘恢复主窗口。"""
        self.after(0, self._do_restore)

    def _do_restore(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_app(self, *_):
        """完全退出应用。"""
        self._save_float_position()
        if self._tray_icon:
            self._tray_icon.stop()
        self.destroy()

    def _save_float_position(self):
        """将悬浮窗当前位置及折叠状态写入 config。"""
        if hasattr(self, "_floating_win") and self._floating_win.winfo_exists():
            try:
                x = self._floating_win.winfo_x()
                y = self._floating_win.winfo_y()
                if x > 0 and y > 0:
                    config = load_config()
                    config["float_pos"] = f"{x}+{y}"
                    config["float_collapsed"] = getattr(self, "_float_collapsed", False)
                    save_config(config)
            except Exception:
                pass

    def _on_close(self):
        """关闭主窗口 → 最小化到托盘而非退出。"""
        self.withdraw()
        return  # 阻止默认关闭行为

    # ==================================================================
    # 亚克力毛玻璃
    # ==================================================================

    def _init_acrylic(self):
        """延迟启用亚克力（需要窗口已映射）。"""
        self.after(100, self._try_enable_acrylic)

    def _try_enable_acrylic(self):
        hwnd = self.winfo_id()
        if hwnd and _enable_acrylic(hwnd):
            self._acrylic_enabled = True
        else:
            self.after(500, self._retry_acrylic)

    def _retry_acrylic(self):
        hwnd = self.winfo_id()
        if hwnd and not self._acrylic_enabled:
            self._acrylic_enabled = _enable_acrylic(hwnd)

    # ==================================================================
    # 主题
    # ==================================================================

    def apply_theme(self, theme_key: str):
        self._current_theme = theme_key
        t = THEMES.get(theme_key, THEMES["transparent"])
        alpha = t.get("alpha", 0.96)

        self.attributes("-alpha", alpha)

        hwnd = self.winfo_id()
        if hwnd:
            if theme_key == "transparent":
                _enable_acrylic(hwnd)
                self._acrylic_enabled = True
            else:
                _disable_acrylic(hwnd)
                self._acrylic_enabled = False

        if theme_key in ("dark",):
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

        if hasattr(self, "_floating_win") and self._floating_win.winfo_exists():
            self._floating_win.attributes("-alpha", alpha)
            self._refresh_floating_theme()

    def _refresh_floating_theme(self):
        """根据当前主题刷新悬浮窗全部配色。"""
        is_dark = (self._current_theme == "dark")
        win_bg = "#1a1a1a" if is_dark else "#f0f0f0"
        container_fg = "#2a2a2a" if is_dark else "#f5f5f5"
        title_fg = "#3a3a3a" if is_dark else "#cce5ff"
        title_text = "#cccccc" if is_dark else "#1a1a1a"
        list_bg = "#2a2a2a" if is_dark else "#f5f5f5"
        list_fg = "#cccccc" if is_dark else "#1a1a1a"

        # 白色主题下为悬浮窗启用亚克力效果
        hwnd = self._floating_win.winfo_id()
        if hwnd:
            if is_dark:
                _disable_acrylic(hwnd)
            else:
                _enable_acrylic(hwnd)

        self._floating_win.configure(bg=win_bg)
        self._float_container.configure(
            fg_color=container_fg,
            border_color=("#555555" if is_dark else "#cccccc"),
        )
        self._float_title_bar.configure(fg_color=title_fg)
        for child in self._float_title_bar.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                child.configure(text_color=title_text)
            elif isinstance(child, ctk.CTkButton):
                child.configure(text_color=title_text)
        self._float_list.configure(bg=list_bg, fg=list_fg)
        self._float_popup_panel.configure(
            fg_color=("#333333" if is_dark else "#f0f0f0"),
        )
        # 右键菜单
        menu_bg = "#2a2a2a" if is_dark else "#f5f5f5"
        menu_fg = "#cccccc" if is_dark else "#1a1a1a"
        self._float_context_menu.configure(bg=menu_bg, fg=menu_fg)

    def open_settings(self):
        SettingsDialog(self, self._current_theme, self.apply_theme)

    # ==================================================================
    # 侧边栏
    # ==================================================================

    def _build_sidebar(self):
        self._sidebar = ctk.CTkFrame(
            self, width=170, corner_radius=0,
            fg_color=("gray92", "gray14"),
        )
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # 应用名
        ctk.CTkLabel(
            self._sidebar, text="流光笺",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(padx=22, pady=(32, 30), anchor="w")

        # 导航按钮
        self._nav_btns = {}
        nav_items = [
            (self.PAGE_HOME, "📋  主页", self._show_home),
        ]
        for page_id, label, cmd in nav_items:
            btn = ctk.CTkButton(
                self._sidebar, text=label,
                anchor="w", height=38, corner_radius=8,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                text_color=("#333333", "#cccccc"),
                hover_color=("#e0e0e0", "#2a2a2a"),
                command=cmd,
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_btns[page_id] = btn

        # 底部按钮
        ctk.CTkButton(
            self._sidebar, text="🪟  悬浮窗",
            anchor="w", height=34, corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            text_color=("#555555", "#999999"),
            hover_color=("#e0e0e0", "#2a2a2a"),
            command=self._toggle_floating,
        ).pack(side="bottom", fill="x", padx=12, pady=(0, 2))

        settings_btn = ctk.CTkButton(
            self._sidebar, text="⚙  设置",
            anchor="w", height=34, corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            text_color=("#555555", "#999999"),
            hover_color=("#e0e0e0", "#2a2a2a"),
            command=self._show_settings,
        )
        settings_btn.pack(side="bottom", fill="x", padx=12, pady=(0, 16))
        self._nav_btns[self.PAGE_SETTINGS] = settings_btn

    # ==================================================================
    # 主内容区
    # ==================================================================

    def _build_main_area(self):
        self._main_container = ctk.CTkFrame(self, fg_color="transparent")
        self._main_container.pack(side="left", fill="both", expand=True)

        # 主页
        self._home_frame = ctk.CTkFrame(self._main_container, fg_color="transparent")
        self._build_home_page()

        # 日历全页
        self._calendar_frame = ctk.CTkFrame(self._main_container, fg_color="transparent")
        self._build_calendar_page()

        # 设置页
        self._settings_frame = ctk.CTkFrame(self._main_container, fg_color="transparent")
        self._build_settings_page()

        self._show_home()

    def _build_home_page(self):
        """主页：搜索栏 + 日历1:任务列表2 比例布局。"""
        # 搜索栏
        search_frame = ctk.CTkFrame(self._home_frame, corner_radius=12,
                                     fg_color=("gray90", "gray17"))
        search_frame.pack(fill="x", padx=16, pady=(16, 10))

        ctk.CTkLabel(search_frame, text="🔍", font=ctk.CTkFont(size=15),
                     text_color=("#999999", "#777777")).pack(
            side="left", padx=(14, 4), pady=10)
        ctk.CTkEntry(search_frame, textvariable=self.search_var,
                     fg_color="transparent", border_width=0,
                     font=ctk.CTkFont(size=14),
                     placeholder_text="搜索任务...", height=36).pack(
            side="left", fill="x", expand=True, padx=(2, 14), pady=10)

        # 主内容行 —— 1:2 比例
        content = ctk.CTkFrame(self._home_frame, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        content.columnconfigure(0, weight=1)  # 日历 1
        content.columnconfigure(1, weight=2)  # 任务 2
        content.rowconfigure(0, weight=1)

        # ---- 日历卡片 ----
        cal_card = ctk.CTkFrame(content, corner_radius=14,
                                 fg_color=("gray90", "gray17"))
        cal_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        cal_header = ctk.CTkFrame(cal_card, fg_color="transparent")
        cal_header.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(cal_header, text="日历视图",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=("#555555", "#aaaaaa")).pack(side="left")

        self.calendar = ModernCalendar(cal_card, on_date_selected=self._on_cal_date,
                                        store=self.store,
                                        on_right_click=self._on_cal_right_click)
        self.calendar.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        # ---- 任务列表卡片（占满整个右侧） ----
        list_card = ctk.CTkFrame(content, corner_radius=14,
                                  fg_color=("gray90", "gray17"))
        list_card.grid(row=0, column=1, sticky="nsew")
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)

        list_header = ctk.CTkFrame(list_card, fg_color="transparent")
        list_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        ctk.CTkLabel(list_header, text="任务详情",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=("#555555", "#aaaaaa")).pack(side="left")

        # Treeview
        self.tree = ttk.Treeview(
            list_card,
            columns=("time", "title", "status"),
            show="headings",
            height=6,
        )
        style = ttk.Style()
        style.configure("Treeview", rowheight=42, font=("Segoe UI", 13),
                        borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"),
                        borderwidth=0, relief="flat")
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        self.tree.heading("time", text="时间")
        self.tree.heading("title", text="任务")
        self.tree.heading("status", text="状态")
        self.tree.column("time", width=80, anchor="center")
        self.tree.column("title", width=420)
        self.tree.column("status", width=60, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # 双击任务弹出上下文菜单（同右击）
        self.tree.bind("<Double-1>", self._on_tree_right_click)

        # 右键弹出新建/编辑/完成/删除
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self._tree_menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 11),
                                  bg="#f5f5f5", fg="#1a1a1a",
                                  activebackground="#0067c0",
                                  activeforeground="#ffffff")
        self._tree_menu.add_command(label="＋ 新建任务", command=self._tree_new_task)
        self._tree_menu.add_command(label="✎ 编辑任务", command=self._tree_edit_task)
        self._tree_menu.add_command(label="☐ 切换完成", command=self._tree_toggle_complete)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="✕ 删除", command=self._tree_delete_task)

    # ==================================================================
    # 任务列表右键菜单处理
    # ==================================================================

    def _on_tree_right_click(self, event):
        """右击任务列表行弹出上下文菜单。"""
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.selected_task_id = int(row)
            task = self.store.get_task(self.selected_task_id)
            if task:
                # 根据完成状态调整菜单文字
                self._tree_menu.entryconfigure(2, label="☑ 取消完成" if task.completed else "☐  完成")
        else:
            self.selected_task_id = None
        self._tree_menu.tk_popup(event.x_root, event.y_root)

    def _tree_new_task(self):
        """右键菜单：新建任务（预填当前选中日期）。"""
        day = self.date_var.get() or date.today().isoformat()
        self.selected_task_id = None
        self.editing_task_id = None
        NewTaskDialog(self, self.store, on_saved=self._on_new_task_saved,
                      prefill_date=day)

    def _tree_edit_task(self):
        """右键菜单：编辑选中任务。"""
        if self.selected_task_id is None:
            return
        task = self.store.get_task(self.selected_task_id)
        if task:
            self.editing_task_id = task.id
            NewTaskDialog(self, self.store, on_saved=self._on_new_task_saved,
                          prefill_date=task.due_date,
                          prefill_task_id=task.id)

    def _tree_toggle_complete(self):
        """右键菜单：切换任务完成状态。"""
        if self.selected_task_id is None:
            return
        task = self.store.get_task(self.selected_task_id)
        if task is None:
            return
        if task.completed:
            self.store.uncomplete_task(self.selected_task_id)
        else:
            self.store.complete_task(self.selected_task_id)
        self.refresh_tasks()
        self._refresh_floating()

    def _tree_delete_task(self):
        """右键菜单：删除选中任务。"""
        if self.selected_task_id is None:
            return
        if not messagebox.askyesno("确认", "确定删除此任务？"):
            return
        self.store.delete_task(self.selected_task_id)
        self.selected_task_id = None
        self.editing_task_id = None
        self.refresh_tasks()
        self._refresh_floating()

    def _on_new_task_saved(self):
        """新建/编辑任务保存后的回调。"""
        self.selected_task_id = None
        self.editing_task_id = None
        self.refresh_tasks()
        self._refresh_floating()

    # ==================================================================
    # 日历全页占位
    # ==================================================================

    def _build_calendar_page(self):
        """日历全页视图（预留后续扩展月/周视图）。"""
        ctk.CTkLabel(self._calendar_frame, text="日历视图",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="center", expand=True)

    # ==================================================================
    # 设置页
    # ==================================================================

    def _build_settings_page(self):
        """设置页：软件主题 + 主界面字体。"""
        card = ctk.CTkFrame(self._settings_frame, corner_radius=14,
                            fg_color=("gray90", "gray17"))
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(card, text="设置",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=24, pady=(20, 20))

        # ---- 软件主题 ----
        theme_section = ctk.CTkFrame(card, fg_color="transparent")
        theme_section.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(theme_section, text="软件主题",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", pady=(0, 6))

        theme_opts = [THEMES[k]["name"] for k in THEMES]
        theme_keys = list(THEMES.keys())
        self._settings_theme_var = tk.StringVar(
            value=THEMES[self._current_theme]["name"])
        theme_menu = ctk.CTkOptionMenu(
            theme_section, values=theme_opts,
            variable=self._settings_theme_var,
            width=200, height=34, corner_radius=8,
            font=ctk.CTkFont(size=13),
            command=self._on_settings_theme_change,
        )
        theme_menu.pack(anchor="w")

    def _on_settings_theme_change(self, name: str):
        for k, t in THEMES.items():
            if t["name"] == name:
                config = load_config()
                config["theme"] = k
                save_config(config)
                self.apply_theme(k)
                break

    # ==================================================================
    # 页面切换
    # ==================================================================

    def _show_home(self):
        self._calendar_frame.pack_forget()
        self._settings_frame.pack_forget()
        self._home_frame.pack(fill="both", expand=True)
        self._current_page = self.PAGE_HOME
        self._highlight_nav(self.PAGE_HOME)

    def _show_calendar(self):
        self._home_frame.pack_forget()
        self._settings_frame.pack_forget()
        self._calendar_frame.pack(fill="both", expand=True)
        self._current_page = self.PAGE_CALENDAR
        self._highlight_nav(self.PAGE_CALENDAR)

    def _show_settings(self):
        self._home_frame.pack_forget()
        self._calendar_frame.pack_forget()
        self._settings_frame.pack(fill="both", expand=True)
        self._current_page = self.PAGE_SETTINGS
        self._highlight_nav(self.PAGE_SETTINGS)

    def _highlight_nav(self, active_page: str):
        for pid, btn in self._nav_btns.items():
            if pid == active_page:
                btn.configure(
                    fg_color=("#d0d0d0", "#3a3a3a"),
                    text_color=("#111111", "#ffffff"),
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=("#333333", "#cccccc"),
                )

    # ==================================================================
    # 悬浮窗
    # ==================================================================

    def _create_floating_window(self):
        self._floating_win = ctk.CTkToplevel(self)
        self._floating_win.title("悬浮窗")
        # 恢复上次关闭时的位置，无记录则默认左上角
        pos = load_config().get("float_pos", "40+40")
        self._floating_win.geometry(f"300x400+{pos}")
        self._floating_win.attributes("-topmost", False)
        self._floating_win.overrideredirect(True)

        # 根据当前主题决定配色
        is_dark = (self._current_theme == "dark")
        win_bg = "#1a1a1a" if is_dark else "#f0f0f0"
        container_fg = ("#2a2a2a" if is_dark else "#f5f5f5")
        title_fg = "#3a3a3a" if is_dark else "#cce5ff"
        title_text = "#cccccc" if is_dark else "#1a1a1a"
        list_bg = "#2a2a2a" if is_dark else "#f5f5f5"
        list_fg = "#cccccc" if is_dark else "#1a1a1a"
        border_c = ("#555555" if is_dark else "#cccccc")

        # 圆角外框容器
        self._floating_win.configure(bg=win_bg)
        self._float_container = ctk.CTkFrame(
            self._floating_win, corner_radius=12, border_width=1,
            border_color=border_c,
            fg_color=container_fg,
        )
        self._float_container.pack(fill="both", expand=True, padx=2, pady=2)
        self._float_container.pack_propagate(False)

        # 标题栏（白色主题用浅蓝，深色主题用深灰，匹配主窗口亚克力风格）
        self._float_title_bar = ctk.CTkFrame(self._float_container, height=32, corner_radius=0,
                                              fg_color=title_fg)
        self._float_title_bar.pack(fill="x")
        self._float_title_bar.pack_propagate(False)
        ctk.CTkLabel(self._float_title_bar, text="今日任务",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=title_text).pack(side="left", padx=12)

        # 关闭按钮
        ctk.CTkButton(
            self._float_title_bar, text="✕", width=28, height=28,
            fg_color="transparent", text_color=title_text,
            hover_color="#c42b1c", font=ctk.CTkFont(size=12),
            command=self._floating_win.withdraw,
        ).pack(side="right", padx=2)

        # 折叠/展开按钮（✕ 左侧）
        self._float_fold_btn = ctk.CTkButton(
            self._float_title_bar, text="▲", width=28, height=28,
            fg_color="transparent", text_color=title_text,
            hover_color="#005aa8", font=ctk.CTkFont(size=11),
            command=self._toggle_float_fold,
        )
        self._float_fold_btn.pack(side="right", padx=0)

        # "..." 按钮（最右侧）
        self._float_more_btn = ctk.CTkButton(
            self._float_title_bar, text="⋯", width=28, height=28,
            fg_color="transparent", text_color=title_text,
            hover_color="#005aa8", font=ctk.CTkFont(size=16),
            command=self._toggle_float_new_popup,
        )
        self._float_more_btn.pack(side="right", padx=0)

        # "..." 弹出面板（在容器内）
        self._float_popup_panel = ctk.CTkFrame(
            self._float_container, corner_radius=10,
            fg_color=("#f0f0f0", "#333333"),
            width=150, height=190,
        )
        self._float_popup_panel.pack_propagate(False)
        popup_inner = ctk.CTkFrame(self._float_popup_panel, fg_color="transparent")
        popup_inner.pack(fill="both", expand=True, padx=10, pady=10)

        # 字号
        ctk.CTkLabel(popup_inner, text="字号调整",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("#555555", "#aaaaaa")).pack(anchor="w", pady=(0, 4))

        self._float_font_var = tk.StringVar(value="24")
        font_opts = ["10", "11", "12", "13", "14", "15", "16", "18", "20", "22", "24"]
        font_menu = ctk.CTkOptionMenu(
            popup_inner, values=font_opts,
            variable=self._float_font_var,
            width=130, height=28, corner_radius=6,
            font=ctk.CTkFont(size=12),
            command=self._float_change_font_size,
        )
        font_menu.pack(fill="x", pady=(0, 6))

        # 置顶 / 置底互斥
        ctk.CTkLabel(popup_inner, text="窗口层级",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("#555555", "#aaaaaa")).pack(anchor="w", pady=(0, 4))

        toggle_row = ctk.CTkFrame(popup_inner, fg_color="transparent")
        toggle_row.pack(fill="x", pady=(0, 6))

        self._float_top_btn = ctk.CTkButton(
            toggle_row, text="置顶", width=62, height=26,
            corner_radius=6, font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color=("#333333", "#cccccc"),
            border_width=1,
            hover_color=("#e0e0e0", "#2a2a2a"),
            command=self._float_set_topmost,
        )
        self._float_top_btn.pack(side="left")

        self._float_bottom_btn = ctk.CTkButton(
            toggle_row, text="置底", width=62, height=26,
            corner_radius=6, font=ctk.CTkFont(size=11),
            fg_color="#0067c0", hover_color="#005aa8",
            command=self._float_set_bottom,
        )
        self._float_bottom_btn.pack(side="right")

        ctk.CTkButton(
            popup_inner, text="＋ 新建任务", width=130, height=30,
            corner_radius=6, font=ctk.CTkFont(size=12),
            fg_color="#0067c0", hover_color="#005aa8",
            command=self._float_new_task,
        ).pack(fill="x")

        # 拖动绑定
        self._float_title_bar.bind("<Button-1>", self._float_drag_start)
        self._float_title_bar.bind("<B1-Motion>", self._float_drag_move)
        for child in self._float_title_bar.winfo_children():
            child.bind("<Button-1>", self._float_drag_start)
            child.bind("<B1-Motion>", self._float_drag_move)

        # 列表区（放容器内）
        self._float_list = tk.Listbox(
            self._float_container, height=16, width=28,
            font=("Segoe UI", 24),
            bg=list_bg, fg=list_fg,
            selectbackground="#0067c0", selectforeground="white",
            relief="flat", bd=0, highlightthickness=0,
            activestyle="none",
        )
        self._float_list.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self._float_list.bind("<Double-1>", self._on_float_dblclick)

        # 右击弹出 toggle 完成 / 删除 菜单（完成是隐藏多选框样式）
        self._float_list.bind("<Button-3>", self._on_float_right_click)
        self._float_context_menu = tk.Menu(self._floating_win, tearoff=0,
                                           font=("Segoe UI", 11),
                                           bg=list_bg, fg=list_fg,
                                           activebackground="#0067c0",
                                           activeforeground="#ffffff")
        self._float_context_menu.add_command(label="☐  完成", command=self._float_ctx_toggle_complete)
        self._float_context_menu.add_command(label="✎  编辑", command=self._float_ctx_edit)
        self._float_context_menu.add_separator()
        self._float_context_menu.add_command(label="✕  删除", command=self._float_ctx_delete)

        self._float_task_ids: list[int] = []

        # 初始尺寸（固定值，折叠时不可变）
        self._float_init_width = 300
        self._float_full_height = 400

        # 恢复上次折叠状态
        self._float_collapsed = load_config().get("float_collapsed", False)
        if self._float_collapsed:
            self._float_list.pack_forget()
            self._float_fold_btn.configure(text="▼")

        self._floating_win.withdraw()

    def _apply_float_rounded(self, *_):
        """对悬浮窗应用 SetWindowRgn 圆角裁切。"""
        try:
            hwnd = self._floating_win.winfo_id()
            w = self._floating_win.winfo_width()
            h = self._floating_win.winfo_height()
            if hwnd and w > 0 and h > 0:
                _apply_rounded_corners(hwnd, w, h, radius=12)
        except Exception:
            pass

    def _toggle_float_new_popup(self):
        """切换悬浮窗设置面板。"""
        if self._float_popup_panel.winfo_ismapped():
            self._float_popup_panel.place_forget()
        else:
            btn_y = self._float_more_btn.winfo_rooty() - self._floating_win.winfo_rooty() + 34
            self._float_popup_panel.place(x=145, y=btn_y)
            self._float_popup_panel.lift()

    def _float_change_font_size(self, size_str: str):
        """切换悬浮窗任务字体大小。"""
        try:
            fs = int(size_str)
            self._float_list.configure(font=("Segoe UI", fs))
        except ValueError:
            pass

    def _float_set_topmost(self):
        """置顶：悬浮在所有窗口之上。"""
        self._floating_win.attributes("-topmost", True)
        self._float_top_btn.configure(fg_color="#0067c0", text_color="#ffffff",
                                       border_width=0)
        self._float_bottom_btn.configure(fg_color="transparent",
                                          text_color=("#333333", "#cccccc"),
                                          border_width=1)

    def _float_set_bottom(self):
        """置底：不再强制置顶，可被其他窗口遮挡。"""
        self._floating_win.attributes("-topmost", False)
        self._float_bottom_btn.configure(fg_color="#0067c0", text_color="#ffffff",
                                          border_width=0)
        self._float_top_btn.configure(fg_color="transparent",
                                       text_color=("#333333", "#cccccc"),
                                       border_width=1)

    # ---- 折叠展开 ----
    def _toggle_float_fold(self):
        """折叠/展开悬浮窗的白色内容区。"""
        if not hasattr(self, "_float_collapsed"):
            self._float_collapsed = False
        self._float_collapsed = not self._float_collapsed
        x = self._floating_win.winfo_x()
        y = self._floating_win.winfo_y()
        w = self._float_init_width
        if self._float_collapsed:
            self._float_list.pack_forget()
            self._float_fold_btn.configure(text="▼")
            self._floating_win.geometry(f"{w}x32+{x}+{y}")
        else:
            self._float_list.pack(fill="both", expand=True, padx=4, pady=(0, 6))
            self._float_fold_btn.configure(text="▲")
            self._floating_win.geometry(f"{w}x{self._float_full_height}+{x}+{y}")
        self.after(50, self._apply_float_rounded)

    def _float_new_task(self):
        """从悬浮窗新建任务：弹出新建任务对话框。"""
        self._float_popup_panel.place_forget()
        NewTaskDialog(self, self.store, on_saved=self._on_new_task_saved)

    def _on_new_task_saved(self):
        """新建任务保存后的回调。"""
        self.refresh_tasks()
        self._refresh_floating()

    def _on_float_right_click(self, event):
        """右击任务项弹出上下文菜单。"""
        idx = self._float_list.nearest(event.y)
        if 0 <= idx < len(self._float_task_ids):
            self._float_list.selection_clear(0, tk.END)
            self._float_list.selection_set(idx)
            self._float_context_idx = idx
            self._float_context_menu.tk_popup(event.x_root, event.y_root)

    def _float_ctx_toggle_complete(self):
        """右击菜单的完成/取消完成——类似隐藏多选框的切换。"""
        idx = getattr(self, "_float_context_idx", None)
        if idx is None or idx >= len(self._float_task_ids):
            return
        task_id = self._float_task_ids[idx]
        task = self.store.get_task(task_id)
        if task is None:
            return
        if task.completed:
            self.store.uncomplete_task(task_id)
        else:
            self.store.complete_task(task_id)
        self.refresh_tasks()
        self._refresh_floating()

    def _float_ctx_edit(self):
        """右键编辑悬浮窗中的任务。"""
        idx = getattr(self, "_float_context_idx", None)
        if idx is not None and idx < len(self._float_task_ids):
            task_id = self._float_task_ids[idx]
            task = self.store.get_task(task_id)
            if task:
                self.selected_task_id = task.id
                self.editing_task_id = task.id
                NewTaskDialog(self, self.store, on_saved=self._on_new_task_saved,
                              prefill_date=task.due_date,
                              prefill_task_id=task.id)

    def _float_ctx_delete(self):
        idx = getattr(self, "_float_context_idx", None)
        if idx is not None and idx < len(self._float_task_ids):
            task_id = self._float_task_ids[idx]
            if messagebox.askyesno("确认", "确定删除此任务？"):
                self.store.delete_task(task_id)
                self.refresh_tasks()
                self._refresh_floating()

    def _toggle_floating(self):
        if self._floating_win.winfo_ismapped():
            self._floating_win.withdraw()
        else:
            self._refresh_floating()
            self._floating_win.deiconify()
            self.after(50, self._apply_float_rounded)

    def _on_float_dblclick(self, event):
        sel = self._float_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._float_task_ids):
            self._complete_by_id(self._float_task_ids[idx])

    def _float_drag_start(self, event):
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def _float_drag_move(self, event):
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        x = self._floating_win.winfo_x() + dx
        y = self._floating_win.winfo_y() + dy
        self._floating_win.geometry(f"+{x}+{y}")
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    # ==================================================================
    # 数据刷新
    # ==================================================================

    def refresh_tasks(self):
        self.tree.delete(*self.tree.get_children())
        day = self.date_var.get() or date.today().isoformat()
        search = self.search_var.get().strip()

        tasks = self.store.list_tasks(day=day, search=search)
        for task in tasks:
            iid = str(task.id)
            values = (
                task.due_time or "--:--",
                task.title,
                "✓" if task.completed else "",
            )
            tags = ("completed",) if task.completed else ()
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)

        self.tree.tag_configure("completed", foreground="#aaaaaa",
                                font=("Segoe UI", 13, "overstrike"))

        if self.selected_task_id is not None:
            if str(self.selected_task_id) in self.tree.get_children():
                self.tree.selection_set(str(self.selected_task_id))

    def _refresh_floating(self):
        if not hasattr(self, "_float_list"):
            return
        self._float_list.delete(0, tk.END)
        self._float_task_ids.clear()
        today = date.today().isoformat()
        tasks = self.store.list_tasks(day=today)

        for task in tasks:
            prefix = "☑ " if task.completed else "☐ "
            if task.due_time:
                bell = "🔔 " if task.remind else ""
                time_part = f"  {bell}{task.due_time}"
            else:
                time_part = ""
            text = f"{prefix}{task.title}{time_part}"
            self._float_list.insert(tk.END, text)
            self._float_task_ids.append(task.id)
            if task.completed:
                self._float_list.itemconfig(tk.END, fg="#aaaaaa")

    # ==================================================================
    # 交互回调
    # ==================================================================

    def _on_cal_right_click(self, date_str: str):
        """日历右键：弹出新建任务对话框，预填该日期。"""
        self.date_var.set(date_str)
        NewTaskDialog(self, self.store, on_saved=self._on_new_task_saved,
                      prefill_date=date_str)

    def _on_cal_date(self, date_str: str):
        """日历点击回调：设置日期并刷新任务列表。"""
        self.date_var.set(date_str)
        self.selected_task_id = None
        self.editing_task_id = None
        self.search_var.set("")
        self.refresh_tasks()
        """日历点击回调：设置日期并刷新任务列表。"""
        self.date_var.set(date_str)
        self.selected_task_id = None
        self.editing_task_id = None
        self.search_var.set("")
        self.refresh_tasks()

    def _on_select(self, event):
        """任务列表选中回调。"""
        selected = self.tree.selection()
        if not selected:
            return
        task_id = int(selected[0])
        self.selected_task_id = task_id
        task = self.store.get_task(task_id)
        if task:
            self.editing_task_id = task.id
            self.date_var.set(task.due_date)
            self.time_var.set(task.due_time)

    def _complete_by_id(self, task_id: int):
        self.store.complete_task(task_id)
        self.refresh_tasks()
        self._refresh_floating()

    # ==================================================================
    # 铃声提醒
    # ==================================================================

    def _start_reminder_timer(self):
        """每 30 秒检查一次是否有需要提醒的任务。"""
        self._check_reminders()
        self.after(30000, self._start_reminder_timer)

    def _check_reminders(self):
        """检查今天有待提醒的任务，播放系统提示音 + 弹出提醒窗口。"""
        from datetime import datetime

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        now_time = now.strftime("%H:%M")

        tasks = self.store.list_tasks(day=today_str)
        for task in tasks:
            if not task.remind or not task.due_time or task.completed:
                continue
            if task.id in self._reminded_today:
                continue
            if task.due_time == now_time:
                self._reminded_today.add(task.id)
                # 播放系统提示音
                try:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass
                # 弹出提醒小窗
                self._show_reminder_popup(task)

    def _show_reminder_popup(self, task: Task):
        """显示一个自动消失的提醒弹窗。"""
        popup = ctk.CTkToplevel(self)
        popup.title("流光笺 提醒")
        popup.geometry("360x140")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.transient(self)

        ctk.CTkLabel(popup, text="🔔  任务提醒",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=28, pady=(20, 8))

        ctk.CTkLabel(popup, text=f"{task.title}",
                     font=ctk.CTkFont(size=14)).pack(
            anchor="w", padx=28)

        time_info = f"⏰ {task.due_time}" if task.due_time else ""
        ctk.CTkLabel(popup, text=time_info,
                     font=ctk.CTkFont(size=12),
                     text_color=("#777777", "#999999")).pack(
            anchor="w", padx=28, pady=(4, 10))

        ctk.CTkButton(popup, text="知道了", width=90, height=30,
                      corner_radius=8,
                      command=popup.destroy).pack(pady=(0, 16))

        # 8 秒后自动关闭
        popup.after(8000, popup.destroy)


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")
    app = TaskTrackerApp()
    app.mainloop()
