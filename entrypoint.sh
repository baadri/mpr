#!/bin/bash

# Запускаем виртуальный дисплей (Xvfb) на дисплее :99
# -ac: отключает контроль доступа (access control)
# -screen 0 1920x1080x24: создает экран с разрешением 1920x1080 и глубиной цвета 24 бита
Xvfb :99 -ac -screen 0 1920x1080x24 &

# Экспортируем переменную DISPLAY, чтобы приложения знали, куда выводить изображение
export DISPLAY=:99

# Ждем пару секунд, чтобы Xvfb успел запуститься
sleep 2

# Запускаем бота
echo "Starting bot with visible browser inside Xvfb..."
python main.py

