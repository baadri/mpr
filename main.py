import asyncio
import logging
import sys
import os
import time

# Принудительно сбрасываем буфер вывода
sys.stdout.reconfigure(line_buffering=True)

# Настройка базового логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

if __name__ == "__main__":
    print("=== MAIN SCRIPT STARTED ===", flush=True)
    print(f"Current working directory: {os.getcwd()}", flush=True)
    
    token = os.getenv("BOT_TOKEN")
    print(f"DEBUG: BOT_TOKEN present: {bool(token)}", flush=True)
    
    # Искусственная задержка для теста
    print("DEBUG: Waiting 1 second...", flush=True)
    time.sleep(1)

    try:
        print("Importing bot module...", flush=True)
        # Импортируем внутри try/except, чтобы поймать ошибки при инициализации модуля
        import bot
        print("Bot module imported successfully.", flush=True)
        
        print("Starting asyncio.run(main())...", flush=True)
        asyncio.run(bot.main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by signal!", flush=True)
    except Exception as e:
        print(f"CRITICAL ERROR IN MAIN: {e}", flush=True)
        logging.exception("Critical error:")
        sys.exit(1)
