# Инструкция по запуску бота на сервере (Docker)

Эта инструкция поможет вам запустить бота на любом сервере с установленным Docker.

## Шаг 1. Подготовка файлов

Убедитесь, что у вас на компьютере есть следующие файлы проекта:
- `main.py`, `bot.py`, `config.py`, `city_codes.py`, `aeroflot_parser.py`, `simple_calendar.py`
- `requirements.txt`
- `Dockerfile`
- `entrypoint.sh`

## Шаг 2. Загрузка на сервер

Зайдите на сервер по SSH или используйте встроенную консоль хостинга.
Создайте папку для бота:

```bash
mkdir bot
cd bot
```

Загрузите файлы в эту папку. Это можно сделать через SFTP (программы типа FileZilla, WinSCP) или просто создать файлы через редактор nano и скопировать содержимое.

## Шаг 3. Сборка и запуск

Находясь в папке `bot`, выполните команду сборки (это займет пару минут):

```bash
docker build -t aeroflot-bot .
```

После успешной сборки запустите бота. 
**Важно:** Замените `ВАШ_ТОКЕН` и `ВАШ_ПРОКСИ` на реальные данные.

```bash
docker run -d \
  --restart always \
  --env BOT_TOKEN="ВАШ_ТОКЕН" \
  --env PROXY_URL="socks5://user:pass@ip:port" \
  --env HEADLESS="False" \
  --name milestrade_bot \
  aeroflot-bot
```

*Примечание: `--restart always` означает, что если сервер перезагрузится или бот упадет, он запустится сам.*

## Полезные команды

Посмотреть статус бота (работает или нет):
```bash
docker ps
```

Посмотреть логи (что пишет бот):
```bash
docker logs -f milestrade_bot
```
(Нажмите Ctrl+C, чтобы выйти из просмотра логов)

Остановить бота:
```bash
docker stop milestrade_bot
```

Перезапустить бота (например, если он завис):
```bash
docker restart milestrade_bot
```

Удалить бота (чтобы пересобрать заново):
```bash
docker rm -f milestrade_bot
```

