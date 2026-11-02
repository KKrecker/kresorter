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
    "quarantine.items": {"en": "Quarantined files", "ru": "Файлы в карантине"},
    "quarantine.id": {"en": "Id", "ru": "№"},
    "quarantine.original": {"en": "Original path", "ru": "Исходный путь"},
    "quarantine.size": {"en": "Size", "ru": "Размер"},
    "quarantine.total": {
        "en": "In the quarantine: {files}, {size}",
        "ru": "Сейчас в карантине: {files}, {size}",
    },
    "quarantine.refresh": {"en": "Refresh", "ru": "Обновить"},
    "quarantine.restore": {"en": "Restore", "ru": "Восстановить"},
    "quarantine.purge": {"en": "Delete permanently", "ru": "Удалить навсегда"},
    "quarantine.permanent": {"en": "Cannot be undone", "ru": "Необратимо"},
    "quarantine.no_check": {
        "en": "No reliable open-file check on this system: the quarantine cannot be used.",
        "ru": "На этой системе нет надёжной проверки открытых файлов: карантином нельзя"
        " пользоваться.",
    },
    "task.list": {"en": "Reading the quarantine", "ru": "Чтение карантина"},
    "task.restore": {"en": "Restoring", "ru": "Восстановление"},
    "task.plan_purge": {"en": "Planning the deletion", "ru": "Подготовка удаления"},
    "task.purge": {"en": "Deleting permanently", "ru": "Удаление навсегда"},
    "restore.confirm": {
        "en": "Restore {files} ({size}) to where they were?",
        "ru": "Вернуть {files} ({size}) на прежнее место?",
    },
    "restore.done": {"en": "Restored: {files}", "ru": "Восстановлено: {files}"},
    "purge.confirm": {
        "en": "Delete {files} ({size}) permanently? They cannot be restored.",
        "ru": "Удалить {files} ({size}) навсегда? Их нельзя будет восстановить.",
    },
    "purge.done": {
        "en": "Deleted permanently: {files}, freed {size}",
        "ru": "Удалено навсегда: {files}, освобождено {size}",
    },
    "purge.nothing": {"en": "Nothing to delete.", "ru": "Удалять нечего."},
    "item.refused": {
        "en": "Refused: [{item}] {path} ({reason})",
        "ru": "Отказано: [{item}] {path} ({reason})",
    },
    "organize.blocked": {
        "en": "Organize does not move files on this system:",
        "ru": "На этой системе сортировка не перемещает файлы:",
    },
    "organize.choose": {"en": "Choose folder…", "ru": "Выбрать папку…"},
    "organize.plan": {"en": "The plan", "ru": "План"},
    "organize.would": {
        "en": "Would move {files}, {size} in {folder}.",
        "ru": "Папка {folder}: будет перемещено {files}, {size}.",
    },
    "organize.nothing": {
        "en": "Nothing to move in {folder}.",
        "ru": "Папка {folder}: перемещать нечего.",
    },
    "organize.refused": {"en": "Refused: {folder}: {reason}", "ru": "Отказано: {folder}: {reason}"},
    "organize.category": {"en": "{category}: {files}, {size}", "ru": "{category}: {files}, {size}"},
    "organize.line": {"en": "{name} → {category}/", "ru": "{name} → {category}/"},
    "organize.stays": {"en": "Stay in place: {n}", "ru": "Остаются на месте: {n}"},
    "organize.stay": {"en": "{name} ({reason})", "ru": "{name} ({reason})"},
    "organize.move": {"en": "Move files", "ru": "Переместить файлы"},
    "organize.confirm": {
        "en": "Move {files} ({size}) into category folders in {folder}? Undo moves them back.",
        "ru": "Разложить {files} ({size}) по папкам категорий внутри {folder}? Их можно"
        " вернуть кнопкой «Вернуть файлы…».",
    },
    "organize.done": {
        "en": "Moved {files}, {size} in {folder} (batch {batch}).",
        "ru": "Перемещено: {files}, {size}, папка {folder} (пакет {batch}).",
    },
    "organize.nothing_moved": {
        "en": "Nothing was moved in {folder}.",
        "ru": "Ничего не перемещено, папка {folder}.",
    },
    "organize.stopped": {
        "en": "Stopped: {error}. Batch {batch}: {state}.",
        "ru": "Остановлено: {error}. Пакет {batch}: {state}.",
    },
    "organize.still": {"en": "Still sorted: {path}", "ru": "Остался разложенным: {path}"},
    "organize.left": {
        "en": "Undo batch {batch} moves them back.",
        "ru": "Возврат пакета {batch} вернёт их на место.",
    },
    "organize.changed": {
        "en": "Changed since the plan: {path}",
        "ru": "Изменился после плана: {path}",
    },
    "organize.undo": {"en": "Undo…", "ru": "Вернуть файлы…"},
    "batches.title": {"en": "Batches", "ru": "Пакеты"},
    "batches.id": {"en": "Id", "ru": "№"},
    "batches.time": {"en": "Time", "ru": "Время"},
    "batches.kind": {"en": "Kind", "ru": "Вид"},
    "batches.moved": {"en": "Files moved", "ru": "Перемещено файлов"},
    "batches.state": {"en": "State", "ru": "Состояние"},
    "batches.folder": {"en": "Folder", "ru": "Папка"},
    "batches.undo_of": {"en": "{kind} of batch {batch}", "ru": "{kind} пакета {batch}"},
    "batches.undone": {"en": "{state}, undone", "ru": "{state}, возвращён"},
    "batches.partly_undone": {
        "en": "{state}, partly undone",
        "ru": "{state}, частично возвращён",
    },
    "undo.title": {"en": "Undo batch {batch}", "ru": "Возврат пакета {batch}"},
    "undo.confirm": {
        "en": "Move back {files} ({size}) sorted by batch {batch} in {folder}?",
        "ru": "Вернуть на прежнее место {files} ({size}) из пакета {batch}, папка {folder}?",
    },
    "undo.action": {"en": "Move back", "ru": "Вернуть"},
    "undo.line": {"en": "{source} → {destination}", "ru": "{source} → {destination}"},
    "undo.refused": {
        "en": "Refused: batch {batch}: {reason}",
        "ru": "Отказано: пакет {batch}: {reason}",
    },
    "undo.nothing": {
        "en": "Nothing to move back from batch {batch}.",
        "ru": "Из пакета {batch} нечего возвращать.",
    },
    "undo.nothing_moved": {
        "en": "Nothing was moved back from batch {batch}.",
        "ru": "Из пакета {batch} ничего не возвращено.",
    },
    "undo.done": {
        "en": "Moved back {files}, {size} in {folder} (batch {batch}, undoing batch {undoing}).",
        "ru": "Возвращено: {files}, {size}, папка {folder} (пакет {batch}, возврат пакета"
        " {undoing}).",
    },
    "undo.again": {
        "en": "Undo batch {batch} again to move back the files still sorted.",
        "ru": "Повторите возврат пакета {batch}, чтобы вернуть файлы, которые остались"
        " разложенными.",
    },
    "task.batches": {"en": "Reading the batches", "ru": "Чтение пакетов"},
    "task.plan": {"en": "Planning", "ru": "Подготовка плана"},
    "task.organize": {"en": "Moving files", "ru": "Перемещение файлов"},
    "task.plan_undo": {"en": "Planning the undo", "ru": "Подготовка возврата"},
    "task.undo": {"en": "Moving files back", "ru": "Возврат файлов"},
    "autostart.entries": {"en": "Autostart entries", "ru": "Записи автозагрузки"},
    "autostart.name": {"en": "Name", "ru": "Название"},
    "autostart.state": {"en": "State", "ru": "Состояние"},
    "autostart.scope": {"en": "Scope", "ru": "Область"},
    "autostart.location": {"en": "Location", "ru": "Расположение"},
    "autostart.group": {"en": "{source}: {n}", "ru": "{source}: {n}"},
    "autostart.total": {
        "en": "{entries}, {disabled} disabled",
        "ru": "{entries}, отключено: {disabled}",
    },
    "autostart.skipped": {"en": "Skipped: {n}", "ru": "Пропущено: {n}"},
    "autostart.skip": {
        "en": "{source}: {location} ({detail})",
        "ru": "{source}: {location} ({detail})",
    },
    "autostart.refresh": {"en": "Refresh", "ru": "Обновить"},
    "autostart.disable": {"en": "Disable…", "ru": "Отключить…"},
    "autostart.enable": {"en": "Enable…", "ru": "Включить…"},
    "autostart.unchecked": {
        "en": "An unfinished autostart change cannot be checked: {detail}. Fix or move what is"
        " there, then use Recover again.",
        "ru": "Незавершённое изменение автозагрузки нельзя проверить: {detail}. Исправьте или"
        " переместите то, что там находится, и снова используйте «Восстановить после сбоя».",
    },
    "autostart.unclosed": {
        "en": "An unfinished autostart change cannot be closed: {detail}. Fix or move what is"
        " there, then use Recover again.",
        "ru": "Незавершённое изменение автозагрузки нельзя закрыть: {detail}. Исправьте или"
        " переместите то, что там находится, и снова используйте «Восстановить после сбоя».",
    },
    "entry.enabled": {"en": "Enabled", "ru": "Включена"},
    "entry.disabled": {"en": "Disabled", "ru": "Отключена"},
    "change.disable_title": {"en": "Disable {name}", "ru": "Отключить {name}"},
    "change.enable_title": {"en": "Enable {name}", "ru": "Включить {name}"},
    "change.disable_confirm": {
        "en": "Disable {name} ({source}, {scope})?",
        "ru": "Отключить {name} ({source}, {scope})?",
    },
    "change.enable_confirm": {
        "en": "Enable {name} ({source}, {scope})?",
        "ru": "Включить {name} ({source}, {scope})?",
    },
    "change.location": {"en": "Location: {location}", "ru": "Расположение: {location}"},
    "change.disable": {"en": "Disable", "ru": "Отключить"},
    "change.enable": {"en": "Enable", "ru": "Включить"},
    "how.run_key_disable": {
        "en": "Its StartupApproved flag is set to disabled, as the Task Manager does; the Run"
        " value is never written.",
        "ru": "Её флаг StartupApproved получает значение «отключено», как это делает диспетчер"
        " задач; значение Run не изменяется.",
    },
    "how.run_key_enable": {
        "en": "Its StartupApproved flag is set to enabled; the Run value is never written.",
        "ru": "Её флаг StartupApproved получает значение «включено»; значение Run не изменяется.",
    },
    "how.enable": {
        "en": "If safeclean disabled it, what it changed is put back (the original from the"
        " store, or the stub moved to the store); nothing is deleted.",
        "ru": "Если её отключил safeclean, изменённое возвращается (оригинал из хранилища, или"
        " заглушка переносится в хранилище); ничего не удаляется.",
    },
    "how.user_disable": {
        "en": "Its file is replaced by a copy with Hidden=true; the original is kept in the"
        " autostart store.",
        "ru": "Её файл заменяется копией с Hidden=true; оригинал сохраняется в хранилище"
        " автозагрузки.",
    },
    "how.system_disable": {
        "en": "A stub with Hidden=true is created in {folder}; the system file is never written.",
        "ru": "В {folder} создаётся заглушка с Hidden=true; системный файл не изменяется.",
    },
    "change.disabled": {
        "en": "Disabled {name} (change {change}).",
        "ru": "Отключено: {name} (изменение {change}).",
    },
    "change.enabled": {
        "en": "Enabled {name} (change {change}).",
        "ru": "Включено: {name} (изменение {change}).",
    },
    "change.refused": {"en": "Refused: {reason}.", "ru": "Отказано: {reason}."},
    "change.rolled_back": {
        "en": "Not changed: {detail}; it was rolled back (change {change}).",
        "ru": "Не изменено: {detail}; всё возвращено как было (изменение {change}).",
    },
    "change.failed": {
        "en": "Change {change} failed: {detail}. Use Recover.",
        "ru": "Изменение {change} не удалось: {detail}. Используйте «Восстановить после сбоя».",
    },
    "change.not_changed": {
        "en": "Cannot change {name}: {detail}; nothing was changed.",
        "ru": "Нельзя изменить {name}: {detail}; ничего не изменено.",
    },
    "task.autostart": {"en": "Reading autostart", "ru": "Чтение автозагрузки"},
    "task.disable": {"en": "Disabling", "ru": "Отключение"},
    "task.enable": {"en": "Enabling", "ru": "Включение"},
    "recover.found": {"en": "Unfinished work: {domains}.", "ru": "Прерванная работа: {domains}."},
    "recover.button": {"en": "Recover…", "ru": "Восстановить после сбоя…"},
    "recover.hide": {"en": "Hide", "ru": "Скрыть"},
    "recover.action": {"en": "Recover", "ru": "Восстановить"},
    "recover.confirm": {
        "en": "Finish the unfinished work ({domains}) by what is on the disk now?",
        "ru": "Завершить прерванную работу ({domains}) по тому, что сейчас на диске?",
    },
    "recover.quarantine": {
        "en": "Quarantine: each interrupted move, restore or deletion is closed by where its"
        " files are now.",
        "ru": "Карантин: каждое прерванное перемещение, возврат или удаление закрывается по"
        " тому, где сейчас находятся его файлы.",
    },
    "recover.organize": {
        "en": "Organize: each interrupted batch is closed by where its files are now; no file"
        " is moved.",
        "ru": "Сортировка: каждый прерванный пакет закрывается по тому, где сейчас находятся"
        " его файлы; файлы не перемещаются.",
    },
    "recover.autostart": {
        "en": "Autostart: each interrupted change is completed or put back, by what its entry"
        " holds now.",
        "ru": "Автозагрузка: каждое прерванное изменение доводится до конца или отменяется по"
        " тому, что сейчас в записи.",
    },
    "recovered.quarantine": {
        "en": "Recovered an interrupted quarantine operation ({files}).",
        "ru": "Восстановлена прерванная операция карантина ({files}).",
    },
    "recovered.organize": {
        "en": "Recovered interrupted organize batches: {n}",
        "ru": "Восстановлено прерванных пакетов сортировки: {n}",
    },
    "recovered.batch": {"en": "Batch {batch}: {state}.", "ru": "Пакет {batch}: {state}."},
    "recovered.undo": {
        "en": "Batch {batch} (undo of batch {undoing}): {state}.",
        "ru": "Пакет {batch} (возврат пакета {undoing}): {state}.",
    },
    "recovered.autostart": {
        "en": "Recovered interrupted autostart changes: {n}",
        "ru": "Восстановлено прерванных изменений автозагрузки: {n}",
    },
    "recovered.change": {
        "en": "Change {change}: {state}.",
        "ru": "Изменение {change}: {state}.",
    },
    "recovered.nothing": {"en": "Nothing to recover.", "ru": "Восстанавливать нечего."},
    "task.look": {"en": "Looking for unfinished work", "ru": "Поиск прерванной работы"},
    "task.recover": {"en": "Recovering", "ru": "Восстановление после сбоя"},
    "folder.title": {"en": "Choose a folder", "ru": "Выберите папку"},
    "folder.path": {"en": "Folder", "ru": "Папка"},
    "folder.choose": {"en": "Choose", "ru": "Выбрать"},
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
