import asyncio
import sqlite3
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

# ========== НАСТРОЙКИ ==========
TOKEN = "TOKEN"
ADMIN_ID = ADMIN_ID # твой ID
DB_NAME = "support.db"
# ===============================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

class TicketStates(StatesGroup):
    waiting_description = State()
    waiting_photo = State()
    admin_replying = State()

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            description TEXT NOT NULL,
            photo_file_id TEXT,
            status TEXT NOT NULL DEFAULT 'Новое',
            created_at TEXT NOT NULL,
            admin_answer TEXT,
            rating INTEGER
        )""")

def format_ticket_id(tid: int) -> str:
    return f"#{tid:04d}"

def parse_ticket_id(text: str):
    try:
        return int(text.replace("#", "").strip())
    except:
        return None

def get_client_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📩 Создать обращение")],
        [KeyboardButton(text="📋 Мои тикеты")]
    ], resize_keyboard=True)

def get_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

def get_skip_photo_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭ Пропустить фото")],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)

def get_admin_ticket_kb(ticket_id: int, status: str):
    row1 = []
    row2 = []
    if status == "Новое":
        row1.append(InlineKeyboardButton(text="🛠 Взять в работу", callback_data=f"take_{ticket_id}"))
    if status in ["Новое", "В работе"]:
        row1.append(InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{ticket_id}"))
        row2.append(InlineKeyboardButton(text="✅ Решено", callback_data=f"close_{ticket_id}"))
    kb = [row1] if not row2 else [row1, row2]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_rating_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'⭐️'*i}", callback_data=f"rate_{i}") for i in range(1, 6)]
    ])

INSTRUCTION_TEXT = (
    "👋 Привет! Я - Support Бот.\n\n"
    "📩 <b>Создать обращение</b> - опиши проблему + фото\n"
    "📋 <b>Мои тикеты</b> - узнать статус\n\n"
    "Просто жми кнопку ниже 👇"
)

# ========== КЛИЕНТ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(INSTRUCTION_TEXT, reply_markup=get_client_kb(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "📩 Создать обращение")
async def create_ticket_start(message: Message, state: FSMContext):
    await state.set_state(TicketStates.waiting_description)
    await message.answer("✍️ Опиши проблему подробно (минимум 5 символов):", reply_markup=get_cancel_kb())

@dp.message(StateFilter(TicketStates.waiting_description))
async def get_description(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_client_kb())
        return
    if not message.text or len(message.text.strip()) < 5:
        await message.answer("Опиши проблему хотя бы в 5 символов. Или нажми Отмена.")
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(TicketStates.waiting_photo)
    await message.answer("Пришли фото проблемы или нажми 'Пропустить фото'", reply_markup=get_skip_photo_kb())

@dp.message(StateFilter(TicketStates.waiting_photo), F.photo | F.text)
async def get_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    description = data.get("description")
    if not description:
        await state.clear()
        await message.answer("Что-то пошло не так, начни заново.", reply_markup=get_client_kb())
        return

    photo_id = None
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_client_kb())
        return
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text == "⏭ Пропустить фото":
        pass
    else:
        await message.answer("Пришли ФОТО или нажми кнопку 'Пропустить фото'")
        return

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tickets (user_id, username, description, photo_file_id, status, created_at) VALUES (?,?,?,?,?,?)",
            (message.from_user.id, message.from_user.username, description, photo_id, "Новое", datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        ticket_id = cur.lastrowid

    await state.clear()
    await message.answer(
        f"✅ Принято!\nНомер: <b>{format_ticket_id(ticket_id)}</b>\nСтатус: <b>Новое</b>",
        reply_markup=get_client_kb(), parse_mode=ParseMode.HTML
    )

    # Уведомление админу
    try:
        admin_text = f"🆕 <b>Новый тикет {format_ticket_id(ticket_id)}</b>\nОт: @{message.from_user.username or message.from_user.id} ID:{message.from_user.id}\n\n{description}"
        if photo_id:
            await bot.send_photo(ADMIN_ID, photo=photo_id, caption=admin_text, parse_mode=ParseMode.HTML, reply_markup=get_admin_ticket_kb(ticket_id, "Новое"))
        else:
            await bot.send_message(ADMIN_ID, admin_text, parse_mode=ParseMode.HTML, reply_markup=get_admin_ticket_kb(ticket_id, "Новое"))
    except Exception as e:
        logging.warning(f"Не смог уведомить админа: {e}")

@dp.message(F.text == "📋 Мои тикеты")
async def my_tickets(message: Message):
    with sqlite3.connect(DB_NAME) as conn:
        tickets = conn.execute("SELECT id, status, created_at, description FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)).fetchall()
    if not tickets:
        await message.answer("У тебя пока нет обращений.", reply_markup=get_client_kb())
        return
    text = "📋 <b>Твои тикеты:</b>\n\n"
    for t_id, status, created_at, desc in tickets:
        emoji = {"Новое":"🟢","В работе":"🟡","Решено":"✅"}.get(status,"⚪️")
        short = (desc[:40]+"...") if len(desc)>40 else desc
        text+=f"{emoji} {format_ticket_id(t_id)} | {status} | {created_at}\n<i>{short}</i>\n\n"
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_client_kb())

# ========== АДМИН ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id!= ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    with sqlite3.connect(DB_NAME) as conn:
        tickets = conn.execute("SELECT id, user_id, description, status FROM tickets WHERE status='Новое' ORDER BY id ASC").fetchall()
    if not tickets:
        await message.answer("✅ Новых тикетов нет.\nПоиск: напиши #0012 или 12")
        return
    await message.answer(f"📥 Новых: {len(tickets)}")
    for t_id, user_id, desc, status in tickets:
        await message.answer(f"<b>Тикет {format_ticket_id(t_id)}</b> от {user_id}\n{desc[:300]}", parse_mode=ParseMode.HTML, reply_markup=get_admin_ticket_kb(t_id, status))

@dp.message(F.from_user.id == ADMIN_ID, F.text.regexp(r'^#?\d{1,6}$'))
async def search_ticket(message: Message):
    ticket_id = parse_ticket_id(message.text)
    if not ticket_id: return
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT id, user_id, username, description, photo_file_id, status, created_at, admin_answer, rating FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not row:
        await message.answer(f"Тикет {format_ticket_id(ticket_id)} не найден.")
        return
    t_id, user_id, username, desc, photo_id, status, created_at, answer, rating = row
    text = f"<b>Тикет {format_ticket_id(t_id)}</b>\nКлиент: @{username or 'нет'} ID:{user_id}\nДата:{created_at}\nСтатус:{status}\nОценка:{rating or 'нет'}\n\n<b>Проблема:</b>\n{desc}\n\n<b>Ответ:</b>\n{answer or 'пока нет'}"
    if photo_id:
        await message.answer_photo(photo_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=get_admin_ticket_kb(t_id, status))
    else:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_ticket_kb(t_id, status))

@dp.callback_query(F.data.startswith("take_"))
async def admin_take(callback: CallbackQuery):
    if callback.from_user.id!= ADMIN_ID: return
    ticket_id = int(callback.data.split("_")[1])
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
        row = cur.fetchone()
        if not row:
            await callback.answer("Тикет не найден", show_alert=True)
            return
        user_id = row[0]
        cur.execute("UPDATE tickets SET status='В работе' WHERE id=?", (ticket_id,))
    await callback.message.edit_reply_markup(reply_markup=get_admin_ticket_kb(ticket_id, "В работе"))
    await callback.answer(f"Взял {format_ticket_id(ticket_id)}")
    try: await bot.send_message(user_id, f"🛠 Твой тикет {format_ticket_id(ticket_id)} взят в работу.")
    except: pass

@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id!= ADMIN_ID: return
    ticket_id = int(callback.data.split("_")[1])
    await state.set_state(TicketStates.admin_replying)
    await state.update_data(reply_ticket_id=ticket_id)
    await callback.message.answer(f"✍️ Пишешь ответ для {format_ticket_id(ticket_id)} (можно с фото):")
    await callback.answer()

@dp.message(StateFilter(TicketStates.admin_replying), F.text | F.photo)
async def admin_send_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    answer_text = message.caption or message.text or ""

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
        row = cur.fetchone()
        if not row:
            await state.clear()
            await message.answer("Тикет уже удален.")
            return
        user_id = row[0]
        cur.execute("UPDATE tickets SET admin_answer=?, status='В работе' WHERE id=?", (answer_text, ticket_id))

    await state.clear()
    await message.answer(f"✅ Ответ на {format_ticket_id(ticket_id)} отправлен.", reply_markup=get_admin_ticket_kb(ticket_id, "В работе"))

    try:
        if message.photo:
            await bot.send_photo(user_id, photo=message.photo[-1].file_id, caption=f"💬 <b>Ответ по {format_ticket_id(ticket_id)}:</b>\n\n{answer_text}", parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(user_id, f"💬 <b>Ответ по {format_ticket_id(ticket_id)}:</b>\n\n{answer_text}", parse_mode=ParseMode.HTML)
    except:
        await message.answer("⚠️ Клиент заблокировал бота, не доставлено.")

@dp.callback_query(F.data.startswith("close_"))
async def admin_close(callback: CallbackQuery):
    if callback.from_user.id!= ADMIN_ID: return
    ticket_id = int(callback.data.split("_")[1])
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE tickets SET status='Решено' WHERE id=?", (ticket_id,))
        row = conn.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not row: return
    user_id = row[0]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Тикет {format_ticket_id(ticket_id)} закрыт.")
    await callback.answer()
    try:
        await bot.send_message(user_id, f"✅ Тикет {format_ticket_id(ticket_id)} <b>Решено</b>.\nОцени поддержку:", parse_mode=ParseMode.HTML, reply_markup=get_rating_kb())
    except: pass

@dp.callback_query(F.data.startswith("rate_"))
async def rate_ticket(callback: CallbackQuery):
    rating = int(callback.data.split("_")[1])
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT id FROM tickets WHERE user_id=? AND status='Решено' AND rating IS NULL ORDER BY id DESC LIMIT 1", (callback.from_user.id,)).fetchone()
        if row:
            conn.execute("UPDATE tickets SET rating=? WHERE id=?", (rating, row[0]))
            await callback.message.edit_text(f"Спасибо за оценку {rating}⭐️ для {format_ticket_id(row[0])}!")
            try: await bot.send_message(ADMIN_ID, f"⭐️ Тикет {format_ticket_id(row[0])} оценили на {rating}/5")
            except: pass
        else:
            await callback.message.edit_text("Спасибо!")
    await callback.answer()

# --- ФИНАЛЬНЫЙ FALLBACK (белиберда) ---
@dp.message()
async def fallback_handler(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    await message.answer(f"🤔 Я тебя не понял.\n\n{INSTRUCTION_TEXT}", parse_mode=ParseMode.HTML, reply_markup=get_client_kb())

async def main():
    init_db()
    print("Support Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
