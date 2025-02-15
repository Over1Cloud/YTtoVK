import logging
import openai
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import asyncio

# Конфигурация
API_TOKEN = 'ВАШ_ТОКЕН'
OPENAI_API_KEY = 'ВАШ_OPENAI_КЛЮЧ'
MAX_MESSAGE_LENGTH = 4096

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())
openai.api_key = OPENAI_API_KEY

# Логирование
logging.basicConfig(level=logging.INFO)

# Подключение к базе данных
def db_connection():
    conn = sqlite3.connect('preferences.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def create_db():
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS girls (
        girl_id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        preferences TEXT
    )''')
    conn.commit()
    conn.close()

create_db()

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    conn = db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (message.from_user.id,))
        user = cursor.fetchone()

        if not user:
            cursor.execute("INSERT INTO users (user_id) VALUES (?)", (message.from_user.id,))
            conn.commit()
        
        await message.answer("Привет! Пересылай сообщения от девушек, чтобы бот помогал в общении.")
    except Exception as e:
        logging.error(f"Ошибка в /start: {e}")
        await message.answer("Произошла ошибка при обработке команды.")
    finally:
        conn.close()

# Обработка пересланных сообщений
@dp.message_handler(lambda message: message.forward_from is not None)
async def forwarded_message_handler(message: types.Message):
    logging.info(f"Пересланное сообщение получено от: {message.forward_from.id}, username: {message.forward_from.username}")

    girl_id = message.forward_from.id
    username = message.forward_from.username or "Неизвестно"
    text = message.text or message.caption or "[Нет текста]"

    conn = db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (girl_id,))
        girl = cursor.fetchone()

        if girl:
            new_preferences = (girl['preferences'] or "") + f"\n{text}"
            cursor.execute("UPDATE girls SET preferences=? WHERE telegram_id=?", (new_preferences, girl_id))
        else:
            cursor.execute("INSERT INTO girls (telegram_id, username, preferences) VALUES (?, ?, ?)", (girl_id, username, text))
        
        conn.commit()
        logging.info(f"Данные для {username} (ID: {girl_id}) успешно записаны в БД.")
    except Exception as e:
        logging.error(f"Ошибка при сохранении предпочтений: {e}")
    finally:
        conn.close()

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Сохранить предпочтения", callback_data=f"save_{girl_id}"),
        InlineKeyboardButton("Помочь с ответом", callback_data=f"reply_{girl_id}")
    )

    await message.reply(f"Получено сообщение от {username}. Что сделать?", reply_markup=keyboard)

# Обработка инлайн-кнопок
@dp.callback_query_handler(lambda c: c.data.startswith('save_'))
async def save_preferences(callback_query: types.CallbackQuery):
    data_parts = callback_query.data.split('_')
    if len(data_parts) != 2 or not data_parts[1].isdigit():
        await callback_query.answer("Ошибка обработки команды.")
        return

    await bot.send_message(callback_query.from_user.id, "Предпочтения сохранены!")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('reply_'))
async def reply_to_girl(callback_query: types.CallbackQuery):
    data_parts = callback_query.data.split('_')
    if len(data_parts) != 2 or not data_parts[1].isdigit():
        await callback_query.answer("Ошибка обработки команды.")
        return

    girl_id = int(data_parts[1])

    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (girl_id,))
        girl_info = cursor.fetchone()
    except Exception as e:
        logging.error(f"Ошибка при получении предпочтений: {e}")
        girl_info = None
    finally:
        conn.close()

    if girl_info:
        response = await generate_ai_response(girl_info['preferences'])
        await bot.send_message(callback_query.from_user.id, response)
    else:
        await bot.send_message(callback_query.from_user.id, "Нет данных для анализа.")

    await callback_query.answer()

# Генерация AI-ответа
async def generate_ai_response(girl_preferences):
    prompt = f"Помоги пользователю ответить девушке. Её предпочтения: {girl_preferences}. Ответь естественно."

    try:
        response = await openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"Ошибка при генерации AI-ответа: {e}")
        return "Произошла ошибка при генерации ответа."

# Просмотр списка девушек
@dp.message_handler(commands=['girls'])
async def show_girls_list(message: types.Message):
    conn = db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT telegram_id, username FROM girls")
        girls = cursor.fetchall()

        if girls:
            response = "Список сохранённых девушек:\n"
            for girl in girls:
                username = f"@{girl['username']}" if girl['username'] else "Неизвестно"
                response += f"ID: {girl['telegram_id']}, Username: {username}\n"
            await message.answer(response)
        else:
            await message.answer("В базе нет сохранённых девушек.")
    except Exception as e:
        logging.error(f"Ошибка в /girls: {e}")
        await message.answer("Произошла ошибка при получении списка девушек.")
    finally:
        conn.close()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
