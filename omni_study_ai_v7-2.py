#!/usr/bin/env python3
# OMNI STUDY AI v7 — один файл, без сторонних пакетов.
# Карточки (SM-2), задачи, экзамены, Pomodoro, математика (уравнения, производные,
# интегралы, матрицы), текст-инструменты, ИИ-команды, самопроверка, запуск с параметрами.
# Онлайн-ИИ по желанию (ANTHROPIC_API_KEY): python omni_study_ai.py --help

from __future__ import annotations

import csv
import difflib
import json
import math
import os
import re
import urllib.error
import urllib.request
import wave
import base64
import hashlib
import random
import secrets
import shutil
import statistics
import time
from collections import Counter
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

try:  # стрелки вверх/вниз и история ввода
    import readline  # noqa: F401
except ImportError:
    pass

APP_NAME = "OMNI STUDY AI"
VERSION = "7.0"
DATA_PATH = Path("omni_study_ai_data.json")
EXPORT_DIR = Path("omni_ai_exports")

MAX_HISTORY = 300
MAX_FILE_READ = 1_000_000      # сколько байт читаем из текстового файла
MAX_INPUT = 4000               # макс. длина сообщения
MAX_NOTE_LEN = 5000
MAX_NOTES = 500
MAX_SCAN_FILES = 5000          # лимит при обходе папки
MAX_EXPR_LEN = 200

# Онлайн-ИИ включается, только если задан ключ в переменной окружения.
API_URL = "https://api.anthropic.com/v1/messages"
API_MODEL = os.getenv("OMNI_MODEL", "claude-sonnet-5-5")

RULE = (
    "Ты — помощник для учёбы. Помогай с задачами, идеями и анализом. "
    "Объясняй по шагам и простыми словами, отвечай на языке пользователя. "
    "Не вреди людям и не давай опасных инструкций."
)

MODES = {
    "1": ("Домашка", "разбор задач по шагам",
          "Режим: разбор задач. Решай по шагам: данные, формула, подстановка, проверка."),
    "2": ("Объяснение", "объяснение темы простыми словами",
          "Режим: объяснение. Суть простыми словами, пример, короткая самопроверка."),
    "3": ("Шпаргалка", "краткие правила и формулы",
          "Режим: шпаргалка. Только главное: определения, формулы, частые ошибки."),
    "4": ("Текст", "план, сочинение и редактирование",
          "Режим: тексты. Помогай с планом, сочинением и редактурой."),
    "5": ("Языки", "перевод и грамматика",
          "Режим: языки. Перевод, грамматика, примеры употребления."),
    "6": ("Свободный режим", "вопросы, идеи и анализ",
          "Режим: свободный. Отвечай на любые учебные и творческие вопросы."),
}

COLORS = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
    "red": "\033[31m",
}
USE_COLOR = os.getenv("NO_COLOR") is None


def color(text: Any, name: str) -> str:
    if not USE_COLOR:
        return str(text)
    return COLORS.get(name, "") + str(text) + COLORS["reset"]


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- данные
def default_data() -> dict[str, Any]:
    return {
        "mode": "6",
        "ai": True,
        "history": [],
        "notes": {},
        "stats": {"messages": 0, "files": 0, "calculations": 0,
                  "pomodoros": 0, "minutes": 0, "cards_reviewed": 0},
        "cards": [], "todos": [], "grades": [], "days": [], "exams": [],
    }


def load_data() -> dict[str, Any]:
    data = default_data()
    if not DATA_PATH.exists():
        return data
    for candidate in (DATA_PATH, DATA_PATH.with_suffix(".bak")):
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        if raw.get("mode") in MODES:
            data["mode"] = raw["mode"]
        if isinstance(raw.get("ai"), bool):
            data["ai"] = raw["ai"]
        if isinstance(raw.get("history"), list):
            data["history"] = [
                h for h in raw["history"][-MAX_HISTORY:]
                if isinstance(h, dict) and isinstance(h.get("user", ""), str)
                and isinstance(h.get("assistant", ""), str)
            ]
        if isinstance(raw.get("notes"), dict):
            data["notes"] = {
                str(k)[:100]: str(v)[:MAX_NOTE_LEN]
                for k, v in list(raw["notes"].items())[:MAX_NOTES]
            }
        if isinstance(raw.get("stats"), dict):
            for key in data["stats"]:
                val = raw["stats"].get(key)
                if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
                    data["stats"][key] = val
        sanitize_extra(raw, data)
        sanitize_exams(raw, data)
        if candidate != DATA_PATH:
            print(color("Основной файл повреждён — восстановлено из резервной копии.", "yellow"))
        return data
    print(color("Не удалось загрузить сохранение; запускаю с чистыми данными.", "yellow"))
    return data


def save_data(data: dict[str, Any]) -> None:
    """Надёжная запись: временный файл, резервная копия и уборка при ошибке."""
    temp = DATA_PATH.with_suffix(DATA_PATH.suffix + ".tmp")
    backup = DATA_PATH.with_suffix(DATA_PATH.suffix + ".bak")
    try:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        temp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        if DATA_PATH.exists():
            try:
                shutil.copy2(DATA_PATH, backup)
            except OSError:
                pass
        temp.replace(DATA_PATH)
    except (OSError, TypeError, ValueError) as exc:
        print(color(f"Ошибка сохранения: {exc}", "red"))
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass



def clear_screen() -> None:
    # без os.system — никакого запуска оболочки
    print("\033[2J\033[H", end="")


# ---------------------------------------------------------------- вывод
def print_banner() -> None:
    print(color(f"\n  ╔═ {APP_NAME} v{VERSION} ═╗\n", "cyan"))


def print_menu(mode: str) -> None:
    print(color("РЕЖИМЫ (введи цифру 1-6)", "bold"))
    for key, (name, desc, _) in MODES.items():
        mark = "●" if key == mode else " "
        print(f" {mark} [{key}] {name:<16} — {desc}")
    print(color("\nКОМАНДЫ (!help — подробнее)", "bold"))
    print(" !help  !menu  !mode N  !ai on/off  !calc  !file  !note  !notes")
    print(" !search слово  !history [N]  !stats  !export  !reset  !clear  !quit")
    print(color(" !tools — карточки, задачи, Pomodoro, математика, текст, утилиты", "cyan"))
    print(color(" !today / !dashboard — быстрый обзор учёбы", "dim"))
    print(color("-" * 52, "dim"))


def print_help() -> None:
    print("""
Примеры:
  !mode 2               режим «Объяснение»  (или просто напиши цифру 2)
  !calc (12 + 8) / 4    калькулятор: sqrt, sin, cos, ln, log, pi, 2^8 ...
  !note био -> клетка — единица живого
  !note del био         удалить заметку
  !notes                список заметок
  !search клетка        поиск по заметкам и истории
  !file "путь"          анализ файла/папки (только внутри домашней папки и текущей)
  !history 15           последние 15 реплик
  !export               экспорт в JSON, TXT и Markdown
  !ai on / !ai off      включить/выключить онлайн-ИИ
  !reset                стереть историю (с подтверждением)
  !tools                все дополнительные инструменты (!today — сводка дня)

Короткие команды: !m, !c, !n, !s, !h, !q.  Напиши заметку по ключу — покажу её.

Онлайн-ИИ: задай переменную ANTHROPIC_API_KEY (ключ нигде не сохраняется).
Без ключа работают локальные шаблоны.
Внимание: в онлайн-режиме твои сообщения отправляются в Anthropic.
""".strip())


# ---------------------------------------------------------------- калькулятор
TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)|([A-Za-z_]+)|(\+|-|\*|/|%|\^|\(|\)|,))")

FUNCTIONS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log10, "ln": math.log, "abs": abs, "round": round,
    "floor": math.floor, "ceil": math.ceil, "min": min, "max": max,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
MAX_DEPTH = 50


class MathParser:
    def __init__(self, expression: str):
        if len(expression) > MAX_EXPR_LEN:
            raise ValueError("Выражение слишком длинное")
        self.tokens = self._tokenize(expression)
        self.pos = 0
        self.depth = 0

    @staticmethod
    def _tokenize(expression: str):
        tokens, pos = [], 0
        while pos < len(expression):
            match = TOKEN_RE.match(expression, pos)
            if not match:
                if expression[pos:].strip() == "":
                    break
                raise ValueError(f"Недопустимый символ: {expression[pos]!r}")
            number, name, operator = match.groups()
            if number is not None:
                tokens.append(("num", float(number)))
            elif name is not None:
                tokens.append(("name", name.lower()))
            else:
                tokens.append((operator, operator))
            pos = match.end()
        if not tokens:
            raise ValueError("Пустое выражение")
        return tokens

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, kind=None):
        tok = self.peek()
        if tok is None or (kind is not None and tok[0] != kind):
            return None
        self.pos += 1
        return tok

    def parse(self):
        value = self.expression()
        if self.peek() is not None:
            raise ValueError("Лишние символы в выражении")
        value = float(value)
        if not math.isfinite(value) or abs(value) > 1e100:
            raise ValueError("Результат слишком большой или не является числом")
        return int(value) if value.is_integer() else round(value, 10)

    def expression(self):
        value = self.term()
        while self.peek() and self.peek()[0] in ("+", "-"):
            op = self.take()[0]
            right = self.term()
            value = value + right if op == "+" else value - right
        return value

    def term(self):
        value = self.unary()
        while True:
            tok = self.peek()
            implicit = tok and tok[0] in ("num", "name", "(")
            if tok and tok[0] in ("*", "/", "%"):
                op = self.take()[0]
                rhs = self.unary()
                if op == "*":
                    value *= rhs
                elif rhs == 0:
                    raise ZeroDivisionError("Деление на ноль")
                elif op == "/":
                    value /= rhs
                else:
                    value %= rhs
            elif implicit:
                value *= self.unary()
            else:
                break
        return value

    def unary(self):
        tok = self.peek()
        if tok and tok[0] in ("+", "-"):
            op = self.take()[0]
            self._enter()
            val = self.unary()
            self.depth -= 1
            return val if op == "+" else -val
        return self.power()

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ValueError("Слишком глубокая вложенность")

    @staticmethod
    def _safe_pow(base, exp):
        # защита от зависания на выражениях вроде 9^9^9
        if base == 0:
            if exp < 0:
                raise ZeroDivisionError("0 в отрицательной степени")
            return 0.0 ** exp
        if base < 0 and float(exp) != int(exp):
            raise ValueError("Корень чётной степени из отрицательного числа")
        if abs(exp) * math.log10(abs(base) or 1) > 100:
            raise ValueError("Результат слишком большой")
        return float(base) ** exp

    def power(self):
        value = self.primary()
        if self.take("^"):
            self._enter()
            exponent = self.unary()
            self.depth -= 1
            value = self._safe_pow(value, exponent)
        return value

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise ValueError("Ожидалось число")
        if tok[0] == "num":
            self.take("num")
            return tok[1]
        if tok[0] == "name":
            name = self.take("name")[1]
            if name in CONSTANTS:
                return CONSTANTS[name]
            if name not in FUNCTIONS:
                raise ValueError(f"Неизвестная функция или переменная: {name}")
            if not self.take("("):
                raise ValueError(f"Для {name} нужны скобки")
            self._enter()
            args = []
            if not self.take(")"):
                args.append(self.expression())
                while self.take(","):
                    args.append(self.expression())
                if not self.take(")"):
                    raise ValueError("Не закрыта скобка")
            self.depth -= 1
            if name in ("min", "max"):
                if not args:
                    raise ValueError(f"{name} требует хотя бы один аргумент")
                return min(args) if name == "min" else max(args)
            if name == "round":
                if len(args) not in (1, 2):
                    raise ValueError("round принимает 1 или 2 аргумента")
                if len(args) == 2:
                    args[1] = int(args[1])
            elif len(args) != 1:
                raise ValueError(f"{name} принимает один аргумент")
            return FUNCTIONS[name](*args)
        if self.take("("):
            self._enter()
            value = self.expression()
            self.depth -= 1
            if not self.take(")"):
                raise ValueError("Не закрыта скобка")
            return value
        raise ValueError("Ожидалось число или скобка")


def calculate(expression: str):
    try:
        return MathParser(expression).parse()
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:
        return f"Ошибка: {exc}"
    except RecursionError:
        return "Ошибка: слишком сложное выражение"


# ---------------------------------------------------------------- файлы
TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def is_allowed(path: Path) -> bool:
    """Разрешены только текущая папка и домашняя папка (symlink'и раскрываются)."""
    try:
        real = path.resolve()
    except (OSError, RuntimeError):
        return False
    for root in (Path.cwd().resolve(), Path.home().resolve()):
        if real == root or root in real.parents:
            return True
    return False


def inspect_path(raw: str) -> tuple[str, bool]:
    path = Path(raw.strip().strip('"').strip("'")).expanduser()
    if not path.exists():
        return f"Не найдено: {path}", False
    if not is_allowed(path):
        return "Доступ закрыт: можно смотреть только текущую и домашнюю папки.", False

    if path.is_dir():
        all_files: list[Path] = []
        for p in path.rglob("*"):
            if p.is_symlink():
                continue
            if p.is_file():
                all_files.append(p)
                if len(all_files) >= MAX_SCAN_FILES:
                    break
        ext_counts = Counter(p.suffix.lower() or "(без расширения)" for p in all_files)
        lines = [f"📁 Папка: {path.resolve()}",
                 f"Файлов: {len(all_files)}" + (" (лимит просмотра)" if len(all_files) >= MAX_SCAN_FILES else "")]
        lines.append("Типы: " + (", ".join(f"{k} — {v}" for k, v in ext_counts.most_common(12)) or "нет"))
        sized = []
        for p in all_files:
            try:
                sized.append((p.stat().st_size, p.name))
            except OSError:
                pass
        if sized:
            lines.append("Самые большие:")
            lines += [f" • {n} — {s / 1024:.1f} KB" for s, n in sorted(sized, reverse=True)[:5]]
        return "\n".join(lines), True

    size = path.stat().st_size
    ext = path.suffix.lower()
    lines = [
        f"📄 {path.name}",
        f"Путь: {path.resolve()}",
        f"Размер: {size:,} байт ({size / 1024:.2f} KB)",
        f"Расширение: {ext or '(нет)'}",
    ]
    if ext == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
                lines.append(f"WAV: {audio.getnchannels()} кан., {audio.getframerate()} Hz, {seconds:.1f} сек.")
        except (wave.Error, OSError, ZeroDivisionError, EOFError) as exc:
            lines.append(f"WAV не прочитан: {exc}")
    elif ext in IMAGE_EXTS:
        lines.append("Изображение: компьютерного зрения в программе нет.")
    elif ext in AUDIO_EXTS:
        lines.append("Аудио: распознавание не встроено.")
    elif ext in VIDEO_EXTS:
        lines.append("Видео: покадровый анализ не встроен.")
    elif ext in TEXT_EXTS:
        try:
            with path.open("rb") as fh:  # читаем только начало файла
                content = fh.read(MAX_FILE_READ).decode("utf-8", errors="replace")
            truncated = size > MAX_FILE_READ
            lines.append(f"Текст: {len(content)} символов, {len(content.splitlines())} строк"
                         + (" (показано начало)" if truncated else ""))
            if ext == ".json":
                if truncated:
                    lines.append("JSON слишком большой для проверки.")
                else:
                    parsed = json.loads(content)
                    lines.append(f"JSON корректен; тип корня: {type(parsed).__name__}")
                    lines.append("Превью:\n" + json.dumps(parsed, ensure_ascii=False, indent=2)[:1200])
            elif ext == ".csv":
                rows = []
                for i, row in enumerate(csv.reader(content.splitlines())):
                    if i >= 1000:
                        break
                    rows.append(row)
                lines.append(f"CSV: просмотрено строк — {len(rows)}")
                if rows:
                    lines.append("Первая строка: " + " | ".join(rows[0][:12]))
            else:
                words = re.findall(r"\b[\w-]{3,}\b", content.lower())
                if words:
                    lines.append("Частые слова: " + ", ".join(f"{w}({n})" for w, n in Counter(words).most_common(8)))
                lines.append("Превью:\n" + content[:1200])
        except (OSError, json.JSONDecodeError, csv.Error) as exc:
            lines.append(f"Ошибка чтения: {exc}")
    else:
        lines.append("Для этого типа файла анализ не подключён.")
    return "\n".join(lines), True


# ---------------------------------------------------------------- ИИ
def ai_available(data: dict) -> bool:
    return bool(data.get("ai")) and bool(os.getenv("ANTHROPIC_API_KEY"))


def ask_llm(mode: str, text: str, data: dict) -> str | None:
    """Онлайн-ответ через API. При любой ошибке возвращает None (будет локальный ответ)."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None

    messages: list[dict[str, str]] = []
    for item in data["history"][-12:]:
        if item.get("src") == "ai":  # шаблонные ответы в контекст не берём
            messages.append({"role": "user", "content": item["user"][:MAX_INPUT]})
            messages.append({"role": "assistant", "content": item["assistant"][:MAX_INPUT * 2]})
    messages.append({"role": "user", "content": text[:MAX_INPUT]})

    body = json.dumps({
        "model": API_MODEL,
        "max_tokens": 1000,
        "system": RULE + " " + MODES[mode][2],
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        answer = "\n".join(p for p in parts if p).strip()
        return answer or None
    except urllib.error.HTTPError as exc:
        hint = {401: "неверный ключ", 429: "лимит запросов", 529: "сервис перегружен"}.get(exc.code, "")
        print(color(f"ИИ недоступен (HTTP {exc.code}{', ' + hint if hint else ''}). Отвечаю локально.", "yellow"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        print(color("Нет связи с ИИ. Отвечаю локально.", "yellow"))
    return None


def local_reply(mode: str, q: str) -> str:
    if mode == "1":
        return (f"📚 Разбор задачи\n\nУсловие: {q}\n\n1) Выпиши данные и единицы.\n"
                "2) Определи, что найти.\n3) Выбери формулу.\n4) Подставь значения.\n5) Проверь ответ.")
    if mode == "2":
        return (f"💡 Тема: {q}\n\n• Суть простыми словами\n• Пример применения\n"
                "• Проверка: объясни своими словами")
    if mode == "3":
        return (f"📌 Шпаргалка: {q}\n\n• Определение:\n• Правило / формула:\n"
                "• Пример:\n• Частая ошибка:\n\nСохранить: !note тема -> текст")
    if mode == "4":
        return (f"✍️ План текста: {q}\n\n1. Вступление и тезис\n2. Аргумент 1 + пример\n"
                "3. Аргумент 2 + пример\n4. Вывод")
    if mode == "5":
        return (f"🌐 Язык: {q}\n\nУкажи исходный и целевой язык для перевода. "
                "Для грамматики разбери значение, порядок слов и форму.")
    words = re.findall(r"[а-яА-ЯёЁa-zA-Z0-9]{3,}", q.lower())
    keywords = ", ".join(w for w, _ in Counter(words).most_common(5)) or "не выделены"
    return (f"🔎 Разбор: {q}\nКлючевые слова: {keywords}\n\n"
            "Совет: начни с главной мысли, режь текст на короткие блоки, убирай повторы.")


def respond(mode: str, text: str, data: dict) -> tuple[str, str]:
    """Возвращает (ответ, источник): calc / note / ai / local."""
    q = text.strip()
    low = q.lower()

    if low in data["notes"]:
        return f"📝 Заметка «{low}»:\n{data['notes'][low]}", "note"

    if re.fullmatch(r"[\d\s.+\-*/%^(),a-zA-Z_]+", q) and re.search(r"\d", q):
        result = calculate(q)
        if not str(result).startswith("Ошибка:"):
            data["stats"]["calculations"] += 1
            return f"🧮 {q} = {result}", "calc"

    if "=" in q and re.fullmatch(r"[\dxX\s.+\-*/%^()=]+", q) and re.search(r"(?<![A-Za-z])[xX](?![A-Za-z])", q):
        solved = solve_linear(q)
        if solved:
            data["stats"]["calculations"] += 1
            return solved, "calc"

    if ai_available(data):
        answer = ask_llm(mode, q, data)
        if answer:
            return answer, "ai"

    reply = local_reply(mode, q)
    if not os.getenv("ANTHROPIC_API_KEY"):
        reply += "\n\n(Локальный режим. Для умных ответов задай ANTHROPIC_API_KEY.)"
    return reply, "local"


# ---------------------------------------------------------------- команды
def show_notes(data: dict) -> None:
    if not data["notes"]:
        print("Заметок нет. Создай: !note ключ -> текст")
        return
    print(color("ЗАМЕТКИ", "bold"))
    for key, value in sorted(data["notes"].items()):
        short = value if len(value) <= 80 else value[:77] + "..."
        print(f" • {key}: {short}")


def show_stats(data: dict) -> None:
    s = data["stats"]
    state = "онлайн" if ai_available(data) else ("выключен" if not data["ai"] else "нет ключа (локально)")
    print(color("СТАТИСТИКА", "bold"))
    print(f"Сообщений: {s['messages']} | Файлов: {s['files']} | Вычислений: {s['calculations']}")
    print(f"Заметок: {len(data['notes'])} | История: {len(data['history'])} | ИИ: {state}")


def show_history(data: dict, limit: int = 10) -> None:
    items = data["history"][-limit:]
    if not items:
        print("История пустая.")
        return
    for item in items:
        print(f"\n[{item.get('time', '?')}] ({item.get('mode', '?')})")
        print("Ты: " + item.get("user", ""))
        print("AI: " + item.get("assistant", ""))


def search_all(data: dict, needle: str) -> None:
    needle = needle.lower().strip()
    if len(needle) < 2:
        print("Формат: !search слово (минимум 2 символа)")
        return
    found = 0
    for key, value in data["notes"].items():
        if needle in key.lower() or needle in value.lower():
            print(f"📝 {key}: {value[:100]}")
            found += 1
    for item in data["history"]:
        if needle in item.get("user", "").lower() or needle in item.get("assistant", "").lower():
            print(f"💬 [{item.get('time', '?')}] {item.get('user', '')[:100]}")
            found += 1
    for c in data.get("cards", []):
        if needle in c["q"].lower() or needle in c["a"].lower():
            print(f"🃏 {c['q'][:60]} → {c['a'][:40]}")
            found += 1
    for t in data.get("todos", []):
        if needle in t["text"].lower():
            print(f"✅ {t['text'][:80]}")
            found += 1
    if not found:
        print("Ничего не найдено.")


def export_data(data: dict) -> None:
    EXPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_file = EXPORT_DIR / f"omni_export_{ts}.json"
    txt_file = EXPORT_DIR / f"omni_history_{ts}.txt"
    md_file = EXPORT_DIR / f"omni_notes_{ts}.md"
    json_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with txt_file.open("w", encoding="utf-8") as fh:
        for item in data["history"]:
            fh.write(f"[{item.get('time', '')}] {item.get('mode', '')}\n")
            fh.write(f"Ты: {item.get('user', '')}\nAI: {item.get('assistant', '')}\n\n")
    with md_file.open("w", encoding="utf-8") as fh:
        fh.write("# Заметки\n\n")
        for key, value in sorted(data["notes"].items()):
            fh.write(f"## {key}\n{value}\n\n")
    print("Экспорт готов:\n" + "\n".join(f" • {p.resolve()}" for p in (json_file, txt_file, md_file)))


def add_history(data: dict, mode: str, user: str, assistant: str, src: str) -> None:
    data["history"].append({"time": now_stamp(), "mode": mode, "user": user[:MAX_INPUT],
                            "assistant": assistant[:MAX_INPUT * 2], "src": src})
    data["history"] = data["history"][-MAX_HISTORY:]
    data["stats"]["messages"] += 1
    touch_day(data)
    save_data(data)


ALIASES = {
    "!help": "help", "!помощь": "help", "!?": "help",
    "!menu": "menu", "!меню": "menu",
    "!clear": "clear", "!очистить": "clear", "!cls": "clear",
    "!stats": "stats", "!stat": "stats",
    "!notes": "notes",
    "!history": "history", "!h": "history",
    "!export": "export",
    "!mode": "mode", "!m": "mode",
    "!calc": "calc", "!c": "calc",
    "!file": "file", "!f": "file",
    "!note": "note", "!n": "note",
    "!search": "search", "!s": "search", "!find": "search",
    "!ai": "ai",
    "!reset": "reset",
    "!quit": "quit", "!exit": "quit", "!q": "quit", "!выход": "quit",
}


def set_mode(data: dict, mode: str) -> str:
    data["mode"] = mode
    save_data(data)
    print(f"Режим: {MODES[mode][0]}")
    return mode


def command_handler(command: str, data: dict, mode: str) -> tuple[bool, str]:
    parts = command.strip().split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    action = ALIASES.get(name)

    if action is None and name in EXTRA:
        try:
            EXTRA[name][0](arg, data)
        except (KeyboardInterrupt, EOFError):
            print("\nОтменено.")
        return True, mode
    if action is None:
        close = difflib.get_close_matches(name, list(ALIASES) + list(EXTRA), n=1, cutoff=0.6)
        print(f"Неизвестная команда {name}." + (f" Может, {close[0]}?" if close else " Напиши !help."))
        return True, mode

    if action == "quit":
        save_data(data)
        print("Сохранено. Пока!")
        raise SystemExit
    if action == "help":
        print_help()
    elif action == "menu":
        print_menu(mode)
    elif action == "clear":
        clear_screen()
        print_banner()
        print_menu(mode)
    elif action == "stats":
        show_stats(data)
    elif action == "notes":
        show_notes(data)
    elif action == "history":
        try:
            limit = max(1, min(100, int(arg))) if arg else 10
        except ValueError:
            print("Формат: !history [число]")
            return True, mode
        show_history(data, limit)
    elif action == "export":
        try:
            export_data(data)
        except OSError as exc:
            print(color(f"Ошибка экспорта: {exc}", "red"))
    elif action == "mode":
        if arg in MODES:
            mode = set_mode(data, arg)
        else:
            print("Используй !mode 1 ... !mode 6")
    elif action == "calc":
        if not arg:
            print("Пример: !calc (5+3)*2")
        else:
            result = calculate(arg)
            print(f"{arg} = {result}")
            if not str(result).startswith("Ошибка:"):
                data["stats"]["calculations"] += 1
                save_data(data)
    elif action == "file":
        if not arg:
            print('Пример: !file "путь к файлу"')
        else:
            report, ok = inspect_path(arg)
            print(report)
            if ok:
                data["stats"]["files"] += 1
                save_data(data)
    elif action == "search":
        search_all(data, arg)
    elif action == "ai":
        if arg.lower() in ("on", "вкл"):
            data["ai"] = True
        elif arg.lower() in ("off", "выкл"):
            data["ai"] = False
        else:
            print("Формат: !ai on | !ai off")
            return True, mode
        save_data(data)
        if data["ai"] and not os.getenv("ANTHROPIC_API_KEY"):
            print("ИИ включён, но ключа ANTHROPIC_API_KEY нет — буду отвечать локально.")
        else:
            print("Онлайн-ИИ: " + ("включён" if data["ai"] else "выключен"))
    elif action == "reset":
        if input("Стереть всю историю? Заметки останутся. [да/нет] > ").strip().lower() in ("да", "y", "yes"):
            data["history"] = []
            save_data(data)
            print("История очищена.")
        else:
            print("Отменено.")
    elif action == "note":
        if not arg:
            print("Формат: !note имя -> текст  |  !note del имя")
        elif arg.lower().startswith(("del ", "delete ")):
            key = arg.split(maxsplit=1)[1].strip().lower()
            if key in data["notes"]:
                del data["notes"][key]
                save_data(data)
                print(f"Заметка «{key}» удалена.")
            else:
                print("Такой заметки нет.")
        elif "->" in arg:
            key, value = arg.split("->", 1)
            key, value = key.strip().lower()[:100], value.strip()[:MAX_NOTE_LEN]
            if not key or not value:
                print("Название и текст не должны быть пустыми.")
            elif key not in data["notes"] and len(data["notes"]) >= MAX_NOTES:
                print(f"Достигнут лимит заметок ({MAX_NOTES}).")
            else:
                data["notes"][key] = value
                save_data(data)
                print(f"Заметка «{key}» сохранена.")
        else:
            print("Формат: !note название -> текст")
    return True, mode


# ====================================================================
#                     v5: ДОПОЛНИТЕЛЬНЫЕ ИНСТРУМЕНТЫ
# ====================================================================
EXTRA: dict[str, tuple[Any, str, str, str]] = {}  # !имя -> (функция, группа, описание, имена)


def tool(names: str, group: str, desc: str):
    def deco(fn):
        for n in names.split():
            EXTRA[n] = (fn, group, desc, names)
        return fn
    return deco


# ---------- общие помощники ----------
def today_str() -> str:
    return date.today().isoformat()


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def fmt(x: Any) -> str:
    if isinstance(x, complex):
        re_, im = round(x.real, 8), round(x.imag, 8)
        return f"{fmt(re_)} {'+' if im >= 0 else '-'} {fmt(abs(im))}i"
    if isinstance(x, float):
        if x.is_integer() and abs(x) < 1e15:
            return str(int(x))
        return f"{x:.10g}"
    return str(x)


def touch_day(data: dict) -> None:
    days = data.setdefault("days", [])
    if today_str() not in days:
        days.append(today_str())
        data["days"] = days[-400:]


def streak(data: dict) -> int:
    days = {parse_date(d) for d in data.get("days", [])} - {None}
    cur = date.today()
    if cur not in days:
        cur -= timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def parse_index(text: str, size: int) -> int | None:
    try:
        i = int(text.strip())
    except ValueError:
        print("Нужен номер, например: 3")
        return None
    if not 1 <= i <= size:
        print(f"Номер вне диапазона 1..{size}")
        return None
    return i - 1


def sanitize_extra(raw: dict, data: dict) -> None:
    """Проверка и очистка новых разделов сохранения."""
    def lst(key: str, limit: int) -> list:
        v = raw.get(key)
        return v[:limit] if isinstance(v, list) else []

    cards = []
    for c in lst("cards", 2000):
        if not isinstance(c, dict) or not c.get("q") or not c.get("a"):
            continue
        try:
            ease, interval, reps = float(c.get("ease", 2.5)), int(c.get("interval", 0)), int(c.get("reps", 0))
        except (TypeError, ValueError):
            continue
        cards.append({
            "q": str(c["q"])[:500], "a": str(c["a"])[:1000],
            "ease": min(max(ease, 1.3), 4.0),
            "interval": max(0, min(interval, 3650)), "reps": max(0, min(reps, 1000)),
            "due": c["due"] if parse_date(c.get("due")) else today_str(),
        })
    data["cards"] = cards

    todos = []
    for t in lst("todos", 1000):
        if isinstance(t, dict) and t.get("text"):
            todos.append({"text": str(t["text"])[:300], "done": bool(t.get("done")),
                          "due": t["due"] if parse_date(t.get("due")) else None})
    data["todos"] = todos

    grades = []
    for g in lst("grades", 1000):
        if not isinstance(g, dict) or not g.get("subject"):
            continue
        try:
            grade, weight = float(g.get("grade")), float(g.get("weight", 1))
        except (TypeError, ValueError):
            continue
        if 0 <= grade <= 100 and 0.1 <= weight <= 10:
            grades.append({"subject": str(g["subject"])[:60], "grade": grade, "weight": weight})
    data["grades"] = grades

    data["days"] = [d for d in lst("days", 400) if parse_date(d)]


def brief(data: dict) -> str:
    today = date.today()
    due_cards = sum(1 for c in data["cards"] if (parse_date(c["due"]) or today) <= today)
    open_t = [t for t in data["todos"] if not t["done"]]
    overdue = sum(1 for t in open_t if (parse_date(t["due"]) or today + timedelta(days=1)) < today)
    lines = exam_lines(data)
    if due_cards:
        lines.append(f"🃏 Карточек к повторению: {due_cards}  (!quiz)")
    if open_t:
        lines.append(f"✅ Открытых задач: {len(open_t)}" + (f", просрочено: {overdue}" if overdue else "") + "  (!todo list)")
    s = streak(data)
    if s:
        lines.append(f"🔥 Серия занятий: {s} дн.")
    return "\n".join(lines)


# ---------- карточки (интервальное повторение SM-2) ----------
def new_card(q: str, a: str) -> dict:
    return {"q": q, "a": a, "ease": 2.5, "interval": 0, "reps": 0, "due": today_str()}


def sm2(card: dict, quality: int) -> None:
    if quality < 3:
        card["reps"], card["interval"] = 0, 1
    else:
        card["reps"] += 1
        if card["reps"] == 1:
            card["interval"] = 1
        elif card["reps"] == 2:
            card["interval"] = 6
        else:
            card["interval"] = min(3650, round(card["interval"] * card["ease"]))
    card["ease"] = max(1.3, card["ease"] + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    card["due"] = (date.today() + timedelta(days=card["interval"])).isoformat()


def cards_from_text(text: str) -> list[tuple[str, str]]:
    out = []
    for line in re.split(r"[\n;]+", text):
        m = re.match(r"\s*(.{2,120}?)\s*(?:—|–| - |:)\s*(.{2,500})", line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


@tool("!card !cards", "Учёба", "карточки: !card add в | о · list · del N · gen заметка · stats")
def cmd_card(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    sub, rest, cards = sub.lower(), rest.strip(), data["cards"]
    if sub == "add":
        if "|" not in rest:
            print("Формат: !card add вопрос | ответ")
            return
        q, a = (x.strip() for x in rest.split("|", 1))
        if not q or not a:
            print("Вопрос и ответ не должны быть пустыми.")
        elif len(cards) >= 2000:
            print("Достигнут лимит карточек (2000).")
        else:
            cards.append(new_card(q[:500], a[:1000]))
            save_data(data)
            print(f"Карточка #{len(cards)} добавлена.")
    elif sub in ("", "list"):
        if not cards:
            print("Карточек нет. Добавь: !card add вопрос | ответ")
        today = date.today()
        for i, c in enumerate(cards[:40], 1):
            due = (parse_date(c["due"]) or today) <= today
            print(f" {i:>3}. {'🔔' if due else '  '} {c['q'][:60]} → {c['a'][:40]}")
        if len(cards) > 40:
            print(f" ... и ещё {len(cards) - 40}")
    elif sub == "del":
        i = parse_index(rest, len(cards))
        if i is not None:
            cards.pop(i)
            save_data(data)
            print("Карточка удалена.")
    elif sub == "gen":
        note = data["notes"].get(rest.lower())
        if note is None:
            print("Заметки с таким названием нет. Формат строк в заметке: термин — определение; ...")
            return
        have = {c["q"].lower() for c in cards}
        added = 0
        for q, a in cards_from_text(note):
            if q.lower() not in have and len(cards) < 2000:
                cards.append(new_card(q[:500], a[:1000]))
                have.add(q.lower())
                added += 1
        save_data(data)
        print(f"Создано карточек: {added}" if added else "Не нашёл пар «термин — определение» (разделители: — : ;)")
    elif sub == "stats":
        today = date.today()
        due = sum(1 for c in cards if (parse_date(c["due"]) or today) <= today)
        mature = sum(1 for c in cards if c["interval"] >= 21)
        print(f"Всего: {len(cards)} | к повторению: {due} | выученных (интервал ≥21 дн.): {mature}")
    else:
        print("Подкоманды: add, list, del N, gen заметка, stats")


@tool("!quiz !review", "Учёба", "повторение карточек на сегодня (до 20 штук)")
def cmd_quiz(arg: str, data: dict) -> None:
    today = date.today()
    due = [c for c in data["cards"] if (parse_date(c["due"]) or today) <= today]
    if not due:
        print("На сегодня карточек нет 🎉  Добавь: !card add вопрос | ответ")
        return
    random.shuffle(due)
    due = due[:20]
    done = 0
    try:
        for i, c in enumerate(due, 1):
            input(f"\n[{i}/{len(due)}] {c['q']}\n  (Enter — показать ответ) ")
            print(color(f"  → {c['a']}", "green"))
            g = input("  1 не знал · 2 трудно · 3 хорошо · 4 легко · q стоп > ").strip().lower()
            if g == "q":
                break
            sm2(c, {"1": 1, "2": 3, "3": 4, "4": 5}.get(g, 4))
            done += 1
    finally:
        if done:
            data["stats"]["cards_reviewed"] += done
            touch_day(data)
            save_data(data)
            print(f"\nПовторено карточек: {done}. Молодец!")


# ---------- задачи ----------
@tool("!todo !t", "Планирование", "задачи: add текст [до ГГГГ-ММ-ДД] · list · done N · del N · clear")
def cmd_todo(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    sub, rest, todos = sub.lower(), rest.strip(), data["todos"]
    if sub == "add":
        m = re.search(r"(?:до|due)\s+(\d{4}-\d{2}-\d{2})", rest)
        due = None
        if m:
            due = m.group(1) if parse_date(m.group(1)) else None
            rest = (rest[:m.start()] + rest[m.end():]).strip()
        if not rest:
            print("Формат: !todo add текст [до 2026-12-31]")
        elif len(todos) >= 1000:
            print("Слишком много задач. Очисти выполненные: !todo clear")
        else:
            todos.append({"text": rest[:300], "done": False, "due": due})
            save_data(data)
            print(f"Задача #{len(todos)} добавлена.")
    elif sub in ("", "list"):
        if not todos:
            print("Задач нет. Добавь: !todo add текст [до 2026-12-31]")
            return
        today = date.today()
        order = sorted(range(len(todos)), key=lambda i: (todos[i]["done"], todos[i]["due"] or "9999", i))
        for i in order[:50]:
            t = todos[i]
            d = parse_date(t["due"])
            flag = "✔" if t["done"] else ("⚠ просрочено" if d and d < today else ("🔥 сегодня" if d == today else ""))
            when = f" (до {t['due']})" if t["due"] else ""
            print(f" {i + 1:>3}. [{'x' if t['done'] else ' '}] {t['text']}{when} {flag}")
    elif sub == "done":
        i = parse_index(rest, len(todos))
        if i is not None:
            todos[i]["done"] = not todos[i]["done"]
            if todos[i]["done"]:
                touch_day(data)
            save_data(data)
            print("Готово ✔" if todos[i]["done"] else "Вернул в работу.")
    elif sub == "del":
        i = parse_index(rest, len(todos))
        if i is not None:
            todos.pop(i)
            save_data(data)
            print("Задача удалена.")
    elif sub == "clear":
        data["todos"] = [t for t in todos if not t["done"]]
        save_data(data)
        print("Выполненные задачи удалены.")
    else:
        print("Подкоманды: add, list, done N, del N, clear")


# ---------- таймеры ----------
def countdown(seconds: int, label: str) -> bool:
    end = time.monotonic() + seconds
    try:
        while True:
            left = int(round(end - time.monotonic()))
            if left <= 0:
                break
            print(f"\r⏳ {label}: {left // 60:02d}:{left % 60:02d}  (Ctrl+C — отмена)   ", end="", flush=True)
            time.sleep(0.5)
        print(f"\r✅ {label}: время вышло!                         \a")
        return True
    except KeyboardInterrupt:
        print(f"\r⏹ {label}: отменено.                            ")
        return False


def parse_duration(text: str) -> int | None:
    t = text.strip().lower().replace(" ", "")
    if re.fullmatch(r"\d+", t):
        return int(t) * 60  # просто число = минуты
    m = re.fullmatch(r"(?:(\d+)(?:h|ч))?(?:(\d+)(?:m|мин|м))?(?:(\d+)(?:s|сек|с))?", t)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


@tool("!pomo !pomodoro", "Планирование", "Pomodoro: !pomo [работа_мин] [отдых_мин] (по умолчанию 25 и 5)")
def cmd_pomo(arg: str, data: dict) -> None:
    nums = [int(n) for n in re.findall(r"\d+", arg)[:2]]
    work = min(max(nums[0], 1), 180) if nums else 25
    rest = min(max(nums[1], 0), 60) if len(nums) > 1 else 5
    if countdown(work * 60, "Работа"):
        data["stats"]["pomodoros"] += 1
        data["stats"]["minutes"] += work
        touch_day(data)
        save_data(data)
        if rest:
            countdown(rest * 60, "Отдых")


@tool("!timer", "Планирование", "таймер: !timer 90s · 5m · 1h30m · 10 (минут)")
def cmd_timer(arg: str, data: dict) -> None:
    sec = parse_duration(arg) if arg else None
    if not sec or sec > 6 * 3600:
        print("Пример: !timer 90s, !timer 5m, !timer 1h30m (максимум 6 часов)")
        return
    countdown(sec, "Таймер")


@tool("!until", "Планирование", "дней до даты: !until 2026-12-31")
def cmd_until(arg: str, data: dict) -> None:
    d = parse_date(arg.strip())
    if not d:
        print("Формат: !until ГГГГ-ММ-ДД")
        return
    n = (d - date.today()).days
    print(f"До {d.isoformat()}: {n} дн. (~{n // 7} нед.)" if n >= 0 else f"С {d.isoformat()} прошло {-n} дн.")


@tool("!today !dash !dashboard", "Планирование", "сводка: серия, карточки, задачи, статистика")
def cmd_today(arg: str, data: dict) -> None:
    s = data["stats"]
    print(color("СЕГОДНЯ " + today_str(), "bold"))
    print(brief(data) or "Всё спокойно. Добавь карточки или задачи!")
    print(f"Помидоров: {s['pomodoros']} | Минут в фокусе: {s['minutes']} | Карточек повторено: {s['cards_reviewed']}")
    print(f"Дней занятий: {len(data['days'])} | Текущая серия: {streak(data)}")


# ---------- математика ----------
def _sub_x(side: str, v: float) -> str:
    return re.sub(r"(?<![A-Za-z])[xX](?![A-Za-z])", f"({v})", side)


def solve_linear(eq: str) -> str | None:
    if eq.count("=") != 1:
        return None
    left, right = eq.split("=")

    def f(v: float) -> float:
        a, b = calculate(_sub_x(left, v)), calculate(_sub_x(right, v))
        if isinstance(a, str) or isinstance(b, str):
            raise ValueError
        return float(a) - float(b)

    try:
        f0, f1, f2 = f(0), f(1), f(2)
    except ValueError:
        return None
    if abs(f2 - 2 * f1 + f0) > 1e-9 * (1 + abs(f0) + abs(f1)):
        return "Это не линейное уравнение. Для квадратного используй: !quad a b c"
    a = f1 - f0
    head = f"📐 {eq.strip()}\nПереносим всё влево: ({fmt(round(a, 10))})·x + ({fmt(round(f0, 10))}) = 0"
    if abs(a) < 1e-12:
        return head + ("\nЛюбое x — решение." if abs(f0) < 1e-9 else "\nРешений нет.")
    x = -f0 / a
    ok = abs(f(x)) < 1e-6 * (1 + abs(x))
    return head + f"\nx = {fmt(round(x, 10))}" + ("\nПроверка: левая часть = правой ✔" if ok else "")


@tool("!solve", "Математика", "линейное уравнение: !solve 2x+3=7")
def cmd_solve(arg: str, data: dict) -> None:
    if not arg:
        print("Пример: !solve 3(x-2)=x+4")
        return
    res = solve_linear(arg)
    if res:
        data["stats"]["calculations"] += 1
        save_data(data)
    print(res or "Не понял уравнение. Используй x, числа и + - * / ^ ( ).")


@tool("!quad", "Математика", "квадратное уравнение: !quad a b c")
def cmd_quad(arg: str, data: dict) -> None:
    try:
        a, b, c = (float(x) for x in re.split(r"[\s;]+", arg.strip()))
    except ValueError:
        print("Формат: !quad a b c  (для ax² + bx + c = 0)")
        return
    if a == 0:
        print("a = 0 — это линейное уравнение." + (f" x = {fmt(-c / b)}" if b else ""))
        return
    d = b * b - 4 * a * c
    print(f"D = {fmt(d)}")
    if d > 0:
        r = math.sqrt(d)
        print(f"x₁ = {fmt((-b + r) / (2 * a))}\nx₂ = {fmt((-b - r) / (2 * a))}")
    elif d == 0:
        print(f"x = {fmt(-b / (2 * a))}")
    else:
        r = math.sqrt(-d) / (2 * a)
        print(f"Комплексные корни:\nx₁ = {fmt(complex(-b / (2 * a), r))}\nx₂ = {fmt(complex(-b / (2 * a), -r))}")


def parse_numbers(arg: str, limit: int = 10000) -> list[float] | None:
    try:
        nums = [float(x) for x in re.split(r"[\s;]+", arg.replace(",", " ").strip()) if x]
    except ValueError:
        return None
    return nums[:limit] if nums else None


@tool("!stat", "Математика", "статистика: !stat 4 8 15 16 23 42")
def cmd_stat(arg: str, data: dict) -> None:
    nums = parse_numbers(arg)
    if not nums or not all(math.isfinite(n) for n in nums):
        print("Пример: !stat 4 8 15 16 23 42")
        return
    print(f"n = {len(nums)} | сумма = {fmt(sum(nums))} | мин = {fmt(min(nums))} | макс = {fmt(max(nums))}")
    print(f"среднее = {fmt(statistics.fmean(nums))} | медиана = {fmt(statistics.median(nums))}")
    print("мода = " + ", ".join(fmt(m) for m in statistics.multimode(nums)[:5]))
    if len(nums) > 1:
        print(f"дисперсия = {fmt(statistics.variance(nums))} | станд. откл. = {fmt(statistics.stdev(nums))}")


def _ints(arg: str) -> list[int] | None:
    try:
        nums = [int(x) for x in arg.replace(",", " ").split()]
    except ValueError:
        return None
    return nums if len(nums) >= 2 and all(abs(n) <= 10**18 for n in nums) else None


@tool("!gcd", "Математика", "НОД: !gcd 12 18 30")
def cmd_gcd(arg: str, data: dict) -> None:
    nums = _ints(arg)
    print(f"НОД = {math.gcd(*nums)}" if nums else "Пример: !gcd 12 18")


@tool("!lcm", "Математика", "НОК: !lcm 4 6 10")
def cmd_lcm(arg: str, data: dict) -> None:
    nums = _ints(arg)
    print(f"НОК = {math.lcm(*nums)}" if nums else "Пример: !lcm 4 6")


@tool("!prime", "Математика", "простое ли число и разложение на множители (до 10¹²)")
def cmd_prime(arg: str, data: dict) -> None:
    try:
        n = int(arg.strip())
    except ValueError:
        n = 0
    if not 2 <= n <= 10**12:
        print("Пример: !prime 360  (число от 2 до 10^12)")
        return
    m, factors, p = n, [], 2
    while p * p <= m:
        while m % p == 0:
            factors.append(p)
            m //= p
        p += 1 if p == 2 else 2
    if m > 1:
        factors.append(m)
    if len(factors) == 1:
        print(f"{n} — простое число.")
    else:
        print(f"{n} — составное: " + " · ".join(f"{k}^{v}" if v > 1 else str(k) for k, v in sorted(Counter(factors).items())))


@tool("!base", "Математика", "системы счисления: !base ff 16 2  (число, из, в)")
def cmd_base(arg: str, data: dict) -> None:
    parts = arg.split()
    try:
        src = int(parts[1]) if len(parts) > 1 else 10
        dst = int(parts[2]) if len(parts) > 2 else (2 if src == 10 else 10)
        if not (2 <= src <= 36 and 2 <= dst <= 36) or len(parts[0]) > 200:
            raise ValueError
        n = int(parts[0], src)
    except (ValueError, IndexError):
        print("Пример: !base 255 10 16   или   !base ff 16 2")
        return
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out, m = "", abs(n)
    while m:
        m, r = divmod(m, dst)
        out = digits[r] + out
    print(f"{parts[0]} (осн. {src}) = {('-' if n < 0 else '') + (out or '0')} (осн. {dst})")


LINEAR_UNITS = {
    "длина": {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344},
    "масса": {"g": 0.001, "kg": 1, "t": 1000, "lb": 0.45359237, "oz": 0.028349523125},
    "время": {"s": 1, "min": 60, "h": 3600, "d": 86400, "wk": 604800},
    "объём": {"ml": 0.001, "l": 1, "gal": 3.785411784},
    "скорость": {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704},
}
UNIT_ALIASES = {
    "км": "km", "м": "m", "см": "cm", "мм": "mm", "миля": "mi", "мили": "mi", "фут": "ft", "дюйм": "in",
    "кг": "kg", "г": "g", "т": "t", "фунт": "lb", "унция": "oz", "с": "s", "сек": "s", "мин": "min",
    "ч": "h", "час": "h", "сут": "d", "нед": "wk", "л": "l", "мл": "ml", "км/ч": "km/h", "kmh": "km/h",
    "kph": "km/h", "м/с": "m/s", "°c": "c", "°f": "f", "цельсий": "c", "кельвин": "k",
}


@tool("!conv", "Математика", "конвертер: !conv 5 km mi · !conv 36.6 c f · !conv 10 кг lb")
def cmd_conv(arg: str, data: dict) -> None:
    toks = [t for t in arg.split() if t.lower() not in ("to", "в", "->")]
    try:
        value = float(toks[0].replace(",", "."))
        src, dst = (UNIT_ALIASES.get(t.lower(), t.lower()) for t in toks[1:3])
        if len(toks) != 3 or not math.isfinite(value):
            raise ValueError
    except (ValueError, IndexError):
        print("Пример: !conv 5 km mi. Единицы: " + ", ".join(u for g in LINEAR_UNITS.values() for u in g) + ", c, f, k")
        return
    temps = {"c", "f", "k"}
    if src in temps and dst in temps:
        c = value if src == "c" else (value - 32) * 5 / 9 if src == "f" else value - 273.15
        out = c if dst == "c" else c * 9 / 5 + 32 if dst == "f" else c + 273.15
        print(f"{fmt(value)} °{src.upper()} = {fmt(round(out, 6))} °{dst.upper()}")
        return
    for group in LINEAR_UNITS.values():
        if src in group and dst in group:
            print(f"{fmt(value)} {src} = {fmt(round(value * group[src] / group[dst], 8))} {dst}")
            return
    print("Эти единицы нельзя конвертировать друг в друга (или они неизвестны).")


@tool("!grade !gpa", "Учёба", "оценки: add предмет оценка [вес] · list · del N  (средний балл)")
def cmd_grade(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    sub, rest, grades = sub.lower(), rest.strip(), data["grades"]
    if sub == "add":
        m = re.fullmatch(r"(.+?)\s+(\d+(?:[.,]\d+)?)(?:\s+(\d+(?:[.,]\d+)?))?", rest)
        if not m:
            print("Формат: !grade add математика 5 [вес]")
            return
        g, w = float(m.group(2).replace(",", ".")), float((m.group(3) or "1").replace(",", "."))
        if not (0 <= g <= 100 and 0.1 <= w <= 10) or len(grades) >= 1000:
            print("Оценка 0..100, вес 0.1..10.")
            return
        grades.append({"subject": m.group(1)[:60], "grade": g, "weight": w})
        save_data(data)
        print("Оценка добавлена.")
    elif sub in ("", "list"):
        if not grades:
            print("Оценок нет. Добавь: !grade add математика 5")
            return
        by: dict[str, list] = {}
        for g in grades:
            by.setdefault(g["subject"], []).append(g)
        for subj, items in sorted(by.items()):
            avg = sum(i["grade"] * i["weight"] for i in items) / sum(i["weight"] for i in items)
            print(f" • {subj}: {fmt(round(avg, 2))}  ({len(items)} шт.)")
        total = sum(g["grade"] * g["weight"] for g in grades) / sum(g["weight"] for g in grades)
        print(color(f"Общий средний балл: {fmt(round(total, 2))}", "bold"))
        for i, g in enumerate(grades[-10:], len(grades) - min(10, len(grades)) + 1):
            print(f"   #{i} {g['subject']}: {fmt(g['grade'])} (вес {fmt(g['weight'])})")
    elif sub == "del":
        i = parse_index(rest, len(grades))
        if i is not None:
            grades.pop(i)
            save_data(data)
            print("Оценка удалена.")
    else:
        print("Подкоманды: add предмет оценка [вес], list, del N")


# ---------- текст ----------
STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам сказал ведь там потом
себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда
кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно
при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо
свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между the and that for are with this from have
was were not but they you your all can has had its one our out use""".split())


def text_or_file(arg: str) -> str | None:
    a = arg.strip().strip('"').strip("'")
    try:
        p = Path(a).expanduser() if 0 < len(a) < 400 else None
        if p is not None and p.is_file():
            if not is_allowed(p):
                print("Доступ закрыт: только текущая и домашняя папки.")
                return None
            with p.open("rb") as fh:
                return fh.read(MAX_FILE_READ).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        pass
    return arg if arg.strip() else None


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[а-яёa-z0-9]{4,}", text.lower()) if w not in STOP]


@tool("!count", "Текст", "статистика текста или файла: !count текст · !count \"файл.txt\"")
def cmd_count(arg: str, data: dict) -> None:
    text = text_or_file(arg)
    if not text:
        print('Пример: !count Мой текст...  или  !count "essay.txt"')
        return
    words = re.findall(r"[\w'-]+", text)
    sentences = [s for s in re.split(r"[.!?…]+", text) if s.strip()]
    no_space = len(re.sub(r"\s", "", text))
    print(f"Символов: {len(text)} (без пробелов: {no_space}) | Слов: {len(words)} | "
          f"Предложений: {len(sentences)} | Строк: {len(text.splitlines()) or 1}")
    if words:
        print(f"Уникальных слов: {len({w.lower() for w in words})} | средняя длина слова: {sum(map(len, words)) / len(words):.1f} | "
              f"время чтения: ~{max(1, round(len(words) / 180))} мин.")
        top = Counter(_words(text)).most_common(5)
        if top:
            print("Частые слова: " + ", ".join(f"{w}({n})" for w, n in top))


@tool("!summary", "Текст", "краткий пересказ (выбор важных предложений): !summary текст")
def cmd_summary(arg: str, data: dict) -> None:
    text = text_or_file(arg)
    if not text:
        print("Пример: !summary длинный текст...  или  !summary \"файл.txt\"")
        return
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if len(s.strip()) > 20]
    if len(sentences) <= 3:
        print("Текст короткий — пересказывать нечего:\n" + text.strip()[:1500])
        return
    freq = Counter(_words(text))
    scored = []
    for i, s in enumerate(sentences):
        ws = _words(s)
        scored.append((sum(freq[w] for w in ws) / (len(ws) + 1) ** 0.6, i))
    keep = sorted(i for _, i in sorted(scored, reverse=True)[:min(4, max(2, len(sentences) // 5))])
    print("📝 Главное:\n" + "\n".join("• " + sentences[i][:400] for i in keep))


@tool("!keywords", "Текст", "ключевые слова: !keywords текст")
def cmd_keywords(arg: str, data: dict) -> None:
    text = text_or_file(arg)
    top = Counter(_words(text)).most_common(10) if text else []
    print("Ключевые слова: " + ", ".join(f"{w}({n})" for w, n in top) if top else "Пример: !keywords текст...")


# ---------- утилиты ----------
@tool("!pass", "Утилиты", "генератор пароля: !pass [длина 8-128] (нигде не сохраняется)")
def cmd_pass(arg: str, data: dict) -> None:
    try:
        n = int(arg) if arg.strip() else 16
    except ValueError:
        n = 16
    n = min(max(n, 8), 128)
    pools = ["abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123456789", "!@#$%^&*-_+="]
    alphabet = "".join(pools)
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if all(any(ch in pw for ch in pool) for pool in pools):
            break
    print(f"🔐 {pw}\n(длина {n}; не сохраняется в истории — скопируй сразу)")


@tool("!hash", "Утилиты", "контрольные суммы текста: !hash текст")
def cmd_hash(arg: str, data: dict) -> None:
    if not arg:
        print("Пример: !hash привет")
        return
    raw = arg.encode("utf-8")
    print(f"SHA-256: {hashlib.sha256(raw).hexdigest()}\nMD5 (только для сверки, не для безопасности): {hashlib.md5(raw).hexdigest()}")


@tool("!b64", "Утилиты", "Base64: !b64 enc текст · !b64 dec SGVsbG8=")
def cmd_b64(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    try:
        if sub.lower() == "enc" and rest:
            print(base64.b64encode(rest.encode("utf-8")).decode())
        elif sub.lower() == "dec" and rest:
            print(base64.b64decode(rest.strip(), validate=True).decode("utf-8", errors="replace"))
        else:
            print("Формат: !b64 enc текст | !b64 dec строка")
    except ValueError:
        print("Это не корректная Base64-строка.")


@tool("!rand", "Утилиты", "случайность: !rand 1 100 · !rand пицца суши плов")
def cmd_rand(arg: str, data: dict) -> None:
    parts = arg.split()
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        nums = None
    if not parts:
        print(random.randint(1, 100))
    elif nums and len(nums) <= 2:
        lo, hi = (1, nums[0]) if len(nums) == 1 else (min(nums), max(nums))
        print(random.randint(lo, hi))
    else:
        print("Выпало: " + random.choice(parts))


TIPS = [
    "Повторяй через интервалы: 1 день, 3 дня, неделя — так запоминается надолго (!quiz делает это за тебя).",
    "Сначала попробуй вспомнить сам, потом смотри ответ — это работает лучше перечитывания.",
    "Работай блоками по 25 минут и делай перерыв: !pomo.",
    "Объясни тему вслух, как будто учишь друга. Где запнулся — там пробел.",
    "Сложное — в начало дня, когда голова свежая.",
    "Разбивай задачу на маленькие шаги и вноси их в !todo.",
    "Спи достаточно: память закрепляется ночью.",
    "Чередуй темы и предметы — это лучше, чем долбить одно часами.",
]


@tool("!tip", "Утилиты", "совет по учёбе")
def cmd_tip(arg: str, data: dict) -> None:
    print("💡 " + random.choice(TIPS))


@tool("!color", "Утилиты", "цвета: !color on / off")
def cmd_color(arg: str, data: dict) -> None:
    global USE_COLOR
    if arg.lower() in ("on", "вкл"):
        USE_COLOR = True
    elif arg.lower() in ("off", "выкл"):
        USE_COLOR = False
    else:
        print("Формат: !color on | !color off")
        return
    print("Цвета " + ("включены." if USE_COLOR else "выключены."))


@tool("!backup", "Данные", "резервная копия сохранения в omni_ai_exports")
def cmd_backup(arg: str, data: dict) -> None:
    save_data(data)
    try:
        EXPORT_DIR.mkdir(exist_ok=True)
        dst = EXPORT_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(DATA_PATH, dst)
        print(f"Копия создана: {dst.resolve()}")
    except OSError as exc:
        print(color(f"Не удалось: {exc}", "red"))


@tool("!import", "Данные", "импорт заметок и карточек из JSON: !import \"файл.json\"")
def cmd_import(arg: str, data: dict) -> None:
    p = Path(arg.strip().strip('"').strip("'")).expanduser()
    try:
        if not p.is_file():
            print("Файл не найден.")
            return
        if not is_allowed(p):
            print("Доступ закрыт: только текущая и домашняя папки.")
            return
        if p.stat().st_size > 2_000_000:
            print("Файл слишком большой (макс. 2 МБ).")
            return
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Не удалось прочитать JSON.")
        return
    if not isinstance(raw, dict):
        print("Ожидался JSON-объект с ключами notes / cards / todos.")
        return
    tmp = default_data()
    sanitize_extra(raw, tmp)
    added = {"notes": 0, "cards": 0, "todos": 0}
    if isinstance(raw.get("notes"), dict):
        for k, v in list(raw["notes"].items())[:MAX_NOTES]:
            k = str(k).lower()[:100]
            if k and k not in data["notes"] and len(data["notes"]) < MAX_NOTES:
                data["notes"][k] = str(v)[:MAX_NOTE_LEN]
                added["notes"] += 1
    have = {c["q"].lower() for c in data["cards"]}
    for c in tmp["cards"]:
        if c["q"].lower() not in have and len(data["cards"]) < 2000:
            data["cards"].append(c)
            added["cards"] += 1
    for t in tmp["todos"]:
        if len(data["todos"]) < 1000:
            data["todos"].append(t)
            added["todos"] += 1
    save_data(data)
    print(f"Импортировано: заметок {added['notes']}, карточек {added['cards']}, задач {added['todos']}.")


@tool("!tools", "Утилиты", "список всех инструментов")
def cmd_tools(arg: str, data: dict) -> None:
    groups: dict[str, list] = {}
    seen = set()
    for _, (fn, group, desc, names) in EXTRA.items():
        if fn not in seen:
            seen.add(fn)
            groups.setdefault(group, []).append((names.split()[0], desc))
    for group in ("Учёба", "Планирование", "Математика", "Текст", "ИИ", "Утилиты", "Данные"):
        if group in groups:
            print(color(group.upper(), "bold"))
            for name, desc in groups[group]:
                print(f"  {name:<9} {desc}")


# ====================================================================
#                          v6: НОВОЕ
# ====================================================================

# ---------- экзамены ----------
def sanitize_exams(raw: dict, data: dict) -> None:
    v = raw.get("exams")
    data["exams"] = [
        {"name": str(e["name"])[:80], "date": e["date"]}
        for e in (v[:200] if isinstance(v, list) else [])
        if isinstance(e, dict) and e.get("name") and parse_date(e.get("date"))
    ]


def exam_lines(data: dict) -> list[str]:
    out = []
    upcoming = sorted((parse_date(e["date"]), e["name"]) for e in data.get("exams", []) if parse_date(e["date"]))
    for d, name in upcoming:
        n = (d - date.today()).days
        if 0 <= n <= 14 and len(out) < 3:
            out.append(f"🎓 {name}: " + ("сегодня!" if n == 0 else f"через {n} дн."))
    return out


@tool("!exam", "Планирование", "экзамены: add предмет ГГГГ-ММ-ДД · list · del N")
def cmd_exam(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    sub, rest, exams = sub.lower(), rest.strip(), data["exams"]
    if sub == "add":
        m = re.fullmatch(r"(.+?)\s+(\d{4}-\d{2}-\d{2})", rest)
        if not m or not parse_date(m.group(2)) or len(exams) >= 200:
            print("Формат: !exam add математика 2026-12-20")
            return
        exams.append({"name": m.group(1)[:80], "date": m.group(2)})
        save_data(data)
        print("Экзамен добавлен.")
    elif sub in ("", "list"):
        if not exams:
            print("Экзаменов нет. Добавь: !exam add математика 2026-12-20")
        for i, e in sorted(enumerate(exams, 1), key=lambda x: x[1]["date"]):
            n = (parse_date(e["date"]) - date.today()).days
            tail = f"через {n} дн." if n > 0 else ("сегодня!" if n == 0 else f"прошёл ({-n} дн. назад)")
            print(f" {i:>3}. {e['date']}  {e['name']} — {tail}")
    elif sub == "del":
        i = parse_index(rest, len(exams))
        if i is not None:
            exams.pop(i)
            save_data(data)
            print("Экзамен удалён.")
    else:
        print("Подкоманды: add, list, del N")


@tool("!heat", "Планирование", "календарь активности за 12 недель")
def cmd_heat(arg: str, data: dict) -> None:
    days = {parse_date(d) for d in data["days"]} - {None}
    today = date.today()
    start = today - timedelta(days=today.weekday() + 7 * 11)
    for wd, name in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
        row = ""
        for w in range(12):
            d = start + timedelta(days=wd + 7 * w)
            row += "  " if d > today else ("█ " if d in days else "· ")
        print(f" {name} {row}")
    print(f" Дней занятий: {len(days)} | Серия: {streak(data)}")


# ---------- ИИ-команды (нужен ANTHROPIC_API_KEY) ----------
def need_ai(data: dict) -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Команде нужен ИИ: задай переменную ANTHROPIC_API_KEY и перезапусти программу.")
        return False
    if not data.get("ai"):
        print("ИИ выключен. Включи: !ai on")
        return False
    return True


def llm_once(system: str, user: str, max_tokens: int = 1200) -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    body = json.dumps({
        "model": API_MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user[:MAX_INPUT]}],
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        return "\n".join(p for p in parts if p).strip() or None
    except urllib.error.HTTPError as exc:
        hint = {401: "неверный ключ", 429: "лимит запросов", 529: "сервис перегружен"}.get(exc.code, "")
        print(color(f"ИИ недоступен (HTTP {exc.code}{', ' + hint if hint else ''}).", "yellow"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        print(color("Нет связи с ИИ.", "yellow"))
    return None


def ai_command(data: dict, system: str, user: str, max_tokens: int = 1200) -> None:
    if not need_ai(data):
        return
    print(color("...", "dim"), end="\r")
    answer = llm_once(RULE + " " + system, user, max_tokens)
    if answer:
        touch_day(data)
        save_data(data)
        print(color("OMNI >", "cyan") + "\n" + answer)


@tool("!explain", "ИИ", "объяснить тему: !explain фотосинтез | для 5 класса")
def cmd_explain(arg: str, data: dict) -> None:
    if not arg:
        print("Пример: !explain производная | для 10 класса")
        return
    topic, _, level = arg.partition("|")
    ai_command(data, "Объясняй структурно: суть, пример, типичная ошибка, мини-проверка. Уровень: "
               + (level.strip()[:80] or "школьник"), f"Тема: {topic.strip()}")


@tool("!translate", "ИИ", "перевод RU↔EN с пояснениями: !translate текст")
def cmd_translate(arg: str, data: dict) -> None:
    if not arg:
        print("Пример: !translate I have been studying for two hours")
        return
    ai_command(data, "Если текст русский — переведи на английский, иначе на русский. Дай перевод, "
               "затем 1–3 кратких заметки о грамматике или лексике.", arg)


@tool("!proof", "ИИ", "проверка текста: орфография, пунктуация, стиль · !proof текст | \"файл\"")
def cmd_proof(arg: str, data: dict) -> None:
    text = text_or_file(arg) if arg else None
    if not text:
        print('Пример: !proof Мой текст...   или   !proof "essay.txt"')
        return
    ai_command(data, "Проверь орфографию, пунктуацию и стиль. Покажи исправленный текст, затем список правок "
               "с объяснением правила. Не выдумывай ошибок, если их нет.", text, 1500)


def parse_cards_json(text: str, limit: int) -> list[tuple[str, str]]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("q"), str) and isinstance(it.get("a"), str):
            q, a = it["q"].strip()[:500], it["a"].strip()[:1000]
            if q and a:
                out.append((q, a))
    return out[:limit]


@tool("!aicards", "ИИ", "ИИ создаёт карточки: !aicards тема [сколько 1-20]")
def cmd_aicards(arg: str, data: dict) -> None:
    m = re.fullmatch(r"(.+?)(?:\s+(\d{1,2}))?", arg.strip())
    if not arg.strip() or not m:
        print("Пример: !aicards столицы Европы 10")
        return
    if not need_ai(data):
        return
    n = min(max(int(m.group(2) or 8), 1), 20)
    answer = llm_once(
        'Ты создаёшь учебные карточки. Верни ТОЛЬКО JSON-массив вида [{"q":"вопрос","a":"краткий ответ"}] '
        "без пояснений и без markdown. Вопросы чёткие, ответы короткие и проверяемые.",
        f"Тема: {m.group(1).strip()}. Сделай {n} карточек.", 2000)
    if not answer:
        return
    pairs = parse_cards_json(answer, n)
    have = {c["q"].lower() for c in data["cards"]}
    added = 0
    for q, a in pairs:
        if q.lower() not in have and len(data["cards"]) < 2000:
            data["cards"].append(new_card(q, a))
            have.add(q.lower())
            added += 1
    save_data(data)
    print(f"Создано карточек: {added}. Повторять: !quiz" if added else "ИИ вернул неподходящий формат — попробуй ещё раз.")


# ---------- многочлены: производная и интеграл ----------
def parse_poly(s: str) -> dict[int, float] | None:
    s = s.replace(" ", "").replace("**", "^").replace("X", "x").replace(",", ".").replace("−", "-")
    if not s or len(s) > 200:
        return None
    poly: dict[int, float] = {}
    for term in re.findall(r"[+-]?[^+-]+", s):
        m = re.fullmatch(r"([+-]?)(\d+\.?\d*|\.\d+)?(\*?x(?:\^(\d+))?)?", term)
        if not m or (m.group(2) is None and m.group(3) is None):
            return None
        try:
            coef = float(m.group(2)) if m.group(2) else 1.0
        except ValueError:
            return None
        deg = (int(m.group(4)) if m.group(4) else 1) if m.group(3) else 0
        if deg > 50:
            return None
        poly[deg] = poly.get(deg, 0.0) + (-coef if m.group(1) == "-" else coef)
    return poly


def fmt_poly(p: dict[int, float]) -> str:
    out = ""
    for d in sorted(p, reverse=True):
        c = p[d]
        if abs(c) < 1e-12:
            continue
        a = abs(c)
        coef = "" if (abs(a - 1) < 1e-12 and d > 0) else fmt(round(a, 10))
        if abs(a - round(a)) > 1e-12:  # красивые дроби: (1/3)x^3 вместо 0.3333333333x^3
            fr = Fraction(a).limit_denominator(1000)
            if abs(float(fr) - a) < 1e-9:
                coef = f"({fr.numerator}/{fr.denominator})"
        term = coef + ("" if d == 0 else "x" if d == 1 else f"x^{d}")
        out = ("-" if c < 0 else "") + term if not out else out + (" - " if c < 0 else " + ") + term
    return out or "0"


def poly_eval(p: dict[int, float], x: float) -> float:
    return sum(c * x ** d for d, c in p.items())


@tool("!deriv", "Математика", "производная многочлена: !deriv 3x^2+2x-5 [at 2]")
def cmd_deriv(arg: str, data: dict) -> None:
    m = re.search(r"\s+(?:at|в)\s+(-?\d+\.?\d*)\s*$", arg)
    at = float(m.group(1)) if m else None
    p = parse_poly(arg[:m.start()] if m else arg)
    if p is None:
        print("Пример: !deriv 3x^2+2x-5   или   !deriv x^3 at 2")
        return
    dp = {d - 1: c * d for d, c in p.items() if d > 0}
    print(f"f(x)  = {fmt_poly(p)}\nf'(x) = {fmt_poly(dp)}")
    if at is not None:
        print(f"f({fmt(at)}) = {fmt(round(poly_eval(p, at), 10))} | f'({fmt(at)}) = {fmt(round(poly_eval(dp, at), 10))}")


@tool("!integ", "Математика", "интеграл многочлена: !integ 3x^2+2x [from 0 to 2]")
def cmd_integ(arg: str, data: dict) -> None:
    m = re.search(r"\s+(?:from|от)\s+(-?\d+\.?\d*)\s+(?:to|до)\s+(-?\d+\.?\d*)\s*$", arg)
    p = parse_poly(arg[:m.start()] if m else arg)
    if p is None:
        print("Пример: !integ 3x^2+2x   или   !integ x^2 from 0 to 3")
        return
    big = {d + 1: c / (d + 1) for d, c in p.items()}
    print(f"∫ ({fmt_poly(p)}) dx = {fmt_poly(big)} + C")
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        print(f"∫[{fmt(a)}; {fmt(b)}] = {fmt(round(poly_eval(big, b) - poly_eval(big, a), 10))}")


# ---------- проценты ----------
def _f(s: str) -> float:
    return float(s.replace(",", "."))


@tool("!pct", "Математика", "проценты: !pct 20% of 150 · !pct 30 of 120 · !pct 100 -> 120")
def cmd_pct(arg: str, data: dict) -> None:
    t = arg.lower().strip()
    num = r"(-?\d+(?:[.,]\d+)?)"
    try:
        if m := re.fullmatch(num + r"\s*%\s*(?:of|от)\s*" + num, t):
            x, y = _f(m.group(1)), _f(m.group(2))
            print(f"{fmt(x)}% от {fmt(y)} = {fmt(round(x * y / 100, 10))}")
        elif m := re.fullmatch(num + r"\s*(?:of|из)\s*" + num, t):
            x, y = _f(m.group(1)), _f(m.group(2))
            print("Делить на ноль нельзя." if y == 0 else f"{fmt(x)} от {fmt(y)} = {fmt(round(x / y * 100, 6))}%")
        elif m := re.fullmatch(num + r"\s*(?:->|to|до|в)\s*" + num, t):
            x, y = _f(m.group(1)), _f(m.group(2))
            if x == 0:
                print("Начальное значение не может быть 0.")
            else:
                ch = (y - x) / x * 100
                print(f"Изменение: {'+' if ch >= 0 else ''}{fmt(round(ch, 6))}%")
        else:
            print("Примеры: !pct 20% of 150 | !pct 30 of 120 | !pct 100 -> 120")
    except ValueError:
        print("Не понял числа.")


# ---------- матрицы (точные дроби) ----------
def parse_matrix(text: str) -> list[list[Fraction]] | None:
    rows = [r.split() for r in text.replace(",", ".").split(";") if r.strip()]
    if not rows or len(rows) > 6 or len(rows[0]) > 6 or any(len(r) != len(rows[0]) for r in rows):
        return None
    if any(len(x) > 12 for r in rows for x in r):
        return None
    try:
        return [[Fraction(x) for x in r] for r in rows]
    except (ValueError, ZeroDivisionError):
        return None


def mat_det(m: list[list[Fraction]]) -> Fraction:
    n, a, det = len(m), [r[:] for r in m], Fraction(1)
    for i in range(n):
        piv = next((r for r in range(i, n) if a[r][i] != 0), None)
        if piv is None:
            return Fraction(0)
        if piv != i:
            a[i], a[piv] = a[piv], a[i]
            det = -det
        det *= a[i][i]
        for r in range(i + 1, n):
            f = a[r][i] / a[i][i]
            for c in range(i, n):
                a[r][c] -= f * a[i][c]
    return det


def mat_inv(m: list[list[Fraction]]) -> list[list[Fraction]] | None:
    n = len(m)
    a = [m[i][:] + [Fraction(int(i == j)) for j in range(n)] for i in range(n)]
    for i in range(n):
        piv = next((r for r in range(i, n) if a[r][i] != 0), None)
        if piv is None:
            return None
        a[i], a[piv] = a[piv], a[i]
        p = a[i][i]
        a[i] = [x / p for x in a[i]]
        for r in range(n):
            if r != i and a[r][i] != 0:
                f = a[r][i]
                a[r] = [x - f * y for x, y in zip(a[r], a[i])]
    return [row[n:] for row in a]


def fmt_frac(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def print_matrix(m: list[list[Fraction]]) -> None:
    cells = [[fmt_frac(x) for x in r] for r in m]
    w = max(len(c) for r in cells for c in r)
    for r in cells:
        print("  | " + "  ".join(c.rjust(w) for c in r) + " |")


@tool("!matrix", "Математика", "матрицы: !matrix det 1 2; 3 4 · inv · t  (строки через ;)")
def cmd_matrix(arg: str, data: dict) -> None:
    sub, _, rest = arg.partition(" ")
    sub = sub.lower()
    m = parse_matrix(rest) if rest else None
    if sub not in ("det", "inv", "t") or m is None:
        print("Пример: !matrix det 1 2; 3 4   (до 6×6, строки разделяются точкой с запятой)")
        return
    square = len(m) == len(m[0])
    if sub == "t":
        print_matrix([list(r) for r in zip(*m)])
    elif not square:
        print("Нужна квадратная матрица.")
    elif sub == "det":
        print(f"det = {fmt_frac(mat_det(m))}")
    else:
        inv = mat_inv(m)
        if inv is None:
            print("Матрица вырожденная (det = 0): обратной нет.")
        else:
            print("Обратная матрица:")
            print_matrix(inv)


# ---------- самопроверка ----------
def run_selftest() -> int:
    c = new_card("q", "a")
    sm2(c, 5)
    first = c["interval"]
    sm2(c, 5)
    cases = [
        ("калькулятор 2^8", calculate("2^8") == 256),
        ("калькулятор: защита 9^9^9", str(calculate("9^9^9")).startswith("Ошибка")),
        ("калькулятор: деление на 0", str(calculate("1/0")).startswith("Ошибка")),
        ("калькулятор: sqrt(81)+2pi", abs(calculate("sqrt(81)+2pi") - (9 + 2 * math.pi)) < 1e-6),
        ("уравнение 2x+3=7", "x = 2" in (solve_linear("2x+3=7") or "")),
        ("уравнение 3(x-2)=x+4", "x = 5" in (solve_linear("3(x-2)=x+4") or "")),
        ("многочлен", parse_poly("3x^2+2x-5") == {2: 3.0, 1: 2.0, 0: -5.0}),
        ("вывод многочлена", fmt_poly({2: 3.0, 1: -1.0, 0: 5.0}) == "3x^2 - x + 5"),
        ("определитель", mat_det(parse_matrix("1 2; 3 4")) == -2),
        ("обратная матрица", mat_inv(parse_matrix("2 0; 0 4")) == [[Fraction(1, 2), 0], [0, Fraction(1, 4)]]),
        ("длительность 1h30m", parse_duration("1h30m") == 5400),
        ("SM-2 интервалы 1 → 6", first == 1 and c["interval"] == 6),
        ("карточки из текста", cards_from_text("ДНК — носитель; клетка: единица") == [("ДНК", "носитель"), ("клетка", "единица")]),
        ("JSON карточек", parse_cards_json('x [{"q":"a","a":"b"}] y', 5) == [("a", "b")]),
        ("защита путей", not is_allowed(Path(Path.home().anchor)) or Path.cwd() == Path(Path.home().anchor)),
        ("даты", parse_date("2026-02-30") is None and parse_date("2026-02-28") is not None),
        ("длительность 45m", parse_duration("45m") == 2700),
    ]
    failed = [name for name, ok in cases if not ok]
    for name, ok in cases:
        print(f" {'✔' if ok else '✘'} {name}")
    print(f"Итого: {len(cases) - len(failed)}/{len(cases)}" + ("" if not failed else "  — ЕСТЬ ОШИБКИ"))
    return 1 if failed else 0


@tool("!selftest", "Утилиты", "проверить, что внутренние функции работают")
def cmd_selftest(arg: str, data: dict) -> None:
    run_selftest()


# ---------- запуск с параметрами и автодополнение ----------
def apply_cli() -> None:
    import argparse
    global DATA_PATH, USE_COLOR
    ap = argparse.ArgumentParser(prog="omni_study_ai", description="OMNI STUDY AI — помощник для учёбы")
    ap.add_argument("--data", help="путь к файлу сохранения (по умолчанию omni_study_ai_data.json)")
    ap.add_argument("--no-color", action="store_true", help="без цветов")
    ap.add_argument("--calc", metavar="ВЫРАЖЕНИЕ", help="вычислить и выйти")
    ap.add_argument("--selftest", action="store_true", help="самопроверка и выход")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    a = ap.parse_args()
    if a.no_color:
        USE_COLOR = False
    if a.data:
        DATA_PATH = Path(a.data).expanduser()
    if a.calc:
        print(calculate(a.calc))
        raise SystemExit(0)
    if a.selftest:
        raise SystemExit(run_selftest())


def setup_completion() -> None:
    try:
        import readline as rl
    except ImportError:
        return
    names = sorted(set(ALIASES) | set(EXTRA))

    def completer(text: str, state: int):
        buf = rl.get_line_buffer()
        if not buf.startswith("!") or " " in buf:
            return None
        opts = [n for n in names if n.startswith(text)]
        return opts[state] if state < len(opts) else None

    rl.set_completer(completer)
    rl.set_completer_delims(" \t\n")
    rl.parse_and_bind("bind ^I rl_complete" if "libedit" in (rl.__doc__ or "") else "tab: complete")


def main() -> None:
    apply_cli()
    data = load_data()
    mode = data["mode"]
    print_banner()
    if ai_available(data):
        print(color("Онлайн-ИИ подключён. Сообщения отправляются в Anthropic (!ai off — отключить).", "green"))
    else:
        print("Работаю локально. Для умного ИИ задай переменную ANTHROPIC_API_KEY.")
    print_menu(mode)
    setup_completion()
    hint = brief(data)
    if hint:
        print(hint + "\n")

    try:
        while True:
            try:
                user = input(color(f"[{MODES[mode][0]}] Ты > ", "green")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nВыход.")
                break
            if not user:
                continue
            if len(user) > MAX_INPUT:
                print(f"Слишком длинно (максимум {MAX_INPUT} символов).")
                continue
            if user == "0":
                print("Сохранено. Пока!")
                break
            if user.startswith("!"):
                try:
                    _, mode = command_handler(user, data, mode)
                except SystemExit:
                    return
                except Exception as exc:
                    print(color(f"Команда завершилась с ошибкой: {type(exc).__name__}: {exc}", "red"))
                    print("Данные сохранены насколько возможно. Попробуй другую команду или !selftest.")
                    save_data(data)
                continue
            if user in MODES:
                mode = set_mode(data, user)
                continue

            quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', user)
            paths = [a or b for a, b in quoted]
            existing = [p for p in paths if len(p) < 400 and Path(p).expanduser().exists()]
            if existing:
                for p in existing:
                    try:
                        report, ok = inspect_path(p)
                        print(report)
                        if ok:
                            data["stats"]["files"] += 1
                    except (OSError, ValueError) as exc:
                        print(color(f"Не удалось проверить {p}: {exc}", "yellow"))
                reply, src = "Файл(ы) проверены. Подробности выше.", "local"
            else:
                print(color("...", "dim"), end="\r")
                reply, src = respond(mode, user, data)
                print("\n" + color("OMNI >", "cyan") + "\n" + reply + "\n")
            add_history(data, mode, user, reply, src)
    finally:
        save_data(data)


if __name__ == "__main__":
    main()
