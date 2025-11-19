import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery

import config
import city_codes
from aeroflot_parser import AeroflotParser
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

# Клавиатура с кнопкой Поиск и Новый поиск
search_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Поиск")], [KeyboardButton(text="🔄 Новый поиск")]],
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

@dp.message(SearchStates.waiting_origin)
async def process_origin(message: types.Message, state: FSMContext):
    if message.text == "🔄 Новый поиск":
        return await start_search(message, state)
        
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
    
    # Отправляем также клавиатуру с кнопкой "Новый поиск" (чтобы она была доступна, но не перекрывала календарь)
    # Однако Inline и Reply клавиатуры не могут быть в одном сообщении.
    # Поэтому отправляем отдельным сообщением инструкцию с Reply клавиатурой, если нужно, или полагаемся на то, что Reply клавиатура осталась с прошлого шага.
    # В данном случае лучше отправить текстовое сообщение с Reply клавиатурой, а календарь прикрепить к предыдущему или новому сообщению.
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

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
