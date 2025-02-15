import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import openai

# Конфигурация
API_TOKEN = 'ВАШ_TELEGRAM_API_TOKEN'
DEEPINFRA_API_KEY = 'ВАШ_DEEPINFRA_API_KEY'
MAX_MESSAGE_LENGTH = 4096

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

# Настройка клиента OpenAI для использования с DeepInfra
openai.api_key = DEEPINFRA_API_KEY
openai.api_base = 'https://api.deepinfra.com/v1/openai'

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
@dp.message_handler(lambda message: message.forward_from is not None or message.forward_sender_name is not None)
async def forwarded_message_handler(message: types.Message):
    logging.info(f"Пересланное сообщение получено: {message}")

    girl_id = message.forward_from.id if message.forward_from else None
    username = message.forward_from.username if message.forward_from else message.forward_sender_name or "Неизвестно"
    text = message.text or message.caption or "[Нет текста]"

    if girl_id:
        # Если ID доступен, сохраняем в БД
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

    # Кнопка "Помочь с ответом"
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Помочь с ответом", callback_data=f"reply_{girl_id or 'unknown'}"))

    await message.reply(f"Получено сообщение от {username}. Что сделать?", reply_markup=keyboard)

# Обработка кнопки "Помочь с ответом"
@dp.callback_query_handler(lambda c: c.data.startswith('reply_'))
async def reply_to_girl(callback_query: types.CallbackQuery):
    girl_id = callback_query.data.split('_')[1]

    if girl_id == "unknown":
        response = await generate_ai_response("Неизвестный собеседник, данных о предпочтениях нет.")
    else:
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

        response = await generate_ai_response(girl_info['preferences'] if girl_info else "Нет данных для анализа.")

    await bot.send_message(callback_query.from_user.id, response)
    await callback_query.answer()

# Генерация AI-ответа с использованием модели DeepInfra
async def generate_ai_response(girl_preferences):
    prompt = f"Помоги пользователю ответить девушке. Её предпочтения: {girl_preferences}. Ответь естественно."

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai.ChatCompletion.create(
                model="deepseek-ai/DeepSeek-R1",
                messages=[
                    {"role": "system", "content": "Ты помощник в общении с девушками."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.7,
                top_p=0.9,
                n=1,
                stop=None
            )
        )
        return response.choices[0].message['content'].strip()
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

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
