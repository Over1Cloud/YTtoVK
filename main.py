import logging
import requests
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ✅ Конфигурация
API_TOKEN = 'ВАШ_TELEGRAM_API_TOKEN'
DEEPINFRA_API_KEY = 'ВАШ_DEEPINFRA_API_KEY'
DEEPINFRA_API_BASE = 'https://api.deepinfra.com/v1'

# ✅ Инициализация бота и диспетчера (aiogram 2.25.1)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

# ✅ Логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Подключение к БД
def db_connection():
    return sqlite3.connect('chatbot.db', isolation_level=None, check_same_thread=False)

# ✅ Создание таблицы пользователей
def create_db():
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            selected_model TEXT
        )''')

create_db()

# ✅ Команда /start – выбор модели
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("💬 DeepSeek-R1 (Общение)", callback_data='select_model_deepseek'),
        InlineKeyboardButton("💻 Qwen2.5-Coder (Кодинг)", callback_data='select_model_qwen'),
        InlineKeyboardButton("🎨 FLUX-1-dev (Генерация изображений)", callback_data='select_model_flux')
    )
    await message.answer("Выберите модель:", reply_markup=keyboard)

# ✅ Обработка выбора модели
@dp.callback_query_handler(lambda c: c.data.startswith('select_model_'))
async def process_model_selection(callback_query: types.CallbackQuery):
    model_map = {
        'select_model_deepseek': 'deepseek-ai/DeepSeek-R1',
        'select_model_qwen': 'Qwen/Qwen2.5-Coder-32B-Instruct',
        'select_model_flux': 'black-forest-labs/FLUX-1-dev'
    }
    selected_model = model_map[callback_query.data]
    user_id = callback_query.from_user.id

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, selected_model) VALUES (?, ?)", (user_id, selected_model))

    await bot.send_message(user_id, f"✅ Вы выбрали: `{selected_model}`\nТеперь отправьте сообщение для общения или используйте команду `/generate_image` для создания изображения.")
    await callback_query.answer()

# ✅ Обработка текстовых сообщений
@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT selected_model FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

    if result:
        selected_model = result['selected_model']
        if selected_model == 'black-forest-labs/FLUX-1-dev':
            await message.answer("🎨 Эта модель для **генерации изображений**. Используйте команду `/generate_image`.")
        else:
            response = generate_text_response(selected_model, message.text)
            await message.answer(response)
    else:
        await message.answer("⚠️ Сначала выберите модель с помощью команды /start.")

# ✅ Функция для генерации текстового ответа
def generate_text_response(model, user_input):
    try:
        url = f"{DEEPINFRA_API_BASE}/openai/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPINFRA_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Вы - дружелюбный AI-ассистент."},
                {"role": "user", "content": user_input}
            ],
            "max_tokens": 150
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
        else:
            logging.error(f"Ошибка API DeepInfra: {response.status_code} - {response.text}")
            return "❌ Ошибка при генерации ответа."
    except Exception as e:
        logging.error(f"Ошибка при генерации ответа: {e}")
        return "❌ Ошибка при генерации ответа."

# ✅ Команда для генерации изображений
@dp.message_handler(commands=['generate_image'])
async def generate_image(message: types.Message):
    user_id = message.from_user.id
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT selected_model FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

    if result:
        selected_model = result['selected_model']
        if selected_model == 'black-forest-labs/FLUX-1-dev':
            prompt = message.get_args()
            if not prompt:
                await message.answer("⚠️ Укажите описание после `/generate_image`.")
                return
            image_url = generate_image_response(selected_model, prompt)
            if image_url:
                await message.answer_photo(image_url)
            else:
                await message.answer("❌ Не удалось сгенерировать изображение.")
        else:
            await message.answer("⚠️ Эта модель не поддерживает генерацию изображений. Выберите FLUX-1-dev.")
    else:
        await message.answer("⚠️ Сначала выберите модель с помощью команды /start.")

# ✅ Функция для генерации изображений
def generate_image_response(model, prompt):
    try:
        url = f"{DEEPINFRA_API_BASE}/models/{model}/generate"
        headers = {
            "Authorization": f"Bearer {DEEPINFRA_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {"prompt": prompt, "num_images": 1}
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            return result['data'][0]['url']  # API должен возвращать URL изображения
        else:
            logging.error(f"Ошибка генерации изображения: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {e}")
        return None

# ✅ Запуск бота (aiogram 2.25.1)
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
