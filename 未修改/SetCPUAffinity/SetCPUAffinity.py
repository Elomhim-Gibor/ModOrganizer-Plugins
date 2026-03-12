# coding=utf-8

import os
import re
import json
import shutil
import webbrowser
import multiprocessing
from typing import List, Sequence, Union, Tuple, Dict, Optional
import configparser

import mobase

# ---------------------------
# Qt compat (PyQt6 préféré, fallback PyQt5)
# ---------------------------
try:
    from PyQt6 import QtGui, QtWidgets
    from PyQt6.QtCore import QCoreApplication, Qt, QUrl
    QMessageBox = QtWidgets.QMessageBox
    QIcon = QtGui.QIcon
    QWidget = QtWidgets.QWidget
    QVBoxLayout = QtWidgets.QVBoxLayout
    QHBoxLayout = QtWidgets.QHBoxLayout
    QLabel = QtWidgets.QLabel
    QPushButton = QtWidgets.QPushButton
    QComboBox = QtWidgets.QComboBox
    QLineEdit = QtWidgets.QLineEdit
    QPlainTextEdit = QtWidgets.QPlainTextEdit
    QClipboard = QtGui.QGuiApplication.clipboard

    class StandardButton:
        Ok       = QMessageBox.StandardButton.Ok
        No       = QMessageBox.StandardButton.No
        Cancel   = QMessageBox.StandardButton.Cancel
        Yes      = QMessageBox.StandardButton.Yes
        NoButton = QMessageBox.StandardButton.NoButton

    QT_IS_PYQT6 = True
except Exception:
    import PyQt5.QtGui as QtGui
    import PyQt5.QtWidgets as QtWidgets
    from PyQt5.QtCore import QCoreApplication, Qt, QUrl
    QMessageBox = QtWidgets.QMessageBox
    QIcon = QtGui.QIcon
    QWidget = QtWidgets.QWidget
    QVBoxLayout = QtWidgets.QVBoxLayout
    QHBoxLayout = QtWidgets.QHBoxLayout
    QLabel = QtWidgets.QLabel
    QPushButton = QtWidgets.QPushButton
    QComboBox = QtWidgets.QComboBox
    QLineEdit = QtWidgets.QLineEdit
    QPlainTextEdit = QtWidgets.QPlainTextEdit
    QClipboard = QtGui.QGuiApplication.clipboard

    class StandardButton:
        Ok       = QMessageBox.Ok
        No       = QMessageBox.No
        Cancel   = QMessageBox.Cancel
        Yes      = QMessageBox.Yes
        NoButton = QMessageBox.NoButton

    QT_IS_PYQT6 = False


# ---------------------------
# Plugin
# ---------------------------
class SetCPUAffinity(mobase.IPluginTool):
    NAME = "SetCPUAffinity"
    DISPLAY_NAME = "Set CPU Affinity"
    DESCRIPTION = (
        "Calculates and writes CPU affinity value for the SKSE plugin "
        "'Skyrim Priority SE AE' (PriorityMod.toml). Adds presets, preview and safer writes."
    )
    TOOLTIP = "Sets CPU affinity in SKSE\\Plugins\\PriorityMod.toml."

    # ---- UI Presets ----
    PRESET_ALL = "All cores"
    PRESET_SMT_FIRST = "1 thread per physical core (SMT off)"
    PRESET_EVEN = "Even logical indices (0,2,4,...)"
    PRESET_ODD = "Odd logical indices (1,3,5,...)"
    PRESET_CUSTOM = "Custom (hex mask)"

    # Set to True if PriorityMod.toml only supports 64-bit masks
    CLAMP_64_BITS = False

    def __init__(self):
        super().__init__()
        self.__organizer: Optional[mobase.IOrganizer] = None
        self.__config_path: str = ""
        self.__parentWidget: Optional[QWidget] = None
        self._plugin_path: str = ""
        self._ui: Dict[str, object] = {}  # store ui widgets
        self._cpu_count: int = max(1, os.cpu_count() or multiprocessing.cpu_count() or 1)

        # persistence (instance-wide)
        self._cfg_path: str = ""
        self._cfg: Dict[str, Union[str, Dict]] = {}

        # cache
        self._cached_current_mask: Optional[str] = None

        # texte courant à copier par le bouton "Copy Mask"
        self._copy_mask_text: str = ""

    # ---- MO2 meta ----
    def name(self) -> str:
        return self.NAME

    def author(self) -> str:
        return "MaskedRPGFan (orig) + Mo2 Plugin Generator"

    def description(self) -> str:
        return self.__tr(self.DESCRIPTION)

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(1, 3, 1)  # bumped

    def isActive(self) -> bool:
        try:
            return self.__organizer.pluginSetting(self.name(), "enabled") is True
        except Exception:
            return True

    def settings(self) -> List[mobase.PluginSetting]:
        # keep your single toggle; the rest is persisted in JSON
        return [mobase.PluginSetting("enabled", self.__tr("Enable this plugin"), True)]

    def displayName(self) -> str:
        return self.__tr(self.DISPLAY_NAME)

    def tooltip(self) -> str:
        return self.__tr(self.TOOLTIP)

    # ---- Init ----
    def init(self, organizer: mobase.IOrganizer):
        self.__organizer = organizer
        self._plugin_path = os.path.dirname(os.path.abspath(__file__))

        # instance-wide config path
        inst_root = os.path.join(self.__organizer.basePath(), "plugins", "SetCPUAffinity")
        os.makedirs(inst_root, exist_ok=True)
        self._cfg_path = os.path.join(inst_root, "config.json")
        self._cfg = self._load_cfg()

        return True

    # ---- Theme/Icon ----
    def is_theme_dark(self) -> str:
        config_obj = configparser.ConfigParser()
        try:
            config_obj.read(os.path.abspath(os.path.join(self.__organizer.pluginDataPath(), "..", "ModOrganizer.ini")))
        except Exception:
            return ""
        theme_name = config_obj.get("Settings", "style", fallback="").strip()
        return "dark" in theme_name.lower()

    def icon(self) -> QIcon:
        icon_filename = "CPUIconDark.png" if self.is_theme_dark() else "CPUIconWhite.png"
        icon_path = os.path.join(self._plugin_path, icon_filename)
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        else:
            print(f"[SetCPUAffinity] Icon file {icon_path} not found.")
            return QIcon()

    def setParentWidget(self, widget: QWidget) -> None:
        self.__parentWidget = widget

    # ---- File discovery ----
    def __findTomlConfig(self) -> str:
        plugin_rel_path = "SKSE/Plugins/"
        plugin_file = "PriorityMod.toml"
        result: Sequence[str] = self.__organizer.findFiles(plugin_rel_path, plugin_file)
        return result[0] if len(result) > 0 else ""

    # ---- UI ----
    def display(self) -> bool:
        self.__config_path = self.__findTomlConfig()
        if self.__config_path == "":
            QMessageBox.critical(
                self.__parentWidget,
                self.__tr("PriorityMod.toml is missing"),
                self.__tr(
                    "<a href='https://www.nexusmods.com/skyrimspecialedition/mods/50129'>"
                    "Skyrim Priority SE AE - skse plugin</a> not found or not enabled.\n"
                    "Please install/enable the mod and refresh MO2."
                ),
            )
            return False

        # window
        win = QWidget()
        win.setWindowTitle(self.DISPLAY_NAME)
        layout = QVBoxLayout(win)

        # Current affinity label
        current = self.__getCurrentAffinity()
        self._cached_current_mask = current or None
        lbl_cur = QLabel(self.__tr(f"Current affinity in TOML: {current or '(not set)'}"))
        lbl_path = QLabel(self.__tr(f"File: {self.__config_path}"))
        layout.addWidget(lbl_cur)
        layout.addWidget(lbl_path)

        # Preset row
        row_preset = QHBoxLayout()
        lbl_preset = QLabel(self.__tr("Preset:"))
        cb_preset = QComboBox()
        cb_preset.addItems([self.PRESET_ALL, self.PRESET_SMT_FIRST, self.PRESET_EVEN, self.PRESET_ODD, self.PRESET_CUSTOM])
        cb_preset.setCurrentText(self._cfg.get("preset", self.PRESET_SMT_FIRST))
        row_preset.addWidget(lbl_preset)
        row_preset.addWidget(cb_preset, 1)
        layout.addLayout(row_preset)

        # Custom mask row (only if preset=custom)
        row_mask = QHBoxLayout()
        lbl_mask = QLabel(self.__tr("Custom hex mask (e.g., 0x000000FF):"))
        # si un masque existant est valide → proposer comme custom par défaut
        default_custom = self._cfg.get("customMask", "")
        if not default_custom and self._cached_current_mask and self._parse_hex_mask(self._cached_current_mask) not in (None, 0):
            default_custom = self._cached_current_mask
        le_mask = QLineEdit(default_custom)
        row_mask.addWidget(lbl_mask)
        row_mask.addWidget(le_mask, 1)
        layout.addLayout(row_mask)

        # Preview area
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        layout.addWidget(preview, 1)

        # Buttons
        row_btns_top = QHBoxLayout()
        btn_open_folder = QPushButton(self.__tr("Open TOML Folder"))
        btn_copy_mask = QPushButton(self.__tr("Copy Mask"))
        # Connexion unique : le handler lira toujours la valeur la plus récente
        btn_copy_mask.clicked.connect(lambda: self._copy_to_clipboard(self._copy_mask_text))
        row_btns_top.addWidget(btn_open_folder)
        row_btns_top.addWidget(btn_copy_mask)
        row_btns_top.addStretch(1)
        layout.addLayout(row_btns_top)

        row_btns = QHBoxLayout()
        btn_apply = QPushButton(self.__tr("Apply"))
        btn_disable = QPushButton(self.__tr("Disable (set 0)"))
        btn_close = QPushButton(self.__tr("Close"))
        row_btns.addWidget(btn_apply)
        row_btns.addWidget(btn_disable)
        row_btns.addStretch(1)
        row_btns.addWidget(btn_close)
        layout.addLayout(row_btns)

        # store refs
        self._ui = {
            "win": win,
            "lbl_cur": lbl_cur,
            "cb_preset": cb_preset,
            "le_mask": le_mask,
            "row_mask": row_mask,
            "preview": preview,
        }

        # wire
        def toggle_custom_row():
            show = (cb_preset.currentText() == self.PRESET_CUSTOM)
            row_mask_parent = row_mask
            row_mask_parent.setEnabled(show)
            # on ne masque pas complètement pour garder le layout propre ; on peut aussi hide() si tu préfères :
            for i in range(row_mask_parent.count()):
                w = row_mask_parent.itemAt(i).widget()
                if w:
                    w.setVisible(show)

        def update_preview():
            preset = cb_preset.currentText()
            custom_hex = le_mask.text().strip()
            mask_hex, indices = self._calc_from_preset(preset, custom_hex)
            if mask_hex is None:
                mask_for_clip = ""
                lines = [
                    f"CPU count: {self._cpu_count}",
                    f"Preset: {preset}",
                    f"Mask: INVALID",
                    f"CPUs: []",
                ]
            else:
                # clamp 64 bits si activé
                mask_hex_eff, indices_eff = self._maybe_clamp(mask_hex, indices)
                mask_for_clip = mask_hex_eff
                lines = [
                    f"CPU count: {self._cpu_count}",
                    f"Preset: {preset}",
                    f"Mask: {mask_hex_eff}",
                    f"CPUs: {indices_eff}",
                ]
            preview.setPlainText("\n".join(lines))
            # Met simplement à jour la valeur utilisée par le bouton
            self._copy_mask_text = mask_for_clip

        def open_toml_folder():
            folder = os.path.dirname(self.__config_path)
            try:
                if os.name == "nt":
                    os.startfile(folder)  # type: ignore[attr-defined]
                else:
                    webbrowser.open(folder)
            except Exception:
                webbrowser.open(folder)

        cb_preset.currentTextChanged.connect(lambda _: (toggle_custom_row(), update_preview()))
        le_mask.textChanged.connect(lambda _: update_preview())
        btn_apply.clicked.connect(lambda: self._on_apply())
        btn_disable.clicked.connect(lambda: self._on_disable())
        btn_close.clicked.connect(win.close)
        btn_open_folder.clicked.connect(open_toml_folder)

        # initial state
        toggle_custom_row()
        update_preview()
        win.show()
        return True

    def _copy_to_clipboard(self, text: str):
        if not text:
            return
        try:
            QClipboard().setText(text)  # type: ignore[call-arg]
        except Exception:
            # fallback
            pass

    # ---- Actions ----
    def _on_apply(self):
        preset = self._ui["cb_preset"].currentText()
        custom_hex = self._ui["le_mask"].text().strip()
        mask_hex, indices = self._calc_from_preset(preset, custom_hex)
        if mask_hex is None:
            QMessageBox.warning(self._ui["win"], self.__tr("Invalid custom mask"), self.__tr("Please enter a valid hex mask (e.g. 0xFF)."))
            return

        mask_hex, indices = self._maybe_clamp(mask_hex, indices)

        ok, err = self.__setAffinity(mask_hex)
        if ok:
            self._cfg["preset"] = preset
            self._cfg["lastAppliedMask"] = mask_hex
            if preset == self.PRESET_CUSTOM:
                self._cfg["customMask"] = custom_hex
            self._save_cfg()
            QMessageBox.information(self._ui["win"], self.__tr("Success"), self.__tr(f"Affinity set to {mask_hex}"))
            self._ui["lbl_cur"].setText(self.__tr(f"Current affinity in TOML: {mask_hex}"))
        else:
            QMessageBox.critical(self._ui["win"], self.__tr("Write failed"), self.__tr(f"Could not write TOML:\n{err}"))

    def _on_disable(self):
        ok, err = self.__setAffinity("0")
        if ok:
            QMessageBox.information(self._ui["win"], self.__tr("Success"), self.__tr("Affinity set to 0 (disabled)."))
            self._ui["lbl_cur"].setText(self.__tr("Current affinity in TOML: 0"))
            self._cfg["lastAppliedMask"] = "0"
            self._save_cfg()
        else:
            QMessageBox.critical(self._ui["win"], self.__tr("Write failed"), self.__tr(f"Could not write TOML:\n{err}"))

    # ---- Affinity helpers ----
    def __getCurrentAffinity(self) -> str:
        path = self.__config_path or ""
        if not path or not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    # match 'affinity = 0x....' ignoring spaces and case
                    m = re.match(r"^\s*affinity\s*=\s*([^\s#;]+)", raw, flags=re.IGNORECASE)
                    if m:
                        return m.group(1).strip()
        except Exception as e:
            print(f"[SetCPUAffinity] Read failed: {e}")
        return ""

    def _calc_from_preset(self, preset: str, custom_hex: str) -> Tuple[Optional[str], List[int]]:
        n = self._cpu_count

        if preset == self.PRESET_ALL:
            indices = list(range(n))
        elif preset == self.PRESET_SMT_FIRST:
            # Heuristic : un thread par cœur (indices pairs). OK pour CPUs fréquents.
            indices = list(range(0, n, 2))
        elif preset == self.PRESET_EVEN:
            indices = list(range(0, n, 2))
        elif preset == self.PRESET_ODD:
            indices = list(range(1, n, 2))
        elif preset == self.PRESET_CUSTOM:
            mask = self._parse_hex_mask(custom_hex)
            if mask is None or mask <= 0:
                return None, []
            indices = [i for i in range(mask.bit_length()) if (mask >> i) & 1]
            return self._indices_to_hex(indices), indices
        else:
            indices = list(range(n))

        return self._indices_to_hex(indices), indices

    def _indices_to_hex(self, indices: List[int]) -> str:
        """Convertit une liste d’indices CPU -> masque hex (0x... en MAJ)."""
        if not indices:
            return "0"
        mask = 0
        for i in indices:
            if i >= 0:
                mask |= (1 << i)
        # largeur hex minimale 2 digits
        hex_len = max(2, ((mask.bit_length() + 3) // 4))
        return "0x" + f"{mask:0{hex_len}X}"

    def _parse_hex_mask(self, s: str) -> Optional[int]:
        s = s.strip()
        if not s:
            return None
        if s.lower().startswith("0x"):
            s = s[2:]
        if not s or any(c not in "0123456789abcdefABCDEF" for c in s):
            return None
        try:
            return int(s, 16)
        except Exception:
            return None

    def _maybe_clamp(self, mask_hex: str, indices: List[int]) -> Tuple[str, List[int]]:
        """
        Si CLAMP_64_BITS est True, on tronque le masque à 64 bits (pour plugins qui ne gèrent pas >64).
        """
        if not self.CLAMP_64_BITS:
            return mask_hex, indices
        val = self._parse_hex_mask(mask_hex)
        if val is None:
            return mask_hex, indices
        val &= (1 << 64) - 1
        indices = [i for i in indices if i < 64]
        hex_len = max(2, ((val.bit_length() + 3) // 4))
        return "0x" + f"{val:0{hex_len}X}", indices

    # ---- TOML write (safe) ----
    def __setAffinity(self, affinity: str = "0") -> Tuple[bool, str]:
        """Écrit/insère 'affinity = <affinity>' dans PriorityMod.toml, avec backup .bak."""
        path = self.__config_path
        if not path:
            return False, "Config path not set"
        if not os.path.exists(path):
            return False, f"File not found: {path}"

        # backup .bak
        try:
            bak = path + ".bak"
            shutil.copyfile(path, bak)
        except Exception as e:
            return False, f"Backup failed: {e}"

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            affinity_re = re.compile(r"^(\s*)affinity\s*=", flags=re.IGNORECASE)
            found = False
            new_lines: List[str] = []
            for line in lines:
                m = affinity_re.match(line)
                if (not found) and m:
                    indent = m.group(1) or ""
                    new_lines.append(f"{indent}affinity = {affinity}\n")
                    found = True
                else:
                    new_lines.append(line)

            if not found:
                # Insère après une clé voisine si possible
                inserted = False
                insert_after_keys = ["priority", "process", "settings"]
                key_re = re.compile(r"^\s*(" + "|".join(re.escape(k) for k in insert_after_keys) + r")\s*=", re.IGNORECASE)
                last_key_idx = -1
                for i, line in enumerate(new_lines):
                    if key_re.match(line):
                        last_key_idx = i
                if last_key_idx >= 0:
                    new_lines.insert(last_key_idx + 1, f"affinity = {affinity}\n")
                    inserted = True

                if not inserted:
                    # append at end with a separator
                    if new_lines and not new_lines[-1].endswith("\n"):
                        new_lines[-1] = new_lines[-1] + "\n"
                    new_lines.append(f"\n# Added by SetCPUAffinity\naffinity = {affinity}\n")

            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.replace(tmp, path)
            return True, ""
        except Exception as e:
            # restore backup on failure
            try:
                shutil.copyfile(path + ".bak", path)
            except Exception:
                pass
            return False, str(e)

    # ---- i18n ----
    def __tr(self, s):
        return QCoreApplication.translate(self.NAME, s)

    # ---- persistence (json) ----
    def _load_cfg(self) -> Dict[str, Union[str, Dict]]:
        try:
            if os.path.exists(self._cfg_path):
                with open(self._cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[SetCPUAffinity] Failed to load config.json: {e}")
        # defaults
        return {
            "preset": self.PRESET_SMT_FIRST,
            "customMask": "",
            "lastAppliedMask": ""
        }

    def _save_cfg(self):
        try:
            tmp = self._cfg_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._cfg_path)
        except Exception as e:
            print(f"[SetCPUAffinity] Failed to save config.json: {e}")


def createPlugin() -> mobase.IPlugin:
    return SetCPUAffinity()
