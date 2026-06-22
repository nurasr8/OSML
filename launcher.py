from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
import wx
import wx.lib.scrolledpanel

try:
    import minecraft_launcher_lib
except ImportError:
    minecraft_launcher_lib = None


APP_NAME = "OSML"
APP_ID = "OSML"
MINECRAFT_DIR = Path.home() / ".minecraft"
CONFIG_DIR = Path.home() / ".config" / APP_ID
SETTINGS_FILE = CONFIG_DIR / "settings.json"

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {
        "name": "English",
        "window_title": "Minecraft Starter",
        "version_label": "Version",
        "username_label": "Username",
        "settings_tooltip": "Settings",
        "open_folder": "Open Minecraft Folder",
        "start_game": "Start Game",
        "loading_versions": "Loading versions...",
        "loaded_versions": "Loaded {count} versions",
        "no_versions": "No versions loaded. Check the internet connection.",
        "settings_title": "Settings",
        "cancel": "Cancel",
        "save": "Save",
        "ram_label": "RAM (GiB)",
        "width_label": "Width",
        "height_label": "Height",
        "language_label": "Language",
        "settings_saved": "Settings saved",
        "settings_save_error": "Could not save settings: {error}",
        "choose_version_first": "Choose a version first.",
        "game_started": "Game started",
        "launcher_error": "Launcher error",
        "debug_label": "Debug info",
        "debug_enabled": "Show debug panel",
        "debug_minecraft_dir": "Minecraft folder",
        "debug_config_file": "Settings file",
        "debug_java_path": "Java path",
        "debug_selected_version": "Selected version",
        "debug_kind": "Kind",
        "debug_mc_version": "Minecraft version",
        "debug_loader_version": "Loader version",
        "debug_ram": "RAM",
        "debug_resolution": "Resolution",
        "debug_last_command": "Last launch command",
        "debug_last_error": "Last error",
        "debug_none": "(none)",
        "debug_not_started": "(not started yet)",
    },
    "ru": {
        "name": "Русский",
        "window_title": "Запуск Minecraft",
        "version_label": "Версия",
        "username_label": "Имя пользователя",
        "settings_tooltip": "Настройки",
        "open_folder": "Открыть папку Minecraft",
        "start_game": "Запустить игру",
        "loading_versions": "Загрузка версий...",
        "loaded_versions": "Загружено версий: {count}",
        "no_versions": "Версии не загружены. Проверьте подключение к интернету.",
        "settings_title": "Настройки",
        "cancel": "Отмена",
        "save": "Сохранить",
        "ram_label": "ОЗУ (ГиБ)",
        "width_label": "Ширина",
        "height_label": "Высота",
        "language_label": "Язык",
        "settings_saved": "Настройки сохранены",
        "settings_save_error": "Не удалось сохранить настройки: {error}",
        "choose_version_first": "Сначала выберите версию.",
        "game_started": "Игра запущена",
        "launcher_error": "Ошибка запуска",
        "debug_label": "Отладочная информация",
        "debug_enabled": "Показывать панель отладки",
        "debug_minecraft_dir": "Папка Minecraft",
        "debug_config_file": "Файл настроек",
        "debug_java_path": "Путь к Java",
        "debug_selected_version": "Выбранная версия",
        "debug_kind": "Тип",
        "debug_mc_version": "Версия Minecraft",
        "debug_loader_version": "Версия загрузчика",
        "debug_ram": "ОЗУ",
        "debug_resolution": "Разрешение",
        "debug_last_command": "Последняя команда запуска",
        "debug_last_error": "Последняя ошибка",
        "debug_none": "(нет)",
        "debug_not_started": "(ещё не запускалось)",
    },
}
DEFAULT_LANGUAGE = "en"

POPUP_MAX_VISIBLE_ROWS = 10


@dataclass(frozen=True)
class VersionChoice:
    label: str
    kind: str
    minecraft_version: str
    loader_version: str | None = None
    installed_version: str | None = None


@dataclass
class LauncherSettings:
    ram_mb: int = 2048
    window_width: int = 854
    window_height: int = 480
    language: str = DEFAULT_LANGUAGE
    debug_enabled: bool = False

    @classmethod
    def load(cls) -> "LauncherSettings":
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return cls()
        except Exception:
            return cls()

        try:
            language = str(raw.get("language", cls.language))
            if language not in LANGUAGES:
                language = DEFAULT_LANGUAGE
            return cls(
                ram_mb=max(512, int(raw.get("ram_mb", cls.ram_mb))),
                window_width=max(320, int(raw.get("window_width", cls.window_width))),
                window_height=max(240, int(raw.get("window_height", cls.window_height))),
                language=language,
                debug_enabled=bool(raw.get("debug_enabled", cls.debug_enabled)),
            )
        except Exception:
            return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "ram_mb": int(self.ram_mb),
            "window_width": int(self.window_width),
            "window_height": int(self.window_height),
            "language": self.language,
            "debug_enabled": bool(self.debug_enabled),
        }
        with SETTINGS_FILE.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)


class LauncherBackend:
    def __init__(self, status: Callable[[str], None], progress: Callable[[int, int], None]):
        self.status = status
        self.progress = progress
        self._runtime_install_patched = False
        MINECRAFT_DIR.mkdir(parents=True, exist_ok=True)

    def require_library(self) -> None:
        if minecraft_launcher_lib is None:
            raise RuntimeError(
                "Missing dependency: minecraft-launcher-lib. "
                "Install it with: python3 -m pip install -r requirements.txt"
            )
        self._use_system_java_runtime()

    def _use_system_java_runtime(self) -> None:
        if self._runtime_install_patched:
            return

        def skip_runtime_install(*_args: object, **_kwargs: object) -> None:
            return None

        minecraft_launcher_lib.install.install_jvm_runtime = skip_runtime_install
        self._runtime_install_patched = True

    def callback(self) -> dict[str, Callable]:
        return {
            "setStatus": lambda text: self.status(str(text)),
            "setProgress": lambda value: self.progress(int(value), -1),
            "setMax": lambda value: self.progress(-1, int(value)),
        }

    def load_versions(self) -> list[VersionChoice]:
        self.require_library()
        choices: list[VersionChoice] = []

        choices.extend(self._load_vanilla_versions())
        choices.extend(self._load_loader_versions("forge"))
        choices.extend(self._load_loader_versions("neoforge"))
        choices.extend(self._load_loader_versions("fabric"))

        seen: set[tuple[str, str, str | None]] = set()
        unique: list[VersionChoice] = []
        for choice in choices:
            key = (choice.kind, choice.minecraft_version, choice.loader_version)
            if key not in seen:
                seen.add(key)
                unique.append(choice)

        return self._group_by_minecraft_version(unique)

    _KIND_ORDER = {"vanilla": 0, "forge": 1, "fabric": 2, "neoforge": 4}

    def _group_by_minecraft_version(
        self, choices: list[VersionChoice]
    ) -> list[VersionChoice]:
        """Order choices as: for each Minecraft version (newest first) —
        Vanilla, Forge, NeoForge — then the next Minecraft version, etc."""

        def mc_sort_key(version: str) -> tuple:
            parts = re.split(r"[.\-]", version)
            key = []
            for part in parts:
                if part.isdigit():
                    key.append((0, int(part)))
                else:
                    key.append((1, part))
            return tuple(key)

        versions_order = sorted(
            {choice.minecraft_version for choice in choices},
            key=mc_sort_key,
            reverse=True,
        )

        grouped: dict[str, list[VersionChoice]] = {version: [] for version in versions_order}
        for choice in choices:
            grouped[choice.minecraft_version].append(choice)

        ordered: list[VersionChoice] = []
        for version in versions_order:
            group = grouped[version]
            group.sort(key=lambda c: self._KIND_ORDER.get(c.kind, 99))
            ordered.extend(group)
        return ordered

    def _load_vanilla_versions(self) -> list[VersionChoice]:
        versions = minecraft_launcher_lib.utils.get_version_list()
        releases = [item["id"] for item in versions if item.get("type") == "release"]
        return [
            VersionChoice(label=f"Vanilla {version}", kind="vanilla", minecraft_version=version)
            for version in releases
        ]

    def _load_loader_versions(self, loader_id: str) -> list[VersionChoice]:
        try:
            loader = minecraft_launcher_lib.mod_loader.get_mod_loader(loader_id)
        except Exception:
            return []

        try:
            mc_versions = loader.get_minecraft_versions(True)
        except Exception:
            return []

        choices: list[VersionChoice] = []
        for mc_version in mc_versions:
            try:
                loader_version = loader.get_latest_loader_version(mc_version)
                installed = loader.get_installed_version(mc_version, loader_version)
            except Exception:
                continue
            name = loader.get_name()
            choices.append(
                VersionChoice(
                    label=f"{name} {mc_version} ({loader_version})",
                    kind=loader_id,
                    minecraft_version=mc_version,
                    loader_version=loader_version,
                    installed_version=installed,
                )
            )
        return choices

    def install_choice(self, choice: VersionChoice) -> str:
        self.require_library()
        callback = self.callback()

        if choice.kind == "vanilla":
            if self._version_launch_files_present(choice.minecraft_version):
                return choice.minecraft_version
            self.status(f"Installing Vanilla {choice.minecraft_version}")
            minecraft_launcher_lib.install.install_minecraft_version(
                choice.minecraft_version, str(MINECRAFT_DIR), callback=callback
            )
            return choice.minecraft_version

        if choice.kind in {"forge", "neoforge", "fabric"}:
            installed = choice.installed_version
            if installed and self._version_launch_files_present(installed):
                return installed

            self.status(f"Installing {choice.kind.title()} {choice.minecraft_version}")
            loader = minecraft_launcher_lib.mod_loader.get_mod_loader(choice.kind)
            return loader.install(
                choice.minecraft_version,
                str(MINECRAFT_DIR),
                loader_version=choice.loader_version,
                callback=callback,
            )

        raise RuntimeError(f"Unsupported version kind: {choice.kind}")

    def start_game(
        self,
        choice: VersionChoice,
        username: str,
        settings: LauncherSettings,
        on_command: Callable[[list[str]], None] | None = None,
    ) -> subprocess.Popen:
        installed_version = self.install_choice(choice)
        self.status(f"Starting {installed_version}")

        options = self._offline_options(username, settings)
        command = minecraft_launcher_lib.command.get_minecraft_command(
            installed_version, str(MINECRAFT_DIR), options
        )
        if on_command is not None:
            on_command(list(command))
        try:
            popen_kwargs: dict[str, object] = {
                "cwd": str(MINECRAFT_DIR),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            return subprocess.Popen(command, **popen_kwargs)
        except FileNotFoundError as exc:
            executable = command[0] if command else str(exc.filename)
            raise RuntimeError(
                f"Could not start Minecraft because '{executable}' was not found. "
                "Install Java with: sudo apt install default-jre"
            ) from exc

    def _offline_options(self, username: str, settings: LauncherSettings) -> dict[str, object]:
        clean_name = re.sub(r"[^A-Za-z0-9_]", "", username).strip() or "Player"
        offline_uuid = uuid.UUID(hashlib.md5(clean_name.encode("utf-8")).hexdigest())
        java_path = self._java_path()
        return {
            "username": clean_name[:16],
            "uuid": offline_uuid.hex,
            "token": "0",
            "executablePath": java_path,
            "defaultExecutablePath": java_path,
            "jvmArguments": [f"-Xmx{settings.ram_mb}M"],
            "customResolution": True,
            "resolutionWidth": str(settings.window_width),
            "resolutionHeight": str(settings.window_height),
            "launcherName": "wxPython-minecraft-starter",
            "launcherVersion": "1.0",
            "gameDirectory": str(MINECRAFT_DIR),
        }

    def java_path(self) -> str:
        """Public, debug-panel-friendly accessor for the resolved Java executable."""
        return self._java_path()

    def _java_path(self) -> str:
        java_path = shutil.which("java")
        if java_path:
            return java_path

        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidate = Path(java_home) / "bin" / "java"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

        raise RuntimeError(
            "Java is required to start Minecraft, but no 'java' executable was found. "
            "Install it with: sudo apt install default-jre"
        )

    def _version_profile_exists(self, version: str) -> bool:
        return (MINECRAFT_DIR / "versions" / version / f"{version}.json").exists()

    def _version_launch_files_present(self, version: str) -> bool:
        version_dir = MINECRAFT_DIR / "versions" / version
        version_file = version_dir / f"{version}.json"
        if not version_file.is_file():
            return False

        try:
            with version_file.open("r", encoding="utf-8") as handle:
                version_data = json.load(handle)
            if "inheritsFrom" in version_data:
                version_data = minecraft_launcher_lib._helper.inherit_json(
                    version_data, str(MINECRAFT_DIR)
                )
        except Exception:
            return False

        jar_version = version_data.get("jar", version_data.get("id", version))
        if not (MINECRAFT_DIR / "versions" / jar_version / f"{jar_version}.jar").is_file():
            return False

        if not self._version_libraries_present(version_data):
            return False

        if self._version_needs_natives(version_data):
            natives_dir = MINECRAFT_DIR / "versions" / version_data["id"] / "natives"
            if not natives_dir.is_dir() or not any(natives_dir.iterdir()):
                return False

        assets_id = version_data.get("assets")
        if assets_id and not (MINECRAFT_DIR / "assets" / "indexes" / f"{assets_id}.json").is_file():
            return False

        return True

    def _version_libraries_present(self, version_data: dict[str, object]) -> bool:
        try:
            for library in version_data.get("libraries", []):
                if "rules" in library and not minecraft_launcher_lib._helper.parse_rule_list(
                    library["rules"], {}
                ):
                    continue

                native = minecraft_launcher_lib.natives.get_natives(library)
                if native == "":
                    library_path = minecraft_launcher_lib._helper.get_library_path(
                        library["name"], str(MINECRAFT_DIR)
                    )
                    if not Path(library_path).is_file():
                        return False
                    continue

                downloads = library.get("downloads", {})
                classifiers = downloads.get("classifiers", {})
                if native in classifiers and "path" in classifiers[native]:
                    native_path = MINECRAFT_DIR / "libraries" / classifiers[native]["path"]
                else:
                    native_path = Path(
                        minecraft_launcher_lib._helper.get_library_path(
                            f"{library['name']}-{native}", str(MINECRAFT_DIR)
                        )
                    )

                if not Path(native_path).is_file():
                    return False
        except Exception:
            return False

        return True

    def _version_needs_natives(self, version_data: dict[str, object]) -> bool:
        try:
            for library in version_data.get("libraries", []):
                if minecraft_launcher_lib.natives.get_natives(library) != "":
                    return True
        except Exception:
            return False
        return False


class LauncherWindow(wx.Frame):
    def __init__(self) -> None:
        super().__init__(parent=None, title=APP_NAME, size=(854, 480))

        self.backend = LauncherBackend(self.set_status_threadsafe, self.set_progress_threadsafe)
        self.choices: list[VersionChoice] = []
        self.settings = LauncherSettings.load()
        self.progress_max = 0
        self.last_command: list[str] | None = None
        self.last_error: str | None = None

        # Create main panel
        main_panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_panel.SetSizer(main_sizer)

        # Title
        title_font = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title = wx.StaticText(main_panel, label="Minecraft Starter")
        title.SetFont(title_font)
        main_sizer.Add(title, 0, wx.ALL | wx.EXPAND, 10)

        # Version selection
        self.version_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.version_row_label = wx.StaticText(main_panel, label=self.tr("version_label"))
        self.version_sizer.Add(self.version_row_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.version_combo = wx.ComboBox(main_panel, style=wx.CB_READONLY)
        self.version_combo.Bind(wx.EVT_COMBOBOX, self.on_version_changed)
        self.version_sizer.Add(self.version_combo, 1, wx.EXPAND)
        main_sizer.Add(self.version_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Username selection
        self.username_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.username_row_label = wx.StaticText(main_panel, label=self.tr("username_label"))
        self.username_sizer.Add(self.username_row_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.username_entry = wx.TextCtrl(main_panel, value=os.environ.get("USER", "Player")[:16])
        self.username_sizer.Add(self.username_entry, 1, wx.EXPAND)
        main_sizer.Add(self.username_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Buttons
        self.button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.settings_button = wx.Button(main_panel, label="⚙️ " + self.tr("settings_tooltip"))
        self.settings_button.Bind(wx.EVT_BUTTON, self.on_settings)
        self.button_sizer.Add(self.settings_button, 0, wx.RIGHT, 5)

        self.open_button = wx.Button(main_panel, label="📁 " + self.tr("open_folder"))
        self.open_button.Bind(wx.EVT_BUTTON, self.on_open_folder)
        self.button_sizer.Add(self.open_button, 0, wx.RIGHT, 5)

        self.button_sizer.AddStretchSpacer()

        self.start_button = wx.Button(main_panel, label="▶️ " + self.tr("start_game"))
        self.start_button.Bind(wx.EVT_BUTTON, self.on_start_game)
        self.start_button.Enable(False)
        self.button_sizer.Add(self.start_button, 0)
        main_sizer.Add(self.button_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Progress bar
        self.progress = wx.Gauge(main_panel, range=100)
        main_sizer.Add(self.progress, 0, wx.ALL | wx.EXPAND, 10)

        # Status label
        self.status_label = wx.StaticText(main_panel, label=self.tr("loading_versions"))
        main_sizer.Add(self.status_label, 0, wx.ALL | wx.EXPAND, 10)

        # Debug panel
        self.debug_frame = wx.StaticBoxSizer(wx.VERTICAL, main_panel, self.tr("debug_label"))
        self.debug_value_label = wx.TextCtrl(main_panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        self.debug_frame.Add(self.debug_value_label, 1, wx.EXPAND)
        main_sizer.Add(self.debug_frame, 0, wx.ALL | wx.EXPAND, 10)
        self.debug_frame.ShowItems(False)

        self.apply_language()
        self.refresh_debug_panel()
        self.load_versions_async()

        # Center and show
        self.Centre()
        self.Show()

    def tr(self, key: str, **kwargs: object) -> str:
        strings = LANGUAGES.get(self.settings.language, LANGUAGES[DEFAULT_LANGUAGE])
        text = strings.get(key, LANGUAGES[DEFAULT_LANGUAGE].get(key, key))
        return text.format(**kwargs) if kwargs else text

    def apply_language(self) -> None:
        self.SetTitle(self.tr("window_title"))
        # Labels — invalidate so the sizer can recalculate their width
        self.version_row_label.SetLabel(self.tr("version_label"))
        self.version_row_label.InvalidateBestSize()
        self.version_sizer.Layout()
        self.username_row_label.SetLabel(self.tr("username_label"))
        self.username_row_label.InvalidateBestSize()
        self.username_sizer.Layout()
        # Debug panel title
        self.debug_frame.GetStaticBox().SetLabel(self.tr("debug_label"))
        # Buttons
        self.settings_button.SetLabel("⚙️ " + self.tr("settings_tooltip"))
        self.settings_button.SetToolTip(self.tr("settings_tooltip"))
        self.open_button.SetLabel("📁 " + self.tr("open_folder"))
        self.start_button.SetLabel("▶️ " + self.tr("start_game"))
        for btn in (self.settings_button, self.open_button, self.start_button):
            btn.InvalidateBestSize()
            btn.SetSize(btn.GetBestSize())
        self.button_sizer.Layout()
        if self.choices:
            self.status_label.SetLabel(self.tr("loaded_versions", count=len(self.choices)))
        self.refresh_debug_panel()

    def refresh_debug_panel(self) -> None:
        if not self.settings.debug_enabled:
            self.debug_frame.ShowItems(False)
            return

        self.debug_frame.ShowItems(True)

        none_text = self.tr("debug_none")
        index = self.version_combo.GetSelection() if self.version_combo else -1
        choice = self.choices[index] if 0 <= index < len(self.choices) else None

        try:
            java_path = self.backend.java_path()
        except Exception as exc:
            java_path = f"{none_text} ({exc})"

        if self.last_command:
            command_text = " ".join(self.last_command)
        else:
            command_text = self.tr("debug_not_started")

        lines = [
            f"{self.tr('debug_minecraft_dir')}: {MINECRAFT_DIR}",
            f"{self.tr('debug_config_file')}: {SETTINGS_FILE}",
            f"{self.tr('debug_java_path')}: {java_path}",
            f"{self.tr('debug_selected_version')}: {choice.label if choice else none_text}",
            f"{self.tr('debug_kind')}: {choice.kind if choice else none_text}",
            f"{self.tr('debug_mc_version')}: {choice.minecraft_version if choice else none_text}",
            f"{self.tr('debug_loader_version')}: {choice.loader_version if choice and choice.loader_version else none_text}",
            f"{self.tr('debug_ram')}: {self.settings.ram_mb} MB",
            f"{self.tr('debug_resolution')}: {self.settings.window_width}x{self.settings.window_height}",
            f"{self.tr('debug_last_command')}: {command_text}",
            f"{self.tr('debug_last_error')}: {self.last_error or none_text}",
        ]
        self.debug_value_label.SetValue("\n".join(lines))

    def on_version_changed(self, event: wx.Event) -> None:
        self.refresh_debug_panel()

    def load_versions_async(self) -> None:
        self.set_busy(True)
        thread = threading.Thread(target=self._load_versions_worker, daemon=True)
        thread.start()

    def _load_versions_worker(self) -> None:
        try:
            choices = self.backend.load_versions()
            wx.CallAfter(self.set_versions, choices)
        except Exception as exc:
            wx.CallAfter(self.show_error, str(exc))
        finally:
            wx.CallAfter(self.set_busy, False)

    def set_versions(self, choices: list[VersionChoice]) -> None:
        self.choices = choices
        self.version_combo.Clear()
        for choice in choices:
            self.version_combo.Append(choice.label)
        if choices:
            self.version_combo.SetSelection(0)
            self.start_button.Enable(True)
            self.status_label.SetLabel(self.tr("loaded_versions", count=len(choices)))
        else:
            self.status_label.SetLabel(self.tr("no_versions"))
        self.refresh_debug_panel()

    def on_open_folder(self, event: wx.Event) -> None:
        MINECRAFT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == 'nt':
                os.startfile(str(MINECRAFT_DIR))
            elif os.name == 'posix':
                subprocess.Popen(["xdg-open", str(MINECRAFT_DIR)])
        except Exception:
            webbrowser.open(MINECRAFT_DIR.as_uri())

    def on_settings(self, event: wx.Event) -> None:
        dialog = wx.Dialog(self, title=self.tr("settings_title"))
        sizer = wx.BoxSizer(wx.VERTICAL)

        # RAM settings
        ram_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ram_label = wx.StaticText(dialog, label=self.tr("ram_label"))
        ram_sizer.Add(ram_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        ram_spin = wx.SpinCtrl(dialog, value=str(max(1, self.settings.ram_mb // 1024)), min=1, max=32)
        ram_sizer.Add(ram_spin, 1, wx.EXPAND)
        sizer.Add(ram_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Width settings
        width_sizer = wx.BoxSizer(wx.HORIZONTAL)
        width_label = wx.StaticText(dialog, label=self.tr("width_label"))
        width_sizer.Add(width_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        width_spin = wx.SpinCtrl(dialog, value=str(self.settings.window_width), min=320, max=7680)
        width_sizer.Add(width_spin, 1, wx.EXPAND)
        sizer.Add(width_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Height settings
        height_sizer = wx.BoxSizer(wx.HORIZONTAL)
        height_label = wx.StaticText(dialog, label=self.tr("height_label"))
        height_sizer.Add(height_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        height_spin = wx.SpinCtrl(dialog, value=str(self.settings.window_height), min=240, max=4320)
        height_sizer.Add(height_spin, 1, wx.EXPAND)
        sizer.Add(height_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Language settings
        language_sizer = wx.BoxSizer(wx.HORIZONTAL)
        language_label = wx.StaticText(dialog, label=self.tr("language_label"))
        language_sizer.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        language_combo = wx.ComboBox(dialog, style=wx.CB_READONLY)
        language_codes = list(LANGUAGES.keys())
        for code in language_codes:
            language_combo.Append(LANGUAGES[code]["name"])
        current_index = (
            language_codes.index(self.settings.language)
            if self.settings.language in language_codes
            else 0
        )
        language_combo.SetSelection(current_index)
        language_sizer.Add(language_combo, 1, wx.EXPAND)
        sizer.Add(language_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Debug checkbox
        debug_check = wx.CheckBox(dialog, label=self.tr("debug_enabled"))
        debug_check.SetValue(self.settings.debug_enabled)
        sizer.Add(debug_check, 0, wx.ALL, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(dialog, wx.ID_OK, self.tr("save"))
        cancel_button = wx.Button(dialog, wx.ID_CANCEL, self.tr("cancel"))
        ok_button.Bind(wx.EVT_BUTTON, lambda e: dialog.EndModal(wx.ID_OK))
        cancel_button.Bind(wx.EVT_BUTTON, lambda e: dialog.EndModal(wx.ID_CANCEL))
        button_sizer.Add(ok_button, 0, wx.RIGHT, 5)
        button_sizer.Add(cancel_button, 0)
        sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        dialog.SetSizer(sizer)
        dialog.Fit()
        dialog.SetMinSize(dialog.GetSize())
        dialog.Centre()

        if dialog.ShowModal() == wx.ID_OK:
            selected_index = language_combo.GetSelection()
            selected_language = (
                language_codes[selected_index]
                if 0 <= selected_index < len(language_codes)
                else self.settings.language
            )
            self.settings = LauncherSettings(
                ram_mb=int(ram_spin.GetValue()) * 1024,
                window_width=int(width_spin.GetValue()),
                window_height=int(height_spin.GetValue()),
                language=selected_language,
                debug_enabled=debug_check.GetValue(),
            )
            try:
                self.settings.save()
                self.apply_language()
                self.status_label.SetLabel(self.tr("settings_saved"))
            except Exception as exc:
                self.show_error(self.tr("settings_save_error", error=exc))
        dialog.Destroy()

    def on_start_game(self, event: wx.Event) -> None:
        index = self.version_combo.GetSelection()
        if index < 0 or index >= len(self.choices):
            self.show_error(self.tr("choose_version_first"))
            return

        username = self.username_entry.GetValue()
        self.set_busy(True)
        self.progress.SetValue(0)
        thread = threading.Thread(
            target=self._start_worker,
            args=(self.choices[index], username, self.settings),
            daemon=True,
        )
        thread.start()

    def _start_worker(
        self, choice: VersionChoice, username: str, settings: LauncherSettings
    ) -> None:
        try:
            self.backend.start_game(
                choice,
                username,
                settings,
                on_command=lambda command: wx.CallAfter(self._record_command, command),
            )
            self.last_error = None
            wx.CallAfter(self.status_label.SetLabel, self.tr("game_started"))
        except Exception as exc:
            self.last_error = str(exc)
            wx.CallAfter(self.show_error, str(exc))
        finally:
            wx.CallAfter(self.set_busy, False)
            wx.CallAfter(self.refresh_debug_panel)

    def _record_command(self, command: list[str]) -> None:
        self.last_command = command
        self.refresh_debug_panel()

    def set_busy(self, busy: bool) -> None:
        self.version_combo.Enable(not busy)
        self.username_entry.Enable(not busy)
        self.settings_button.Enable(not busy)
        self.open_button.Enable(not busy)
        self.start_button.Enable((not busy) and bool(self.choices))

    def set_status_threadsafe(self, text: str) -> None:
        wx.CallAfter(self.status_label.SetLabel, text)

    def set_progress_threadsafe(self, value: int, max_value: int) -> None:
        def update() -> None:
            if max_value >= 0:
                self.progress_max = max_value
            if value >= 0 and self.progress_max > 0:
                self.progress.SetValue(min(int(value * 100 / self.progress_max), 100))

        wx.CallAfter(update)

    def show_error(self, message: str) -> None:
        self.last_error = message
        self.status_label.SetLabel(message)
        self.refresh_debug_panel()
        dialog = wx.MessageDialog(
            self,
            message,
            self.tr("launcher_error"),
            wx.OK | wx.ICON_ERROR,
        )
        dialog.ShowModal()
        dialog.Destroy()


class LauncherApp(wx.App):
    def OnInit(self) -> bool:
        self.frame = LauncherWindow()
        return True


def main() -> None:
    app = LauncherApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
