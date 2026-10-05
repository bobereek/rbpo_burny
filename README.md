# WildBurny

WildBurny — учебный REST API для согласования заявок на покупку внутри
организации.

Сейчас доступны предметное ядро и минимальная запускаемая основа EK1:
FastAPI, `GET /health` и подключение к локальной SQLite. Предметные HTTP-маршруты
и аутентификация — следующие этапы реализации.

## Локальный запуск

После установки Python 3.12 выполните из корня репозитория:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn wildburny.main:create_app --factory --host 127.0.0.1 --port 8000
```

Проверка из другого терминала: `curl --fail http://127.0.0.1:8000/health`.
Ожидаемый ответ: `{"status":"ok"}`. Проверки проекта: `.venv/bin/python -m pytest -q`.
Путь к SQLite, команды Ruff и детали запуска описаны в
[паспорте проекта](PROJECT.md#10-локальный-запуск).

## Документы проекта

- [Паспорт проекта](PROJECT.md)
- [Требования безопасности](SECURITY_REQUIREMENTS.md)
- [Модель угроз](THREAT_MODEL.md)
- [Проектные решения безопасности](DESIGN_DECISIONS.md)
- [Вклад участников](CONTRIBUTIONS.md)
- [Использование ИИ](AI_USAGE.md)
