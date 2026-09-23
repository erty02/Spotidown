# downloader.py
import os
import threading
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, USLT, SYLT
import lyricsgenius
from lang import get_string
from artwork import embed_cover, save_id3v23

try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
except ImportError:
    THEFUZZ_AVAILABLE = False

class DownloaderThread(threading.Thread):
    def __init__(self, url_or_payload, download_type, keys, lang, log_callback, finish_callback, download_path, quality, cancel_event):
        super().__init__()
        self.url_or_payload = url_or_payload
        self.download_type = download_type
        self.keys = keys if keys else {}
        self.lang = lang
        self.log = log_callback
        self.on_finish = finish_callback
        self.download_path = download_path
        self.quality = quality
        self.cancel_event = cancel_event
        self.cover_cache = {}
        self.daemon = True

    def run(self):
        try:
            ffmpeg_path = os.path.join(os.getcwd(), 'ffmpeg', 'bin')
            if not os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg.exe')):
                self.log("ERROR: FFmpeg not found."); return
            if not os.path.exists(self.download_path):
                os.makedirs(self.download_path)

            sp, genius = None, None
            if self.keys.get('spotify_id') and self.keys.get('spotify_secret'):
                self.log(get_string('connecting_spotify', self.lang))
                auth_manager = SpotifyClientCredentials(client_id=self.keys['spotify_id'], client_secret=self.keys['spotify_secret'])
                sp = spotipy.Spotify(auth_manager=auth_manager)
            if self.keys.get('genius_token'):
                self.log(get_string('connecting_genius', self.lang))
                try:
                    genius = lyricsgenius.Genius(
                        self.keys['genius_token'], remove_section_headers=True, timeout=15)
                    # Older releases use this attribute; newer ones are silent by default.
                    if hasattr(genius, 'verbose'):
                        genius.verbose = False
                except Exception as genius_error:
                    genius = None
                    self.log(f"WARNING: Lyrics disabled ({type(genius_error).__name__}). Continuing with audio and artwork.")
            
            if self.download_type == 'spotify' and sp:
                self.process_spotify_download(ffmpeg_path, sp, genius)
            elif self.download_type == 'youtube':
                self.process_youtube_download(ffmpeg_path, sp, genius)
            elif self.download_type in ['apple_music', 'deezer']:
                self.process_scraped_download(ffmpeg_path, sp, genius)
            else:
                self.log(f"Could not start download for type '{self.download_type}'. Check source selection and API Keys.")

        except Exception as e:
            self.log(f"CRITICAL ERROR: {type(e).__name__} - {e}")
        finally:
            self.log(get_string('process_finished', self.lang))
            self.on_finish()

    def clean_filename(self, filename):
        return "".join([c for c in filename if c.isalnum() or c in (' ', '-')]).rstrip()

    def download_options(self, mp3_filepath, ffmpeg_path):
        return {
            # Prefer an audio-only stream; use a combined stream only if needed.
            'format': 'bestaudio/best',
            'concurrent_fragment_downloads': 4,
            'postprocessors': [{'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': self.quality}],
            'outtmpl': os.path.splitext(mp3_filepath)[0],
            'default_search': 'ytsearch1:',
            'quiet': True, 'noprogress': True, 'ffmpeg_location': ffmpeg_path,
            'cookiefile': 'youtube-cookies.txt',
        }

    # --- ТВОЯТА РАБОТЕЩА ФУНКЦИЯ ---
    def find_best_spotify_match(self, video_info, sp):
        yt_title = video_info.get('title', '')
        
        # По-добро почистване на заглавието от YouTube
        clean_title = yt_title.lower()
        clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title) # Премахва всичко в скоби
        junk_words = ['official', 'music', 'video', 'audio', 'lyrics', 'lyric', 'hd', '4k', 'hq', 'visualizer', 'explicit']
        pattern = r'\b(' + '|'.join(junk_words) + r')\b'
        clean_title = re.sub(pattern, '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'[^\w\s-]', '', clean_title) # Почиства символи, но запазва тирета
        clean_title = re.sub(r'\s+', ' ', clean_title).strip()
        
        self.log(f"{get_string('yt_cleaned_title', self.lang)} '{clean_title}'")
        if not clean_title: return None, 0

        try:
            results = sp.search(q=clean_title, type='track', limit=10)
            if not results['tracks']['items']: return None, 0

            best_match, best_score = None, 0
            for track in results['tracks']['items']:
                artist_name = track['artists'][0]['name'].lower()
                track_name = track['name'].lower()
                spotify_title = f"{artist_name} {track_name}"
                
                score = fuzz.token_set_ratio(clean_title, spotify_title)
                
                # Бонус, ако каналът в YouTube съвпада с изпълнителя
                channel_name = video_info.get('channel', '').lower()
                if artist_name in channel_name or f"{artist_name}vevo" in channel_name.replace(' ', ''):
                    score = min(score + 10, 100) # Добавяме бонус точки
                
                if score > best_score:
                    best_score, best_match = score, track
            
            return best_match, best_score
        except Exception as e:
            self.log(f"   -> Spotify search error: {e}"); return None, 0
            
    def process_youtube_download(self, ffmpeg_path, sp, genius):
        can_search_metadata = THEFUZZ_AVAILABLE and sp
        if not THEFUZZ_AVAILABLE:
            self.log("WARNING: 'thefuzz' library not found. Metadata search disabled.")

        initial_ydl_opts = {'quiet': True, 'noprogress': True, 'ignoreerrors': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(initial_ydl_opts) as ydl:
            info = ydl.extract_info(self.url_or_payload, download=False)
            if not info:
                self.log(f"Could not retrieve info for URL: {self.url_or_payload}"); return
            
            videos = info.get('entries', [info])
            for video in videos:
                if self.cancel_event.is_set(): break
                if not video: continue
                
                original_title = video.get('title', 'Unknown YouTube Video')
                video_url = video.get('webpage_url', video.get('url'))
                if not video_url:
                    self.log(f"Could not find a valid URL for video: {original_title}. Skipping."); continue
                
                spotify_track_info = None
                if can_search_metadata:
                    self.log(f"{get_string('yt_metadata_search', self.lang)} '{original_title}'")
                    # ИЗПОЛЗВАМЕ ТВОЯТА ФУНКЦИЯ
                    best_match, best_score = self.find_best_spotify_match(video, sp)
                    if best_match and best_score > 75: # Праг на увереност
                        self.log(f"{get_string('yt_metadata_found', self.lang).format(best_score)}")
                        spotify_track_info = best_match

                if spotify_track_info:
                    log_name = f"{spotify_track_info['artists'][0]['name']} - {spotify_track_info['name']}"
                else:
                    if can_search_metadata: self.log(get_string('yt_metadata_not_found', self.lang))
                    log_name = original_title

                safe_filename = self.clean_filename(log_name)
                final_filepath = os.path.join(self.download_path, f"{safe_filename}.mp3")

                if os.path.exists(final_filepath):
                    self.log(f"{get_string('song_skipped', self.lang)} {log_name}"); continue

                self.log(f"{get_string('downloading_song', self.lang)} {log_name}")
                
                download_ydl_opts = self.download_options(final_filepath, ffmpeg_path)
                try:
                    with yt_dlp.YoutubeDL(download_ydl_opts) as download_ydl:
                        download_ydl.download([video_url])
                    
                    self.add_downloaded_metadata(final_filepath, spotify_track_info,
                                                 genius, original_title, "Unknown Artist")
                    
                    self.log(f"{get_string('song_done', self.lang)} {log_name}")
                except Exception as download_error:
                    self.log(f"!! DOWNLOAD ERROR for '{log_name}': {download_error}")
                    if os.path.exists(final_filepath):
                        try: os.remove(final_filepath)
                        except OSError: pass

    def process_scraped_download(self, ffmpeg_path, sp, genius):
        # Тази функция използва по-просто търсене, защото данните от скрейпърите са по-чисти
        tracks_to_process = self.url_or_payload
        self.log(f"Processing {len(tracks_to_process)} tracks from {self.download_type.replace('_', ' ').title()}...")
        
        for track in tracks_to_process:
            if self.cancel_event.is_set(): break
            artist = track.get('artist')
            name = track.get('name')
            if not artist or not name: continue

            log_name = f"{artist} - {name}"
            safe_filename = self.clean_filename(log_name)
            mp3_filepath = os.path.join(self.download_path, f"{safe_filename}.mp3")

            if os.path.exists(mp3_filepath):
                self.log(f"{get_string('song_skipped', self.lang)} {log_name}"); continue

            self.log(f"{get_string('downloading_song', self.lang)} {log_name}")

            spotify_track_info = None
            if sp:
                 # За скрейпнати данни можем да използваме по-директно търсене
                 results = sp.search(q=f"artist:\"{artist}\" track:\"{name}\"", type='track', limit=1)
                 if results['tracks']['items']:
                     spotify_track_info = results['tracks']['items'][0]

            try:
                search_query = f"ytsearch1:{artist} - {name} audio"
                ydl_opts = self.download_options(mp3_filepath, ffmpeg_path)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([search_query])

                self.add_downloaded_metadata(mp3_filepath, spotify_track_info,
                                             genius, name, artist)
                self.log(f"{get_string('song_done', self.lang)} {log_name}")
            except Exception as download_error:
                self.log(f"!! DOWNLOAD ERROR for '{log_name}': {download_error}")
                if os.path.exists(mp3_filepath):
                    try: os.remove(mp3_filepath)
                    except OSError: pass

    def process_spotify_download(self, ffmpeg_path, sp, genius):
        tracks_to_process = []
        url = self.url_or_payload
        if "/playlist/" in url:
            results = sp.playlist_items(url)
            while results:
                for item in results.get('items',[]):
                    if item.get('track'): tracks_to_process.append(item['track'])
                results = sp.next(results) if results.get('next') else None
        elif "/track/" in url:
            tracks_to_process.append(sp.track(url))
        self.log(get_string('found_tracks', self.lang).format(len(tracks_to_process)))
        for track in tracks_to_process:
            if self.cancel_event.is_set(): break
            if not track or not track.get('id') or track.get('type', 'track') != 'track': continue
            log_name = f"{track['artists'][0]['name']} - {track['name']}"
            safe_filename = self.clean_filename(log_name)
            mp3_filepath = os.path.join(self.download_path, f"{safe_filename}.mp3")
            if os.path.exists(mp3_filepath):
                self.log(f"Updating tags and cover (audio already exists): {log_name}")
                try:
                    self.add_metadata(mp3_filepath, track, None)
                    self.log(f"{get_string('song_done', self.lang)} {log_name}")
                except Exception as metadata_error:
                    self.log(f"!! METADATA ERROR for '{log_name}' (existing file kept): {metadata_error}")
                continue
            try:
                self.log(f"{get_string('downloading_song', self.lang)} {log_name}")
                search_query = f"{track['artists'][0]['name']} - {track['name']} audio"
                ydl_opts = self.download_options(mp3_filepath, ffmpeg_path)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([search_query])
                self.add_downloaded_metadata(mp3_filepath, track, genius)
                self.log(f"{get_string('song_done', self.lang)} {log_name}")
            except Exception as download_error:
                self.log(f"!! DOWNLOAD ERROR for '{log_name}': {download_error}")
                if os.path.exists(mp3_filepath):
                    try: os.remove(mp3_filepath)
                    except OSError: pass
    
    def add_downloaded_metadata(self, mp3_filepath, track, genius,
                                name="", artist=""):
        # Tagging failures must not fall into the download-error cleanup.
        try:
            if track:
                self.add_metadata(mp3_filepath, track, genius)
            else:
                self.add_basic_metadata(mp3_filepath, name, artist)
        except Exception as metadata_error:
            self.log(f"   -> WARNING: Audio kept, but metadata could not be saved: {metadata_error}")

    def add_metadata(self, mp3_filepath, track, genius):
        audio = MP3(mp3_filepath, ID3=ID3)
        if audio.tags is None: audio.add_tags()
        original_track_name = track['name']
        artist_name = track['artists'][0]['name']
        album_name = track['album']['name']
        audio.tags.add(TIT2(encoding=1, text=original_track_name))
        audio.tags.add(TPE1(encoding=1, text=' / '.join(a['name'] for a in track['artists'])))
        audio.tags.add(TALB(encoding=1, text=album_name))
        album_artists = track['album'].get('artists') or track['artists']
        audio.tags.add(TPE2(encoding=1, text=' / '.join(a['name'] for a in album_artists)))
        if track.get('track_number'):
            audio.tags.add(TRCK(encoding=1, text=str(track['track_number'])))
        if track.get('disc_number'):
            audio.tags.add(TPOS(encoding=1, text=str(track['disc_number'])))
        if track['album'].get('release_date'):
            audio.tags.add(TDRC(encoding=1, text=track['album']['release_date']))
        has_cover = embed_cover(audio.tags, track, self.log, cache=self.cover_cache)
        if genius:
            try:
                song = genius.search_song(original_track_name, artist_name, get_full_info=False)
                if song and song.lyrics:
                    cleaned_lyrics = song.lyrics.strip()
                    if cleaned_lyrics:
                        audio.tags.add(USLT(encoding=1, lang='eng', desc='Lyrics', text=cleaned_lyrics))
                        audio.tags.add(SYLT(encoding=1, lang='eng', format=2, type=1, desc='Lyrics', text=[(cleaned_lyrics, 0)]))
                else: self.log(f"   -> INFO: Lyrics not found on Genius.com.")
            except Exception as lyrics_error: self.log(f"   -> INFO: Error fetching lyrics: {lyrics_error}")
        save_id3v23(audio, mp3_filepath)
        if has_cover:
            self.log("   -> Cover embedded: JPEG, up to 600 x 600, ID3v2.3 (iTunes / iPod).")

    def add_basic_metadata(self, mp3_filepath, name, artist):
        # ... (тази функция не се променя)
        audio = MP3(mp3_filepath, ID3=ID3)
        if audio.tags is None: audio.add_tags()
        audio.tags.add(TIT2(encoding=1, text=name))
        audio.tags.add(TPE1(encoding=1, text=artist))
        save_id3v23(audio, mp3_filepath)
