# Инструкция по запуску бота на сервере (Docker)

Эта инструкция поможет вам запустить бота на любом сервере с установленным Docker.

## Шаг 1. Подготовка файлов

Убедитесь, что у вас на компьютере есть следующие файлы проекта:
- `main.py`, `bot.py`, `config.py`, `city_codes.py`, `aeroflot_parser.py`, `aeroflot_upgrade.py`, `simple_calendar.py`
- `requirements.txt`
- `Dockerfile`
- `entrypoint.sh`

## Шаг 2. Загрузка на сервер

Зайдите на сервер по SSH или используйте встроенную консоль хостинга.
Создайте папку для бота:

```bash
mkdir -p bot
cd bot
```

Загрузите файлы в эту папку. Создайте файл с настройками `.env`:
```bash
nano .env
```
Вставьте содержимое:
```ini
BOT_TOKEN=ваш_токен
PROXY_URL=ваш_прокси (или пусто)
HEADLESS=False
MILE_RATE=1.0
```
*(Ctrl+O, Enter, Ctrl+X для сохранения)*

## Шаг 3. Полная пересборка и запуск (Чистый лист)

Выполните эти команды по очереди, чтобы удалить старые версии и запустить новую:

```bash
# 1. Останавливаем и удаляем старый контейнер (игнорируем ошибки если нет контейнера)
docker rm -f milestrade_bot

# 2. Собираем образ заново
docker build -t aeroflot-bot .

# 3. Запускаем бота
docker run -d \
  --restart unless-stopped \
  --env-file .env \
  --shm-size=2gb \
  --name milestrade_bot \
  aeroflot-bot
```

## Проверка работы

Посмотреть логи:
```bash
docker logs -f milestrade_bot
```
(Нажмите Ctrl+C, чтобы выйти из просмотра логов)

Остановить бота:
```bash
docker stop milestrade_bot
```

Перезапустить бота:
```bash
docker restart milestrade_bot
```
