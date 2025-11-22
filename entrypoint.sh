#!/bin/bash

# Если HEADLESS=True, запускаем просто python (Playwright сам запустится в headless)
if [ "$HEADLESS" = "True" ]; then
    echo "Starting bot in HEADLESS mode..."
    python main.py
else
    # Если HEADLESS=False, используем xvfb-run для создания виртуального дисплея
    echo "Starting bot with HEADLESS=False using xvfb-run..."
    
    # --auto-servernum: автоматически выбрать свободный номер дисплея
    # --server-args: параметры экрана (разрешение)
    exec xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python main.py
fi
