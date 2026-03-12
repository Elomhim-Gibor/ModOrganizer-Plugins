# coding=utf-8

# 移除requests库依赖，使用标准库urllib
import zipfile
import io
import os
import json
import urllib.request
import urllib.error
import ssl # 添加 ssl 模块
import time
import tempfile
import shutil
import threading
import re
import webbrowser # 添加 webbrowser 导入
from urllib.parse import urlparse

try:
    import PyQt6.QtWidgets as QtWidgets
    import PyQt6.QtGui as QtGui
    from PyQt6.QtCore import QCoreApplication, Qt, QThread, pyqtSignal
except ImportError:
    import PyQt5.QtWidgets as QtWidgets
    import PyQt5.QtGui as QtGui
    from PyQt5.QtCore import QCoreApplication, Qt, QThread, pyqtSignal

# 更新检查器类，用于后台检查更新
class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str, str)  # 版本, 更新日志, 下载URL
    no_update = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, current_version, version_url, changelog_url): # 添加 changelog_url
        super().__init__()
        self.current_version = current_version
        self.version_url = version_url
        self.changelog_url = changelog_url # 存储 changelog_url
        self.max_retries = 3
        self.retry_delay = 2  # 秒
        
    def run(self):
        retry_count = 0
        while retry_count < self.max_retries:
            try:
                # 设置请求头，模拟浏览器请求
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36"
                }
                req = urllib.request.Request(self.version_url, headers=headers)
                
                # 创建不验证 SSL 证书的上下文
                context = ssl._create_unverified_context()
                # 设置超时时间
                with urllib.request.urlopen(req, context=context, timeout=30) as response: # 增加超时到 30 秒
                    data = json.loads(response.read().decode('utf-8'))
                
                latest_version = data.get("version", "0.0.0")
                # changelog = data.get("changelog", "- 更新日志未提供") # 不再从 version url 获取
                download_url = data.get("download_url", "")
                
                if self._compare_versions(latest_version, self.current_version) > 0:
                    # 获取更新日志
                    changelog = self._fetch_changelog()
                    self.update_available.emit(latest_version, changelog, download_url)
                else:
                    self.no_update.emit()
                return
            except urllib.error.URLError as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    self.error_occurred.emit(f"网络连接错误: {str(e)}")
                else:
                    time.sleep(self.retry_delay)
            except Exception as e:
                self.error_occurred.emit(f"检查更新时发生错误: {str(e)}")
                return
    
    def _compare_versions(self, version1, version2):
        """比较两个版本号，如果version1大于version2返回1，相等返回0，小于返回-1"""
        v1_parts = list(map(int, version1.split('.')))
        v2_parts = list(map(int, version2.split('.')))
        
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1 = v1_parts[i] if i < len(v1_parts) else 0
            v2 = v2_parts[i] if i < len(v2_parts) else 0
            
            if v1 > v2:
                return 1
            elif v1 < v2:
                return -1
        
        return 0

    def _fetch_changelog(self):
        """从指定的URL获取更新日志文本"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36"
            }
            req = urllib.request.Request(self.changelog_url, headers=headers)
            # 创建不验证 SSL 证书的上下文
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=context, timeout=30) as response: # 增加超时到 30 秒
                # 假设 changelog 是纯文本
                changelog_content = response.read().decode('utf-8')
                return changelog_content.strip() if changelog_content else "- 未能获取更新日志"
        except Exception as e:
            print(f"获取更新日志失败: {str(e)}")
            return f"- 未能获取更新日志 ({str(e)})"

# 下载器类，用于后台下载文件
class Downloader(QThread):
    progress_updated = pyqtSignal(int)
    download_complete = pyqtSignal(str)
    download_error = pyqtSignal(str)
    
    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        
    def run(self):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36"
            }
            
            req = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                # 获取文件大小
                file_size = int(response.headers.get('Content-Length', 0))
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    downloaded = 0
                    block_size = 8192
                    
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                            
                        downloaded += len(buffer)
                        temp_file.write(buffer)
                        
                        # 更新进度
                        if file_size > 0:
                            progress = int((downloaded / file_size) * 100)
                            self.progress_updated.emit(progress)
                
                # 下载完成后，备份原文件并替换
                if os.path.exists(self.save_path):
                    backup_path = self.save_path + ".bak"
                    shutil.copy2(self.save_path, backup_path)
                
                # 移动临时文件到目标位置
                shutil.move(temp_file.name, self.save_path)
                self.download_complete.emit(self.save_path)
                
        except Exception as e:
            self.download_error.emit(str(e))

class Network:
    def __init__(self, controller, version, update_server_url, changelog_url): # 添加 controller 参数
        self.controller = controller # 存储 controller 实例
        self.version = version
        self.update_server_url = update_server_url
        self.changelog_url = changelog_url # 存储 changelog_url
        self.update_checker = None
        self.downloader = None

    def check_for_updates(self, parent_window=None):
        """
        检查更新并显示更新对话框
        
        Args:
            parent_window: 父窗口，用于显示进度对话框
        """
        # 创建进度对话框
        progress_dialog = QtWidgets.QProgressDialog("正在检查更新...", "取消", 0, 100, parent_window)
        progress_dialog.setWindowTitle("插件更新")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setAutoClose(False)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)
        progress_dialog.show()
        
        # 创建更新检查器
        self.update_checker = UpdateChecker(self.version, self.update_server_url, self.changelog_url) # 传递 changelog_url
        
        # 连接信号
        self.update_checker.update_available.connect(
            lambda version, changelog, url: self._handle_update_available(version, changelog, url, progress_dialog, parent_window)
        )
        self.update_checker.no_update.connect(
            lambda: self._handle_no_update(progress_dialog, parent_window)
        )
        self.update_checker.error_occurred.connect(
            lambda error: self._handle_update_error(error, progress_dialog, parent_window)
        )
        
        # 启动检查
        self.update_checker.start()

    def _handle_update_available(self, version, changelog, download_url, progress_dialog, parent_window):
        """处理发现新版本的情况"""
        progress_dialog.setLabelText(f"发现新版本: {version}")
        
        # 询问用户是否更新
        result = QtWidgets.QMessageBox.question(
            parent_window,
            "发现新版本",
            f"发现新版本: {version}\n\n更新内容:\n{changelog}\n\n是否立即更新?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if result == QtWidgets.QMessageBox.Yes:
            # 如果没有提供下载URL，使用默认URL
            if not download_url:
                download_url = f"{self.update_server_url}/download"
                
            # 开始下载
            progress_dialog.setLabelText("正在下载更新...")
            self.download_and_install_update(download_url, progress_dialog, parent_window)
        else:
            progress_dialog.close()

    def _handle_no_update(self, progress_dialog, parent_window):
        """处理无需更新的情况"""
        progress_dialog.close()
        QtWidgets.QMessageBox.information(
            parent_window,
            "无需更新",
            "当前插件已是最新版本。"
        )

    def _handle_update_error(self, error, progress_dialog, parent_window):
        """处理更新检查错误的情况"""
        progress_dialog.close()
        QtWidgets.QMessageBox.critical(
            parent_window,
            "更新检查失败",
            f"检查更新时发生错误: {error}"
        )

    def download_and_install_update(self, update_package_url, progress_dialog=None, parent_window=None):
        """
        下载更新包并替换文件
        
        Args:
            update_package_url: 更新包URL
            progress_dialog: 进度对话框
            parent_window: 父窗口
        """
        try:
            # 确保URL格式正确
            if not update_package_url.startswith(('http://', 'https://')):
                update_package_url = f"{self.update_server_url}/{update_package_url.lstrip('/')}"
            
            # 获取当前脚本路径
            # 获取当前脚本所在目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 构建 consolidation_controller.py 的完整路径
            target_file_path = os.path.join(current_dir, "consolidation_controller.py")
            # 使用 target_file_path 作为保存路径 (需要修改下一行使用此变量)
            
            # 创建下载器
            self.downloader = Downloader(update_package_url, target_file_path) # 使用修正后的路径
            
            # 连接信号
            if progress_dialog:
                self.downloader.progress_updated.connect(progress_dialog.setValue)
            
            self.downloader.download_complete.connect(
                lambda path: self._handle_download_complete(path, self.version, progress_dialog, parent_window)
            )
            self.downloader.download_error.connect(
                lambda error: self._handle_download_error(error, progress_dialog, parent_window)
            )
            
            # 启动下载
            self.downloader.start()
            
        except Exception as e:
            if progress_dialog:
                progress_dialog.close()
                
            error_msg = f"下载更新失败: {str(e)}"
            if parent_window:
                QtWidgets.QMessageBox.critical(
                    parent_window,
                    "更新失败",
                    error_msg
                )
            else:
                print(error_msg)

    def _handle_download_complete(self, path, version, progress_dialog, parent_window):
        """处理下载完成的情况"""
        if progress_dialog:
            progress_dialog.close()

        # 更新内存中的版本号 (Network 实例的)
        self.version = version

        # --- 添加调用 controller 更新 ini 文件 ---
        try:
            print(f"准备调用 controller.update_local_version_in_config 更新版本为: {version}")
            self.controller.update_local_version_in_config(version)
            print(f"成功调用 controller 更新本地版本配置。")
        except AttributeError:
            print("错误: 传入的 controller 对象没有 update_local_version_in_config 方法。")
        except Exception as e:
            print(f"调用 controller.update_local_version_in_config 时出错: {e}")
        # --- 结束添加 ---

        success_msg = f"插件已更新到版本 {version}。\n本地版本记录已更新。\n原始文件已备份为 {path}.bak\n请重启Mod Organizer以应用更新。"
        
        if parent_window:
            QtWidgets.QMessageBox.information(
                parent_window,
                "更新成功",
                success_msg
            )
        else:
            print(success_msg)

    def _handle_download_error(self, error, progress_dialog, parent_window):
        """处理下载错误的情况"""
        if progress_dialog:
            progress_dialog.close()

        # 定义网盘链接
        manual_download_url = "https://pan.baidu.com/s/1AqS8bhhdW34C_AT-2BbBJQ?pwd=xcfn"

        # 修改错误信息
        error_msg = f"自动下载更新失败: {error}\n\n请手动下载更新包，并将其内容解压覆盖到插件目录。\n\n点击“确定”后将尝试打开网盘链接。"

        if parent_window:
            # 显示修改后的错误信息
            QtWidgets.QMessageBox.critical(
                parent_window,
                "下载失败",
                error_msg
            )
            # 在用户点击确定后打开链接
            try:
                webbrowser.open(manual_download_url)
            except Exception as e:
                print(f"无法打开浏览器链接: {e}")
                QtWidgets.QMessageBox.warning(
                    parent_window,
                    "无法打开链接",
                    f"无法自动打开网盘链接。\n请手动复制链接并在浏览器中打开：\n{manual_download_url}"
                )
        else:
            print(error_msg)
            # 尝试在控制台打开链接（如果环境支持）
            try:
                webbrowser.open(manual_download_url)
                print(f"已尝试打开网盘链接: {manual_download_url}")
            except Exception as e:
                print(f"无法打开浏览器链接: {e}")
                print(f"请手动复制链接并在浏览器中打开： {manual_download_url}")