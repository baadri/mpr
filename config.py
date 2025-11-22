import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Proxy settings (Socks5)
PROXY_URL = os.getenv("PROXY_URL")
if PROXY_URL and not PROXY_URL.strip():
    PROXY_URL = None

# Стоимость 1 мили в рублях
# Парсим безопасно, удаляя возможные комментарии (например, "1.0 # коммент")
raw_mile_rate = os.getenv("MILE_RATE", "1.0")
if "#" in raw_mile_rate:
    raw_mile_rate = raw_mile_rate.split("#")[0]
MILE_RATE = float(raw_mile_rate.strip())

# Headless mode for browser
HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"
