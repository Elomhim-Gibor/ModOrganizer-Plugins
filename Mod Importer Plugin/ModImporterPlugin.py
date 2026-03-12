# Written by MaskPlague (modified by Alhimik)
# MO2 Mod Importer - Import mods from another MO2 instance with drag & drop positioning

import mobase
import os
import shutil
import configparser
import json
import time
from datetime import datetime

try:
    from PyQt6.QtCore import QCoreApplication, Qt, QMimeData, pyqtSignal, QSettings, QPoint, QRect
    from PyQt6.QtGui import QIcon, QDrag, QColor, QPainter, QPen, QPixmap, QBrush
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QComboBox,
        QListWidget, QLabel, QListWidgetItem, QProgressDialog, QMessageBox, QLineEdit,
        QSplitter, QWidget, QCheckBox, QInputDialog, QColorDialog, QStyle, QAbstractItemView,
        QMenu, QApplication  # 新增 QMenu 和 QApplication
    )
    PYQT_VERSION = 6
except ImportError:
    from PyQt5.QtCore import QCoreApplication, Qt, QMimeData, pyqtSignal, QSettings, QPoint, QRect
    from PyQt5.QtGui import QIcon, QDrag, QColor, QPainter, QPen, QPixmap, QBrush
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QComboBox,
        QListWidget, QLabel, QListWidgetItem, QProgressDialog, QMessageBox, QLineEdit,
        QSplitter, QWidget, QCheckBox, QInputDialog, QColorDialog, QStyle, QAbstractItemView,
        QMenu, QApplication  # 新增 QMenu 和 QApplication
    )
    PYQT_VERSION = 5

# Custom MIME type for internal drag operations
MIME_TYPE_INTERNAL = "application/x-mo2-mod-importer-internal"
MIME_TYPE_EXTERNAL = "application/x-mo2-mod-importer-external"


class DragListWidget(QListWidget):
    """支持从源列表拖拽项目的自定义列表控件，增加右键复制功能"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.drag_start_position = None
        # 允许上下文菜单
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._showContextMenu)
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self.drag_start_position:
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < 10:
            return
        selected_items = self.selectedItems()
        if not selected_items:
            return
        mod_data_list = []
        for item in selected_items:
            mod_data = item.data(Qt.ItemDataRole.UserRole)
            if mod_data and not mod_data.get('separator') and mod_data.get('exists'):
                mod_data_list.append(mod_data)
        if not mod_data_list:
            return
        drag = QDrag(self)
        mime_data = QMimeData()
        data = json.dumps([{
            'name': mod['name'],
            'enabled': mod['enabled'],
            'exists': mod.get('exists', False)   # ← 加上 exists
        } for mod in mod_data_list])
        mime_data.setData(MIME_TYPE_EXTERNAL, data.encode('utf-8'))
        mime_data.setText(data)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)
    def _showContextMenu(self, pos):
        """显示右键菜单"""
        item = self.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        copy_action = menu.addAction("复制模组名称")
        action = menu.exec(self.mapToGlobal(pos))
        
        if action == copy_action:
            mod_data = item.data(Qt.ItemDataRole.UserRole)
            if mod_data and mod_data.get('name'):
                clipboard = QApplication.clipboard()
                clipboard.setText(mod_data['name'])
class DropListWidget(QListWidget):
    """接受拖放并显示插入位置的自定义列表控件，增加右键复制功能"""
    mods_dropped = pyqtSignal(list, int, bool)  # mod_data_list, insert_position, is_internal
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.drop_indicator_index = -1
        self.drag_start_position = None
        self.dragging_mods = []  # 存储当前正在拖动的新建模组数据
        self.setMouseTracking(True)
        self.viewport().setAcceptDrops(True)
        # 允许上下文菜单
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._showContextMenu)
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self.drag_start_position:
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < 10:
            return
        selected_items = self.selectedItems()
        if not selected_items:
            return
        new_mods = []
        for item in selected_items:
            text = item.text()
            if text.startswith("[NEW]"):
                parts = text.split('] ', 2)
                if len(parts) >= 3:
                    mod_name = parts[2]
                    enabled = '[✓]' in text
                    new_mods.append({'name': mod_name, 'enabled': enabled})
        if not new_mods:
            return
        self.dragging_mods = new_mods.copy()
        drag = QDrag(self)
        mime_data = QMimeData()
        data = json.dumps(new_mods)
        mime_data.setData(MIME_TYPE_INTERNAL, data.encode('utf-8'))
        mime_data.setText(data)
        drag.setMimeData(mime_data)
        result = drag.exec(Qt.DropAction.MoveAction)
        if result == Qt.DropAction.IgnoreAction:
            self.dragging_mods = []
    def _getDropIndex(self, pos):
        """根据鼠标位置计算放置索引，提高准确性"""
        if self.count() == 0:
            return 0
        # 如果鼠标不在任何项目上
        item = self.itemAt(pos)
        if item is None:
            # 如果在最后一个项目下方
            last_item = self.item(self.count() - 1)
            last_rect = self.visualItemRect(last_item)
            if pos.y() > last_rect.bottom():
                return self.count()
            # 如果在第一个项目上方
            first_item = self.item(0)
            first_rect = self.visualItemRect(first_item)
            if pos.y() < first_rect.top():
                return 0
            return self.count()
        # 鼠标在某个项目上：判断是在该项目上半部分还是下半部分
        item_rect = self.visualItemRect(item)
        item_index = self.row(item)
        item_middle = item_rect.top() + item_rect.height() // 2
        if pos.y() < item_middle:
            # 在上半部分 - 插入到该项目之前
            return item_index
        else:
            # 在下半部分 - 插入到该项目之后
            return item_index + 1
    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasFormat(MIME_TYPE_INTERNAL) or mime.hasFormat(MIME_TYPE_EXTERNAL) or mime.hasText():
            event.accept()
            self._updateDropIndicator(event)
        else:
            event.ignore()
    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasFormat(MIME_TYPE_INTERNAL) or mime.hasFormat(MIME_TYPE_EXTERNAL) or mime.hasText():
            event.accept()
            self._updateDropIndicator(event)
        else:
            event.ignore()
    def _updateDropIndicator(self, event):
        """更新放置指示器位置"""
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()
        new_index = self._getDropIndex(pos)
        if new_index != self.drop_indicator_index:
            self.drop_indicator_index = new_index
            self.viewport().update()
    def dragLeaveEvent(self, event):
        self.drop_indicator_index = -1
        self.viewport().update()
        event.accept()
    def paintEvent(self, event):
        """重写绘制事件以绘制放置指示器"""
        super().paintEvent(event)
        if self.drop_indicator_index >= 0:
            painter = QPainter(self.viewport())
            pen = QPen(QColor(0, 120, 215), 3)
            painter.setPen(pen)
            # 计算 Y 坐标位置
            if self.drop_indicator_index < self.count():
                item = self.item(self.drop_indicator_index)
                rect = self.visualItemRect(item)
                y = rect.top()
            else:
                # 在列表末尾
                if self.count() > 0:
                    item = self.item(self.count() - 1)
                    rect = self.visualItemRect(item)
                    y = rect.bottom()
                else:
                    y = 5  # 空列表时默认位置
            painter.drawLine(5, y, self.viewport().width() - 5, y)  # 绘制水平线
            # 绘制左侧三角形箭头
            painter.setBrush(QColor(0, 120, 215))
            painter.drawPolygon([
                QPoint(0, y - 5),
                QPoint(8, y),
                QPoint(0, y + 5)
            ])
            # 绘制右侧三角形箭头
            w = self.viewport().width()
            painter.drawPolygon([
                QPoint(w, y - 5),
                QPoint(w - 8, y),
                QPoint(w, y + 5)
            ])
            painter.end()
    def dropEvent(self, event):
        mime = event.mimeData()
        is_internal = mime.hasFormat(MIME_TYPE_INTERNAL)
        if mime.hasFormat(MIME_TYPE_INTERNAL) or mime.hasFormat(MIME_TYPE_EXTERNAL) or mime.hasText():
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            insert_row = self._getDropIndex(pos)
            try:
                if mime.hasFormat(MIME_TYPE_INTERNAL):
                    data = bytes(mime.data(MIME_TYPE_INTERNAL)).decode('utf-8')
                elif mime.hasFormat(MIME_TYPE_EXTERNAL):
                    data = bytes(mime.data(MIME_TYPE_EXTERNAL)).decode('utf-8')
                else:
                    data = mime.text()
                mod_data_list = json.loads(data)
                self.mods_dropped.emit(mod_data_list, insert_row, is_internal)
                event.accept()
                self.dragging_mods = []
            except Exception as e:
                print(f"Error parsing drop data: {e}")
                event.ignore()
        else:
            event.ignore()
        self.drop_indicator_index = -1
        self.viewport().update()
        
    def _showContextMenu(self, pos):
        """显示右键菜单"""
        item = self.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        copy_action = menu.addAction("复制模组名称")
        action = menu.exec(self.mapToGlobal(pos))
        
        if action == copy_action:
            mod = item.data(Qt.ItemDataRole.UserRole)
            if mod and mod.get('name'):
                clipboard = QApplication.clipboard()
                clipboard.setText(mod['name'])


class ModImporterDialog(QDialog):
    def __init__(self, parent, organizer):
        super().__init__(parent)
        self._organizer = organizer
        self.source_mo2_path = None
        self.profiles_path = None
        self.mods_path = None
        self.source_mod_data = []
        self.target_mod_data = []  # 目标 MO2 的原始模组列表
        self.display_list = []     # 显示在目标列表中的完整模组列表（含新导入项）
        self.new_mod_names = set() # 已添加到导入列表的模组名称集合
        # 源列表过滤状态
        self.source_unfiltered_selected_mod = None          # 未过滤时选中的模组
        self.source_filter_selected_mod_name = None         # 过滤时选中的模组
        self.source_last_filtered_state = False             # 上次过滤状态
        # 目标列表过滤相关变量
        self.target_unfiltered_selected_mod = None        # 未过滤时选中的模组名称
        self.target_filter_selected_mod_name = None       # 过滤时选中的模组名称
        self.target_last_filtered_state = False           # 上一次调用时的过滤状态

        # 导入模组的默认颜色
        self.selected_color = QColor(213, 174, 0)

        # 使用 QSettings 保存设置
        self.settings = QSettings("MO2Plugins", "ModImporter")

        # 加载已保存的设置
        self._loadSettings()

        # 设置窗口标题（保留原始英文注释）
        # self.setWindowTitle("Import Mods from Another MO2 (by) Alhimik")
        self.setWindowTitle("从另一个 MO2 实例导入模组（作者：Alhimik）")

        self.setMinimumWidth(1100)
        self.setMinimumHeight(750)
        self._setupUI()
        self._restoreGeometry()
        self._loadTargetModList()

        # 如果有保存的源路径，尝试加载它
        if self.source_mo2_path and os.path.exists(self.source_mo2_path):
            ini_path = os.path.join(self.source_mo2_path, "ModOrganizer.ini")
            if os.path.exists(ini_path):
                # self.path_label.setText(f"Source MO2 Path: {self.source_mo2_path}")
                self.path_label.setText(f"源 MO2 路径：{self.source_mo2_path}")
                self._parseINI(ini_path)
                self._loadProfiles()

                # 恢复上次选择的配置文件
                last_profile = self.settings.value("lastProfile", "")
                if last_profile:
                    idx = self.profile_combo.findText(last_profile)
                    if idx >= 0:
                        self.profile_combo.setCurrentIndex(idx)

    def _loadSettings(self):
        """从 QSettings 加载已保存的设置"""
        # 源路径
        self.source_mo2_path = self.settings.value("lastSourcePath", None)

        # 颜色
        saved_color = self.settings.value("noteColor", None)
        if saved_color:
            self.selected_color = QColor(saved_color)

        # 备份复选框状态
        self.backup_enabled = self.settings.value("createBackup", True, type=bool)

    def _saveSettings(self):
        """将当前设置保存到 QSettings"""
        if self.source_mo2_path:
            self.settings.setValue("lastSourcePath", self.source_mo2_path)
        self.settings.setValue("noteColor", self.selected_color.name())
        self.settings.setValue("createBackup", self.backup_checkbox.isChecked())

        if self.profile_combo.currentText():
            self.settings.setValue("lastProfile", self.profile_combo.currentText())

        # 保存窗口几何形状
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitterState", self.splitter.saveState())

    def _restoreGeometry(self):
        """从设置中恢复窗口几何形状"""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        splitter_state = self.settings.value("splitterState")
        if splitter_state:
            self.splitter.restoreState(splitter_state)

    def closeEvent(self, event):
        """关闭对话框时保存设置"""
        self._saveSettings()
        super().closeEvent(event)

    def reject(self):
        """拒绝对话框时（点击取消按钮）保存设置"""
        self._saveSettings()
        super().reject()

    def accept(self):
        """接受对话框时保存设置"""
        self._saveSettings()
        super().accept()

    def _setupUI(self):
        layout = QVBoxLayout()

        # 源 MO2 路径选择
        path_layout = QHBoxLayout()
        self.path_label = QLabel("源 MO2 路径：未选择")
        path_layout.addWidget(self.path_label, 1)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._selectSourceMO2)
        browse_btn.setFixedWidth(100)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 配置文件选择
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("配置文件："))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.currentIndexChanged.connect(self._loadSourceModList)
        profile_layout.addWidget(self.profile_combo, 1)
        layout.addLayout(profile_layout)

        # === 移除全局搜索框（原来的位置） ===

        # 说明标签
        instruction = QLabel("👉 从源列表拖拽模组到目标列表。蓝色线表示插入位置。使用按钮重新排序。")
        instruction.setStyleSheet("color: #0066cc; font-weight: bold; padding: 5px; background-color: #e6f0ff; border-radius: 3px;")
        layout.addWidget(instruction)

        # 选项行
        options_layout = QHBoxLayout()

        # 备份复选框
        self.backup_checkbox = QCheckBox("导入前创建备份")
        self.backup_checkbox.setChecked(self.backup_enabled)
        options_layout.addWidget(self.backup_checkbox)
        options_layout.addSpacing(20)

        # 导入模组的颜色选择器
        # options_layout.addWidget(QLabel("Import color:"))
        options_layout.addWidget(QLabel("导入颜色："))
        self.color_button = QPushButton()
        self.color_button.setFixedSize(60, 25)
        self._updateColorButton()
        self.color_button.setToolTip("MO2 中导入模组的备注颜色")
        self.color_button.clicked.connect(self._selectColor)
        options_layout.addWidget(self.color_button)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 两个并排的列表
        lists_layout = QHBoxLayout()

        # === 源列表（左侧）=== 
        source_widget = QWidget()
        source_layout = QVBoxLayout(source_widget)
        source_layout.setContentsMargins(0, 0, 0, 0)

        source_header = QHBoxLayout()
        source_header.addWidget(QLabel("👈 源模组（拖拽到目标）："))
        self.source_count_label = QLabel("")
        self.source_count_label.setStyleSheet("color: #666;")
        source_header.addWidget(self.source_count_label)
        source_header.addStretch()
        source_layout.addLayout(source_header)

        # === 源列表的过滤框 ===
        source_search_layout = QHBoxLayout()
        source_search_layout.addWidget(QLabel("过滤："))
        
        self.source_search_box = QLineEdit()
        self.source_search_box.setPlaceholderText("输入以过滤源模组...")
        self.source_search_box.textChanged.connect(self._filterSourceMods)
        source_search_layout.addWidget(self.source_search_box, 1)
        
        source_clear_filter_btn = QPushButton("×")
        source_clear_filter_btn.setToolTip("清除过滤")
        source_clear_filter_btn.clicked.connect(lambda: self.source_search_box.clear())
        source_clear_filter_btn.setFixedWidth(30)
        source_search_layout.addWidget(source_clear_filter_btn)
        
        source_layout.addLayout(source_search_layout)

        self.source_list = DragListWidget()
        self.source_list.setAlternatingRowColors(True)
        source_layout.addWidget(self.source_list, 1)       

        # === 目标列表（右侧）带控制按钮 ===
        target_widget = QWidget()
        target_layout = QVBoxLayout(target_widget)
        target_layout.setContentsMargins(0, 0, 0, 0)

        target_header = QHBoxLayout()
        target_header.addWidget(QLabel("👉 目标模组列表（绿色 = 新增）："))
        self.target_count_label = QLabel("")
        self.target_count_label.setStyleSheet("color: #666;")
        target_header.addWidget(self.target_count_label)
        target_header.addStretch()
        target_layout.addLayout(target_header)

        # === 目标列表的过滤框 ===
        target_search_layout = QHBoxLayout()
        target_search_layout.addWidget(QLabel("过滤："))
        
        self.target_search_box = QLineEdit()
        self.target_search_box.setPlaceholderText("输入以过滤目标模组...")
        self.target_search_box.textChanged.connect(self._filterTargetMods)
        target_search_layout.addWidget(self.target_search_box, 1)
        
        target_clear_filter_btn = QPushButton("×")
        target_clear_filter_btn.setToolTip("清除过滤")
        target_clear_filter_btn.clicked.connect(lambda: self.target_search_box.clear())
        target_clear_filter_btn.setFixedWidth(30)
        target_search_layout.addWidget(target_clear_filter_btn)
        
        target_layout.addLayout(target_search_layout)

        # 带侧边按钮的目标列表
        target_content = QHBoxLayout()
        self.target_list = DropListWidget()
        self.target_list.setAlternatingRowColors(True)
        self.target_list.mods_dropped.connect(self._onModsDropped)
        target_content.addWidget(self.target_list, 1)

        # 移动按钮
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()

        self.btn_move_top = QPushButton("↑↑")
        self.btn_move_top.setToolTip("移到顶部")
        self.btn_move_top.clicked.connect(self._moveToTop)
        self.btn_move_top.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_move_top)

        self.btn_move_up = QPushButton("↑")
        self.btn_move_up.setToolTip("上移")
        self.btn_move_up.clicked.connect(self._moveUp)
        self.btn_move_up.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_move_up)

        self.btn_move_down = QPushButton("↓")
        self.btn_move_down.setToolTip("下移")
        self.btn_move_down.clicked.connect(self._moveDown)
        self.btn_move_down.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_move_down)

        self.btn_move_bottom = QPushButton("↓↓")
        self.btn_move_bottom.setToolTip("移到底部")
        self.btn_move_bottom.clicked.connect(self._moveToBottom)
        self.btn_move_bottom.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_move_bottom)

        btn_layout.addSpacing(15)

        self.btn_toggle = QPushButton("✓/✗")
        self.btn_toggle.setToolTip("切换启用/禁用")
        self.btn_toggle.clicked.connect(self._toggleSelected)
        self.btn_toggle.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_toggle)

        # self.btn_remove = QPushButton("×")
        self.btn_remove = QPushButton("×")
        # self.btn_remove.setToolTip("Remove from import list")
        self.btn_remove.setToolTip("从导入列表中移除")
        self.btn_remove.clicked.connect(self._removeSelected)
        self.btn_remove.setFixedSize(35, 35)
        btn_layout.addWidget(self.btn_remove)

        btn_layout.addStretch()
        target_content.addLayout(btn_layout)
        target_layout.addLayout(target_content, 1)

        # 清除目标列表的按钮
        clear_btn = QPushButton("🧹 清除所有新模组")
        clear_btn.clicked.connect(self._clearPlacements)
        target_layout.addWidget(clear_btn, 0)

        # 添加到分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(source_widget)
        self.splitter.addWidget(target_widget)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        lists_layout.addWidget(self.splitter, 1)
        layout.addLayout(lists_layout, 1)

        # === 安全连接信号 ===
        # 源模组列表选择变化监听
        self.source_list.itemSelectionChanged.connect(self._onSourceSelectionChanged)

        # 目标列表选择变化监听
        self.target_list.itemSelectionChanged.connect(self._onTargetSelectionChanged)

        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight: bold; color: green; padding: 5px;")
        layout.addWidget(self.status_label)

        # 操作按钮
        button_layout = QHBoxLayout()

        restore_btn = QPushButton("🔄 恢复备份")
        restore_btn.clicked.connect(self._restoreBackup)
        button_layout.addWidget(restore_btn)

        button_layout.addStretch()

        import_btn = QPushButton("✅ 导入新模组")
        import_btn.clicked.connect(self._importMods)
        import_btn.setStyleSheet("font-weight: bold; padding: 10px 20px; background-color: #4CAF50; color: white;")
        button_layout.addWidget(import_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)


    def _updateColorButton(self):
        """更新颜色按钮外观"""
        self.color_button.setStyleSheet(
            f"background-color: {self.selected_color.name()}; border: 2px solid #666; border-radius: 3px;"
        )

    def _selectColor(self):
        """打开颜色选择对话框"""
        # color = QColorDialog.getColor(self.selected_color, self, "Select Note Color for Imported Mods")
        color = QColorDialog.getColor(self.selected_color, self, "为导入的模组选择备注颜色")
        if color.isValid():
            self.selected_color = color
            self._updateColorButton()

    def _setModNoteColor(self, mod_path, color):
        """在模组的 meta.ini 文件中设置备注颜色"""
        try:
            meta_ini_path = os.path.join(mod_path, "meta.ini")
            r, g, b = color.red(), color.green(), color.blue()

            # 转换 8 位 RGB 到 16 位
            r16, g16, b16 = r * 257, g * 257, b * 257

            # 格式化为十六进制字节（大端序）
            r_bytes = r16.to_bytes(2, 'big')
            g_bytes = g16.to_bytes(2, 'big')
            b_bytes = b16.to_bytes(2, 'big')

            # 创建颜色字符串
            color_str = f"@Variant(\\0\\0\\0\\x43\\x1\\xff\\xff"
            color_str += f"\\x{r_bytes[0]:02x}\\x{r_bytes[1]:02x}"
            color_str += f"\\x{g_bytes[0]:02x}\\x{g_bytes[1]:02x}"
            color_str += f"\\x{b_bytes[0]:02x}\\x{b_bytes[1]:02x}"
            color_str += "\\0\\0)"

            config = configparser.ConfigParser()
            if os.path.exists(meta_ini_path):
                config.read(meta_ini_path, encoding='utf-8')

            if not config.has_section('General'):
                config.add_section('General')

            config.set('General', 'color', color_str)

            with open(meta_ini_path, 'w', encoding='utf-8') as f:
                config.write(f, space_around_delimiters=False)

            return True
        except Exception as e:
            print(f"Error setting note color for {mod_path}: {e}")
            return False

    def _selectSourceMO2(self):
        """选择源 MO2 目录"""
        start_path = self.source_mo2_path if self.source_mo2_path else ""
        # path = QFileDialog.getExistingDirectory(self, "Select Source MO2 Directory", start_path, QFileDialog.Option.ShowDirsOnly)
        path = QFileDialog.getExistingDirectory(self, "选择源 MO2 目录", start_path, QFileDialog.Option.ShowDirsOnly)
        if path:
            ini_path = os.path.join(path, "ModOrganizer.ini")
            if not os.path.exists(ini_path):
                # QMessageBox.warning(self, "Error", "ModOrganizer.ini not found in selected directory!")
                QMessageBox.warning(self, "错误", "所选目录中未找到 ModOrganizer.ini！")
                return

            self.source_mo2_path = path
            # self.path_label.setText(f"Source MO2 Path: {path}")
            self.path_label.setText(f"源 MO2 路径：{path}")
            self._parseINI(ini_path)
            self._loadProfiles()

    def _parseINI(self, ini_path):
        """解析 ModOrganizer.ini 以获取路径"""
        config = configparser.ConfigParser()
        config.read(ini_path, encoding='utf-8')
        base_dir = self.source_mo2_path

        try:
            if config.has_option('Settings', 'base_directory'):
                custom_base = config.get('Settings', 'base_directory')
                if custom_base and custom_base != '.':
                    base_dir = custom_base if os.path.isabs(custom_base) else os.path.join(self.source_mo2_path, custom_base)
        except Exception:
            pass

        # 获取配置文件目录
        if config.has_option('Settings', 'profiles_directory'):
            profiles_dir = config.get('Settings', 'profiles_directory')
            if profiles_dir and profiles_dir != '.':
                self.profiles_path = profiles_dir if os.path.isabs(profiles_dir) else os.path.join(base_dir, profiles_dir)
            else:
                self.profiles_path = os.path.join(base_dir, "profiles")
        else:
            self.profiles_path = os.path.join(base_dir, "profiles")

        # 获取模组目录
        if config.has_option('Settings', 'mod_directory'):
            mods_dir = config.get('Settings', 'mod_directory')
            if mods_dir and mods_dir != '.':
                self.mods_path = mods_dir if os.path.isabs(mods_dir) else os.path.join(base_dir, mods_dir)
            else:
                self.mods_path = os.path.join(base_dir, "mods")
        else:
            self.mods_path = os.path.join(base_dir, "mods")

    def _loadProfiles(self):
        """加载可用的配置文件"""
        self.profile_combo.clear()
        if not os.path.exists(self.profiles_path):
            # QMessageBox.warning(self, "Error", f"Profiles directory not found: {self.profiles_path}")
            QMessageBox.warning(self, "错误", f"未找到配置文件目录：{self.profiles_path}")
            return

        profiles = []
        for item in os.listdir(self.profiles_path):
            profile_path = os.path.join(self.profiles_path, item)
            if os.path.isdir(profile_path):
                modlist_path = os.path.join(profile_path, "modlist.txt")
                if os.path.exists(modlist_path):
                    profiles.append(item)

        if not profiles:
            # QMessageBox.warning(self, "Error", "No valid profiles found!")
            QMessageBox.warning(self, "错误", "未找到有效的配置文件！")
            return

        self.profile_combo.addItems(sorted(profiles))

    def _loadSourceModList(self):
        """从选定的源配置文件加载模组列表"""
        self.source_list.clear()
        self.source_mod_data = []

        if self.profile_combo.currentText() == "":
            return

        profile_name = self.profile_combo.currentText()
        modlist_path = os.path.join(self.profiles_path, profile_name, "modlist.txt")
        if not os.path.exists(modlist_path):
            return

        with open(modlist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 反转顺序以便在 UI 中正确显示（最上面的模组最先加载）
        lines = list(reversed(lines))

        for line in lines:
            line = line.strip()
            if not line:
                continue

            is_enabled = False
            mod_name = line

            if line.startswith('+'):
                is_enabled = True
                mod_name = line[1:]
            elif line.startswith('-'):
                mod_name = line[1:]
            elif line.startswith('*'):
                mod_name = line[1:]

            is_separator = mod_name.endswith('_separator') or line.startswith('*')

            mod_exists = False
            if not is_separator:
                mod_path = os.path.join(self.mods_path, mod_name)
                mod_exists = os.path.exists(mod_path) and os.path.isdir(mod_path)

            self.source_mod_data.append({
                'name': mod_name,
                'enabled': is_enabled,
                'separator': is_separator,
                'exists': mod_exists,
                'original_line': line
            })

        self._displaySourceMods()

    def _displaySourceMods(self):
        """在列表控件中显示源模组"""
        self.source_list.clear()
        available_count = 0

        for mod in self.source_mod_data:
            if mod['separator']:
                # item = QListWidgetItem(f"──── {mod['name']} ────")
                item = QListWidgetItem(f"──── {mod['name']} ────")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor(100, 100, 100))
                item.setBackground(QColor(240, 240, 240))
            else:
                if not mod['exists']:
                    # display_text = f"⚠️ [MISSING] {mod['name']}"
                    display_text = f"⚠️ [缺失] {mod['name']}"
                    item = QListWidgetItem(display_text)
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setForeground(QColor(180, 0, 0))
                elif mod['name'] in self.new_mod_names:
                    # display_text = f"⚠️ [ADDED] {mod['name']}"
                    display_text = f"⚠️ [已添加] {mod['name']}"
                    item = QListWidgetItem(display_text)
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setForeground(QColor(100, 100, 100))
                    item.setBackground(QColor(230, 255, 230))
                else:
                    prefix = "✓" if mod['enabled'] else "✗"
                    display_text = f"{prefix} {mod['name']}"
                    item = QListWidgetItem(display_text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    available_count += 1

                item.setData(Qt.ItemDataRole.UserRole, mod)

            self.source_list.addItem(item)

        # self.source_count_label.setText(f"({available_count} available)")
        self.source_count_label.setText(f"（{available_count} 个可用）")

    def _loadTargetModList(self):
        """加载当前目标 MO2 的模组列表"""
        self.target_mod_data = []
        self.display_list = []
        self.new_mod_names = set()

        profiles_path = self._organizer.profilePath()
        modlist_path = os.path.join(profiles_path, "modlist.txt")
        if not os.path.exists(modlist_path):
            # self.target_list.addItem("No modlist.txt found in current profile")
            self.target_list.addItem("当前配置文件中未找到 modlist.txt")
            return

        with open(modlist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 反转顺序以便在 UI 中正确显示
        lines = list(reversed(lines))

        for line in lines:
            line = line.strip()
            if not line:
                continue

            is_enabled = False
            mod_name = line

            if line.startswith('+'):
                is_enabled = True
                mod_name = line[1:]
            elif line.startswith('-'):
                mod_name = line[1:]
            elif line.startswith('*'):
                mod_name = line[1:]

            is_separator = mod_name.endswith('_separator') or line.startswith('*')

            mod_entry = {
                'name': mod_name,
                'enabled': is_enabled,
                'separator': is_separator,
                'is_new': False,
                'original_line': line
            }

            self.target_mod_data.append(mod_entry)
            self.display_list.append(mod_entry.copy())

        self._refreshTargetDisplay()

    def _refreshTargetDisplay(self):
        """根据 display_list 刷新目标列表显示"""
        self.target_list.clear()
        new_count = 0

        for mod in self.display_list:
            if mod['separator']:
                item = QListWidgetItem(f"──── {mod['name']} ────")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor(100, 100, 100))
                item.setBackground(QColor(240, 240, 240))
            elif mod.get('is_new', False):
                prefix = "✓" if mod['enabled'] else "✗"
                item = QListWidgetItem(f"[新增] {prefix} {mod['name']}")
                item.setForeground(QColor(0, 140, 0))
                item.setBackground(QColor(230, 255, 230))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                # 关键修复：设置可查询的 UserRole 数据
                item.setData(Qt.ItemDataRole.UserRole, mod)
                new_count += 1
            else:
                prefix = "✓" if mod.get('enabled') else "✗"
                item = QListWidgetItem(f" {prefix} {mod['name']}")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                # 关键修复：设置可查询的 UserRole 数据
                item.setData(Qt.ItemDataRole.UserRole, mod)

            self.target_list.addItem(item)

        self.target_count_label.setText(f"（共 {len(self.display_list)} 项，{new_count} 个新增）")
        self._updateStatus()


    def _onModsDropped(self, mod_data_list, insert_position, is_internal):
        """处理拖放到目标列表的模组"""
        if is_internal:
            # 内部拖动 - 重新排列 [NEW] 项
            mod_names_to_move = [m['name'] for m in mod_data_list]

            # 收集要移动的模组
            mods_to_move = []
            original_indices = []
            for i, mod in enumerate(self.display_list):
                if mod.get('is_new') and mod['name'] in mod_names_to_move:
                    mods_to_move.append(mod.copy())
                    original_indices.append(i)

            # 调整插入位置（考虑已删除的项）
            adjusted_position = insert_position
            for idx in original_indices:
                if idx < insert_position:
                    adjusted_position -= 1

            # 删除原位置的项
            for i in reversed(original_indices):
                del self.display_list[i]

            # 插入到新位置
            actual_insert = min(adjusted_position, len(self.display_list))
            actual_insert = max(0, actual_insert)
            for mod in mods_to_move:
                self.display_list.insert(actual_insert, mod)
                actual_insert += 1
        else:  # 外部拖动 - 添加新模组
            mods_to_add = []
            valid_mods = []
            for mod_data in mod_data_list:
                # === 新增：跳过不存在的模组（即使数据中没传 exists，默认为 True）
                # 但更安全的方式是：只允许来自 source_mod_data 且 exists=True 的模组
                # 我们可以通过 name 反查 source_mod_data
                found_mod = None
                for sm in self.source_mod_data:
                    if sm['name'] == mod_data['name']:
                        found_mod = sm
                        break
                if found_mod is None or not found_mod.get('exists', False):
                    continue  # 跳过缺失或未知模组

                if mod_data['name'] not in self.new_mod_names:
                    mods_to_add.append({
                        'name': mod_data['name'],
                        'enabled': mod_data['enabled'],
                        'separator': False,
                        'is_new': True
                    })
                    valid_mods.append(mod_data['name'])

            if not mods_to_add:
                QMessageBox.information(self, "重复模组", "所选模组已存在于导入列表中。")
                return

            # 只有确认要添加的模组才加入 new_mod_names
            for name in valid_mods:
                self.new_mod_names.add(name)

            # 插入到指定位置
            actual_insert = min(insert_position, len(self.display_list))
            actual_insert = max(0, actual_insert)
            for mod in reversed(mods_to_add):  # 保持拖拽顺序
                self.display_list.insert(actual_insert, mod)

            self._refreshTargetDisplay()

    def _onSourceSelectionChanged(self):
        """源模组列表选择变化监听"""
        if not self.source_list:  # 确保列表已初始化
            return
            
        selected_items = self.source_list.selectedItems()
        if not selected_items:
            return
            
        selected_item = selected_items[0]
        mod_data = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 只记录有效的模组项目（非分隔符且存在的）
        if mod_data and not mod_data.get('separator') and mod_data.get('exists'):
            if self.source_last_filtered_state:
                # 过滤状态下选中的项目
                self.source_filter_selected_mod_name = mod_data['name']
            else:
                # 非过滤状态下选中的项目
                self.source_unfiltered_selected_mod = mod_data['name']


    def _filterSourceMods(self):
        """根据搜索框内容过滤源模组列表"""
        filter_text = self.source_search_box.text().lower().strip()
        is_filtering = bool(filter_text)
        was_filtering = self.source_last_filtered_state
        
        # === 第1步：在过滤状态改变前捕获当前选中项 ===
        if is_filtering and not was_filtering:
            # 即将进入过滤状态，记录当前的未过滤选中项
            selected_items = self.source_list.selectedItems()
            if selected_items and len(selected_items) > 0:
                selected_item = selected_items[0]
                mod_data = selected_item.data(Qt.ItemDataRole.UserRole)
                if mod_data and not mod_data.get('separator') and mod_data.get('exists'):
                    self.source_unfiltered_selected_mod = mod_data['name']
            else:
                self.source_unfiltered_selected_mod = None
        
        # === 第2步：重建列表 ===
        self.source_list.clear()
        available_count = 0
        
        # === 生成列表项目 ===
        self.source_list.setUpdatesEnabled(False)  # 减少UI更新
        
        for mod in self.source_mod_data:
            # 处理分隔符项目
            if mod['separator']:
                if not is_filtering:  # 只在无过滤时显示分隔符
                    item = QListWidgetItem(f"──── {mod['name']} ────")
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setForeground(QColor(100, 100, 100))
                    item.setBackground(QColor(240, 240, 240))
                    self.source_list.addItem(item)
                continue
            
            # 检查匹配
            if is_filtering and filter_text not in mod['name'].lower():
                continue
                
            # 创建项目
            if not mod['exists']:
                display_text = f"⚠️ [缺失] {mod['name']}"
                item = QListWidgetItem(display_text)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor(180, 0, 0))
            elif mod['name'] in self.new_mod_names:
                display_text = f"⚠️ [已添加] {mod['name']}"
                item = QListWidgetItem(display_text)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor(100, 100, 100))
                item.setBackground(QColor(230, 255, 230))
            else:
                prefix = "✓" if mod['enabled'] else "✗"
                display_text = f"{prefix} {mod['name']}"
                item = QListWidgetItem(display_text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                available_count += 1
            
            item.setData(Qt.ItemDataRole.UserRole, mod)
            self.source_list.addItem(item)
        
        self.source_list.setUpdatesEnabled(True)  # 重新启用UI更新
        
        # 更新计数
        self.source_count_label.setText(f"（{available_count} 个可用）")
        
        # === 第3步：智能处理选中项和滚动 ===
        target_item = None
        target_name = None
        
        if was_filtering and not is_filtering:  # 从过滤状态过渡到非过滤状态
            if self.source_filter_selected_mod_name:
                target_name = self.source_filter_selected_mod_name
            else:
                target_name = self.source_unfiltered_selected_mod
        elif not was_filtering and is_filtering:  # 从非过滤状态进入过滤状态
            target_name = self.source_unfiltered_selected_mod
        elif was_filtering and is_filtering:  # 连续过滤状态下
            target_name = self.source_filter_selected_mod_name
        
        if target_name:
            # 在当前列表中查找目标项目
            for index in range(self.source_list.count()):
                item = self.source_list.item(index)
                mod_data = item.data(Qt.ItemDataRole.UserRole)
                if mod_data and mod_data['name'] == target_name:
                    target_item = item
                    break
        
        # 执行滚动和选中
        if target_item:
            self.source_list.clearSelection()
            
            # 根据PyQt版本选择正确的滚动提示
            scroll_hint = QAbstractItemView.ScrollHint.PositionAtCenter if PYQT_VERSION == 6 else QAbstractItemView.PositionAtCenter
            
            # 确保项目可见
            self.source_list.scrollToItem(target_item, scroll_hint)
            target_item.setSelected(True)
            self.source_list.setCurrentItem(target_item)
        
        # 保存当前状态
        self.source_last_filtered_state = is_filtering


    def _onSourceSelectionChanged(self):
        """当源列表选中项改变时，更新选中的模组名称"""
        if not self.source_list:  # 确保列表已初始化
            return
            
        selected_items = self.source_list.selectedItems()
        if not selected_items:
            return
            
        selected_item = selected_items[0]
        mod_data = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 只记录有效的模组项目（非分隔符且存在的）
        if mod_data and not mod_data.get('separator') and mod_data.get('exists'):
            if self.source_last_filtered_state:
                # 过滤状态下选中的项目
                self.source_filter_selected_mod_name = mod_data['name']
            else:
                # 非过滤状态下选中的项目
                self.source_unfiltered_selected_mod = mod_data['name']

    def _onTargetSelectionChanged(self):
        """目标列表选择变化监听"""
        if not self.target_list:  # 确保列表已初始化
            return
            
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return
            
        selected_item = selected_items[0]
        mod = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 只记录有效的模组项目（非分隔符）
        if mod and not mod.get('separator'):
            if self.target_last_filtered_state:
                # 过滤状态下选中的项目
                self.target_filter_selected_mod_name = mod['name']
            else:
                # 非过滤状态下选中的项目
                self.target_unfiltered_selected_mod = mod['name']

    def _filterTargetMods(self):
        """根据搜索框内容过滤目标模组列表，与源列表过滤逻辑一致"""
        filter_text = self.target_search_box.text().lower().strip()
        is_filtering = bool(filter_text)
        was_filtering = self.target_last_filtered_state
        
        # === 第1步：在过滤状态改变前捕获当前选中项 ===
        if is_filtering and not was_filtering:
            # 即将进入过滤状态，记录当前的未过滤选中项
            selected_items = self.target_list.selectedItems()
            if selected_items:
                selected_item = selected_items[0]
                mod = selected_item.data(Qt.ItemDataRole.UserRole)
                if mod and not mod.get('separator'):
                    self.target_unfiltered_selected_mod = mod['name']
            else:
                self.target_unfiltered_selected_mod = None
        
        # === 第2步：重建列表 ===
        self.target_list.clear()
        new_count = 0
        visible_count = 0
        
        # === 生成列表项目 ===
        self.target_list.setUpdatesEnabled(False)  # 减少UI更新，提高性能
        
        for mod in self.display_list:
            # 处理分隔符项目
            if mod['separator']:
                if not is_filtering:  # 只在无过滤时显示分隔符
                    item = QListWidgetItem(f"──── {mod['name']} ────")
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setForeground(QColor(100, 100, 100))
                    item.setBackground(QColor(240, 240, 240))
                    self.target_list.addItem(item)
                    visible_count += 1
                continue
            
            # 检查匹配
            if is_filtering and filter_text not in mod['name'].lower():
                continue
                
            # 创建项目
            if mod.get('is_new', False):
                prefix = "✓" if mod['enabled'] else "✗"
                item = QListWidgetItem(f"[新增] {prefix} {mod['name']}")
                item.setForeground(QColor(0, 140, 0))
                item.setBackground(QColor(230, 255, 230))
                new_count += 1
            else:
                prefix = "✓" if mod.get('enabled') else "✗"
                item = QListWidgetItem(f" {prefix} {mod['name']}")
            
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, mod)
            self.target_list.addItem(item)
            visible_count += 1
        
        # 重新启用UI更新
        self.target_list.setUpdatesEnabled(True)
        
        # 更新计数标签
        self.target_count_label.setText(f"（共 {len(self.display_list)} 项，{new_count} 个新增，{visible_count} 项可见）")
        
        # === 第3步：智能处理选中项和滚动 ===
        target_item = None
        target_name = None
        
        if was_filtering and not is_filtering:  # 从过滤状态过渡到非过滤状态
            if self.target_filter_selected_mod_name:
                target_name = self.target_filter_selected_mod_name
            else:
                target_name = self.target_unfiltered_selected_mod
        elif not was_filtering and is_filtering:  # 从非过滤状态进入过滤状态
            target_name = self.target_unfiltered_selected_mod
        elif was_filtering and is_filtering:  # 连续过滤状态下
            # 修复：清除已取消选择的名称
            current_selected = self.target_list.currentItem()
            if not current_selected or target_name != self.target_filter_selected_mod_name:
                self.target_filter_selected_mod_name = None
            target_name = self.target_filter_selected_mod_name

        # 修复：跳过无效选择
        if not target_name:
            self.target_last_filtered_state = is_filtering
            return
        
        if target_name:
            # 在当前列表中查找目标项目
            for index in range(self.target_list.count()):
                item = self.target_list.item(index)
                mod_data = item.data(Qt.ItemDataRole.UserRole)  # 修正拼写错误
                if mod_data and mod_data['name'] == target_name:
                    target_item = item
                    break
        
        # 执行滚动和选中
        if target_item:
            self.target_list.clearSelection()
            
            # 根据PyQt版本选择正确的滚动提示
            if PYQT_VERSION == 6:
                scroll_hint = QAbstractItemView.ScrollHint.PositionAtCenter
            else:
                scroll_hint = QAbstractItemView.PositionAtCenter
            
            # 确保项目可见
            self.target_list.scrollToItem(target_item, scroll_hint)
            target_item.setSelected(True)
            self.target_list.setCurrentItem(target_item)
        
        # 保存当前状态
        self.target_last_filtered_state = is_filtering



    def _onTargetSelectionChanged(self):
        """当目标列表选中项改变时，更新选中的模组名称"""
        if not self.target_list:  # 确保列表已初始化
            return
            
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return
            
        selected_item = selected_items[0]
        mod = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 只记录有效的模组项目（非分隔符）
        if mod and not mod.get('separator'):
            if self.target_last_filtered_state:
                # 过滤状态下选中的项目
                self.target_filter_selected_mod_name = mod['name']
            else:
                # 非过滤状态下选中的项目
                self.target_unfiltered_selected_mod = mod['name']



    def _moveToTop(self):
        """将选中的新模组移到目标列表顶部"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        new_mods = []
        indices_to_remove = []

        for i in range(len(self.display_list)):
            mod = self.display_list[i]
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                new_mods.append(mod.copy())
                indices_to_remove.append(i)

        if not new_mods:
            return

        # 从原位置删除
        for i in reversed(indices_to_remove):
            del self.display_list[i]

        # 插入到顶部
        for mod in reversed(new_mods):
            self.display_list.insert(0, mod)

        self._refreshTargetDisplay()

    def _moveToBottom(self):
        """将选中的新模组移到目标列表底部"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        new_mods = []
        indices_to_remove = []

        for i in range(len(self.display_list)):
            mod = self.display_list[i]
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                new_mods.append(mod.copy())
                indices_to_remove.append(i)

        if not new_mods:
            return

        # 从原位置删除
        for i in reversed(indices_to_remove):
            del self.display_list[i]

        # 插入到底部
        for mod in new_mods:
            self.display_list.append(mod)

        self._refreshTargetDisplay()

    def _moveUp(self):
        """将选中的新模组上移一位"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        # 获取所有选中新模组的索引（从后往前处理避免索引偏移）
        indices = []
        for i in range(len(self.display_list)):
            mod = self.display_list[i]
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                indices.append(i)

        if not indices:
            return

        # 从前往后处理（确保不会跳过相邻项）
        for i in sorted(indices):
            if i > 0 and not self.display_list[i-1].get('is_new'):
                # 与非新模组交换
                self.display_list[i], self.display_list[i-1] = self.display_list[i-1], self.display_list[i]
            elif i > 0 and self.display_list[i-1].get('is_new'):
                # 与新模组交换（仅当未选中上一项时才移动）
                if not any(item.text().endswith(self.display_list[i-1]['name']) for item in selected_items):
                    self.display_list[i], self.display_list[i-1] = self.display_list[i-1], self.display_list[i]

        self._refreshTargetDisplay()

    def _moveDown(self):
        """将选中的新模组下移一位"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        # 获取所有选中新模组的索引（从后往前处理）
        indices = []
        for i in range(len(self.display_list)):
            mod = self.display_list[i]
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                indices.append(i)

        if not indices:
            return

        # 从后往前处理（确保不会跳过相邻项）
        for i in reversed(sorted(indices)):
            if i < len(self.display_list) - 1 and not self.display_list[i+1].get('is_new'):
                # 与非新模组交换
                self.display_list[i], self.display_list[i+1] = self.display_list[i+1], self.display_list[i]
            elif i < len(self.display_list) - 1 and self.display_list[i+1].get('is_new'):
                # 与新模组交换（仅当未选中下一项时才移动）
                if not any(item.text().endswith(self.display_list[i+1]['name']) for item in selected_items):
                    self.display_list[i], self.display_list[i+1] = self.display_list[i+1], self.display_list[i]

        self._refreshTargetDisplay()

    def _toggleSelected(self):
        """切换选中新模组的启用/禁用状态"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        toggled = False
        for i, mod in enumerate(self.display_list):
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                mod['enabled'] = not mod['enabled']
                toggled = True

        if toggled:
            self._refreshTargetDisplay()

    def _removeSelected(self):
        """从导入列表中移除选中的新模组"""
        selected_items = self.target_list.selectedItems()
        if not selected_items:
            return

        names_to_remove = set()
        indices_to_remove = []

        for i, mod in enumerate(self.display_list):
            if mod.get('is_new') and any(item.text().endswith(mod['name']) for item in selected_items):
                names_to_remove.add(mod['name'])
                indices_to_remove.append(i)

        if not names_to_remove:
            return

        # 从后往前删除以避免索引偏移
        for i in reversed(indices_to_remove):
            del self.display_list[i]

        # 从集合中移除
        self.new_mod_names -= names_to_remove

        self._refreshTargetDisplay()

    def _clearPlacements(self):
        """清除所有新导入的模组"""
        # reply = QMessageBox.question(self, "Confirm Clear",
        #                             "Remove all newly added mods from the target list?",
        #                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        reply = QMessageBox.question(self, "确认清除",
                                    "是否从目标列表中移除所有新添加的模组？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.display_list = [mod for mod in self.display_list if not mod.get('is_new')]
            self.new_mod_names.clear()
            self._refreshTargetDisplay()

    def _updateStatus(self):
        """更新状态标签"""
        if self.new_mod_names:
            # self.status_label.setText(f"Ready to import {len(self.new_mod_names)} new mod(s)")
            self.status_label.setText(f"准备导入 {len(self.new_mod_names)} 个新模组")
        else:
            self.status_label.setText("")

    def _createBackup(self):
        """在导入前创建 modlist.txt 的备份"""
        profiles_path = self._organizer.profilePath()
        modlist_path = os.path.join(profiles_path, "modlist.txt")
        backup_path = modlist_path + ".backup"

        try:
            if os.path.exists(modlist_path):
                shutil.copy2(modlist_path, backup_path)
            return True
        except Exception as e:
            # QMessageBox.critical(self, "Backup Error", f"Failed to create backup:\n{str(e)}")
            QMessageBox.critical(self, "备份错误", f"创建备份失败：\n{str(e)}")
            return False

    def _restoreBackup(self):
        """从备份恢复 modlist.txt"""
        profiles_path = self._organizer.profilePath()
        modlist_path = os.path.join(profiles_path, "modlist.txt")
        backup_path = modlist_path + ".backup"

        if not os.path.exists(backup_path):
            # QMessageBox.warning(self, "No Backup", "No backup file found to restore.")
            QMessageBox.warning(self, "无备份", "未找到可恢复的备份文件。")
            return

        # reply = QMessageBox.question(self, "Restore Backup",
        #                             "This will replace your current modlist with the backup.\nProceed?",
        #                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        reply = QMessageBox.question(self, "恢复备份",
                                    "此操作将用备份替换当前的模组列表。\n是否继续？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.copy2(backup_path, modlist_path)
                # QMessageBox.information(self, "Success", "Backup restored successfully!")
                QMessageBox.information(self, "成功", "备份已成功恢复！")
                self._loadTargetModList()
            except Exception as e:
                # QMessageBox.critical(self, "Restore Error", f"Failed to restore backup:\n{str(e)}")
                QMessageBox.critical(self, "恢复错误", f"恢复备份失败：\n{str(e)}")

    def _importMods(self):
        """执行模组导入操作"""
        if not self.new_mod_names:
            # QMessageBox.information(self, "Nothing to Import", "No new mods to import.")
            QMessageBox.information(self, "无内容可导入", "没有新模组需要导入。")
            return

        # 创建备份（如果启用）
        if self.backup_checkbox.isChecked():
            if not self._createBackup():
                return

        # 构建新的 modlist
        new_lines = []
        for mod in reversed(self.display_list):  # 反转以匹配 MO2 的存储顺序
            if mod['separator']:
                new_lines.append(f"*{mod['name']}")
            elif mod.get('is_new'):
                prefix = '+' if mod['enabled'] else '-'
                new_lines.append(f"{prefix}{mod['name']}")
            else:
                # 保留原始行（包括前缀和分隔符标记）
                new_lines.append(mod['original_line'])

        # 写入 modlist.txt
        profiles_path = self._organizer.profilePath()
        modlist_path = os.path.join(profiles_path, "modlist.txt")

        # === 新增：复制模组文件夹 ===
        source_mods_dir = self.mods_path  # 源 MO2 的 mods 目录（已在 _parseINI 中设置）
        target_mods_dir = self._organizer.modsPath()  # 当前 MO2 的 mods 目录

        if not os.path.exists(source_mods_dir):
            QMessageBox.warning(self, "路径错误", f"源模组目录不存在：{source_mods_dir}")
            return

        # 创建进度对话框
        progress = QProgressDialog("正在复制模组文件...", "取消", 0, len(self.new_mod_names), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowTitle("复制模组")
        progress.setAutoClose(True)
        progress.setValue(0)

        copied_count = 0
        for i, mod_name in enumerate(self.new_mod_names):
            if progress.wasCanceled():
                break

            source_mod_path = os.path.join(source_mods_dir, mod_name)
            target_mod_path = os.path.join(target_mods_dir, mod_name)

            # 跳过已存在的模组（避免覆盖）
            if os.path.exists(target_mod_path):
                copied_count += 1
                progress.setValue(i + 1)
                continue

            # 检查源模组是否存在
            if not os.path.exists(source_mod_path):
                print(f"警告：源模组不存在 {source_mod_path}")
                progress.setValue(i + 1)
                continue

            try:
                # 执行复制（递归复制整个文件夹）
                shutil.copytree(source_mod_path, target_mod_path)
                copied_count += 1
            except Exception as e:
                QMessageBox.warning(self, "复制失败", f"无法复制模组 '{mod_name}'：\n{str(e)}")

            progress.setValue(i + 1)

        progress.close()
        # === 复制结束 ===

        try:
            with open(modlist_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines) + '\n')

            # 为每个新导入的模组设置备注颜色
            # === 修复点：使用 modList().getMod() 并判空 ===

            mod_list = self._organizer.modList()

            for mod_name in self.new_mod_names:

                mod = mod_list.getMod(mod_name)  # ← 新 API

                if mod is None:

                    continue  # 模组不存在，跳过

                mod_path = mod.absolutePath()

                if os.path.exists(mod_path):

                    self._setModNoteColor(mod_path, self.selected_color)

            # 刷新 MO2 界面
            self._organizer.refresh()

            # QMessageBox.information(self, "Success", f"Successfully imported {len(self.new_mod_names)} mod(s)!")
            QMessageBox.information(self, "成功", f"成功导入了 {len(self.new_mod_names)} 个模组！")
            self.accept()

        except Exception as e:
            # QMessageBox.critical(self, "Import Error", f"Failed to import mods:\n{str(e)}")
            QMessageBox.critical(self, "导入错误", f"导入模组失败：\n{str(e)}")


def createPlugin(parent, organizer):
    return ModImporterPlugin(parent, organizer)


class ModImporterPlugin(mobase.IPluginTool):
    def __init__(self, parent=None, organizer=None):
        super().__init__()
        self._parent = parent
        self._organizer = organizer
        self.__version = mobase.VersionInfo(1, 3, 0, mobase.ReleaseType.FINAL)

    def init(self, organizer):
        self._organizer = organizer
        return True

    def name(self):
        # return "MO2 Mod Importer"
        return "MO2 模组导入器"

    def author(self):
        # return "MaskPlague (modified by Alhimik)"
        return "MaskPlague（由 Alhimik 修改）"

    def description(self):
        # return "Import mods from another MO2 instance with drag & drop positioning"
        return "通过拖放定位，从另一个 MO2 实例导入模组"

    def version(self):
        return self.__version

    def isActive(self):
        return True

    def settings(self):
        return []

    def displayName(self):
        # return "Import Mods from Another MO2"
        return "从另一个 MO2 导入模组"

    def tooltip(self):
        # return "Import mods from another MO2 instance"
        return "从另一个 MO2 实例导入模组"

    def icon(self):
        # 兼容 PyQt5 和 PyQt6
        try:
            from PyQt6.QtGui import QPixmap, QIcon
            from PyQt6.QtCore import Qt
        except ImportError:
            from PyQt5.QtGui import QPixmap, QIcon
            from PyQt5.QtCore import Qt

        # 创建 1x1 透明 pixmap
        pixmap = QPixmap(1, 1)
        pixmap.fill(Qt.GlobalColor.transparent)  # 兼容写法
        return QIcon(pixmap)

    def setParentWidget(self, widget):
        self._parent = widget

    def display(self):
        dialog = ModImporterDialog(self._parent, self._organizer)
        dialog.exec()
        
    def tr(self, text: str) -> str:
        return QCoreApplication.translate("Import Mods from MO2", text)

def createPlugin():
    """MO2 要求此函数无参数，并返回插件实例"""
    return ModImporterPlugin()


class ModImporterPlugin(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self._parent = None
        self._organizer = None
        self.__version = mobase.VersionInfo(1, 3, 0, mobase.ReleaseType.FINAL)

    def init(self, organizer: mobase.IOrganizer) -> bool:
        """MO2 会在加载插件后自动调用 init，并传入 organizer"""
        self._organizer = organizer
        return True

    def setParentWidget(self, widget):
        """MO2 会调用此方法设置父窗口"""
        self._parent = widget

    def name(self):
        return "MO2 模组导入器"

    def author(self):
        return "MaskPlague（由 Alhimik 修改）"

    def description(self):
        return "通过拖放定位，从另一个 MO2 实例导入模组"

    def version(self):
        return self.__version

    def isActive(self):
        return True

    def settings(self):
        return []

    def displayName(self):
        return "从另一个 MO2 导入模组"

    def tooltip(self):
        return "从另一个 MO2 实例导入模组"

    def icon(self):
        # 兼容 PyQt5 和 PyQt6
        try:
            from PyQt6.QtGui import QPixmap, QIcon
            from PyQt6.QtCore import Qt
        except ImportError:
            from PyQt5.QtGui import QPixmap, QIcon
            from PyQt5.QtCore import Qt

        # 创建 1x1 透明 pixmap
        pixmap = QPixmap(1, 1)
        pixmap.fill(Qt.GlobalColor.transparent)  # 兼容写法
        return QIcon(pixmap)

    def display(self):
        """当用户点击插件菜单项时调用"""
        if self._parent is None or self._organizer is None:
            return
        dialog = ModImporterDialog(self._parent, self._organizer)
        dialog.exec()