# lang.py
LANGUAGES = {
    'window_title': { 'en': 'SpotiDown', 'bg': 'SpotiDown', 'es': 'SpotiDown' },
    'url_label': { 'en': 'URL (Spotify or Apple Music):', 'bg': 'URL (Spotify или Apple Music):', 'es': 'URL (Spotify o Apple Music):' },
    'start_button': { 'en': 'Start Download', 'bg': 'Старт', 'es': 'Iniciar Descarga' },
    'progress_label': { 'en': 'Log:', 'bg': 'Прогрес:', 'es': 'Registro:' },
    'lang_label': { 'en': 'Language:', 'bg': 'Език:', 'es': 'Idioma:' },
    'source_type_label': { 'en': 'Source Type:', 'bg': 'Тип на източника:', 'es': 'Tipo de Fuente:' },
    'download_folder_label': { 'en': 'Download Folder:', 'bg': 'Папка за сваляне:', 'es': 'Carpeta de Descarga:' },
    'browse_button': { 'en': 'Browse...', 'bg': 'Избери...', 'es': 'Explorar...' },
    'keys_prompt_title': { 'en': 'API Keys Required', 'bg': 'Необходими са API Ключове', 'es': 'Se Requieren Claves de API' },
    'keys_prompt_message': {
        'en': 'Please enter your API keys. Genius.com key is optional.',
        'bg': 'Моля, въведете вашите API ключове. Ключът за Genius.com не е задължителен.',
        'es': 'Por favor, ingrese sus claves de API. La clave de Genius.com es opcional.'
    },
    'save_keys_button': { 'en': 'Save and Continue', 'bg': 'Запази и Продължи', 'es': 'Guardar y Continuar' },
    'settings_menu_label': { 'en': 'Settings', 'bg': 'Настройки', 'es': 'Configuración' },
    'settings_menu_change_keys': { 'en': 'Change API Keys', 'bg': 'Смяна на API Ключове', 'es': 'Cambiar Claves de API' },
    'quality_label': { 'en': 'Audio Quality (kbps):', 'bg': 'Качество на звука (kbps):', 'es': 'Calidad de Audio (kbps):' },
    'cancel_button': { 'en': 'Cancel', 'bg': 'Отказ', 'es': 'Cancelar' },
    'cancelling_message': { 'en': 'Cancelling... will stop after the current song.', 'bg': 'Отменя се... ще спре след текущата песен.', 'es': 'Cancelando... se detendrá después de la canción actual.' },
    'downloading_song': { 'en': 'Downloading:', 'bg': 'Сваля се:', 'es': 'Descargando:' },
    'song_done': { 'en': '✓ Done:', 'bg': '✓ Готово:', 'es': '✓ Hecho:' },
    'song_skipped': { 'en': '→ Skipped (file already exists):', 'bg': '→ Пропуснато (файлът вече съществува):', 'es': '→ Omitido (el archivo ya existe):' },
    'process_finished': { 'en': '\n--- Finished! ---', 'bg': '\n--- Процесът приключи! ---', 'es': '\n--- ¡Proceso Terminado! ---' },
    'connecting_spotify': { 'en': 'Connecting to Spotify API...', 'bg': 'Свързване със Spotify API...', 'es': 'Conectando a la API de Spotify...' },
    'connecting_genius': { 'en': 'Connecting to Genius.com API...', 'bg': 'Свързване с Genius.com API...', 'es': 'Conectando a la API de Genius.com...' }
}

def get_string(key, lang_code='en'):
    lang_dict = LANGUAGES.get(key, {})
    return lang_dict.get(lang_code, lang_dict.get('en', f"[{key}]"))