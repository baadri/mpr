import asyncio
import logging
import re
from datetime import datetime
from playwright.async_api import async_playwright
import config

# Настройка логирования
logger = logging.getLogger(__name__)

class AeroflotUpgradeParser:
    def __init__(self):
        self.url = "https://www.aeroflot.ru/sb/pnr/app/ru-ru#/search"

    async def _close_popups(self, page):
        """Закрывает назойливые модальные окна (копия из основного парсера)"""
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
                if await page.locator(selector).is_visible():
                    await page.locator(selector).click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

    def _check_fare_eligibility(self, fare_code: str, is_kaliningrad: bool) -> dict:
        """
        Проверяет подходит ли тариф для апгрейда.
        
        Правила:
        1. Код тарифа СОДЕРЖИТ (не обязательно заканчивается) FM, FO, PM, XM.
        2. ИЛИ направление Калининград и код BPXOWRF или BPXRTRF.
        """
        fare_code_upper = fare_code.upper().strip()
        
        # Правило 1: Содержит FM, FO, PM, XM
        substrings = ("FM", "FO", "PM", "XM")
        if any(sub in fare_code_upper for sub in substrings):
             return {"eligible": True, "reason": "Тариф группы Максимум (FM/FO/PM/XM)"}

        # Правило 2: Калининград
        if is_kaliningrad:
            special_fares = ("BPXOWRF", "BPXRTRF")
            if fare_code_upper in special_fares:
                return {"eligible": True, "reason": "Спецтариф для Калининграда (BPX)"}

        return {"eligible": False, "reason": "Тариф не является Эконом-Максимум или Комфорт-Максимум"}
        
    def _extract_flight_details(self, segment_text: str) -> dict:
        """
        Извлекает детали рейса из текста сегмента.
        Ожидается текст вида:
        ...
        22:35SVOB NOZ06:55
        ...
        SU 1459
        ...
        Дата: "19 февраля 2026 г."
        """
        details = {}
        
        # 1. Поиск даты
        # Пример: 19 февраля 2026 г., четверг
        date_match = re.search(r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})', segment_text, re.IGNORECASE)
        if date_match:
            day, month_str, year = date_match.groups()
            month_map = {
                'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
                'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
                'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
            }
            month = month_map.get(month_str.lower())
            if month:
                # Форматируем в DD.MM.YYYY
                details['date'] = f"{int(day):02d}.{month}.{year}"

        # 2. Поиск номера рейса (SU XXXX)
        flight_match = re.search(r'(SU\s*\d{4})', segment_text)
        if flight_match:
            # SU 1459 -> SU1459
            details['flight_number'] = flight_match.group(1).replace(" ", "")
            
        # 3. Поиск кодов аэропортов (3 заглавные буквы)
        # Часто они идут рядом с временем: 22:35SVOB NOZ06:55
        # Или просто в тексте
        # Это сложнее, так как текст склеен.
        # Попробуем найти последовательности 3-4 заглавных букв
        
        # Поиск IATA кодов
        iata_codes = re.findall(r'[A-Z]{3}', segment_text)
        # Фильтруем коды дней недели и месяцев (JAN, FEB...) если они вдруг на английском, 
        # но у нас русский интерфейс.
        # В примере: 22:35SVOB NOZ06:55 -> SVOB (SVO B), NOZ
        # Попробуем найти коды городов в city_codes.py или просто взять первые два валидных кода
        
        # Лучший вариант - если мы найдем их по позиции.
        # В примере "22:35SVOB NOZ06:55"
        # Попробуем регулярку для времени и кода: (\d{2}:\d{2})([A-Z]{3,4})\s*([A-Z]{3,4})(\d{2}:\d{2})
        # SVO B - это терминал B. Нам нужен код SVO.
        
        route_match = re.search(r'(\d{2}:\d{2})\s*([A-Z]{3})(?:[A-Z0-9]*)?\s+([A-Z]{3})(?:[A-Z0-9]*)?\s*(\d{2}:\d{2})', segment_text)
        if route_match:
             details['origin_code'] = route_match.group(2)
             details['destination_code'] = route_match.group(3)
        
        return details

    async def check_upgrade(self, pnr_code: str, last_name: str) -> dict:
        logger.info(f"Checking upgrade for PNR: {pnr_code}, Last Name: {last_name}")
        
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
                # 1. Переход на страницу
                await page.goto(self.url, wait_until="networkidle", timeout=60000)
                await self._close_popups(page)

                # 2. Ввод данных
                # Используем более надежные селекторы чем динамические ID
                
                # Поле кода бронирования (обычно первое или по placeholder)
                pnr_input = page.locator("input[placeholder*='Код бронирования'], input[placeholder*='PNR'], input[name*='pnr']")
                if not await pnr_input.count():
                    # Фолбэк: пробуем найти по лейблам
                    pnr_input = page.locator("input").first # Рискованно, но на странице поиска это обычно первый инпут
                
                await pnr_input.fill(pnr_code)
                
                # Поле фамилии (обычно второе)
                last_name_input = page.locator("input[placeholder*='Фамилия'], input[name*='last_name']")
                if not await last_name_input.count():
                     last_name_input = page.locator("input").nth(1) # Второй инпут
                
                await last_name_input.fill(last_name)
                
                # 3. Нажатие кнопки Найти
                find_button = page.locator("button:has-text('Найти')")
                
                # Ждем пока кнопка станет активной (уберется класс disabled если есть)
                # Иногда нужно кликнуть вне полей, чтобы сработала валидация
                await page.click("body") 
                await page.wait_for_timeout(500)
                
                await find_button.click()

                # 4. Ожидание загрузки бронирования (Успех ИЛИ Ошибка)
                try:
                    # Ждем появления ОДНОГО ИЗ элементов: класса бронирования или сообщения об ошибке
                    # Используем Promise.race через Python логику ожидания любого из селекторов
                    # Но проще в Playwright использовать locator(...).first.wait_for() или просто проверить наличие
                    
                    # Ждем любой элемент, который скажет нам о результате
                    # .flight-booking__class_name (успех)
                    # .alert--error (ошибка)
                    # h1:has-text('не найдено') (ошибка)
                    
                    # Создаем общий локатор для ожидания
                    await page.wait_for_selector(
                        ".flight-booking__class_name, .alert--error, h1:has-text('не найдено'), .message-error", 
                        timeout=20000
                    )
                except Exception:
                    # Если ничего не появилось, возможно долгая загрузка, делаем скриншот
                    await page.screenshot(path="upgrade_debug.png")
                    return {"status": "error", "message": "Не удалось загрузить данные бронирования (таймаут)."}

                # Проверяем на ошибки на странице
                error_element = await page.query_selector(".alert--error, .message-error")
                not_found_h1 = await page.query_selector("h1:has-text('не найдено')")
                
                if error_element or not_found_h1:
                    error_text = "Бронирование не найдено"
                    if error_element:
                        error_text = await error_element.inner_text()
                    elif not_found_h1:
                        error_text = await not_found_h1.inner_text()
                        
                    return {"status": "error", "message": f"Ошибка на сайте: {error_text.strip()}\nПроверьте код бронирования и фамилию."}

                # 5. Парсинг ВСЕХ сегментов
                
                segments_data = []
                
                segment_elements = await page.locator(".flight-booking__group").all()
                
                if not segment_elements:
                    # Фолбэк на поиск просто классов тарифа, если структура другая
                    fare_elements = await page.locator(".flight-booking__class_name").all()
                    if not fare_elements:
                        return {"status": "error", "message": "Не удалось найти сегменты полета на странице."}
                        
                    for i, el in enumerate(fare_elements):
                        fare_code = await el.inner_text()
                        segments_data.append({
                            "route": f"Сегмент {i+1}",
                            "fare_code": fare_code.strip(),
                            "class_desc": "Не определен",
                            "is_kaliningrad": False,
                            "details": {} # Нет данных для парсинга деталей
                        })
                else:
                    for segment in segment_elements:
                        # Пытаемся извлечь маршрут
                        text_content = await segment.inner_text()
                        
                        # Маршрут
                        lines = text_content.split('\n')
                        route = lines[0] if lines else "Маршрут не определен"
                        
                        # Проверяем Калининград
                        is_kaliningrad = "KGD" in text_content or "Калининград" in text_content or "Kaliningrad" in text_content
                        
                        # Ищем ВСЕ коды тарифа внутри этого сегмента (группы)
                        fare_els = await segment.locator(".flight-booking__class_name").all()
                        
                        if not fare_els:
                            continue
                            
                        # Для парсинга деталей нам нужно попытаться найти блоки для каждого рейса
                        # Но текст text_content содержит ВСЕ рейсы слитно.
                        # Попытаемся разбить текст по блокам, если это возможно, или искать все вхождения
                        
                        # Упрощение: если рейсов > 1, мы просто ищем все SU XXXX в тексте и сопоставляем по порядку
                        all_flight_matches = re.findall(r'(SU\s*\d{4})', text_content)
                        all_date_matches = re.findall(r'(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})', text_content, re.IGNORECASE)
                        
                        # IATA коды: ищем пары кодов (SVOB NOZ)
                        # (\d{2}:\d{2})\s*([A-Z]{3})(?:[A-Z0-9]*)?\s+([A-Z]{3})
                        all_route_matches = re.findall(r'\d{2}:\d{2}\s*([A-Z]{3})(?:[A-Z0-9]*)?\s+([A-Z]{3})', text_content)
                        
                        for i, fare_el in enumerate(fare_els):
                            fare_code = await fare_el.inner_text()
                            fare_code = fare_code.strip()
                            
                            # Описание класса
                            class_desc_els = await segment.locator(".flight-booking__col--class").all()
                            if i < len(class_desc_els):
                                class_desc = await class_desc_els[i].inner_text()
                            else:
                                class_desc = fare_code
                                
                            route_suffix = f" (Рейс {i+1})" if len(fare_els) > 1 else ""
                            
                            # Собираем детали
                            details = {}
                            if i < len(all_flight_matches):
                                details['flight_number'] = all_flight_matches[i].replace(" ", "")
                            if i < len(all_date_matches): # Дата может быть одна на группу, если пересадка в тот же день, или разные
                                # Если дат меньше чем рейсов, возможно дата общая (в начале группы)
                                # Но в примере "20 февраля... 06:00..." дата в заголовке группы.
                                # Возьмем дату из заголовка группы если не нашли уникальных дат
                                d_str = all_date_matches[i] if i < len(all_date_matches) else (all_date_matches[0] if all_date_matches else None)
                                if d_str:
                                     # Конвертируем дату
                                    day_match = re.search(r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})', d_str, re.IGNORECASE)
                                    if day_match:
                                        day, month_str, year = day_match.groups()
                                        month_map = {'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08', 'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'}
                                        details['date'] = f"{int(day):02d}.{month_map.get(month_str.lower())}.{year}"
                                        
                            if i < len(all_route_matches):
                                details['origin_code'] = all_route_matches[i][0]
                                details['destination_code'] = all_route_matches[i][1]

                            segments_data.append({
                                "route": route + route_suffix,
                                "fare_code": fare_code,
                                "class_desc": class_desc,
                                "is_kaliningrad": is_kaliningrad,
                                "details": details
                            })

                if not segments_data:
                     return {"status": "error", "message": "Не удалось извлечь данные о сегментах."}

                # 6. Проверка условий для каждого сегмента
                results = []
                all_eligible = True
                
                for seg in segments_data:
                    check = self._check_fare_eligibility(seg["fare_code"], seg["is_kaliningrad"])
                    seg["eligible"] = check["eligible"]
                    seg["reason"] = check["reason"]
                    results.append(seg)
                    if not check["eligible"]:
                        all_eligible = False

                return {
                    "status": "success",
                    "segments": results,
                    "all_eligible": all_eligible
                }

            except Exception as e:
                logger.error(f"Error in check_upgrade: {e}")
                return {"status": "error", "message": str(e)}
                
            finally:
                await browser.close()
