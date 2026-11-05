"""A label in English and Russian for every value of an enumeration the window shows
(decision 0014, item 31), and for each category of organize's table (item 44). Details that
come with a value (a path, a rule, the system's own message) are shown after its label, as they
are; a category's directory keeps its name on disk, which is its English label."""

from __future__ import annotations

from enum import StrEnum

from kresorter.analysis.score import Evidence, Level
from kresorter.autostart.journal import ChangeRefusal, ChangeState
from kresorter.autostart.models import Scope, Source
from kresorter.core.models import SkipReason
from kresorter.core.policy import BlockReason
from kresorter.core.preflight import RefusalReason
from kresorter.llm.failure import Unavailable
from kresorter.organize.folders import FolderReason
from kresorter.organize.journal import BatchKind, BatchState
from kresorter.organize.planner import StayReason
from kresorter.organize.platforms import Blocker
from kresorter.organize.undo import UndoReason
from kresorter.quarantine.service import PurgeRefusal, RestoreRefusal
from kresorter.storage.pending import Domain
from kresorter.storage.session import SessionFailure
from kresorter.ui.settings import Unused

__all__ = ["CATEGORIES", "LABELS"]


def _both(en: str, ru: str) -> dict[str, str]:
    return {"en": en, "ru": ru}


_ITEM_REFUSALS = {
    "unknown_item": _both("No such item", "Нет такого элемента"),
    "duplicate_item": _both("Named twice", "Указан дважды"),
    "not_quarantined": _both("Not in the quarantine", "Не в карантине"),
    "vault_missing": _both("Its copy in the quarantine is gone", "Его копии в карантине нет"),
    "vault_changed": _both(
        "Its copy in the quarantine has changed", "Его копия в карантине изменилась"
    ),
}

# By the name on disk (``organize/categories.toml``), which the English label repeats.
CATEGORIES: dict[str, dict[str, str]] = {
    "Images": _both("Images", "Изображения"),
    "Videos": _both("Videos", "Видео"),
    "Audio": _both("Audio", "Аудио"),
    "Documents": _both("Documents", "Документы"),
    "Archives": _both("Archives", "Архивы"),
    "Installers": _both("Installers", "Установщики"),
}

LABELS: dict[type[StrEnum], dict[str, dict[str, str]]] = {
    Level: {
        "safe": _both("Safe", "Безопасно"),
        "likely_safe": _both("Likely safe", "Скорее безопасно"),
        "review": _both("Review", "Проверить"),
    },
    Evidence: {
        "junk_cache": _both("Cache", "Кэш"),
        "junk_thumbnails": _both("Thumbnails", "Миниатюры"),
        "junk_os_metadata": _both("System metadata", "Служебные файлы системы"),
        "junk_temp": _both("Temporary file", "Временный файл"),
        "junk_crash_dump": _both("Crash dump", "Дамп сбоя"),
        "duplicate_copy": _both("Duplicate copy", "Копия дубликата"),
        "junk_browser_cache": _both("Browser cache", "Кэш браузера"),
        "large": _both("Large file", "Большой файл"),
        "old": _both("Not changed for a long time", "Давно не изменялся"),
    },
    RefusalReason: {
        "blocked": _both("Protected location", "Защищённое место"),
        "open_file": _both("In use by a program", "Открыт программой"),
        "not_found": _both("No longer there", "Больше не найден"),
        "unreadable": _both("Cannot be read", "Не читается"),
        "symlink": _both("A link", "Ссылка"),
        "not_regular": _both("Not a regular file", "Не обычный файл"),
        "changed": _both("Changed since the scan", "Изменился после сканирования"),
        "parent_swapped": _both("A folder on its path changed", "Папка на его пути изменилась"),
        "twin_missing": _both("The copy that stays is gone", "Остающейся копии нет"),
        "twin_changed": _both("The copy that stays has changed", "Остающаяся копия изменилась"),
        "twin_same_file": _both(
            "The same file as the copy that stays", "Тот же файл, что и остающаяся копия"
        ),
        "cross_device": _both("On another drive", "На другом диске"),
        "conflict": _both("The destination is taken", "Место назначения занято"),
        "duplicate_candidate": _both("Named twice", "Указан дважды"),
    },
    BlockReason: {
        "program_files": _both("Installed programs", "Установленные программы"),
        "system": _both("The system", "Система"),
        "profile": _both("Profile settings", "Настройки профиля"),
        "open_file": _both("In use", "Используется"),
        "app_data": _both("kresorter's own data", "Данные kresorter"),
        "app_program": _both("kresorter's own program", "Программа kresorter"),
    },
    SkipReason: {
        "symlink": _both("A link, not followed", "Ссылка, без перехода по ней"),
        "blocked": _both("Protected", "Защищено"),
        "special": _both("A special file", "Специальный файл"),
        "not_found": _both("Gone while scanning", "Исчез при сканировании"),
        "permission_denied": _both("Permission denied", "Нет доступа"),
        "unreadable": _both("Cannot be read", "Не читается"),
        "changed": _both("Changed while scanning", "Изменился при сканировании"),
    },
    RestoreRefusal: {
        **_ITEM_REFUSALS,
        "conflict": _both("Its place is taken", "Его место занято"),
        "parent_swapped": _both("A folder on its path changed", "Папка на его пути изменилась"),
        "move_failed": _both("Could not be moved back", "Не удалось вернуть"),
    },
    PurgeRefusal: {
        **_ITEM_REFUSALS,
        "delete_failed": _both("Could not be deleted", "Не удалось удалить"),
    },
    StayReason: {
        "not_regular": _both("Not a regular file", "Не обычный файл"),
        "folder_metadata": _both("The folder's own file", "Служебный файл папки"),
        "in_progress": _both("Still being written", "Ещё записывается"),
        "junk": _both("Junk: for the cleanup", "Мусор: для очистки"),
        "unknown_kind": _both("Unknown kind", "Неизвестный тип"),
        "companion": _both("Belongs with other files", "Связан с другими файлами"),
        "program": _both("A program or installer", "Программа или установщик"),
        "path_too_long": _both(
            "Its new path would be too long", "Новый путь был бы слишком длинным"
        ),
        "conflict": _both("Its place is taken", "Его место занято"),
        "category_blocked": _both(
            "Its category's folder cannot be used", "Папку категории нельзя использовать"
        ),
        "missing": _both("No longer there", "Больше нет"),
    },
    FolderReason: {
        "not_found": _both("No such folder", "Нет такой папки"),
        "not_a_directory": _both("Not a folder", "Не папка"),
        "link": _both("A link", "Ссылка"),
        "blocked": _both("A protected location", "Защищённое место"),
        "home": _both("The home folder or above it", "Домашняя папка или выше"),
        "unreadable": _both("Cannot be read", "Не читается"),
        "cloud_sync": _both("A synced folder", "Синхронизируемая папка"),
        "game_library": _both("A game library", "Библиотека игр"),
        "project": _both("A project", "Проект"),
        "cache_or_temp": _both("A cache or temporary folder", "Кэш или временная папка"),
    },
    UndoReason: {
        "not_found": _both("No such batch", "Нет такого пакета"),
        "undo_batch": _both("An undo cannot be undone", "Возврат нельзя отменить"),
        "pending": _both("The batch is unfinished", "Пакет не завершён"),
    },
    Blocker: {
        "no_open_file_check": _both(
            "Files in use cannot be recognized here", "Здесь нельзя распознать открытые файлы"
        ),
        "cloud_sync": _both("Folders synced to the cloud", "Папки синхронизируются с облаком"),
    },
    BatchKind: {
        "organize": _both("Sorted", "Сортировка"),
        "undo": _both("Undo", "Возврат"),
    },
    BatchState: {
        "pending": _both("Unfinished", "Не завершён"),
        "done": _both("Done", "Готово"),
        "rolled_back": _both("Rolled back", "Откачен"),
        "failed": _both("Failed", "Сбой"),
    },
    Source: {
        "xdg_autostart": _both("Desktop autostart", "Автозапуск рабочего стола"),
        "systemd_user": _both("systemd user service", "Пользовательская служба systemd"),
        "run_key": _both("Registry Run", "Реестр: Run"),
        "run_once_key": _both("Registry RunOnce", "Реестр: RunOnce"),
        "startup_folder": _both("Startup folder", "Папка автозагрузки"),
        "service": _both("Service", "Служба"),
        "scheduled_task": _both("Scheduled task", "Задание планировщика"),
        "launch_agent": _both("Launch agent", "Агент запуска"),
    },
    Scope: {
        "user": _both("This user", "Этот пользователь"),
        "system": _both("All users", "Все пользователи"),
    },
    ChangeState: {
        "pending": _both("Unfinished", "Не завершено"),
        "done": _both("Done", "Готово"),
        "failed": _both("Failed", "Сбой"),
        "rolled_back": _both("Rolled back", "Откачено"),
    },
    ChangeRefusal: {
        "read_only": _both("This kind of entry is not changed", "Такие записи не изменяются"),
        "changed": _both("Changed since it was listed", "Изменилась после показа списка"),
        "already": _both("Already so", "Уже так"),
        "pending": _both("Unfinished work first", "Сначала незавершённая работа"),
        "other_device": _both("The store is on another drive", "Хранилище на другом диске"),
        "too_large": _both("Too large", "Слишком большая"),
        "foreign": _both("Not disabled by kresorter", "Отключена не через kresorter"),
        "original_changed": _both("Its original has changed", "Её оригинал изменился"),
    },
    Domain: {
        "quarantine": _both("Quarantine", "Карантин"),
        "autostart": _both("Autostart", "Автозагрузка"),
        "organize": _both("Organize", "Сортировка"),
    },
    Unavailable: {
        "config": _both("The settings are refused", "Настройки отклонены"),
        # Either server may be the one asked (decision 0019, item 11).
        "unreachable": _both("The local AI is not running", "Локальный ИИ не запущен"),
        "timeout": _both("The local AI did not answer in time", "Локальный ИИ не ответил вовремя"),
        "redirect": _both(
            "The local AI redirected the request", "Локальный ИИ перенаправил запрос"
        ),
        "http_status": _both("The local AI returned an error", "Локальный ИИ вернул ошибку"),
        "not_ollama": _both("It is not Ollama", "Это не Ollama"),
        "not_lmstudio": _both("It is not LM Studio", "Это не LM Studio"),
        "model_missing": _both("The model is not installed", "Модель не установлена"),
        "too_large": _both("The answer is too large", "Ответ слишком большой"),
        "bad_response": _both("The answer cannot be read", "Ответ не читается"),
        "empty": _both("The answer is empty", "Ответ пустой"),
    },
    SessionFailure: {
        "data_dir": _both("The data folder cannot be used here", "Папка данных здесь недопустима"),
        "locked": _both("kresorter is busy elsewhere", "kresorter уже занят другим процессом"),
        "data_dir_os": _both("The data folder cannot be used", "Папку данных нельзя использовать"),
        "journal_open": _both("The journal cannot be opened", "Журнал не открывается"),
        "stopped": _both("Stopped", "Остановлено"),
        "journal_failed": _both("The journal failed", "Сбой журнала"),
    },
    Unused: {
        "unreadable": _both("The file cannot be read", "Файл не читается"),
        "not_json": _both("The file is not valid JSON", "Файл не является корректным JSON"),
        "not_an_object": _both("The file is not a JSON object", "Файл не является объектом JSON"),
        "wrong_value": _both(
            "A setting has a wrong or unknown value",
            "У настройки неверное или неизвестное значение",
        ),
    },
}
