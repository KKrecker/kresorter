"""The window's texts, by key, in English and Russian (decision 0014, item 28), and its counts
(item 29). Placeholders are the same in both languages; ``{n}`` is a count's number."""

from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {
    "app.title": {"en": "safeclean", "ru": "safeclean"},
    "page.overview": {"en": "Overview", "ru": "Обзор"},
    "page.findings": {"en": "Findings", "ru": "Находки"},
    "page.quarantine": {"en": "Quarantine", "ru": "Карантин"},
    "page.organize": {"en": "Organize", "ru": "Сортировка"},
    "page.autostart": {"en": "Autostart", "ru": "Автозагрузка"},
    "page.settings": {"en": "Settings", "ru": "Настройки"},
    "button.cancel": {"en": "Cancel", "ru": "Отмена"},
    "task.running": {"en": "Running: {task}", "ru": "Выполняется: {task}"},
    "task.failed": {"en": "{task} failed: {message}", "ru": "Ошибка ({task}): {message}"},
    "close.wait": {
        "en": "{task} is still running; the window closes when it ends.",
        "ru": "Ещё выполняется: {task}. Окно закроется, когда это завершится.",
    },
    "overview.folder": {"en": "Folder {folder}", "ru": "Папка {folder}"},
}

PLURALS: dict[str, dict[str, tuple[str, ...]]] = {
    "file": {"en": ("{n} file", "{n} files"), "ru": ("{n} файл", "{n} файла", "{n} файлов")},
    "folder": {
        "en": ("{n} folder", "{n} folders"),
        "ru": ("{n} папка", "{n} папки", "{n} папок"),
    },
    "entry": {
        "en": ("{n} entry", "{n} entries"),
        "ru": ("{n} запись", "{n} записи", "{n} записей"),
    },
    "batch": {
        "en": ("{n} batch", "{n} batches"),
        "ru": ("{n} пакет", "{n} пакета", "{n} пакетов"),
    },
    "group": {
        "en": ("{n} group", "{n} groups"),
        "ru": ("{n} группа", "{n} группы", "{n} групп"),
    },
    "path": {"en": ("{n} path", "{n} paths"), "ru": ("{n} путь", "{n} пути", "{n} путей")},
}
