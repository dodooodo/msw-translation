from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QDoubleSpinBox, QPushButton, QColorDialog, QFormLayout, QTabWidget,
    QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from config_manager import load_config, save_config


class GlossaryTableWidget(QTableWidget):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if not text:
                super().keyPressEvent(event)
                return

            rows = text.split('\n')
            # Remove trailing newline empty splitting result
            if rows and not rows[-1]:
                rows.pop()

            current_row = self.currentRow()
            if current_row < 0:
                current_row = self.rowCount()

            for row_idx, row_text in enumerate(rows):
                cols = row_text.split('\t')

                target_row = current_row + row_idx
                if target_row >= self.rowCount():
                    self.insertRow(target_row)

                for col_idx, col_text in enumerate(cols):
                    if col_idx < self.columnCount():
                        self.setItem(target_row, col_idx, QTableWidgetItem(col_text.strip()))
            return
        super().keyPressEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, glossary=None, pipeline=None):
        super().__init__(parent)
        self._glossary = glossary
        self._pipeline = pipeline
        self._glossary_modified = False

        self.setWindowTitle("⚙️ 翻譯器設定")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(500, 420)

        self.config = load_config()

        src = self.config.get("source_language", "Korean")
        tgt = self.config.get("target_language", "Traditional Chinese")
        self._active_src = src
        self._active_tgt = tgt
        self._orig_entries = (
            list(self._glossary.get_all_entries()) if self._glossary else []
        )

        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "⚙️ 一般")
        tabs.addTab(self._build_glossary_tab(), "📖 詞彙表")

        save_btn = QPushButton("💾 儲存並關閉")
        save_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;"
        )
        save_btn.clicked.connect(self._save_and_close)

        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setStyleSheet("padding: 8px;")
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)

        main = QVBoxLayout()
        main.addWidget(tabs)
        main.addLayout(btn_row)
        self.setLayout(main)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout()

        # Source language
        self.source_combo = QComboBox()
        self.source_langs = [
            "Korean", "Japanese", "English", "Traditional Chinese", "Simplified Chinese"
        ]
        self.source_combo.addItems(["韓文", "日文", "英文", "繁體中文", "簡體中文"])
        try:
            src_idx = self.source_langs.index(
                self.config.get("source_language", "Korean")
            )
        except ValueError:
            src_idx = 0
        self.source_combo.setCurrentIndex(src_idx)
        form.addRow("🔍 遊戲畫面語言 (來源):", self.source_combo)

        # Target language
        self.target_combo = QComboBox()
        self.target_langs = ["Traditional Chinese", "Simplified Chinese", "English"]
        self.target_combo.addItems(["繁體中文", "簡體中文", "英文"])
        try:
            tgt_idx = self.target_langs.index(
                self.config.get("target_language", "Traditional Chinese")
            )
        except ValueError:
            tgt_idx = 0
        self.target_combo.setCurrentIndex(tgt_idx)
        form.addRow("🗣️ 想要翻譯成 (目標):", self.target_combo)

        # Engine
        self.engine_combo = QComboBox()
        self.engine_combo.addItems([
            "Dummy (測試用不翻譯)", "Apple 翻譯 (系統內建)", "Google Translate"
        ])
        engine_map = {"dummy": 0, "apple": 1, "google": 2}
        self.engine_combo.setCurrentIndex(
            engine_map.get(self.config.get("translator_engine", "dummy"), 0)
        )
        form.addRow("🔄 翻譯引擎:", self.engine_combo)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 72)
        self.font_spin.setValue(self.config.get("font_size", 26))
        form.addRow("🔠 翻譯字體大小:", self.font_spin)

        # Text color
        self.color_btn = QPushButton("選擇顏色")
        self.current_color = self.config.get("text_color", "#FFE600")
        self._update_color_btn()
        self.color_btn.clicked.connect(self._choose_color)
        form.addRow("🎨 翻譯文字顏色:", self.color_btn)

        # OCR interval
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(float(self.config.get("ocr_interval", 1.0)))
        form.addRow("⏱ OCR 辨識頻率 (秒):", self.interval_spin)

        tab.setLayout(form)
        return tab

    def _build_glossary_tab(self) -> QWidget:
        tab = QWidget()
        vlay = QVBoxLayout()

        # Language pair label
        _display = {
            "Korean": "韓文", "Japanese": "日文", "English": "英文",
            "Traditional Chinese": "繁體中文", "Simplified Chinese": "簡體中文",
        }
        src_d = _display.get(self._active_src, self._active_src)
        tgt_d = _display.get(self._active_tgt, self._active_tgt)
        pair_lbl = QLabel(f"目前活躍語言對：{src_d} → {tgt_d}（此表格為全語系通用，可直接貼上包含所有語系的 Excel 表格）")
        pair_lbl.setStyleSheet("color: #888; font-size: 11px;")
        pair_lbl.setWordWrap(True)
        vlay.addWidget(pair_lbl)

        # Table
        self._gloss_table = GlossaryTableWidget()
        
        self._glossary_langs = [
            "Traditional Chinese", "Korean", "English"
        ]
        self._glossary_headers = ["繁體中文", "韓文", "英文", "備註"]
        
        self._gloss_table.setColumnCount(len(self._glossary_headers))
        self._gloss_table.setHorizontalHeaderLabels(self._glossary_headers)
        
        hdr = self._gloss_table.horizontalHeader()
        for i in range(len(self._glossary_headers)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            
        self._gloss_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._gloss_table.verticalHeader().setVisible(False)

        for entry in self._orig_entries:
            self._append_table_row(entry)

        vlay.addWidget(self._gloss_table)

        # Add / Remove buttons
        btn_add = QPushButton("➕ 新增詞彙")
        btn_add.clicked.connect(self._add_glossary_row)
        btn_remove = QPushButton("🗑️ 刪除選取")
        btn_remove.clicked.connect(self._remove_glossary_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        vlay.addLayout(btn_row)

        if not self._glossary:
            pair_lbl.setText("（未提供詞彙表服務）")
            self._gloss_table.setEnabled(False)
            btn_add.setEnabled(False)
            btn_remove.setEnabled(False)

        tab.setLayout(vlay)
        return tab

    # ------------------------------------------------------------------
    # Glossary table helpers
    # ------------------------------------------------------------------

    def _append_table_row(self, entry=None) -> None:
        row = self._gloss_table.rowCount()
        self._gloss_table.insertRow(row)
        
        if entry:
            for i, lang in enumerate(self._glossary_langs):
                val = entry.terms.get(lang, "")
                self._gloss_table.setItem(row, i, QTableWidgetItem(val))
            self._gloss_table.setItem(row, len(self._glossary_langs), QTableWidgetItem(entry.notes))
        else:
            for i in range(len(self._glossary_headers)):
                self._gloss_table.setItem(row, i, QTableWidgetItem(""))

    def _add_glossary_row(self) -> None:
        self._append_table_row()
        row = self._gloss_table.rowCount() - 1
        self._gloss_table.scrollToBottom()
        self._gloss_table.setCurrentCell(row, 0)
        self._gloss_table.editItem(self._gloss_table.item(row, 0))

    def _remove_glossary_row(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._gloss_table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._gloss_table.removeRow(row)

    # ------------------------------------------------------------------
    # Color picker helpers
    # ------------------------------------------------------------------

    def _update_color_btn(self) -> None:
        self.color_btn.setStyleSheet(
            f"background-color: {self.current_color}; "
            "color: black; font-weight: bold; padding: 5px;"
        )

    def _choose_color(self) -> None:
        from PyQt6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.current_color), self, "選擇文字顏色")
        if color.isValid():
            self.current_color = color.name()
            self._update_color_btn()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_and_close(self) -> None:
        engine_rev_map = {0: "dummy", 1: "apple", 2: "google"}
        new_config = {
            "source_language": self.source_langs[self.source_combo.currentIndex()],
            "target_language": self.target_langs[self.target_combo.currentIndex()],
            "translator_engine": engine_rev_map.get(
                self.engine_combo.currentIndex(), "dummy"
            ),
            "font_size": self.font_spin.value(),
            "text_color": self.current_color,
            "ocr_interval": self.interval_spin.value(),
        }
        save_config(new_config)

        # Sync glossary entries for the active language pair
        if self._glossary:
            from glossary_service import GlossaryEntry
            
            new_entries = []
            for row in range(self._gloss_table.rowCount()):
                def _cell(col: int) -> str:
                    item = self._gloss_table.item(row, col)
                    return item.text().strip() if item else ""
                
                terms = {}
                for i, lang in enumerate(self._glossary_langs):
                    val = _cell(i)
                    if val:
                        terms[lang] = val
                
                notes = _cell(len(self._glossary_langs))
                
                # Only add if it has at least one term
                if terms:
                    new_entries.append(GlossaryEntry(terms=terms, notes=notes))

            # Simplistic check if anything changed (length or values differs)
            # In i18n bulk mode, we just overwrite all entries if we opened settings
            self._glossary.set_all_entries(new_entries)
            self._glossary_modified = True

        if self._glossary_modified and self._pipeline:
            self._pipeline.clear_cache()

        self.accept()
