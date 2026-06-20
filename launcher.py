
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

import gi
import requests

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

try:
    import minecraft_launcher_lib
except ImportError:
    minecraft_launcher_lib = None


APP_NAME = "OSML"
APP_ID = "OSML"
MINECRAFT_DIR = Path.home() / ".minecraft"
CONFIG_DIR = Path.home() / ".config" / APP_ID
SETTINGS_FILE = CONFIG_DIR / "settings.json"
OPTIFINE_DOWNLOADS_URL = "https://optifine.net/downl1oads"

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

class ScrollableComboBoxText(Gtk.Box):

    def __init__(self, max_visible_rows: int = POPUP_MAX_VISIBLE_ROWS) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._items: list[str] = []
        self._active_index: int = -1
        self._max_visible_rows = max_visible_rows
        self._signal_handlers: list[Callable[["ScrollableComboBoxText"], None]] = []
        self._row_height_px = 30

        self._button = Gtk.MenuButton()
        self._button_label = Gtk.Label(xalign=0)
        self._button_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._button.add(self._button_label)
        self.pack_start(self._button, True, True, 0)

        self._popover = Gtk.Popover()
        self._popover.set_relative_to(self._button)
        self._button.set_popover(self._popover)

        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scrolled.set_propagate_natural_height(True)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.connect("row-activated", self._on_row_activated)
        self._scrolled.add(self._list_box)
        self._popover.add(self._scrolled)

        self._update_button_label()

    def set_hexpand(self, expand: bool) -> None:
        Gtk.Box.set_hexpand(self, expand)
        self._button.set_hexpand(expand)

    def set_sensitive(self, sensitive: bool) -> None:
        self._button.set_sensitive(sensitive)

    def connect_changed(self, callback: Callable[["ScrollableComboBoxText"], None]) -> None:
        self._signal_handlers.append(callback)

    def remove_all(self) -> None:
        self._items = []
        self._active_index = -1
        for child in list(self._list_box.get_children()):
            self._list_box.remove(child)
        self._update_button_label()

    def append_text(self, text: str) -> None:
        self._items.append(text)
        row_label = Gtk.Label(label=text, xalign=0)
        row_label.set_margin_start(8)
        row_label.set_margin_end(8)
        row_label.set_margin_top(6)
        row_label.set_margin_bottom(6)
        row = Gtk.ListBoxRow()
        row.add(row_label)
        row.show_all()
        self._list_box.add(row)
        self._resize_popup()

    def get_active(self) -> int:
        return self._active_index

    def set_active(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            self._active_index = -1
        else:
            self._active_index = index
            row = self._list_box.get_row_at_index(index)
            if row is not None:
                self._list_box.select_row(row)
        self._update_button_label()
        for handler in self._signal_handlers:
            handler(self)

    def _on_row_activated(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._active_index = row.get_index()
        self._update_button_label()
        self._popover.popdown()
        for handler in self._signal_handlers:
            handler(self)

    def _update_button_label(self) -> None:
        if 0 <= self._active_index < len(self._items):
            self._button_label.set_text(self._items[self._active_index])
        else:
            self._button_label.set_text("")

    def _resize_popup(self) -> None:
        visible_rows = min(len(self._items), self._max_visible_rows)
        height = max(1, visible_rows) * self._row_height_px
        self._scrolled.set_min_content_height(height)
        self._scrolled.set_max_content_height(height)


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

    def _use_system_java_runtime(self) -> None: #ИГНОР СКАЧИВАНИЕ JAVA RUNTIME
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
        choices.extend(self._load_optifine_versions())

        seen: set[tuple[str, str, str | None]] = set()
        unique: list[VersionChoice] = []
        for choice in choices:
            key = (choice.kind, choice.minecraft_version, choice.loader_version)
            if key not in seen:
                seen.add(key)
                unique.append(choice)
        return unique

    def _load_vanilla_versions(self) -> list[VersionChoice]:
        versions = minecraft_launcher_lib.utils.get_version_list()
        releases = [item["id"] for item in versions if item.get("type") == "release"]
        return [
            VersionChoice(label=f"Vanilla {version}", kind="vanilla", minecraft_version=version)
            for version in releases[:80]
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
        for mc_version in mc_versions[:60]:
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

    def _load_optifine_versions(self) -> list[VersionChoice]:
        try:
            response = requests.get(OPTIFINE_DOWNLOADS_URL, timeout=15) # оптифайн апи не работает так что версии сами парсятся 
            response.raise_for_status()
        except Exception:
            return []

        html = response.text
        matches = re.findall(r"OptiFine_([0-9][0-9A-Za-z_.-]*)_(HD_U_[0-9A-Za-z_]+)\.jar", html)
        choices: list[VersionChoice] = []
        seen: set[tuple[str, str]] = set()
        for mc_version, loader_version in matches:
            key = (mc_version, loader_version)
            if key in seen:
                continue
            seen.add(key)
            installed = self._guess_optifine_profile(mc_version, loader_version)
            choices.append(
                VersionChoice(
                    label=f"OptiFine {mc_version} {loader_version}",
                    kind="optifine",
                    minecraft_version=mc_version,
                    loader_version=loader_version,
                    installed_version=installed,
                )
            )
        return choices[:80]

    def _guess_optifine_profile(self, mc_version: str, loader_version: str) -> str:
        likely = f"{mc_version}-OptiFine_{loader_version}"
        version_file = MINECRAFT_DIR / "versions" / likely / f"{likely}.json"
        if version_file.exists():
            return likely

        versions_dir = MINECRAFT_DIR / "versions"
        if versions_dir.exists():
            needle = f"{mc_version}-OptiFine"
            for child in versions_dir.iterdir():
                if child.is_dir() and child.name.startswith(needle):
                    return child.name
        return likely

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

        if choice.kind in {"forge", "neoforge"}:
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

        if choice.kind == "optifine":
            installed = choice.installed_version or self._guess_optifine_profile(
                choice.minecraft_version, choice.loader_version or ""
            )
            if self._version_profile_exists(installed): #если версия есть то оставялем
                return installed
            raise RuntimeError(
                "OptiFine is listed, but its installer is not automated here. "
                "Install this OptiFine version once with the official installer, "
                "then start it from this launcher."
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
        clean_name = re.sub(r"[^A-Za-z0-9_]", "", username).strip() or "Player" # если игрок напишет ник с неподдерживаемыми символами игра крашнется
        offline_uuid = uuid.UUID(hashlib.md5(clean_name.encode("utf-8")).hexdigest()) #UUID будет работать если игра оффлайн
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
            "launcherName": "pygobject-minecraft-starter",
            "launcherVersion": "1.0",
            "gameDirectory": str(MINECRAFT_DIR),
        }

    def java_path(self) -> str:
        """Public, debug-panel-friendly accessor for the resolved Java executable."""
        return self._java_path()

    def _java_path(self) -> str:
        java_path = shutil.which("java")   #ищем джаву
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


class LauncherWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title=APP_NAME)
        self.set_default_size(520, 240)
        self.set_border_width(18)

        self.backend = LauncherBackend(self.set_status_threadsafe, self.set_progress_threadsafe)
        self.choices: list[VersionChoice] = []
        self.settings = LauncherSettings.load()
        self.progress_max = 0
        self.last_command: list[str] | None = None
        self.last_error: str | None = None

        grid = Gtk.Grid(column_spacing=10, row_spacing=12)
        self.add(grid)

        title = Gtk.Label(label="Minecraft Starter")
        title.set_xalign(0)
        title.get_style_context().add_class("title")
        grid.attach(title, 0, 0, 2, 1)
        self.title_label = title

        self.version_row_label = Gtk.Label(xalign=0)
        grid.attach(self.version_row_label, 0, 1, 1, 1)
        self.version_combo = ScrollableComboBoxText()
        self.version_combo.set_hexpand(True)
        self.version_combo.connect_changed(lambda _combo: self.refresh_debug_panel())
        grid.attach(self.version_combo, 1, 1, 1, 1)

        self.username_row_label = Gtk.Label(xalign=0)
        grid.attach(self.username_row_label, 0, 2, 1, 1)
        self.username_entry = Gtk.Entry()
        self.username_entry.set_text(os.environ.get("USER", "Player")[:16])
        grid.attach(self.username_entry, 1, 2, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.settings_button = Gtk.Button.new_from_icon_name(
            "emblem-system-symbolic", Gtk.IconSize.BUTTON
        )
        self.settings_button.connect("clicked", self.on_settings)
        button_box.pack_start(self.settings_button, False, False, 0)

        self.open_button = Gtk.Button()
        self.open_button.connect("clicked", self.on_open_folder)
        button_box.pack_start(self.open_button, False, False, 0)

        self.start_button = Gtk.Button()
        self.start_button.connect("clicked", self.on_start_game)
        self.start_button.set_sensitive(False)
        button_box.pack_end(self.start_button, False, False, 0)
        grid.attach(button_box, 0, 3, 2, 1)

        self.progress = Gtk.ProgressBar()
        grid.attach(self.progress, 0, 4, 2, 1)

        self.status_label = Gtk.Label(xalign=0)
        grid.attach(self.status_label, 0, 5, 2, 1)

        self.debug_frame = Gtk.Frame()
        self.debug_frame.set_shadow_type(Gtk.ShadowType.IN)
        self.debug_label_widget = Gtk.Label(xalign=0)
        self.debug_label_widget.get_style_context().add_class("title")
        self.debug_value_label = Gtk.Label(xalign=0)
        self.debug_value_label.set_selectable(True)
        self.debug_value_label.set_line_wrap(True)
        self.debug_value_label.set_xalign(0)
        self.debug_value_label.set_valign(Gtk.Align.START)

        self.debug_scrolled = Gtk.ScrolledWindow()
        self.debug_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.debug_scrolled.set_min_content_height(80)
        self.debug_scrolled.set_vexpand(True)
        self.debug_scrolled.add(self.debug_value_label)

        debug_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        debug_box.set_border_width(8)
        debug_box.pack_start(self.debug_label_widget, False, False, 0)
        debug_box.pack_start(self.debug_scrolled, True, True, 0)
        self.debug_frame.add(debug_box)
        self.debug_frame.set_vexpand(True)
        grid.attach(self.debug_frame, 0, 6, 2, 1)
        self.debug_frame.set_no_show_all(True)

        self.connect("destroy", Gtk.main_quit)
        self.apply_language()
        self.status_label.set_text(self.tr("loading_versions"))
        self.refresh_debug_panel()
        self.load_versions_async()

    def tr(self, key: str, **kwargs: object) -> str:
        strings = LANGUAGES.get(self.settings.language, LANGUAGES[DEFAULT_LANGUAGE])
        text = strings.get(key, LANGUAGES[DEFAULT_LANGUAGE].get(key, key))
        return text.format(**kwargs) if kwargs else text

    def apply_language(self) -> None:
        self.title_label.set_text(self.tr("window_title"))
        self.version_row_label.set_text(self.tr("version_label"))
        self.username_row_label.set_text(self.tr("username_label"))
        self.settings_button.set_tooltip_text(self.tr("settings_tooltip"))
        self.open_button.set_label(self.tr("open_folder"))
        self.start_button.set_label(self.tr("start_game"))
        self.debug_label_widget.set_text(self.tr("debug_label"))
        if self.choices:
            self.status_label.set_text(self.tr("loaded_versions", count=len(self.choices)))
        self.refresh_debug_panel()

    def refresh_debug_panel(self) -> None:
        if not self.settings.debug_enabled:
            self.debug_frame.hide()
            return

        self.debug_frame.set_no_show_all(False)
        self.debug_frame.show_all()

        none_text = self.tr("debug_none")

        index = self.version_combo.get_active() if hasattr(self, "version_combo") else -1
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
            f"{self.tr('debug_selected_version')}: "
            f"{choice.label if choice else none_text}",
            f"{self.tr('debug_kind')}: {choice.kind if choice else none_text}",
            f"{self.tr('debug_mc_version')}: "
            f"{choice.minecraft_version if choice else none_text}",
            f"{self.tr('debug_loader_version')}: "
            f"{choice.loader_version if choice and choice.loader_version else none_text}",
            f"{self.tr('debug_ram')}: {self.settings.ram_mb} MB",
            f"{self.tr('debug_resolution')}: "
            f"{self.settings.window_width}x{self.settings.window_height}",
            f"{self.tr('debug_last_command')}: {command_text}",
            f"{self.tr('debug_last_error')}: {self.last_error or none_text}",
        ]
        self.debug_value_label.set_text("\n".join(lines))

    def load_versions_async(self) -> None:
        self.set_busy(True)
        thread = threading.Thread(target=self._load_versions_worker, daemon=True)
        thread.start()

    def _load_versions_worker(self) -> None:
        try:
            choices = self.backend.load_versions()
            GLib.idle_add(self.set_versions, choices)
        except Exception as exc:
            GLib.idle_add(self.show_error, str(exc))
        finally:
            GLib.idle_add(self.set_busy, False)

    def set_versions(self, choices: list[VersionChoice]) -> None:
        self.choices = choices
        self.version_combo.remove_all()
        for choice in choices:
            self.version_combo.append_text(choice.label)
        if choices:
            self.version_combo.set_active(0)
            self.start_button.set_sensitive(True)
            self.status_label.set_text(self.tr("loaded_versions", count=len(choices)))
        else:
            self.status_label.set_text(self.tr("no_versions"))
        self.refresh_debug_panel()

    def on_open_folder(self, _button: Gtk.Button) -> None:
        MINECRAFT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(MINECRAFT_DIR)])
        except Exception:
            webbrowser.open(MINECRAFT_DIR.as_uri())

    def on_settings(self, _button: Gtk.Button) -> None:
        dialog = Gtk.Dialog(
            title=self.tr("settings_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button(self.tr("cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(self.tr("save"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_border_width(12)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        content.add(grid)

        ram_label = Gtk.Label(label=self.tr("ram_label"), xalign=0)
        grid.attach(ram_label, 0, 0, 1, 1)
        self.ram_spin = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.ram_spin.set_value(max(1, self.settings.ram_mb // 1024))
        grid.attach(self.ram_spin, 1, 0, 1, 1)

        width_label = Gtk.Label(label=self.tr("width_label"), xalign=0)
        grid.attach(width_label, 0, 1, 1, 1)

        width_spin = Gtk.SpinButton.new_with_range(320, 7680, 16)
        width_spin.set_value(self.settings.window_width)
        self.window_width_spin = width_spin
        grid.attach(width_spin, 1, 1, 1, 1)

        height_label = Gtk.Label(label=self.tr("height_label"), xalign=0)
        grid.attach(height_label, 0, 2, 1, 1)

        height_spin = Gtk.SpinButton.new_with_range(240, 4320, 16)
        height_spin.set_value(self.settings.window_height)
        self.window_height_spin = height_spin
        grid.attach(height_spin, 1, 2, 1, 1)

        language_label = Gtk.Label(label=self.tr("language_label"), xalign=0)
        grid.attach(language_label, 0, 3, 1, 1)

        language_combo = Gtk.ComboBoxText()
        language_codes = list(LANGUAGES.keys())
        for code in language_codes:
            language_combo.append_text(LANGUAGES[code]["name"])
        current_index = (
            language_codes.index(self.settings.language)
            if self.settings.language in language_codes
            else 0
        )
        language_combo.set_active(current_index)
        self.language_combo = language_combo
        self._language_codes = language_codes
        grid.attach(language_combo, 1, 3, 1, 1)

        debug_check = Gtk.CheckButton(label=self.tr("debug_enabled"))
        debug_check.set_active(self.settings.debug_enabled)
        self.debug_check = debug_check
        grid.attach(debug_check, 0, 4, 2, 1)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            selected_index = self.language_combo.get_active()
            selected_language = (
                self._language_codes[selected_index]
                if 0 <= selected_index < len(self._language_codes)
                else self.settings.language
            )
            self.settings = LauncherSettings(
                ram_mb=int(self.ram_spin.get_value()) * 1024,
                window_width=int(self.window_width_spin.get_value()),
                window_height=int(self.window_height_spin.get_value()),
                language=selected_language,
                debug_enabled=self.debug_check.get_active(),
            )
            try:
                self.settings.save()
                self.apply_language()
                self.status_label.set_text(self.tr("settings_saved"))
            except Exception as exc:
                self.show_error(self.tr("settings_save_error", error=exc))
        dialog.destroy()

    def on_start_game(self, _button: Gtk.Button) -> None:
        index = self.version_combo.get_active()
        if index < 0 or index >= len(self.choices):  #если версии нет то не запускаем
            self.show_error(self.tr("choose_version_first"))
            return

        username = self.username_entry.get_text()
        self.set_busy(True)
        self.progress.set_fraction(0)
        thread = threading.Thread( #поток чтоб gtk не зависал
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
                on_command=lambda command: GLib.idle_add(self._record_command, command),
            )
            self.last_error = None
            GLib.idle_add(self.status_label.set_text, self.tr("game_started"))
        except Exception as exc:
            self.last_error = str(exc)
            GLib.idle_add(self.show_error, str(exc))
        finally:
            GLib.idle_add(self.set_busy, False)
            GLib.idle_add(self.refresh_debug_panel)

    def _record_command(self, command: list[str]) -> None:
        self.last_command = command
        self.refresh_debug_panel()

    def set_busy(self, busy: bool) -> None:
        self.version_combo.set_sensitive(not busy)
        self.username_entry.set_sensitive(not busy)
        self.settings_button.set_sensitive(not busy)
        self.open_button.set_sensitive(not busy)
        self.start_button.set_sensitive((not busy) and bool(self.choices))

    def set_status_threadsafe(self, text: str) -> None:
        GLib.idle_add(self.status_label.set_text, text)

    def set_progress_threadsafe(self, value: int, max_value: int) -> None:
        def update() -> None:
            if max_value >= 0:
                self.progress_max = max_value
            if value >= 0 and self.progress_max > 0:
                self.progress.set_fraction(min(value / self.progress_max, 1.0))

        GLib.idle_add(update)

    def show_error(self, message: str) -> None:
        self.last_error = message
        self.status_label.set_text(message)
        self.refresh_debug_panel()
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=self.tr("launcher_error"),
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def main() -> None:
    window = LauncherWindow()
    window.show_all()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        Gtk.main_quit()


if __name__ == "__main__":
    main()