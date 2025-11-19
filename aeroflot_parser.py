import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime
import logging
import config
import os
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AeroflotParser:
    def __init__(self):
        self.base_url = "https://www.aeroflot.ru/sb/app/ru-ru#/search"

    @staticmethod
    def convert_date(date_str):
        """Конвертирует дату из DD.MM.YYYY в YYYYMMDD"""
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            return dt.strftime("%Y%m%d")
        except ValueError:
            return None

    async def _close_popups(self, page):
        """Закрывает назойливые модальные окна и куки"""
        logger.info("Attempting to close popups...")
        selectors_to_click = [
            ".notification--choice-country .button", 
            "button:has-text('Да')",
            ".cookie-block .button", 
            "button:has-text('Понятно')",
            "button:has-text('Принять')",
            ".modal__close",
            ".notification__close"
        ]
        
        for selector in selectors_to_click:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    if await el.is_visible():
                        logger.info(f"Closing popup: {selector}")
                        await el.click(timeout=1000)
                        await page.wait_for_timeout(500)
            except Exception:
                pass 

    async def get_tickets(self, origin_code, destination_code, date_str, direct_only=False):
        formatted_date = self.convert_date(date_str)
        if not formatted_date:
            return {"error": "Неверный формат даты"}

        url = (
            f"{self.base_url}?"
            f"adults=1&award=Y&cabin=business&children=0&childrenaward=0&childrenfrgn=0&infants=0&"
            f"routes={origin_code}.{formatted_date}.{destination_code}"
        )
        
        logger.info(f"Opening URL: {url}")

        proxy_settings = None
        if config.PROXY_URL and (config.PROXY_URL.startswith("http") or config.PROXY_URL.startswith("socks")):
            proxy_settings = {"server": config.PROXY_URL}

        async with async_playwright() as p:
            if proxy_settings:
                browser = await p.chromium.launch(headless=config.HEADLESS, proxy=proxy_settings)
            else:
                browser = await p.chromium.launch(headless=config.HEADLESS)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                await self._close_popups(page)

                try:
                    search_button = await page.wait_for_selector("a.button--wide.button--lg:has-text('Найти'), button:has-text('Найти')", timeout=5000)
                    if search_button:
                        logger.info("Clicking 'Find' button")
                        await search_button.click(force=True)
                        await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"Search button not found or click failed: {e}")

                logger.info("Waiting 2 seconds for results to load...")
                await page.wait_for_timeout(2000)
                
                await self._close_popups(page)

                if direct_only:
                    logger.info("Filtering direct flights only...")
                    try:
                        # Логика: найти блок фильтров "Количество пересадок"
                        # Внутри него найти все чекбоксы.
                        # Оставить включенным только "Прямой рейс".
                        # Остальные (1, 2, 3...) выключить.
                        
                        # Находим лейбл "Прямой рейс"
                        direct_label = await page.query_selector("label:has-text('Прямой рейс')")
                        
                        if direct_label:
                            logger.info("Found 'Direct flight' label. Searching for filter container...")
                            
                            # Ищем родительский контейнер с role='region' или классом wrapper
                            # Используем evaluate_handle для навигации по DOM вверх
                            container = await direct_label.evaluate_handle("""(element) => {
                                return element.closest("div[role='region']") || element.closest(".wrapper") || element.closest(".accordion__content");
                            }""")
                            
                            if container:
                                container_element = container.as_element()
                                if container_element:
                                    # Ищем внутри контейнера label
                                    digit_labels = await container_element.query_selector_all("label")
                                    
                                    found_filters = False
                                    for label in digit_labels:
                                        text = await label.inner_text()
                                        text = text.strip()
                                        
                                        if text in ['1', '2', '3', '4']:
                                            logger.info(f"Clicking transfer filter: {text}")
                                            await label.click()
                                            found_filters = True
                                            await page.wait_for_timeout(500)
                                    
                                    if found_filters:
                                        logger.info("Filters clicked. Waiting for update...")
                                        await page.wait_for_timeout(2000)
                                    else:
                                        logger.warning("No digit labels found in the container")
                                else:
                                    logger.warning("Container handle could not be converted to element")
                            else:
                                logger.warning("Could not find filter container (ancestor of direct label)")
                                
                        else:
                             logger.warning("Direct flight label not found")
                             
                    except Exception as e:
                        logger.warning(f"Could not apply direct filter: {e}")

                screenshot_path = "results_screenshot.png"
                try:
                    frame_element = await page.query_selector(".frame.flight-searchs")
                    if frame_element:
                        await frame_element.screenshot(path=screenshot_path)
                        logger.info("Screenshot of .frame.flight-searchs saved")
                    else:
                        panel_info = await page.query_selector(".flight-search__panel-info")
                        if panel_info:
                             await panel_info.screenshot(path=screenshot_path)
                        else:
                             await page.screenshot(path=screenshot_path)
                             logger.info("Full page screenshot saved (frame not found)")
                except Exception as e:
                    logger.error(f"Error taking screenshot: {e}")
                    await page.screenshot(path=screenshot_path)

                # Парсинг данных
                flights_data = {
                    "direct": [],
                    "transfers": []
                }

                flight_elements = await page.query_selector_all(".flight-search")
                if not flight_elements:
                     # Проверка на отсутствие билетов по тексту на странице
                     content = await page.content()
                     if "Билетов класса Бизнес нет в наличии" in content or "Рейсы не найдены" in content:
                         await browser.close()
                         return {
                            "status": "no_tickets",
                            "screenshot": screenshot_path
                        }
                
                logger.info(f"Found {len(flight_elements)} flight elements")

                for index, flight in enumerate(flight_elements):
                    try:
                        text_content = await flight.inner_text()
                        if "Билетов класса Бизнес нет в наличии" in text_content:
                            continue

                        # Время вылета (HH:MM)
                        time_match = re.search(r'(\d{2}:\d{2})', text_content)
                        departure_time = time_match.group(1) if time_match else "??"

                        # Номера рейсов
                        flight_numbers = re.findall(r'SU\s*\d{4}', text_content)
                        # Сохраняем порядок и уникальность
                        seen = set()
                        flight_numbers_clean = [x for x in flight_numbers if not (x in seen or seen.add(x))]
                        flight_numbers_str = ", ".join(flight_numbers_clean)

                        # Тип рейса
                        is_transfer = "Пересадка" in text_content or len(flight_numbers_clean) > 1

                        # Попытка раскрыть рейс для получения мест и цен
                        # Нажимаем кнопку "ВЫБРАТЬ РЕЙС"
                        try:
                            # Ищем кнопку раскрытия
                            expand_btn = await flight.query_selector("button.button--outline")
                            if expand_btn:
                                await expand_btn.click(force=True)
                                await page.wait_for_timeout(1000) # Ждем анимацию открытия модалки
                        except Exception as e:
                            logger.warning(f"Flight {index}: Could not click expand button: {e}")

                        # ТЕПЕРЬ РАБОТАЕМ С МОДАЛЬНЫМ ОКНОМ
                        # Ищем открытое модальное окно .modal__frame
                        modal = await page.query_selector(".modal__frame")
                        
                        # Инициализация переменных перед блоком try-except
                        seats = "Не указано" 
                        miles = 0
                        taxes = 0

                        if modal:
                            try:
                                # Ждем контент
                                await page.wait_for_timeout(1000)
                                modal_text = await modal.inner_text()
                                # Нормализуем текст модалки сразу для удобства
                                modal_text_norm = modal_text.replace('\xa0', ' ')
                                
                                # Попробуем найти конкретные элементы ячеек с ценами
                                price_cells = await modal.query_selector_all(".tariff__table-cell.tariff__table-price")
                                
                                found_price = False
                                
                                if price_cells:
                                    # Пытаемся определить индекс колонки "Стандарт"
                                    header_cells = await modal.query_selector_all(".tariff__table-head .tariff__item-title, .tariff__table-head .text-bold")
                                    
                                    std_index = -1
                                    if header_cells:
                                        for i, h_cell in enumerate(header_cells):
                                            h_text = await h_cell.inner_text()
                                            if "Стандарт" in h_text or "Standard" in h_text:
                                                std_index = i
                                                break
                                    
                                    # Эвристика по количеству ячеек
                                    if std_index == -1:
                                        if len(price_cells) >= 3:
                                            std_index = 1
                                        elif len(price_cells) == 1:
                                            std_index = 0
                                    
                                    if std_index != -1 and std_index < len(price_cells):
                                        cell_text = await price_cells[std_index].inner_text()
                                        # Нормализация текста: заменяем все виды пробелов (в т.ч. узкие)
                                        cell_text_norm = re.sub(r'[\s\xa0\u202F]+', ' ', cell_text)
                                        
                                        # Парсим цену: "от 60 000 ¥ и 11 369 a"
                                        p_match = re.search(r'(\d[\d\s]*).*?и\s+(\d[\d\s]*)', cell_text_norm)
                                        if p_match:
                                            def clean_int(s):
                                                return int(re.sub(r'\D', '', s))
                                            
                                            try:
                                                miles = clean_int(p_match.group(1))
                                                taxes = clean_int(p_match.group(2))
                                                found_price = True
                                            except ValueError:
                                                logger.error(f"Failed to convert to int: {p_match.groups()}")
                                
                                # Фолбэк по всему тексту
                                if not found_price:
                                    # Ищем все пары (число... и число)
                                    all_prices = re.findall(r'от\s+(\d[\d\s]+).*?и\s+(\d[\d\s]+)', modal_text_norm)
                                    headers_text = re.findall(r'(Смарт|Лайт|Базовый|Стандарт|Гибкий|Максимум)', modal_text_norm)
                                    
                                    if "Стандарт" in headers_text:
                                        try:
                                            std_idx_txt = headers_text.index("Стандарт")
                                            if std_idx_txt < len(all_prices):
                                                 def clean_int(s):
                                                     return int(re.sub(r'\D', '', s))
                                                 miles = clean_int(all_prices[std_idx_txt][0])
                                                 taxes = clean_int(all_prices[std_idx_txt][1])
                                                 found_price = True
                                        except:
                                            pass
                                    
                                    if not found_price and all_prices:
                                        idx = 1 if len(all_prices) >= 3 else 0
                                        def clean_int(s):
                                            return int(re.sub(r'\D', '', s))
                                        miles = clean_int(all_prices[idx][0])
                                        taxes = clean_int(all_prices[idx][1])
                                
                                # Парсинг мест
                                seats_match_modal = re.search(r'(?:Доступно|Свободных)\s+мест.*?:?\s*(\d+)', modal_text_norm, re.IGNORECASE)
                                if seats_match_modal:
                                     seats = seats_match_modal.group(1)
                                
                                # Закрываем модальное окно
                                close_btn = await page.query_selector(".modal__close")
                                if close_btn:
                                    await close_btn.click()
                                    await page.wait_for_timeout(500)
                                else:
                                    await page.keyboard.press("Escape")
                                    await page.wait_for_timeout(500)
                                    
                            except Exception as e:
                                logger.error(f"Error parsing modal: {e}")
                                await page.keyboard.press("Escape")

                        # Места (если не нашли в модалке, пробуем из карточки)
                        if seats == "Не указано":
                            seats_match = re.search(r'(?:Доступно|Свободных)\s+мест.*?:?\s*(\d+)', text_content, re.IGNORECASE)
                            if seats_match:
                                 seats = seats_match.group(1)
                        
                        flight_info = {
                            "time": departure_time,
                            "flight_number": flight_numbers_str,
                            "seats": seats,
                            "miles": miles,
                            "taxes": taxes
                        }

                        if is_transfer:
                            flights_data["transfers"].append(flight_info)
                        else:
                            flights_data["direct"].append(flight_info)

                    except Exception as e:
                        logger.error(f"Error parsing flight {index}: {e}")

                await browser.close()
                
                # Если после парсинга списки пусты, значит билетов нет (или отфильтрованы)
                if not flights_data["direct"] and not flights_data["transfers"]:
                    return {
                        "status": "no_tickets",
                        "screenshot": screenshot_path
                    }

                return {
                    "status": "success",
                    "screenshot": screenshot_path,
                    "flights": flights_data
                }

            except Exception as e:
                logger.error(f"Global error in get_tickets: {e}")
                await browser.close()
                if os.path.exists("results_screenshot.png"):
                    return {"status": "timeout", "screenshot": "results_screenshot.png", "error": str(e)}
                return {"error": str(e)}
