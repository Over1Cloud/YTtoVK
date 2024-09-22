from flask import Flask, render_template, request, jsonify, send_from_directory
import threading
import json
import logging
from logging.handlers import RotatingFileHandler
import time
import os
import psutil
import GPUtil
from threading import Thread
from googleapiclient.discovery import build
import httplib2
import vk_api
from datetime import datetime
import random
import socks
import socket
import subprocess
import hashlib
from pathlib import Path
import ffmpeg
import yt_dlp
import ssl
import urllib3
from vk_api import VkUpload
import traceback
from moviepy.editor import VideoFileClip
import requests

app = Flask(__name__)

# Настройка логирования
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.log')
file_handler = RotatingFileHandler(log_file_path, maxBytes=1024 * 1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
file_handler.setLevel(logging.DEBUG)

# Настройка корневого логгера
logging.basicConfig(level=logging.DEBUG, handlers=[file_handler])

# Получение логгера для приложения
logger = logging.getLogger(__name__)

def load_settings():
    try:
        with open('settings.cfg', 'r') as f:
            settings = json.load(f)
        if 'apiYouTube' not in settings or not settings['apiYouTube']:
            logger.warning("API YouTube отсутствует в настройках")
        return settings
    except Exception as e:
        logger.error(f"Ошибка при загрузке настроек: {str(e)}")
        return None

def save_settings(settings):
    try:
        with open('settings.cfg', 'w') as f:
            json.dump(settings, f, indent=2)
        logger.info("Settings saved successfully")
    except Exception as e:
        logger.error(f"Error saving settings: {e}")

default_settings = {
    # ... (существующие настройки)
    'PostingTitle': '@video от @author'
}

# Загрузка настроек
settings = load_settings()
if settings is None:
    settings = default_settings.copy()
else:
    for key, value in default_settings.items():
        if key not in settings:
            settings[key] = value

# Сохранение обновленных настроек
save_settings(settings)

logger.info(f"Loaded settings: {settings}")

# Отключаем предупреждения о небезопасных запросах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/update')
def update_channels_route():
    return update_channels()

@app.route('/api/status')
def get_status():
    global settings
    parsing_time = int(settings.get('parsingTime', 60)) * 60  # Конвертируем минуты в секунды
    time_since_last_update = time.time() - last_update_time
    time_until_next_update = max(0, parsing_time - time_since_last_update)
    return jsonify({
        "status": "Updating" if time_since_last_update < 60 else "Idle",
        "nextUpdate": int(time_until_next_update)
    })

@app.route('/api/logs')
def get_logs():
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.log')
    try:
        with open(log_file_path, 'r') as log_file:
            # Читаем последние 1000 строк (или меньше, если файл короче)
            lines = log_file.readlines()[-1000:]
            return ''.join(lines)
    except Exception as e:
        logger.error(f"Ошибка при чтении лог-файла: {e}")
        return "Ошибка при чтении логов"

@app.route('/api/settings', methods=['GET', 'POST'])
def settings_route():
    global settings
    if request.method == 'GET':
        return jsonify(settings)
    elif request.method == 'POST':
        new_settings = request.json
        settings.update(new_settings)
        save_settings(settings)
        return jsonify({"message": "Settings updated successfully"}), 200

@app.route('/api/system-info')
def system_info():
    cpu_percent = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    gpus = GPUtil.getGPUs()
    gpu_percent = gpus[0].load * 100 if gpus else 0

    return jsonify({
        "cpu": cpu_percent,
        "ram": ram.used / (1024 ** 3),  # Convert to GB
        "rom": disk.used / (1024 ** 3),  # Convert to GB
        "gpu": gpu_percent
    })
@app.route('/api/channels', methods=['GET'])
def get_channels():
    with open('youtube.json', 'r') as file:
        channels = json.load(file)
    return jsonify(channels)

@app.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json
    with open('youtube.json', 'r+') as file:
        channels = json.load(file)
        channels.append(new_channel)
        file.seek(0)
        json.dump(channels, file, indent=2)
    return jsonify({"message": "Channel added successfully"}), 201

@app.route('/api/channels', methods=['DELETE'])
def delete_channels():
    try:
        indexes_to_remove = request.json
        channels = load_channels()
        
        # Сортируем индексы в обратном порядке, чтобы удаление не влияло на последующие индексы
        for index in sorted(indexes_to_remove, reverse=True):
            if 0 <= index < len(channels):
                del channels[index]
        
        save_channels(channels)
        return jsonify({"message": "Каналы успешно удалены"}), 200
    except Exception as e:
        logger.error(f"Ошибка при удалении каналов: {str(e)}")
        return jsonify({"error": "Произошла ошибка при удалении каналов"}), 500

   
@app.route('/api/video-duration', methods=['POST'])
def get_video_duration(video_path):
    try:
        with VideoFileClip(video_path) as clip:
            return clip.duration
    except Exception as e:
        logger.error(f"Ошибка при получении длительности видео: {str(e)}")
        return 0

def upload_short_video_to_vk(video_path, video_name, channel_title, settings):
    try:
        # Получаем URL для загрузки видео
        upload_url = get_video_upload_url(settings)
        if not upload_url:
            raise Exception("Не удалось получить URL для загрузки видео")

        # Формируем название видео
        posting_title = format_posting_title(settings.get('PostingTitle', '@video'), video_name, channel_title)

        # Загружаем видео
        with open(video_path, 'rb') as video_file:
            files = {'video_file': video_file}
            data = {
                'name': posting_title,
                'is_private': 0,
                'wallpost': 1,
                'group_id': settings['groupId'],
                'is_short_video': 1  # Указываем, что это короткое видео
            }
            response = requests.post(upload_url, files=files, data=data)

        if response.status_code == 200:
            response_data = response.json()
            if 'response' in response_data:
                video_id = response_data['response']['video_id']
                owner_id = response_data['response']['owner_id']
                logger.info(f"Видео успешно загружено. ID: {video_id}, Owner ID: {owner_id}")
                return True
            else:
                logger.error(f"Ошибка при загрузке видео: {response_data}")
        else:
            logger.error(f"Ошибка при загрузке видео. Статус: {response.status_code}, Ответ: {response.text}")

        return False
    except Exception as e:
        logger.error(f"Ошибка при загрузке видео в ВК: {str(e)}")
        return False

def get_video_upload_url(settings):
    try:
        api_version = '5.131'  # Используйте актуальную версию API
        url = f"https://api.vk.com/method/video.save?access_token={settings['apiVK']}&group_id={settings['groupId']}&is_short_video=1&v={api_version}"
        response = requests.get(url)
        data = response.json()
        if 'response' in data and 'upload_url' in data['response']:
            return data['response']['upload_url']
        else:
            logger.error(f"Ошибка при получении URL для загрузки: {data}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении URL для загрузки: {str(e)}")
        return None

def get_upload_url(video_path, access_token):
    try:
        with open(video_path, 'rb') as file:
            files = {'video_file': file}
            params = {'access_token': access_token, 'v': '5.131'}
            
            if settings.get('proxyToggle'):
                proxy = get_random_proxy()
                if proxy:
                    ip, port, username, password = proxy.split(':')
                    proxies = {
                        'http': f'socks5://{username}:{password}@{ip}:{port}',
                        'https': f'socks5://{username}:{password}@{ip}:{port}'
                    }
                    response = requests.post('https://api.vk.com/method/video.save', params=params, files=files, proxies=proxies)
                else:
                    response = requests.post('https://api.vk.com/method/video.save', params=params, files=files)
            else:
                response = requests.post('https://api.vk.com/method/video.save', params=params, files=files)
            
            response_data = response.json()
            if 'response' in response_data:
                return response_data['response']['upload_url']
            else:
                logger.error(f"Ошибка при получении URL для загрузки: {response_data}")
                return None
    except Exception as e:
        logger.error(f"Ошибка при получении URL для загрузки: {e}")
        return None
def format_posting_title(template, video_name, channel_title):
    return template.replace('@video', video_name).replace('@author', channel_title)

def get_video_duration(video_path):
    try:
        clip = VideoFileClip(video_path)
        duration = clip.duration
        clip.close()
        return duration
    except Exception as e:
        logger.error(f"Ошибка при получении длительности видео: {e}")
        return 0


############################################################################################
############################################################################################
############################################################################################

# Глобальные переменные
youtube = None
last_update_time = 0

def set_proxy():
    if settings.get('proxyToggle'):
        proxy = get_random_proxy()
        if proxy:
            ip, port, username, password = proxy.split(':')
            proxy_url = f"socks5://{username}:{password}@{ip}:{port}"
            os.environ['HTTP_PROXY'] = proxy_url
            os.environ['HTTPS_PROXY'] = proxy_url
            socks.set_default_proxy(socks.SOCKS5, ip, int(port), username=username, password=password)
            socket.socket = socks.socksocket
            logger.info(f"Прокси установлен: {ip}:{port}")
        else:
            logger.error("Не удалось получить прокси")
    else:
        # Сброс прокси
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('HTTPS_PROXY', None)
        socks.set_default_proxy()
        socket.socket = socket._socketobject
        logger.info("Прокси отключен")


def check_and_upload_videos():
    while True:
        try:
            with open('youtube.json', 'r') as f:
                channels = json.load(f)
            
            for channel in channels:
                if channel.get('status') == 'Downloaded':
                    video_path = f"channels/{channel['Title']}/{channel['LastVideoTITLE']}.mp4"
                    
                    upload_attempts = 0
                    while upload_attempts < 3:
                        if upload_video_to_vk(video_path, channel['LastVideoTITLE'], channel['Title'], settings):
                            channel['status'] = 'Uploaded'
                            break
                        upload_attempts += 1
                        time.sleep(5)  # Пауза между попытками
                    
                    if channel['status'] != 'Uploaded':
                        channel['status'] = 'Error_Upload'
            
            with open('youtube.json', 'w') as f:
                json.dump(channels, f, indent=2)
        
        except Exception as e:
            logger.error(f"Ошибка в процессе проверки и загрузки видео: {e}")
        
        time.sleep(60)  # Проверяем каждую минуту

def parse_new_videos():
    global last_update_time, settings
    while True:
        current_time = time.time()
        if current_time - last_update_time >= int(settings.get('parsingTime', 60)) * 60:
            if initialize_youtube_api():
                channels = load_channels()
                for channel in channels:
                    updated_channel = process_channel(channel, settings)
                    # Обновляем канал в списке
                    channel.update(updated_channel)
                save_channels(channels)
                last_update_time = current_time
            else:
                logger.error("Не удалось инициализировать YouTube API")
        time.sleep(60)  # Проверка каждую минуту




def get_random_proxy():
    try:
        with open('proxy.txt', 'r') as f:
            proxies = f.readlines()
        valid_proxies = [proxy.strip() for proxy in proxies if proxy.count(':') == 3]
        if not valid_proxies:
            logger.error("No valid proxies found in proxy.txt")
            return None
        chosen_proxy = random.choice(valid_proxies)
        logger.info(f"Selected proxy: {chosen_proxy}")
        return chosen_proxy
    except Exception as e:
        logger.error(f"Error reading proxy file: {e}")
        return None

def load_channels():
    try:
        with open('youtube.json', 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logger.error(f"Ошибка загрузки каналов: {e}")
        return []

def save_channels(channels):
    try:
        with open('youtube.json', 'w', encoding='utf-8') as file:
            json.dump(channels, file, indent=2)
        logger.info("Channels saved successfully")
    except Exception as e:
        logger.error(f"Ошибка сохранения каналов: {e}")



def process_channel(channel, settings):
    try:
        logger.info(f"Обработка канала: {channel}")
        if 'URL' not in channel:
            logger.error(f"Отсутствует URL канала: {channel}")
            channel['status'] = 'Ошибка: Отсутствует URL'
            return

        channel_id = channel['URL'].split('/')[-1]
        logger.info(f"ID канала: {channel_id}")

        playlist_id = f"UU{channel_id[2:]}"
        playlist_items = youtube.playlistItems().list(
            part='snippet',
            playlistId=playlist_id,
            maxResults=1
        ).execute()
        
        if 'items' in playlist_items and playlist_items['items']:
            video = playlist_items['items'][0]['snippet']
            video_id = video['resourceId']['videoId']
            video_title = video['title']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_date = video['publishedAt']
            
            if channel.get('LastVideoURL') != video_url or channel.get('status') == 'Error_Download':
                channel['LastVideoURL'] = video_url
                channel['LastVideoTITLE'] = video_title
                channel['LastVideoDateTime'] = video_date
                
                if settings['downloadToggle']:
                    max_attempts = 3
                    for attempt in range(max_attempts):
                        if download_video(video_id, channel['Title'], settings):
                            channel['status'] = 'Downloaded'
                            break
                        else:
                            logger.warning(f"Попытка {attempt + 1} скачать видео не удалась. {'Пробуем еще раз.' if attempt < max_attempts - 1 else 'Все попытки исчерпаны.'}")
                            time.sleep(5)  # Пауза между попытками
                    
                    if channel['status'] != 'Downloaded':
                        channel['status'] = 'Error_Download'
                else:
                    channel['status'] = 'Download_Disabled'
            else:
                channel['status'] = 'Нет новых видео'
        else:
            channel['status'] = 'Видео не найдены'
    except Exception as e:
        logger.error(f"Ошибка обработки канала: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        channel['status'] = 'Ошибка обработки'

    return channel

def download_video(video_id, channel_title, settings):
    logger.debug(f"Попытка скачивания видео {video_id}")
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_dir = os.path.join('channels', channel_title)
            os.makedirs(video_dir, exist_ok=True)
            
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': os.path.join(video_dir, '%(title)s.%(ext)s'),
                'retries': 5,
                'fragment_retries': 5,
                'ignoreerrors': True,
            }
            
            if settings.get('proxyToggle'):
                proxy = get_random_proxy()
                if proxy:
                    ip, port, username, password = proxy.split(':')
                    ydl_opts['proxy'] = f'socks5://{username}:{password}@{ip}:{port}'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                if info is None:
                    logger.error(f"Не удалось получить информацию о видео {video_id}")
                    if attempt == max_attempts - 1:
                        return False
                    time.sleep(5)  # Пауза перед следующей попыткой
                    continue
                
                video_path = ydl.prepare_filename(info)
                
                # Проверяем, существует ли файл и доступен ли он для чтения
                if os.path.exists(video_path) and os.access(video_path, os.R_OK):
                    logger.info(f"Видео успешно скачано: {video_path}")
                    time.sleep(2)  # Добавьте 2-секундную задержку после скачивания
                    return True
                else:
                    logger.error(f"Не удалось скачать видео {video_id} или файл недоступен")
                    return False
        except Exception as e:
            logger.error(f"Ошибка при скачивании видео {video_id}: {str(e)}")
            if attempt == max_attempts - 1:
                return False
            time.sleep(5)  # Пауза перед следующей попыткой
    return False

def process_uploads():
    while True:
        with open('youtube.json', 'r') as f:
            channels = json.load(f)
        
        for channel in channels:
            if channel['status'] == 'Downloaded':
                video_path = f"channels/{channel['Title']}/{channel['LastVideoTITLE']}.mp4"
                
                upload_attempts = 0
                while upload_attempts < 3:
                    if upload_video_to_vk(video_path, channel['LastVideoTITLE'], channel['Title'], settings):
                        channel['status'] = 'Uploaded'
                        break
                    upload_attempts += 1
                
                if channel['status'] != 'Uploaded':
                    channel['status'] = 'Error_Upload'
        
        with open('youtube.json', 'w') as f:
            json.dump(channels, f, indent=2)
        
        time.sleep(60)  # Проверяем каждую минуту

def check_video_in_vk_group(video_name, settings):
    try:
        vk_session = vk_api.VkApi(token=settings['apiVK'])
        vk = vk_session.get_api()
        
        videos = vk.video.get(owner_id=f"-{settings['groupId']}")
        
        for video in videos['items']:
            if video['title'] == video_name:
                return True
        
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке видео в группе ВК: {str(e)}")
        return False

def upload_video_to_vk(video_path, video_name, channel_title, settings):
    try:
        vk_session = vk_api.VkApi(token=settings['apiVK'])
        upload = vk_api.VkUpload(vk_session)
        posting_title = settings.get('PostingTitle', '@video от @author')
        formatted_title = format_posting_title(posting_title, video_name, channel_title)
        
        # Получаем длительность видео
        duration = get_video_duration(video_path)
        
        # Определяем, нужно ли загружать как клип
        is_short_video = duration < 180  # меньше 3 минут
        
        # Формируем название видео
        posting_title = format_posting_title(settings['PostingTitle'], video_name, channel_title)
        
        # Загружаем видео
        if is_short_video:
            # Загрузка как клип
            video_info = upload.video(
                video_file=video_path,
                name=posting_title,
                group_id=settings['groupId'],
                is_short_video=True
            )
        else:
            # Загрузка как обычное видео
            video_info = upload.video(
                video_file=video_path,
                name=posting_title,
                group_id=settings['groupId']
            )
        
        logger.info(f"Видео успешно загружено в ВК: {video_info}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при загрузке видео в ВК: {e}")
        return False


def update_channels():
    try:
        channels = load_channels()
        if not channels:
            logger.warning("Список каналов пуст")
            return jsonify({"message": "Нет каналов для обновления"}), 200

        settings = load_settings()

        if settings is None:
            logger.error("Не удалось загрузить настройки. Завершение работы.")
            sys.exit(1)
        
        updated_channels = []
        for channel in channels:
            try:
                process_channel(channel, settings)
                updated_channels.append(channel)
            except Exception as e:
                logger.error(f"Ошибка при обработке канала {channel.get('URL', 'Unknown')}: {str(e)}")
                channel['status'] = 'Ошибка'
                updated_channels.append(channel)

        save_channels(updated_channels)
        return jsonify({"message": "Каналы успешно обновлены"}), 200
    except Exception as e:
        logger.error(f"Ошибка при обновлении каналов: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Произошла ошибка при обновлении каналов"}), 500




def initialize_youtube_api():
    global youtube, settings
    api_key = settings.get('apiYouTube')
    if not api_key:
        logger.error("YouTube API key not found in settings")
        return False

    try:
        if settings.get('proxyToggle'):
            proxy = get_random_proxy()
            if proxy:
                ip, port, username, password = proxy.split(':')
                proxy_info = httplib2.ProxyInfo(
                    proxy_type=socks.PROXY_TYPE_SOCKS5,
                    proxy_host=ip,
                    proxy_port=int(port),
                    proxy_user=username,
                    proxy_pass=password
                )
                http = httplib2.Http(proxy_info=proxy_info, disable_ssl_certificate_validation=True)
            else:
                logger.error("No valid proxy available")
                return False
        else:
            http = httplib2.Http()

        youtube = build('youtube', 'v3', developerKey=api_key, http=http)
        logger.info("YouTube API initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing YouTube API: {e}")
        youtube = None
        return False

def change_proxy():
    new_proxy = get_random_proxy()
    if new_proxy:
        ip, port, username, password = new_proxy.split(':')
        socks.set_default_proxy(socks.SOCKS5, ip, int(port), username=username, password=password)
        logger.info("Proxy changed successfully")
    else:
        logger.error("Failed to change proxy, no valid proxies available")

def background_task():
    global app, settings
    with app.app_context():
        while True:
            update_channels()
            time.sleep(int(settings.get('parsingTime', 60)) * 60)  # Ждем указанное время перед следующим обновлением



if __name__ == '__main__':
    try:
        Thread(target=check_and_upload_videos, daemon=True).start()
        Thread(target=parse_new_videos, daemon=True).start()
        upload_thread = threading.Thread(target=process_uploads)
        upload_thread.start()
        app.run(debug=True)
    except Exception as e:
        logger.exception("Произошла непредвиденная ошибка:")