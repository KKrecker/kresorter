"""The window's texts, by key, in English and Russian (decision 0014, item 28), and its counts
(item 29), and the units of a size. Placeholders are the same in both languages; ``{n}`` is a
count's number."""

from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {
    "app.title": {"en": "Kresorter", "ru": "Kresorter"},
    "page.overview": {"en": "Overview", "ru": "Обзор"},
    "page.findings": {"en": "Findings", "ru": "Находки"},
    "page.quarantine": {"en": "Quarantine", "ru": "Карантин"},
    "page.organize": {"en": "Organize", "ru": "Сортировка"},
    "page.autostart": {"en": "Autostart", "ru": "Автозагрузка"},
    "page.settings": {"en": "Settings", "ru": "Настройки"},
    "head.overview": {
        "en": "Report first: nothing moves until you confirm, and what moves can be put back.",
        "ru": "Сначала отчёт: ничего не перемещается без вашего подтверждения, и всё"
        " перемещённое можно вернуть.",
    },
    "head.findings": {
        "en": "What the last scan found, grouped by its strongest reason.",
        "ru": "Что нашло последнее сканирование, по главной причине.",
    },
    "head.organize": {
        "en": "The files directly in one folder, sorted by kind; subfolders are never entered"
        " or moved.",
        "ru": "Файлы, лежащие прямо в одной папке, по типам; во вложенные папки сортировка не"
        " заходит и не перемещает их.",
    },
    "head.autostart": {
        "en": "Programs that start when you sign in. Turning one off keeps a record and can be"
        " undone.",
        "ru": "Программы, которые запускаются при входе в систему. Отключение записывается, и"
        " его можно отменить.",
    },
    "head.quarantine": {
        "en": "Files moved here can be put back where they were, or deleted for good.",
        "ru": "Перемещённые сюда файлы можно вернуть на место или удалить навсегда.",
    },
    "head.settings": {
        "en": "What the window remembers, and the local AI.",
        "ru": "Что окно запоминает, и локальный ИИ.",
    },
    "sidebar.pages": {"en": "Pages", "ru": "Страницы"},
    "sidebar.open_files": {
        "en": "Open-file check: reliable",
        "ru": "Открытые файлы: проверка надёжна",
    },
    "sidebar.no_open_files": {
        "en": "Open-file check: not reliable",
        "ru": "Открытые файлы: проверка ненадёжна",
    },
    "sidebar.ai": {"en": "AI explanations: {model}", "ru": "Объяснения ИИ: {model}"},
    "sidebar.ai_refused": {
        "en": "AI explanations: {name} is refused",
        "ru": "Объяснения ИИ: значение {name} отклонено",
    },
    "button.cancel": {"en": "Cancel", "ru": "Отмена"},
    "button.close": {"en": "Close", "ru": "Закрыть"},
    "button.copy": {"en": "Copy", "ru": "Копировать"},
    "error.title": {
        "en": "Kresorter: an unexpected error",
        "ru": "Kresorter: непредвиденная ошибка",
    },
    "error.text": {
        "en": "The window stays open, and nothing was sent anywhere. The details below can be"
        " copied into a report.",
        "ru": "Окно остаётся открытым, и ничего никуда не отправлено. Подробности ниже можно"
        " скопировать в отчёт.",
    },
    "task.running": {"en": "Running: {task}", "ru": "Выполняется: {task}"},
    "task.read": {"en": "Running: {task}, {read}", "ru": "Выполняется: {task}, {read}"},
    "task.failed": {"en": "{task} failed: {message}", "ru": "Ошибка ({task}): {message}"},
    "close.wait": {
        "en": "{task} is still running; the window closes when it ends.",
        "ru": "Ещё выполняется: {task}. Окно закроется, когда это завершится.",
    },
    "overview.add": {"en": "Add folder", "ru": "Добавить папку"},
    "overview.remove": {"en": "Remove folder {folder}", "ru": "Убрать папку {folder}"},
    "overview.skip": {
        "en": "Leave {folder} out of the scan",
        "ru": "Убрать {folder} из сканирования",
    },
    "overview.zone_link": {"en": "+ {folder}", "ru": "+ {folder}"},
    "overview.put_back": {"en": "Scan {folder} again", "ru": "Снова сканировать {folder}"},
    "overview.scan_title": {"en": "Scan", "ru": "Сканирование"},
    "overview.read_only": {
        "en": "Read-only: a scan never changes anything on the disk.",
        "ru": "Только чтение: сканирование ничего не меняет на диске.",
    },
    "overview.scan": {"en": "Scan now", "ru": "Сканировать"},
    "overview.none": {"en": "Not scanned yet.", "ru": "Сканирования ещё не было."},
    "overview.last": {
        "en": "Last scan {moment} · {files} scanned · duplicates: {groups} · skipped: {paths}",
        "ru": "Последнее сканирование {moment} · просканировано: {files} · дубликаты: {groups}"
        " · пропущено: {paths}",
    },
    "overview.reasons": {"en": "{files}: {reasons}", "ru": "{files}: {reasons}"},
    "overview.never": {
        "en": "{files}. Never proposed: you decide one by one.",
        "ru": "{files}. Никогда не предлагается: решаете вы, по одному.",
    },
    "overview.open_level": {"en": "Review findings →", "ru": "Посмотреть находки →"},
    "overview.open_review": {"en": "Look at them →", "ru": "Посмотреть их →"},
    "overview.quarantine": {"en": "Moved files wait here", "ru": "Здесь ждут перемещённые файлы"},
    "overview.quarantine_read": {"en": "{files} · {size}", "ru": "{files} · {size}"},
    "overview.quarantine_note": {
        "en": "Each can be put back where it was",
        "ru": "Каждый можно вернуть на место",
    },
    "overview.organize": {"en": "Sort one folder by kind", "ru": "Разложить папку по типам"},
    "overview.organize_note": {
        "en": "Nothing is renamed, overwritten or deleted",
        "ru": "Ничего не переименовывается, не перезаписывается и не удаляется",
    },
    "overview.organize_read": {"en": "{files} in {folder}", "ru": "{files} в {folder}"},
    "overview.organize_into": {
        "en": "Can be sorted into {folders}",
        "ru": "Можно разложить: {folders}",
    },
    "overview.organize_nothing": {"en": "Nothing to sort", "ru": "Раскладывать нечего"},
    "overview.autostart": {
        "en": "Programs that start at sign-in",
        "ru": "Программы, которые запускаются при входе",
    },
    "overview.autostart_note": {
        "en": "Turning one off can be undone",
        "ru": "Отключение можно отменить",
    },
    "overview.autostart_off": {"en": "{n} turned off", "ru": "отключено: {n}"},
    "overview.ai_title": {"en": "Local AI", "ru": "Локальный ИИ"},
    "overview.ai": {"en": "{server} · Model: {model}", "ru": "{server} · Модель: {model}"},
    "overview.ai_first": {
        "en": "{server} · Model: the first it lists",
        "ru": "{server} · Модель: первая в списке",
    },
    "overview.ai_refused": {"en": "{name} is refused", "ru": "Значение {name} отклонено"},
    "overview.ai_not_checked": {
        "en": "Not checked yet; Check is in Settings",
        "ru": "Ещё не проверялась; проверка — в настройках",
    },
    "overview.ai_available": {
        "en": "Available at the last check",
        "ru": "Доступна по последней проверке",
    },
    "overview.ai_unavailable": {
        "en": "Unavailable at the last check",
        "ru": "Недоступна по последней проверке",
    },
    "overview.unreliable": {
        "en": "Files in use cannot be recognized on this system, so nothing can be moved to the"
        " quarantine.",
        "ru": "На этой системе нельзя распознать открытые файлы, поэтому ничего нельзя"
        " переместить в карантин.",
    },
    "task.scan": {"en": "Scanning", "ru": "Сканирование"},
    "selected.files": {"en": "{files} selected", "ru": "Выбрано: {files}"},
    "selected.size": {"en": "· {size}", "ru": "· {size}"},
    "findings.tree": {"en": "Findings", "ru": "Находки"},
    "findings.scan_of": {
        "en": "Scan of {folders}, {moment}",
        "ru": "Сканирование {folders}, {moment}",
    },
    "list.and": {"en": "{first} and {last}", "ru": "{first} и {last}"},
    "findings.rescan": {"en": "Rescan", "ru": "Сканировать снова"},
    "findings.chip": {"en": "{level} {n}", "ru": "{level} {n}"},
    "findings.name": {"en": "Name", "ru": "Имя"},
    "findings.size": {"en": "Size", "ru": "Размер"},
    "findings.level": {"en": "Level", "ru": "Уровень"},
    "findings.rules": {"en": "{files} · {rules}", "ru": "{files} · {rules}"},
    "findings.copies": {
        "en": "{files} · one copy of each stays",
        "ru": "{files} · одна копия каждого остаётся",
    },
    "findings.search": {"en": "Search the paths", "ru": "Поиск по путям"},
    "findings.select": {"en": "Select all: {level}", "ru": "Выбрать все: {level}"},
    "findings.clear": {"en": "Clear selection", "ru": "Снять выбор"},
    "findings.move": {"en": "Move to quarantine", "ru": "Переместить в карантин"},
    "findings.move_ask": {"en": "Move to quarantine…", "ru": "Переместить в карантин…"},
    "detail.none": {
        "en": "Choose a file to see why it was found.",
        "ru": "Выберите файл, чтобы увидеть, почему он найден.",
    },
    "detail.size": {"en": "Size", "ru": "Размер"},
    "detail.modified": {"en": "Modified", "ru": "Изменён"},
    "detail.found": {"en": "Found in", "ru": "Найден в"},
    "detail.why": {"en": "Why", "ru": "Почему"},
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
    "quarantine.name": {"en": "Name", "ru": "Имя"},
    "quarantine.size": {"en": "Size", "ru": "Размер"},
    "quarantine.id": {"en": "ID", "ru": "№"},
    "quarantine.empty": {"en": "The quarantine is empty.", "ru": "Карантин пуст."},
    "quarantine.total": {
        "en": "In the quarantine: {files}, {size}",
        "ru": "Сейчас в карантине: {files}, {size}",
    },
    "quarantine.refresh": {"en": "Refresh", "ru": "Обновить"},
    "quarantine.restore": {"en": "Restore", "ru": "Восстановить"},
    "quarantine.purge": {"en": "Delete permanently", "ru": "Удалить навсегда"},
    "quarantine.permanent": {"en": "Cannot be undone", "ru": "Необратимо"},
    "quarantine.select_all": {"en": "Select all", "ru": "Выбрать все"},
    "quarantine.clear": {"en": "Clear selection", "ru": "Снять выбор"},
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
    "organize.change": {"en": "Change…", "ru": "Изменить…"},
    "organize.group": {
        "en": "Group by meaning (local AI)",
        "ru": "Сгруппировать по смыслу (локальный ИИ)",
    },
    "organize.by_kind": {"en": "By kind", "ru": "По типу"},
    "organize.grouped": {
        "en": "The local AI ({model}) grouped {files} {into}: the groups may be wrong. By kind"
        " goes back to the plan by kind.",
        "ru": "Локальный ИИ ({model}) сгруппировал {files} {into}: группы могут быть неверными."
        " «По типу» возвращает план по типам.",
    },
    "organize.grouped_stopped": {
        "en": "The local AI ({model}) grouped {files} {into}, then stopped: {reason}. The groups"
        " may be wrong. By kind goes back to the plan by kind.",
        "ru": "Локальный ИИ ({model}) сгруппировал {files} {into} и остановился: {reason}."
        " Группы могут быть неверными. «По типу» возвращает план по типам.",
    },
    "organize.not_grouped": {
        "en": "Not grouped: {reason}. The plan by kind stays.",
        "ru": "Не сгруппировано: {reason}. План по типам остаётся.",
    },
    "organize.no_groups": {
        "en": "The local AI found no group of two files or more; the plan by kind stays.",
        "ru": "Локальный ИИ не нашёл групп из двух файлов и более; план по типам остаётся.",
    },
    "organize.folder": {"en": "Folder", "ru": "Папка"},
    "organize.no_folder": {"en": "No folder chosen", "ru": "Папка не выбрана"},
    "organize.state": {
        "en": "Plan made {moment} · nothing moved yet",
        "ru": "План составлен {moment} · ничего ещё не перемещено",
    },
    "organize.amount": {"en": "{files} · {size}", "ru": "{files} · {size}"},
    "organize.named": {"en": "{label} (folder {category})", "ru": "{label} (папка {category})"},
    "organize.stays_title": {"en": "Stays in place", "ru": "Остаются на месте"},
    "organize.stays_note": {
        "en": "{files}, each with its reason",
        "ru": "{files}, каждый — по своей причине",
    },
    "organize.will": {"en": "{files} will move {into}.", "ru": "Будет разложено: {files} {into}."},
    "organize.safe": {
        "en": "Nothing is renamed, overwritten or deleted; the batch can be undone.",
        "ru": "Ничего не переименовывается, не перезаписывается и не удаляется; пакет можно"
        " вернуть.",
    },
    "organize.sort": {"en": "Sort…", "ru": "Разложить…"},
    "organize.nothing": {
        "en": "Nothing to move in {folder}.",
        "ru": "Папка {folder}: перемещать нечего.",
    },
    "organize.refused": {"en": "Refused: {folder}: {reason}", "ru": "Отказано: {folder}: {reason}"},
    "organize.line": {"en": "{name} → {category}/", "ru": "{name} → {category}/"},
    "organize.stay": {"en": "{name} ({reason})", "ru": "{name} ({reason})"},
    "organize.move": {"en": "Sort files", "ru": "Разложить файлы"},
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
    "batches.title": {"en": "Recent batches", "ru": "Последние пакеты"},
    "organize.batch": {"en": "Batch {batch} · {moment}", "ru": "Пакет {batch} · {moment}"},
    "organize.batch_note": {
        "en": "{files} moved · {kind} · {state}",
        "ru": "{files} · {kind} · {state}",
    },
    "organize.no_batches": {"en": "No batches yet.", "ru": "Пакетов пока нет."},
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
    "task.group": {
        "en": "Grouping by meaning (local AI)",
        "ru": "Группировка по смыслу (локальный ИИ)",
    },
    "task.organize": {"en": "Moving files", "ru": "Перемещение файлов"},
    "task.plan_undo": {"en": "Planning the undo", "ru": "Подготовка возврата"},
    "task.undo": {"en": "Moving files back", "ru": "Возврат файлов"},
    "autostart.entries": {"en": "Autostart entries", "ru": "Записи автозагрузки"},
    "autostart.search": {"en": "Search entries", "ru": "Поиск записей"},
    "autostart.group": {"en": "{source} · {entries}", "ru": "{source} · {entries}"},
    "autostart.locked": {
        "en": "Listed only: kresorter does not change this entry",
        "ru": "Только для просмотра: kresorter не меняет эту запись",
    },
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
        "en": "If kresorter disabled it, what it changed is put back (the original from the"
        " store, or the stub moved to the store); nothing is deleted.",
        "ru": "Если её отключил kresorter, изменённое возвращается (оригинал из хранилища, или"
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
    "explain.button": {"en": "Explain (local AI)", "ru": "Объяснить (локальный ИИ)"},
    "explain.title": {"en": "AI explanation", "ru": "Объяснение ИИ"},
    "explain.advisory": {"en": "advisory", "ru": "лишь совет"},
    "explain.model": {
        "en": "{model} via {server} · may be wrong",
        "ru": "{model} через {server} · может ошибаться",
    },
    "explain.none": {
        "en": "No explanation: {reason}. The Check on the Settings page shows how to set it up.",
        "ru": "Объяснения нет: {reason}. Проверка на странице «Настройки» покажет, как это"
        " настроить.",
    },
    "task.explain": {"en": "Asking the local AI", "ru": "Запрос к локальному ИИ"},
    "entry.command": {"en": "Command: {command}", "ru": "Команда: {command}"},
    "entry.shadows": {
        "en": "Replaces the system entry {shadows}",
        "ru": "Заменяет системную запись {shadows}",
    },
    "entry.note": {"en": "Condition: {note}", "ru": "Условие: {note}"},
    "autostart.machine": {
        "en": "Machine-wide entries (HKLM, services, scheduled tasks, the common startup folder)"
        " were not read; turn them on in Settings.",
        "ru": "Общесистемные записи (HKLM, службы, задачи планировщика, общая папка"
        " автозагрузки) не прочитаны; их можно включить в настройках.",
    },
    "organize.path": {"en": "Path: {path}", "ru": "Путь: {path}"},
    "organize.why": {"en": "Stays: {reason}", "ru": "Остаётся: {reason}"},
    "settings.language": {"en": "Language", "ru": "Язык"},
    "settings.system": {"en": "As the system", "ru": "Как в системе"},
    "settings.en": {"en": "English", "ru": "English"},
    "settings.ru": {"en": "Русский", "ru": "Русский"},
    "settings.language_note": {
        "en": "A new language applies the next time the window opens.",
        "ru": "Новый язык применится при следующем открытии окна.",
    },
    "settings.restart_title": {"en": "Restart the window?", "ru": "Перезапустить окно?"},
    "settings.restart_text": {
        "en": (
            "The window opens again in the new language, on this page. A task that changes files"
            " ends first."
        ),
        "ru": (
            "Окно откроется снова на новом языке, на этой же странице. Задача, которая меняет"
            " файлы, сначала завершится."
        ),
    },
    "settings.restart_action": {"en": "Restart now", "ru": "Перезапустить сейчас"},
    "settings.appearance": {"en": "Appearance", "ru": "Оформление"},
    "settings.theme_system": {"en": "System", "ru": "Как в системе"},
    "settings.theme_light": {"en": "Light", "ru": "Светлая"},
    "settings.theme_dark": {"en": "Dark", "ru": "Тёмная"},
    "settings.machine": {
        "en": "Read machine-wide autostart entries",
        "ru": "Читать общесистемные записи автозагрузки",
    },
    "settings.machine_title": {
        "en": "Read machine-wide entries",
        "ru": "Читать общесистемные записи",
    },
    "settings.machine_confirm": {
        "en": "The Autostart page will also read the machine-wide entries: the HKLM Run keys,"
        " the services, the scheduled tasks and the common startup folder. They are only read;"
        " nothing in them is changed.",
        "ru": "Страница «Автозагрузка» будет читать и общесистемные записи: ключи Run в HKLM,"
        " службы, задачи планировщика и общую папку автозагрузки. Они только читаются; ничего"
        " в них не меняется.",
    },
    "settings.machine_action": {"en": "Read", "ru": "Читать"},
    "settings.saved": {"en": "Saved.", "ru": "Сохранено."},
    "settings.not_saved": {"en": "Not saved: {reason}.", "ru": "Не сохранено: {reason}."},
    "settings.unused": {
        "en": "The settings file was not used: {reason}. The defaults apply until a setting is"
        " changed.",
        "ru": "Файл настроек не использован: {reason}. Действуют значения по умолчанию, пока"
        " настройка не изменена.",
    },
    "settings.data_dir": {"en": "Data folder", "ru": "Папка данных"},
    "settings.version": {"en": "Kresorter {version}", "ru": "Kresorter {version}"},
    "settings.licence": {
        "en": "Kresorter is under the MIT licence. Its Windows build carries Qt and PySide6 under"
        " the LGPL-3.0; THIRD-PARTY-NOTICES.txt in the program's folder names each part and its"
        " licence.",
        "ru": "Kresorter распространяется под лицензией MIT. Сборка для Windows содержит Qt и"
        " PySide6 под лицензией LGPL-3.0; файл THIRD-PARTY-NOTICES.txt в папке программы"
        " называет каждую часть и её лицензию.",
    },
    "settings.address": {
        "en": "Address: {url} · Model: {model}",
        "ru": "Адрес: {url} · Модель: {model}",
    },
    "settings.ai": {"en": "Local AI", "ru": "Локальный ИИ"},
    "settings.server": {"en": "Server", "ru": "Сервер"},
    "settings.server_env": {
        "en": "{variable} sets the server: {server}. The server chosen here applies once it is"
        " unset.",
        "ru": "{variable} задаёт сервер: {server}. Сервер, выбранный здесь, применится, когда"
        " переменная не задана.",
    },
    "settings.first_model": {
        "en": "the first model LM Studio lists",
        "ru": "первая модель в списке LM Studio",
    },
    "settings.check": {"en": "Check", "ru": "Проверить"},
    "settings.model": {"en": "Model", "ru": "Модель"},
    "settings.model_env": {
        "en": "{variable} sets the model: {model}. The model chosen here applies once it is unset.",
        "ru": "{variable} задаёт модель: {model}. Модель, выбранная здесь, применится, когда"
        " переменная не задана.",
    },
    "settings.recommended": {
        "en": "Recommended for this computer ({memory}, {processors}): {model}; Qwen 2.5 writes"
        " Russian as well as English. To get it: ollama pull {model} (kresorter installs nothing"
        " itself).",
        "ru": "Рекомендуется для этого компьютера ({memory}, {processors}): {model}; Qwen 2.5"
        " пишет и по-русски, и по-английски. Чтобы получить её: ollama pull {model} (kresorter"
        " сам ничего не устанавливает).",
    },
    "settings.recommended_lmstudio": {
        "en": "Recommended for this computer ({memory}, {processors}): {model}; Qwen 2.5 writes"
        " Russian as well as English. To get it: find {model} in LM Studio's Discover tab and"
        " download it (kresorter installs nothing itself).",
        "ru": "Рекомендуется для этого компьютера ({memory}, {processors}): {model}; Qwen 2.5"
        " пишет и по-русски, и по-английски. Чтобы получить её: найдите {model} на вкладке"
        " Discover в LM Studio и скачайте её (kresorter сам ничего не устанавливает).",
    },
    "settings.memory": {"en": "{size} of memory", "ru": "{size} памяти"},
    "settings.memory_unknown": {"en": "memory unknown", "ru": "память неизвестна"},
    "settings.processors_unknown": {
        "en": "number of processors unknown",
        "ru": "число процессоров неизвестно",
    },
    "task.check": {"en": "Checking the local AI", "ru": "Проверка локального ИИ"},
    "check.server": {"en": "{server}: {state}", "ru": "{server}: {state}"},
    "check.model": {"en": "Model: {state}", "ru": "Модель: {state}"},
    "check.running": {
        "en": "running at {url} (version {version})",
        "ru": "работает по адресу {url} (версия {version})",
    },
    "check.running_unversioned": {"en": "running at {url}", "ru": "работает по адресу {url}"},
    "check.unreachable": {
        "en": "not reachable at {url} ({detail})",
        "ru": "недоступна по адресу {url} ({detail})",
    },
    "check.not_server": {
        "en": "{url} does not answer as {server} ({detail})",
        "ru": "{url} отвечает не как {server} ({detail})",
    },
    "check.not_checked": {"en": "not checked", "ru": "не проверено"},
    "check.refused": {
        "en": "refused setting {name}={value} ({why})",
        "ru": "настройка отклонена: {name}={value} ({why})",
    },
    "check.installed": {"en": "{model}: installed", "ru": "{model}: установлена"},
    "check.missing": {"en": "{model}: not installed", "ru": "{model}: не установлена"},
    "check.model_not_checked": {"en": "{model}: not checked", "ru": "{model}: не проверена"},
    "check.listed": {"en": "{model}: available", "ru": "{model}: доступна"},
    "check.not_listed": {"en": "{model}: not available", "ru": "{model}: недоступна"},
    "check.none_listed": {"en": "none listed", "ru": "ни одной в списке"},
    "check.available": {
        "en": "Explanations are available: Explain (local AI) on a finding, an autostart entry"
        " or a file that stays in place.",
        "ru": "Объяснения доступны: «Объяснить (локальный ИИ)» у находки, записи автозагрузки"
        " или файла, который остаётся на месте.",
    },
    "check.unavailable": {
        "en": "Explanations are unavailable; kresorter works as usual without them.",
        "ru": "Объяснения недоступны; kresorter работает без них как обычно.",
    },
    "check.setup": {
        "en": "To set them up (kresorter installs nothing itself):",
        "ru": "Как их настроить (kresorter сам ничего не устанавливает):",
    },
    "check.step": {"en": "{n}. {step}", "ru": "{n}. {step}"},
    "check.install": {
        "en": "Install Ollama from https://ollama.com/download and start it.",
        "ru": "Установите Ollama с https://ollama.com/download и запустите её.",
    },
    "check.pull": {
        "en": "Download the model: ollama pull {model}",
        "ru": "Скачайте модель: ollama pull {model}",
    },
    "check.install_lmstudio": {
        "en": "Install LM Studio from https://lmstudio.ai, download a model and start its server"
        " (Developer, Start Server).",
        "ru": "Установите LM Studio (https://lmstudio.ai), скачайте модель и запустите её сервер"
        " (Developer, Start Server).",
    },
    "check.download_lmstudio": {
        "en": "Download the model in LM Studio: {model}",
        "ru": "Скачайте модель в LM Studio: {model}",
    },
    "check.again": {"en": "Check again.", "ru": "Проверьте снова."},
    "check.settings": {
        "en": "Settings, from the environment the window started in: {server_variable} (ollama"
        " or lmstudio, default ollama), {url_variable} (a loopback address, default {url}) and"
        " {model_variable} (default {model}).",
        "ru": "Настройки берутся из окружения, в котором запущено окно: {server_variable} (ollama"
        " или lmstudio, по умолчанию ollama), {url_variable} (адрес loopback, по умолчанию"
        " {url}) и {model_variable} (по умолчанию {model}).",
    },
}

# Sizes: bytes, then binary multiples; the decimal separator of each language.
UNITS: dict[str, tuple[str, ...]] = {
    "en": ("B", "KiB", "MiB", "GiB", "TiB"),
    "ru": ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"),
}
DECIMAL: dict[str, str] = {"en": ".", "ru": ","}

PLURALS: dict[str, dict[str, tuple[str, ...]]] = {
    "file": {"en": ("{n} file", "{n} files"), "ru": ("{n} файл", "{n} файла", "{n} файлов")},
    "read": {
        "en": ("{n} file read", "{n} files read"),
        "ru": ("прочитан {n} файл", "прочитано {n} файла", "прочитано {n} файлов"),
    },
    "folder": {
        "en": ("{n} folder", "{n} folders"),
        "ru": ("{n} папка", "{n} папки", "{n} папок"),
    },
    "entry": {
        "en": ("{n} entry", "{n} entries"),
        "ru": ("{n} запись", "{n} записи", "{n} записей"),
    },
    "group": {
        "en": ("{n} group", "{n} groups"),
        "ru": ("{n} группа", "{n} группы", "{n} групп"),
    },
    "path": {"en": ("{n} path", "{n} paths"), "ru": ("{n} путь", "{n} пути", "{n} путей")},
    "processor": {
        "en": ("{n} processor", "{n} processors"),
        "ru": ("{n} процессор", "{n} процессора", "{n} процессоров"),
    },
    "folders.into": {
        "en": ("into {n} folder", "into {n} folders"),
        "ru": ("по {n} папке", "по {n} папкам", "по {n} папкам"),
    },
    "grouped.files": {
        "en": ("{grouped} of {n} file", "{grouped} of {n} files"),
        "ru": ("{grouped} из {n} файла", "{grouped} из {n} файлов", "{grouped} из {n} файлов"),
    },
    "grouped.into": {
        "en": ("into {n} folder", "into {n} folders"),
        "ru": ("в {n} папку", "в {n} папки", "в {n} папок"),
    },
}
