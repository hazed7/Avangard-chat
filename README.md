[![CI](https://img.shields.io/github/actions/workflow/status/hazed7/Avangard-chat/ci.yml?branch=main&label=CI&style=flat-square&logo=githubactions)](https://github.com/hazed7/Avangard-chat/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-proprietary-red?style=flat-square&logo=opensourceinitiative&logoColor=white)](https://github.com/hazed7/Avangard-chat/blob/main/LICENSE)
[![Coverage](https://codecov.io/gh/hazed7/Avangard-chat/graph/badge.svg)](https://codecov.io/gh/hazed7/Avangard-chat)

## Стек

<p align="left">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" alt="MongoDB" />
  <img src="https://img.shields.io/badge/DragonflyDB-FF3D00?style=for-the-badge&logoColor=white" alt="DragonflyDB" />
  <img src="https://img.shields.io/badge/Typesense-D90368?style=for-the-badge&logoColor=white" alt="Typesense" />
  <img src="https://img.shields.io/badge/Rustfs-0096FF?style=for-the-badge&logoColor=white" alt="Rustfs" />
</p>

Бэкенд чат-приложения на FastAPI:
- JWT-аутентификация и refresh-сессии
- групповые чаты и личные сообщения
- realtime-обмен сообщениями через ws
- зашифрованное хранение сообщений
- полнотекстовый поиск (Typesense)
- счётчики непрочитанных
- api загрузки файлов / медиа-хранилище (Rustfs)

## Что реализовано

- Auth
  - регистрация, логин, refresh, logout
  - access token в JSON, refresh token в HttpOnly cookie
  - TTL по умолчанию: access 15 минут, refresh 30 дней
- Rooms
  - групповые комнаты и лс
  - управление участниками групп
  - список комнат
- Messages
  - отправка, редактирование, удаление, отметка прочитанного, прикрепление файлов
  - история и поиск
  - счётчики непрочитанных и read-state по комнате
- WebSocket
  - realtime-сообщения, presence, typing, delivery-state события
  - идемпотентность отправки сообщений

## Шифрование и хранение сообщений

- Текст сообщений хранится в MongoDB в зашифрованном виде.
- Алгоритм: `AES-256-GCM`.
- Для каждого сообщения используется отдельный случайный nonce.
- Контекст привязывает шифртекст к `room_id` и `sender_id`.
- Хранятся поля: ciphertext, nonce, key id, aad.
- Удалённые сообщения soft-delete (`is_deleted=true`) и в API отдаются как `[deleted]`.

## Фоновые воркеры

Запускаются автоматически при старте приложения:

- Cleanup worker
  - обрабатывает асинхронные cleanup задачи с retry/backoff и dead-letter
  - очищает документы typesense и кэш после удаления сообщений/комнат
- Unread reconciliation worker
  - периодически пересчитывает unread-счётчики и исправляет дрейф

## Запуск

```bash
docker compose up -d --build
```

API: `http://localhost:8000`.

Некоторые эндпоинты:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Liveness: `http://localhost:8000/health/live`
- Readiness: `http://localhost:8000/health/ready`

## Линтер

```bash
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev pytest tests/unit tests/api
```

## Git hooks

Выполняются автоматически при коммите.

Сетап:
```bash
uv sync --group dev
uv run --group dev pre-commit install
```

Прогнать вручную:
```bash
uv run --group dev pre-commit run --all-files
```

Проверка коммита выполняется через pre-commit хуком `check-commit-msg`

## Что пока не реализовано

- speech-to-text / text-to-speech
- AI-модерация, перевод, саммаризация
- фронт

## Лицензия

См. [LICENSE](LICENSE).
