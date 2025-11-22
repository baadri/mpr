import asyncio
import logging
import sys
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery

import config
import city_codes
from aeroflot_parser import AeroflotParser
from aeroflot_upgrade import AeroflotUpgradeParser
from simple_calendar import SimpleCalendar, CalendarCallback

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Семафор для ограничения количества одновременных браузеров
# Устанавливаем значение 2, чтобы не перегрузить сервер
browser_semaphore = asyncio.Semaphore(2)

# Определение состояний
class SearchStates(StatesGroup):
    waiting_origin = State()
    waiting_destination = State()
    waiting_date = State()
    waiting_flight_type = State()

class UpgradeStates(StatesGroup):
    waiting_booking_code = State()
    waiting_last_name = State()

# Клавиатура с кнопкой Поиск и Новый поиск
search_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Поиск")], 
        [KeyboardButton(text="💎 Проверить апгрейд")],
        [KeyboardButton(text="🔄 Новый поиск")]
    ],
    resize_keyboard=True
)

# Клавиатура для постоянного доступа к "Новый поиск"
# Она будет отправляться вместе с ответами на каждом этапе
def get_new_search_kb(add_buttons=None):
    buttons = []
    if add_buttons:
        buttons.extend(add_buttons)
    buttons.append([KeyboardButton(text="🔄 Новый поиск")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Клавиатура выбора типа рейсов
flight_type_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Только прямые")],
        [KeyboardButton(text="Любые")],
        [KeyboardButton(text="🔄 Новый поиск")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Добро пожаловать в проект Milestrade. Я проверю наличие билетов за бонусные мили на нужную дату. "
        "Сообщу стоимость и количество доступных авиабилетов к оформлению",
        reply_markup=search_kb
    )

@dp.message(F.text.in_({"Поиск", "🔄 Новый поиск"}))
async def start_search(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Введите направление откуда летим", reply_markup=get_new_search_kb())
    await state.set_state(SearchStates.waiting_origin)

# --- Логика поиска билетов ---

@dp.message(SearchStates.waiting_origin)
async def process_origin(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)
        
    city_name = message.text.strip()
    results = city_codes.find_city(city_name)
    
    if not results:
        await message.answer("Город не найден. Попробуйте ввести название точнее.", reply_markup=get_new_search_kb())
        return

    # Берем первый найденный город
    city, code = results[0]
    
    await state.update_data(origin_name=city, origin_code=code)
    await message.answer(f"Выбрано: {city} ({code}).\nВведите направление куда летим", reply_markup=get_new_search_kb())
    await state.set_state(SearchStates.waiting_destination)

@dp.message(SearchStates.waiting_destination)
async def process_destination(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)

    city_name = message.text.strip()
    results = city_codes.find_city(city_name)
    
    if not results:
        await message.answer("Город не найден. Попробуйте ввести название точнее.", reply_markup=get_new_search_kb())
        return

    city, code = results[0]
    
    await state.update_data(destination_name=city, destination_code=code)
    
    # Запуск календаря
    calendar = SimpleCalendar()
    await message.answer(
        f"Выбрано: {city} ({code}).\n"
        "Укажите дату перелёта:",
        reply_markup=await calendar.start_calendar()
    )
    
    await message.answer(
        "(Примечание: Бот осуществляет поиск только билетов в одну сторону. Для обратного билета повторите поиск.)",
        reply_markup=get_new_search_kb()
    )
    
    await state.set_state(SearchStates.waiting_date)

@dp.callback_query(CalendarCallback.filter(), SearchStates.waiting_date)
async def process_calendar_selection(callback_query: CallbackQuery, callback_data: CalendarCallback, state: FSMContext):
    calendar = SimpleCalendar()
    selected, date = await calendar.process_selection(callback_query, callback_data)
    
    if selected:
        date_text = date.strftime("%d.%m.%Y")
        await state.update_data(date=date_text)
        
        await callback_query.message.answer(
            f"Выбрана дата: {date_text}\n"
            "Искать только прямые рейсы или добавить варианты с пересадкой?",
            reply_markup=flight_type_kb
        )
        await state.set_state(SearchStates.waiting_flight_type)

@dp.message(SearchStates.waiting_date)
async def process_date_manual(message: types.Message, state: FSMContext):
    # Оставляем возможность ручного ввода на всякий случай
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)

    date_text = message.text.strip()
    
    try:
        if len(date_text.split('.')) != 3:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, выберите дату, используя календарь выше, или введите в формате ДД.ММ.ГГГГ", reply_markup=get_new_search_kb())
        return

    await state.update_data(date=date_text)
    await message.answer(
        "Искать только прямые рейсы или добавить варианты с пересадкой?",
        reply_markup=flight_type_kb
    )
    await state.set_state(SearchStates.waiting_flight_type)

@dp.message(SearchStates.waiting_flight_type)
async def process_flight_type(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)

    if message.text not in ["Только прямые", "Любые"]:
        await message.answer("Пожалуйста, выберите вариант используя кнопки.", reply_markup=flight_type_kb)
        return
    
    direct_only = (message.text == "Только прямые")
    
    data = await state.get_data()
    origin_code = data['origin_code']
    destination_code = data['destination_code']
    date_text = data['date']
    
    await message.answer("Начинаю поиск билетов... Это может занять около минуты.", reply_markup=ReplyKeyboardRemove())
    
    # Проверяем, есть ли свободные слоты в семафоре
    if browser_semaphore.locked():
        await message.answer("⚠️ Все потоки поиска заняты. Вы поставлены в очередь, поиск начнется автоматически, как только освободится место...")

    async with browser_semaphore:
        # Запуск парсера
        parser = AeroflotParser()
        result = await parser.get_tickets(origin_code, destination_code, date_text, direct_only=direct_only)
    
    # Отправка скриншота, если он есть
    screenshot_path = result.get("screenshot")
    if screenshot_path:
        try:
            photo = types.FSInputFile(screenshot_path)
            await message.answer_photo(photo)
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await message.answer("Не удалось отправить скриншот.")

    if result.get("status") == "success":
        flights = result.get("flights", {})
        direct = flights.get("direct", [])
        transfers = flights.get("transfers", [])
        
        msg_lines = []
        
        if direct:
            msg_lines.append("✈️ <b>Прямые рейсы:</b>")
            for f in direct:
                miles = f.get('miles', 0)
                taxes = f.get('taxes', 0)
                total_cost = int(miles * config.MILE_RATE + taxes)
                
                # Форматируем числа с пробелами
                miles_fmt = "{:,}".format(miles).replace(",", " ")
                taxes_fmt = "{:,}".format(taxes).replace(",", " ")
                total_fmt = "{:,}".format(total_cost).replace(",", " ")
                
                msg_lines.append(
                    f"🕒 {f['time']} | ✈️ {f['flight_number']}\n"
                    f"💺 Мест: {f['seats']}\n"
                    f"💰 {miles_fmt} миль + {taxes_fmt} руб = <b>{total_fmt} руб</b>\n"
                )
            msg_lines.append("")
            
        if transfers:
            msg_lines.append("🔄 <b>Рейсы с пересадкой:</b>")
            for f in transfers:
                miles = f.get('miles', 0)
                taxes = f.get('taxes', 0)
                total_cost = int(miles * config.MILE_RATE + taxes)
                
                # Форматируем числа с пробелами
                miles_fmt = "{:,}".format(miles).replace(",", " ")
                taxes_fmt = "{:,}".format(taxes).replace(",", " ")
                total_fmt = "{:,}".format(total_cost).replace(",", " ")

                msg_lines.append(
                    f"🕒 {f['time']} | ✈️ {f['flight_number']}\n"
                    f"💺 Мест: {f['seats']}\n"
                    f"💰 {miles_fmt} миль + {taxes_fmt} руб = <b>{total_fmt} руб</b>\n"
                )
        
        if not msg_lines:
            await message.answer("Рейсы найдены, но не удалось извлечь детали.", reply_markup=search_kb)
        else:
            # Добавляем подпись в конце сообщения
            msg_lines.append("\n📌 Цена указана за 1 пассажира в одну сторону")
            msg_lines.append("✍️ Оформить билет через менеджера: @milestrade")
            
            await message.answer("\n".join(msg_lines), parse_mode="HTML", reply_markup=search_kb)
            
    elif result.get("status") == "no_tickets":
        await message.answer("Билетов класса Бизнес за мили нет в наличии на эту дату.", reply_markup=search_kb)

    if "error" in result and result["status"] != "no_tickets":
        await message.answer(f"Ошибка: {result['error']}", reply_markup=search_kb)
    
    await state.clear()

# --- Логика проверки апгрейда ---

@dp.message(F.text == "💎 Проверить апгрейд")
async def start_upgrade_check(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Введите код бронирования.\n"
        "Формат: 6 символов (латинские буквы и цифры).",
        reply_markup=get_new_search_kb()
    )
    await state.set_state(UpgradeStates.waiting_booking_code)

@dp.message(UpgradeStates.waiting_booking_code)
async def process_booking_code(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)
        
    code = message.text.strip().upper()
    
    # Валидация: 6 символов, латиница + цифры
    if not re.match(r'^[A-Z0-9]{6}$', code):
        await message.answer(
            "❌ Некорректный формат кода бронирования.\n"
            "Код должен состоять ровно из 6 символов (латинские буквы и цифры).\n"
            "Попробуйте снова.",
            reply_markup=get_new_search_kb()
        )
        return

    await state.update_data(booking_code=code)
    await message.answer(
        "Введите фамилию пассажира (латиницей, как в билете).",
        reply_markup=get_new_search_kb()
    )
    await state.set_state(UpgradeStates.waiting_last_name)

@dp.message(UpgradeStates.waiting_last_name)
async def process_booking_lastname(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
    if message.text == "💎 Проверить апгрейд":
        return await start_upgrade_check(message, state)
        
    last_name = message.text.strip()
    
    # Проверка на латиницу
    # Разрешаем буквы A-Z, дефис и пробел
    if not re.match(r'^[A-Z\-\s]+$', last_name.upper()):
        await message.answer(
            "❌ Фамилия должна содержать только латинские буквы.\n"
            "Пожалуйста, введите фамилию заново.",
            reply_markup=get_new_search_kb()
        )
        return
    
    data = await state.get_data()
    booking_code = data['booking_code']
    
    await message.answer("Проверяю возможность апгрейда... Это может занять минуту.", reply_markup=ReplyKeyboardRemove())
    
    # Используем тот же семафор или новый?
    # Лучше использовать общий семафор, чтобы не открывать слишком много браузеров сразу
    if browser_semaphore.locked():
        await message.answer("⚠️ Очередь запросов. Поиск начнется автоматически, как только освободится место...")

    async with browser_semaphore:
        parser = AeroflotUpgradeParser()
        result = await parser.check_upgrade(booking_code, last_name)

    if result.get("status") == "success":
        segments = result.get("segments", [])
        all_eligible = result.get("all_eligible", False)
        
        msg = (
            f"🎫 <b>Бронирование:</b> {booking_code}\n"
            f"👤 <b>Фамилия:</b> {last_name}\n\n"
        )
        
        # Проходим по сегментам и проверяем наличие билетов для апгрейда
        # Для этого нужно запустить поиск, если тариф подходит
        
        processed_segments = []
        all_seats_found = True
        any_seats_found = False
        
        for idx, seg in enumerate(segments, 1):
            route = seg['route']
            fare = seg['fare_code']
            desc = seg['class_desc']
            eligible = seg['eligible']
            reason = seg['reason']
            details = seg.get('details', {})
            
            # Упрощение отображения маршрута если есть детали
            if details.get('origin_code') and details.get('destination_code') and details.get('date'):
                flight_num = details.get('flight_number', '')
                route_display = f"{details['origin_code']} ➡️ {details['destination_code']} ({details['date']})"
                if flight_num:
                    route_display += f", {flight_num}"
            else:
                # Очищаем текст маршрута от лишних переносов строк
                route_display = route.split('\n')[0]

            seg_msg = (
                f"<b>Сегмент {idx}:</b> {route_display}\n"
                f"📊 Тариф: {desc} ({fare})\n"
            )
            
            if eligible:
                # Проверяем билеты за мили
                found_upgrade = False
                checked_seats = False

                if details.get('origin_code') and details.get('destination_code') and details.get('date'):
                    await message.answer(f"🔎 Проверяю наличие мест для апгрейда на сегменте {idx}...")
                    
                    checked_seats = True
                    # Используем семафор для поиска
                    async with browser_semaphore:
                        parser = AeroflotParser()
                        # Ищем прямой рейс (так как проверяем конкретный сегмент)
                        ticket_res = await parser.get_tickets(
                            details['origin_code'], 
                            details['destination_code'], 
                            details['date'],
                            direct_only=True 
                        )
                    
                    upgrade_cost = 0
                    
                    if ticket_res.get("status") == "success":
                        # Ищем наш рейс в списке
                        flights_direct = ticket_res.get("flights", {}).get("direct", [])
                        target_flight = details.get('flight_number') # Например SU1459
                        
                        for f in flights_direct:
                            # Сравниваем номер рейса (очищенный от пробелов)
                            f_num = f['flight_number'].replace(" ", "").replace(",", "")
                            # В парсере flight_number может быть списком "SU 1459" или "SU 1459, SU ..."
                            # Проверяем вхождение
                            if target_flight and target_flight in f_num:
                                # Нашли!
                                found_upgrade = True
                                # Стоимость апгрейда = мили / 2
                                upgrade_cost = int(f['miles'] / 2)
                                break
                    
                    if found_upgrade:
                        cost_rub = int(upgrade_cost * config.MILE_RATE)
                        cost_fmt = "{:,}".format(cost_rub).replace(",", " ")
                        miles_fmt = "{:,}".format(upgrade_cost).replace(",", " ")
                        seg_msg += f"✅ Тариф подходит. \n🎟 <b>Места для апгрейда ЕСТЬ!</b>\n💰 Стоимость: {miles_fmt} миль = <b>{cost_fmt} руб</b>\n"
                        any_seats_found = True
                    else:
                        seg_msg += f"✅ Тариф подходит. \n❌ Мест за мили нет (или рейс не найден в выдаче)\n"
                        all_seats_found = False
                else:
                    seg_msg += f"✅ Тариф подходит. \n⚠️ Не удалось определить параметры рейса для проверки мест.\n"
                    all_seats_found = False
            else:
                seg_msg += f"❌ Тариф не подходит\n   └ <i>{reason}</i>\n"
                all_seats_found = False
            
            processed_segments.append(seg_msg)

        msg += "\n".join(processed_segments)
        msg += "\n\n"

        if all_eligible and all_seats_found:
            msg += "🎉 <b>Весь маршрут доступен для апгрейда!</b>"
        elif all_eligible and any_seats_found:
            msg += "⚠️ <b>Тарифы подходят, но места есть не на всех сегментах.</b>"
        elif all_eligible and not any_seats_found:
            msg += "❌ <b>Тарифы подходят, но нет свободных мильных мест.</b>"
        else:
            msg += "⚠️ <b>Не все сегменты подходят по тарифу.</b>"

        await message.answer(msg, parse_mode="HTML", reply_markup=search_kb)
        
    else:
        # Ошибка
        error_msg = result.get("message", "Неизвестная ошибка")
        # Убираем дублирование "Ошибка на сайте: ..." если оно уже есть в сообщении
        if error_msg.startswith("Ошибка на сайте:"):
             await message.answer(f"⚠️ {error_msg}", reply_markup=search_kb)
        else:
             await message.answer(f"⚠️ Ошибка при проверке: {error_msg}", reply_markup=search_kb)
    
    await state.clear()

async def main():
    print("Bot polling started") # Добавлен print для диагностики
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
