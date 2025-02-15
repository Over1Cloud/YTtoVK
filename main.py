import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import openai

# Конфигурация
API_TOKEN = 'ВАШ_TELEGRAM_API_TOKEN'
DEEPINFRA_API_KEY = 'ВАШ_DEEPINFRA_API_KEY'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

# Настройка OpenAI API для использования с DeepInfra
openai.api_key = DEEPINFRA_API_KEY
openai.api_base = 'https://api.deepinfra.com/v1/openai'

# Логирование
logging.basicConfig(level=logging.INFO)

# Асинхронное подключение к базе данных
async def db_connection():
    return await aiosqlite.connect('preferences.db')

async def create_db():
    async with await db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS girls (
            girl_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            preferences TEXT
        )''')
        await conn.commit()

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    async with await db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT user_id FROM users WHERE user_id=?", (message.from_user.id,))
        user = await cursor.fetchone()

        if not user:
            await cursor.execute("INSERT INTO users (user_id) VALUES (?)", (message.from_user.id,))
            await conn.commit()
    
    await message.answer("Привет! Пересылай сообщения от девушек, чтобы бот помогал в общении.")

# Обработка пересланных сообщений
@dp.message_handler(lambda message: message.forward_from is not None or message.forward_sender_name is not None)
async def forwarded_message_handler(message: types.Message):
    girl_id = message.forward_from.id if message.forward_from else None
    username = message.forward_from.username if message.forward_from else message.forward_sender_name or "Неизвестно"
    text = message.text or message.caption or "[Нет текста]"

    if girl_id:
        async with await db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (girl_id,))
            girl = await cursor.fetchone()

            if girl:
                new_preferences = (girl[0] or "") + f"\n{text}"
                await cursor.execute("UPDATE girls SET preferences=? WHERE telegram_id=?", (new_preferences, girl_id))
            else:
                await cursor.execute("INSERT INTO girls (telegram_id, username, preferences) VALUES (?, ?, ?)", (girl_id, username, text))
            await conn.commit()

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
        async with await db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (girl_id,))
            girl_info = await cursor.fetchone()

        response = await generate_ai_response(girl_info[0] if girl_info else "Нет данных для анализа.")

    await bot.send_message(callback_query.from_user.id, response)
    await callback_query.answer()

# Генерация AI-ответа с использованием модели DeepInfra
async def generate_ai_response(girl_preferences):
    prompt = f"Помоги пользователю ответить девушке. Её предпочтения: {girl_preferences}. Ответь естественно."

    try:
        response = await openai.ChatCompletion.acreate(
            model="deepseek-ai/DeepSeek-R1",
            messages=[{"role": "system", "content": "Ты помощник в общении с девушками."},
                      {"role": "user", "content": prompt}],
            max_tokens=150
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка при генерации AI-ответа: {e}")
        return "Ошибка при генерации ответа."

# Просмотр списка девушек
@dp.message_handler(commands=['girls'])
async def show_girls_list(message: types.Message):
    async with await db_connection() as conn:
        cursor = await conn.cursor()

        try:
            await cursor.execute("SELECT telegram_id, username FROM girls")
            girls = await cursor.fetchall()

            if girls:
                response = "Список сохранённых девушек:\n"
                for girl in girls:
                    username = f"@{girl[1]}" if girl[1] else "Неизвестно"
                    response += f"ID: {girl[0]}, Username: {username}\n"
                await message.answer(response)
            else:
                await message.answer("В базе нет сохранённых девушек.")
        except Exception as e:
            logging.error(f"Ошибка в /girls: {e}")
            await message.answer("Произошла ошибка при получении списка девушек.")

# Запуск бота
async def main():
    await create_db()  # Теперь инициализация базы данных происходит перед запуском бота
    executor.start_polling(dp, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())  # Используем asyncio.run() для запуска всего кода
