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

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

# Настройка OpenAI API
openai.api_key = DEEPINFRA_API_KEY
openai.api_base = 'https://api.deepinfra.com/v1/openai'

# Логирование
logging.basicConfig(level=logging.INFO)

# Функция для подключения к БД
def db_connection():
    return sqlite3.connect('preferences.db', isolation_level=None, check_same_thread=False)

# Функция для создания таблиц
def create_db():
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS girls (
            girl_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE,
            username TEXT,
            preferences TEXT
        )''')

# Создаём базу перед запуском бота
create_db()

# Функция отправки длинных сообщений
async def send_long_message(chat_id, text):
    max_length = 4096  # Максимальная длина сообщения в Telegram
    for i in range(0, len(text), max_length):
        await bot.send_message(chat_id, text[i:i+max_length])

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    
    await message.answer("Привет! Пересылай сообщения от девушек, каналов или скрытых аккаунтов, чтобы бот помогал в общении.")

# Обработка пересланных сообщений (от пользователей, скрытых аккаунтов, каналов)
@dp.message_handler(lambda message: message.forward_from or message.forward_sender_name or message.forward_from_chat)
async def forwarded_message_handler(message: types.Message):
    """Обрабатывает пересланные сообщения от пользователей, скрытых аккаунтов и каналов."""
    if message.forward_from:  # Обычный пользователь
        sender_id = str(message.forward_from.id)
        username = message.forward_from.username or "Неизвестно"
    elif message.forward_from_chat:  # Канал
        sender_id = f"channel_{message.forward_from_chat.id}"
        username = message.forward_from_chat.title or "Без названия (Канал)"
    else:  # Скрытый аккаунт
        sender_id = "hidden_account"
        username = message.forward_sender_name or "Скрытый пользователь"

    text = message.text or message.caption or "[Нет текста]"

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (sender_id,))
        girl = cursor.fetchone()

        if girl:
            new_preferences = (girl[0] or "") + f"\n{text}"
            cursor.execute("UPDATE girls SET preferences=? WHERE telegram_id=?", (new_preferences, sender_id))
        else:
            cursor.execute("INSERT INTO girls (telegram_id, username, preferences) VALUES (?, ?, ?)", (sender_id, username, text))

    # Кнопки: "Помочь с ответом" и "Анализ анкеты"
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Помочь с ответом", callback_data=f"reply_{sender_id}"),
        InlineKeyboardButton("Анализ анкеты", callback_data=f"analyze_{sender_id}")
    )

    await message.answer(f"Получено сообщение от {username}. Что сделать?", reply_markup=keyboard)

# Обработка кнопки "Помочь с ответом"
@dp.callback_query_handler(lambda c: c.data.startswith('reply_'))
async def reply_to_girl(callback_query: types.CallbackQuery):
    sender_id = callback_query.data.split('_')[1]

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (sender_id,))
        girl_info = cursor.fetchone()

    response = generate_ai_response(girl_info[0] if girl_info else "Нет данных для анализа.")

    await send_long_message(callback_query.from_user.id, response)
    await callback_query.answer()

# Обработка кнопки "Анализ анкеты"
@dp.callback_query_handler(lambda c: c.data.startswith('analyze_'))
async def analyze_profile_handler(callback_query: types.CallbackQuery):
    sender_id = callback_query.data.split('_')[1]

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT preferences FROM girls WHERE telegram_id=?", (sender_id,))
        girl_info = cursor.fetchone()

    analysis = analyze_profile_response(girl_info[0] if girl_info else "Нет данных для анализа.")

    await send_long_message(callback_query.from_user.id, analysis)
    await callback_query.answer()

# Генерация AI-ответа с использованием модели DeepInfra
def generate_ai_response(preferences):
    prompt = f"Помоги пользователю ответить. Данные о собеседнике: {preferences}. Ответь естественно."

    try:
        response = openai.ChatCompletion.create(
            model="deepseek-ai/DeepSeek-R1",
            messages=[
                {"role": "system", "content": "Ты помощник в общении."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000  # Длинные ответы
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка при генерации AI-ответа: {e}")
        return "Ошибка при генерации ответа."

# Анализ анкеты
def analyze_profile_response(preferences):
    prompt = f"""
    Проведи анализ анкеты на основе следующей информации:
    {preferences}
    
    Оцени анкету по следующим критериям:
    - Интересность и уникальность (0-10)
    - Глубина раскрытия личности (0-10)
    - Общая привлекательность для общения (0-10)
    
    Итоговый балл = среднее значение по этим параметрам.
    Опиши плюсы и минусы анкеты и сделай вывод.
    """

    try:
        response = openai.ChatCompletion.create(
            model="deepseek-ai/DeepSeek-R1",
            messages=[
                {"role": "system", "content": "Ты аналитик анкет."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка при анализе анкеты: {e}")
        return "Ошибка при анализе анкеты."

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
