let channels = [];
let settings = {};

document.addEventListener('DOMContentLoaded', function () {
    console.log("DOM fully loaded");
    fetchChannels();
    loadSettings();
    updateSystemInfo();
    initializeTimer();
});

function fetchChannels() {
    console.log("Fetching channels...");
    fetch('/api/channels')
        .then(response => {
            console.log("Response status:", response.status);
            return response.json();
        })
        .then(data => {
            console.log("Received channels:", data);
            channels = data;
            document.getElementById('totalRecords').innerText = channels.length;
            changeRecordsPerPage();
        })
        .catch(error => console.error('Error fetching data:', error));
}

function populateTable(data) {
    const tbody = document.querySelector('#channelTable tbody');
    tbody.innerHTML = '';

    data.forEach(channel => {
        const row = document.createElement('tr');
        let formattedDate = 'N/A';
        if (channel.LastVideoDateTime) {
            const date = new Date(channel.LastVideoDateTime);
            formattedDate = date.toLocaleString('ru-RU', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }).replace(',', '');
        }
        row.innerHTML = `
            <td>${channel.Title || 'Unknown'}</td>
            <td>${channel.LastVideoTITLE || 'N/A'}</td>
            <td>${formattedDate}</td>
            <td>${channel.status || 'Unknown'}</td>
        `;
        tbody.appendChild(row);
    });
}

function showAddModal() {
    closeModal(); // Закрываем предыдущее модальное окно, если оно открыто
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Добавить канал(ы)</h2>
            <textarea id="channelUrls" placeholder="Вставьте ссылки на каналы (по одной на строку)" rows="5"></textarea>
            <button onclick="addChannels()">Добавить</button>
            <button onclick="closeModal()">Отмена</button>
        </div>
    `;
    document.body.appendChild(modal);
}

function addChannels() {
    const urls = document.getElementById('channelUrls').value.trim().split('\n');
    const validUrls = urls.filter(url => url.trim() !== '');
    
    if (validUrls.length > 0) {
        const addPromises = validUrls.map(url => 
            fetch('/api/channels', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ URL: url.trim() }),
            }).then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
        );

        Promise.all(addPromises)
            .then(() => {
                return fetch('/api/channels');  // Получаем обновленный список каналов
            })
            .then(response => response.json())
            .then(updatedChannels => {
                channels = updatedChannels;
                changeRecordsPerPage();
                closeModal();
                alert(`Добавлено ${validUrls.length} канал(ов)`);
            })
            .catch(error => {
                console.error('Error adding channels:', error);
                alert('Произошла ошибка при добавлении каналов');
            });
    } else {
        alert('Пожалуйста, введите хотя бы один URL канала');
    }
}

function showRemoveModal() {
    closeModal(); // Закрываем предыдущее модальное окно, если оно открыто
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Удалить каналы</h2>
            <div id="channelList"></div>
            <button onclick="removeSelectedChannels()">Удалить выбранные</button>
            <button onclick="closeModal()">Отмена</button>
        </div>
    `;
    document.body.appendChild(modal);

    const channelList = document.getElementById('channelList');
    channels.forEach((channel, index) => {
        channelList.innerHTML += `
            <div>
                <input type="checkbox" id="channel${index}" value="${index}">
                <label for="channel${index}">${channel.Title || channel.URL}</label>
            </div>
        `;
    });
}

function removeSelectedChannels() {
    const checkboxes = document.querySelectorAll('#channelList input[type="checkbox"]:checked');
    const indexesToRemove = Array.from(checkboxes).map(checkbox => parseInt(checkbox.value));

    if (indexesToRemove.length === 0) {
        alert('Пожалуйста, выберите каналы для удаления');
        return;
    }

    fetch('/api/channels', {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(indexesToRemove),
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        console.log('Channels removed:', data);
        closeModal();
        fetchChannels();
    })
    .catch(error => {
        console.error('Error removing channels:', error);
        alert('Произошла ошибка при удалении каналов');
    });
}

function closeModal() {
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => modal.remove());
}

function updateChannels() {
    fetch('/api/update')
        .then(response => response.json())
        .then(data => {
            console.log('Update response:', data);
            if (data.message === "Update started") {
                checkUpdateStatus();
            } else {
                fetchChannels();
                startUpdateTimer();
            }
        })
        .catch(error => {
            console.error('Error updating channels:', error);
            startUpdateTimer();
        });
}

function checkUpdateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            fetchChannels();
            if (data.some(channel => channel.status === 'Downloading 0%' || channel.status === 'Uploading to VK')) {
                setTimeout(checkUpdateStatus, 5000);  // Проверяем каждые 5 секунд
            } else {
                startUpdateTimer();
            }
        })
        .catch(error => {
            console.error('Error checking update status:', error);
            setTimeout(checkUpdateStatus, 5000);
        });
}

function updateNextUpdateTime() {
    fetch('/api/next-update')
        .then(response => response.json())
        .then(data => {
            const nextUpdate = data.next_update;
            const minutes = Math.floor(nextUpdate / 60);
            const seconds = nextUpdate % 60;
            document.getElementById('nextUpdate').textContent = 
                `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            
            if (nextUpdate > 0) {
                setTimeout(updateNextUpdateTime, 1000);
            } else {
                updateChannels();
            }
        })
        .catch(error => {
            console.error('Error updating next update time:', error);
            setTimeout(updateNextUpdateTime, 5000); // Повторная попытка через 5 секунд
        });
}

function startUpdateTimer() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            let timeLeft = data.nextUpdate;
            updateTimerDisplay(timeLeft);
            
            const timerInterval = setInterval(() => {
                timeLeft--;
                if (timeLeft <= 0) {
                    clearInterval(timerInterval);
                    startUpdateTimer();
                } else {
                    updateTimerDisplay(timeLeft);
                }
            }, 1000);
        });
}

function updateTimerDisplay(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    document.getElementById('nextUpdate').textContent = `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}

// Добавьте эту функцию для инициализации таймера при загрузке страницы
function initializeTimer() {
    startUpdateTimer();
}

// Измените обработчик события DOMContentLoaded
document.addEventListener('DOMContentLoaded', function () {
    fetchChannels();
    loadSettings();
    updateSystemInfo();
    initializeTimer();
});

// Добавьте эти строки в конец файла
document.querySelector('.controls button:nth-child(1)').addEventListener('click', showAddModal);
document.querySelector('.controls button:nth-child(2)').addEventListener('click', showRemoveModal);
document.querySelector('.controls button:nth-child(3)').addEventListener('click', updateChannels);

// Добавьте обработчик события для нового переключателя
document.getElementById('proxyToggle').addEventListener('change', saveSettings);

function changeRecordsPerPage() {
    const recordsPerPage = parseInt(document.getElementById('recordsPerPage').value);
    console.log(`Records per page changed to: ${recordsPerPage}`);
    
    const startIndex = 0;
    const endIndex = Math.min(recordsPerPage, channels.length);
    const visibleChannels = channels.slice(startIndex, endIndex);
    
    populateTable(visibleChannels);
}

function loadSettings() {
    fetch('/api/settings')
        .then(response => response.json())
        .then(data => {
            settings = data; // Сохраняем полученные настройки в глобальную переменную
            document.getElementById('apiYouTube').value = data.apiYouTube || '';
            document.getElementById('apiVK').value = data.apiVK || '';
            document.getElementById('groupId').value = data.groupId || '';
            document.getElementById('parsingTime').value = data.parsingTime || '';
            document.getElementById('tgIdUser').value = data.tgIdUser || '';
            document.getElementById('tgBotToken').value = data.tgBotToken || '';
            document.getElementById('telegramNotification').value = data.telegramNotification || 'off';
            
            document.getElementById('workToggle').checked = data.workToggle || false;
            document.getElementById('downloadToggle').checked = data.downloadToggle || false;
            document.getElementById('uploadToggle').checked = data.uploadToggle || false;
            
            document.getElementById('proxyToggle').checked = data.proxyToggle || false;
        })
        .catch(error => console.error('Error loading settings:', error));
}

function saveSettings() {
    const settings = {
        apiYouTube: document.getElementById('apiYouTube').value,
        apiVK: document.getElementById('apiVK').value,
        groupId: document.getElementById('groupId').value,
        parsingTime: document.getElementById('parsingTime').value,
        tgIdUser: document.getElementById('tgIdUser').value,
        tgBotToken: document.getElementById('tgBotToken').value,
        telegramNotification: document.getElementById('telegramNotification').value,
        
        workToggle: document.getElementById('workToggle').checked,
        downloadToggle: document.getElementById('downloadToggle').checked,
        uploadToggle: document.getElementById('uploadToggle').checked,
        
        proxyToggle: document.getElementById('proxyToggle').checked
    };

    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
    })
    .then(response => response.json())
    .then(data => {
        console.log('Settings saved:', data);
        alert('Settings saved successfully!');
        startUpdateTimer(); // перезапускаем таймер с новым значением
    })
    .catch(error => console.error('Error saving settings:', error));
}

function updateSystemInfo() {
    fetch('/api/system-info')
        .then(response => response.json())
        .then(data => {
            document.getElementById('cpuUsage').textContent = `CPU ${data.cpu}%`;
            document.getElementById('gpuUsage').textContent = `GPU ${data.gpu}%`;
            document.getElementById('ramUsage').textContent = `RAM ${data.ram.toFixed(1)}GB`;
            document.getElementById('romUsage').textContent = `ROM ${data.rom.toFixed(1)}MB`;
        })
        .catch(error => console.error('Error updating system info:', error));
}

// ... существующий код ...

function uploadVideoToVK(videoPath, videoName, channelTitle, settings) {
    // ... существующий код ...
    
    // Получаем длительность видео
    const duration = getVideoDuration(videoPath);
    
    // Определяем, нужно ли загружать как клип
    const isShortVideo = duration < 180; // меньше 3 минут
    
    // Формируем название видео
    const postingTitle = formatPostingTitle(settings.PostingTitle, videoName, channelTitle);
    
    // Загружаем видео
    if (isShortVideo) {
        // Загрузка как клип
        video_info = upload.video(
            video_file=videoPath,
            name=postingTitle,
            group_id=settings['groupId'],
            is_short_video=True
        )
    } else {
        // Загрузка как обычное видео
        video_info = upload.video(
            video_file=videoPath,
            name=postingTitle,
            group_id=settings['groupId']
        )
    }
    
    // ... остальной код ...
}

function formatPostingTitle(template, videoName, channelTitle) {
    return template.replace('@video', videoName).replace('@author', channelTitle);
}

function showTitleSettingsModal() {
    closeModal(); // Закрываем предыдущее модальное окно, если оно открыто
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Настройки заголовка видео</h2>
            <input type="text" id="postingTitleInput" placeholder="Введите шаблон заголовка">
            <p class="hint">@video - оригинальное название видео<br>@author - название канала</p>
            <button onclick="savePostingTitle()">Сохранить</button>
            <button onclick="closeModal()">Назад</button>
        </div>
    `;
    document.body.appendChild(modal);
    
    // Загружаем текущее значение
    document.getElementById('postingTitleInput').value = settings.PostingTitle || '@video';
}

function savePostingTitle() {
    const postingTitle = document.getElementById('postingTitleInput').value;
    settings.PostingTitle = postingTitle;
    
    // Отправляем обновленные настройки на сервер
    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
    })
    .then(response => response.json())
    .then(data => {
        console.log('Settings saved:', data);
        alert('Настройки заголовка сохранены успешно!');
        closeModal();
    })
    .catch(error => {
        console.error('Error saving settings:', error);
        alert('Произошла ошибка при сохранении настроек');
    });
}

// ... существующий код ...

// Добавьте эту функцию в начало файла
function getVideoDuration(videoPath) {
    // Эта функция должна быть реализована на сервере
    // Здесь мы просто отправляем запрос на сервер для получения длительности
    return fetch('/api/video-duration', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ videoPath: videoPath }),
    })
    .then(response => response.json())
    .then(data => data.duration)
    .catch(error => {
        console.error('Error getting video duration:', error);
        return 0;
    });
}

function showTitleSettingsModal() {
    closeModal(); // Закрываем предыдущее модальное окно, если оно открыто
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Настройки заголовка видео</h2>
            <input type="text" id="postingTitleInput" placeholder="Введите шаблон заголовка">
            <p class="hint">@video - оригинальное название видео<br>@author - название канала</p>
            <button onclick="savePostingTitle()">Сохранить</button>
            <button onclick="closeModal()">Назад</button>
        </div>
    `;
    document.body.appendChild(modal);
    
    // Загружаем текущее значение
    document.getElementById('postingTitleInput').value = settings.PostingTitle || '@video';
}

function savePostingTitle() {
    const postingTitle = document.getElementById('postingTitleInput').value;
    settings.PostingTitle = postingTitle;
    saveSettings();
    closeModal();
}










// Обновляем системную информацию каждые 30 секунд вместо 5
setInterval(updateSystemInfo, 30000);

// Добавьте обработчики событий для переключателей
document.getElementById('workToggle').addEventListener('change', saveSettings);
document.getElementById('downloadToggle').addEventListener('change', saveSettings);
document.getElementById('uploadToggle').addEventListener('change', saveSettings);

// Вызовите эту функцию при загрузке страницы
document.addEventListener('DOMContentLoaded', function () {
    startUpdateTimer();
    fetchChannels();
    loadSettings();
    updateSystemInfo();
});

// Добавьте эти строки в конец файла
document.querySelector('.controls button:nth-child(1)').addEventListener('click', showAddModal);
document.querySelector('.controls button:nth-child(2)').addEventListener('click', showRemoveModal);
document.querySelector('.controls button:nth-child(3)').addEventListener('click', updateChannels);

// Добавьте обработчик события для изменения времени парсинга
document.getElementById('parsingTime').addEventListener('change', function() {
    startUpdateTimer();
});

// Добавьте эту функцию для обновления логов
function updateLogs() {
    fetch('/api/logs')
        .then(response => response.text())
        .then(data => {
            const logsArea = document.getElementById('logsArea');
            logsArea.value = data;
            // Прокрутка вниз для отображения последних логов
            logsArea.scrollTop = logsArea.scrollHeight;
        })
        .catch(error => console.error('Error fetching logs:', error));
}

// Обновляем логи каждые 5 секунд
setInterval(updateLogs, 5000);

// Вызываем функцию при загрузке страницы
document.addEventListener('DOMContentLoaded', function () {
    // ... (существующий код) ...
    updateLogs();
});
