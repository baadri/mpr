#!/bin/bash
set -e

echo "=== ENTRYPOINT STARTED ==="
echo "Date: $(date)"

# Очистка локов
rm -f /tmp/.X99-lock

if [ "$HEADLESS" = "True" ]; then
    echo "Starting bot in HEADLESS mode..."
    python main.py
else
    echo "Starting Xvfb manually..."
    # Запускаем Xvfb в фоне
    Xvfb :99 -screen 0 1920x1080x24 &
    XVFB_PID=$!
    
    echo "Xvfb started with PID $XVFB_PID. Waiting 2 seconds..."
    sleep 2
    
    export DISPLAY=:99
    
    echo "Starting python main.py..."
    # Запускаем python напрямую
    python main.py
    
    # Если python упадет, убиваем Xvfb
    kill $XVFB_PID
fi
