"""The window's texts, by key, in English and Russian (decision 0014, item 28), and its counts
(item 29), and the units of a size. Placeholders are the same in both languages; ``{n}`` is a
count's number."""

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
    "overview.folders": {"en": "Folders to scan", "ru": "Папки для сканирования"},
    "overview.add": {"en": "Add folder…", "ru": "Добавить папку…"},
    "overview.remove": {"en": "Remove folder", "ru": "Убрать папку"},
    "overview.scan": {"en": "Scan", "ru": "Сканировать"},
    "overview.none": {"en": "Not scanned yet.", "ru": "Сканирования ещё не было."},
    "overview.level": {"en": "{level}: {files}, {size}", "ru": "{level}: {files}, {size}"},
    "overview.duplicates": {"en": "Duplicate groups: {n}", "ru": "Групп дубликатов: {n}"},
    "overview.skipped": {"en": "Skipped paths: {n}", "ru": "Пропущено путей: {n}"},
    "overview.unreliable": {
        "en": "Files in use cannot be recognized on this system, so nothing can be moved to the"
        " quarantine.",
        "ru": "На этой системе нельзя распознать открытые файлы, поэтому ничего нельзя"
        " переместить в карантин.",
    },
    "task.scan": {"en": "Scanning", "ru": "Сканирование"},
    "findings.tree": {"en": "Findings", "ru": "Находки"},
    "findings.path": {"en": "Path", "ru": "Путь"},
    "findings.level": {"en": "Level", "ru": "Уровень"},
    "findings.size": {"en": "Size", "ru": "Размер"},
    "findings.group": {"en": "{reason}: {files}, {size}", "ru": "{reason}: {files}, {size}"},
    "findings.search": {"en": "Search the paths", "ru": "Поиск по путям"},
    "findings.select": {"en": "Select all: {level}", "ru": "Выбрать все: {level}"},
    "findings.clear": {"en": "Clear selection", "ru": "Снять выбор"},
    "findings.selected": {"en": "Selected: {files}, {size}", "ru": "Выбрано: {files}, {size}"},
    "findings.move": {"en": "Move to quarantine", "ru": "Переместить в карантин"},
    "detail.path": {"en": "Path: {path}", "ru": "Путь: {path}"},
    "detail.size": {"en": "Size: {size}", "ru": "Размер: {size}"},
    "detail.modified": {"en": "Modified: {moment}", "ru": "Изменён: {moment}"},
    "detail.level": {"en": "Level: {level}", "ru": "Уровень: {level}"},
    "detail.reason": {"en": "{reason}: {detail}", "ru": "{reason}: {detail}"},
    "detail.kept": {
        "en": "This copy stays: the others are its duplicates.",
        "ru": "Эта копия остаётся: остальные — её дубликаты.",
    },
    "move.confirm": {
        "en": "Move {files} ({size}) to the quarantine? They can be restored from the Quarantine"
        " page.",
        "ru": "Переместить {files} ({size}) в карантин? Их можно вернуть на странице «Карантин».",
    },
    "task.quarantine": {"en": "Moving to quarantine", "ru": "Перемещение в карантин"},
    "move.moved": {
        "en": "Moved to the quarantine: {files}, {size}",
        "ru": "Перемещено в карантин: {files}, {size}",
    },
    "move.refused": {"en": "Refused: {path} ({reason})", "ru": "Отказано: {path} ({reason})"},
    "move.stopped": {
        "en": "Stopped: {error}. The files that had moved were put back.",
        "ru": "Остановлено: {error}. Уже перемещённые файлы возвращены на место.",
    },
    "session.unfinished": {
        "en": "Unfinished work ({domains}) comes first: nothing was changed. Use Recover.",
        "ru": "Сначала нужно завершить прерванную работу ({domains}): ничего не изменено."
        " Используйте «Восстановить после сбоя».",
    },
    "session.no_check": {
        "en": "No reliable open-file check on this system: nothing was moved.",
        "ru": "На этой системе нет надёжной проверки открытых файлов: ничего не перемещено.",
    },
    "session.failed": {"en": "{failure}: {detail}", "ru": "{failure}: {detail}"},
    "folder.title": {"en": "Choose a folder to scan", "ru": "Выберите папку для сканирования"},
    "folder.path": {"en": "Folder", "ru": "Папка"},
    "folder.add": {"en": "Add", "ru": "Добавить"},
}

# Sizes: bytes, then binary multiples; the decimal separator of each language.
UNITS: dict[str, tuple[str, ...]] = {
    "en": ("B", "KiB", "MiB", "GiB", "TiB"),
    "ru": ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"),
}
DECIMAL: dict[str, str] = {"en": ".", "ru": ","}

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
