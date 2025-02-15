import logging
import openai
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.filters import Text
import asyncio
from aiogram.utils.exceptions import RetryAfter, NetworkError

# Конфигурация
API_TOKEN = '8054902787:AAEa7LXJbyfQgSrl6feKDc3Upuo3KOf9WR0'
OPENAI_API_KEY = 'YOUR_OPENAI_API_KEY'
ADMIN_USER_ID = 7614384792  # Замените на свой Telegram ID
MAX_MESSAGE_LENGTH = 4096  # Ограничение Telegram на одно сообщение

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())
openai.api_key = OPENAI_API_KEY

# Логирование
logging.basicConfig(level=logging.INFO)

# Подключение к базе данных
def db_connection():
    try:
        conn = sqlite3.connect('preferences.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по именам
        return conn
    except sqlite3.Error as e:
        logging.error(f"Ошибка подключения к БД: {e}")
        return None

def create_db():
    conn = db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS girls (
            girl_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            preferences TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            age TEXT,
            height_weight TEXT,
            city TEXT,
            interests TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS feedbacks (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            feedback TEXT
        )''')
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании таблиц: {e}")
    finally:
        conn.close()

create_db()

# Состояния для сбора информации о пользователе
class UserState(StatesGroup):
    waiting_for_age = State()
    waiting_for_height_weight = State()
    waiting_for_city = State()
    waiting_for_interests = State()

# Состояние для обратной связи
class FeedbackState(StatesGroup):
    waiting_for_feedback = State()

# Функция разбиения длинных сообщений
def split_text(text, max_length=MAX_MESSAGE_LENGTH):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

# Генерация AI-ответа
async def generate_response(user_info, girl_info, messages):
    if not user_info or not girl_info:
        return "Недостаточно данных для генерации ответа."

    prompt = (
        f"Ты — AI, помогающий пользователю вести диалог с девушками. "
        f"Пользователь: возраст {user_info['age']}, рост/вес {user_info['height_weight']}, город {user_info['city']}, интересы: {user_info['interests']}.\n"
        f"Девушка: {girl_info['preferences']}.\n"
        f"Сообщения: {messages}\n"
        f"Дай естественный ответ, учитывая контекст."
    )

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        return response['choices'][0]['message']['content'].strip()
    except openai.error.OpenAIError as e:
        logging.error(f"Ошибка OpenAI: {e}")
        return "Ошибка при генерации ответа."

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer("Привет! Введи свой возраст.")
    await UserState.waiting_for_age.set()

# Обработка ввода возраста
@dp.message_handler(state=UserState.waiting_for_age, content_types=types.ContentType.TEXT)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите корректный возраст (число).")
        return
    await state.update_data(age=message.text)
    await message.answer("Введи свой рост/вес (например, 175/70):")
    await UserState.waiting_for_height_weight.set()

# Обработка ввода роста/веса
@dp.message_handler(state=UserState.waiting_for_height_weight, content_types=types.ContentType.TEXT)
async def process_height_weight(message: types.Message, state: FSMContext):
    if '/' not in message.text or len(message.text.split('/')) != 2:
        await message.answer("Пожалуйста, введите данные в формате 'рост/вес' (например, 175/70).")
        return
    await state.update_data(height_weight=message.text)
    await message.answer("Введи свой город:")
    await UserState.waiting_for_city.set()

# Обработка ввода города
@dp.message_handler(state=UserState.waiting_for_city, content_types=types.ContentType.TEXT)
async def process_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Введи свои интересы (например, спорт, музыка, кино):")
    await UserState.waiting_for_interests.set()

# Обработка ввода интересов и сохранение в БД
@dp.message_handler(state=UserState.waiting_for_interests, content_types=types.ContentType.TEXT)
async def process_interests(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    user_data['interests'] = message.text

    conn = db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, age, height_weight, city, interests)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                age = excluded.age,
                height_weight = excluded.height_weight,
                city = excluded.city,
                interests = excluded.interests
            """, (message.from_user.id, user_data['age'], user_data['height_weight'], user_data['city'], user_data['interests']))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Ошибка при сохранении данных пользователя: {e}")
        finally:
            conn.close()

    await message.answer(f"Данные сохранены: {user_data}")
    await state.finish()

# Команда /feedback
@dp.message_handler(commands=['feedback'])
async def feedback_start(message: types.Message):
    await message.answer("Оставьте ваш отзыв:")
    await FeedbackState.waiting_for_feedback.set()

@dp.message_handler(state=FeedbackState.waiting_for_feedback, content_types=types.ContentType.TEXT)
async def feedback_save(message: types.Message, state: FSMContext):
    conn = db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO feedbacks (user_id, feedback) VALUES (?, ?)", (message.from_user.id, message.text))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Ошибка при сохранении отзыва: {e}")
        finally:
            conn.close()
    await message.answer("Спасибо за ваш отзыв!")
    await state.finish()

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)