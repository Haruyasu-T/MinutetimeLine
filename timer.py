#!/usr/bin/env python3
"""MinutetimeLine — 総分数:秒表示のタイムラインタイマー（区間管理）"""

import copy
import json
import os
import re
import sys
import math as _math
import datetime as _dt
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import threading
import time as _time_mod

try:
    import winsound as _winsound
    _SOUND_AVAILABLE = True
except ImportError:
    _winsound = None
    _SOUND_AVAILABLE = False

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PALETTE = [
    "#E74C3C", "#3498DB", "#2ECC71", "#F1C40F",
    "#9B59B6", "#1ABC9C", "#E67E22", "#EC407A",
    "#00BCD4", "#FF7043",
]
REMAIN_COLOR = "#556677"
MIN_SEG_SEC  = 1

PRECISION: dict[str, Tuple[str, int, int]] = {
    "秒":     ("s",  1000, 84),
    "1/10秒": ("ds",  100, 72),
    "1/100秒":("cs",   10, 62),
}

# 表示領域サイズ: (フォント倍率, サークルキャンバス高さ)
DISP_SIZE_CFG: dict[str, Tuple[float, int]] = {
    "小": (0.65, 240),
    "中": (1.00, 360),
    "大": (1.40, 480),
}

# タイムラインバーは常にこの間隔で再描画（精度設定に関わらず滑らか）
REDRAW_MS = 50

ALERT_FLASH = {
    # カウントゼロ: アプリ全体をオーバーレイで点滅（赤→消える→赤…）
    "complete": {
        "colors":   ["#cc2222"],   # オーバーレイ表示色（赤）
        "interval": 400, "count": 2, "loop": True,
    },
    "segment":  {"interval": 200, "loop": False},   # 色は区間ごとに動的に決定
}

ALERT_SOUND = {
    "complete": [(1400, 80), (0, 50), (1400, 80), (0, 50), (1200, 600)],
}

# --- 実行形態に応じた基準ディレクトリ ---
# PyInstaller で .exe 化した場合:
#   - 書き込むユーザーデータ(JSON)は exe と同じ場所（一時展開フォルダは毎回消えるため）
#   - 同梱リソース(timer.ico)は展開先の sys._MEIPASS から読む
if getattr(sys, "frozen", False):
    DATA_DIR     = Path(sys.executable).parent                       # exe のある場所
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR))          # 同梱リソース展開先
else:
    DATA_DIR     = Path(__file__).parent
    RESOURCE_DIR = Path(__file__).parent

SETTINGS_PATH = DATA_DIR / "timer_settings.json"
PRESETS_PATH  = DATA_DIR / "timer_presets.json"
STATS_PATH    = DATA_DIR / "timer_stats.json"
ICON_PATH     = RESOURCE_DIR / "timer.ico"


def read_source(data_path: Path) -> Optional[Path]:
    """読み込み元のパスを返す。ユーザーデータ(data_path)が無ければ、
    exe に同梱した既定ファイル(RESOURCE_DIR)へフォールバックする。
    どちらも無ければ None。書き込みは常に data_path 側へ行う。"""
    if data_path.exists():
        return data_path
    bundled = RESOURCE_DIR / data_path.name
    if bundled != data_path and bundled.exists():
        return bundled
    return None


_SAFE_COLOR_RE = re.compile(r"^#?[0-9A-Za-z]+$")


def safe_color(c) -> bool:
    """tk.eval に色を文字列展開する前の検証。16進(#RRGGBB)や名前付き色のみ許可し、
    Tcl のメタ文字（空白・中括弧・角括弧・$・; 等）を含む値を弾く。
    色は設定/プリセットの JSON から読み込まれるため、不正な値による Tcl 注入を防ぐ。"""
    return isinstance(c, str) and bool(_SAFE_COLOR_RE.match(c))

# キーボードショートカット一覧（? キーで表示）
SHORTCUTS = [
    ("Space", "スタート / 一時停止"),
    ("R", "リセット"),
    ("N", "次の区間へスキップ"),
    ("P / B", "前の区間へスキップ"),
    ("C", "コンパクト表示の切替"),
    ("F", "フラット / サークル切替"),
    ("?", "このショートカット一覧"),
    ("ホイール(分の桁)", "区間/総時間を ±1分"),
    ("ホイール(秒の桁)", "区間/総時間を ±1秒"),
    ("Shift+ホイール", "±10 単位"),
    ("行を ⠿ でドラッグ", "区間の並べ替え"),
]


# ── 多言語化（日本語キー → 各言語） ──────────────────────────────────────────
# t(s): 日本語の文字列を現在言語に変換（未登録は日本語のままフォールバック）
# untr(s): 表示文字列を日本語キーへ逆変換（セグメントボタンの値→内部キー用）
_LANG = "ja"

TRANSLATIONS = {
    "en": {
        # 精度・サイズ・テーマ・スタイル（セグメントボタンの値）
        "秒": "sec", "1/10秒": "1/10s", "1/100秒": "1/100s",
        "小": "S", "中": "M", "大": "L",
        "自動": "Auto", "ライト": "Light", "ダーク": "Dark",
        "フラット": "Flat", "サークル": "Circle", "時刻": "Time",
        # メインボタン・ラベル
        "▶  スタート": "▶  Start", "↺  リセット": "↺  Reset",
        "⏸  一時停止": "⏸  Pause", "▶  再開": "▶  Resume",
        "総時間:": "Total:", "設定": "Apply", "⚙ 設定": "⚙ Settings",
        "表示精度:": "Precision:", "次区間 ⏭": "Next ⏭", "⏮ 前区間": "⏮ Prev",
        "点滅通知:": "Flash alert:", "区間終了": "Seg end",
        "🔊 音声": "🔊 Sound", "🔁 繰り返し": "🔁 Repeat",
        "🔔 鳴り続ける": "🔔 Keep ringing", "🔔 試聴": "🔔 Test", "💡 点滅": "💡 Flash",
        "🎵 音ファイル": "🎵 Sound file", "（ビープ音）": "(beep)",
        "表示設定:": "Display:", "サイズ:": "Size:",
        "コンパクト": "Compact", "経過時間": "Elapsed",
        "プリセット:": "Preset:", "読込": "Load", "保存": "Save", "削除": "Delete",
        "完了後に連結:": "Chain next:", "（なし）": "(none)",
        "📊 実績": "📊 Stats", "⌨ ヘルプ": "⌨ Help",
        "回(0=無限)": "× (0=∞)",
        "指定時刻に開始:": "Start at:", "予約": "Set", "予約解除": "Cancel",
        "🗕 閉じる時トレイへ": "🗕 Close to tray",
        "表示": "Show", "終了": "Quit",
        "予約を解除しました": "Schedule canceled",
        "HH:MM 形式で入力してください": "Enter time as HH:MM",
        "時刻が不正です": "Invalid time",
        "に開始を予約しました": "start scheduled",
        "▼  展開": "▼  Expand", "言語:": "Language:",
        # タイムライン・区間リスト
        "タイムライン": "Timeline",
        "仕切りをドラッグして区間サイズを変更": "Drag dividers to resize",
        "区間リスト": "Segments", "等分": "Even",
        "残り": "Left", "残り —": "Left —", "待機": "Idle", "進行中": "Active",
        "完了": "Done", "メモ": "Memo",
        "＋ボタンで区間を追加してください。": "Click + to add a segment.",
        # ステータス・通知
        "保存しました": "Saved", "読み込みました": "Loaded",
        "削除しました": "Deleted", "保存失敗": "Save failed", "読込失敗": "Load failed",
        "回": "times",
        "この環境では音を再生できません": "Sound is unavailable on this system",
        "タイマーが完了しました": "Timer finished",
        # ダイアログ
        "プリセット名を入力してください:": "Enter a preset name:",
        "プリセットを保存": "Save preset",
        "プリセットを選択してください": "Please select a preset",
        "削除するプリセットを選択してください": "Select a preset to delete",
        "色を選択": "Choose color", "点滅色を選択": "Choose flash color",
        "完了音の .wav を選択": "Choose completion .wav",
        "WAV ファイル": "WAV files", "すべて": "All files",
        # 実績
        "実績": "Stats", "📊  実績": "📊  Stats",
        "今日の完了回数": "Today's count", "今日の合計時間": "Today's total",
        "累計完了回数": "All-time count", "累計合計時間": "All-time total",
        "最近の記録": "Recent", "ログを消去": "Clear log",
        "実績をすべて消去しますか？": "Clear all stats?",
        # ショートカット説明
        "キーボードショートカット": "Keyboard shortcuts",
        "⌨  キーボードショートカット": "⌨  Keyboard shortcuts",
        "スタート / 一時停止": "Start / Pause", "リセット": "Reset",
        "次の区間へスキップ": "Skip to next segment",
        "前の区間へスキップ": "Skip to previous segment",
        "コンパクト表示の切替": "Toggle compact view",
        "フラット / サークル切替": "Toggle Flat / Circle",
        "このショートカット一覧": "This shortcut list",
        "ホイール(分の桁)": "Wheel (minute digit)", "区間/総時間を ±1分": "Segment/total ±1 min",
        "ホイール(秒の桁)": "Wheel (second digit)", "区間/総時間を ±1秒": "Segment/total ±1 sec",
        "Shift+ホイール": "Shift+Wheel", "±10 単位": "×10 step",
        "行を ⠿ でドラッグ": "Drag a row by ⠿", "区間の並べ替え": "Reorder segments",
    },
}


def set_lang(lang: str):
    global _LANG
    _LANG = lang if lang in ("ja", "en") else "ja"


def t(s: str) -> str:
    """日本語キー s を現在言語に変換（未登録なら s をそのまま返す）"""
    if _LANG == "ja":
        return s
    return TRANSLATIONS.get(_LANG, {}).get(s, s)


def untr(s: str) -> str:
    """表示文字列 s を日本語キーへ逆変換（セグメントボタン値→内部キー）"""
    if _LANG == "ja":
        return s
    for ja, loc in TRANSLATIONS.get(_LANG, {}).items():
        if loc == s:
            return ja
    return s


def darken(hex_color: str, factor: float = 0.4) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def fmt(secs: int) -> str:
    m, s = divmod(max(0, secs), 60)
    return f"{m}:{s:02d}"


def fmt_main(ms: int, code: str) -> str:
    ms = max(0, ms)
    m, s = divmod(ms // 1000, 60)
    if code == "s":
        return f"{m}:{s:02d}"
    if code == "ds":
        return f"{m}:{s:02d}.{(ms % 1000) // 100}"
    return f"{m}:{s:02d}.{(ms % 1000) // 10:02d}"


def fmt_hms(ms: int) -> str:
    total_s = max(0, ms) // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if _LANG == "en":
        if h > 0:
            return f"({h}h {m}m {s}s)"
        if m > 0:
            return f"({m}m {s}s)"
        return f"({s}s)"
    if h > 0:
        return f"({h}時間 {m}分 {s}秒)"
    if m > 0:
        return f"({m}分 {s}秒)"
    return f"({s}秒)"


def dur_str(secs: int) -> str:
    m, s = divmod(max(0, secs), 60)
    return f"{m}:{s:02d}"


def parse_dur(text: str) -> int:
    text = text.strip()
    if text.lower().endswith("s"):
        return round(float(text[:-1]))
    if ":" in text:
        left, right = text.split(":", 1)
        m = int(left) if left.strip() else 0
        s = int(right.strip()) if right.strip() else 0
        return m * 60 + s
    return round(float(text) * 60)


@dataclass
class Segment:
    name: str
    duration_seconds: int
    color: str
    memo: str = ""        # 区間のメモ／タスク名（任意）


@dataclass
class WarnThreshold:
    enabled: bool
    seconds: int
    count: int
    color: str


_DEFAULT_WARNS = [
    WarnThreshold(True, 30, 2, "#ccaa00"),   # 黄  （30秒前）
    WarnThreshold(True, 10, 4, "#dd6600"),   # 橙  （10秒前）
]
# カウントゼロ: #cc2222（赤） → 黄→橙→赤 の3段階で緊急度を表現


class TimerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MinutetimeLine")
        self.geometry("920x800")
        self._min_w = 700        # 通常時の最小幅（起動後にコントロール幅から自動調整）
        self._min_h = 560        # コントロール部はスクロール可能なので低めでもボタンに到達可
        self.minsize(self._min_w, self._min_h)
        if ICON_PATH.exists():
            try:
                self.iconbitmap(str(ICON_PATH))
            except Exception:
                pass
            # Windows ではタスクバー/Alt-Tab 用に高解像度アイコンを直接設定する。
            # iconbitmap だけだと低解像度の画像が使われ、高DPIで荒く見えるため。
            self.after(0, self._apply_hires_icon)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._segments: List[Segment] = []
        self._total_sec: int = 3600
        self._elapsed_ms: int = 0
        self._prec_code: str = "s"
        self._running: bool = False
        self._after_id: Optional[str] = None
        self._wall_start: float = 0.0   # 直近のスタート/再開時の壁時計
        self._ms_at_start: int = 0      # 直近のスタート/再開時の _elapsed_ms

        self._drag_div: Optional[int] = None
        self._drag_start_x: int = 0
        self._drag_seg_secs: List[int] = []
        self._divider_xs: List[int] = []

        self._row_dur_vars: List[ctk.StringVar] = []
        self._row_rem_lbls: List[ctk.CTkLabel] = []
        self._row_sts_lbls: List[ctk.CTkLabel] = []
        self._row_frames: List = []          # 区間行フレーム（ドラッグ並べ替え用）
        self._drag_seg_from: Optional[int] = None   # ドラッグ開始の区間index

        self._warn_thresholds: List[WarnThreshold] = copy.deepcopy(_DEFAULT_WARNS)
        self._sv_sound   = ctk.BooleanVar(value=True)
        self._sv_segment = ctk.BooleanVar(value=True)
        self._sv_repeat  = ctk.BooleanVar(value=False)
        self._repeat_max_var = ctk.StringVar(value="0")    # 繰り返し回数上限（0=無限）
        self._sv_loop_alarm = ctk.BooleanVar(value=False)  # 完了音を止めるまで鳴らす
        self._alarm_stop = threading.Event()               # ループ音停止フラグ
        self._sv_countup = ctk.BooleanVar(value=False)     # 残り時間ではなく経過時間を表示
        self._settings_open = False                         # 設定項目の開閉状態
        self._custom_sound_path = ""                        # 完了音に使う .wav（空=ビープ）
        self._next_preset = ""                              # 完了後に自動連結するプリセット名
        self._sv_tray = ctk.BooleanVar(value=False)        # 閉じる時トレイへ最小化
        self._tray_icon = None                              # pystray アイコン
        self._sched_var = ctk.StringVar(value="")          # 指定時刻スタート(HH:MM)
        self._sched_after_id = None                         # 予約スタートの after id
        # 言語は UI 構築前に反映する必要があるため、設定ファイルから先読みする
        self._lang = "ja"
        try:
            _src = read_source(SETTINGS_PATH)
            if _src:
                _d = json.loads(_src.read_text(encoding="utf-8"))
                self._lang = _d.get("language", "ja")
        except Exception:
            self._lang = "ja"
        set_lang(self._lang)
        self._circle_cfg_job: Optional[str] = None         # リサイズ時のサークル再描画デバウンス
        self._timeline_cfg_job: Optional[str] = None       # リサイズ時のタイムライン再描画デバウンス
        self._circle_size = (0, 0)                          # 前回描画したサークルキャンバスサイズ
        self._timeline_w = 0                                # 前回描画したタイムライン幅
        self._win_size = (0, 0)                             # 前回のウィンドウサイズ
        self._resizing = False                              # リサイズ中フラグ（重い再描画を抑制）
        self._resize_settle_job: Optional[str] = None       # リサイズ確定検出
        self._appearance_mode: str = "ダーク"
        self._repeat_count: int = 0       # 完了した回数（自動再スタートをまたいで加算）
        self._repeat_after_id: Optional[str] = None  # 再スタート予約
        self._warned: set = set()
        self._active_seg_idx: int = -1
        self._flash_job: Optional[str] = None
        self._flash_wall_start: float = 0.0   # 点滅開始の壁時計（ドリフト補正用）
        self._disp_default_color = None
        self._warn_row_widgets: List[dict] = []
        self._presets: list = []
        self._preset_var = ctk.StringVar(value="")
        self._style_mode: str = "フラット"
        self._circle_num_mode: str = "時刻"
        self._disp_size: str = "中"
        self._circle_flash_on: bool = False
        self._circle_flash_color: str = ""
        self._sv_compact = ctk.BooleanVar(value=False)
        self._is_compact: bool = False
        self._normal_geometry: str = ""

        self._build_ui()
        self._disp_default_color = self._disp_frame.cget("fg_color")
        # カウントゼロ点滅用: (canvas, 元bg, 元inner_parts_fill) のリスト
        self._flash_canvases: list = []

        # 起動時に設定・プリセットを自動読込（失敗しても無視）
        self._load_settings(silent=True)
        self._load_presets()
        self._rebuild_rows()
        self._rebuild_warn_rows()
        self._refresh_display()
        # ウィンドウ全体のクリックでフラッシュ停止（サークルモード含む）
        self.bind("<Button-1>", self._on_disp_click, add="+")
        # キーボードショートカット（入力欄にフォーカス中は無効）
        self.bind_all("<space>", self._on_space_key)
        self.bind_all("<Key>", self._on_key)
        # ウィンドウのドラッグリサイズ中は重い再描画を抑制し、確定後に一度だけ描画
        self.bind("<Configure>", self._on_window_configure, add="+")
        # コントロール部の必要幅に合わせて最小幅を自動調整（ボタンが見切れないように）
        self.after(400, self._adjust_min_width)

    @property
    def _elapsed_sec(self) -> int:
        return self._elapsed_ms // 1000

    @property
    def _total_ms(self) -> int:
        return self._total_sec * 1000

    # ── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        # 区間リスト(row2)が伸縮。コントロール(row3)は自然高さ（設定は折りたたみ可）
        self.grid_rowconfigure(2, weight=1, minsize=110)   # 区間リスト

        # 時間表示フレーム（フラッシュ対象・クリックでフラッシュ停止）
        self._disp_frame = ctk.CTkFrame(self, corner_radius=14)
        self._disp_frame.grid(row=0, column=0, padx=20, pady=(20, 8), sticky="ew")
        self._disp_frame.grid_columnconfigure(0, weight=1)

        self._time_lbl = ctk.CTkLabel(
            self._disp_frame, text=fmt_main(self._total_ms, self._prec_code),
            font=ctk.CTkFont(size=84, weight="bold"),
        )
        self._time_lbl.grid(row=0, column=0, pady=(18, 0))

        self._breakdown_lbl = ctk.CTkLabel(
            self._disp_frame, text=fmt_hms(self._total_ms),
            font=ctk.CTkFont(size=14), text_color=("gray10", "gray55")
        )
        self._breakdown_lbl.grid(row=1, column=0, pady=(2, 4))

        self._phase_lbl = ctk.CTkLabel(
            self._disp_frame, text="", font=ctk.CTkFont(size=15), text_color=("gray20", "gray65")
        )
        self._phase_lbl.grid(row=2, column=0, pady=(0, 16))

        # サークル表示用キャンバス（フラットモードでは非表示）
        self._circle_canvas = tk.Canvas(
            self._disp_frame, height=360, bg="#1e1e2e", highlightthickness=0)
        self._circle_canvas.bind("<Configure>", self._on_circle_configure)
        self._circle_canvas.bind("<Button-1>", self._on_disp_click)
        # 初期は非表示（grid しない）

        # 表示エリアのクリックでフラッシュ停止
        for w in (self._disp_frame, self._time_lbl, self._breakdown_lbl, self._phase_lbl):
            w.bind("<Button-1>", self._on_disp_click)

        # タイムライン
        self._tl_frame = ctk.CTkFrame(self, corner_radius=14)
        tl = self._tl_frame
        tl.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        tl.grid_columnconfigure(0, weight=1)

        hdr_tl = ctk.CTkFrame(tl, fg_color="transparent")
        self._tl_header = hdr_tl
        hdr_tl.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="ew")
        hdr_tl.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr_tl, text=t("タイムライン"),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray25", "gray70")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hdr_tl, text=t("仕切りをドラッグして区間サイズを変更"),
                     font=ctk.CTkFont(size=11), text_color=("gray10", "gray55")).grid(row=0, column=1, sticky="e")

        self._canvas = tk.Canvas(tl, height=60, bg="#1e1e2e", highlightthickness=0)
        self._canvas.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        self._canvas.bind("<Configure>", self._on_timeline_configure)
        self._canvas.bind("<Motion>", self._on_canvas_motion)
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        # 区間パネル
        sp = ctk.CTkFrame(self, corner_radius=14)
        self._seg_panel = sp
        sp.grid(row=2, column=0, padx=20, pady=8, sticky="nsew")
        sp.grid_columnconfigure(0, weight=1)
        sp.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(sp, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text=t("区間リスト"),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray25", "gray70")).grid(row=0, column=0, sticky="w")

        cnt_row = ctk.CTkFrame(hdr, fg_color="transparent")
        cnt_row.grid(row=0, column=1)
        ctk.CTkButton(cnt_row, text="－", width=36, height=32,
                      command=self._remove_segment).pack(side="left", padx=2)
        self._cnt_lbl = ctk.CTkLabel(cnt_row, text="0", width=32,
                                      font=ctk.CTkFont(size=14, weight="bold"))
        self._cnt_lbl.pack(side="left")
        ctk.CTkButton(cnt_row, text="＋", width=36, height=32,
                      command=self._add_segment).pack(side="left", padx=2)
        ctk.CTkButton(cnt_row, text=t("等分"), width=52, height=32,
                      fg_color="#2471a3", hover_color="#1a5276",
                      command=self._equalize).pack(side="left", padx=(10, 2))

        self._scroll = ctk.CTkScrollableFrame(sp)
        self._scroll.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        # コントロール
        ctrl = ctk.CTkFrame(self, corner_radius=14)
        self._ctrl_frame = ctrl
        ctrl.grid(row=3, column=0, padx=20, pady=(8, 20), sticky="ew")
        ctrl.grid_columnconfigure(2, weight=1)
        ctrl.grid_rowconfigure(1, weight=1)   # 設定フレームが縦に伸びる/縮む

        # 行0: 総時間 + ボタン + 保存/読込
        ctk.CTkLabel(ctrl, text=t("総時間:")).grid(
            row=0, column=0, padx=(16, 4), pady=(12, 6))
        self._total_var = ctk.StringVar(value="60:00")
        total_entry = ctk.CTkEntry(ctrl, textvariable=self._total_var, width=80)
        total_entry.grid(row=0, column=1, pady=(12, 6))
        total_entry.bind("<Return>", lambda _: self._apply_total())
        # ホイールで総時間を増減（分の位置=±1分 / 秒の位置=±1秒、Shiftで×10）
        total_entry._entry.bind("<MouseWheel>", self._on_total_wheel)
        ctk.CTkButton(ctrl, text=t("設定"), width=60, command=self._apply_total).grid(
            row=0, column=2, padx=(6, 0), pady=(12, 6), sticky="w")

        self._start_btn = ctk.CTkButton(
            ctrl, text=t("▶  スタート"), width=140,
            fg_color="#27ae60", hover_color="#1e8449",
            command=self._toggle,
        )
        self._start_btn.grid(row=0, column=3, padx=8, pady=(12, 6), sticky="e")

        ctk.CTkButton(
            ctrl, text=t("↺  リセット"), width=120,
            fg_color="#d35400", hover_color="#a04000",
            command=self._reset,
        ).grid(row=0, column=4, padx=(0, 8), pady=(12, 6))

        # ⚙ 設定の開閉ボタン
        self._settings_btn = ctk.CTkButton(
            ctrl, text=t("⚙ 設定"), width=72,
            fg_color="gray35", hover_color="gray25",
            command=self._toggle_settings,
        )
        self._settings_btn.grid(row=0, column=5, padx=(0, 16), pady=(12, 6))

        # 設定項目（折りたたみ可能なコンテナ。⚙で開閉。
        # 窓を縮めたときは項目が消えずスクロールで到達できるようスクロール可能フレーム）
        sf = ctk.CTkScrollableFrame(ctrl, fg_color="transparent")
        self._settings_frame = sf
        sf.grid(row=1, column=0, columnspan=7, sticky="nsew")
        sf.grid_columnconfigure(2, weight=1)
        sf.grid_remove()   # 初期は隠す

        # 表示精度（左） + 区間スキップ（右）を pack で1行に配置
        ps = ctk.CTkFrame(sf, fg_color="transparent")
        ps.grid(row=0, column=0, columnspan=7, padx=14, pady=(4, 4), sticky="ew")
        ctk.CTkLabel(ps, text=t("表示精度:")).pack(side="left", padx=(2, 4))
        self._prec_btn = ctk.CTkSegmentedButton(
            ps, values=[t(k) for k in PRECISION.keys()],
            command=self._on_precision_change,
        )
        self._prec_btn.set(t("秒"))
        self._prec_btn.pack(side="left", padx=(0, 8))
        # スキップは右寄せ。side="right" は先に pack した方が右端なので 次区間→前区間 の順
        ctk.CTkButton(ps, text=t("次区間 ⏭"), width=84, height=28,
                      fg_color="gray35", hover_color="gray25",
                      command=lambda: self._skip_segment(1)).pack(side="right", padx=(3, 2))
        ctk.CTkButton(ps, text=t("⏮ 前区間"), width=84, height=28,
                      fg_color="gray35", hover_color="gray25",
                      command=lambda: self._skip_segment(-1)).pack(side="right", padx=3)

        # 通知ヘッダー（横が長いので2段に折り返す）
        notif_hdr = ctk.CTkFrame(sf, fg_color="transparent")
        notif_hdr.grid(row=1, column=0, columnspan=7, padx=14, pady=(4, 2), sticky="ew")
        n1 = ctk.CTkFrame(notif_hdr, fg_color="transparent"); n1.pack(side="top", anchor="w")
        n2 = ctk.CTkFrame(notif_hdr, fg_color="transparent"); n2.pack(side="top", anchor="w", pady=(2, 0))

        ctk.CTkLabel(n1, text=t("点滅通知:"), text_color=("gray25", "gray70"),
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(n1, text="＋", width=30, height=24,
                      command=self._add_warn).pack(side="left", padx=2)
        ctk.CTkButton(n1, text="－", width=30, height=24,
                      command=self._remove_warn).pack(side="left", padx=2)
        ctk.CTkLabel(n1, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(10, 6))
        ctk.CTkCheckBox(n1, text=t("区間終了"), variable=self._sv_segment,
                        checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(n1, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(4, 6))
        ctk.CTkSwitch(n1, text=t("🔊 音声"), variable=self._sv_sound).pack(side="left", padx=4)
        ctk.CTkLabel(n1, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkSwitch(n1, text=t("🔁 繰り返し"), variable=self._sv_repeat,
                      button_color="#e67e22", progress_color="#e67e22").pack(side="left", padx=4)
        ctk.CTkEntry(n1, textvariable=self._repeat_max_var, width=40, height=24,
                     justify="center").pack(side="left", padx=(4, 2))
        ctk.CTkLabel(n1, text=t("回(0=無限)"), font=ctk.CTkFont(size=11),
                     text_color=("gray15", "gray60")).pack(side="left")

        ctk.CTkSwitch(n2, text=t("🔔 鳴り続ける"), variable=self._sv_loop_alarm,
                      button_color="#c0392b", progress_color="#c0392b").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(n2, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkButton(n2, text=t("🔔 試聴"), width=64, height=24,
                      fg_color="gray35", hover_color="gray25",
                      command=self._preview_sound).pack(side="left", padx=2)
        ctk.CTkButton(n2, text=t("💡 点滅"), width=64, height=24,
                      fg_color="gray35", hover_color="gray25",
                      command=self._preview_flash).pack(side="left", padx=2)
        ctk.CTkLabel(n2, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkButton(n2, text=t("🎵 音ファイル"), width=92, height=24,
                      fg_color="gray35", hover_color="gray25",
                      command=self._pick_sound).pack(side="left", padx=2)
        self._sound_lbl = ctk.CTkLabel(n2, text=t("（ビープ音）"),
                                       font=ctk.CTkFont(size=11),
                                       text_color=("gray20", "gray60"))
        self._sound_lbl.pack(side="left", padx=(2, 0))
        ctk.CTkButton(n2, text="✕", width=24, height=24,
                      fg_color="gray35", hover_color="gray25",
                      command=self._clear_sound).pack(side="left", padx=(4, 0))

        # 表示設定（横が長いので2段に折り返す）
        disp_hdr = ctk.CTkFrame(sf, fg_color="transparent")
        disp_hdr.grid(row=2, column=0, columnspan=7, padx=14, pady=(2, 2), sticky="ew")
        d1 = ctk.CTkFrame(disp_hdr, fg_color="transparent"); d1.pack(side="top", anchor="w")
        d2 = ctk.CTkFrame(disp_hdr, fg_color="transparent"); d2.pack(side="top", anchor="w", pady=(2, 0))

        ctk.CTkLabel(d1, text=t("表示設定:"), text_color=("gray25", "gray70"),
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
        self._theme_btn = ctk.CTkSegmentedButton(
            d1,
            values=[t("自動"), t("ライト"), t("ダーク")],
            command=self._on_appearance_change,
            height=24, font=ctk.CTkFont(size=12),
        )
        self._theme_btn.set(t("ダーク"))
        self._theme_btn.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(d1, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(4, 6))
        self._style_btn = ctk.CTkSegmentedButton(
            d1,
            values=[t("フラット"), t("サークル")],
            command=self._on_style_change,
            height=24, font=ctk.CTkFont(size=12),
        )
        self._style_btn.set(t("フラット"))
        self._style_btn.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(d1, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(4, 6))
        self._num_mode_btn = ctk.CTkSegmentedButton(
            d1,
            values=[t("時刻"), "%"],
            command=self._on_num_mode_change,
            height=24, font=ctk.CTkFont(size=12),
        )
        self._num_mode_btn.set(t("時刻"))
        self._num_mode_btn.pack(side="left", padx=4)

        ctk.CTkLabel(d2, text=t("サイズ:"), text_color=("gray10", "gray80"),
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self._disp_size_btn = ctk.CTkSegmentedButton(
            d2,
            values=[t("小"), t("中"), t("大")],
            command=self._on_disp_size_change,
            height=24, font=ctk.CTkFont(size=12),
        )
        self._disp_size_btn.set(t("中"))
        self._disp_size_btn.pack(side="left", padx=4)

        ctk.CTkLabel(d2, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkSwitch(d2, text=t("コンパクト"), variable=self._sv_compact,
                      command=self._on_compact_toggle,
                      font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        ctk.CTkLabel(d2, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkSwitch(d2, text=t("経過時間"), variable=self._sv_countup,
                      command=lambda: self._refresh_display(),
                      font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        ctk.CTkLabel(d2, text="│", text_color=("gray10", "gray40")).pack(side="left", padx=(8, 6))
        ctk.CTkLabel(d2, text=t("言語:"), text_color=("gray10", "gray80"),
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self._lang_btn = ctk.CTkSegmentedButton(
            d2, values=["日本語", "English"], command=self._on_lang_change,
            height=24, font=ctk.CTkFont(size=12))
        self._lang_btn.set("日本語" if _LANG == "ja" else "English")
        self._lang_btn.pack(side="left", padx=4)

        # 警告しきい値リスト（動的）
        self._warn_frame = ctk.CTkFrame(sf, fg_color="transparent")
        self._warn_frame.grid(row=3, column=0, columnspan=7, padx=14, pady=(0, 4), sticky="ew")

        # プリセット
        preset_row = ctk.CTkFrame(sf, fg_color="transparent")
        preset_row.grid(row=4, column=0, columnspan=7, padx=14, pady=(4, 12), sticky="ew")
        ctk.CTkLabel(preset_row, text=t("プリセット:"),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray25", "gray70")).pack(side="left", padx=(0, 8))
        self._preset_combo = ctk.CTkComboBox(
            preset_row, values=[], width=220,
            variable=self._preset_var,
        )
        self._preset_combo.set("")
        self._preset_combo.pack(side="left", padx=(0, 8))
        ctk.CTkButton(preset_row, text=t("読込"), width=58, height=30,
                      fg_color="#2471a3", hover_color="#1a5276",
                      command=self._preset_load).pack(side="left", padx=2)
        ctk.CTkButton(preset_row, text=t("保存"), width=58, height=30,
                      fg_color="#117a65", hover_color="#0e6655",
                      command=self._preset_save).pack(side="left", padx=2)
        ctk.CTkButton(preset_row, text=t("削除"), width=58, height=30,
                      fg_color="#922b21", hover_color="#7b241c",
                      command=self._preset_delete).pack(side="left", padx=2)

        # その他（自動連結・実績・ヘルプ）
        misc_row = ctk.CTkFrame(sf, fg_color="transparent")
        misc_row.grid(row=5, column=0, columnspan=7, padx=14, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(misc_row, text=t("完了後に連結:"), font=ctk.CTkFont(size=12),
                     text_color=("gray25", "gray70")).pack(side="left", padx=(0, 6))
        self._chain_combo = ctk.CTkComboBox(
            misc_row, values=[t("（なし）")], width=160,
            command=self._on_chain_change)
        self._chain_combo.set(t("（なし）"))
        self._chain_combo.pack(side="left", padx=(0, 12))
        ctk.CTkButton(misc_row, text=t("📊 実績"), width=72, height=28,
                      fg_color="#2471a3", hover_color="#1a5276",
                      command=self._show_stats).pack(side="left", padx=3)
        ctk.CTkButton(misc_row, text=t("⌨ ヘルプ"), width=80, height=28,
                      fg_color="gray35", hover_color="gray25",
                      command=self._show_shortcuts).pack(side="left", padx=3)

        # 予約スタート（指定時刻）＋ トレイ最小化
        sched_row = ctk.CTkFrame(sf, fg_color="transparent")
        sched_row.grid(row=6, column=0, columnspan=7, padx=14, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(sched_row, text=t("指定時刻に開始:"), font=ctk.CTkFont(size=12),
                     text_color=("gray25", "gray70")).pack(side="left", padx=(0, 6))
        ctk.CTkEntry(sched_row, textvariable=self._sched_var, width=70, height=28,
                     placeholder_text="HH:MM").pack(side="left", padx=(0, 4))
        self._sched_btn = ctk.CTkButton(sched_row, text=t("予約"), width=84, height=28,
                                        fg_color="#2471a3", hover_color="#1a5276",
                                        command=self._toggle_schedule)
        self._sched_btn.pack(side="left", padx=(0, 14))
        ctk.CTkSwitch(sched_row, text=t("🗕 閉じる時トレイへ"),
                      variable=self._sv_tray, font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        # コンパクトモード用バー（通常は非表示・2行構成）
        self._compact_bar = ctk.CTkFrame(self, corner_radius=10)
        # grid しない（_enter_compact で追加）
        self._compact_bar.grid_columnconfigure(0, weight=1)
        # 1行目: 区間名・残り時間・周回数を表示する情報ラベル（全幅・左寄せ）
        self._compact_info_lbl = ctk.CTkLabel(
            self._compact_bar, text="", anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("gray15", "gray85"),
        )
        self._compact_info_lbl.grid(row=0, column=0, columnspan=4,
                                    padx=14, pady=(6, 2), sticky="ew")
        # 2行目: 一時停止・リセット・展開ボタン（右寄せ、column0 が伸びて押し出す）
        self._compact_start_btn = ctk.CTkButton(
            self._compact_bar, text=t("⏸  一時停止"), width=100, height=28,
            fg_color="#e67e22", hover_color="#ca6f1e",
            command=self._toggle,
        )
        self._compact_start_btn.grid(row=1, column=1, padx=4, pady=(0, 8))
        ctk.CTkButton(
            self._compact_bar, text=t("↺  リセット"), width=90, height=28,
            fg_color="#d35400", hover_color="#a04000",
            command=self._reset,
        ).grid(row=1, column=2, padx=4, pady=(0, 8))
        ctk.CTkButton(
            self._compact_bar, text=t("▼  展開"), width=80, height=28,
            fg_color="transparent", border_width=1,
            text_color=("gray20", "gray80"),
            command=self._on_expand_click,
        ).grid(row=1, column=3, padx=(4, 12), pady=(0, 8))

    # ── 設定の保存・読込 ──────────────────────────────────────────────────────

    def _save_settings(self):
        data = {
            "total_sec": self._total_sec,
            "segments": [
                {"name": s.name, "duration_seconds": s.duration_seconds, "color": s.color, "memo": s.memo}
                for s in self._segments
            ],
            "warn_thresholds": [
                {"enabled": th.enabled, "seconds": th.seconds, "count": th.count, "color": th.color}
                for th in self._warn_thresholds
            ],
            "language": self._lang,
            "sound": self._sv_sound.get(),
            "segment_alert": self._sv_segment.get(),
            "repeat": self._sv_repeat.get(),
            "repeat_max": self._repeat_max(),
            "loop_alarm": self._sv_loop_alarm.get(),
            "countup": self._sv_countup.get(),
            "tray": self._sv_tray.get(),
            "settings_open": self._settings_open,
            "custom_sound": self._custom_sound_path,
            "next_preset": self._next_preset,
            "appearance": self._appearance_mode,
            "precision": untr(self._prec_btn.get()),
            "style": self._style_mode,
            "circle_num_mode": self._circle_num_mode,
            "disp_size": self._disp_size,
            "compact": self._sv_compact.get(),
        }
        try:
            SETTINGS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._flash_status(t("保存しました"))
        except Exception as e:
            self._flash_status(f"{t('保存失敗')}: {e}")

    def _load_settings(self, silent: bool = False):
        src = read_source(SETTINGS_PATH)
        if src is None:
            return
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            self._total_sec = int(data.get("total_sec", 3600))
            self._total_var.set(dur_str(self._total_sec))
            self._segments = [
                Segment(s["name"], int(s["duration_seconds"]), s["color"], s.get("memo", ""))
                for s in data.get("segments", [])
            ]
            warns = data.get("warn_thresholds", None)
            if warns:
                self._warn_thresholds = [
                    WarnThreshold(bool(w["enabled"]), int(w["seconds"]),
                                  int(w["count"]), w["color"])
                    for w in warns
                ]
            self._sv_sound.set(bool(data.get("sound", True)))
            self._sv_segment.set(bool(data.get("segment_alert", True)))
            self._sv_repeat.set(bool(data.get("repeat", False)))
            self._repeat_max_var.set(str(int(data.get("repeat_max", 0))))
            self._sv_loop_alarm.set(bool(data.get("loop_alarm", False)))
            self._sv_countup.set(bool(data.get("countup", False)))
            self._sv_tray.set(bool(data.get("tray", False)))
            self._custom_sound_path = data.get("custom_sound", "") or ""
            if self._custom_sound_path and os.path.exists(self._custom_sound_path):
                self._sound_lbl.configure(text=os.path.basename(self._custom_sound_path))
            else:
                self._custom_sound_path = ""
            self._next_preset = data.get("next_preset", "") or ""
            self.after(250, lambda v=bool(data.get("settings_open", False)):
                       self._toggle_settings(v))
            appearance = data.get("appearance", "ダーク")
            self._appearance_mode = appearance
            self._theme_btn.set(t(appearance))
            ctk.set_appearance_mode(self._APPEARANCE_MAP.get(appearance, "dark"))
            precision = data.get("precision", "秒")
            if precision in PRECISION:
                self._prec_btn.set(t(precision))
                self._on_precision_change(t(precision))
            style = data.get("style", "フラット")
            if style in ("フラット", "サークル"):
                self._style_mode = style
                self._style_btn.set(t(style))
                self.after(150, self._update_style_layout)
            num_mode = data.get("circle_num_mode", "時刻")
            if num_mode in ("時刻", "%"):
                self._circle_num_mode = num_mode
                self._num_mode_btn.set(t(num_mode))
            disp_size = data.get("disp_size", "中")
            if disp_size in DISP_SIZE_CFG:
                self._disp_size = disp_size
                self._disp_size_btn.set(t(disp_size))
                self.after(200, self._apply_disp_font)
            self._sv_compact.set(bool(data.get("compact", False)))
            self._rebuild_rows()
            self._rebuild_warn_rows()
            self._refresh_display()
            if not silent:
                self._flash_status(t("読み込みました"))
        except Exception as e:
            if not silent:
                self._flash_status(f"{t('読込失敗')}: {e}")

    # ── プリセット ────────────────────────────────────────────────────────────────

    def _load_presets(self):
        """timer_presets.json を読み込み、コンボボックスを更新する"""
        src = read_source(PRESETS_PATH)
        if src is not None:
            try:
                data = json.loads(src.read_text(encoding="utf-8"))
                self._presets = data if isinstance(data, list) else []
            except Exception:
                self._presets = []
        self._refresh_preset_combo()

    def _save_presets_file(self):
        try:
            PRESETS_PATH.write_text(
                json.dumps(self._presets, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _refresh_preset_combo(self):
        names = [p["name"] for p in self._presets]
        self._preset_combo.configure(values=names if names else [])
        cur = self._preset_var.get()
        if names and cur not in names:
            self._preset_combo.set(names[0])
        elif not names:
            self._preset_combo.set("")
        # 自動連結ドロップダウンも更新
        if hasattr(self, "_chain_combo"):
            self._chain_combo.configure(values=[t("（なし）")] + names)
            if self._next_preset and self._next_preset in names:
                self._chain_combo.set(self._next_preset)
            else:
                self._chain_combo.set(t("（なし）"))
                self._next_preset = ""

    def _preset_save(self):
        """現在の設定をプリセットとして保存（同名なら上書き確認なしで上書き）"""
        dialog = ctk.CTkInputDialog(
            text=t("プリセット名を入力してください:"), title=t("プリセットを保存"))
        name = dialog.get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        preset = {
            "name": name,
            "total_sec": self._total_sec,
            "segments": [
                {"name": s.name, "duration_seconds": s.duration_seconds, "color": s.color, "memo": s.memo}
                for s in self._segments
            ],
            "warn_thresholds": [
                {"enabled": th.enabled, "seconds": th.seconds,
                 "count": th.count, "color": th.color}
                for th in self._warn_thresholds
            ],
            "sound": self._sv_sound.get(),
            "repeat": self._sv_repeat.get(),
        }
        for i, p in enumerate(self._presets):
            if p["name"] == name:
                self._presets[i] = preset
                break
        else:
            self._presets.append(preset)
        self._save_presets_file()
        self._refresh_preset_combo()
        self._preset_combo.set(name)
        self._flash_status(f"「{name}」を保存しました")

    def _preset_load(self):
        """選択中のプリセットを読み込み、タイマー設定に反映する"""
        name = self._preset_combo.get()
        preset = next((p for p in self._presets if p["name"] == name), None)
        if not preset:
            self._flash_status(t("プリセットを選択してください"))
            return
        self._total_sec = int(preset.get("total_sec", 3600))
        self._total_var.set(dur_str(self._total_sec))
        self._segments = [
            Segment(s["name"], int(s["duration_seconds"]), s["color"], s.get("memo", ""))
            for s in preset.get("segments", [])
        ]
        warns = preset.get("warn_thresholds")
        if warns:
            self._warn_thresholds = [
                WarnThreshold(bool(w["enabled"]), int(w["seconds"]),
                              int(w["count"]), w["color"])
                for w in warns
            ]
        self._sv_sound.set(bool(preset.get("sound", True)))
        self._sv_repeat.set(bool(preset.get("repeat", False)))
        self._rebuild_rows()
        self._rebuild_warn_rows()
        self._refresh_display()
        self._flash_status(f"{name}: {t('読み込みました')}")

    def _preset_delete(self):
        """選択中のプリセットを削除する"""
        name = self._preset_combo.get()
        if not name or not any(p["name"] == name for p in self._presets):
            self._flash_status(t("削除するプリセットを選択してください"))
            return
        self._presets = [p for p in self._presets if p["name"] != name]
        self._save_presets_file()
        self._refresh_preset_combo()
        self._flash_status(f"{name}: {t('削除しました')}")

    def _flash_status(self, msg: str):
        """phase_lbl に一時メッセージを表示"""
        self._phase_lbl.configure(text=msg, text_color="#5dade2")
        self.after(2000, lambda: self._refresh_display())

    def _apply_hires_icon(self):
        """Windows のタスクバー/Alt-Tab に高解像度アイコンを設定する。
        Tkinter の iconbitmap は低解像度の画像を使うため、高DPIでは荒く見える。
        WM_SETICON で .ico 内の 256px / 32px を直接渡してくっきり表示させる。"""
        if sys.platform != "win32" or not ICON_PATH.exists():
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.winfo_id())
            LR_LOADFROMFILE = 0x00000010
            IMAGE_ICON = 1
            WM_SETICON = 0x0080
            ICON_SMALL, ICON_BIG = 0, 1
            p = str(ICON_PATH)
            big = user32.LoadImageW(None, p, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
            small = user32.LoadImageW(None, p, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
            if small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        except Exception:
            pass

    def _on_close(self):
        # トレイに最小化が有効なら、閉じる代わりにトレイへ格納
        if self._sv_tray.get() and self._tray_icon is None:
            self._minimize_to_tray()
            return
        self._save_settings()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.destroy()

    # ── フラッシュ停止（表示エリアクリック）────────────────────────────────────

    def _on_disp_click(self, event=None):
        if self._flash_job or self._flash_canvases or self._circle_flash_on:
            self._stop_flash()
            self._time_lbl.configure(text_color=("gray10", "gray90"))
            self._refresh_display()

    # ── 警告しきい値リスト ────────────────────────────────────────────────────

    def _rebuild_warn_rows(self):
        for w in self._warn_frame.winfo_children():
            w.destroy()
        self._warn_row_widgets = []
        for i, th in enumerate(self._warn_thresholds):
            self._make_warn_row(i, th)

    def _make_warn_row(self, idx: int, th: WarnThreshold):
        row_f = ctk.CTkFrame(self._warn_frame, fg_color="transparent")
        row_f.pack(side="top", fill="x", pady=1)

        enabled_var = ctk.BooleanVar(value=th.enabled)
        enabled_var.trace_add("write",
            lambda *_, i=idx, v=enabled_var: self._on_warn_enabled(i, v))
        ctk.CTkCheckBox(row_f, text=t("残り"), variable=enabled_var,
                        checkbox_width=18, checkbox_height=18, width=50).pack(side="left")

        sec_var = ctk.StringVar(value=str(th.seconds))
        sec_e = ctk.CTkEntry(row_f, textvariable=sec_var, width=48, height=24,
                              justify="center", font=ctk.CTkFont(size=12))
        sec_e.pack(side="left", padx=2)
        sec_e.bind("<Return>",   lambda _, i=idx, v=sec_var: self._on_warn_sec(i, v))
        sec_e.bind("<FocusOut>", lambda _, i=idx, v=sec_var: self._on_warn_sec(i, v))
        ctk.CTkLabel(row_f, text=t("秒"), text_color=("gray15", "gray60")).pack(side="left")

        chip = tk.Frame(row_f, bg=th.color, width=22, height=22,
                        cursor="hand2", relief="flat", bd=1)
        chip.pack(side="left", padx=(8, 0))
        chip.bind("<Button-1>", lambda _, i=idx: self._pick_warn_color(i))

        self._warn_row_widgets.append({
            "frame": row_f, "enabled_var": enabled_var,
            "sec_var": sec_var, "chip": chip,
        })

    def _add_warn(self):
        self._warn_thresholds.append(WarnThreshold(True, 60, 2, "#2ecc71"))
        self._warned = {k for k in self._warned if not k.startswith("warn_")}
        self._rebuild_warn_rows()

    def _remove_warn(self):
        if self._warn_thresholds:
            self._warn_thresholds.pop()
            self._warned = {k for k in self._warned if not k.startswith("warn_")}
            self._rebuild_warn_rows()

    def _on_warn_enabled(self, idx: int, var: ctk.BooleanVar):
        if 0 <= idx < len(self._warn_thresholds):
            self._warn_thresholds[idx].enabled = var.get()

    def _on_warn_sec(self, idx: int, var: ctk.StringVar):
        if not (0 <= idx < len(self._warn_thresholds)):
            return
        try:
            v = max(1, int(var.get()))
        except ValueError:
            v = self._warn_thresholds[idx].seconds
        self._warn_thresholds[idx].seconds = v
        var.set(str(v))


    def _pick_warn_color(self, idx: int):
        if not (0 <= idx < len(self._warn_thresholds)):
            return
        res = colorchooser.askcolor(
            self._warn_thresholds[idx].color, parent=self, title=t("点滅色を選択"))
        if res and res[1]:
            self._warn_thresholds[idx].color = res[1]
            if idx < len(self._warn_row_widgets):
                self._warn_row_widgets[idx]["chip"].configure(bg=res[1])

    # ── アラート ──────────────────────────────────────────────────────────────

    def _get_active_seg_idx(self) -> int:
        cum = 0
        for i, seg in enumerate(self._segments):
            cum += seg.duration_seconds
            if self._elapsed_sec < cum:
                return i
        return len(self._segments)

    def _phase_parts(self) -> Tuple[str, str, int]:
        """現在のフェーズを (kind, name, remaining_sec) で返す。
        kind: "seg"=区間中 / "leftover"=残り区間 / "done"=完了 / "none"=区間なし。
        フェーズ文字列の生成を一元化する（表示先ごとに整形）。"""
        if not self._segments:
            return ("none", "", 0)
        elap = self._elapsed_sec
        for seg in self._segments:
            if elap < seg.duration_seconds:
                label = f"{seg.name}（{seg.memo}）" if seg.memo else seg.name
                return ("seg", label, seg.duration_seconds - elap)
            elap -= seg.duration_seconds
        if self._leftover() > 0 and self._elapsed_ms < self._total_ms:
            return ("leftover", t("残り"), self._total_sec - self._elapsed_sec)
        return ("done", "", 0)

    def _play_sound(self, alert_type: str, loop: bool = False):
        if not _SOUND_AVAILABLE or not self._sv_sound.get():
            return
        self._alarm_stop.clear()
        stop = self._alarm_stop
        # 完了音にカスタム .wav が指定されていればそれを再生
        wav = self._custom_sound_path
        if alert_type == "complete" and wav and os.path.exists(wav):
            def _play_wav():
                try:
                    while True:
                        _winsound.PlaySound(wav, _winsound.SND_FILENAME)  # 同期再生
                        if not loop or stop.is_set():
                            return
                        for _ in range(8):
                            if stop.is_set():
                                return
                            _time_mod.sleep(0.05)
                except Exception:
                    pass
            threading.Thread(target=_play_wav, daemon=True).start()
            return
        pattern = ALERT_SOUND.get(alert_type, [])
        def _play():
            try:
                while True:
                    for freq, dur in pattern:
                        if stop.is_set():
                            return
                        if freq > 0:
                            _winsound.Beep(freq, dur)
                        else:
                            _time_mod.sleep(dur / 1000)
                    if not loop:
                        return
                    # ループ繰り返しの前に小休止（停止チェックしつつ）
                    for _ in range(12):
                        if stop.is_set():
                            return
                        _time_mod.sleep(0.05)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    # ── 実績ログ・カスタム音 ────────────────────────────────────────────────
    def _log_completion(self):
        """完了を実績ログに記録（直近500件を保持）"""
        rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"),
               "total_sec": int(self._total_sec),
               "preset": self._preset_var.get() or ""}
        try:
            data = json.loads(STATS_PATH.read_text(encoding="utf-8")) if STATS_PATH.exists() else []
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        data.append(rec)
        try:
            STATS_PATH.write_text(json.dumps(data[-500:], ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except Exception:
            pass

    # ── タスクトレイに最小化 ─────────────────────────────────────────────────
    def _minimize_to_tray(self):
        if self._tray_icon is not None:
            return
        try:
            import pystray
            from PIL import Image
            try:
                img = Image.open(str(ICON_PATH))
            except Exception:
                img = Image.new("RGB", (64, 64), "#27ae60")
            menu = pystray.Menu(
                pystray.MenuItem(t("表示"), self._tray_restore, default=True),
                pystray.MenuItem(t("終了"), self._tray_quit))
            self._tray_icon = pystray.Icon("MinutetimeLine", img, "MinutetimeLine", menu)
            self.withdraw()
            self._tray_icon.run_detached()
        except Exception:
            # トレイ不可なら通常の最小化にフォールバック
            self._tray_icon = None
            self.iconify()

    def _tray_restore(self, icon=None, item=None):
        # pystray スレッドから呼ばれるのでメインスレッドへ戻す
        self.after(0, self._do_tray_restore)

    def _do_tray_restore(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self, icon=None, item=None):
        self.after(0, self._really_quit)

    def _really_quit(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self._save_settings()
        self.destroy()

    # ── 指定時刻スタート（アラーム的）────────────────────────────────────────
    def _toggle_schedule(self):
        if self._sched_after_id is not None:        # 予約中 → 解除
            self.after_cancel(self._sched_after_id)
            self._sched_after_id = None
            self._sched_btn.configure(text=t("予約"), fg_color="#2471a3", hover_color="#1a5276")
            self._flash_status(t("予約を解除しました"))
            return
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", self._sched_var.get())
        if not m:
            self._flash_status(t("HH:MM 形式で入力してください"))
            return
        hh, mm = int(m.group(1)), int(m.group(2))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            self._flash_status(t("時刻が不正です"))
            return
        now = _dt.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)         # 過ぎていれば翌日
        delay_ms = int((target - now).total_seconds() * 1000)
        self._sched_after_id = self.after(delay_ms, self._scheduled_fire)
        self._sched_btn.configure(text=t("予約解除"), fg_color="#d35400", hover_color="#a04000")
        self._flash_status(f"{target.strftime('%H:%M')} {t('に開始を予約しました')}")

    def _scheduled_fire(self):
        self._sched_after_id = None
        self._sched_btn.configure(text=t("予約"), fg_color="#2471a3", hover_color="#1a5276")
        if self._tray_icon is not None:
            self._do_tray_restore()
        if not self._running:
            self._start(fresh=(self._elapsed_ms == 0))

    def _pick_sound(self):
        """完了音に使う .wav を選択（空にするとビープに戻る）"""
        path = filedialog.askopenfilename(
            parent=self, title=t("完了音の .wav を選択"),
            filetypes=[(t("WAV ファイル"), "*.wav"), (t("すべて"), "*.*")])
        if path:
            self._custom_sound_path = path
            self._sound_lbl.configure(text=os.path.basename(path))
        # 何も選ばなければ変更しない

    def _clear_sound(self):
        self._custom_sound_path = ""
        self._sound_lbl.configure(text=t("（ビープ音）"))

    def _show_stats(self, at_geo: Optional[str] = None):
        """実績（今日/累計の完了回数・合計時間、最近の記録）を表示。
        at_geo を渡すと、その位置・サイズで開く（消去後の再表示で位置維持）。"""
        try:
            data = json.loads(STATS_PATH.read_text(encoding="utf-8")) if STATS_PATH.exists() else []
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        today = _dt.date.today().isoformat()
        t_recs = [r for r in data if str(r.get("ts", "")).startswith(today)]
        t_cnt, t_sec = len(t_recs), sum(int(r.get("total_sec", 0)) for r in t_recs)
        a_cnt, a_sec = len(data), sum(int(r.get("total_sec", 0)) for r in data)

        win = ctk.CTkToplevel(self)
        win.title(t("実績"))
        win.geometry(at_geo if at_geo else "440x480")
        win.transient(self)
        ctk.CTkLabel(win, text=t("📊  実績"),
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 8))
        # 消去ボタンを先に下端へ固定（下のスクロールリストに押し出されないように）
        ctk.CTkButton(win, text=t("ログを消去"), width=140,
                      fg_color="#922b21", hover_color="#7b241c",
                      command=lambda w=win: self._clear_stats(w)).pack(side="bottom", pady=(6, 12))
        summ = ctk.CTkFrame(win)
        summ.pack(fill="x", padx=16, pady=(0, 8))
        def srow(k, v):
            f = ctk.CTkFrame(summ, fg_color="transparent")
            f.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(f, text=k, anchor="w").pack(side="left")
            ctk.CTkLabel(f, text=v, anchor="e",
                         font=ctk.CTkFont(weight="bold")).pack(side="right")
        srow(t("今日の完了回数"), f"{t_cnt} {t('回')}")
        srow(t("今日の合計時間"), fmt(t_sec))
        srow(t("累計完了回数"), f"{a_cnt} {t('回')}")
        srow(t("累計合計時間"), fmt(a_sec))
        ctk.CTkLabel(win, text=t("最近の記録"),
                     text_color=("gray25", "gray70")).pack(fill="x", padx=20, pady=(8, 2))
        body = ctk.CTkScrollableFrame(win)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for r in reversed(data[-30:]):
            ts = str(r.get("ts", "")).replace("T", "  ")
            txt = f"{ts}    {fmt(int(r.get('total_sec', 0)))}"
            if r.get("preset"):
                txt += f"    [{r['preset']}]"
            ctk.CTkLabel(body, text=txt, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(fill="x", pady=1)
        win.after(120, win.focus)

    def _clear_stats(self, win):
        # 確認してから消去（誤操作防止）。消去後は同じ位置・サイズで開き直す。
        if not messagebox.askyesno(t("実績"), t("実績をすべて消去しますか？"), parent=win):
            return
        try:
            if STATS_PATH.exists():
                STATS_PATH.unlink()
        except Exception:
            pass
        try:
            geo = win.geometry()   # 現在の位置・サイズを引き継ぐ
        except Exception:
            geo = None
        win.destroy()
        self._show_stats(at_geo=geo)

    def _stop_flash(self):
        # ループ中の完了音も停止
        self._alarm_stop.set()
        if self._flash_job:
            self.after_cancel(self._flash_job)
            self._flash_job = None
        if self._disp_default_color is not None:
            self._disp_frame.configure(fg_color=self._disp_default_color)
        self._time_lbl.configure(text_color=("gray10", "gray90"))
        # 全キャンバスを元の色に戻す（カウントゼロ点滅用）
        if self._flash_canvases:
            cmds = []
            for cv, bg_orig, fill_orig in self._flash_canvases:
                p = str(cv)
                if safe_color(bg_orig):
                    cmds.append(f"catch {{{p} configure -background {bg_orig}}}")
                if safe_color(fill_orig):
                    cmds.append(f"catch {{{p} itemconfigure inner_parts -fill {fill_orig}}}")
            try:
                self.tk.eval("\n".join(cmds))
            except Exception:
                pass
            self._flash_canvases = []
        # サークルオーバーレイ解除
        self._circle_flash_on = False
        self._circle_flash_color = ""
        if self._style_mode == "サークル":
            self._draw_circle_clock()

    def _start_flash(self, colors: list, interval: int, count: int,
                     loop: bool = False, txt_colors: list = None,
                     overlay: bool = False):
        self._stop_flash()
        if overlay:
            # 全CTkFrameの _canvas を収集し、現在の bg と inner_parts fill を保存
            def _collect(w):
                if isinstance(w, ctk.CTkFrame) and hasattr(w, "_canvas"):
                    cv = w._canvas
                    try:
                        bg_orig   = cv.cget("bg")
                        try:
                            fill_orig = cv.itemcget("inner_parts", "fill")
                        except Exception:
                            fill_orig = ""
                        self._flash_canvases.append((cv, bg_orig, fill_orig))
                    except Exception:
                        pass
                for child in w.winfo_children():
                    _collect(child)
            _collect(self)
        self._flash_wall_start = _time_mod.monotonic()
        self._do_flash(colors, interval, count, 0, loop, txt_colors, overlay, total_tick=0)

    def _do_flash(self, colors: list, interval: int, count: int,
                  step: int, loop: bool, txt_colors: list = None,
                  overlay: bool = False, total_tick: int = 0):
        if not loop and step >= count:
            self._stop_flash()
            return
        idx = step % len(colors)
        if overlay:
            # 全キャンバスを一括 Tcl eval で変更（catch で部分失敗を無視）
            cmds = []
            if step % 2 == 0:
                # 点灯: 全キャンバスを flash 色に
                if safe_color(colors[0]):
                    for cv, _, _ in self._flash_canvases:
                        p = str(cv)
                        cmds.append(f"catch {{{p} configure -background {colors[0]}}}")
                        cmds.append(f"catch {{{p} itemconfigure inner_parts -fill {colors[0]}}}")
            else:
                # 消灯: 元の色に戻す
                for cv, bg_orig, fill_orig in self._flash_canvases:
                    p = str(cv)
                    if safe_color(bg_orig):
                        cmds.append(f"catch {{{p} configure -background {bg_orig}}}")
                    if safe_color(fill_orig):
                        cmds.append(f"catch {{{p} itemconfigure inner_parts -fill {fill_orig}}}")
            if cmds:
                try:
                    self.tk.eval("\n".join(cmds))
                except Exception:
                    pass
            # サークルモードのオーバーレイ点滅
            if self._style_mode == "サークル":
                self._circle_flash_on = (step % 2 == 0)
                self._circle_flash_color = colors[0]
                self._draw_circle_clock()
        else:
            self._disp_frame.configure(fg_color=colors[idx])
            if txt_colors:
                self._time_lbl.configure(text_color=txt_colors[idx % len(txt_colors)])
        next_step = (step + 1) % count if loop else step + 1
        next_tick = total_tick + 1
        # 壁時計ベースで次ステップの遅延を計算（処理時間のドリフトを補正）
        target = self._flash_wall_start + next_tick * interval / 1000.0
        delay = max(1, round((target - _time_mod.monotonic()) * 1000))
        self._flash_job = self.after(
            delay,
            lambda c=colors, i=interval, n=count, s=next_step, lp=loop,
                   tc=txt_colors, ov=overlay, tt=next_tick:
                self._do_flash(c, i, n, s, lp, tc, ov, tt)
        )

    def _make_complete_sound(self, n: int) -> list:
        """N回目の完了音パターンを生成: ピリピリピー + ピッ×N"""
        base = [(1400, 80), (0, 50), (1400, 80), (0, 50), (1200, 500)]
        pips = []
        for _ in range(n):
            pips += [(0, 120), (1800, 100)]
        return base + pips

    def _get_sound_duration_ms(self, n: int) -> int:
        """N回目の完了音の概算再生時間(ms) — 点滅の自動停止タイミングに使用"""
        base_ms = 80 + 50 + 80 + 50 + 500   # ピリピリピー = 760ms
        pip_ms  = n * (120 + 100)             # ピッ×N = n×220ms
        return base_ms + pip_ms + 200         # 200ms の余白

    def _trigger_complete(self):
        if self._sv_repeat.get():
            # 繰り返しモード: 回数カウント音 → 3秒後に自動再スタート
            self._repeat_count += 1
            self._trigger_complete_repeat(self._repeat_count)
            return
        # 通常モード: 実績ログ
        self._log_completion()
        # プリセット自動連結が設定されていれば、点滅だけして次へ
        nxt = self._next_preset
        if nxt and nxt in [p.get("name") for p in self._presets]:
            cfg = ALERT_FLASH["complete"]
            self._start_flash(cfg["colors"], cfg["interval"], 6, loop=False, overlay=True)
            self._play_sound("complete", loop=False)
            self.after(2500, lambda n=nxt: self._chain_to_preset(n))
            return
        # アプリ全体をオーバーレイでループ点滅 + 完了音
        # 点滅を先に開始（_start_flash 内の _stop_flash が鳴音停止フラグを立てるため、
        # 音の再生は必ずその後に行う）
        cfg = ALERT_FLASH["complete"]
        self._start_flash(cfg["colors"], cfg["interval"], cfg["count"],
                          loop=True, overlay=True)
        self._play_sound("complete", loop=self._sv_loop_alarm.get())

    def _chain_to_preset(self, name: str):
        """完了後に次のプリセットを読み込んで自動スタート"""
        self._stop_flash()
        self._preset_var.set(name)
        self._preset_load()
        self.after(200, lambda: self._start(fresh=True))

    def _on_chain_change(self, value: str):
        self._next_preset = "" if value in ("（なし）", t("（なし）"), "") else value

    def _on_lang_change(self, value: str):
        new = "en" if value == "English" else "ja"
        if new == self._lang:
            return
        self._migrate_seg_names(new)   # 既定の区間名を新言語へ
        self._lang = new
        set_lang(new)
        self._save_settings()
        self._relayout_language()      # 再起動せず UI を即時再構築

    def _migrate_seg_names(self, to_lang: str):
        """既定パターンの区間名のみ言語間で変換（カスタム名は保持）"""
        for seg in self._segments:
            if to_lang == "en":
                m = re.fullmatch(r"区間\s*(\d+)", seg.name)
                if m:
                    seg.name = f"Segment {m.group(1)}"
            else:
                m = re.fullmatch(r"Segment\s*(\d+)", seg.name)
                if m:
                    seg.name = f"区間 {m.group(1)}"

    def _relayout_language(self):
        """言語切替時に UI を作り直して新言語で表示（状態は保持）"""
        self._stop_flash()
        was_compact = self._is_compact
        self._is_compact = False
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        self._disp_default_color = self._disp_frame.cget("fg_color")
        # 現在の状態を新しいウィジェットへ反映
        self._total_var.set(dur_str(self._total_sec))
        self._theme_btn.set(t(self._appearance_mode))
        for label, (code, _, _) in PRECISION.items():
            if code == self._prec_code:
                self._prec_btn.set(t(label))
                break
        self._style_btn.set(t(self._style_mode))
        self._num_mode_btn.set(t(self._circle_num_mode))
        self._disp_size_btn.set(t(self._disp_size))
        self._lang_btn.set("日本語" if self._lang == "ja" else "English")
        self._apply_disp_font()
        self._rebuild_rows()
        self._rebuild_warn_rows()
        self._refresh_preset_combo()
        self._update_style_layout()
        if self._settings_open:
            self._settings_open = False
            self._toggle_settings(True)
        self._refresh_display()
        if was_compact and self._sv_compact.get():
            self._enter_compact()
        self.after(300, self._adjust_min_width)

    def _trigger_complete_repeat(self, count: int):
        """繰り返しモードの完了処理: 音を鳴らして即座に再スタート、音の間は点滅"""
        # 繰り返しでも1周ごとに実績ログに記録
        self._log_completion()
        # N回目の完了音を鳴らす（バックグラウンドスレッドで再生）
        if _SOUND_AVAILABLE and self._sv_sound.get():
            pattern = self._make_complete_sound(count)
            def _play():
                try:
                    for freq, dur in pattern:
                        if freq > 0:
                            _winsound.Beep(freq, dur)
                        else:
                            _time_mod.sleep(dur / 1000)
                except Exception:
                    pass
            threading.Thread(target=_play, daemon=True).start()

        # アラーム音の間だけ点滅（音が終わったら自動停止）
        cfg = ALERT_FLASH["complete"]
        self._start_flash(cfg["colors"], cfg["interval"], cfg["count"],
                          loop=True, overlay=True)
        self.after(self._get_sound_duration_ms(count), self._stop_flash)

        # タイマーは即座に再スタート（点滅は keep_flash=True で継続させる）
        self._repeat_after_id = self.after(0, self._restart_loop)

    def _repeat_max(self) -> int:
        """繰り返し回数の上限（0=無限）"""
        try:
            return max(0, int(self._repeat_max_var.get()))
        except (ValueError, AttributeError):
            return 0

    def _restart_loop(self):
        """繰り返しモードの自動再スタート（カウントは維持）"""
        self._repeat_after_id = None
        if not self._sv_repeat.get():
            return
        mx = self._repeat_max()
        if mx > 0 and self._repeat_count >= mx:
            # 指定回数に達したので終了（ボタンを戻して停止）
            self._running = False
            self._stop_flash()
            self._set_start_btn("▶  スタート", "#27ae60", "#1e8449")
            self._refresh_display()
            return
        self._elapsed_ms = 0
        self._start(fresh=False, keep_flash=True)  # 点滅を止めずに再スタート

    def _trigger_segment(self, seg_idx: int):
        count = 3 * 2   # 3回点滅（固定）
        # 終了した区間の色でフラッシュ（初期状態でその区間と同色）
        if 0 <= seg_idx < len(self._segments):
            seg_color = self._segments[seg_idx].color
        else:
            seg_color = "#d4ac0d"
        cfg = ALERT_FLASH["segment"]
        self._start_flash([seg_color, "#1e1e2e"], cfg["interval"], count)

    _APPEARANCE_MAP = {"自動": "system", "ライト": "light", "ダーク": "dark"}

    def _on_appearance_change(self, value: str):
        value = untr(value)   # 表示ラベル → 内部キー(日本語)
        self._appearance_mode = value
        _geo = self.geometry()
        ctk.set_appearance_mode(self._APPEARANCE_MAP.get(value, "dark"))
        def _after_theme():
            self.geometry(_geo)
            self._disp_default_color = self._disp_frame.cget("fg_color")
            if not self._flash_job:
                self._time_lbl.configure(text_color=("gray10", "gray90"))
                self._refresh_display()
        self.after(100, _after_theme)

    # ── 表示スタイル切替 ──────────────────────────────────────────────────────────

    def _toggle_settings(self, open_: Optional[bool] = None):
        """⚙ 設定項目の開閉。開くと全項目が収まる高さへ窓を一度だけ広げ、
        閉じると元の高さに戻す。最小高さは強制しないのでリサイズは自由。"""
        self._settings_open = (not self._settings_open) if open_ is None else open_
        if self._settings_open:
            # 設定モード: 区間リストを一時的に隠し、その場所をコントロール(設定)に
            # 充てる。縮めたら設定がスクロールして項目が消えない。閉じれば区間リスト復帰。
            self._seg_panel.grid_remove()
            self.grid_rowconfigure(2, weight=0, minsize=0)
            self.grid_rowconfigure(3, weight=1, minsize=130)
            self._ctrl_frame.grid_configure(sticky="nsew")
            self._settings_frame.grid()
            self._settings_btn.configure(fg_color="#2471a3", hover_color="#1a5276")
            self.after(60, self._grow_for_settings)
        else:
            self._seg_panel.grid()
            self.grid_rowconfigure(2, weight=1, minsize=110)
            self.grid_rowconfigure(3, weight=0, minsize=0)
            self._ctrl_frame.grid_configure(sticky="ew")
            self._settings_frame.grid_remove()
            self._settings_btn.configure(fg_color="gray35", hover_color="gray25")

    @staticmethod
    def _parse_wh(geo: str) -> Tuple[int, int]:
        m = re.match(r"(\d+)x(\d+)", geo)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def _geo_size(self) -> Tuple[int, int]:
        """現在の窓サイズ(論理px) を geometry 文字列から取得（DPIスケール整合）"""
        w, h = self._parse_wh(self.geometry())
        return (w or self.winfo_width(), h or self.winfo_height())

    def _grow_for_settings(self):
        """設定オープン時に全項目が収まる高さへ窓を一度だけ広げる（画面高さで上限）。
        最小高さはベースのままにして、その後のリサイズを妨げない。"""
        if not self._settings_open:
            return
        self.update_idletasks()
        disp = self._disp_frame.winfo_reqheight()
        tl   = self._tl_frame.winfo_reqheight() if self._style_mode != "サークル" else 0
        # スクロール可能フレームでは ctrl.reqheight が内容を反映しないため、
        # 設定内容の高さ(sf) を直接使う。row0(スタート/リセット行)は概算。
        # 設定モードでは区間リストを隠すので、表示部＋タイムライン＋設定内容
        # ＋row0(操作行)＋余白 が収まれば全項目が見える。
        sf_content = self._settings_frame.winfo_reqheight()
        need_phys = disp + tl + 80 + sf_content + 130
        # 物理px → 論理px に変換（geometry は論理px を期待。DPIスケール整合）
        cur_w_log, cur_h_log = self._geo_size()
        scaling = self.winfo_height() / max(1, cur_h_log)
        need_log = int(need_phys / max(0.1, scaling))
        screen_log = int((self.winfo_screenheight() - 60) / max(0.1, scaling))
        need_log = min(need_log, screen_log)
        if cur_h_log < need_log:
            self.geometry(f"{cur_w_log}x{need_log}")

    def _on_style_change(self, value: str):
        self._style_mode = untr(value)
        self._update_style_layout()

    def _on_num_mode_change(self, value: str):
        self._circle_num_mode = untr(value)
        if self._style_mode == "サークル":
            self._draw_circle_clock()

    def _update_style_layout(self):
        if self._style_mode == "サークル":
            self._time_lbl.grid_remove()
            self._breakdown_lbl.grid_remove()
            self._phase_lbl.grid_remove()
            self._tl_frame.grid_remove()
            self._disp_frame.grid_rowconfigure(0, weight=1)
            self._circle_canvas.grid(
                row=0, column=0, padx=8, pady=8, sticky="nsew")
        else:
            self._circle_canvas.grid_remove()
            self._disp_frame.grid_rowconfigure(0, weight=0)
            self._time_lbl.grid(row=0, column=0, pady=(18, 0))
            self._breakdown_lbl.grid(row=1, column=0, pady=(2, 4))
            self._phase_lbl.grid(row=2, column=0, pady=(0, 16))
            if not self._is_compact:
                self._tl_frame.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        self._refresh_display()

    # ── コンパクトモード ──────────────────────────────────────────────────────────

    def _on_compact_toggle(self):
        """コンパクトスイッチ操作: 即座に表示を切り替える"""
        if self._sv_compact.get():
            self._enter_compact()
        else:
            self._exit_compact()

    def _on_expand_click(self):
        """展開ボタン: コンパクト解除し、スイッチもOFFに同期（再ONで再コンパクト可）"""
        self._sv_compact.set(False)
        self._exit_compact()

    def _enter_compact(self):
        if self._is_compact:
            return
        self._is_compact = True
        self._normal_geometry = self.geometry()

        # 区間パネル・コントロールを隠し、行の予約スペースを消す
        self._seg_panel.grid_remove()
        self._ctrl_frame.grid_remove()
        self.grid_rowconfigure(2, weight=0, minsize=0)
        self.grid_rowconfigure(3, weight=0, minsize=0)
        # 最小サイズ制約を緩める（これがないと minsize 分の空白が残る）
        self.minsize(300, 100)

        if self._style_mode == "サークル":
            self._circle_canvas.configure(height=180)
        else:
            # フラット: ラベルを小さく・不要な要素を隠す
            self._breakdown_lbl.grid_remove()
            self._phase_lbl.grid_remove()
            self._time_lbl.configure(font=ctk.CTkFont(size=42, weight="bold"))
            self._time_lbl.grid_configure(pady=(6, 4))
            # ヘッダーを隠し、キャンバスを row=0 に詰める（空行を消す）
            self._tl_header.grid_remove()
            self._canvas.configure(height=58)   # バー全体（y1+6=57px）が収まる高さ
            self._canvas.grid_configure(row=0, pady=(2, 4))
            self._tl_frame.grid_configure(padx=12, pady=(0, 2))

        # _disp_frame の上下余白を縮める
        self._disp_frame.grid_configure(pady=(4, 2))

        # 展開バーを表示し、情報ラベルを即更新
        self._compact_bar.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")
        self._update_compact_info()

        # 最前面・ウィンドウ縮小（レイアウト確定後）
        self.attributes("-topmost", True)
        self.after(80, self._resize_to_compact)

    def _resize_to_compact(self):
        self.update_idletasks()
        self.update()
        disp = self._disp_frame.winfo_reqheight()
        bar  = self._compact_bar.winfo_reqheight()
        if self._style_mode == "サークル":
            # サークルモード: _tl_frame はメインウィンドウに存在しない
            h = disp + (4 + 2) + bar + (0 + 6)
        else:
            tl = self._tl_frame.winfo_reqheight()
            h = disp + (4 + 2) + tl + (0 + 2) + bar + (0 + 6)
        self.geometry(f"360x{h}")

    def _exit_compact(self):
        if not self._is_compact:
            return
        self._is_compact = False

        # コンパクトバーを隠す
        self._compact_bar.grid_remove()

        if self._style_mode == "サークル":
            # サークル高さを元に戻す
            _, circle_h = DISP_SIZE_CFG.get(self._disp_size, (1.0, 360))
            self._circle_canvas.configure(height=circle_h)
        else:
            # フラット: フォント・ラベル・タイムラインを復元
            self._apply_disp_font()
            self._time_lbl.grid_configure(pady=(18, 0))
            self._breakdown_lbl.grid(row=1, column=0, pady=(2, 4))
            self._phase_lbl.grid(row=2, column=0, pady=(0, 16))
            self._tl_header.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="ew")
            self._canvas.configure(height=60)
            self._canvas.grid_configure(row=1, pady=(0, 12))
            self._tl_frame.grid_configure(padx=20, pady=8)

        # _disp_frame の余白を元に戻す
        self._disp_frame.grid_configure(pady=(20, 8))

        # 区間パネル・コントロールを戻す
        self._seg_panel.grid(row=2, column=0, padx=20, pady=8, sticky="nsew")
        self._ctrl_frame.grid(row=3, column=0, padx=20, pady=(8, 20), sticky="ew")
        # 設定の開閉状態に応じた行設定を再適用（区間リスト/設定が消えないように）
        self._toggle_settings(self._settings_open)

        # 最小サイズ・最前面・ジオメトリを復元
        self.minsize(self._min_w, self._min_h)
        self.attributes("-topmost", False)
        if self._normal_geometry:
            self.geometry(self._normal_geometry)

    def _adjust_min_width(self):
        """コントロール部の必要幅に合わせて最小幅を設定し、横並びボタンの
        見切れを防ぐ。ウィンドウが新しい最小幅より狭ければ広げる。"""
        try:
            self.update_idletasks()
            # 設定行は折りたたみ中でも幅を計測（開いたときに見切れないように）
            need = max(self._ctrl_frame.winfo_reqwidth(),
                       self._settings_frame.winfo_reqwidth()) + 48
        except Exception:
            return
        self._min_w = max(700, need)
        if not self._is_compact:
            # 最小高さはベースのまま（縦リサイズを妨げない）。設定の表示は
            # 開いたときに窓を一度広げて対応する。
            self.minsize(self._min_w, self._min_h)
            if self.winfo_width() < self._min_w:
                self.geometry(f"{self._min_w}x{self.winfo_height()}")
            if self._settings_open:
                self._grow_for_settings()

    def _on_window_configure(self, event=None):
        """ウィンドウのドラッグリサイズ検出。連続イベント中は _resizing を立て、
        重い再描画（タイムライン・サークル・行更新）を抑制。確定後に一度だけ描画。"""
        if event is not None and event.widget is not self:
            return
        size = (self.winfo_width(), self.winfo_height())
        if size == self._win_size:
            return
        self._win_size = size
        self._resizing = True
        if self._resize_settle_job:
            self.after_cancel(self._resize_settle_job)
        self._resize_settle_job = self.after(120, self._on_resize_settled)

    def _on_resize_settled(self):
        self._resize_settle_job = None
        self._resizing = False
        # 確定サイズで一度だけ再描画
        self._draw_timeline()
        if self._style_mode == "サークル":
            self._draw_circle_clock()

    def _on_circle_configure(self, event=None):
        """リサイズ中は <Configure> が多発するため再描画をデバウンスする。
        サイズが実際に変わったときだけ予約する。"""
        if self._resizing:
            return   # リサイズ確定後にまとめて描画する

        size = (event.width, event.height) if event else self._circle_size
        if size == self._circle_size:
            return
        self._circle_size = size
        if self._circle_cfg_job:
            self.after_cancel(self._circle_cfg_job)
        self._circle_cfg_job = self.after(60, self._draw_circle_clock)

    def _on_timeline_configure(self, event=None):
        if self._resizing:
            return
        w = event.width if event else self._timeline_w
        if w == self._timeline_w:
            return
        self._timeline_w = w
        if self._timeline_cfg_job:
            self.after_cancel(self._timeline_cfg_job)
        self._timeline_cfg_job = self.after(60, self._draw_timeline)

    def _draw_circle_clock(self):
        """サークルモード: 分針・秒針付き時計 ＋ 外周ドーナツタイムライン"""
        self._circle_cfg_job = None
        c = self._circle_canvas
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 50 or H < 50:
            return

        is_dark  = ctk.get_appearance_mode().lower() != "light"
        bg_col   = "#1e1e2e" if is_dark else "#e8e8f0"
        face_col = "#252535" if is_dark else "#ffffff"
        tick_col = "#8888aa" if is_dark else "#555566"
        num_col  = "#9999bb" if is_dark else "#666677"
        text_col = "#e8e8ff" if is_dark else "#111122"
        hand_m   = "#ccccee" if is_dark else "#222244"
        hand_s   = "#e74c3c"
        div_col  = bg_col

        c.configure(bg=bg_col)

        CX = W / 2
        CY = H / 2
        R       = min(W, H) / 2 - 10
        DONUT_W = max(20, R * 0.14)
        outer_r = R
        inner_r = R - DONUT_W
        face_r  = inner_r - 16

        # ── ドーナツ背景リング ───────────────────────────────
        ring_bg = "#2a2a3e" if is_dark else "#d8d8e8"
        c.create_arc(CX - outer_r + DONUT_W/2, CY - outer_r + DONUT_W/2,
                     CX + outer_r - DONUT_W/2, CY + outer_r - DONUT_W/2,
                     start=0, extent=359.9, outline=ring_bg,
                     width=DONUT_W, style="arc")

        # ── ドーナツ区間 ─────────────────────────────────────
        r_mid  = (outer_r + inner_r) / 2
        arc_w  = outer_r - inner_r

        def draw_arc(start_d: float, extent_d: float, color: str):
            if extent_d < 0.2:
                return
            cs = 90.0 + start_d   # 反時計回り: 12時から CCW へ
            ce = extent_d          # 正値 = CCW
            c.create_arc(CX - r_mid, CY - r_mid, CX + r_mid, CY + r_mid,
                         start=cs, extent=ce,
                         outline=color, width=arc_w, style="arc")

        def _dim(hex_col: str) -> str:
            """区間色を暗くブレンド: 経過済み部分の表示用"""
            h = hex_col.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            bh = ring_bg.lstrip('#')
            br, bg_, bb = int(bh[0:2], 16), int(bh[2:4], 16), int(bh[4:6], 16)
            # 20% 元色 + 80% 背景リング色 → すべての色でコントラスト比 4.5:1 以上
            return f'#{int(0.20*r+0.80*br):02x}{int(0.20*g+0.80*bg_):02x}{int(0.20*b+0.80*bb):02x}'

        if self._total_sec > 0:
            rem_elap = float(self._elapsed_ms)
            cur_start = 0.0
            boundaries: list[float] = [0.0]

            # 区間の合計がタイマー全体を超える場合、比例スケールで正規化する
            sum_seg_ms = sum(float(s.duration_seconds * 1000) for s in self._segments)
            denom_ms   = max(float(self._total_ms), sum_seg_ms)

            # 区間同士が継ぎ目（特に頂点）で1px重ならないよう、終端に微小な隙間を設ける
            SEG_GAP = 1.0   # 度

            for seg in self._segments:
                seg_ms      = float(seg.duration_seconds * 1000)
                ext         = seg_ms / denom_ms * 360.0
                # タイマー時間上でこの区間が占める実効ミリ秒
                seg_timer_ms = seg_ms / denom_ms * self._total_ms
                done_ms     = min(rem_elap, seg_timer_ms)
                done_e      = ext * (done_ms / seg_timer_ms) if seg_timer_ms > 0 else 0.0
                rem_elap   -= done_ms
                # 終端の隙間を引いた実描画長（区間が極小なら隙間なし）
                draw_ext = ext - SEG_GAP if ext > SEG_GAP * 2 else ext
                # 区間全体を暗色で描画し、残り部分だけ鮮やかな色で上書き
                draw_arc(cur_start, draw_ext, _dim(seg.color))
                if draw_ext - done_e > 0:
                    draw_arc(cur_start + done_e, draw_ext - done_e, seg.color)
                cur_start += ext
                boundaries.append(cur_start)

            lo = self._leftover()
            if lo > 0:
                lo_ms     = float(lo * 1000)
                lo_ext    = lo_ms / denom_ms * 360.0
                done_lo   = min(rem_elap, lo_ms)
                done_lo_e = lo_ext * (done_lo / lo_ms) if lo_ms > 0 else 0.0
                draw_lo_ext = lo_ext - SEG_GAP if lo_ext > SEG_GAP * 2 else lo_ext
                draw_arc(cur_start, draw_lo_ext, _dim(REMAIN_COLOR))
                if draw_lo_ext - done_lo_e > 0:
                    draw_arc(cur_start + done_lo_e, draw_lo_ext - done_lo_e, REMAIN_COLOR)
                cur_start += lo_ext
                boundaries.append(cur_start)

            # 区間境界線（頂点 0/360 も含めて描く。最後と最初の区間の継ぎ目を明示）
            # boundaries[:-1] で先頭 0（=頂点）を含め、末尾 360（重複）を除外
            for bd in boundaries[:-1]:
                rad = _math.radians(-90 - bd)   # CCW: tkinter弧角度の符号逆変換
                ix = CX + inner_r * _math.cos(rad)
                iy = CY + inner_r * _math.sin(rad)
                ox = CX + outer_r * _math.cos(rad)
                oy = CY + outer_r * _math.sin(rad)
                c.create_line(ix, iy, ox, oy, fill=div_col, width=2)

            # 現在位置マーカー（ドーナツ上の針）
            progress  = min(1.0, self._elapsed_ms / self._total_ms)
            ph_angle  = progress * 360.0
            rad = _math.radians(-90 - ph_angle)   # CCW: 12時スタート、反時計回り
            c.create_line(
                CX + (inner_r - 5) * _math.cos(rad),
                CY + (inner_r - 5) * _math.sin(rad),
                CX + (outer_r + 5) * _math.cos(rad),
                CY + (outer_r + 5) * _math.sin(rad),
                fill="#f0f0f0", width=2)

        # ── 時計フェイス ─────────────────────────────────────
        c.create_oval(CX - face_r, CY - face_r, CX + face_r, CY + face_r,
                      fill=face_col, outline=tick_col, width=1)

        # ── 目盛り ───────────────────────────────────────────
        for i in range(60):
            a   = i * 6.0
            rad = _math.radians(a - 90)
            if i % 5 == 0:
                t_out, t_in, lw = face_r - 2, face_r - 12, 2
            else:
                t_out, t_in, lw = face_r - 3, face_r - 7, 1
            c.create_line(
                CX + t_out * _math.cos(rad), CY + t_out * _math.sin(rad),
                CX + t_in  * _math.cos(rad), CY + t_in  * _math.sin(rad),
                fill=tick_col, width=lw)

        # 数字（反時計回り配置、時刻 or % 切替）
        if face_r > 70 and self._total_sec > 0:
            num_r  = face_r * 0.76
            num_fs = max(7, int(face_r * 0.09))
            if self._circle_num_mode == "%":
                # 10% 刻み・逆順（残り時間: 90%→10%）、9 目盛り × 36°
                marks = [(i, -i * 36.0, f"{(10 - i) * 10}%") for i in range(1, 10)]
            else:
                # 総時間を12等分した残り時間（逆順）、11 目盛り × 30°
                step_sec = self._total_sec / 12
                marks = []
                for i in range(1, 12):
                    val = round((12 - i) * step_sec)
                    m, s = divmod(val, 60)
                    marks.append((i, -i * 30.0, f"{m}:{s:02d}" if s else str(m)))
            for _, a, label in marks:
                rad = _math.radians(a - 90)
                c.create_text(
                    CX + num_r * _math.cos(rad),
                    CY + num_r * _math.sin(rad),
                    text=label, fill=num_col,
                    font=("Arial", num_fs))

        # ── 分針（1時間で1回転）────────────────────────────
        elapsed_s = self._elapsed_ms / 1000.0
        min_angle = -(elapsed_s % 3600) / 3600 * 360
        min_r     = face_r * 0.60
        back_r    = face_r * 0.14
        rad  = _math.radians(min_angle - 90)
        brad = rad + _math.pi
        c.create_line(
            CX + back_r * _math.cos(brad), CY + back_r * _math.sin(brad),
            CX + min_r  * _math.cos(rad),  CY + min_r  * _math.sin(rad),
            fill=hand_m, width=5, capstyle="round")

        # ── 秒針（総時間 < 1分なら全体で1回転、それ以外は60秒で1回転）─────
        sec_period = float(self._total_sec) if 0 < self._total_sec < 60 else 60.0
        sec_angle  = -(elapsed_s % sec_period) / sec_period * 360
        sec_r     = face_r * 0.84
        sec_tail  = face_r * 0.22
        rad = _math.radians(sec_angle - 90)
        c.create_line(
            CX - sec_tail * _math.cos(rad), CY - sec_tail * _math.sin(rad),
            CX + sec_r    * _math.cos(rad), CY + sec_r    * _math.sin(rad),
            fill=hand_s, width=2, capstyle="round")

        # ── 細針（精度が 1/10秒・1/100秒 のとき: 1秒で1回転する細い針）──
        if self._prec_code in ("ds", "cs"):
            frac       = (self._elapsed_ms % 1000) / 1000.0
            fine_angle = -frac * 360
            fine_r     = face_r * 0.90
            fine_tail  = face_r * 0.16
            rad = _math.radians(fine_angle - 90)
            c.create_line(
                CX - fine_tail * _math.cos(rad), CY - fine_tail * _math.sin(rad),
                CX + fine_r    * _math.cos(rad), CY + fine_r    * _math.sin(rad),
                fill="#f1c40f", width=1, capstyle="round")

        # 中心ハブ
        hub_r = 5
        c.create_oval(CX - hub_r, CY - hub_r, CX + hub_r, CY + hub_r,
                      fill=hand_s, outline="")

        # ── デジタル時間（コンパクト時も中央に表示。経過/残りを切替）────
        remaining_ms = max(0, self._total_ms - self._elapsed_ms)
        shown_ms = self._elapsed_ms if self._sv_countup.get() else remaining_ms
        time_str = fmt_main(shown_ms, self._prec_code)
        fs_main  = max(14, int(face_r * 0.28))
        c.create_text(CX, CY + face_r * 0.22,
                      text=time_str, fill=text_col,
                      font=("Arial", fs_main, "bold"))

        # ── フェーズ表示（区間名: コンパクト時は下バーに出すので省略）──
        # 目盛り数字（半径 0.76*face_r のリング）と被らないよう、デジタル時間の
        # すぐ上の中央付近に小さく表示し、幅を抑えるため繰り返し接頭辞は付けない
        if not self._is_compact:
            kind, name, rem = self._phase_parts()
            if kind == "seg":
                phase_txt = f"{name}  {t('残り')} {fmt(rem)}"
            elif kind == "leftover":
                phase_txt = f"{t('残り')} {fmt(rem)}"
            elif kind == "done":
                phase_txt = t("完了")
            else:
                phase_txt = ""
            if phase_txt:
                fs_ph = max(8, int(face_r * 0.085))
                c.create_text(CX, CY - face_r * 0.02,
                              text=phase_txt, fill=tick_col,
                              font=("Arial", fs_ph))

        # ── フラッシュオーバーレイ（サークルモード用）───────────────
        if self._circle_flash_on and self._circle_flash_color:
            c.create_rectangle(0, 0, W, H, fill=self._circle_flash_color,
                               outline="", stipple="gray50")

    def _trigger_warn(self, idx: int):
        th = self._warn_thresholds[idx]
        # カウントゼロと同じ全体点滅（overlay）、色はしきい値ごとに設定
        self._start_flash([th.color], 220, th.count * 2, overlay=True)

    # ── 精度変更 ──────────────────────────────────────────────────────────────

    def _apply_disp_font(self):
        label = untr(self._prec_btn.get())
        _, _, base_font = PRECISION[label]
        factor, circle_h = DISP_SIZE_CFG.get(self._disp_size, (1.0, 360))
        self._time_lbl.configure(font=ctk.CTkFont(size=max(20, int(base_font * factor)), weight="bold"))
        self._circle_canvas.configure(height=circle_h)

    def _on_precision_change(self, label: str):
        label = untr(label)
        code, _, _ = PRECISION[label]
        self._prec_code = code
        self._apply_disp_font()
        self._refresh_display()

    def _on_disp_size_change(self, value: str):
        self._disp_size = untr(value)
        self._apply_disp_font()
        self._refresh_display()

    # ── 区間管理 ──────────────────────────────────────────────────────────────

    def _leftover(self) -> int:
        return max(0, self._total_sec - sum(s.duration_seconds for s in self._segments))

    def _redistribute_equal(self):
        n = len(self._segments)
        if n == 0:
            return
        base = self._total_sec // n   # 余りは「残り」セクションへ（区間は全て同一秒数）
        for seg in self._segments:
            seg.duration_seconds = max(MIN_SEG_SEC, base)

    def _equalize(self):
        self._redistribute_equal()
        self._rebuild_rows()
        self._refresh_display()

    def _move_segment(self, idx: int, direction: int):
        other = idx + direction
        if not (0 <= other < len(self._segments)):
            return
        self._segments[idx], self._segments[other] = self._segments[other], self._segments[idx]
        self._rebuild_rows()
        self._refresh_display()

    def _on_memo_change(self, idx: int, var: ctk.StringVar):
        # メモは表示の付帯情報。再描画は不要（フェーズ表示は次回更新時に反映）
        if 0 <= idx < len(self._segments):
            self._segments[idx].memo = var.get()

    # ── 区間行のドラッグ並べ替え ──────────────────────────────────────────────
    def _drag_start(self, idx: int, event):
        self._drag_seg_from = idx

    def _drag_motion(self, event):
        if self._drag_seg_from is None:
            return
        tgt = self._segment_idx_at_y(event.y_root)
        # ドラッグ中の視覚フィードバック: 対象行を薄くハイライト
        for i, fr in enumerate(self._row_frames):
            try:
                fr.configure(fg_color=("gray75", "gray25") if i == tgt
                             else ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
            except Exception:
                pass

    def _drag_release(self, event):
        src = self._drag_seg_from
        self._drag_seg_from = None
        if src is None:
            return
        tgt = self._segment_idx_at_y(event.y_root)
        if tgt is not None and 0 <= tgt < len(self._segments) and tgt != src:
            seg = self._segments.pop(src)
            self._segments.insert(tgt, seg)
            self._rebuild_rows()
            self._refresh_display()
        else:
            self._rebuild_rows()   # ハイライトを元に戻す

    def _segment_idx_at_y(self, y_root: int) -> Optional[int]:
        """画面上のy座標がどの区間行の上にあるかを返す"""
        best = None
        for i, fr in enumerate(self._row_frames):
            try:
                top = fr.winfo_rooty()
                bot = top + fr.winfo_height()
            except Exception:
                continue
            if y_root < top:
                return i if best is None else best
            if top <= y_root <= bot:
                return i
            best = i   # y はこの行より下 → 現状最後の候補
        return best

    def _add_segment(self):
        n = len(self._segments)
        self._segments.append(Segment(str(n + 1), 0, PALETTE[n % len(PALETTE)]))
        self._redistribute_equal()
        self._rebuild_rows()
        self._draw_timeline()

    def _remove_segment(self):
        if self._segments:
            self._segments.pop()
            self._redistribute_equal()
            self._rebuild_rows()
            self._draw_timeline()

    # ── 区間行ウィジェット ────────────────────────────────────────────────────

    def _rebuild_rows(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._row_dur_vars = []
        self._row_rem_lbls = []
        self._row_sts_lbls = []
        self._row_frames = []
        self._cnt_lbl.configure(text=str(len(self._segments)))

        if not self._segments:
            ctk.CTkLabel(self._scroll,
                         text=t("＋ボタンで区間を追加してください。"),
                         text_color=("gray10", "gray55")).grid(pady=24)
        else:
            for i, seg in enumerate(self._segments):
                self._make_seg_row(i, seg)

        lo = self._leftover()
        if lo > 0:
            self._make_remain_row(lo)
        self._update_rows()

    def _make_seg_row(self, idx: int, seg: Segment):
        n = len(self._segments)
        f = ctk.CTkFrame(self._scroll, corner_radius=8)
        f.grid(row=idx, column=0, padx=4, pady=3, sticky="ew")
        f.grid_columnconfigure(5, weight=1)   # メモ欄が伸びる
        self._row_frames.append(f)

        # ドラッグ用ハンドル（つかんで上下に並べ替え）。tk.Label なので
        # ButtonPress/Motion/Release がそのまま受け取れる。
        is_dark = ctk.get_appearance_mode().lower() != "light"
        fg_col = f.cget("fg_color")
        row_bg = (fg_col[1] if is_dark else fg_col[0]) if isinstance(fg_col, (list, tuple)) else fg_col
        handle = tk.Label(f, text="⠿", width=2, cursor="fleur", fg="#888888", bg=row_bg)
        handle.grid(row=0, column=0, padx=(6, 0))
        handle.bind("<ButtonPress-1>",   lambda e, i=idx: self._drag_start(i, e))
        handle.bind("<B1-Motion>",       self._drag_motion)
        handle.bind("<ButtonRelease-1>", self._drag_release)

        chip = tk.Frame(f, bg=seg.color, width=10, cursor="hand2")
        chip.grid(row=0, column=1, sticky="ns", padx=(2, 0), pady=4)
        chip.bind("<Button-1>", lambda _, i=idx: self._pick_color(i))

        nv = ctk.StringVar(value=seg.name)
        nv.trace_add("write", lambda *_, i=idx, v=nv: self._on_name_change(i, v))
        ctk.CTkEntry(f, textvariable=nv, width=72, height=28).grid(
            row=0, column=2, padx=(8, 4), pady=6)

        dv = ctk.StringVar(value=dur_str(seg.duration_seconds))
        de = ctk.CTkEntry(f, textvariable=dv, width=60, height=28)
        de.grid(row=0, column=3, padx=4, pady=6)
        de.bind("<Return>",   lambda _, i=idx, v=dv: self._on_dur_commit(i, v))
        de.bind("<FocusOut>", lambda _, i=idx, v=dv: self._on_dur_commit(i, v))
        # ホイールで増減: 分の位置なら±1分、秒の位置なら±1秒（Shiftで×10）。
        de._entry.bind("<MouseWheel>", lambda e, i=idx: self._on_dur_wheel(i, e))
        ctk.CTkLabel(f, text="M:SS", text_color=("gray10", "gray50"),
                     font=ctk.CTkFont(size=11), width=36).grid(row=0, column=4, sticky="w")

        # メモ／タスク名（任意・中央で伸びる）
        mv = ctk.StringVar(value=seg.memo)
        mv.trace_add("write", lambda *_, i=idx, v=mv: self._on_memo_change(i, v))
        me = ctk.CTkEntry(f, textvariable=mv, height=28,
                          placeholder_text=t("メモ"))
        me.grid(row=0, column=5, padx=6, pady=6, sticky="ew")

        rl = ctk.CTkLabel(f, text=t("残り —"), font=ctk.CTkFont(size=12), width=110, anchor="e")
        rl.grid(row=0, column=6, padx=(4, 8))

        sl = ctk.CTkLabel(f, text=t("待機"), font=ctk.CTkFont(size=11),
                          text_color="#5dade2", width=50, anchor="center")
        sl.grid(row=0, column=7, padx=(0, 6))

        ctk.CTkButton(f, text="↑", width=26, height=26,
                      fg_color="gray30", hover_color="gray20",
                      state="normal" if idx > 0 else "disabled",
                      command=lambda i=idx: self._move_segment(i, -1)).grid(
            row=0, column=8, padx=2)
        ctk.CTkButton(f, text="↓", width=26, height=26,
                      fg_color="gray30", hover_color="gray20",
                      state="normal" if idx < n - 1 else "disabled",
                      command=lambda i=idx: self._move_segment(i, 1)).grid(
            row=0, column=9, padx=(2, 8))

        self._row_dur_vars.append(dv)
        self._row_rem_lbls.append(rl)
        self._row_sts_lbls.append(sl)

    def _make_remain_row(self, secs: int):
        row = len(self._segments)
        f = ctk.CTkFrame(self._scroll, corner_radius=8, fg_color="#252535")
        f.grid(row=row, column=0, padx=4, pady=3, sticky="ew")
        tk.Frame(f, bg=REMAIN_COLOR, width=10).grid(
            row=0, column=0, sticky="ns", padx=(6, 0), pady=4)
        ctk.CTkLabel(f, text=t("残り"), font=ctk.CTkFont(size=13),
                     text_color=("gray15", "gray60"), width=80).grid(
            row=0, column=1, padx=(8, 6), pady=8, sticky="w")
        ctk.CTkLabel(f, text=fmt(secs), text_color=("gray10", "gray50")).grid(row=0, column=2, padx=6)

    def _on_name_change(self, idx: int, var: ctk.StringVar):
        if 0 <= idx < len(self._segments):
            self._segments[idx].name = var.get()
            self._draw_timeline()

    def _sync_total_from_segments(self):
        total = sum(s.duration_seconds for s in self._segments)
        if total == 0:
            return
        self._total_sec = total
        self._total_var.set(dur_str(total))
        self._elapsed_ms = min(self._elapsed_ms, self._total_ms)

    def _on_dur_commit(self, idx: int, var: ctk.StringVar):
        if not (0 <= idx < len(self._segments)):
            return
        try:
            secs = max(MIN_SEG_SEC, parse_dur(var.get()))
        except (ValueError, IndexError):
            var.set(dur_str(self._segments[idx].duration_seconds))
            return
        self._segments[idx].duration_seconds = secs
        var.set(dur_str(secs))
        self._sync_total_from_segments()
        self._rebuild_rows()
        self._refresh_display()

    def _pick_color(self, idx: int):
        if not (0 <= idx < len(self._segments)):
            return
        res = colorchooser.askcolor(self._segments[idx].color, parent=self, title=t("色を選択"))
        if res and res[1]:
            self._segments[idx].color = res[1]
            self._rebuild_rows()
            self._draw_timeline()

    def _update_rows(self):
        """④ O(n²) → O(n): 累積和で start/end を計算"""
        # 行ラベルが未構築（ロード途中など）の場合は存在する分だけ更新
        n = min(len(self._segments), len(self._row_rem_lbls), len(self._row_sts_lbls))
        elapsed = self._elapsed_sec
        cum = 0
        for i in range(n):
            seg   = self._segments[i]
            start = cum
            end   = cum + seg.duration_seconds
            cum   = end
            if elapsed >= end:
                txt, col, sts = t("完了"), ("gray10", "gray50"), t("完了")
            elif elapsed > start:
                txt, col, sts = f"{t('残り')} {fmt(end - elapsed)}", "#2ecc71", t("進行中")
            else:
                txt, col, sts = f"{t('残り')} {fmt(seg.duration_seconds)}", "#5dade2", t("待機")
            self._row_rem_lbls[i].configure(text=txt, text_color=col)
            self._row_sts_lbls[i].configure(text=sts, text_color=col)

    # ── タイムライン描画 ──────────────────────────────────────────────────────

    def _draw_timeline(self):
        self._timeline_cfg_job = None
        c = self._canvas
        c.delete("all")
        W = c.winfo_width()
        if W < 10 or self._total_sec == 0:
            return

        BAR_H, y0 = 42, 9
        y1 = y0 + BAR_H
        c.create_rectangle(0, y0, W, y1, fill="#3a3a4a", outline="")

        self._divider_xs = []
        # ① ミリ秒精度で経過量を計算
        x, rem_elap_ms = 0.0, float(self._elapsed_ms)

        # 区間合計がタイマーを超える場合、比例スケールで正規化
        sum_seg_ms_tl = sum(float(s.duration_seconds * 1000) for s in self._segments)
        denom_ms_tl   = max(float(self._total_ms), sum_seg_ms_tl)

        for seg in self._segments:
            seg_ms       = float(seg.duration_seconds * 1000)
            sw           = W * seg_ms / denom_ms_tl
            xr           = min(float(W), x + sw)
            seg_timer_ms = seg_ms / denom_ms_tl * self._total_ms
            done_ms      = min(rem_elap_ms, seg_timer_ms)
            done_w       = sw * (done_ms / seg_timer_ms) if seg_timer_ms else 0
            rem_elap_ms -= done_ms

            if done_w > 0:
                c.create_rectangle(int(x), y0, int(x + done_w), y1,
                                   fill=darken(seg.color), outline="")
            if int(x + done_w) < int(xr):
                c.create_rectangle(int(x + done_w), y0, int(xr), y1,
                                   fill=seg.color, outline="")
            if sw > 44:
                mc = max(1, int(sw // 10))
                label = seg.name[:mc] + ("…" if len(seg.name) > mc else "")
                c.create_text(int(x + sw / 2), y0 + BAR_H // 2,
                              text=label, fill="white", font=("Arial", 10, "bold"))

            self._divider_xs.append(int(xr))
            x = xr

        lo = self._leftover()
        if lo > 0 and x < W:
            lo_ms  = float(lo * 1000)
            rem_w  = W - x
            done_lo_ms = min(rem_elap_ms, lo_ms)
            done_lo_w  = rem_w * (done_lo_ms / lo_ms) if lo_ms else 0
            if done_lo_w > 0:
                c.create_rectangle(int(x), y0, int(x + done_lo_w), y1,
                                   fill=darken(REMAIN_COLOR, 0.6), outline="")
            c.create_rectangle(int(x + done_lo_w), y0, W, y1, fill=REMAIN_COLOR, outline="")
            c.create_text(int(x + rem_w / 2), y0 + BAR_H // 2,
                          text=t("残り"), fill="white", font=("Arial", 10))

        n = len(self._segments)
        drag_count = (n - 1) + (1 if lo > 0 else 0)
        for i in range(drag_count):
            dx = self._divider_xs[i]
            c.create_line(dx, y0 - 4, dx, y1 + 4, fill="white", width=2, dash=(4, 3))

        hx = int(W * min(1.0, self._elapsed_ms / self._total_ms))
        c.create_line(hx, y0 - 6, hx, y1 + 6, fill="#f0f0f0", width=2)
        c.create_polygon(hx - 5, y0 - 6, hx + 5, y0 - 6, hx, y0, fill="#f0f0f0", outline="")

    # ── タイムライン ドラッグ ─────────────────────────────────────────────────

    def _draggable_count(self) -> int:
        return (len(self._segments) - 1) + (1 if self._leftover() > 0 else 0)

    def _find_divider(self, x: int) -> Optional[int]:
        count = self._draggable_count()
        for i in range(count):
            if i < len(self._divider_xs) and abs(x - self._divider_xs[i]) <= 7:
                return i
        return None

    def _on_canvas_motion(self, event):
        self._canvas.configure(
            cursor="sb_h_double_arrow" if self._find_divider(event.x) is not None else "")

    def _on_canvas_click(self, event):
        div = self._find_divider(event.x)
        if div is not None:
            self._drag_div = div
            self._drag_start_x = event.x
            self._drag_seg_secs = [s.duration_seconds for s in self._segments]

    def _on_canvas_drag(self, event):
        if self._drag_div is None:
            return
        W = self._canvas.winfo_width()
        if W < 10:
            return
        delta = round((event.x - self._drag_start_x) * self._total_sec / W)
        n, div = len(self._segments), self._drag_div
        if div < n - 1:
            li, ri = div, div + 1
            ol, or_ = self._drag_seg_secs[li], self._drag_seg_secs[ri]
            combined = ol + or_
            nl = max(MIN_SEG_SEC, min(combined - MIN_SEG_SEC, ol + delta))
            self._segments[li].duration_seconds = nl
            self._segments[ri].duration_seconds = combined - nl
            self._row_dur_vars[li].set(dur_str(nl))
            self._row_dur_vars[ri].set(dur_str(combined - nl))
        else:
            li = n - 1
            ol = self._drag_seg_secs[li]
            max_l = self._total_sec - sum(self._drag_seg_secs[:li])
            nl = max(MIN_SEG_SEC, min(max_l, ol + delta))
            self._segments[li].duration_seconds = nl
            self._row_dur_vars[li].set(dur_str(nl))
        self._draw_timeline()
        self._update_rows()

    def _on_canvas_release(self, event):
        if self._drag_div is not None:
            self._drag_div = None
            self._rebuild_rows()

    # ── タイマー制御 ──────────────────────────────────────────────────────────

    def _apply_total(self):
        if self._running:          # ② 実行中は変更不可
            return
        try:
            secs = parse_dur(self._total_var.get())
            if secs <= 0:
                return
        except (ValueError, IndexError):
            self._total_var.set(dur_str(self._total_sec))
            return
        old_total = self._total_sec
        self._total_sec = secs
        self._total_var.set(dur_str(secs))
        self._elapsed_ms = 0
        # 区間があれば、現在の比率を保ったまま新しい総時間に合わせて調整する
        # （等分なら等分のまま、手動で比率を変えていればその比率のまま拡縮）
        if self._segments and old_total > 0:
            factor = secs / old_total
            for seg in self._segments:
                seg.duration_seconds = max(MIN_SEG_SEC,
                                           round(seg.duration_seconds * factor))
        self._rebuild_rows()
        self._refresh_display()

    def _focus_in_entry(self) -> bool:
        """入力欄（Entry等）にフォーカス中か"""
        w = self.focus_get()
        return w is not None and w.__class__.__name__ in (
            "Entry", "CTkEntry", "Text", "Spinbox")

    def _on_space_key(self, event=None):
        if self._focus_in_entry():
            return
        self._toggle()
        return "break"   # スペースによるボタン等の既定動作を抑制

    def _on_key(self, event=None):
        """ショートカット: R=リセット, N=次区間, P/B=前区間, C=コンパクト, F=表示切替"""
        if self._focus_in_entry() or not event:
            return
        key = (event.keysym or "").lower()
        if key == "r":
            self._reset()
        elif key == "n":
            self._skip_segment(1)
        elif key in ("p", "b"):
            self._skip_segment(-1)
        elif key == "c":
            self._sv_compact.set(not self._sv_compact.get())
            self._on_compact_toggle()
        elif key == "f":
            new = "フラット" if self._style_mode == "サークル" else "サークル"
            self._style_btn.set(t(new))
            self._on_style_change(t(new))
        elif event.keysym == "question" or key == "question":
            self._show_shortcuts()
        else:
            return
        return "break"

    def _show_shortcuts(self):
        """ショートカット一覧をダイアログ表示（? キー）"""
        win = ctk.CTkToplevel(self)
        win.title(t("キーボードショートカット"))
        win.geometry("420x420")
        win.transient(self)
        ctk.CTkLabel(win, text=t("⌨  キーボードショートカット"),
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 8))
        body = ctk.CTkScrollableFrame(win, width=380)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_columnconfigure(1, weight=1)
        for i, (key, desc) in enumerate(SHORTCUTS):
            ctk.CTkLabel(body, text=t(key), anchor="w", width=140,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=("#1a5276", "#5dade2")).grid(
                row=i, column=0, sticky="w", padx=(4, 8), pady=4)
            ctk.CTkLabel(body, text=t(desc), anchor="w",
                         font=ctk.CTkFont(size=13)).grid(
                row=i, column=1, sticky="w", pady=4)
        win.after(120, win.focus)

    def _skip_segment(self, direction: int):
        """実行位置を前後の区間境界へジャンプ（direction: +1=次, -1=現区間先頭/前区間）"""
        if self._total_sec == 0:
            return
        bounds, cum = [0], 0
        for seg in self._segments:
            cum += seg.duration_seconds
            bounds.append(cum)
        if bounds[-1] < self._total_sec:   # 「残り」区間の境界
            bounds.append(self._total_sec)
        cur = self._elapsed_sec
        if direction > 0:
            target = next((b for b in bounds if b > cur), self._total_sec)
        else:
            seg_start = max((b for b in bounds if b <= cur), default=0)
            if cur - seg_start <= 1 and seg_start > 0:
                prev = [b for b in bounds if b < seg_start]
                target = prev[-1] if prev else 0
            else:
                target = seg_start
        target = max(0, min(target, self._total_sec))
        self._elapsed_ms = target * 1000
        self._ms_at_start = self._elapsed_ms
        self._wall_start = _time_mod.monotonic()
        self._warned.clear()
        self._active_seg_idx = self._get_active_seg_idx()
        if not self._running:
            if self._elapsed_ms >= self._total_ms:
                self._set_start_btn("▶  スタート", "#27ae60", "#1e8449")
            else:
                label = "▶  再開" if self._elapsed_ms > 0 else "▶  スタート"
                self._set_start_btn(label, "#27ae60", "#1e8449")
        self._refresh_display()

    def _wheel_unit(self, widget, x: int) -> int:
        """M:SS 表示の Entry 上で、マウス位置が分(コロンの左)なら60、
        秒(右)なら1 を返す。判定できなければ秒(1)。"""
        try:
            text = widget.get()
            colon = text.find(":")
            idx = widget.index(f"@{x}")
            if colon >= 0 and idx <= colon:
                return 60   # 分
        except Exception:
            pass
        return 1            # 秒

    def _on_dur_wheel(self, idx: int, event):
        """区間時間をホイールで増減。マウスが分の位置なら±1分、秒なら±1秒
        （Shiftで×10）。行ウィジェットは作り直さずちらつかせない。"""
        if not (0 <= idx < len(self._segments)) or self._running:
            return "break"
        unit = self._wheel_unit(event.widget, event.x)
        if event.state & 0x0001:   # Shift で ×10
            unit *= 10
        delta = unit if event.delta > 0 else -unit
        seg = self._segments[idx]
        # 「残り」行が表示中か（区間数より子ウィジェットが多い）を先に判定
        had_remain = len(self._scroll.winfo_children()) > len(self._segments)
        seg.duration_seconds = max(MIN_SEG_SEC, seg.duration_seconds + delta)
        self._sync_total_from_segments()   # total=区間合計 → leftover は 0 になる
        # 該当行と全体表示だけ即時更新（ウィジェットは作り直さない＝ちらつかない）
        if idx < len(self._row_dur_vars):
            self._row_dur_vars[idx].set(dur_str(seg.duration_seconds))
        self._total_var.set(dur_str(self._total_sec))
        self._update_rows()
        self._draw_timeline()
        if self._style_mode == "サークル":
            self._draw_circle_clock()
        # 残り行が不要になった場合のみ作り直す（通常はちらつかない）
        if had_remain and self._leftover() == 0:
            self._rebuild_rows()
        return "break"

    def _on_total_wheel(self, event):
        """総時間をホイールで増減。マウスが分の位置なら±1分、秒なら±1秒
        （Shiftで×10）。区間はそのままで「残り」が増減する。"""
        if self._running:
            return "break"
        unit = self._wheel_unit(event.widget, event.x)
        if event.state & 0x0001:
            unit *= 10
        delta = unit if event.delta > 0 else -unit
        had_remain = len(self._scroll.winfo_children()) > len(self._segments)
        self._total_sec = max(1, self._total_sec + delta)
        self._total_var.set(dur_str(self._total_sec))
        self._elapsed_ms = min(self._elapsed_ms, self._total_ms)
        self._update_rows()
        self._draw_timeline()
        if self._style_mode == "サークル":
            self._draw_circle_clock()
        # 「残り」行の有無が変わったら作り直す
        if had_remain != (self._leftover() > 0):
            self._rebuild_rows()
        return "break"

    def _preview_sound(self):
        """完了音を1回テスト再生（音声OFFでも鳴らす）"""
        if not _SOUND_AVAILABLE:
            self._flash_status("この環境では音を再生できません")
            return
        pattern = ALERT_SOUND.get("complete", [])
        self._alarm_stop.clear()
        def _play():
            try:
                for freq, dur in pattern:
                    if freq > 0:
                        _winsound.Beep(freq, dur)
                    else:
                        _time_mod.sleep(dur / 1000)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def _preview_flash(self):
        """完了点滅を数回テスト表示"""
        cfg = ALERT_FLASH["complete"]
        # このクリック自体が _on_disp_click（クリックで点滅停止）に伝播するため、
        # 点滅開始をクリック処理の後に遅延させて即停止を防ぐ
        self.after(60, lambda: self._start_flash(
            cfg["colors"], cfg["interval"], 6, loop=False, overlay=True))

    def _toggle(self):
        if self._total_sec == 0:
            return
        if self._running:
            self._pause()
        else:
            # elapsed=0 なら新規スタート（カウントリセット）、そうでなければ再開
            self._start(fresh=(self._elapsed_ms == 0))

    def _set_start_btn(self, text: str, fg: str, hover: str):
        """通常・コンパクト両方のスタート/一時停止ボタンを同期更新"""
        text = t(text)   # 日本語キー → 現在言語
        self._start_btn.configure(text=text, fg_color=fg, hover_color=hover)
        # コンパクトバーは短いラベルにする
        short = text.replace("  ", " ")
        self._compact_start_btn.configure(text=short, fg_color=fg, hover_color=hover)

    def _start(self, fresh: bool = True, keep_flash: bool = False):
        # 繰り返し再スタート予約をキャンセル（手動操作が優先）
        if self._repeat_after_id:
            self.after_cancel(self._repeat_after_id)
            self._repeat_after_id = None
        if fresh:
            self._repeat_count = 0  # 手動スタートは回数リセット
        self._running = True
        self._warned.clear()
        self._active_seg_idx = self._get_active_seg_idx()
        if not keep_flash:
            self._stop_flash()
        self._set_start_btn("⏸  一時停止", "#e67e22", "#ca6f1e")
        self._wall_start = _time_mod.monotonic()
        self._ms_at_start = self._elapsed_ms
        # コンパクトモードが有効なら自動最小化（新規スタート・再開どちらも）
        if self._sv_compact.get():
            self._enter_compact()
        self._tick()

    def _pause(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        # 繰り返し再スタート予約もキャンセル
        if self._repeat_after_id:
            self.after_cancel(self._repeat_after_id)
            self._repeat_after_id = None
        self._set_start_btn("▶  再開", "#27ae60", "#1e8449")

    def _reset(self):
        self._pause()
        self._elapsed_ms = 0
        self._repeat_count = 0
        self._warned.clear()
        self._active_seg_idx = -1
        self._stop_flash()
        self._exit_compact()
        self._time_lbl.configure(text_color=("gray10", "gray90"))
        self._set_start_btn("▶  スタート", "#27ae60", "#1e8449")
        self._refresh_display()

    def _tick(self):
        if not self._running:
            return

        # 壁時計から経過時間を算出（精度設定に関係なく正確）
        wall_elapsed_ms = int((_time_mod.monotonic() - self._wall_start) * 1000)
        self._elapsed_ms = min(self._ms_at_start + wall_elapsed_ms, self._total_ms)

        if self._elapsed_ms >= self._total_ms:
            self._running = False
            self._set_start_btn("▶  スタート", "#27ae60", "#1e8449")
            if "complete" not in self._warned:
                self._warned.add("complete")
                self._trigger_complete()
            self._refresh_display()
            return

        new_idx = self._get_active_seg_idx()
        # overlay 点滅中（完了アラーム）は区間・警告フラッシュを起動しない
        if (not self._flash_canvases
                and self._active_seg_idx >= 0
                and new_idx != self._active_seg_idx
                and new_idx < len(self._segments)
                and self._sv_segment.get()
                and "complete" not in self._warned):
            self._trigger_segment(self._active_seg_idx)
        self._active_seg_idx = new_idx

        remaining_s = max(0, self._total_ms - self._elapsed_ms) // 1000
        if not self._flash_canvases:   # overlay 点滅中は警告フラッシュを抑制
            for i, th in enumerate(self._warn_thresholds):
                key = f"warn_{i}"
                if th.enabled and remaining_s <= th.seconds and key not in self._warned:
                    self._warned.add(key)
                    self._trigger_warn(i)

        self._refresh_display()
        # 常に REDRAW_MS 間隔で再描画（精度設定に関わらずバーは滑らか）
        self._after_id = self.after(REDRAW_MS, self._tick)

    def _refresh_display(self):
        remaining_ms = max(0, self._total_ms - self._elapsed_ms)
        # 経過時間モードなら経過、それ以外は残りを表示
        shown_ms = self._elapsed_ms if self._sv_countup.get() else remaining_ms
        self._time_lbl.configure(text=fmt_main(shown_ms, self._prec_code))
        self._breakdown_lbl.configure(text=fmt_hms(shown_ms))

        if not self._flash_job:
            remaining_s = remaining_ms // 1000
            if remaining_s <= 10:
                tcolor = "#e74c3c"
            elif remaining_s <= 30:
                tcolor = "#e67e22"
            elif remaining_s <= 60:
                tcolor = ("#b8860b", "#f1c40f")
            else:
                tcolor = ("gray10", "gray90")
            self._time_lbl.configure(text_color=tcolor)

        # 繰り返しモードで実行中: 第N回を接頭辞として表示
        n = self._repeat_count + 1
        rpt_prefix = ((f"Round {n}  ─  " if _LANG == "en" else f"第 {n} 回  ─  ")
                      if self._sv_repeat.get() else "")
        kind, name, rem = self._phase_parts()
        if kind == "seg":
            phase = f"{rpt_prefix}{name}  ─  {t('残り')} {fmt(rem)}"
        elif kind == "leftover":
            phase = f"{rpt_prefix}{t('残り')}  ─  {fmt(rem)}"
        elif kind == "done":
            phase = t("完了")
        else:
            phase = ""
        self._phase_lbl.configure(text=phase, text_color=("gray20", "gray65"))

        # リサイズ中は重いキャンバス描画を抑制（確定後に _on_resize_settled で描画）
        if not self._resizing:
            self._draw_timeline()
            if self._style_mode == "サークル":
                self._draw_circle_clock()
        self._update_rows()
        if self._is_compact:
            self._update_compact_info()

    def _update_compact_info(self):
        """コンパクトバーに区間名・残り時間・周回数を表示"""
        n = self._repeat_count + 1
        rpt = (f"Round {n}" if _LANG == "en" else f"第{n}回") if self._sv_repeat.get() else ""
        kind, name, rem = self._phase_parts()
        if kind == "seg":
            seg_txt = f"{name}  {t('残り')} {fmt(rem)}"
        elif kind == "leftover":
            seg_txt = f"{t('残り')}  {fmt(rem)}"
        elif kind == "done":
            seg_txt = t("完了")
        else:
            seg_txt = ""
        bits = [b for b in (rpt, seg_txt) if b]
        self._compact_info_lbl.configure(text="    ".join(bits))


if __name__ == "__main__":
    app = TimerApp()
    app.mainloop()
