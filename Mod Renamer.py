# -*- coding: utf-8 -*-
"""
Mod Renamer Plugin for Mod Organizer 2
批量重命名模组，支持灵活的模式和前缀预设。

快捷键：Ctrl+Shift+R
"""

import json
import logging
import os
import re
from datetime import datetime

from PyQt6.QtCore import QObject, QEvent, Qt, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QTreeView, QDialog, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit, QTabWidget, QWidget
)

import mobase

log = logging.getLogger("ModRenamer")


# ============================================================
#  RenamerStorage - 存储设置、前缀和历史记录
# ============================================================

class RenamerStorage:
    """存储设置、前缀预设和重命名历史记录的类。"""

    def __init__(self, storage_path):
        """
        初始化存储类
        
        Args:
            storage_path: 存储文件的路径
        """
        self._path = storage_path
        self._data = {
            "settings": {},
            "prefixes": [
                "【{SEP}】", 
                "【服装】", "【护甲】", "【武器】", "【特效】",
                "【美化】", "【预设】", "【随从】", "【战斗】",
                "【动画】", "【环境】", "【修复】", "【远景】",
                "【纹理】", "【补丁】", "【界面】", "【功能】",
                "【NPC】"
            ],
            "history": []
        }
        self._load()

    def _load(self):
        """从文件加载存储的数据。"""
        if os.path.isfile(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for key in loaded:
                        self._data[key] = loaded[key]
                log.info(f"成功加载设置文件: {self._path}")
            except Exception as e:
                log.error(f"加载设置失败: {e}")

    def _save(self):
        """保存数据到文件。"""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            log.info(f"成功保存设置文件: {self._path}")
        except Exception as e:
            log.error(f"保存失败: {e}")

    @property
    def settings(self):
        """获取保存的设置。"""
        return self._data.get("settings", {})

    def save_settings(self, settings):
        """
        保存设置
        
        Args:
            settings: 要保存的设置字典
        """
        self._data["settings"] = settings
        self._save()

    def get_prefixes(self):
        """获取前缀预设列表。"""
        return self._data.get("prefixes", [])

    def add_prefix(self, prefix):
        """
        添加新的前缀预设
        
        Args:
            prefix: 要添加的前缀
            
        Returns:
            bool: 是否成功添加
        """
        prefixes = self._data.get("prefixes", [])
        if prefix and prefix not in prefixes:
            prefixes.insert(0, prefix)  # 新前缀放在最前面
            self._data["prefixes"] = prefixes
            self._save()
            return True
        return False

    def remove_prefix(self, prefix):
        """
        移除前缀预设
        
        Args:
            prefix: 要移除的前缀
            
        Returns:
            bool: 是否成功移除
        """
        prefixes = self._data.get("prefixes", [])
        if prefix in prefixes:
            prefixes.remove(prefix)
            self._data["prefixes"] = prefixes
            self._save()
            return True
        return False

    def add_history(self, entry):
        """
        添加重命名历史记录
        
        Args:
            entry: 历史记录条目
        """
        history = self._data.get("history", [])
        history.insert(0, entry)  # 新记录放在最前面
        self._data["history"] = history[:30]  # 只保留最近30条记录
        self._save()

    def get_history(self):
        """获取历史记录列表。"""
        return self._data.get("history", [])

    def remove_last_history(self):
        """
        移除最后一条历史记录
        
        Returns:
            dict or None: 被移除的历史记录，如果没有则返回None
        """
        history = self._data.get("history", [])
        if history:
            removed = history.pop(0)
            self._data["history"] = history
            self._save()
            return removed
        return None

    def clear_history(self):
        """清空历史记录。"""
        self._data["history"] = []
        self._save()


# ============================================================
#  RenameEngine - 重命名引擎
# ============================================================

class RenameEngine:
    """基于模式的重命名引擎，支持前缀和其他特殊标签。"""

    # 前缀模式匹配正则表达式：匹配 [TAG] 格式的开头
    PREFIX_PATTERN = re.compile(r'^(\[[^\]]+\]\s*)+')

    def __init__(self):
        """初始化重命名引擎。"""
        self._counter = 1
        self._counter_step = 1
        self._counter_digits = 2

    def reset_counter(self, start=1, step=1, digits=2):
        """
        重置计数器
        
        Args:
            start: 计数器起始值
            step: 计数器步长
            digits: 计数器最小位数
        """
        self._counter = start
        self._counter_step = step
        self._counter_digits = digits

    def increment_counter(self):
        """递增计数器。"""
        self._counter += self._counter_step

    @classmethod
    def strip_prefix(cls, name):
        """
        从名称中移除现有的 [TAG] 前缀
        
        Args:
            name: 原始名称
            
        Returns:
            str: 移除前缀后的名称
        """
        return cls.PREFIX_PATTERN.sub('', name).strip()

    def expand_prefix_tags(self, prefix, separator_name=""):
        """
        展开前缀中的特殊标签：
            {SEP} - 分隔符名称
            {N} - 计数器（无填充）
            {NN} - 计数器（2位数字）
            {NNN} - 计数器（3位数字）
            {DATE} - YYYY-MM-DD
            {YMD} - YYYYMMDD
        
        Args:
            prefix: 包含标签的前缀
            separator_name: 分隔符名称
            
        Returns:
            str: 展开标签后的前缀
        """
        result = prefix
        now = datetime.now()

        if "{SEP}" in result:
            # 清理分隔符名称，移除常见的分隔符字符和后缀
            sep_clean = self.clean_separator_name(separator_name)
            result = result.replace("{SEP}", sep_clean)

        # 日期相关标签
        result = result.replace("{DATE}", now.strftime("%Y-%m-%d"))
        result = result.replace("{YMD}", now.strftime("%Y%m%d"))
        
        # 计数器相关标签
        result = result.replace("{NNN}", str(self._counter).zfill(3))
        result = result.replace("{NN}", str(self._counter).zfill(2))
        result = result.replace("{N}", str(self._counter))

        return result

    def apply_pattern(self, original_name, pattern, separator_name=""):
        """
        应用完整的重命名模式。
        
        支持的标签：
            [N] - 原始名称
            [N1-5] - 字符1-5
            [N2,5] - 从位置2开始的5个字符
            [C] / [C:3] - 计数器
            [S] - 分隔符名称
            [YMD], [Y], [M], [D] - 日期
            [hms], [h], [m], [s] - 时间
        
        Args:
            original_name: 原始名称
            pattern: 重命名模式
            separator_name: 分隔符名称
            
        Returns:
            str: 应用模式后的名称
        """
        result = pattern
        now = datetime.now()

        # 替换原始名称
        result = result.replace("[N]", original_name)

        # 提取指定范围的字符 [N1-5] 格式
        for match in re.finditer(r'\[N(\d+)-(\d+)\]', result):
            start = int(match.group(1)) - 1  # 转换为零基索引
            end = int(match.group(2))
            extracted = original_name[start:end] if start < len(original_name) else ""
            result = result.replace(match.group(0), extracted, 1)

        # 提取从指定位置开始的字符 [N2,5] 格式
        for match in re.finditer(r'\[N(\d+),(\d+)\]', result):
            pos = int(match.group(1)) - 1  # 转换为零基索引
            length = int(match.group(2))
            extracted = original_name[pos:pos + length] if pos < len(original_name) else ""
            result = result.replace(match.group(0), extracted, 1)

        # 替换分隔符名称，清理特殊字符和后缀
        sep_clean = self.clean_separator_name(separator_name)
        result = result.replace("[S]", sep_clean)

        # 日期标签
        result = result.replace("[YMD]", now.strftime("%Y%m%d"))
        result = result.replace("[Y]", now.strftime("%Y"))
        result = result.replace("[M]", now.strftime("%m"))
        result = result.replace("[D]", now.strftime("%d"))

        # 时间标签
        result = result.replace("[hms]", now.strftime("%H%M%S"))
        result = result.replace("[h]", now.strftime("%H"))
        result = result.replace("[m]", now.strftime("%M"))
        result = result.replace("[s]", now.strftime("%S"))

        # 自定义位数的计数器 [C:3] 格式
        for match in re.finditer(r'\[C:(\d+)\]', result):
            digits = int(match.group(1))
            result = result.replace(match.group(0), str(self._counter).zfill(digits), 1)

        # 默认计数器 [C] 格式
        result = result.replace("[C]", str(self._counter).zfill(self._counter_digits))

        return result

    @staticmethod
    def clean_separator_name(name):
        """
        清理分隔符名称，移除常见后缀和特殊字符
        
        Args:
            name: 原始分隔符名称
            
        Returns:
            str: 清理后的分隔符名称
        """
        if not name:
            return ""
        
        # 移除常见的分隔符后缀
        cleaned = name
        suffixes_to_remove = [
            "_separator", "_sep", "_divider", "-separator", 
            "-sep", "-divider", " separator", " sep", " divider"
        ]
        
        for suffix in suffixes_to_remove:
            if cleaned.lower().endswith(suffix.lower()):
                cleaned = cleaned[:-len(suffix)]
                
        # 移除常见的分隔符字符前缀和后缀
        cleaned = cleaned.strip("-=*# \t_+[]()")
        
        return cleaned

    def apply_search_replace(self, name, search, replace,
                             use_regex=False, ignore_case=False):
        """
        应用搜索和替换，支持正则表达式
        
        Args:
            name: 原始名称
            search: 搜索字符串
            replace: 替换字符串
            use_regex: 是否使用正则表达式
            ignore_case: 是否忽略大小写
            
        Returns:
            str: 替换后的名称
        """
        if not search:
            return name

        try:
            if use_regex:
                flags = re.IGNORECASE if ignore_case else 0
                return re.sub(search, replace, name, flags=flags)
            else:
                if ignore_case:
                    # 使用正则表达式实现忽略大小写的替换
                    pattern = re.compile(re.escape(search), re.IGNORECASE)
                    return pattern.sub(replace, name)
                return name.replace(search, replace)
        except re.error as e:
            log.warning(f"正则表达式错误: {e}")
            return name

    def apply_case(self, name, mode):
        """
        应用大小写转换
        
        Args:
            name: 原始名称
            mode: 大小写模式
            
        Returns:
            str: 转换后的名称
        """
        modes = {
            "lower": str.lower,      # 全小写
            "upper": str.upper,      # 全大写
            "title": str.title,      # 首字母大写
            "capitalize": str.capitalize  # 句子形式
        }
        func = modes.get(mode)
        return func(name) if func else name

    @staticmethod
    def sanitize_name(name):
        """
        清理名称，移除文件夹名称中不允许的字符
        
        Args:
            name: 原始名称
            
        Returns:
            str: 清理后的名称
        """
        # 移除Windows文件夹名称中不允许的字符
        for char in '<>:"/\\|?*':
            name = name.replace(char, '')
        
        # 移除多余的空白字符
        name = ' '.join(name.split())
        # 移除开头和结尾的空白及句点
        name = name.strip().strip('.')
        return name


# ============================================================
#  RenameDialog - 重命名对话框
# ============================================================

class RenameDialog(QDialog):
    """用于批量重命名模组的对话框，支持前缀预设。"""

    def __init__(self, mod_list, storage, rename_callback,
                 mods_path, parent=None):
        """
        初始化重命名对话框
        
        Args:
            mod_list: 模组列表，每个元素为 (mod_name, separator_name) 元组
            storage: 存储对象
            rename_callback: 重命名回调函数
            mods_path: 模组路径
            parent: 父窗口
        """
        super().__init__(parent)
        self.setWindowTitle("模组重命名器 (Ctrl+Shift+R)")
        self.setMinimumSize(850, 650)

        self._mod_list = mod_list
        self._storage = storage
        self._rename_callback = rename_callback
        self._mods_path = mods_path
        self._engine = RenameEngine()
        self._preview_data = []

        self._setup_ui()
        self._load_settings()
        self._update_preview()

    def _setup_ui(self):
        """设置用户界面。"""
        layout = QVBoxLayout(self)

        # === 在创建标签页之前创建按钮 ===
        self._btn_undo = QPushButton("↶ 撤销上次")
        self._btn_undo.setFixedSize(100, 30)
        self._btn_undo.clicked.connect(self._on_undo)

        self._btn_execute = QPushButton("✓ 执行")
        self._btn_execute.setFixedSize(100, 30)
        self._btn_execute.setStyleSheet(
            "QPushButton { background-color: #2d5f2d; color: white; "
            "font-weight: bold; padding: 8px 24px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #3a7a3a; }"
            "QPushButton:disabled { background-color: #ccc; color: #666; }"
        )
        self._btn_execute.clicked.connect(self._on_execute)

        btn_close = QPushButton("关闭")
        btn_close.setFixedSize(100, 30)
        btn_close.clicked.connect(self.reject)

        # === 标签页 ===
        tabs = QTabWidget()
        layout.addWidget(tabs)

        rename_tab = QWidget()
        tabs.addTab(rename_tab, "重命名")
        self._setup_rename_tab(rename_tab)

        history_tab = QWidget()
        tabs.addTab(history_tab, "历史记录")
        self._setup_history_tab(history_tab)

        # === 将按钮添加到布局 ===
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._btn_undo)
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_execute)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        self._update_buttons()

    def _setup_rename_tab(self, parent):
        """设置重命名标签页。"""
        layout = QVBoxLayout(parent)

        # === 前缀预设 ===
        prefix_group = QGroupBox("前缀预设")
        prefix_layout = QHBoxLayout(prefix_group)

        self._prefix_combo = QComboBox()
        self._prefix_combo.setEditable(True)
        self._prefix_combo.setMinimumWidth(200)
        self._prefix_combo.setPlaceholderText("选择或输入前缀...")
        self._prefix_combo.currentTextChanged.connect(self._on_prefix_changed)
        self._refresh_prefix_combo()
        prefix_layout.addWidget(self._prefix_combo)

        btn_add_prefix = QPushButton("+")
        btn_add_prefix.setFixedSize(30, 30)
        btn_add_prefix.setToolTip("保存当前为预设")
        btn_add_prefix.clicked.connect(self._on_add_prefix)
        prefix_layout.addWidget(btn_add_prefix)

        btn_remove_prefix = QPushButton("×")
        btn_remove_prefix.setFixedSize(30, 30)
        btn_remove_prefix.setToolTip("移除选中的预设")
        btn_remove_prefix.clicked.connect(self._on_remove_prefix)
        prefix_layout.addWidget(btn_remove_prefix)

        self._replace_prefix_check = QCheckBox("替换现有前缀")
        self._replace_prefix_check.setChecked(True)
        self._replace_prefix_check.stateChanged.connect(self._on_settings_changed)
        prefix_layout.addStretch()

        btn_apply_prefix = QPushButton("应用前缀")
        btn_apply_prefix.setFixedSize(100, 30)
        btn_apply_prefix.setStyleSheet(
            "QPushButton { background-color: #1a5276; color: white; padding: 4px 12px; border-radius: 4px; }"
        )
        btn_apply_prefix.clicked.connect(self._on_apply_prefix)
        prefix_layout.addWidget(btn_apply_prefix)

        layout.addWidget(prefix_group)

        prefix_help = QLabel(
            "<small>标签: <b>{SEP}</b>=分隔符, <b>{N}</b>=计数器, "
            "<b>{NN}</b>=01, <b>{NNN}</b>=001, <b>{DATE}</b>=2024-12-15</small>"
        )
        prefix_help.setStyleSheet("color: #888;")
        layout.addWidget(prefix_help)

        # === 模式和选项 ===
        options_layout = QHBoxLayout()

        # 左侧：模式设置
        pattern_group = QGroupBox("模式 (高级)")
        pattern_layout = QVBoxLayout(pattern_group)

        pattern_row = QHBoxLayout()
        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText("[N] (原始名称)")
        self._pattern_edit.textChanged.connect(self._on_settings_changed)
        pattern_row.addWidget(QLabel("模式:"))
        pattern_row.addWidget(self._pattern_edit)
        pattern_layout.addLayout(pattern_row)

        pattern_help = QLabel(
            "<small>[N]=名称 [N1-5]=字符 [C]=计数器 [S]=分隔符 [YMD]=日期</small>"
        )
        pattern_help.setStyleSheet("color: #888;")
        pattern_layout.addWidget(pattern_help)

        # 计数器设置
        counter_row = QHBoxLayout()
        counter_row.addWidget(QLabel("计数器:"))
        self._counter_start = QSpinBox()
        self._counter_start.setRange(0, 9999)
        self._counter_start.setValue(1)
        self._counter_start.valueChanged.connect(self._on_settings_changed)
        counter_row.addWidget(QLabel("起始"))
        counter_row.addWidget(self._counter_start)

        self._counter_step = QSpinBox()
        self._counter_step.setRange(1, 100)
        self._counter_step.setValue(1)
        self._counter_step.valueChanged.connect(self._on_settings_changed)
        counter_row.addWidget(QLabel("步长"))
        counter_row.addWidget(self._counter_step)

        self._counter_digits = QSpinBox()
        self._counter_digits.setRange(1, 5)
        self._counter_digits.setValue(2)
        self._counter_digits.valueChanged.connect(self._on_settings_changed)
        counter_row.addWidget(QLabel("位数"))
        counter_row.addWidget(self._counter_digits)
        counter_row.addStretch()

        pattern_layout.addLayout(counter_row)
        options_layout.addWidget(pattern_group)

        # 右侧：搜索/替换和大小写
        sr_group = QGroupBox("搜索 / 替换")
        sr_layout = QGridLayout(sr_group)

        self._search_edit = QLineEdit()
        self._search_edit.textChanged.connect(self._on_settings_changed)
        sr_layout.addWidget(QLabel("查找:"), 0, 0)
        sr_layout.addWidget(self._search_edit, 0, 1)

        self._replace_edit = QLineEdit()
        self._replace_edit.textChanged.connect(self._on_settings_changed)
        sr_layout.addWidget(QLabel("替换:"), 1, 0)
        sr_layout.addWidget(self._replace_edit, 1, 1)

        check_row = QHBoxLayout()
        self._regex_check = QCheckBox("正则表达式")
        self._regex_check.stateChanged.connect(self._on_settings_changed)
        check_row.addWidget(self._regex_check)

        self._ignore_case_check = QCheckBox("忽略大小写")
        self._ignore_case_check.stateChanged.connect(self._on_settings_changed)
        check_row.addWidget(self._ignore_case_check)
        check_row.addStretch()
        sr_layout.addLayout(check_row, 2, 0, 1, 2)

        case_row = QHBoxLayout()
        case_row.addWidget(QLabel("大小写:"))
        self._case_combo = QComboBox()
        self._case_combo.addItems([
            "无变化", "小写", "大写", "标题格式", "句子格式"
        ])
        self._case_combo.currentIndexChanged.connect(self._on_settings_changed)
        case_row.addWidget(self._case_combo)
        case_row.addStretch()
        sr_layout.addLayout(case_row, 3, 0, 1, 2)

        options_layout.addWidget(sr_group)
        layout.addLayout(options_layout)

        # === 预览表格 ===
        self._preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(self._preview_group)

        self._preview_table = QTableWidget()
        self._preview_table.setColumnCount(3)
        self._preview_table.setHorizontalHeaderLabels(["原始", "新名称", "状态"])
        self._preview_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._preview_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._preview_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self._preview_table.setAlternatingRowColors(True)
        preview_layout.addWidget(self._preview_table)

        layout.addWidget(self._preview_group, stretch=1)

    def _setup_history_tab(self, parent):
        """设置历史记录标签页。"""
        layout = QVBoxLayout(parent)

        self._history_text = QTextEdit()
        self._history_text.setReadOnly(True)
        self._history_text.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._history_text)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("清空历史记录")
        btn_clear.setFixedSize(120, 30)
        btn_clear.clicked.connect(self._on_clear_history)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_history()

    # === 前缀相关方法 ===

    def _refresh_prefix_combo(self):
        """刷新前缀组合框。"""
        current = self._prefix_combo.currentText()
        self._prefix_combo.clear()
        self._prefix_combo.addItem("")
        for prefix in self._storage.get_prefixes():
            self._prefix_combo.addItem(prefix)
        idx = self._prefix_combo.findText(current)
        if idx >= 0:
            self._prefix_combo.setCurrentIndex(idx)

    def _on_prefix_changed(self, text):
        """前缀更改事件处理器。"""
        pass

    def _on_add_prefix(self):
        """添加前缀预设。"""
        text = self._prefix_combo.currentText().strip()
        if text:
            if self._storage.add_prefix(text):
                self._refresh_prefix_combo()
                self._prefix_combo.setCurrentText(text)

    def _on_remove_prefix(self):
        """移除前缀预设。"""
        text = self._prefix_combo.currentText().strip()
        if text and self._storage.remove_prefix(text):
            self._refresh_prefix_combo()

    def _on_apply_prefix(self):
        """应用选中的前缀到模式。"""
        prefix = self._prefix_combo.currentText().strip()
        if not prefix:
            QMessageBox.information(self, "无前缀",
                                    "请选择或输入一个前缀。")
            return

        self._pattern_edit.setText(f"{prefix} [N]")
        self._update_preview()

    # === 设置相关方法 ===

    def _load_settings(self):
        """加载保存的设置。"""
        s = self._storage.settings
        self._pattern_edit.setText(s.get("pattern", ""))
        self._search_edit.setText(s.get("search", ""))
        self._replace_edit.setText(s.get("replace", ""))
        self._regex_check.setChecked(s.get("use_regex", False))
        self._ignore_case_check.setChecked(s.get("ignore_case", False))
        self._case_combo.setCurrentIndex(s.get("case_index", 0))
        self._counter_start.setValue(s.get("counter_start", 1))
        self._counter_step.setValue(s.get("counter_step", 1))
        self._counter_digits.setValue(s.get("counter_digits", 2))
        self._replace_prefix_check.setChecked(s.get("replace_prefix", True))

    def _save_settings(self):
        """保存当前设置。"""
        self._storage.save_settings({
            "pattern": self._pattern_edit.text(),
            "search": self._search_edit.text(),
            "replace": self._replace_edit.text(),
            "use_regex": self._regex_check.isChecked(),
            "ignore_case": self._ignore_case_check.isChecked(),
            "case_index": self._case_combo.currentIndex(),
            "counter_start": self._counter_start.value(),
            "counter_step": self._counter_step.value(),
            "counter_digits": self._counter_digits.value(),
            "replace_prefix": self._replace_prefix_check.isChecked()
        })

    def _on_settings_changed(self):
        """设置更改事件处理器。"""
        self._update_preview()

    # === 预览相关方法 ===

    def _update_preview(self):
        """更新预览表格。"""
        self._preview_data = []
        self._preview_table.setRowCount(0)

        pattern = self._pattern_edit.text().strip()
        search = self._search_edit.text()
        replace = self._replace_edit.text()
        use_regex = self._regex_check.isChecked()
        ignore_case = self._ignore_case_check.isChecked()
        
        # 大小写转换模式
        case_modes = ["none", "lower", "upper", "title", "capitalize"]
        case_mode = case_modes[self._case_combo.currentIndex()]
        replace_prefix = self._replace_prefix_check.isChecked()

        # 重置计数器
        self._engine.reset_counter(
            self._counter_start.value(),
            self._counter_step.value(),
            self._counter_digits.value()
        )

        new_names_count = {}
        self._preview_table.setRowCount(len(self._mod_list))
        errors = 0
        changes = 0

        for row, (mod_name, sep_name) in enumerate(self._mod_list):
            error = ""
            new_name = mod_name
            working_name = mod_name

            # 如果需要替换前缀且有模式，则移除现有前缀
            if replace_prefix and pattern:
                if pattern.startswith("[") and "]" in pattern:
                    working_name = self._engine.strip_prefix(mod_name)

            # 应用重命名模式
            if pattern:
                expanded_pattern = self._engine.expand_prefix_tags(pattern, sep_name)
                new_name = self._engine.apply_pattern(
                    working_name, expanded_pattern, sep_name)
            else:
                new_name = working_name

            # 应用搜索替换
            new_name = self._engine.apply_search_replace(
                new_name, search, replace, use_regex, ignore_case)
            
            # 应用大小写转换
            new_name = self._engine.apply_case(new_name, case_mode)
            
            # 清理名称
            new_name = self._engine.sanitize_name(new_name)

            # 如果模式中包含计数器标签，则递增计数器
            if "[C" in pattern or "{N" in pattern:
                self._engine.increment_counter()

            # 检查错误
            if not new_name:
                error = "名称为空"
                errors += 1
            elif new_name != mod_name:
                # 检查重复名称
                new_names_count[new_name] = new_names_count.get(new_name, 0) + 1
                if new_names_count[new_name] > 1:
                    error = "重复名称"
                    errors += 1
                elif os.path.exists(os.path.join(self._mods_path, new_name)):
                    # 检查目标名称是否已存在
                    if new_name.lower() != mod_name.lower():
                        error = "名称已存在"
                        errors += 1
                    else:
                        changes += 1
                else:
                    changes += 1

            # 保存预览数据
            self._preview_data.append((mod_name, new_name, error))

            # 创建表格项
            item_old = QTableWidgetItem(mod_name)
            item_new = QTableWidgetItem(new_name)
            item_status = QTableWidgetItem(
                error if error else ("已更改" if new_name != mod_name else "—"))

            # 设置颜色
            if error:
                item_new.setForeground(QBrush(QColor("#e74c3c")))  # 红色
                item_status.setForeground(QBrush(QColor("#e74c3c")))
            elif new_name != mod_name:
                item_new.setForeground(QBrush(QColor("#2ecc71")))  # 绿色
                item_status.setForeground(QBrush(QColor("#2ecc71")))
            else:
                item_new.setForeground(QBrush(QColor("#7f8c8d")))  # 灰色
                item_status.setForeground(QBrush(QColor("#7f8c8d")))

            self._preview_table.setItem(row, 0, item_old)
            self._preview_table.setItem(row, 1, item_new)
            self._preview_table.setItem(row, 2, item_status)

        # 更新预览组标题
        self._preview_group.setTitle(
            f"预览 — {len(self._mod_list)} 个模组, {changes} 个更改"
            + (f", {errors} 个错误" if errors else "")
        )

        # 更新执行按钮状态
        self._btn_execute.setEnabled(changes > 0 and errors == 0)

    def _update_buttons(self):
        """更新按钮状态。"""
        history = self._storage.get_history()
        self._btn_undo.setEnabled(len(history) > 0)

    # === 历史记录相关方法 ===

    def _refresh_history(self):
        """刷新历史记录显示。"""
        history = self._storage.get_history()
        lines = []

        if not history:
            lines.append("尚未记录重命名操作。")
        else:
            for i, entry in enumerate(history, 1):
                ts = entry.get("timestamp", "?")
                renames = entry.get("renames", [])
                lines.append(f"{'─' * 50}")
                lines.append(f"#{i}  {ts}  ({len(renames)} 个项目)")
                for old, new in renames[:10]:
                    lines.append(f"  {old}")
                    lines.append(f"    → {new}")
                if len(renames) > 10:
                    lines.append(f"  ... 还有 {len(renames) - 10} 个")

        self._history_text.setText("\n".join(lines))
        self._update_buttons()

    def _on_clear_history(self):
        """清空历史记录。"""
        reply = QMessageBox.question(
            self, "清空历史记录",
            "清空所有重命名历史？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._storage.clear_history()
            self._refresh_history()

    # === 操作相关方法 ===

    def _on_execute(self):
        """执行重命名操作。"""
        # 获取需要更改的项目
        changes = [(old, new) for old, new, err in self._preview_data
                   if old != new and not err]

        if not changes:
            return

        reply = QMessageBox.question(
            self, "确认重命名",
            f"重命名 {len(changes)} 个模组？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 保存设置
        self._save_settings()

        success = []
        failed = []

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            for old_name, new_name in changes:
                ok, err = self._rename_callback(old_name, new_name)
                if ok:
                    success.append((old_name, new_name))
                else:
                    failed.append((old_name, err))
        finally:
            QApplication.restoreOverrideCursor()

        # 添加到历史记录
        if success:
            self._storage.add_history({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "renames": success
            })

        self._refresh_history()

        if failed:
            msg = f"重命名 {len(success)} 个, 失败 {len(failed)} 个:\n"
            for name, err in failed[:5]:
                msg += f"\n• {name}: {err}"
            QMessageBox.warning(self, "部分成功", msg)
        else:
            QMessageBox.information(self, "完成",
                                    f"已重命名 {len(success)} 个模组。")
            self.accept()

    def _on_undo(self):
        """撤销上次重命名操作。"""
        history = self._storage.get_history()
        if not history:
            return

        last = history[0]
        renames = last.get("renames", [])

        reply = QMessageBox.question(
            self, "确认撤销",
            f"撤销 {len(renames)} 个重命名？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        success = 0
        failed = []

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            for old_name, new_name in renames:
                new_path = os.path.join(self._mods_path, new_name)
                old_path = os.path.join(self._mods_path, old_name)

                # 检查新名称对应的文件夹是否存在
                if not os.path.exists(new_path):
                    failed.append((new_name, "未找到"))
                    continue
                # 检查旧名称对应的文件夹是否已存在
                if os.path.exists(old_path) and old_name.lower() != new_name.lower():
                    failed.append((new_name, f"'{old_name}' 已存在"))
                    continue

                ok, err = self._rename_callback(new_name, old_name)
                if ok:
                    success += 1
                else:
                    failed.append((new_name, err))
        finally:
            QApplication.restoreOverrideCursor()

        self._storage.remove_last_history()
        self._refresh_history()

        if failed:
            msg = f"恢复 {success} 个, 失败 {len(failed)} 个:\n"
            for name, err in failed[:5]:
                msg += f"\n• {name}: {err}"
            QMessageBox.warning(self, "部分撤销", msg)
        else:
            QMessageBox.information(self, "撤销完成",
                                    f"已恢复 {success} 个名称。")


# ============================================================
#  Key Filter - 键盘过滤器
# ============================================================

class _KeyFilter(QObject):
    """用于处理 Ctrl+Shift+R 快捷键的过滤器。"""

    def __init__(self, plugin):
        """
        初始化键盘过滤器
        
        Args:
            plugin: 插件实例
        """
        super().__init__()
        self._plugin = plugin

    def eventFilter(self, obj, event):
        """
        事件过滤器
        
        Args:
            obj: 事件对象
            event: 事件
            
        Returns:
            bool: 是否处理了事件
        """
        if event.type() != QEvent.Type.KeyPress:
            return False

        mods = event.modifiers()
        if not (mods & Qt.KeyboardModifier.ControlModifier):
            return False
        if not (mods & Qt.KeyboardModifier.ShiftModifier):
            return False

        if event.key() == Qt.Key.Key_R:
            # 延迟执行，避免与UI更新冲突
            QTimer.singleShot(0, self._plugin.on_rename)
            return True

        return False


# ============================================================
#  Main Plugin - 主插件类
# ============================================================

class ModRenamer(mobase.IPlugin):
    """MO2插件，用于批量重命名模组。快捷键：Ctrl+Shift+R"""

    def __init__(self):
        """初始化插件。"""
        super().__init__()
        self._organizer = None
        self._modList = None
        self._mod_view = None  # 专门存储模组列表视图
        self._filter = None
        self._storage = None

    def __del__(self):
        """析构函数，清理事件过滤器。"""
        if self._mod_view and self._filter:
            try:
                self._mod_view.removeEventFilter(self._filter)
            except Exception:
                pass

    def name(self):
        """返回插件名称。"""
        return "模组重命名器"

    def author(self):
        """返回作者名称。"""
        return "User"

    def version(self):
        """返回版本信息。"""
        return mobase.VersionInfo(2, 3, 1)  # 版本增加以反映修复

    def description(self):
        """返回插件描述。"""
        return (
            "使用模式和前缀预设批量重命名模组。\n\n"
            "快捷键：Ctrl+Shift+R\n\n"
            "功能：\n"
            "• 前缀预设支持标签 ({SEP}, {N}, {DATE})\n"
            "• 基于模式的重命名\n"
            "• 搜索/替换支持正则表达式\n"
            "• 重复检测\n"
            "• 撤销支持\n"
            "• 修复分隔符选择问题"
        )

    def settings(self):
        """返回插件设置。"""
        return []

    def isActive(self):
        """检查插件是否激活。"""
        return True

    def init(self, organizer: mobase.IOrganizer):
        """
        初始化插件
        
        Args:
            organizer: MO2组织器对象
            
        Returns:
            bool: 初始化是否成功
        """
        self._organizer = organizer
        self._modList = organizer.modList()

        base_path = organizer.basePath()
        if not base_path:
            return False

        storage_file = os.path.join(base_path, "mod_renamer", "settings.json")
        self._storage = RenamerStorage(storage_file)

        self._filter = _KeyFilter(self)

        # 尝试安装事件过滤器
        try:
            organizer.onUserInterfaceInitialized(lambda w: self._install_filter())
        except Exception:
            QTimer.singleShot(3000, self._install_filter)

        return True

    def _install_filter(self):
        """安装键盘事件过滤器。"""
        QTimer.singleShot(500, self._install_filter_delayed)

    def _install_filter_delayed(self):
        """延迟安装过滤器以确保UI完全加载。"""
        # 尝试立即查找模组列表视图
        self._find_mod_list_view()
        
        # 如果找不到，设置定时器持续查找
        if not self._mod_view:
            QTimer.singleShot(1000, self._find_mod_list_view)
            QTimer.singleShot(2000, self._find_mod_list_view)
            QTimer.singleShot(5000, self._find_mod_list_view)

    def _find_mod_list_view(self):
        """查找模组列表视图。"""
        for widget in QApplication.allWidgets():
            if isinstance(widget, QTreeView) and widget.objectName() == "modList":
                self._mod_view = widget
                widget.installEventFilter(self._filter)
                log.info("已找到并安装模组列表视图过滤器")
                return
        
        # 如果还是找不到，尝试通过其他方式识别
        for widget in QApplication.allWidgets():
            if isinstance(widget, QTreeView):
                # 检查是否有model，以及model的列数是否符合模组列表特征
                model = widget.model()
                if model and model.columnCount() >= 3:  # 模组列表通常有3列以上
                    # 尝试获取第一行数据
                    if model.rowCount() > 0:
                        index = model.index(0, 0)
                        if index.isValid():
                            data = index.data(Qt.ItemDataRole.DisplayRole)
                            if data and isinstance(data, str):
                                # 如果第一行数据看起来像是模组名称
                                if any(keyword in data.lower() for keyword in 
                                      ['mod', 'separator', 'output', '_', '-', '[', '+']):
                                    self._mod_view = widget
                                    widget.installEventFilter(self._filter)
                                    log.info("已通过特征找到并安装模组列表视图过滤器")
                                    return

    # === 辅助方法 ===

    def _is_separator(self, mod_name):
            """更可靠的分隔符检测方法"""
            if not mod_name:
                return False
            
            # 基于后缀的判断
            if mod_name.endswith("_separator"):
                return True
                
            # 基于装饰字符的判断
            symbols = ["---", "===", "###", "***", "+++", "~~~"]
            for symbol in symbols:
                if mod_name.startswith(symbol) or mod_name.endswith(symbol):
                    return True
            
            try:
                # 基于优先级的判断
                if self._modList:
                    prio = self._modList.priority(mod_name)
                    # MO2中分隔符的优先级为负值
                    if prio is not None and prio < 0:
                        return True
            except:
                pass
            
            return False

    def _get_mods_ordered(self):
        """
        获取按优先级排序的所有模组
        
        Returns:
            list: 排序后的模组列表
        """
        try:
            mods = list(self._modList.allMods())
            mods.sort(key=lambda m: self._modList.priority(m))
            return mods
        except Exception:
            # 如果排序失败，返回原始列表
            return list(self._modList.allMods())

    def _find_parent_separator(self, index, model):
            """基于Qt模型索引递归查找父分隔符"""
            try:
                if not index.isValid():
                    return ""
                    
                # 获取当前节点名称
                name = model.data(index, 0)
                
                # 如果是顶层节点，返回空字符串
                if not index.parent().isValid():
                    return ""
                    
                # 递归向上查找父分隔符
                current_parent = index.parent()
                while current_parent.isValid():
                    parent_name = model.data(current_parent, 0)
                    if parent_name and self._is_separator(parent_name):
                        return RenameEngine.clean_separator_name(parent_name)
                    current_parent = current_parent.parent()
                    
                return ""
            except Exception as e:
                log.error(f"查找父分隔符时出错: {e}")
                return ""

    def _expand_selection(self, selected):
        """
        扩展选择：如果选择了分隔符，包含其中的所有模组
        
        Args:
            selected: 已选择的模组列表
            
        Returns:
            list: 扩展后的模组列表
        """
        if not selected:
            return []

        all_mods = self._get_mods_ordered()
        result = []
        seen = set()

        # 获取所有分隔符的位置索引
        sep_indices = [i for i, m in enumerate(all_mods) if self._is_separator(m)]

        for name in selected:
            if name in seen:
                continue

            if self._is_separator(name):
                # 如果选择的是分隔符，获取其中的所有模组
                try:
                    sep_idx = all_mods.index(name)
                except ValueError:
                    continue

                # 找到下一个分隔符或列表末尾
                next_sep = len(all_mods)
                for idx in sep_indices:
                    if idx > sep_idx:
                        next_sep = idx
                        break

                # 添加分隔符之间的所有非分隔符模组
                for i in range(sep_idx + 1, next_sep):
                    mod = all_mods[i]
                    if mod not in seen and not self._is_separator(mod):
                        seen.add(mod)
                        result.append(mod)
                
                # 即使分隔符下没有模组也添加它本身（以便重命名分隔符）
                if name not in seen:
                    seen.add(name)
                    result.append(name)
            else:
                # 如果选择的是普通模组，直接添加
                seen.add(name)
                result.append(name)

        return result

    def _is_valid_separator(self, mod_name):
            """检查是否为有效的分隔符"""
            try:
                pri = self._modList.priority(mod_name)
                return pri is not None and pri < 0
            except Exception:
                return False

    def _get_separator_children(self, index, model):
        """按显示顺序递归获取分隔符下的所有非分隔符子模组"""
        try:
            if not index.isValid():
                return []
                
            name = model.data(index, 0)
            if not name or not self._is_separator(name):
                return []
            
            # 按照Qt树视图中的显示顺序收集子项
            ordered_children = []
            row_count = model.rowCount(index)
            
            for row in range(row_count):
                child_index = model.index(row, 0, index)
                child_name = model.data(child_index, 0)
                
                if not child_name:
                    continue
                    
                # 如果是嵌套的分隔符，递归处理
                if self._is_separator(child_name):
                    # 递归获取嵌套分隔符的子模组
                    # 保持嵌套结构中的顺序
                    nested_children = self._get_separator_children(child_index, model)
                else:
                    # 普通模组直接添加到列表
                    nested_children = [child_name]
                
                # 按照原始顺序添加
                ordered_children.extend(nested_children)
                    
            return ordered_children  # 保持原始顺序
        except Exception as e:
            log.error(f"获取分隔符子模组时出错: {e}")
            return []
    
    def _get_selected_mods(self):
            """最终修复版：使用Qt模型索引的正确实现"""
            if not self._mod_view:
                log.warning("未找到模组列表视图")
                return []

            model = self._mod_view.model()
            selection_model = self._mod_view.selectionModel()
            
            if not model:
                log.error("模组列表模型未加载")
                return []
                
            if not selection_model:
                log.error("选择模型未初始化")
                return []

            selected_indexes = selection_model.selectedRows(0)
            if not selected_indexes:
                log.info("未选择任何模组")
                return []

            result = []
            processed_items = set()
            
            for index in selected_indexes:
                if not index.isValid():
                    continue
                    
                name = model.data(index, 0)
                if not name:
                    continue
                    
                # 避免重复处理同一项目
                if name in processed_items:
                    continue
                    
                processed_items.add(name)
                
                if self._is_separator(name):
                    # 处理分隔符：收集所有子模组
                    log.info(f"处理分隔符: {name}")
                    children = self._get_separator_children(index, model)
                    
                    if children:
                        cleaned_sep = RenameEngine.clean_separator_name(name)
                        log.info(f"分隔符 '{name}' 下找到 {len(children)} 个子模组")
                        
                        for child in children:
                            # 确保子模组不是分隔符
                            if not self._is_separator(child):
                                result.append((child, cleaned_sep))
                                log.debug(f"添加子模组: {child}")
                            else:
                                log.warning(f"意外发现嵌套分隔符作为子项: {child}")
                    else:
                        log.info(f"分隔符 '{name}' 下没有子模组")
                else:
                    # 处理普通模组：查找父分隔符
                    log.debug(f"处理普通模组: {name}")
                    separator_name = self._find_parent_separator(index, model)
                    result.append((name, separator_name))
                    log.debug(f"添加普通模组: {name} (父分隔符: {separator_name})")
                    
            return result

    def _rename_mod(self, old_name, new_name):
        """
        使用MO2 API重命名模组（保留状态和位置）
        
        Args:
            old_name: 旧名称
            new_name: 新名称
            
        Returns:
            tuple: (bool, str) 成功标志和错误信息
        """
        if old_name == new_name:
            return True, ""

        try:
            mod = self._modList.getMod(old_name)
            if not mod:
                return False, "模组未找到"

            new_mod = self._modList.renameMod(mod, new_name)

            if new_mod:
                return True, ""
            else:
                # 如果API调用失败，使用备用方法
                return self._rename_mod_fallback(old_name, new_name)

        except AttributeError:
            # 如果没有renameMod方法，使用备用方法
            return self._rename_mod_fallback(old_name, new_name)
        except Exception as e:
            return False, str(e)

    def _rename_mod_fallback(self, old_name, new_name):
        """
        备用方法：直接文件系统重命名（用于较老的MO2版本）
        
        Args:
            old_name: 旧名称
            new_name: 新名称
            
        Returns:
            tuple: (bool, str) 成功标志和错误信息
        """
        mods_path = self._organizer.modsPath()
        old_path = os.path.join(mods_path, old_name)
        new_path = os.path.join(mods_path, new_name)

        if not os.path.isdir(old_path):
            return False, "源文件夹不存在"

        if os.path.exists(new_path):
            # 处理大小写更改的情况
            if old_name.lower() == new_name.lower():
                tmp_name = f"_rename_tmp_{datetime.now().timestamp()}"
                tmp_path = os.path.join(mods_path, tmp_name)
                try:
                    os.rename(old_path, tmp_path)
                    os.rename(tmp_path, new_path)
                    self._refresh()
                    return True, ""
                except Exception as e:
                    # 尝试回滚
                    if os.path.exists(tmp_path) and not os.path.exists(old_path):
                        try:
                            os.rename(tmp_path, old_path)
                        except Exception:
                            pass
                    return False, str(e)
            return False, "目标名称已存在"

        try:
            os.rename(old_path, new_path)
            self._refresh()
            return True, ""
        except PermissionError:
            return False, "权限被拒绝（文件正在使用？）"
        except Exception as e:
            return False, str(e)

    def _refresh(self):
        """刷新MO2界面（带保存）。"""
        try:
            self._organizer.refresh(True)
        except TypeError:
            try:
                self._organizer.refresh()
            except Exception:
                pass
        except Exception:
            pass

    # === 主要操作方法 ===

    def on_rename(self):
        """打开重命名对话框。"""
        mods = self._get_selected_mods()

        if not mods:
            # 修复：现在检查是否选中了分隔符，即使没有展开也能处理
            if self._mod_view:
                sel = self._mod_view.selectionModel()
                if sel:
                    indexes = sel.selectedRows(0)
                    if indexes:
                        # 获取选中的名称
                        selected_names = [idx.data() for idx in indexes if idx.data()]
                        
                        # 检查是否全是分隔符
                        all_are_separators = all(
                            self._is_separator(name) for name in selected_names if name
                        )
                        
                        if all_are_separators and selected_names:
                            # 即使只选中了分隔符，也允许重命名它们
                            all_mods = self._get_mods_ordered()
                            result = []
                            for mod in selected_names:
                                sep = self._find_separator_for_mod(mod, all_mods)
                                # 清理分隔符名称
                                cleaned_sep = RenameEngine.clean_separator_name(sep)
                                result.append((mod, cleaned_sep))
                            
                            if result:
                                dialog = RenameDialog(
                                    result,
                                    self._storage,
                                    self._rename_mod,
                                    self._organizer.modsPath(),
                                    self._mod_view
                                )
                                dialog.exec()
                                self._refresh()
                                return
                        
                        # 或者选中了混合项目（分隔符+模组）
                        mixed_selection = any(
                            self._is_separator(name) or not self._is_separator(name) 
                            for name in selected_names if name
                        )
                        
                        if mixed_selection:
                            # 扩展选择并处理
                            expanded = self._expand_selection(selected_names)
                            if expanded:
                                all_mods = self._get_mods_ordered()
                                result = []
                                for mod in expanded:
                                    sep = self._find_separator_for_mod(mod, all_mods)
                                    cleaned_sep = RenameEngine.clean_separator_name(sep)
                                    result.append((mod, cleaned_sep))
                                
                                if result:
                                    dialog = RenameDialog(
                                        result,
                                        self._storage,
                                        self._rename_mod,
                                        self._organizer.modsPath(),
                                        self._mod_view
                                    )
                                    dialog.exec()
                                    self._refresh()
                                    return

            # 显示一般的选择提示
            QMessageBox.information(
                self._mod_view, "未选择模组",
                "请先在模组列表中选择模组。\n"
                "选择分隔符将包含其中的所有模组。"
            )
            return

        dialog = RenameDialog(
            mods,
            self._storage,
            self._rename_mod,
            self._organizer.modsPath(),
            self._mod_view
        )
        dialog.exec()
        self._refresh()


def createPlugin():
    """创建插件实例的工厂函数。"""
    return ModRenamer()