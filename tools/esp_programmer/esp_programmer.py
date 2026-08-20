#!/usr/bin/env python3

import math
import shlex
import subprocess
import struct
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QInputDialog,
    QPushButton, QPlainTextEdit, QProgressBar, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from serial.tools import list_ports

BYTES_PER_ROW = 16
ROWS_PER_PAGE = 256
PAGE_SIZE = BYTES_PER_ROW * ROWS_PER_PAGE


class CommandWorker(QThread):
    output = Signal(str)
    finished_ok = Signal(bool)

    def __init__(self, command: list[str]):
        super().__init__()
        self.command = command

    def run(self):
        try:
            self.output.emit("$ " + shlex.join(self.command) + "\n\n")
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if process.stdout:
                for line in process.stdout:
                    self.output.emit(line)
            self.finished_ok.emit(process.wait() == 0)
        except Exception as exc:
            self.output.emit(f"\nОшибка запуска: {exc}\n")
            self.finished_ok.emit(False)


class HexViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.data = b""
        self.file_path = None
        self.current_page = 0
        self.found_offsets = []
        self.found_index = -1

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.open_button = QPushButton("Открыть BIN")
        self.open_button.clicked.connect(self.open_file)
        self.file_label = QLabel("Файл не открыт")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(self.open_button)
        top.addWidget(self.file_label, 1)
        layout.addLayout(top)

        nav = QHBoxLayout()
        self.prev_button = QPushButton("◀ Предыдущая")
        self.prev_button.clicked.connect(self.prev_page)
        self.next_button = QPushButton("Следующая ▶")
        self.next_button.clicked.connect(self.next_page)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self.page_changed)
        self.page_label = QLabel("из 1")
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Адрес, например 0x1000")
        self.goto_button = QPushButton("Перейти")
        self.goto_button.clicked.connect(self.goto_address)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.next_button)
        nav.addSpacing(16)
        nav.addWidget(QLabel("Страница:"))
        nav.addWidget(self.page_spin)
        nav.addWidget(self.page_label)
        nav.addStretch()
        nav.addWidget(self.address_input)
        nav.addWidget(self.goto_button)
        layout.addLayout(nav)

        search = QHBoxLayout()
        self.search_type = QComboBox()
        self.search_type.addItems(["Текст", "HEX"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ExpressLRS или E9 03 02 20")
        self.search_input.returnPressed.connect(self.find_next)
        self.find_button = QPushButton("Найти")
        self.find_button.clicked.connect(self.find_all)
        self.find_next_button = QPushButton("Следующее")
        self.find_next_button.clicked.connect(self.find_next)
        self.search_status = QLabel("")
        search.addWidget(self.search_type)
        search.addWidget(self.search_input, 1)
        search.addWidget(self.find_button)
        search.addWidget(self.find_next_button)
        search.addWidget(self.search_status)
        layout.addLayout(search)

        self.table = QTableWidget(0, 18)
        self.table.setHorizontalHeaderLabels(
            ["Адрес"] + [f"{i:02X}" for i in range(16)] + ["ASCII"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.cellClicked.connect(self.byte_selected)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.TypeWriter)
        self.table.setFont(mono)
        self.table.setColumnWidth(0, 105)
        for col in range(1, 17):
            self.table.setColumnWidth(col, 38)
        self.table.setColumnWidth(17, 170)
        layout.addWidget(self.table, 1)

        info = QGroupBox("Выбранный байт")
        grid = QGridLayout(info)
        self.info_address = QLabel("-")
        self.info_hex = QLabel("-")
        self.info_dec = QLabel("-")
        self.info_bin = QLabel("-")
        self.info_ascii = QLabel("-")
        for label in [self.info_address, self.info_hex, self.info_dec, self.info_bin, self.info_ascii]:
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(QLabel("Адрес:"), 0, 0)
        grid.addWidget(self.info_address, 0, 1)
        grid.addWidget(QLabel("HEX:"), 0, 2)
        grid.addWidget(self.info_hex, 0, 3)
        grid.addWidget(QLabel("DEC:"), 0, 4)
        grid.addWidget(self.info_dec, 0, 5)
        grid.addWidget(QLabel("BIN:"), 1, 0)
        grid.addWidget(self.info_bin, 1, 1, 1, 2)
        grid.addWidget(QLabel("ASCII:"), 1, 3)
        grid.addWidget(self.info_ascii, 1, 4, 1, 2)
        layout.addWidget(info)
        self.update_controls()

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть прошивку или дамп Flash",
            str(Path.home()),
            "Binary files (*.bin *.img);;All files (*)",
        )
        if not filename:
            return
        try:
            self.file_path = Path(filename)
            self.data = self.file_path.read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка чтения", str(exc))
            return

        self.current_page = 0
        self.found_offsets = []
        self.found_index = -1
        self.file_label.setText(
            f"{self.file_path}  |  {len(self.data):,} байт  |  0x{len(self.data):X}"
        )
        pages = max(1, math.ceil(len(self.data) / PAGE_SIZE))
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(pages)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self.page_label.setText(f"из {pages}")
        self.render_page()
        self.update_controls()

    def render_page(self):
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        start = self.current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self.data))
        chunk = self.data[start:end]
        row_count = math.ceil(len(chunk) / BYTES_PER_ROW) if chunk else 0
        self.table.setRowCount(row_count)

        for row in range(row_count):
            row_start = row * BYTES_PER_ROW
            absolute = start + row_start
            addr = QTableWidgetItem(f"0x{absolute:08X}")
            addr.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, addr)
            row_bytes = chunk[row_start:row_start + BYTES_PER_ROW]
            ascii_chars = []
            for index, byte in enumerate(row_bytes):
                item = QTableWidgetItem(f"{byte:02X}")
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, absolute + index)
                self.table.setItem(row, index + 1, item)
                ascii_chars.append(chr(byte) if 32 <= byte <= 126 else ".")
            self.table.setItem(row, 17, QTableWidgetItem("".join(ascii_chars)))

        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()

    def update_controls(self):
        pages = max(1, math.ceil(len(self.data) / PAGE_SIZE))
        self.prev_button.setEnabled(bool(self.data) and self.current_page > 0)
        self.next_button.setEnabled(bool(self.data) and self.current_page < pages - 1)
        self.goto_button.setEnabled(bool(self.data))
        self.find_button.setEnabled(bool(self.data))
        self.find_next_button.setEnabled(bool(self.found_offsets))

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.sync_page_spin()
            self.render_page()
            self.update_controls()

    def next_page(self):
        pages = max(1, math.ceil(len(self.data) / PAGE_SIZE))
        if self.current_page < pages - 1:
            self.current_page += 1
            self.sync_page_spin()
            self.render_page()
            self.update_controls()

    def page_changed(self, value):
        self.current_page = value - 1
        self.render_page()
        self.update_controls()

    def sync_page_spin(self):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)

    def goto_address(self):
        if not self.data:
            return
        text = self.address_input.text().strip().lower()
        try:
            address = int(text, 16 if text.startswith("0x") else 10)
        except ValueError:
            QMessageBox.warning(self, "Неверный адрес", "Введи адрес как 0x1000 или десятичное число.")
            return
        if address < 0 or address >= len(self.data):
            QMessageBox.warning(
                self,
                "Адрес вне файла",
                f"Допустимый диапазон: 0x0 ... 0x{len(self.data) - 1:X}",
            )
            return
        self.select_offset(address)

    def parse_search_pattern(self):
        text = self.search_input.text()
        if self.search_type.currentText() == "Текст":
            return text.encode("utf-8")
        cleaned = text.replace(",", " ").replace("0x", "")
        try:
            return bytes(int(part, 16) for part in cleaned.split())
        except ValueError as exc:
            raise ValueError("HEX вводится байтами: E9 03 02 20") from exc

    def find_all(self):
        if not self.data:
            return
        try:
            pattern = self.parse_search_pattern()
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка поиска", str(exc))
            return
        if not pattern:
            QMessageBox.warning(self, "Ошибка поиска", "Строка поиска пустая.")
            return
        offsets = []
        start = 0
        while True:
            found = self.data.find(pattern, start)
            if found < 0:
                break
            offsets.append(found)
            start = found + 1
            if len(offsets) >= 10000:
                break
        self.found_offsets = offsets
        self.found_index = -1
        if not offsets:
            self.search_status.setText("Не найдено")
            self.find_next_button.setEnabled(False)
            return
        self.search_status.setText(f"Найдено: {len(offsets)}")
        self.find_next_button.setEnabled(True)
        self.find_next()

    def find_next(self):
        if not self.found_offsets:
            self.find_all()
            return
        self.found_index = (self.found_index + 1) % len(self.found_offsets)
        offset = self.found_offsets[self.found_index]
        self.search_status.setText(
            f"{self.found_index + 1}/{len(self.found_offsets)} @ 0x{offset:X}"
        )
        self.select_offset(offset)

    def select_offset(self, offset):
        self.current_page = offset // PAGE_SIZE
        self.sync_page_spin()
        self.render_page()
        self.update_controls()
        within = offset % PAGE_SIZE
        row = within // BYTES_PER_ROW
        col = (within % BYTES_PER_ROW) + 1
        item = self.table.item(row, col)
        if item:
            self.table.setCurrentItem(item)
            self.table.scrollToItem(item)
            self.show_byte_info(offset)

    def byte_selected(self, row, column):
        if column < 1 or column > 16:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        offset = item.data(Qt.UserRole)
        if offset is not None:
            self.show_byte_info(int(offset))

    def show_byte_info(self, offset):
        if offset < 0 or offset >= len(self.data):
            return
        value = self.data[offset]
        self.info_address.setText(f"0x{offset:08X}")
        self.info_hex.setText(f"0x{value:02X}")
        self.info_dec.setText(str(value))
        self.info_bin.setText(f"{value:08b}")
        self.info_ascii.setText(chr(value) if 32 <= value <= 126 else "непечатный")


class PartitionsViewer(QWidget):
    """ESP32 partition-table viewer for full flash dumps and combined images."""

    TYPE_NAMES = {
        0x00: "app",
        0x01: "data",
    }

    APP_SUBTYPES = {
        0x00: "factory",
        0x10: "ota_0",
        0x11: "ota_1",
        0x12: "ota_2",
        0x13: "ota_3",
        0x14: "ota_4",
        0x15: "ota_5",
        0x16: "ota_6",
        0x17: "ota_7",
        0x18: "ota_8",
        0x19: "ota_9",
        0x1A: "ota_10",
        0x1B: "ota_11",
        0x1C: "ota_12",
        0x1D: "ota_13",
        0x1E: "ota_14",
        0x1F: "ota_15",
        0x20: "test",
    }

    DATA_SUBTYPES = {
        0x00: "ota",
        0x01: "phy",
        0x02: "nvs",
        0x03: "coredump",
        0x04: "nvs_keys",
        0x05: "efuse",
        0x06: "undefined",
        0x80: "esphttpd",
        0x81: "fat",
        0x82: "spiffs",
        0x83: "littlefs",
    }

    def __init__(self, hex_viewer=None):
        super().__init__()
        self.hex_viewer = hex_viewer
        self.data = b""
        self.file_path = None
        self.entries = []
        self.table_offset = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.open_button = QPushButton("Открыть BIN / дамп Flash")
        self.open_button.clicked.connect(self.open_file)

        self.use_hex_button = QPushButton("Взять файл из HEX Viewer")
        self.use_hex_button.clicked.connect(self.use_hex_file)

        self.file_label = QLabel("Файл не открыт")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        top.addWidget(self.open_button)
        top.addWidget(self.use_hex_button)
        top.addWidget(self.file_label, 1)
        layout.addLayout(top)

        self.status_label = QLabel(
            "Открой полный дамп ESP32. Для ESP8266/ESP8285 стандартной таблицы ESP32 нет."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Имя",
                "Тип",
                "Подтип",
                "Начало",
                "Конец",
                "Размер HEX",
                "Размер",
                "Флаги",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self.open_partition_in_hex)

        widths = [150, 85, 110, 110, 110, 110, 110, 90]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)

        layout.addWidget(self.table, 1)

        map_box = QGroupBox("Схематическая карта Flash")
        map_layout = QVBoxLayout(map_box)

        self.memory_map = QPlainTextEdit()
        self.memory_map.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.TypeWriter)
        self.memory_map.setFont(mono)

        map_layout.addWidget(self.memory_map)
        layout.addWidget(map_box, 1)

        hint = QLabel(
            "Двойной щелчок по разделу откроет его начальный адрес во вкладке HEX Viewer."
        )
        layout.addWidget(hint)

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть полный дамп Flash или объединённый BIN",
            str(Path.home()),
            "Binary files (*.bin *.img);;All files (*)",
        )
        if filename:
            self.load_file(filename)

    def use_hex_file(self):
        if not self.hex_viewer or not self.hex_viewer.file_path:
            QMessageBox.information(
                self,
                "Нет файла",
                "Сначала открой BIN во вкладке HEX Viewer.",
            )
            return
        self.load_file(str(self.hex_viewer.file_path))

    def load_file(self, filename):
        try:
            self.file_path = Path(filename)
            self.data = self.file_path.read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка чтения", str(exc))
            return

        self.file_label.setText(
            f"{self.file_path}  |  {len(self.data):,} байт  |  0x{len(self.data):X}"
        )
        self.analyse()

    @staticmethod
    def human_size(size):
        if size >= 1024 * 1024 and size % (1024 * 1024) == 0:
            return f"{size // (1024 * 1024)} MB"
        if size >= 1024 and size % 1024 == 0:
            return f"{size // 1024} KB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    def subtype_name(self, ptype, subtype):
        if ptype == 0x00:
            return self.APP_SUBTYPES.get(subtype, f"0x{subtype:02X}")
        if ptype == 0x01:
            return self.DATA_SUBTYPES.get(subtype, f"0x{subtype:02X}")
        return f"0x{subtype:02X}"

    def parse_at(self, offset):
        entries = []
        cursor = offset
        max_entries = 96

        for _ in range(max_entries):
            if cursor + 32 > len(self.data):
                break

            record = self.data[cursor:cursor + 32]
            magic = struct.unpack_from("<H", record, 0)[0]

            if record == b"\xFF" * 32:
                break

            if magic == 0xEBEB:
                cursor += 32
                continue

            if magic != 0x50AA:
                break

            ptype = record[2]
            subtype = record[3]
            part_offset, size = struct.unpack_from("<II", record, 4)
            label_raw = record[12:28].split(b"\x00", 1)[0]
            label = label_raw.decode("utf-8", errors="replace") or "(без имени)"
            flags = struct.unpack_from("<I", record, 28)[0]

            # Guard against random AA50 bytes being misread as a table.
            if size == 0 or part_offset >= 0x10000000 or size >= 0x10000000:
                return []

            entries.append(
                {
                    "label": label,
                    "type": ptype,
                    "subtype": subtype,
                    "offset": part_offset,
                    "size": size,
                    "flags": flags,
                }
            )
            cursor += 32

        return entries

    def find_partition_table(self):
        preferred = [0x8000, 0x9000, 0x7000, 0xA000]
        checked = set()

        for offset in preferred:
            checked.add(offset)
            if offset + 32 <= len(self.data):
                entries = self.parse_at(offset)
                if entries:
                    return offset, entries

        # Custom offsets are unusual, but humans do enjoy inventing them.
        scan_end = min(len(self.data) - 32, 0x20000)
        for offset in range(0, max(0, scan_end + 1), 0x1000):
            if offset in checked:
                continue
            if self.data[offset:offset + 2] == b"\xAA\x50":
                entries = self.parse_at(offset)
                if entries:
                    return offset, entries

        return None, []

    def analyse(self):
        self.table.setRowCount(0)
        self.memory_map.clear()
        self.table_offset, self.entries = self.find_partition_table()

        if not self.entries:
            header = self.data[:1]
            chip_hint = (
                "Файл похож на ESP8266/ESP8285 или на отдельный application.bin."
                if header == b"\xE9"
                else "Стандартная ESP32 partition table не найдена."
            )
            self.status_label.setText(
                chip_hint
                + " Для полноценной карты нужен полный дамп Flash, обычно начиная с адреса 0x000000."
            )
            self.memory_map.setPlainText(
                self.build_fallback_map()
            )
            return

        self.status_label.setText(
            f"Найдена ESP32 partition table по адресу 0x{self.table_offset:08X}. "
            f"Разделов: {len(self.entries)}."
        )
        self.populate_table()
        self.memory_map.setPlainText(self.build_memory_map())

    def populate_table(self):
        self.table.setRowCount(len(self.entries))

        for row, entry in enumerate(self.entries):
            ptype_name = self.TYPE_NAMES.get(
                entry["type"], f"0x{entry['type']:02X}"
            )
            subtype_name = self.subtype_name(entry["type"], entry["subtype"])
            start = entry["offset"]
            end = start + entry["size"] - 1

            values = [
                entry["label"],
                ptype_name,
                subtype_name,
                f"0x{start:08X}",
                f"0x{end:08X}",
                f"0x{entry['size']:X}",
                self.human_size(entry["size"]),
                f"0x{entry['flags']:08X}",
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col >= 3:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

    def build_fallback_map(self):
        if not self.data:
            return "Нет данных."

        length = len(self.data)
        lines = [
            f"ФАЙЛ / FLASH: {self.human_size(length)} (0x{length:X})",
            "",
            f"0x00000000  ├──────────────────────────────────────────┤",
            f"            │ BIN / содержимое Flash                  │",
            f"0x{max(0, length - 1):08X}  └──────────────────────────────────────────┘",
            "",
            "Таблица разделов формата ESP32 не обнаружена.",
            "У ESP8266/ESP8285 такой стандартной таблицы обычно нет.",
        ]
        return "\n".join(lines)

    def build_memory_map(self):
        flash_size = max(
            len(self.data),
            max(entry["offset"] + entry["size"] for entry in self.entries),
        )
        width = 54
        lines = [
            f"FLASH: {self.human_size(flash_size)} (0x{flash_size:X})",
            f"PARTITION TABLE: 0x{self.table_offset:08X}",
            "",
        ]

        sorted_entries = sorted(self.entries, key=lambda item: item["offset"])
        cursor = 0

        for entry in sorted_entries:
            start = entry["offset"]
            size = entry["size"]
            end = start + size

            if start > cursor:
                gap = start - cursor
                gap_blocks = max(1, round(gap / flash_size * width))
                lines.append(
                    f"0x{cursor:08X}  [{'·' * min(width, gap_blocks):<{width}}] "
                    f"свободно/служебное  {self.human_size(gap)}"
                )

            blocks = max(1, round(size / flash_size * width))
            bar = "█" * min(width, blocks)
            label = f"{entry['label']} ({self.subtype_name(entry['type'], entry['subtype'])})"
            lines.append(
                f"0x{start:08X}  [{bar:<{width}}] "
                f"{label:<24} {self.human_size(size)}"
            )
            cursor = max(cursor, end)

        if cursor < flash_size:
            gap = flash_size - cursor
            blocks = max(1, round(gap / flash_size * width))
            lines.append(
                f"0x{cursor:08X}  [{'·' * min(width, blocks):<{width}}] "
                f"свободно/неразмечено  {self.human_size(gap)}"
            )

        lines.append(f"0x{flash_size:08X}")
        return "\n".join(lines)

    def open_partition_in_hex(self, row, _column):
        if row < 0 or row >= len(self.entries):
            return
        if not self.hex_viewer:
            return

        entry = self.entries[row]

        if self.file_path and self.hex_viewer.file_path != self.file_path:
            try:
                self.hex_viewer.file_path = self.file_path
                self.hex_viewer.data = self.data
                self.hex_viewer.current_page = 0
                self.hex_viewer.found_offsets = []
                self.hex_viewer.found_index = -1
                self.hex_viewer.file_label.setText(
                    f"{self.file_path}  |  {len(self.data):,} байт  |  0x{len(self.data):X}"
                )
                pages = max(1, math.ceil(len(self.data) / PAGE_SIZE))
                self.hex_viewer.page_spin.blockSignals(True)
                self.hex_viewer.page_spin.setMaximum(pages)
                self.hex_viewer.page_spin.setValue(1)
                self.hex_viewer.page_spin.blockSignals(False)
                self.hex_viewer.page_label.setText(f"из {pages}")
                self.hex_viewer.render_page()
                self.hex_viewer.update_controls()
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))
                return

        if entry["offset"] >= len(self.hex_viewer.data):
            QMessageBox.information(
                self,
                "Адрес вне файла",
                "Раздел описан в таблице, но его адрес находится за пределами открытого файла. "
                "Вероятно, открыт не полный дамп Flash.",
            )
            return

        self.hex_viewer.select_offset(entry["offset"])
        window = self.window()
        if hasattr(window, "tabs"):
            window.tabs.setCurrentWidget(self.hex_viewer)


class EspProgrammer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.setWindowTitle("ESP Programmer (Trakror Corporation - 2026)")
        self.resize(1180, 760)
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        title1 = QLabel("ESP Programmer v2.0 2026  ")
        title1.setStyleSheet("font-size: 24px; font-weight: bold;")
        title2 = QLabel("(Sinelnikov Oleg)")
        title2.setStyleSheet("font-size: 12px")
        
        main.addWidget(title1)
        main.addWidget(title2)
        main.addWidget(QLabel("Диагностика ESP и просмотр бинарных прошивок"))

        self.tabs = QTabWidget()
        main.addWidget(self.tabs, 1)
        self.programmer_tab = QWidget()
        self.hex_viewer = HexViewer()
        self.partitions_viewer = PartitionsViewer(self.hex_viewer)
        self.tabs.addTab(self.programmer_tab, "Устройство")
        self.tabs.addTab(self.hex_viewer, "HEX Viewer")
        self.tabs.addTab(self.partitions_viewer, "Разделы Flash")
        self.build_programmer_tab()
        self.refresh_ports()

    def build_programmer_tab(self):
        layout = QVBoxLayout(self.programmer_tab)
        connection_box = QGroupBox("Подключение")
        grid = QGridLayout(connection_box)
        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("115200")
        refresh = QPushButton("Обновить порты")
        refresh.clicked.connect(self.refresh_ports)
        grid.addWidget(QLabel("Порт:"), 0, 0)
        grid.addWidget(self.port_combo, 0, 1)
        grid.addWidget(refresh, 0, 2)
        grid.addWidget(QLabel("Скорость:"), 1, 0)
        grid.addWidget(self.baud_combo, 1, 1)
        layout.addWidget(connection_box)

        actions = QGroupBox("Операции")
        action_grid = QGridLayout(actions)
        detect = QPushButton("Определить устройство")
        detect.clicked.connect(self.detect_chip)
        flash = QPushButton("Информация о Flash")
        flash.clicked.connect(self.flash_id)
        mac = QPushButton("Прочитать MAC")
        mac.clicked.connect(self.read_mac)
        backup = QPushButton("Сохранить полный Flash")
        backup.clicked.connect(self.backup_flash)

        write_firmware = QPushButton("Записать прошивку")
        write_firmware.clicked.connect(self.write_firmware)

        open_hex = QPushButton("Открыть BIN в HEX Viewer")
        open_hex.clicked.connect(lambda: self.tabs.setCurrentWidget(self.hex_viewer))
        open_partitions = QPushButton("Посмотреть разделы Flash")
        open_partitions.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.partitions_viewer)
        )
        erase = QPushButton("Очистить окно")
        action_grid.addWidget(detect, 0, 0)
        action_grid.addWidget(flash, 0, 1)
        action_grid.addWidget(mac, 1, 0)
        action_grid.addWidget(backup, 1, 1)
        action_grid.addWidget(write_firmware, 2, 0, 1, 2)
        action_grid.addWidget(open_hex, 3, 0)
        action_grid.addWidget(open_partitions, 3, 1)
        layout.addWidget(actions)

        status = QHBoxLayout()
        self.status_label = QLabel("Готово")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        status.addWidget(self.status_label)
        status.addWidget(self.progress)
        layout.addLayout(status)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.TypeWriter)
        self.console.setFont(mono)
        erase.clicked.connect(self.console.clear)
        layout.addWidget(self.console, 1)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(erase)
        layout.addLayout(bottom)

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        for port in ports:
            self.port_combo.addItem(
                f"{port.device} — {port.description or 'неизвестное устройство'}",
                port.device,
            )
        if not ports:
            self.port_combo.addItem("Порты не найдены", "")
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == current:
                self.port_combo.setCurrentIndex(index)
                break

    def selected_port(self):
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Нет порта", "Подключи устройство и обнови список портов.")
            return ""
        return port

    def base_command(self):
        port = self.selected_port()
        if not port:
            return []
        if getattr(sys, "frozen", False):
            esptool_exe = Path(sys.executable).with_name("esptool.exe")
            if not esptool_exe.exists():
                QMessageBox.critical(
                    self,
                    "esptool.exe не найден",
                    f"Рядом с программой отсутствует файл:\n{esptool_exe}",
                )
                return []

            return [
                str(esptool_exe),
                "--port",
                port,
                "--baud",
                self.baud_combo.currentText(),
            ]

        return [
            sys.executable,
            "-m",
            "esptool",
            "--port",
            port,
            "--baud",
            self.baud_combo.currentText(),
        ]

    def run_command(self, command):
        if not command:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Операция выполняется", "Дождись окончания текущей операции.")
            return
        self.status_label.setText("Выполняется…")
        self.progress.setRange(0, 0)
        self.worker = CommandWorker(command)
        self.worker.output.connect(self.console.insertPlainText)
        self.worker.finished_ok.connect(self.command_finished)
        self.worker.start()

    def command_finished(self, success):
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_label.setText("Успешно" if success else "Ошибка")
        self.console.insertPlainText(
            "\nОперация завершена успешно.\n" if success else "\nОперация завершилась с ошибкой.\n"
        )

    def detect_chip(self):
        command = self.base_command()
        if command:
            command.append("chip_id")
            self.run_command(command)

    def flash_id(self):
        command = self.base_command()
        if command:
            command.append("flash_id")
            self.run_command(command)

    def read_mac(self):
        command = self.base_command()
        if command:
            command.append("read_mac")
            self.run_command(command)

    def backup_flash(self):
        if not self.selected_port():
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить дамп Flash",
            str(Path.home() / f"esp_flash_{timestamp}.bin"),
            "Binary files (*.bin);;All files (*)",
        )
        if not output_file:
            return
        size_text, ok = self.ask_flash_size()
        if not ok:
            return
        command = self.base_command()
        if command:
            command.extend(["read-flash", "0x000000", size_text, output_file])
            self.run_command(command)

    def write_firmware(self):
        if not self.selected_port():
            return

        firmware_file, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать прошивку",
            str(Path.home()),
            "Firmware files (*.bin);;All files (*)",
        )
        if not firmware_file:
            return

        default_address = "0x000000"
        address, ok = QInputDialog.getText(
            self,
            "Адрес записи",
            "Начальный адрес прошивки:",
            QLineEdit.Normal,
            default_address,
        )
        if not ok:
            return

        address = address.strip()
        try:
            parsed_address = int(address, 0)
        except ValueError:
            QMessageBox.warning(
                self,
                "Неверный адрес",
                "Адрес должен выглядеть как 0x000000, 0x1000 или 65536.",
            )
            return

        if parsed_address < 0:
            QMessageBox.warning(
                self,
                "Неверный адрес",
                "Адрес не может быть отрицательным.",
            )
            return

        file_size = Path(firmware_file).stat().st_size
        answer = QMessageBox.question(
            self,
            "Подтверждение записи",
            "Будет записан файл:\n"
            f"{firmware_file}\n\n"
            f"Размер: {file_size:,} байт (0x{file_size:X})\n"
            f"Адрес: 0x{parsed_address:X}\n\n"
            "Запись Flash изменит содержимое устройства. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        command = self.base_command()
        if command:
            command.extend(
                [
                    "--before",
                    "default-reset",
                    "--after",
                    "hard-reset",
                    "write-flash",
                    "--flash-mode",
                    "keep",
                    "--flash-freq",
                    "keep",
                    "--flash-size",
                    "keep",
                    f"0x{parsed_address:X}",
                    firmware_file,
                ]
            )
            self.console.insertPlainText(
                "\n=== Запись прошивки ===\n"
                f"Файл: {firmware_file}\n"
                f"Адрес: 0x{parsed_address:X}\n"
                f"Размер: {file_size:,} байт\n\n"
            )
            self.run_command(command)

    def ask_flash_size(self):
        from PySide6.QtWidgets import QInputDialog
        sizes = {
            "1 MB": "0x100000", "2 MB": "0x200000", "4 MB": "0x400000",
            "8 MB": "0x800000", "16 MB": "0x1000000",
        }
        label, ok = QInputDialog.getItem(
            self, "Размер Flash", "Выбери размер Flash:", list(sizes.keys()), 2, False
        )
        return (sizes[label], True) if ok else ("", False)


def main():
    app = QApplication(sys.argv)
    window = EspProgrammer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
