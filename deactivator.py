import os
import shutil
import json
import mobase
from datetime import datetime
from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtWidgets import ( QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QMessageBox, QLabel, QScrollArea, QWidget, QTextEdit, QFrame, QTabWidget, QTreeWidget, QTreeWidgetItem, QLineEdit, QComboBox, QSplitter, QGroupBox, QProgressBar, QListWidget, QListWidgetItem, QInputDialog, QMenu )
from PyQt6.QtGui import QIcon, QColor, QFont, QGuiApplication
from collections import defaultdict, deque

class PluginManagerPro(mobase.IPluginTool):
    def __init__(self):
        super(PluginManagerPro, self).__init__()
        self._organizer = None
        self._parent = None
        self.deactivation_log_path = None
        self.deactivation_data_path = None
        self.snapshots_path = None
        self.dependency_cache = {}
        self.reverse_dependency_cache = {}

    def init(self, organizer):
        self._organizer = organizer
        logs_path = os.path.join(self._organizer.basePath(), "logs")
        self.deactivation_log_path = os.path.join(logs_path, "PluginManagerPro.log")
        self.deactivation_data_path = os.path.join(logs_path, "PluginManagerPro_data.json")
        self.snapshots_path = os.path.join(logs_path, "PluginManagerPro_snapshots.json")
        os.makedirs(logs_path, exist_ok=True)

        if not os.path.exists(self.deactivation_log_path):
            with open(self.deactivation_log_path, 'w', encoding='utf-8') as log_file:
                log_file.write("Plugin Manager Pro initialized\n\n")

        if not os.path.exists(self.deactivation_data_path):
            with open(self.deactivation_data_path, 'w', encoding='utf-8') as data_file:
                json.dump({}, data_file)

        if not os.path.exists(self.snapshots_path):
            with open(self.snapshots_path, 'w', encoding='utf-8') as snapshots_file:
                json.dump([], snapshots_file)

        return True

    def name(self):
        return "PluginManagerPro"

    def author(self):
        return "Alhimik"

    def description(self):
        # Advanced plugin management tool with dependency analysis, backup/restore, and snapshots.
        return self.tr("高级插件管理工具，具备依赖分析、备份/还原和快照功能。")

    def version(self):
        return mobase.VersionInfo(2, 0, 0, mobase.ReleaseType.FINAL)

    def settings(self):
        return []

    def displayName(self):
        # Plugin Manager Pro
        return self.tr("插件管理器专业版")

    def tooltip(self):
        return self.description()

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.png")
        return QIcon(icon_path) if os.path.isfile(icon_path) else QIcon()

    def setParentWidget(self, widget):
        self._parent = widget

    def display(self):
        self.buildDependencyCaches()
        self.showMainDialog()

    def buildDependencyCaches(self):
        """构建主文件和反向依赖缓存，用于快速分析依赖关系"""
        self.dependency_cache.clear()
        self.reverse_dependency_cache.clear()
        all_plugins = self._organizer.pluginList().pluginNames()
        for plugin_name in all_plugins:
            masters = self._organizer.pluginList().masters(plugin_name)
            self.dependency_cache[plugin_name] = masters
            for master in masters:
                if master not in self.reverse_dependency_cache:
                    self.reverse_dependency_cache[master] = []
                self.reverse_dependency_cache[master].append(plugin_name)

    def getPluginsWithMissingMasters(self):
        """获取所有当前激活但缺少必需主文件（masters）的插件列表"""
        plugins_with_missing_masters = []
        all_plugins = self._organizer.pluginList().pluginNames()
        active_plugins = [
            plugin for plugin in all_plugins
            if self._organizer.pluginList().state(plugin) == mobase.PluginState.ACTIVE
        ]
        for plugin_name in active_plugins:
            masters = self.dependency_cache.get(plugin_name, [])
            missing_masters = [
                master for master in masters
                if self._organizer.pluginList().state(master) != mobase.PluginState.ACTIVE
            ]
            if missing_masters:
                plugins_with_missing_masters.extend((plugin_name, master) for master in missing_masters)
        return plugins_with_missing_masters

    def predictCascadingIssues(self, plugins_to_deactivate):
        """预测停用指定插件后可能引发的连锁问题（即其他插件因失去依赖而失效）"""
        affected_plugins = {}
        processed = set()
        queue = deque(plugins_to_deactivate)
        while queue:
            current_plugin = queue.popleft()
            if current_plugin in processed:
                continue
            processed.add(current_plugin)
            # 查找所有依赖于当前插件的子插件
            dependents = self.reverse_dependency_cache.get(current_plugin, [])
            for dependent in dependents:
                # 如果该子插件当前是激活状态，则会受到影响
                if self._organizer.pluginList().state(dependent) == mobase.PluginState.ACTIVE:
                    if dependent not in affected_plugins:
                        affected_plugins[dependent] = []
                    affected_plugins[dependent].append(current_plugin)
                    # 将受影响的子插件也加入队列，以检查更深层的影响
                    if dependent not in plugins_to_deactivate:
                        queue.append(dependent)
        return affected_plugins

    def getFullDependencyTree(self, plugin_name, depth=0, max_depth=10, visited=None):
        """递归获取指定插件的完整依赖树"""
        if visited is None:
            visited = set()
        if plugin_name in visited or depth > max_depth:
            return []
        visited.add(plugin_name)
        tree = []
        masters = self.dependency_cache.get(plugin_name, [])
        for master in masters:
            is_active = self._organizer.pluginList().state(master) == mobase.PluginState.ACTIVE
            subtree = self.getFullDependencyTree(master, depth + 1, max_depth, visited)
            tree.append({
                'name': master,
                'active': is_active,
                'depth': depth,
                'children': subtree
            })
        return tree

    def createSnapshot(self, description=""):
        """创建当前所有插件状态（激活/未激活及优先级）的快照"""
        all_plugins = self._organizer.pluginList().pluginNames()
        plugin_states = {}
        for plugin in all_plugins:
            plugin_states[plugin] = {
                'active': self._organizer.pluginList().state(plugin) == mobase.PluginState.ACTIVE,
                'priority': self._organizer.pluginList().priority(plugin)
            }
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'description': description,
            'plugin_states': plugin_states
        }
        snapshots = self.loadSnapshots()
        snapshots.append(snapshot)
        # 限制快照数量（最多保留50个）
        if len(snapshots) > 50:
            snapshots = snapshots[-50:]
        with open(self.snapshots_path, 'w', encoding='utf-8') as f:
            json.dump(snapshots, f, indent=2)
        return snapshot

    def loadSnapshots(self):
        """从磁盘加载所有已保存的快照"""
        if os.path.exists(self.snapshots_path):
            with open(self.snapshots_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def restoreSnapshot(self, snapshot):
        """根据提供的快照数据恢复插件状态"""
        plugin_states = snapshot['plugin_states']
        for plugin, state in plugin_states.items():
            try:
                target_state = mobase.PluginState.ACTIVE if state['active'] else mobase.PluginState.INACTIVE
                self._organizer.pluginList().setState(plugin, target_state)
            except:
                pass # 忽略无法设置状态的插件（例如已被删除）
        self._organizer.refresh()

    def showMainDialog(self):
        """显示插件管理器的主对话框"""
        dialog = QDialog(self._parent)
        dialog.setMinimumSize(1200, 800)
        # Plugin Manager Pro
        dialog.setWindowTitle(self.tr("插件管理器专业版"))
        main_layout = QVBoxLayout(dialog)

        # 创建标签页
        tab_widget = QTabWidget()

        # Tab 1: 分析与停用
        # Tab 1: Analysis & Deactivate
        analysis_tab = self.createAnalysisTab()
        tab_widget.addTab(analysis_tab, self.tr("🔍 分析与停用"))

        # Tab 2: 还原插件
        # Tab 2: Restore Plugins
        restore_tab = self.createRestoreTab()
        tab_widget.addTab(restore_tab, self.tr("🔄 还原插件"))

        # Tab 3: 快照
        # Tab 3: Snapshots
        snapshots_tab = self.createSnapshotsTab()
        tab_widget.addTab(snapshots_tab, self.tr("📸 快照"))

        # Tab 4: 历史记录
        # Tab 4: History
        history_tab = self.createHistoryTab()
        tab_widget.addTab(history_tab, self.tr("📜 历史记录"))

        # Tab 5: 排序分析
        sort_tab = self.createSortAnalysisTab()
        tab_widget.addTab(sort_tab, self.tr("📊 排序分析"))
    
        main_layout.addWidget(tab_widget)

        # 底部信息
        # Created by <a href="https://next.nexusmods.com/profile/alhimikph">Alhimik</a>
        info_label = QLabel(self.tr('由 <a href="https://next.nexusmods.com/profile/alhimikph">Alhimik</a> 制作'))
        info_label.setOpenExternalLinks(True)
        main_layout.addWidget(info_label)

        # 关闭按钮
        # Close
        close_button = QPushButton(self.tr("关闭"))
        close_button.clicked.connect(dialog.accept)
        main_layout.addWidget(close_button)

        dialog.exec()

    def createAnalysisTab(self):
        """创建“分析与停用”标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 顶部面板：扫描按钮
        top_panel = QHBoxLayout()
        # Scan for Missing Masters
        scan_button = QPushButton(self.tr("🔍 扫描缺失的主文件"))
        scan_button.setStyleSheet("QPushButton { padding: 8px; font-weight: bold; }")
        scan_button.setFixedHeight(40)
        scan_button.setFixedWidth(250)
        top_panel.addWidget(scan_button)
        self.problem_count_label = QLabel(self.tr("点击扫描以检查问题"))
        self.problem_count_label.setStyleSheet("font-weight: bold; color: gray; padding: 5px;")
        top_panel.addWidget(self.problem_count_label)
        top_panel.addStretch()
        layout.addLayout(top_panel)

        # 主分割器：左侧插件列表，右侧详情
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ====== 左侧面板：有问题的插件列表 ======
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 插件列表标题
        # Plugins with Missing Masters:
        header_layout = QVBoxLayout()
        plugins_label = QLabel(self.tr("⚠️ 缺失主文件的插件："))
        plugins_label.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 5px;")
        header_layout.addWidget(plugins_label)
        # Search plugins...
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(self.tr("🔍 搜索插件..."))
        self.search_box.setFixedHeight(30)
        header_layout.addWidget(self.search_box)
        left_layout.addLayout(header_layout)

        # 可滚动的插件复选框区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(300)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        scroll_area.setWidget(self.scroll_content)
        left_layout.addWidget(scroll_area, 1) # stretch factor 1

        # 全选/取消全选按钮
        select_buttons = QHBoxLayout()
        # Select All
        select_all_btn = QPushButton(self.tr("全选"))
        select_all_btn.setFixedHeight(30)
        # Deselect All
        deselect_all_btn = QPushButton(self.tr("取消全选"))
        deselect_all_btn.setFixedHeight(30)
        select_buttons.addWidget(select_all_btn)
        select_buttons.addWidget(deselect_all_btn)
        left_layout.addLayout(select_buttons)

        main_splitter.addWidget(left_panel)

        # ====== 右侧面板：依赖详情 ======
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 依赖树标题
        # Dependency Tree:
        tree_label = QLabel(self.tr("🌳 依赖树："))
        tree_label.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 5px;")
        right_layout.addWidget(tree_label)

        self.dependency_tree = QTreeWidget()
        # Plugin, Status, Info
        self.dependency_tree.setHeaderLabels([self.tr("插件"), self.tr("状态"), self.tr("信息")])
        self.dependency_tree.setColumnWidth(0, 200)
        self.dependency_tree.setColumnWidth(1, 100)
        self.dependency_tree.setMinimumHeight(250)

        # 添加新的右键菜单功能
        self.dependency_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dependency_tree.customContextMenuRequested.connect(self.showAnalysisTreeContextMenu)
        
        right_layout.addWidget(self.dependency_tree, 1) # stretch factor 1

        # 连锁影响预测
        # Cascade Impact Prediction:
        cascade_label = QLabel(self.tr("🔗 连锁影响预测："))
        cascade_label.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 5px;")
        right_layout.addWidget(cascade_label)

        self.cascade_info = QTextEdit()
        self.cascade_info.setReadOnly(True)
        self.cascade_info.setFixedHeight(120)
        self.cascade_info.setStyleSheet("background-color: #f8f9fa; padding: 5px;")
        right_layout.addWidget(self.cascade_info)

        # 停用选项
        # Deactivation Options
        options_group = QGroupBox(self.tr("⚙️ 停用选项"))
        options_layout = QVBoxLayout()
        options_layout.setSpacing(5)
        # Move plugins to backup folder
        self.delete_checkbox = QCheckBox(self.tr("将插件移至备份文件夹"))
        self.delete_checkbox.setChecked(True)
        options_layout.addWidget(self.delete_checkbox)
        # Auto-select dependent plugins
        self.cascade_checkbox = QCheckBox(self.tr("自动选择依赖插件"))
        self.cascade_checkbox.setChecked(True)
        options_layout.addWidget(self.cascade_checkbox)
        # Create snapshot before deactivation
        self.snapshot_checkbox = QCheckBox(self.tr("停用前创建快照"))
        self.snapshot_checkbox.setChecked(True)
        options_layout.addWidget(self.snapshot_checkbox)
        options_group.setLayout(options_layout)
        options_group.setFixedHeight(110)
        right_layout.addWidget(options_group)

        # 停用按钮
        # Deactivate Selected Plugins
        self.deactivate_button = QPushButton(self.tr("🛑 停用所选插件"))
        self.deactivate_button.setStyleSheet("QPushButton { padding: 10px; background-color: #ff6b6b; color: white; font-weight: bold; font-size: 11pt; }")
        self.deactivate_button.setEnabled(False)
        self.deactivate_button.setFixedHeight(45)
        right_layout.addWidget(self.deactivate_button)

        main_splitter.addWidget(right_panel)

        # 设置分割器初始比例 (40% left, 60% right)
        main_splitter.setSizes([480, 720])
        layout.addWidget(main_splitter, 1) # stretch factor 1 for main_splitter

        # 连接信号
        self.checkboxes = []
        scan_button.clicked.connect(lambda: self.performScan())
        select_all_btn.clicked.connect(self.selectAllPlugins)
        deselect_all_btn.clicked.connect(self.deselectAllPlugins)
        self.deactivate_button.clicked.connect(self.performDeactivation)
        self.search_box.textChanged.connect(self.filterPlugins)

        return widget

            # 新增方法：显示分析依赖树的右键菜单
    def showAnalysisTreeContextMenu(self, position):
        """显示依赖树上下文的右键菜单"""
        item = self.dependency_tree.itemAt(position)
        if not item:
            return
            
        # 获取插件名称（存在于第0列）
        plugin_name = item.text(0)
        
        # 创建菜单
        menu = QMenu(self.dependency_tree)
        
        # 添加复制插件名称操作
        copy_action = menu.addAction(self.tr("复制插件名称"))
        
        # 显示菜单并等待用户选择
        action = menu.exec(self.dependency_tree.viewport().mapToGlobal(position))
        
        # 处理用户选择
        if action == copy_action:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(plugin_name)

    def performScan(self):
        """执行扫描，查找并显示所有有缺失主文件的插件"""
        # 清空现有UI
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.checkboxes.clear()
        self.dependency_tree.clear()
        self.cascade_info.clear()

        plugins_with_missing_masters = self.getPluginsWithMissingMasters()
        if not plugins_with_missing_masters:
            # No issues found
            self.problem_count_label.setText(self.tr("✅ 未发现问题"))
            self.problem_count_label.setStyleSheet("font-weight: bold; color: green;")
            self.deactivate_button.setEnabled(False)
            return

        # 按插件分组
        plugins_dict = defaultdict(list)
        for plugin, master in plugins_with_missing_masters:
            plugins_dict[plugin].append(master)

        # Found {len(plugins_dict)} plugins with issues
        self.problem_count_label.setText(self.tr(f"⚠️ 发现 {len(plugins_dict)} 个插件存在问题"))
        self.problem_count_label.setStyleSheet("font-weight: bold; color: red;")
        self.deactivate_button.setEnabled(True)

        # 按Mod分组
        mod_plugins = defaultdict(list)
        for plugin, masters in plugins_dict.items():
            mod_name = self._organizer.pluginList().origin(plugin)
            mod_plugins[mod_name].append((plugin, masters))

        # 构建UI
        for mod_name, plugins in sorted(mod_plugins.items()):
            # Mod 标题
            mod_label = QLabel(f"📁 {mod_name}")
            mod_label.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
            mod_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            mod_label.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 8px; border-radius: 3px;")
            self.scroll_layout.addWidget(mod_label)

            for plugin, masters in plugins:
                checkbox = QCheckBox(f" {plugin}")
                checkbox.setChecked(True)
                checkbox.setProperty("plugin_name", plugin)
                checkbox.setProperty("masters", masters)

                # 如果缺失的主文件本身也是有问题的插件，则标记为严重
                if any(master in plugins_dict for master in masters):
                    checkbox.setStyleSheet("color: #e74c3c; font-weight: bold;") # 红色 - 严重：依赖了其他有问题的主文件
                    # Critical: depends on missing masters
                    tooltip = "⚠️ 严重：依赖了缺失的主文件\n"
                else:
                    checkbox.setStyleSheet("color: #f39c12;") # 橙色 - 警告：有缺失的主文件
                    # Warning: has missing masters
                    tooltip = "⚠️ 警告：存在缺失的主文件\n"
                tooltip += "\n".join([f" 缺失: {master}" for master in masters])
                checkbox.setToolTip(tooltip)
                checkbox.stateChanged.connect(self.updateCascadePreview)
                self.scroll_layout.addWidget(checkbox)
                self.checkboxes.append(checkbox)

        self.scroll_layout.addStretch()
        self.updateCascadePreview()

    def updateCascadePreview(self):
        """更新右侧的连锁影响预览和依赖树"""
        selected_plugins = [cb.property("plugin_name") for cb in self.checkboxes if cb.isChecked()]
        if not selected_plugins:
            self.cascade_info.clear()
            self.dependency_tree.clear()
            return

        # 预测连锁影响
        affected = self.predictCascadingIssues(selected_plugins)

        # 显示影响文本
        if affected:
            # WARNING: Deactivating selected plugins will cause {len(affected)} additional plugins to have missing masters:
            text = self.tr(f"⚠️ 警告：停用所选插件将导致 {len(affected)} 个额外插件出现缺失主文件问题：\n\n")
            for plugin, missing_masters in sorted(affected.items()):
                text += f"⚠️ {plugin}\n"
                text += f" 将缺失: {', '.join(missing_masters)}\n\n"
            if self.cascade_checkbox.isChecked():
                # These plugins will be auto-selected for deactivation.
                text += self.tr("\n✅ 已启用“自动选择依赖插件”，它们将被一并停用。")
            else:
                # Enable 'Auto-select dependent plugins' to include them.
                text += self.tr("\n💡 启用“自动选择依赖插件”选项以包含它们。")
            self.cascade_info.setStyleSheet("background-color: #fff3cd; color: #856404;")
        else:
            # No cascade impact detected. Safe to proceed.
            text = self.tr("✅ 未检测到连锁影响。可以安全进行。")
            self.cascade_info.setStyleSheet("background-color: #d4edda; color: #155724;")
        self.cascade_info.setText(text)

        # 更新依赖树（仅显示第一个选中插件的）
        self.updateDependencyTree()  # 删除原先的选择参数

    def updateDependencyTree(self):
        """更新依赖树视图，展示所有选中插件的依赖结构"""
        self.dependency_tree.clear()
        selected_plugins = [cb.property("plugin_name") for cb in self.checkboxes if cb.isChecked()]
        
        if not selected_plugins:
            return
            
        # 创建根节点
        root = QTreeWidgetItem(self.dependency_tree)
        root.setText(0, self.tr("所有有问题的插件"))
        root.setExpanded(True)
        
        for plugin_name in selected_plugins:
            # 为每个选中插件创建子树
            plugin_root = QTreeWidgetItem(root)
            plugin_root.setText(0, plugin_name)
            plugin_root.setBackground(0, QColor("#3498db"))
            plugin_root.setForeground(0, QColor("white"))
            plugin_root.setText(1, "🎯 目标")

            # 获取该插件的完整依赖树
            tree = self.getFullDependencyTree(plugin_name)
            self.buildTreeItems(plugin_root, tree)

        self.dependency_tree.expandAll()

    def buildTreeItems(self, parent, tree):
        """递归构建依赖树的UI项"""
        for node in tree:
            item = QTreeWidgetItem(parent)
            item.setText(0, node['name'])
            if node['active']:
                # Active
                item.setText(1, "✅ 已激活")
                item.setForeground(1, QColor("green"))
            else:
                # Missing
                item.setText(1, "❌ 缺失")
                item.setForeground(1, QColor("red"))
                item.setBackground(0, QColor("#ffcccc")) # 背景高亮红色

            # 显示依赖此插件的数量
            dependents_count = len(self.reverse_dependency_cache.get(node['name'], []))
            if dependents_count > 0:
                # {dependents_count} dependents
                item.setText(2, f"👥 {dependents_count} 个依赖者")

            if node['children']:
                self.buildTreeItems(item, node['children'])

    def selectAllPlugins(self):
        """全选所有插件复选框"""
        for cb in self.checkboxes:
            cb.setChecked(True)

    def deselectAllPlugins(self):
        """取消全选所有插件复选框"""
        for cb in self.checkboxes:
            cb.setChecked(False)

    def filterPlugins(self, text):
        """根据搜索框文本过滤插件列表"""
        text = text.lower()
        for cb in self.checkboxes:
            plugin_name = cb.property("plugin_name").lower()
            cb.setVisible(text in plugin_name)

    def performDeactivation(self):
        """执行停用操作"""
        selected_plugins = [cb.property("plugin_name") for cb in self.checkboxes if cb.isChecked()]
        if not selected_plugins:
            # No Selection, Please select at least one plugin to deactivate.
            QMessageBox.warning(self._parent, self.tr("未选择"), self.tr("请至少选择一个要停用的插件。"))
            return

        # 如果启用了连锁选择，则扩展选择列表
        if self.cascade_checkbox.isChecked():
            affected = self.predictCascadingIssues(selected_plugins)
            selected_plugins.extend(affected.keys())
            selected_plugins = list(set(selected_plugins)) # 去重

        # 确认对话框
        # Confirm Deactivation, You are about to deactivate {len(selected_plugins)} plugin(s).
        msg = QMessageBox(self._parent)
        msg.setWindowTitle(self.tr("确认停用"))
        msg.setText(self.tr(f"您即将停用 {len(selected_plugins)} 个插件。"))
        # This action can be undone using snapshots or restore function.
        msg.setInformativeText(self.tr("此操作可通过快照或还原功能撤销。"))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        # 创建快照
        if self.snapshot_checkbox.isChecked():
            self.createSnapshot(f"停用 {len(selected_plugins)} 个插件前")

        # 执行停用
        progress = QProgressBar()
        progress.setMaximum(len(selected_plugins))
        self.scroll_layout.addWidget(progress)

        disabled_plugins = []
        for i, plugin in enumerate(selected_plugins):
            if self._organizer.pluginList().state(plugin) == mobase.PluginState.ACTIVE:
                self._organizer.pluginList().setState(plugin, mobase.PluginState.INACTIVE)
                disabled_plugins.append(plugin)
            progress.setValue(i + 1)
            QCoreApplication.processEvents() # 保持UI响应

        self.logDeactivation(disabled_plugins)
        self.updateDataFile(disabled_plugins)

        # 移动到备份文件夹
        if self.delete_checkbox.isChecked():
            self.movePluginsToBackup(disabled_plugins)

        self._organizer.refresh()
        # Successfully deactivated {len(disabled_plugins)} plugin(s).
        QMessageBox.information(self._parent, self.tr("成功"), self.tr(f"已成功停用 {len(disabled_plugins)} 个插件。"))

        # 重新扫描以刷新UI
        self.performScan()

    def createRestoreTab(self):
        """创建“还原插件”标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        # Restore Previously Deactivated Plugins:
        layout.addWidget(QLabel(self.tr("还原先前停用的插件：")))

        # 顶部过滤器
        filter_layout = QHBoxLayout()
        # Search plugins...
        self.restore_search = QLineEdit()
        self.restore_search.setPlaceholderText(self.tr("搜索插件..."))
        filter_layout.addWidget(self.restore_search)
        self.restore_filter = QComboBox()
        # All, By Date, By Mod
        self.restore_filter.addItems([self.tr("全部"), self.tr("按日期"), self.tr("按Mod")])
        filter_layout.addWidget(self.restore_filter)
        # Refresh
        refresh_button = QPushButton(self.tr("🔄 刷新"))
        filter_layout.addWidget(refresh_button)
        layout.addLayout(filter_layout)

        # 可滚动的还原列表
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.restore_scroll_content = QWidget()
        self.restore_scroll_layout = QVBoxLayout(self.restore_scroll_content)
        scroll_area.setWidget(self.restore_scroll_content)
        layout.addWidget(scroll_area)

        # 全选/取消全选按钮
        buttons_layout = QHBoxLayout()
        # Select All
        select_all_restore = QPushButton(self.tr("全选"))
        # Deselect All
        deselect_all_restore = QPushButton(self.tr("取消全选"))
        buttons_layout.addWidget(select_all_restore)
        buttons_layout.addWidget(deselect_all_restore)
        layout.addLayout(buttons_layout)

        # 还原信息组
        # Restore Information
        info_group = QGroupBox(self.tr("还原信息"))
        info_layout = QVBoxLayout()
        # Select plugins to see restore information
        self.restore_info_label = QLabel(self.tr("选择插件以查看还原信息"))
        info_layout.addWidget(self.restore_info_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # 还原按钮
        # Restore Selected Plugins
        restore_button = QPushButton(self.tr("🔄 还原所选插件"))
        restore_button.setStyleSheet("QPushButton { padding: 10px; background-color: #27ae60; color: white; font-weight: bold; }")
        layout.addWidget(restore_button)

        # 连接信号
        self.restore_checkboxes = []
        refresh_button.clicked.connect(self.loadRestoreList)
        select_all_restore.clicked.connect(lambda: self.setAllRestoreChecks(True))
        deselect_all_restore.clicked.connect(lambda: self.setAllRestoreChecks(False))
        restore_button.clicked.connect(self.performRestore)
        self.restore_search.textChanged.connect(self.filterRestoreList)

        # 初始加载
        self.loadRestoreList()
        return widget

    def loadRestoreList(self):
        """从备份文件夹加载可还原的插件列表"""
        while self.restore_scroll_layout.count():
            child = self.restore_scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.restore_checkboxes.clear()

        backup_folder = os.path.join(self._organizer.modsPath(), 'Deactivated_plugins_backup')
        if not os.path.exists(backup_folder):
            # No backup folder found. No plugins to restore.
            label = QLabel(self.tr("未找到备份文件夹。无可还原的插件。"))
            label.setStyleSheet("color: gray; font-style: italic;")
            self.restore_scroll_layout.addWidget(label)
            return

        # 读取插件数据文件
        plugin_data = {}
        if os.path.exists(self.deactivation_data_path):
            with open(self.deactivation_data_path, 'r', encoding='utf-8') as f:
                plugin_data = json.load(f)

        # 按Mod分组插件
        mod_plugins = defaultdict(list)
        for mod_name in os.listdir(backup_folder):
            mod_backup_path = os.path.join(backup_folder, mod_name)
            if os.path.isdir(mod_backup_path):
                for plugin in os.listdir(mod_backup_path):
                    plugin_path = os.path.join(mod_backup_path, plugin)
                    if os.path.isfile(plugin_path):
                        mod_plugins[mod_name].append((plugin, plugin_path))

        if not mod_plugins:
            # No plugins found in backup. Nothing to restore.
            label = QLabel(self.tr("备份中未找到插件。无可还原内容。"))
            label.setStyleSheet("color: gray; font-style: italic;")
            self.restore_scroll_layout.addWidget(label)
            return

        # 构建UI
        for mod_name, plugins in sorted(mod_plugins.items()):
            mod_label = QLabel(f"📁 {mod_name}")
            mod_label.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
            mod_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            mod_label.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px; border-radius: 3px;")
            self.restore_scroll_layout.addWidget(mod_label)

            for plugin, plugin_path in plugins:
                checkbox = QCheckBox(f" {plugin}")
                checkbox.setProperty("plugin_path", plugin_path)
                checkbox.setProperty("plugin_name", plugin)
                checkbox.setProperty("mod_name", mod_name)

                # 添加文件信息到提示
                if os.path.exists(plugin_path):
                    size = os.path.getsize(plugin_path)
                    size_str = self.formatSize(size)
                    mtime = os.path.getmtime(plugin_path)
                    date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    # Path: {plugin_path}\nSize: {size_str}\nModified: {date_str}
                    tooltip = f"路径: {plugin_path}\n大小: {size_str}\n修改时间: {date_str}"
                    checkbox.setToolTip(tooltip)
                self.restore_scroll_layout.addWidget(checkbox)
                self.restore_checkboxes.append(checkbox)

        self.restore_scroll_layout.addStretch()
        # Found {len([cb for cb in self.restore_checkboxes])} plugins available for restore
        self.restore_info_label.setText(self.tr(f"找到 {len(self.restore_checkboxes)} 个可还原的插件"))

    def formatSize(self, size):
        """将字节大小格式化为易读的字符串"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def setAllRestoreChecks(self, checked):
        """设置所有可见的还原复选框状态"""
        for cb in self.restore_checkboxes:
            if cb.isVisible():
                cb.setChecked(checked)

    def filterRestoreList(self, text):
        """根据搜索框文本过滤还原列表"""
        text = text.lower()
        for cb in self.restore_checkboxes:
            plugin_name = cb.property("plugin_name").lower()
            cb.setVisible(text in plugin_name)

    def performRestore(self):
        """执行还原操作"""
        selected = [(cb.property("plugin_path"), cb.property("plugin_name"), cb.property("mod_name"))
                   for cb in self.restore_checkboxes if cb.isChecked()]
        if not selected:
            # No Selection, Please select at least one plugin to restore.
            QMessageBox.warning(self._parent, self.tr("未选择"), self.tr("请至少选择一个要还原的插件。"))
            return

        # 检查缺失的主文件
        warnings = []
        for _, plugin_name, _ in selected:
            masters = self.dependency_cache.get(plugin_name, [])
            missing = [m for m in masters if self._organizer.pluginList().state(m) != mobase.PluginState.ACTIVE]
            if missing:
                warnings.append(f"{plugin_name}: 缺失 {', '.join(missing)}")

        if warnings:
            # Warning: Missing Masters Detected, Some plugins you're restoring will still have missing masters:, Do you want to continue?
            msg = QMessageBox(self._parent)
            msg.setWindowTitle(self.tr("⚠️ 警告：检测到缺失的主文件"))
            msg.setText(self.tr("您要还原的部分插件仍将缺少主文件："))
            msg.setDetailedText("\n".join(warnings))
            msg.setInformativeText(self.tr("是否继续？"))
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if msg.exec() != QMessageBox.StandardButton.Yes:
                return

        # 创建快照
        self.createSnapshot(f"还原 {len(selected)} 个插件前")

        # 执行还原
        restored = []
        for plugin_path, plugin_name, mod_name in selected:
            mod_folder = os.path.join(self._organizer.modsPath(), mod_name)
            os.makedirs(mod_folder, exist_ok=True)
            restore_path = os.path.join(mod_folder, plugin_name)
            if os.path.exists(plugin_path):
                shutil.move(plugin_path, restore_path)
                self._organizer.pluginList().setState(plugin_name, mobase.PluginState.ACTIVE)
                restored.append(plugin_name)

        self._organizer.refresh()
        self.logRestoration(restored)
        # Successfully restored {len(restored)} plugin(s).
        QMessageBox.information(self._parent, self.tr("成功"), self.tr(f"已成功还原 {len(restored)} 个插件。"))

        # 重新加载列表
        self.loadRestoreList()

    def createSnapshotsTab(self):
        """创建“快照”标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 顶部按钮
        buttons_layout = QHBoxLayout()
        # Create New Snapshot
        create_snapshot_btn = QPushButton(self.tr("📸 创建新快照"))
        create_snapshot_btn.setStyleSheet("padding: 8px; font-weight: bold;")
        buttons_layout.addWidget(create_snapshot_btn)
        # Refresh
        refresh_snapshots_btn = QPushButton(self.tr("🔄 刷新"))
        buttons_layout.addWidget(refresh_snapshots_btn)
        layout.addLayout(buttons_layout)

        # 快照列表
        self.snapshots_list = QListWidget()
        self.snapshots_list.setAlternatingRowColors(True)
        layout.addWidget(self.snapshots_list)

        # 快照详情
        # Snapshot Details
        info_group = QGroupBox(self.tr("快照详情"))
        info_layout = QVBoxLayout()
        self.snapshot_details = QTextEdit()
        self.snapshot_details.setReadOnly(True)
        self.snapshot_details.setMaximumHeight(150)
        info_layout.addWidget(self.snapshot_details)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # 操作按钮
        action_buttons = QHBoxLayout()
        # Restore Selected Snapshot
        restore_snapshot_btn = QPushButton(self.tr("🔄 还原所选快照"))
        restore_snapshot_btn.setStyleSheet("padding: 8px; background-color: #27ae60; color: white; font-weight: bold;")
        action_buttons.addWidget(restore_snapshot_btn)
        # Delete Selected
        delete_snapshot_btn = QPushButton(self.tr("🗑️ 删除所选"))
        delete_snapshot_btn.setStyleSheet("padding: 8px;")
        action_buttons.addWidget(delete_snapshot_btn)
        layout.addLayout(action_buttons)

        # 连接信号
        create_snapshot_btn.clicked.connect(self.createManualSnapshot)
        refresh_snapshots_btn.clicked.connect(self.loadSnapshotsList)
        self.snapshots_list.currentItemChanged.connect(self.displaySnapshotDetails)
        restore_snapshot_btn.clicked.connect(self.restoreSelectedSnapshot)
        delete_snapshot_btn.clicked.connect(self.deleteSelectedSnapshot)

        # 初始加载
        self.loadSnapshotsList()
        return widget

    def loadSnapshotsList(self):
        """加载快照列表到UI"""
        self.snapshots_list.clear()
        snapshots = self.loadSnapshots()
        if not snapshots:
            # No snapshots available
            item = QListWidgetItem(self.tr("无可用快照"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.snapshots_list.addItem(item)
            return

        for i, snapshot in enumerate(reversed(snapshots)):
            timestamp = datetime.fromisoformat(snapshot['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
            description = snapshot.get('description', 'No description')
            active_count = sum(1 for state in snapshot['plugin_states'].values() if state['active'])
            total_count = len(snapshot['plugin_states'])
            # 📸 {timestamp} | {active_count}/{total_count} active | {description}
            item_text = f"📸 {timestamp} | {active_count}/{total_count} 已激活 | {description}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, len(snapshots) - 1 - i) # 存储原始
            self.snapshots_list.addItem(item)

    def displaySnapshotDetails(self, current, previous):
        """在选中快照时显示其详细信息"""
        if not current:
            self.snapshot_details.clear()
            return

        index = current.data(Qt.ItemDataRole.UserRole)
        snapshots = self.loadSnapshots()
        if index < 0 or index >= len(snapshots):
            self.snapshot_details.setText(self.tr("无效的快照索引"))
            return

        snapshot = snapshots[index]
        timestamp = datetime.fromisoformat(snapshot['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
        description = snapshot.get('description', self.tr('无描述'))
        plugin_states = snapshot['plugin_states']
        active_plugins = [name for name, state in plugin_states.items() if state['active']]
        inactive_plugins = [name for name, state in plugin_states.items() if not state['active']]

        details = self.tr(f"创建时间: {timestamp}\n")
        details += self.tr(f"描述: {description}\n")
        details += self.tr(f"激活插件数: {len(active_plugins)}\n")
        details += self.tr(f"未激活插件数: {len(inactive_plugins)}\n\n")

        # 显示前10个激活和未激活插件作为预览
        if active_plugins:
            details += self.tr("激活插件（前10个）:\n") + "\n".join(active_plugins[:10])
            if len(active_plugins) > 10:
                details += f"\n... {self.tr('还有')} {len(active_plugins) - 10} {self.tr('个')}"
        else:
            details += self.tr("无激活插件")

        details += "\n\n"
        if inactive_plugins:
            details += self.tr("未激活插件（前10个）:\n") + "\n".join(inactive_plugins[:10])
            if len(inactive_plugins) > 10:
                details += f"\n... {self.tr('还有')} {len(inactive_plugins) - 10} {self.tr('个')}"
        else:
            details += self.tr("无未激活插件")

        self.snapshot_details.setText(details)

    def createManualSnapshot(self):
        """手动创建新快照"""
        # Snapshot Description
        description, ok = QInputDialog.getText(self._parent, self.tr("创建快照"), self.tr("请输入快照描述："))
        if ok and description.strip():
            self.createSnapshot(description.strip())
            self.loadSnapshotsList()
            # Snapshot created successfully.
            QMessageBox.information(self._parent, self.tr("成功"), self.tr("快照已成功创建。"))
        elif ok:  # 用户点击了确定但未输入内容
            self.createSnapshot()
            self.loadSnapshotsList()
            QMessageBox.information(self._parent, self.tr("成功"), self.tr("快照已成功创建（无描述）。"))

    def restoreSelectedSnapshot(self):
        """还原所选快照"""
        current = self.snapshots_list.currentItem()
        if not current or current.text() == self.tr("无可用快照"):
            # No snapshot selected
            QMessageBox.warning(self._parent, self.tr("未选择"), self.tr("请选择一个快照进行还原。"))
            return

        index = current.data(Qt.ItemDataRole.UserRole)
        snapshots = self.loadSnapshots()
        if index < 0 or index >= len(snapshots):
            QMessageBox.critical(self._parent, self.tr("错误"), self.tr("无法找到所选快照。"))
            return

        # Confirm Restore, This will restore all plugin states to the selected snapshot.
        msg = QMessageBox(self._parent)
        msg.setWindowTitle(self.tr("确认还原"))
        msg.setText(self.tr("此操作将把所有插件状态恢复到所选快照的状态。"))
        # This action can be undone by restoring another snapshot.
        msg.setInformativeText(self.tr("可通过还原其他快照撤销此操作。"))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        snapshot = snapshots[index]
        self.restoreSnapshot(snapshot)
        # Snapshot restored successfully.
        QMessageBox.information(self._parent, self.tr("成功"), self.tr("快照已成功还原。"))

    def deleteSelectedSnapshot(self):
        """删除所选快照"""
        current = self.snapshots_list.currentItem()
        if not current or current.text() == self.tr("无可用快照"):
            # No snapshot selected
            QMessageBox.warning(self._parent, self.tr("未选择"), self.tr("请选择一个快照进行删除。"))
            return

        index = current.data(Qt.ItemDataRole.UserRole)
        snapshots = self.loadSnapshots()
        if index < 0 or index >= len(snapshots):
            QMessageBox.critical(self._parent, self.tr("错误"), self.tr("无法找到所选快照。"))
            return

        # Confirm Deletion, Are you sure you want to delete this snapshot?
        reply = QMessageBox.question(self._parent, self.tr("确认删除"),
                                     self.tr("您确定要删除此快照吗？"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            del snapshots[index]
            with open(self.snapshots_path, 'w', encoding='utf-8') as f:
                json.dump(snapshots, f, indent=2)
            self.loadSnapshotsList()
            # Snapshot deleted successfully.
            QMessageBox.information(self._parent, self.tr("成功"), self.tr("快照已成功删除。"))

    def createHistoryTab(self):
        """创建“历史记录”标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 历史记录文本框
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        layout.addWidget(self.history_text)

        # 底部按钮
        button_layout = QHBoxLayout()
        # Refresh History
        refresh_button = QPushButton(self.tr("🔄 刷新历史记录"))
        button_layout.addWidget(refresh_button)
        # Clear History
        clear_button = QPushButton(self.tr("🗑️ 清空历史记录"))
        button_layout.addWidget(clear_button)
        layout.addLayout(button_layout)

        # 连接信号
        refresh_button.clicked.connect(self.loadHistory)
        clear_button.clicked.connect(self.clearHistory)

        # 初始加载
        self.loadHistory()
        return widget

    def loadHistory(self):
        """从日志文件加载历史记录"""
        if os.path.exists(self.deactivation_log_path):
            with open(self.deactivation_log_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = self.tr("暂无历史记录")
        self.history_text.setText(content)

    def clearHistory(self):
        """清空历史记录"""
        # Confirm Clear, This will permanently delete all history logs.
        reply = QMessageBox.question(self._parent, self.tr("确认清空"),
                                     self.tr("此操作将永久删除所有历史日志。"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            open(self.deactivation_log_path, 'w', encoding='utf-8').close()
            self.loadHistory()
            # History cleared successfully.
            QMessageBox.information(self._parent, self.tr("成功"), self.tr("历史记录已成功清空。"))

    def logDeactivation(self, plugins):
        """记录停用操作到日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.deactivation_log_path, 'a', encoding='utf-8') as log_file:
            log_file.write(f"[{timestamp}] Deactivated plugins:\n")
            for plugin in plugins:
                log_file.write(f"  - {plugin}\n")
            log_file.write("\n")

    def logRestoration(self, plugins):
        """记录还原操作到日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.deactivation_log_path, 'a', encoding='utf-8') as log_file:
            log_file.write(f"[{timestamp}] Restored plugins:\n")
            for plugin in plugins:
                log_file.write(f"  - {plugin}\n")
            log_file.write("\n")

    def updateDataFile(self, plugins):
        """更新插件数据文件，记录停用插件的元信息"""
        if os.path.exists(self.deactivation_data_path):
            with open(self.deactivation_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}

        for plugin in plugins:
            mod_name = self._organizer.pluginList().origin(plugin)
            if mod_name not in data:
                data[mod_name] = {}
            data[mod_name][plugin] = {
                'deactivated_at': datetime.now().isoformat(),
                'original_mod': mod_name
            }

        with open(self.deactivation_data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def tr(self, text):
        """翻译函数（此处直接返回中文，实际项目中可接入Qt翻译系统）"""
        return QCoreApplication.translate("PluginManagerPro", text)

    def createSortAnalysisTab(self):
        """创建'排序分析'标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 顶部面板：扫描按钮
        top_panel = QHBoxLayout()
        # Scan Plugin List
        scan_button = QPushButton(self.tr("🔍 扫描插件列表"))
        scan_button.setStyleSheet("QPushButton { padding: 8px; font-weight: bold; }")
        scan_button.setFixedHeight(40)
        scan_button.setFixedWidth(250)
        top_panel.addWidget(scan_button)
        
        # 问题数量标签
        self.sort_problem_count_label = QLabel(self.tr("点击扫描以检查问题"))
        self.sort_problem_count_label.setStyleSheet("font-weight: bold; color: gray; padding: 5px;")
        top_panel.addWidget(self.sort_problem_count_label)
        
        top_panel.addStretch()
        layout.addLayout(top_panel)

        # 主分割器
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ====== 左侧面板 ======
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 问题插件标题
        plugins_label = QLabel(self.tr("⚠️ 存在依赖排序问题的插件："))
        plugins_label.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 5px;")
        left_layout.addWidget(plugins_label)
        
        # 搜索框
        self.sort_search_box = QLineEdit()
        self.sort_search_box.setPlaceholderText(self.tr("🔍 搜索插件..."))
        self.sort_search_box.setFixedHeight(30)
        left_layout.addWidget(self.sort_search_box)
        
        # 问题插件列表
        self.sort_problem_list = QListWidget()
        self.sort_problem_list.setAlternatingRowColors(True)
        self.sort_problem_list.itemSelectionChanged.connect(self.updateSortDependencyTree)
        left_layout.addWidget(self.sort_problem_list, 1)
        
        # 添加到面板
        left_panel.setLayout(left_layout)
        main_splitter.addWidget(left_panel)

        # ====== 右侧面板 ======
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 依赖树标题
        tree_label = QLabel(self.tr("🌳 依赖树："))
        tree_label.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 5px;")
        right_layout.addWidget(tree_label)
        
        # 依赖树（添加第四列"排序"）
        self.sort_dependency_tree = QTreeWidget()
        self.sort_dependency_tree.setHeaderLabels([
            self.tr("插件"), 
            self.tr("状态"), 
            self.tr("信息"),
            self.tr("排序")
        ])
        self.sort_dependency_tree.setColumnWidth(0, 200)
        self.sort_dependency_tree.setColumnWidth(1, 100)
        self.sort_dependency_tree.setColumnWidth(2, 150)
        self.sort_dependency_tree.setColumnWidth(3, 150)
        right_layout.addWidget(self.sort_dependency_tree, 1)

        # 设置上下文菜单策略
        self.sort_dependency_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sort_dependency_tree.customContextMenuRequested.connect(self.showTreeContextMenu)
    
        right_layout.addWidget(self.sort_dependency_tree, 1)
        
        # 添加到面板
        right_panel.setLayout(right_layout)
        main_splitter.addWidget(right_panel)

        # 设置分割器比例
        main_splitter.setSizes([450, 750])
        layout.addWidget(main_splitter, 1)
        
        # 连接信号
        scan_button.clicked.connect(self.performSortAnalysis)
        self.sort_search_box.textChanged.connect(self.filterSortPlugins)

        return widget

    # 新增方法：显示树状视图的右键菜单
    def showTreeContextMenu(self, position):
        # 获取当前选中的项
        item = self.sort_dependency_tree.itemAt(position)
        if not item:
            return
            
        # 从第一列获取完整的插件名称
        plugin_name = item.text(0)
        
        # 创建菜单
        menu = QMenu(self.sort_dependency_tree)
        
        # 添加复制插件名称操作
        copy_action = menu.addAction(self.tr("复制插件名称"))
        
        # 显示菜单并等待用户选择
        action = menu.exec(self.sort_dependency_tree.viewport().mapToGlobal(position))
        
        # 处理用户选择
        if action == copy_action:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(plugin_name)
        
    def performSortAnalysis(self):
        """执行排序分析扫描"""
        self.sort_problem_list.clear()
        self.sort_dependency_tree.clear()
        
        # 获取所有激活插件
        all_plugins = self._organizer.pluginList().pluginNames()
        active_plugins = [
            p for p in all_plugins
            if self._organizer.pluginList().state(p) == mobase.PluginState.ACTIVE
        ]
        
        # 存储问题插件
        problem_plugins = {}
        
        for plugin in active_plugins:
            plugin_priority = self._organizer.pluginList().priority(plugin)
            masters = self._organizer.pluginList().masters(plugin)
            
            for master in masters:
                if master in active_plugins:
                    master_priority = self._organizer.pluginList().priority(master)
                    
                    # 检查排序问题: 插件优先级高于主插件优先级
                    if plugin_priority < master_priority:
                        problem_key = f"{plugin} -> {master}"
                        problem_plugins[problem_key] = {
                            'plugin': plugin,
                            'master': master,
                            'plugin_priority': plugin_priority,
                            'master_priority': master_priority
                        }
        
        # 显示结果
        if not problem_plugins:
            self.sort_problem_count_label.setText(self.tr("✅ 未发现排序问题"))
            self.sort_problem_count_label.setStyleSheet("font-weight: bold; color: green;")
            return
        
        self.sort_problem_count_label.setText(
            self.tr(f"⚠️ 发现 {len(problem_plugins)} 个排序问题")
        )
        self.sort_problem_count_label.setStyleSheet("font-weight: bold; color: red;")
        
        # 添加到列表
        for key, data in problem_plugins.items():
            item = QListWidgetItem(
                f"{data['plugin']} (优先级:{data['plugin_priority']}) -> "
                f"{data['master']} (优先级:{data['master_priority']})"
            )
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.sort_problem_list.addItem(item)

    def updateSortDependencyTree(self):
        """更新排序依赖树视图"""
        self.sort_dependency_tree.clear()
        selected_items = self.sort_problem_list.selectedItems()
        
        if not selected_items:
            return
            
        # 获取选中的问题信息
        problem_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
        plugin_name = problem_data['plugin']
        master_name = problem_data['master']
        
        # 创建根节点
        root = QTreeWidgetItem(self.sort_dependency_tree)
        root.setText(0, plugin_name)
        root.setBackground(0, QColor("#3498db"))
        root.setForeground(0, QColor("white"))
        root.setText(1, "🎯 目标")
        
        # 添加问题master节点（红色加粗显示）
        master_item = QTreeWidgetItem(root)
        master_item.setText(0, master_name)
        
        # 设置排序问题显示（加粗红色）
        problem_text = f"⚠ 问题: {plugin_name}在{master_name}之前加载"
        problem_font = QFont()
        problem_font.setBold(True)
        
        # 插件优先级显示
        plugin_priority = QTreeWidgetItem(master_item)
        plugin_priority.setText(0, plugin_name)
        plugin_priority.setText(3, f"{problem_data['plugin_priority']}")
        plugin_priority.setFont(3, problem_font)
        plugin_priority.setForeground(3, QColor("red"))
        
        # 主插件优先级显示
        master_priority = QTreeWidgetItem(master_item)
        master_priority.setText(0, master_name)
        master_priority.setText(3, f"{problem_data['master_priority']}")
        master_priority.setFont(3, problem_font)
        master_priority.setForeground(3, QColor("red"))
        
        # 显示依赖数量
        master_item.setText(2, problem_text)
        master_item.setFont(2, problem_font)
        master_item.setForeground(2, QColor("red"))
        
        # 展开树
        self.sort_dependency_tree.expandAll()

    def filterSortPlugins(self, text):
        """根据文本过滤排序问题列表"""
        text = text.lower()
        
        for i in range(self.sort_problem_list.count()):
            item = self.sort_problem_list.item(i)
            item_text = item.text().lower()
            item.setHidden(text not in item_text)

def createPlugin():
    return PluginManagerPro()