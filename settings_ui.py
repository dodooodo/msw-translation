from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QDoubleSpinBox, QPushButton, QColorDialog, QFormLayout, QTabWidget,
    QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QInputDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
            "Dummy (測試用不翻譯)", "Apple 翻譯 (macOS 內建)", "Windows 翻譯 (系統內建)", "Google Translate"
        ])
        engine_map = {"dummy": 0, "apple": 1, "windows": 2, "google": 3}
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

        # Community / import / export toolbar
        comm_btn   = QPushButton("☁ Community")
        url_btn    = QPushButton("🔗 URL 匯入")
        export_btn = QPushButton("↓ 匯出")
        for btn in (comm_btn, url_btn, export_btn):
            btn.setStyleSheet("padding: 4px 10px;")
        comm_btn.clicked.connect(self._open_community_dialog)
        url_btn.clicked.connect(self._import_from_url)
        export_btn.clicked.connect(self._export_glossary)
        share_row = QHBoxLayout()
        share_row.addWidget(comm_btn)
        share_row.addWidget(url_btn)
        share_row.addWidget(export_btn)
        share_row.addStretch()
        vlay.addLayout(share_row)

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
    # Community / import / export
    # ------------------------------------------------------------------

    def _open_community_dialog(self) -> None:
        dlg = CommunityGlossaryDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_entries:
            self._merge_or_replace_entries(dlg.selected_entries)

    def _import_from_url(self) -> None:
        url, ok = QInputDialog.getText(
            self, "🔗 URL 匯入", "貼上詞彙表 JSON 的原始網址 (raw URL)："
        )
        if not ok or not url.strip():
            return
        from community_glossary import fetch_glossary_from_url
        try:
            entries = fetch_glossary_from_url(url.strip())
        except Exception as e:
            QMessageBox.warning(self, "匯入失敗", str(e))
            return
        if not entries:
            QMessageBox.information(self, "匯入完成", "未找到任何詞彙條目。")
            return
        self._merge_or_replace_entries(entries)

    def _export_glossary(self) -> None:
        import json
        from glossary_service import GlossaryEntry
        from dataclasses import asdict

        # Collect current table entries
        entries = []
        for row in range(self._gloss_table.rowCount()):
            def _cell(col: int) -> str:
                item = self._gloss_table.item(row, col)
                return item.text().strip() if item else ""
            terms = {lang: _cell(i) for i, lang in enumerate(self._glossary_langs) if _cell(i)}
            notes = _cell(len(self._glossary_langs))
            if terms:
                entries.append(GlossaryEntry(terms=terms, notes=notes))

        path, _ = QFileDialog.getSaveFileName(
            self, "匯出詞彙表", "glossary.json", "JSON (*.json)"
        )
        if not path:
            return
        data = {"version": 1, "entries": [asdict(e) for e in entries]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "匯出完成", f"已儲存 {len(entries)} 條詞彙至\n{path}")

    def _merge_or_replace_entries(self, new_entries: list) -> None:
        reply = QMessageBox.question(
            self, "匯入詞彙",
            f"匯入了 {len(new_entries)} 條詞彙。\n\n"
            "「取代」— 清除目前所有詞彙後匯入\n"
            "「合併」— 追加到現有詞彙後方",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        if reply == QMessageBox.StandardButton.Yes:  # Replace
            while self._gloss_table.rowCount():
                self._gloss_table.removeRow(0)
        for entry in new_entries:
            self._append_table_row(entry)
        self._glossary_modified = True

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_and_close(self) -> None:
        engine_rev_map = {0: "dummy", 1: "apple", 2: "windows", 3: "google"}
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


# ---------------------------------------------------------------------------
# Community glossary browser
# ---------------------------------------------------------------------------

class _FetchIndexWorker(QThread):
    finished = pyqtSignal(list)   # list[GlossaryMeta]
    error    = pyqtSignal(str)

    def run(self):
        try:
            from community_glossary import fetch_index
            self.finished.emit(fetch_index())
        except Exception as e:
            self.error.emit(str(e))


class _FetchGlossaryWorker(QThread):
    finished = pyqtSignal(list)   # list[GlossaryEntry]
    error    = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        try:
            from community_glossary import fetch_glossary
            self.finished.emit(fetch_glossary(self._url))
        except Exception as e:
            self.error.emit(str(e))


class CommunityGlossaryDialog(QDialog):
    """Browse and import community-shared glossaries from the msw-glossary repo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_entries: list = []
        self._meta: list = []

        self.setWindowTitle("☁ Community Glossaries")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(480, 360)

        self._status_lbl = QLabel("正在載入清單…")
        self._status_lbl.setStyleSheet("color: #888; font-size: 11px;")

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self._import_btn = QPushButton("↓ 匯入選取")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)

        cancel_btn = QPushButton("關閉")
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._import_btn)
        btn_row.addWidget(cancel_btn)

        vlay = QVBoxLayout()
        vlay.addWidget(self._status_lbl)
        vlay.addWidget(self._list)
        vlay.addLayout(btn_row)
        self.setLayout(vlay)

        self._fetch_worker = _FetchIndexWorker()
        self._fetch_worker.finished.connect(self._on_index_loaded)
        self._fetch_worker.error.connect(self._on_index_error)
        self._fetch_worker.start()

    def _on_index_loaded(self, metas: list) -> None:
        self._meta = metas
        self._list.clear()
        if not metas:
            self._status_lbl.setText("目前沒有社群詞彙表。")
            return
        self._status_lbl.setText(f"找到 {len(metas)} 個詞彙表，點選後按匯入。")
        for m in metas:
            label = f"{m.name}  ({m.entry_count} 條)"
            item = QListWidgetItem(label)
            self._list.addItem(item)
        self._import_btn.setEnabled(True)

    def _on_index_error(self, msg: str) -> None:
        self._status_lbl.setText(f"載入失敗：{msg}")
        self._status_lbl.setStyleSheet("color: #e55; font-size: 11px;")

    def _on_import(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._meta):
            return
        meta = self._meta[row]
        self._import_btn.setEnabled(False)
        self._status_lbl.setText(f"正在下載「{meta.name}」…")

        self._gloss_worker = _FetchGlossaryWorker(meta.raw_url)
        self._gloss_worker.finished.connect(self._on_glossary_loaded)
        self._gloss_worker.error.connect(self._on_glossary_error)
        self._gloss_worker.start()

    def _on_glossary_loaded(self, entries: list) -> None:
        self.selected_entries = entries
        self._status_lbl.setText(f"下載完成，共 {len(entries)} 條。")
        self.accept()

    def _on_glossary_error(self, msg: str) -> None:
        self._status_lbl.setText(f"下載失敗：{msg}")
        self._status_lbl.setStyleSheet("color: #e55; font-size: 11px;")
        self._import_btn.setEnabled(True)
