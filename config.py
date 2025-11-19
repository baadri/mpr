import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Proxy settings (Socks5)
# Format: "socks5://user:pass@host:port" or "socks5://host:port"
PROXY_URL = os.getenv("PROXY_URL")
if PROXY_URL and not PROXY_URL.strip():
    PROXY_URL = None

# Стоимость 1 мили в рублях (по умолчанию 1.0)
MILE_RATE = float(os.getenv("MILE_RATE", "1.0"))

# Headless mode for browser (False - чтобы видеть окно браузера)
# Берем из переменных окружения, по умолчанию False (видимый режим)
# На сервере с Docker и Xvfb тоже ставим False, чтобы сайт думал, что мы обычный пользователь.
HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"

