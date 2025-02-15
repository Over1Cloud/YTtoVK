import logging
import requests
import sqlite3
import os
import io
from PyPDF2 import PdfReader
from docx import Document
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ✅ Конфигурация
API_TOKEN = 'ВАШ_TELEGRAM_API_TOKEN'
DEEPINFRA_API_KEY = 'ВАШ_DEEPINFRA_API_KEY'
DEEPINFRA_API_BASE = 'https://api.deepinfra.com/v1'

# ✅ Инициализация бота (aiogram 2.25.1)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

# ✅ Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Подключение к БД
def db_connection():
    return sqlite3.connect('chatbot.db', isolation_level=None, check_same_thread=False)

# ✅ Создание базы данных
def create_db():
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            selected_model TEXT DEFAULT 'deepseek-ai/DeepSeek-V3'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
            user_id INTEGER,
            message TEXT,
            response TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')

create_db()

# ✅ Сохранение истории сообщений
def save_message(user_id, user_message, bot_response):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (user_id, message, response) VALUES (?, ?, ?)",
                       (user_id, user_message, bot_response))
        conn.commit()

# ✅ Получение последних сообщений для контекста
def get_message_history(user_id, limit=5):
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message, response FROM messages WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                       (user_id, limit))
        rows = cursor.fetchall()
    
    # Формируем историю в виде диалога
    history = []
    for row in reversed(rows):
        history.append({"role": "user", "content": row[0]})
        history.append({"role": "assistant", "content": row[1]})
    
    return history

# ✅ Команда /start – выбор модели
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("⚡ DeepSeek-V3 (Быстрое общение)", callback_data='select_model_deepseek_v3'),
        InlineKeyboardButton("💬 DeepSeek-R1 (Общение)", callback_data='select_model_deepseek_r1'),
        InlineKeyboardButton("💻 Qwen2.5-Coder (Кодинг)", callback_data='select_model_qwen'),
        InlineKeyboardButton("🎨 FLUX-1-dev (Генерация изображений)", callback_data='select_model_flux')
    )
    await message.answer("Выберите модель:", reply_markup=keyboard)

# ✅ Обработка выбора модели
@dp.callback_query_handler(lambda c: c.data.startswith('select_model_'))
async def process_model_selection(callback_query: types.CallbackQuery):
    model_map = {
        'select_model_deepseek_v3': 'deepseek-ai/DeepSeek-V3',
        'select_model_deepseek_r1': 'deepseek-ai/DeepSeek-R1',
        'select_model_qwen': 'Qwen/Qwen2.5-Coder-32B-Instruct',
        'select_model_flux': 'black-forest-labs/FLUX-1-dev'
    }
    selected_model = model_map[callback_query.data]
    user_id = callback_query.from_user.id

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, selected_model) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET selected_model=?",
                       (user_id, selected_model, selected_model))

    await bot.send_message(user_id, f"✅ Вы выбрали: `{selected_model}`.\nТеперь просто отправьте сообщение.")
    await callback_query.answer()

# ✅ Обработка текстовых сообщений
@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT selected_model FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

    selected_model = result[0] if result else "deepseek-ai/DeepSeek-V3"
    logging.info(f"📝 Пользователь {user_id} использует модель: {selected_model}")

    if selected_model == 'black-forest-labs/FLUX-1-dev':
        image_url = generate_image_response(selected_model, message.text)
        if image_url:
            await message.answer_photo(image_url, caption=f"🎨 Сгенерировано по запросу:\n`{message.text}`")
        else:
            await message.answer("❌ Не удалось сгенерировать изображение.")
    else:
        # Получаем историю общения
        history = get_message_history(user_id)
        
        # Генерируем ответ с учетом контекста
        response = generate_text_response(selected_model, message.text, history)
        
        # Сохраняем сообщение и ответ в БД
        save_message(user_id, message.text, response)

        await message.answer(response)

# ✅ Функция для генерации текстового ответа (с контекстом)
def generate_text_response(model, user_input, history):
    try:
        url = f"{DEEPINFRA_API_BASE}/openai/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPINFRA_API_KEY}", "Content-Type": "application/json"}
        
        # Формируем полный контекст для запроса
        messages = history + [{"role": "user", "content": user_input}]
        
        data = {
            "model": model,
            "messages": messages,
            "max_tokens": 500
        }

        response = requests.post(url, headers=headers, json=data)
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"Ошибка генерации текста: {e}")
        return "❌ Ошибка при обработке сообщения."

# ✅ Функция генерации изображений через FLUX
def generate_image_response(model, prompt):
    try:
        url = f"{DEEPINFRA_API_BASE}/models/{model}/generate"
        headers = {"Authorization": f"Bearer {DEEPINFRA_API_KEY}", "Content-Type": "application/json"}
        data = {"prompt": prompt, "num_images": 1}
        response = requests.post(url, headers=headers, json=data)
        return response.json()['data'][0]['url']
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {e}")
        return None

# ✅ Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
