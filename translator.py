"""
translator.py
Qt UI layer + thin OCRWorker thread.
All business logic lives in the pure modules:
  capture/, ocr/, color_sampler, block_merger, translation_pipeline, glossary_service.
"""

import sys
import time
import threading
from dataclasses import dataclass

from PyQt6.QtWidgets import (QApplication, QMainWindow, QHBoxLayout, QVBoxLayout,
                              QWidget, QPushButton, QLineEdit,
                              QLabel, QListWidget, QListWidgetItem)
from PyQt6.QtCore    import Qt, QThread, pyqtSignal, QRect, QTimer, QPoint
from PyQt6.QtGui     import QPainter, QColor, QPen, QFont

import capture
import ocr
import color_sampler
from block_merger        import merge_blocks_by_proximity
from translation_pipeline import TranslationPipeline, has_source_content
from translator_engine   import engine_translate
from glossary_service    import GlossaryService, GlossaryEntry
from ocr_model           import OCRBlock
from config_manager      import load_config, save_config
from settings_ui         import SettingsDialog
from hotkey_listener     import HotkeyListener
from tracking_utils      import bbox_iou, is_same_track, should_drop_tracked_block


# ---------------------------------------------------------------------------
# State tracking helpers (pure Python, no Qt deps)
# ---------------------------------------------------------------------------

@dataclass
class _TrackedBlock:
    """One UI text element tracked across OCR ticks."""
    block:       OCRBlock   # last confirmed state (bbox, text, colors)
    translation: str        # last confirmed translation
    ttl:         int        # ticks remaining before ghost expires
    confirmed:   bool = True  # True if OCR confirmed it on the latest processed frame


# ---------------------------------------------------------------------------
# OCR Worker thread
# ---------------------------------------------------------------------------

class OCRWorker(QThread):
    result_ready = pyqtSignal(list)   # list[OCRBlock] — emitted up to twice per new text

    def __init__(self, roi: tuple, config: dict, pipeline: TranslationPipeline):
        super().__init__()
        self.roi      = roi
        self.config   = config        # shared dict reference
        self.pipeline = pipeline      # injected — owns cache + translation
        self.running  = True
        self.paused   = False

        self._capture = capture.get_provider()
        self._ocr     = ocr.get_provider()
        self._languages = ocr.OCR_LANG_MAP.get(config.get("source_language", "Korean"),
                                                ["ko-KR"])
        self._tracked:      list[_TrackedBlock] = []
        self._tracked_lock: threading.Lock      = threading.Lock()
        self._latest_seen:  list[OCRBlock]      = []
        self._latest_seen_lock: threading.Lock  = threading.Lock()
        self._custom_words: list[str]           = self._build_custom_words()
        self.overlay_win_id: int | None = None
        self.game_win_id:    int | None = None

        # ── Single-thread translation queue (drop-old strategy) ────────
        # Only one translation thread is ever alive.  When a new OCR tick
        # finds missing texts while the previous translation is still
        # running, the pending job is *replaced* so we never waste time
        # translating stale screen content.
        self._job_lock = threading.Lock()
        self._pending_job: tuple[list[OCRBlock], list[str]] | None = None
        self._job_event = threading.Event()
        self._translator_thread: threading.Thread | None = None

        # Frame-diff skip: cache last capture hash to skip OCR on unchanged frames
        self._last_fingerprint: int | None = None

    def _build_custom_words(self) -> list[str]:
        """Extract source-language glossary terms to hint the OCR engine."""
        if not self.pipeline.glossary:
            return []
        src  = self.config.get("source_language", "Korean")
        tgt  = self.config.get("target_language", "Traditional Chinese")
        return [w for e in self.pipeline.glossary.get_entries(src, tgt)
                if (w := e.terms.get(src))]

    def reload_config(self) -> None:
        """Re-derive cached config values after the shared dict is mutated."""
        self._languages    = ocr.OCR_LANG_MAP.get(
            self.config.get("source_language", "Korean"), ["ko-KR"]
        )
        self._custom_words = self._build_custom_words()

    def reload_custom_words(self) -> None:
        """Refresh OCR custom-word hints after glossary changes."""
        self._custom_words = self._build_custom_words()

    def _decay_ghosts_on_skipped_frame(self) -> list[OCRBlock] | None:
        """Age out ghost blocks when we skip OCR on an identical frame."""
        with self._tracked_lock:
            changed = False
            kept: list[_TrackedBlock] = []
            for t in self._tracked:
                if t.confirmed:
                    kept.append(t)
                    continue
                t.ttl -= 1
                changed = True
                if t.ttl > 0:
                    kept.append(t)
            if not changed:
                return None
            self._tracked = kept
            return [t.block for t in self._tracked]

    def run(self) -> None:
        # Start the single translation consumer thread
        self._translator_thread = threading.Thread(
            target=self._translation_consumer, daemon=True
        )
        self._translator_thread.start()

        while self.running:
            if self.paused:
                with self._tracked_lock:
                    self._tracked = []
                time.sleep(self.config.get("ocr_interval", 1.0))
                continue

            interval = self.config.get("ocr_interval", 1.0)

            # ---- Capture ----
            image = self._capture.grab(self.roi, self.overlay_win_id, self.game_win_id)

            # ---- Frame-diff skip: reuse last tick if pixels are identical ----
            fp = self._capture.fingerprint(image)
            if fp is not None and fp == self._last_fingerprint and self._tracked:
                render_now = self._decay_ghosts_on_skipped_frame()
                if render_now is not None:
                    self.result_ready.emit(render_now)
                time.sleep(interval)
                continue
            self._last_fingerprint = fp

            # ---- OCR ----
            blocks = self._ocr.recognize(image,
                                         self.roi[2], self.roi[3],
                                         self._languages,
                                         self._custom_words)
            color_sampler.annotate_colors(image, blocks, self.roi[2], self.roi[3])
            blocks = merge_blocks_by_proximity(
                blocks,
                gap_ratio        = self.config.get("merge_gap_ratio",        0.8),
                max_height_ratio = self.config.get("merge_max_height_ratio", 1.2),
                min_h_overlap    = self.config.get("merge_min_h_overlap",    0.3),
            )

            # Filter blocks: drop pure ASCII (non-English mode), low confidence, very short text
            source_lang = self.config.get("source_language", "Korean")
            min_conf = self.config.get("min_confidence", 0.0)
            min_len  = self.config.get("min_text_length", 1)
            blocks = [
                b for b in blocks
                if b.conf >= min_conf
                and len(b.text.strip()) >= min_len
                and has_source_content(b.text, source_lang)
            ]
            with self._latest_seen_lock:
                self._latest_seen = list(blocks)

            linger_frames = self.config.get("linger_frames", 3)
            occlusion_threshold = self.config.get("tracked_occlusion_threshold", 0.5)

            # ---- Classify each block: cache hit / state match / new ----
            fresh_translated: list[OCRBlock] = []   # ready to render immediately
            new_blocks:       list[OCRBlock] = []   # need async translation
            missing:          list[str]      = []

            for b in blocks:
                # Fast path: cache hit (Option A _normalize applied inside get_cached)
                cached = self.pipeline.get_cached(b.text)
                if cached is not None:
                    b.translated = cached
                    fresh_translated.append(b)
                    continue

                # Mechanism 3: spatio-temporal match — same position + similar text
                with self._tracked_lock:
                    match = next(
                        (t for t in self._tracked
                         if is_same_track(b.bbox, b.text, t.block.bbox, t.block.text)),
                        None
                    )
                if match is not None:
                    b.translated = match.translation
                    fresh_translated.append(b)
                else:
                    new_blocks.append(b)
                    missing.append(b.text)

            # ---- Mechanism 4: rebuild tracked state with TTL ghost rendering ----
            matched_norm = {self.pipeline._normalize(b.text)
                            for b in fresh_translated + new_blocks}
            with self._tracked_lock:
                new_tracked: list[_TrackedBlock] = []
                for b in fresh_translated:
                    new_tracked.append(_TrackedBlock(
                        b, b.translated, linger_frames, confirmed=True
                    ))
                for t in self._tracked:
                    if self.pipeline._normalize(t.block.text) in matched_norm:
                        continue
                    if should_drop_tracked_block(
                        t.block,
                        blocks,
                        occlusion_threshold=occlusion_threshold,
                    ):
                        continue
                    t.ttl -= 1
                    if t.ttl > 0:
                        t.confirmed = False
                        new_tracked.append(t)   # ghost: keep rendering last known state
                self._tracked = new_tracked
                render_now = [t.block for t in self._tracked]

            self.result_ready.emit(render_now)   # emit #1: cache hits + state matches + ghosts

            # ---- Enqueue translation job for new blocks (drop-old strategy) ----
            if missing:
                with self._job_lock:
                    self._pending_job = (list(new_blocks), list(missing))
                self._job_event.set()

            time.sleep(interval)

        # Signal the consumer thread to exit
        self._job_event.set()

    def _translation_consumer(self) -> None:
        """Single long-lived thread: waits for a translation job, executes it,
        then loops.  Only one translate_apple subprocess runs at a time."""
        while self.running:
            self._job_event.wait()
            if not self.running:
                break
            self._job_event.clear()

            # Grab and clear the pending job atomically
            with self._job_lock:
                job = self._pending_job
                self._pending_job = None

            if job is None:
                continue

            new_blocks, missing = job
            self.pipeline.translate_missing(missing)

            # Add newly translated blocks to _tracked, then emit full state
            linger_frames = self.config.get("linger_frames", 3)
            occlusion_threshold = self.config.get("tracked_occlusion_threshold", 0.5)
            with self._latest_seen_lock:
                latest_seen = list(self._latest_seen)
            with self._tracked_lock:
                for b in new_blocks:
                    if should_drop_tracked_block(
                        b,
                        latest_seen,
                        occlusion_threshold=occlusion_threshold,
                    ):
                        continue
                    cached = self.pipeline.get_cached(b.text)
                    if cached:
                        b.translated = cached
                        self._tracked = [
                            t for t in self._tracked
                            if not (
                                bbox_iou(b.bbox, t.block.bbox) > 0.8
                                and self.pipeline._normalize(b.text)
                                == self.pipeline._normalize(t.block.text)
                            )
                        ]
                        self._tracked.append(_TrackedBlock(
                            b, cached, linger_frames, confirmed=True
                        ))
                render = [t.block for t in self._tracked]
            self.result_ready.emit(render)   # emit #2: after translation, includes ghosts

    def stop(self) -> None:
        self.running = False
        self._job_event.set()          # wake consumer so it can exit
        if self._translator_thread:
            self._translator_thread.join(timeout=5)
        self.wait()


# ---------------------------------------------------------------------------
# BBox worker (no translation, no colour sampling)
# ---------------------------------------------------------------------------

_BBOX_COLORS = [
    QColor(255, 80,  80,  200),
    QColor(80,  180, 255, 200),
    QColor(80,  220, 80,  200),
    QColor(255, 200, 0,   200),
    QColor(200, 100, 255, 200),
]


class RawOCRWorker(QThread):
    result_ready = pyqtSignal(list)   # list[OCRBlock]

    def __init__(self, roi: tuple, config: dict):
        super().__init__()
        self.roi            = roi
        self.config         = config
        self.running        = True
        self.overlay_win_id: int | None = None
        self.game_win_id:    int | None = None
        self._capture       = capture.get_provider()
        self._ocr           = ocr.get_provider()
        self._languages     = ocr.OCR_LANG_MAP.get(
            config.get("source_language", "Korean"), ["ko-KR"]
        )

    def run(self) -> None:
        while self.running:
            interval = self.config.get("ocr_interval", 1.0)
            image    = self._capture.grab(self.roi, self.overlay_win_id, self.game_win_id)
            blocks   = self._ocr.recognize(image, self.roi[2], self.roi[3],
                                           self._languages)
            merged   = merge_blocks_by_proximity(
                blocks,
                gap_ratio        = self.config.get("merge_gap_ratio",        0.8),
                max_height_ratio = self.config.get("merge_max_height_ratio", 1.2),
                min_h_overlap    = self.config.get("merge_min_h_overlap",    0.3),
            )
            self.result_ready.emit(merged)
            time.sleep(interval)

    def stop(self) -> None:
        self.running = False
        self.wait()


# ---------------------------------------------------------------------------
# Step 1 — ROI selector (Snipping Tool)
# ---------------------------------------------------------------------------

class SnippingToolWindow(QMainWindow):
    roi_selected = pyqtSignal(tuple)

    def __init__(self, config: dict, glossary=None, pipeline=None):
        super().__init__()
        self.config    = config
        self._glossary = glossary
        self._pipeline = pipeline
        self.setWindowTitle("翻譯區域截圖定位")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        screens = QApplication.screens()
        geom = screens[0].geometry()
        for s in screens[1:]:
            geom = geom.united(s.geometry())
        self.setGeometry(geom)

        self.begin_pos  = None
        self.end_pos    = None
        self.is_drawing = False
        self.confirm_rect = None
        self.toolbar    = None
        self.has_interacted = False

        self._restore_initial_state()

    def _restore_initial_state(self) -> None:
        self.is_drawing = False
        self.has_interacted = False
        self.begin_pos = None
        self.end_pos = None
        self.confirm_rect = None
        if self.toolbar:
            self.toolbar.hide()
            
        last_roi = self.config.get("last_roi", [])
        if last_roi and len(last_roi) == 4:
            rx, ry, rw, rh = last_roi
            self.confirm_rect = QRect(rx, ry, rw, rh)
            QTimer.singleShot(100, lambda: self.show_toolbar(self.confirm_rect))
        
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        draw_rect = None
        if self.is_drawing and self.begin_pos and self.end_pos:
            draw_rect = QRect(self.begin_pos, self.end_pos).normalized()
        elif self.confirm_rect:
            draw_rect = self.confirm_rect

        if draw_rect:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(draw_rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#00A2FF"), 4, Qt.PenStyle.DashLine))
            painter.drawRect(draw_rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.has_interacted = True
            if self.toolbar:
                self.toolbar.hide()
            self.confirm_rect = None
            self.begin_pos    = event.globalPosition().toPoint()
            self.end_pos      = self.begin_pos
            self.is_drawing   = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.is_drawing:
            self.end_pos = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            self.is_drawing = False
            self.end_pos    = event.globalPosition().toPoint()
            rect = QRect(self.begin_pos, self.end_pos).normalized()
            if rect.width() > 10 and rect.height() > 10:
                self.confirm_rect = rect
                self.show_toolbar(rect)
            else:
                self.confirm_rect = None
            self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if not self.has_interacted:
                return
            self._restore_initial_state()
        else:
            super().keyPressEvent(event)

    def show_toolbar(self, rect: QRect) -> None:
        if self.toolbar:
            self.toolbar.deleteLater()

        self.toolbar = QWidget(self)
        self.toolbar.setStyleSheet(
            "background-color: #2F3136; border-radius: 8px; border: 1px solid #1E1F22;"
        )
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        btn_settings = QPushButton("⚙️ 設定檔")
        btn_settings.setStyleSheet(
            "color: white; font-weight: bold; font-size: 14px; padding: 6px; border: none;"
        )
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.clicked.connect(self.open_settings)

        btn_confirm = QPushButton("✅ 確認並開始翻譯")
        btn_confirm.setStyleSheet(
            "background-color: #5865F2; color: white; padding: 8px 16px;"
            "font-weight: bold; font-size: 14px; border-radius: 6px; border: none;"
        )
        btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_confirm.clicked.connect(self.commit_roi)

        btn_quit = QPushButton("✕ 關閉")
        btn_quit.setStyleSheet(
            "color: #aaa; font-weight: bold; font-size: 14px; padding: 6px; border: none;"
        )
        btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quit.clicked.connect(QApplication.quit)

        layout.addWidget(btn_settings)
        layout.addWidget(btn_confirm)
        layout.addWidget(btn_quit)
        self.toolbar.setLayout(layout)

        tb_w, tb_h = 340, 55
        tb_x = rect.x() + rect.width() // 2 - tb_w // 2
        tb_y = rect.bottom() + 15
        if tb_y + tb_h > QApplication.screens()[0].geometry().height():
            tb_y = rect.y() - tb_h - 15
        self.toolbar.setGeometry(tb_x, tb_y, tb_w, tb_h)
        self.toolbar.show()

    def open_settings(self) -> None:
        self.toolbar.hide()
        dialog = SettingsDialog(self, glossary=self._glossary, pipeline=self._pipeline)
        dialog.exec()
        # Mutate the shared config dict in-place so OCRWorker sees the update
        self.config.update(load_config())
        self.toolbar.show()

    def commit_roi(self) -> None:
        if not self.confirm_rect:
            return
        roi = (self.confirm_rect.x(), self.confirm_rect.y(),
               self.confirm_rect.width(), self.confirm_rect.height())
        self.config["last_roi"] = list(roi)
        save_config(self.config)
        if self.toolbar:
            self.toolbar.hide()
        self.roi_selected.emit(roi)


# ---------------------------------------------------------------------------
# Step 2a — Inline edit popup
# ---------------------------------------------------------------------------

class EditPopup(QWidget):
    """Floats over the overlay when the user clicks a bbox in edit mode.
    Lets the user correct the translation and save it as a glossary entry.
    """
    saved = pyqtSignal(str, str)   # (source_term, target_term)

    _BG       = "rgba(14, 14, 20, 250)"
    _BORDER   = "rgba(255, 255, 255, 16)"
    _INPUT_BG = "rgba(255, 255, 255, 7)"
    _TEXT     = "#DDDDE8"
    _MUTED    = "#6B6C7B"
    _ACCENT   = "rgba(99, 102, 241, 210)"
    _ACCENT_H = "rgba(118, 121, 255, 255)"

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ep")
        self.setStyleSheet(f"""
            QWidget#ep {{
                background: {self._BG};
                border: 1px solid {self._BORDER};
                border-radius: 8px;
            }}
        """)
        _line_edit_style = f"""
            QLineEdit {{
                background: {self._INPUT_BG};
                color: {self._TEXT};
                border: 1px solid {self._BORDER};
                border-radius: 5px;
                padding: 0 8px;
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: rgba(99, 102, 241, 150); }}
        """

        self._src_edit = QLineEdit()
        self._src_edit.setFixedHeight(30)
        self._src_edit.setStyleSheet(_line_edit_style)
        self._src_edit.setPlaceholderText("原文")
        self._src_edit.returnPressed.connect(self._on_save)

        self._edit = QLineEdit()
        self._edit.setFixedHeight(30)
        self._edit.setStyleSheet(_line_edit_style)
        self._edit.returnPressed.connect(self._on_save)

        btn_save = QPushButton("儲存")
        btn_save.setFixedHeight(30)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {self._ACCENT};
                color: white;
                font-size: 13px;
                font-weight: bold;
                border-radius: 5px;
                border: none;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background: {self._ACCENT_H}; }}
        """)
        btn_save.clicked.connect(self._on_save)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 30)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {self._MUTED};
                font-size: 13px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{ color: #E06C75; }}
        """)
        btn_close.clicked.connect(self.hide)

        edit_row = QHBoxLayout()
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.setSpacing(6)
        edit_row.addWidget(self._edit)
        edit_row.addWidget(btn_save)
        edit_row.addWidget(btn_close)

        vlay = QVBoxLayout()
        vlay.setContentsMargins(10, 8, 10, 8)
        vlay.setSpacing(5)
        vlay.addWidget(self._src_edit)
        vlay.addLayout(edit_row)
        self.setLayout(vlay)

        self.setFixedWidth(300)
        self.hide()

    def show_for_item(self, item: dict, click_pos: QPoint) -> None:
        self._src_edit.setText(item.get("src", ""))
        self._edit.setText(item.get("trans", ""))
        self._edit.selectAll()
        self.adjustSize()

        parent = self.parent()
        pw = parent.width()  if parent else 9999
        ph = parent.height() if parent else 9999
        x = min(click_pos.x(), pw - self.width()  - 4)
        y = click_pos.y() - self.height() - 6
        if y < 0:
            y = click_pos.y() + 20
        y = min(y, ph - self.height() - 4)
        self.move(max(0, x), max(0, y))
        self.show()
        self._edit.setFocus()

    def _on_save(self) -> None:
        src = self._src_edit.text().strip()
        tgt = self._edit.text().strip()
        if src and tgt:
            self.saved.emit(src, tgt)
        self.hide()


# ---------------------------------------------------------------------------
# Step 2 — Translation overlay (QPainter)
# ---------------------------------------------------------------------------

def _sync_level_with_game(ns_window, game_win_id: int | None) -> None:
    """Set ns_window's level to match the game window's CGWindowLayer.
    This lets normal windows that cover the game also cover the overlay."""
    if game_win_id is None:
        return
    try:
        import Quartz
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
        )
        for w in wins:
            if w.get(Quartz.kCGWindowNumber) == game_win_id:
                game_level = w.get(Quartz.kCGWindowLayer, 0)
                ns_window.setLevel_(game_level + 1)
                break
    except Exception:
        pass


class TranslatorOverlay(QMainWindow):
    def __init__(self, roi: tuple, pipeline: TranslationPipeline):
        super().__init__()
        self.roi        = roi
        self.pipeline   = pipeline
        self.display_items: list[dict] = []
        self._merged_blocks: list[OCRBlock] = []
        self._edit_mode  = False
        self._edit_popup: EditPopup | None = None
        self._init_ui()

        config = load_config()
        self.ocr_worker = OCRWorker(roi=roi, config=config, pipeline=pipeline)
        self.ocr_worker.result_ready.connect(self.update_translation)
        self.ocr_worker.start()

    def _init_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(self.roi[0], self.roi[1], self.roi[2], self.roi[3])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            import objc
            from ctypes import c_void_p
            ns_view   = objc.objc_object(c_void_p=int(self.winId()))
            ns_window = ns_view.window()
            if ns_window:
                ns_window.setHasShadow_(False)
                self.ocr_worker.overlay_win_id = ns_window.windowNumber()
                from capture.window_finder import find_game_window_id
                game_win_id = find_game_window_id("MapleStory Worlds")
                self.ocr_worker.game_win_id = game_win_id
                _sync_level_with_game(ns_window, game_win_id)
        except Exception as e:
            print(f"[Overlay] 無法取得 NSWindow: {e}")

    def set_paused(self, paused: bool) -> None:
        self.ocr_worker.paused = paused
        if paused:
            self.display_items = []
            self.ocr_worker._prev_map = {}
            self.update()

    def update_translation(self, blocks: list[OCRBlock]) -> None:
        if self.ocr_worker.paused:
            return
        self._merged_blocks = blocks
        self.display_items = self._flatten(blocks)
        self.update()

    def _flatten(self, blocks: list[OCRBlock]) -> list[dict]:
        """Expand merged blocks into one display item per sub-bbox."""
        items = []
        for b in blocks:
            translated = b.translated
            if not b.is_merged:
                items.append({
                    "bbox": b.bbox, "trans": translated,
                    "text_color": b.text_color, "bg_color": b.bg_color,
                    "src": b.text,
                })
            else:
                orig_lens  = [len(t) for t in b.sub_texts]
                total_orig = max(sum(orig_lens), 1)
                trans_len  = len(translated)
                pos = 0
                for i, (sb, ol) in enumerate(zip(b.sub_bboxes, orig_lens)):
                    sc = b.sub_colors[i] if i < len(b.sub_colors) else (b.text_color, b.bg_color)
                    if i == len(b.sub_bboxes) - 1:
                        part = translated[pos:]
                    else:
                        n    = round(ol / total_orig * trans_len)
                        part = translated[pos:pos + n]
                        pos += n
                    if part:
                        items.append({
                            "bbox": sb, "trans": part,
                            "text_color": sc[0], "bg_color": sc[1],
                            "src": b.sub_texts[i],
                        })
        return items

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        for item in self.display_items:
            x, y, w, h = item["bbox"]
            text        = item["trans"]
            font_size   = max(10, int(h * 0.85))
            ix, iy      = max(0, int(x)), max(0, int(y))
            bg_w        = int(w)                         # fill only bbox width
            text_w      = max(int(w), self.roi[2] - ix)  # text may extend to ROI edge

            painter.fillRect(ix, iy, bg_w, int(h), QColor(item["bg_color"]))

            font = QFont("PingFang TC", font_size)
            font.setWeight(QFont.Weight.Black)
            painter.setFont(font)
            painter.setPen(QColor(item["text_color"]))
            painter.drawText(
                QRect(ix, iy, text_w, int(h)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextSingleLine,
                text,
            )

        if self._edit_mode:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for i, b in enumerate(self._merged_blocks):
                color = _BBOX_COLORS[i % len(_BBOX_COLORS)]
                x, y, w, h = (int(v) for v in b.bbox)
                fill = QColor(color)
                fill.setAlpha(40)
                painter.fillRect(x, y, w, h, fill)
                painter.setPen(QPen(color, 2))
                painter.drawRect(x, y, w, h)

        painter.end()

    def set_edit_mode(self, active: bool) -> None:
        self._edit_mode = active
        if not active and self._edit_popup:
            self._edit_popup.hide()
        flags = (Qt.WindowType.WindowStaysOnTopHint |
                 Qt.WindowType.FramelessWindowHint)
        if not active:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.show()
        self.update()

    def mousePressEvent(self, event) -> None:
        if not self._edit_mode:
            return
        pos = event.position().toPoint()
        for b in self._merged_blocks:
            x, y, w, h = (int(v) for v in b.bbox)
            if x <= pos.x() <= x + w and y <= pos.y() <= y + h:
                item = {
                    "bbox": b.bbox, "trans": b.translated,
                    "text_color": b.text_color, "bg_color": b.bg_color,
                    "src": b.text,
                }
                self._show_edit_popup(item, pos)
                return
        if self._edit_popup:
            self._edit_popup.hide()

    def _show_edit_popup(self, item: dict, pos: QPoint) -> None:
        if self._edit_popup is None:
            self._edit_popup = EditPopup(self)
            self._edit_popup.saved.connect(self._on_glossary_save)
        self._edit_popup.show_for_item(item, pos)

    def _on_glossary_save(self, src_text: str, tgt_text: str) -> None:
        cfg = self.pipeline.config
        entry = GlossaryEntry(
            terms={
                cfg.get("source_language", "Korean"): src_text,
                cfg.get("target_language", "Traditional Chinese"): tgt_text,
            }
        )
        if self.pipeline.glossary:
            self.pipeline.glossary.add_entry(entry)
        self.pipeline.clear_cache()

    def closeEvent(self, event) -> None:
        self.ocr_worker.stop()
        event.accept()


# ---------------------------------------------------------------------------
# Step 2b — BBox debug overlay
# ---------------------------------------------------------------------------

class BBoxOverlay(QMainWindow):
    def __init__(self, roi: tuple, config: dict):
        super().__init__()
        self.roi    = roi
        self.blocks: list[OCRBlock] = []

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(roi[0], roi[1], roi[2], roi[3])

        self.worker = RawOCRWorker(roi, config)
        self.worker.result_ready.connect(self._on_blocks)
        self.worker.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            import objc
            from ctypes import c_void_p
            ns_view   = objc.objc_object(c_void_p=int(self.winId()))
            ns_window = ns_view.window()
            if ns_window:
                ns_window.setHasShadow_(False)
                self.worker.overlay_win_id = ns_window.windowNumber()
                from capture.window_finder import find_game_window_id
                game_win_id = find_game_window_id("MapleStory Worlds")
                self.worker.game_win_id = game_win_id
                _sync_level_with_game(ns_window, game_win_id)
        except Exception:
            pass

    def _on_blocks(self, blocks: list[OCRBlock]) -> None:
        self.blocks = blocks
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Menlo", 11)
        font.setBold(True)
        painter.setFont(font)

        for i, b in enumerate(self.blocks):
            color = _BBOX_COLORS[i % len(_BBOX_COLORS)]
            x, y, w, h = (int(v) for v in b.bbox)

            fill = QColor(color)
            fill.setAlpha(40)
            painter.fillRect(x, y, w, h, fill)

            painter.setPen(QPen(color, 2))
            painter.drawRect(x, y, w, h)

            label = f"[{i}]{'⊕' if b.is_merged else ''} {b.text}"

            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                painter.drawText(x + 2 + dx, y + 14 + dy, label)

            painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
            painter.drawText(x + 2, y + 14, label)

    def closeEvent(self, event) -> None:
        self.worker.stop()
        event.accept()


# ---------------------------------------------------------------------------
# Step 3 — Control bar
# ---------------------------------------------------------------------------

class ControlWindow(QMainWindow):
    stop_requested = pyqtSignal()
    pause_toggled  = pyqtSignal(bool)
    mode_changed   = pyqtSignal(str)    # "translate" | "bbox"

    # Design tokens
    _BG       = "rgba(14, 14, 20, 242)"
    _BORDER   = "rgba(255, 255, 255, 16)"
    _INPUT_BG = "rgba(255, 255, 255, 7)"
    _ACCENT   = "rgba(99, 102, 241, 210)"
    _ACCENT_H = "rgba(118, 121, 255, 255)"
    _TEXT     = "#DDDDE8"
    _MUTED    = "#6B6C7B"

    # Heights used by _reposition()
    _H_BAR    = 50   # main bar (margins 8+8 + button 34)
    _H_RESULT = 38   # result row when visible (spacing 6 + pills 28 + bottom 4)
    _H_BANNER = 36   # update banner when visible (spacing 6 + content 26 + top 4)

    def __init__(self, x: int, y: int, glossary=None, config=None, pipeline=None):
        super().__init__()
        self._glossary = glossary
        self._config   = config
        self._pipeline = pipeline
        self._paused   = False
        self._mode     = "translate"
        self._roi_x    = x
        self._roi_y    = y

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── Pause ──────────────────────────────────────────────────────────
        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setFixedSize(34, 34)
        self.btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause.setToolTip("暫停 / 繼續")
        self.btn_pause.setStyleSheet(self._pause_style(False))
        self.btn_pause.clicked.connect(self._toggle_pause)

        # ── Input ──────────────────────────────────────────────────────────
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("查詢詞彙 或 輸入翻譯…")
        self.line_edit.setFixedHeight(34)
        self.line_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {self._INPUT_BG};
                color: {self._TEXT};
                border: 1px solid {self._BORDER};
                border-radius: 7px;
                padding: 0 10px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 1px solid rgba(99, 102, 241, 150);
            }}
        """)
        self.line_edit.textChanged.connect(self._update_suggestions)
        self.line_edit.returnPressed.connect(self._on_submit)

        # ── Translate ──────────────────────────────────────────────────────
        btn_send = QPushButton("↵")
        btn_send.setFixedSize(34, 34)
        btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_send.setToolTip("翻譯 (Enter)")
        btn_send.setStyleSheet(f"""
            QPushButton {{
                background: {self._ACCENT};
                color: white;
                font-size: 17px;
                font-weight: bold;
                border-radius: 7px;
                border: none;
            }}
            QPushButton:hover {{ background: {self._ACCENT_H}; }}
        """)
        btn_send.clicked.connect(self._on_submit)

        # ── BBox toggle ────────────────────────────────────────────────────
        self._btn_bbox = QPushButton("⊕")
        self._btn_bbox.setFixedSize(34, 34)
        self._btn_bbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_bbox.setToolTip("切換編輯模式")
        self._btn_bbox.setStyleSheet(self._bbox_style(False))
        self._btn_bbox.clicked.connect(self._toggle_edit)

        # ── Stop ───────────────────────────────────────────────────────────
        self.btn_stop = QPushButton("✕")
        self.btn_stop.setFixedSize(34, 34)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setToolTip("退出並重新截圖")
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 7);
                color: #E06C75;
                font-size: 14px;
                font-weight: bold;
                border-radius: 7px;
                border: 1px solid {self._BORDER};
            }}
            QPushButton:hover {{
                background: rgba(224, 108, 117, 30);
                border-color: rgba(224, 108, 117, 100);
            }}
        """)
        self.btn_stop.clicked.connect(self.stop_requested.emit)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        bar.addWidget(self.btn_pause)
        bar.addWidget(self.line_edit)
        bar.addWidget(btn_send)
        bar.addWidget(self._btn_bbox)
        bar.addWidget(self.btn_stop)

        # ── Result pills ───────────────────────────────────────────────────
        _pill = f"""
            QPushButton {{
                background: rgba(255, 255, 255, 7);
                color: {self._TEXT};
                font-size: 13px;
                border: 1px solid {self._BORDER};
                border-radius: 5px;
                padding: 3px 10px;
                max-width: 160px;
            }}
            QPushButton:hover {{
                background: rgba(99, 102, 241, 110);
                border-color: rgba(99, 102, 241, 200);
            }}
        """
        self._btn_tgt = QPushButton()
        self._btn_tgt.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_tgt.setStyleSheet(_pill)
        self._btn_tgt.clicked.connect(
            lambda: self._copy(self._btn_tgt, self._btn_tgt.text())
        )

        self._btn_src = QPushButton()
        self._btn_src.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_src.setStyleSheet(_pill)
        self._btn_src.clicked.connect(
            lambda: self._copy(self._btn_src, self._btn_src.text())
        )

        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: {self._MUTED}; font-size: 12px;")

        copy_hint = QLabel("點擊複製")
        copy_hint.setStyleSheet(f"color: {self._MUTED}; font-size: 11px;")

        result_lay = QHBoxLayout()
        result_lay.setContentsMargins(0, 0, 0, 0)
        result_lay.setSpacing(8)
        result_lay.addWidget(self._btn_tgt)
        result_lay.addWidget(arrow)
        result_lay.addWidget(self._btn_src)
        result_lay.addSpacing(4)
        result_lay.addWidget(copy_hint)
        result_lay.addStretch()

        self._result_row = QWidget()
        self._result_row.setLayout(result_lay)
        self._result_row.hide()

        # ── Update banner (hidden until an update is detected) ─────────────
        self._banner_lbl = QLabel("")
        self._banner_lbl.setStyleSheet(f"color: #EAB308; font-size: 12px;")
        self._banner_action = QPushButton("")
        self._banner_action.setFixedHeight(22)
        self._banner_action.setStyleSheet(f"""
            QPushButton {{
                background: rgba(234,179,8,60);
                color: #EAB308;
                border: 1px solid rgba(234,179,8,120);
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: rgba(234,179,8,100); }}
        """)
        banner_dismiss = QPushButton("✕")
        banner_dismiss.setFixedSize(22, 22)
        banner_dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {self._MUTED};
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {self._TEXT}; }}
        """)
        banner_dismiss.clicked.connect(self._dismiss_banner)

        banner_lay = QHBoxLayout()
        banner_lay.setContentsMargins(4, 2, 4, 2)
        banner_lay.setSpacing(6)
        banner_lay.addWidget(self._banner_lbl)
        banner_lay.addStretch()
        banner_lay.addWidget(self._banner_action)
        banner_lay.addWidget(banner_dismiss)

        self._update_banner = QWidget()
        self._update_banner.setStyleSheet(
            "QWidget { background: rgba(234,179,8,18); border-radius: 6px; }"
        )
        self._update_banner.setLayout(banner_lay)
        self._update_banner.hide()

        # ── Container card ─────────────────────────────────────────────────
        vlay = QVBoxLayout()
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(6)
        vlay.addWidget(self._update_banner)
        vlay.addLayout(bar)
        vlay.addWidget(self._result_row)

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        central.setObjectName("card")
        central.setStyleSheet(f"""
            QWidget#card {{
                background: {self._BG};
                border: 1px solid {self._BORDER};
                border-radius: 10px;
            }}
        """)
        central.setLayout(vlay)
        self.setCentralWidget(central)

        self.setFixedWidth(440)
        self._reposition()

        # ── Autocomplete popup ─────────────────────────────────────────────
        self._popup = QListWidget()
        self._popup.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setStyleSheet(f"""
            QListWidget {{
                background: {self._BG};
                color: {self._TEXT};
                border: 1px solid {self._BORDER};
                border-radius: 8px;
                font-size: 13px;
                padding: 3px;
                outline: 0;
            }}
            QListWidget::item {{
                padding: 6px 12px;
                border-radius: 5px;
            }}
            QListWidget::item:hover, QListWidget::item:selected {{
                background: rgba(99, 102, 241, 160);
            }}
        """)
        self._popup.itemClicked.connect(self._on_suggestion_clicked)

    # ------------------------------------------------------------------
    # Pause / stop
    # ------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.btn_pause.setText("▶" if self._paused else "⏸")
        self.btn_pause.setStyleSheet(self._pause_style(self._paused))
        self.pause_toggled.emit(self._paused)

    @staticmethod
    def _pause_style(paused: bool) -> str:
        if paused:
            return """
                QPushButton {
                    background: rgba(72, 187, 120, 200);
                    color: white;
                    font-size: 16px;
                    border-radius: 7px;
                    border: none;
                }
                QPushButton:hover { background: rgba(72, 187, 120, 255); }
            """
        return """
            QPushButton {
                background: rgba(255, 255, 255, 7);
                color: #6B6C7B;
                font-size: 16px;
                border-radius: 7px;
                border: 1px solid rgba(255, 255, 255, 16);
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 14);
                color: #DDDDE8;
            }
        """

    @staticmethod
    def _bbox_style(active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: rgba(245, 158, 11, 210);
                    color: white;
                    font-size: 16px;
                    border-radius: 7px;
                    border: none;
                }
                QPushButton:hover { background: rgba(245, 158, 11, 255); }
            """
        return """
            QPushButton {
                background: rgba(255, 255, 255, 7);
                color: #6B6C7B;
                font-size: 16px;
                border-radius: 7px;
                border: 1px solid rgba(255, 255, 255, 16);
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 14);
                color: #DDDDE8;
            }
        """

    def _toggle_edit(self) -> None:
        self._mode = "edit" if self._mode == "translate" else "translate"
        self._btn_bbox.setStyleSheet(self._bbox_style(self._mode == "edit"))
        self.mode_changed.emit(self._mode)

    def reset_pause(self) -> None:
        """Reset pause state when the overlay is recreated."""
        if self._paused:
            self._paused = False
            self.btn_pause.setText("⏸")
            self.btn_pause.setStyleSheet(self._pause_style(False))

    # ------------------------------------------------------------------
    # Window positioning
    # ------------------------------------------------------------------

    def _reposition(self) -> None:
        h = self._H_BAR
        if not self._result_row.isHidden():
            h += self._H_RESULT
        if not self._update_banner.isHidden():
            h += self._H_BANNER
        self.setGeometry(self._roi_x, max(0, self._roi_y - h - 8), 440, h)

    def show_glossary_update(self, remote_version: int) -> None:
        self._banner_lbl.setText("✨ 社群詞彙表有更新")
        self._banner_action.setText("立即更新")
        try:
            self._banner_action.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._banner_action.clicked.connect(
            lambda: self._on_glossary_update_clicked(remote_version)
        )
        self._update_banner.show()
        self._reposition()

    def show_app_update(self, latest_version: str) -> None:
        self._banner_lbl.setText(f"🚀 新版本 v{latest_version} 可下載")
        self._banner_action.setText("前往下載")
        try:
            self._banner_action.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._banner_action.clicked.connect(self._on_app_update_clicked)
        self._update_banner.show()
        self._reposition()

    def _on_glossary_update_clicked(self, remote_version: int) -> None:
        from settings_ui import CommunityGlossaryDialog
        dlg = CommunityGlossaryDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.selected_entries:
            if self._glossary:
                existing = self._glossary.get_all_entries()
                self._glossary.set_all_entries(list(existing) + dlg.selected_entries)
            if self._pipeline:
                self._pipeline.clear_cache()
        if self._config:
            self._config["community_glossary_seen_version"] = remote_version
            from config_manager import save_config
            save_config(self._config)
        self._dismiss_banner()

    def _on_app_update_clicked(self) -> None:
        import webbrowser
        webbrowser.open(f"https://github.com/dodooodo/msw-translation/releases/latest")

    def _dismiss_banner(self) -> None:
        self._update_banner.hide()
        self._reposition()

    # ------------------------------------------------------------------
    # Manual translation submit
    # ------------------------------------------------------------------

    def _on_submit(self) -> None:
        self._popup.hide()
        text = self.line_edit.text().strip()
        if not text or not self._pipeline or not self._config:
            return

        self.line_edit.clear()

        cfg = self._config
        src = cfg.get("source_language", "Korean")
        tgt = cfg.get("target_language", "Traditional Chinese")

        # Protect known target terms with placeholders before reverse translation
        protected = text
        pmap: dict[str, str] = {}
        if self._glossary:
            for i, entry in enumerate(self._glossary.get_entries(src, tgt)):
                t = entry.terms.get(tgt, "")
                s = entry.terms.get(src, "")
                if t and t in protected:
                    ph = f"__T{i}__"
                    protected = protected.replace(t, ph)
                    pmap[ph] = s

        rev_config = dict(cfg)
        rev_config["source_language"] = tgt
        rev_config["target_language"] = src
        result = engine_translate([protected], rev_config)[0]

        for ph, source_term in pmap.items():
            result = result.replace(ph, source_term)

        self._btn_tgt.setText(text)
        self._btn_src.setText(result)
        was_hidden = self._result_row.isHidden()
        self._result_row.show()
        if was_hidden:
            self._reposition()

    # ------------------------------------------------------------------
    # Glossary autocomplete
    # ------------------------------------------------------------------

    def _update_suggestions(self, text: str) -> None:
        if not text or not self._glossary or not self._config:
            self._popup.hide()
            return

        src = self._config.get("source_language", "Korean")
        tgt = self._config.get("target_language", "Traditional Chinese")
        matches = [
            e for e in self._glossary.get_entries(src, tgt)
            if (e.terms.get(tgt) or "").startswith(text)
        ]

        if not matches:
            self._popup.hide()
            return

        self._popup.clear()
        for entry in matches:
            item = QListWidgetItem(f"{entry.terms.get(tgt, '')}   →   {entry.terms.get(src, '')}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._popup.addItem(item)

        pos = self.line_edit.mapToGlobal(QPoint(0, self.line_edit.height() + 4))
        self._popup.move(pos)
        self._popup.resize(self.line_edit.width(), min(len(matches) * 36 + 8, 200))
        self._popup.show()
        self.line_edit.setFocus()

    def _on_suggestion_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        src = self._config.get("source_language", "Korean")
        tgt = self._config.get("target_language", "Traditional Chinese")
        self._popup.hide()
        self.line_edit.clear()
        self._btn_tgt.setText(entry.terms.get(tgt, ""))
        self._btn_src.setText(entry.terms.get(src, ""))
        was_hidden = self._result_row.isHidden()
        self._result_row.show()
        if was_hidden:
            self._reposition()

    def _copy(self, btn: QPushButton, text: str) -> None:
        QApplication.clipboard().setText(text)
        original = btn.text()
        btn.setText("✓ 已複製")
        QTimer.singleShot(800, lambda: btn.setText(original))


# ---------------------------------------------------------------------------
# Step 3b — BBox control bar (restart / quit)
# ---------------------------------------------------------------------------

class VisControl(QMainWindow):
    stop_requested = pyqtSignal()

    _BG       = "rgba(14, 14, 20, 242)"
    _BORDER   = "rgba(255, 255, 255, 16)"
    _MUTED    = "#6B6C7B"
    _ACCENT   = "rgba(99, 102, 241, 210)"
    _ACCENT_H = "rgba(118, 121, 255, 255)"

    def __init__(self, x: int, y: int):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        title = QLabel("BBox 可視化")
        title.setStyleSheet(
            f"color: {self._MUTED}; font-size: 13px; font-weight: bold;"
        )

        btn_restart = QPushButton("↩ 重新截圖")
        btn_restart.setFixedHeight(34)
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.setToolTip("重新選擇截圖區域")
        btn_restart.setStyleSheet(f"""
            QPushButton {{
                background: {self._ACCENT};
                color: white;
                font-size: 13px;
                font-weight: bold;
                border-radius: 7px;
                border: none;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {self._ACCENT_H}; }}
        """)
        btn_restart.clicked.connect(self.stop_requested.emit)

        btn_quit = QPushButton("✕")
        btn_quit.setFixedSize(34, 34)
        btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quit.setToolTip("關閉")
        btn_quit.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 7);
                color: #E06C75;
                font-size: 14px;
                font-weight: bold;
                border-radius: 7px;
                border: 1px solid {self._BORDER};
            }}
            QPushButton:hover {{
                background: rgba(224, 108, 117, 30);
                border-color: rgba(224, 108, 117, 100);
            }}
        """)
        btn_quit.clicked.connect(QApplication.quit)

        row = QHBoxLayout()
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(btn_restart)
        row.addWidget(btn_quit)

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        central.setObjectName("card")
        central.setStyleSheet(f"""
            QWidget#card {{
                background: {self._BG};
                border: 1px solid {self._BORDER};
                border-radius: 10px;
            }}
        """)
        central.setLayout(row)
        self.setCentralWidget(central)

        self.setFixedSize(300, 50)
        self.move(x, max(0, y - 58))


# ---------------------------------------------------------------------------
# Application orchestrator
# ---------------------------------------------------------------------------

class AppController:
    def __init__(self):
        self.overlay  = None
        self.control  = None
        self.selector = None
        self._roi: tuple | None = None
        # Pipeline and glossary are created once and reused across ROI changes
        self._config   = load_config()
        self._glossary = GlossaryService()
        self._pipeline = TranslationPipeline(self._config, self._glossary)

        # Pending update notifications (may arrive before ControlWindow exists)
        self._pending_app_update: str | None = None
        self._pending_glossary_version: int | None = None

        # Global pause hotkey — lets users pause OCR from inside a fullscreen
        # game without alt-tabbing. No-op when the ROI selector is showing.
        self._hotkey = HotkeyListener(
            self._config.get("hotkey_pause", "<ctrl>+<alt>+p")
        )
        self._hotkey.triggered.connect(self._on_pause_hotkey)
        self._hotkey.start()

        self._start_update_check()
        self.show_selector()

    def _on_pause_hotkey(self) -> None:
        # Only meaningful when the overlay is live; otherwise ignored.
        if self.control is not None:
            self.control._toggle_pause()

    def _start_update_check(self) -> None:
        from update_checker import UpdateCheckerThread
        seen = self._config.get("community_glossary_seen_version", 0)
        self._update_thread = UpdateCheckerThread(seen)
        self._update_thread.app_update_available.connect(self._on_app_update)
        self._update_thread.glossary_update_available.connect(self._on_glossary_update)
        self._update_thread.start()

    def _on_app_update(self, latest: str) -> None:
        if self.control:
            self.control.show_app_update(latest)
        else:
            self._pending_app_update = latest

    def _on_glossary_update(self, remote_version: int) -> None:
        if self.control:
            self.control.show_glossary_update(remote_version)
        else:
            self._pending_glossary_version = remote_version

    def show_selector(self) -> None:
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        if self.control:
            self.control.close()
            self.control = None

        from capture.window_finder import find_window_client_rect
        rect = find_window_client_rect("MapleStory Worlds")
        if rect is not None:
            print(f"[AutoDetect] MapleStory Worlds: {rect}")
            self._config["last_roi"] = list(rect)
            save_config(self._config)
            self.launch_overlay(rect)
            return

        self.selector = SnippingToolWindow(
            self._config, glossary=self._glossary, pipeline=self._pipeline
        )
        self.selector.roi_selected.connect(self.launch_overlay)
        self.selector.show()

    def launch_overlay(self, roi: tuple) -> None:
        if self.selector:
            self.selector.close()

        self._roi = roi
        self.overlay = TranslatorOverlay(roi, self._pipeline)
        self.overlay.show()

        self.control = ControlWindow(roi[0], roi[1], glossary=self._glossary,
                                     config=self._config, pipeline=self._pipeline)
        self.control.stop_requested.connect(self.show_selector)
        self.control.pause_toggled.connect(self.overlay.set_paused)
        self.control.mode_changed.connect(self._on_mode_changed)
        self.control.show()

        # Deliver any update notifications that arrived before ControlWindow existed
        if self._pending_app_update:
            self.control.show_app_update(self._pending_app_update)
            self._pending_app_update = None
        if self._pending_glossary_version is not None:
            self.control.show_glossary_update(self._pending_glossary_version)
            self._pending_glossary_version = None

    def _on_mode_changed(self, mode: str) -> None:
        self.overlay.set_edit_mode(mode == "edit")
        if mode == "translate":
            self.control.reset_pause()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    controller = AppController()
    sys.exit(app.exec())
