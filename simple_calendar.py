import calendar
from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

# CallbackData для кнопок календаря
class CalendarCallback(CallbackData, prefix="calendar"):
    action: str  # 'IGNORE', 'PREV-YEAR', 'NEXT-YEAR', 'PREV-MONTH', 'NEXT-MONTH', 'DAY'
    year: int
    month: int
    day: int

class SimpleCalendar:
    def __init__(self):
        pass

    async def start_calendar(self, year: int = datetime.now().year, month: int = datetime.now().month):
        """
        Создает клавиатуру с календарем на заданный год и месяц
        """
        markup = []
        
        # Первая строка - Год и Месяц
        markup.append([
            InlineKeyboardButton(
                text="<<",
                callback_data=CalendarCallback(action="PREV-YEAR", year=year, month=month, day=1).pack()
            ),
            InlineKeyboardButton(
                text=f"{year}",
                callback_data=CalendarCallback(action="IGNORE", year=year, month=month, day=1).pack()
            ),
            InlineKeyboardButton(
                text=">>",
                callback_data=CalendarCallback(action="NEXT-YEAR", year=year, month=month, day=1).pack()
            )
        ])

        markup.append([
            InlineKeyboardButton(
                text="<",
                callback_data=CalendarCallback(action="PREV-MONTH", year=year, month=month, day=1).pack()
            ),
            InlineKeyboardButton(
                text=f"{calendar.month_name[month]}",
                callback_data=CalendarCallback(action="IGNORE", year=year, month=month, day=1).pack()
            ),
            InlineKeyboardButton(
                text=">",
                callback_data=CalendarCallback(action="NEXT-MONTH", year=year, month=month, day=1).pack()
            )
        ])

        # Дни недели
        week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        markup.append([InlineKeyboardButton(text=day, callback_data="IGNORE") for day in week_days])

        # Дни месяца
        month_calendar = calendar.monthcalendar(year, month)
        for week in month_calendar:
            row = []
            for day in week:
                if day == 0:
                    row.append(InlineKeyboardButton(text=" ", callback_data="IGNORE"))
                else:
                    row.append(InlineKeyboardButton(
                        text=str(day),
                        callback_data=CalendarCallback(action="DAY", year=year, month=month, day=day).pack()
                    ))
            markup.append(row)

        return InlineKeyboardMarkup(inline_keyboard=markup)

    async def process_selection(self, query, data: CalendarCallback):
        """
        Обрабатывает нажатие на кнопку календаря.
        Возвращает (True, date) если выбрана дата, иначе (False, None)
        """
        return_data = (False, None)
        temp_date = datetime(int(data.year), int(data.month), 1)
        
        if data.action == "IGNORE":
            await query.answer(cache_time=60)
            
        elif data.action == "DAY":
            return_data = True, datetime(int(data.year), int(data.month), int(data.day))
            
        elif data.action == "PREV-YEAR":
            new_year = int(data.year) - 1
            await query.message.edit_reply_markup(reply_markup=await self.start_calendar(int(new_year), int(data.month)))
            
        elif data.action == "NEXT-YEAR":
            new_year = int(data.year) + 1
            await query.message.edit_reply_markup(reply_markup=await self.start_calendar(int(new_year), int(data.month)))
            
        elif data.action == "PREV-MONTH":
            prev_month = temp_date - timedelta(days=1)
            await query.message.edit_reply_markup(reply_markup=await self.start_calendar(int(prev_month.year), int(prev_month.month)))
            
        elif data.action == "NEXT-MONTH":
            next_month = temp_date + timedelta(days=31)
            await query.message.edit_reply_markup(reply_markup=await self.start_calendar(int(next_month.year), int(next_month.month)))
            
        return return_data

