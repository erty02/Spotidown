"""Background download jobs. Callbacks pass data; only the UI thread touches Tk."""
import os
import re
import threading
import time
import tempfile
from collections import Counter
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import lyricsgenius
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, USLT
from artwork import embed_cover, save_id3v23
from lang import get_string
from matching import score_candidate, normalize


class Cancelled(Exception):
    pass


class DownloaderThread(threading.Thread):
    def __init__(self, url_or_payload, download_type, keys, lang, log_callback,
                 finish_callback, download_path, quality, cancel_event,
                 progress_callback=None, report_callback=None, lyrics_enabled=True):
        super().__init__(daemon=True)
        self.url_or_payload, self.download_type = url_or_payload, download_type
        self.keys, self.lang = keys or {}, lang
        self.log, self.on_finish = log_callback, finish_callback
        self.download_path, self.quality = download_path, quality
        self.cancel_event = cancel_event
        self.on_progress = progress_callback or (lambda event: None)
        self.on_report = report_callback or (lambda report: None)
        self.lyrics_enabled = lyrics_enabled
        self.cover_cache = {}
        self.issues = []
        self.stats = dict(total=0, completed=0, downloaded=0, updated=0, skipped=0, failed=0)
        self.current_track = ''
        self.stage = 'reading'
        self.last_progress = 0
        self.summary = None

    def tr(self, key, **values):
        return get_string(key, self.lang).format(**values)

    def safe_message(self, message):
        text = str(message)
        for value in self.keys.values():
            if isinstance(value, str) and value:
                text = text.replace(value, '[redacted]')
        return re.sub(r'\x1b\[[0-9;]*m', '', text)

    def issue(self, message, severity='error', stage=None):
        item = dict(track=self.current_track or self.tr('job'), stage=stage or self.stage,
                    severity=severity, message=self.safe_message(message))
        if item not in self.issues:
            self.issues.append(item)
            self.log(f"{self.tr(severity)} · {item['track']}: {item['message']}")

    def debug(self, message):
        pass

    def warning(self, message):
        self.issue(message, 'warning')

    def error(self, message):
        self.issue(message)

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def progress(self, stage, **data):
        self.stage = stage
        self.on_progress(dict(stage=stage, track=self.current_track, **self.stats, **data))

    def progress_hook(self, data):
        self.check_cancel()
        if data.get('status') == 'finished':
            self.progress('converting', percent=None)
            return
        if data.get('status') != 'downloading':
            return
        now = time.monotonic()
        if now - self.last_progress < .15:
            return
        self.last_progress = now
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        percent = min(100, data.get('downloaded_bytes', 0) / total * 100) if total else None
        self.progress('downloading', percent=percent, speed=data.get('speed'), eta=data.get('eta'))

    def postprocessor_hook(self, data):
        self.check_cancel()
        self.progress('converting', percent=None)

    def run(self):
        try:
            self.progress('reading', percent=None)
            self.check_cancel()
            ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg', 'bin')
            if not os.path.exists(os.path.join(ffmpeg_path, 'ffmpeg.exe')):
                raise RuntimeError(self.tr('ffmpeg_missing'))
            os.makedirs(self.download_path, exist_ok=True)
            sp, genius = None, None
            if self.keys.get('spotify_id') and self.keys.get('spotify_secret'):
                self.log(self.tr('connecting_spotify'))
                auth = SpotifyClientCredentials(client_id=self.keys['spotify_id'], client_secret=self.keys['spotify_secret'])
                sp = spotipy.Spotify(auth_manager=auth, requests_timeout=15, retries=2)
            if self.keys.get('genius_token') and self.lyrics_enabled:
                try:
                    genius = lyricsgenius.Genius(self.keys['genius_token'], remove_section_headers=True, timeout=15)
                    if hasattr(genius, 'verbose'):
                        genius.verbose = False
                except Exception as error:
                    self.issue(self.tr('lyrics_disabled', error=type(error).__name__), 'warning', 'lyrics')
            if self.download_type == 'spotify':
                if not sp:
                    raise ValueError(self.tr('keys_required'))
                self.process_spotify_download(ffmpeg_path, sp, genius)
            elif self.download_type == 'youtube':
                self.process_youtube_download(ffmpeg_path, sp, genius)
            elif self.download_type in ('apple_music', 'deezer'):
                self.process_scraped_download(ffmpeg_path, sp, genius)
            else:
                raise ValueError(self.tr('invalid_source'))
        except Cancelled:
            pass
        except Exception as error:
            if not self.cancel_event.is_set():
                self.issue(f'{type(error).__name__}: {error}')
        finally:
            self.summary = dict(**self.stats, cancelled=self.cancel_event.is_set(), issues=list(self.issues))
            self.log(self.tr('cancelled' if self.summary['cancelled'] else 'finished'))
            self.log(self.tr('summary', **self.stats))
            self.log(self.tr('issue_count', count=len(self.issues)))
            for item in self.issues:
                self.log(f"{self.tr(item['severity'])} | {item['track']} | {self.tr(item['stage'])}: {item['message']}")
            self.on_report(self.summary)
            self.on_finish()

    def clean_filename(self, filename):
        name = ''.join(c for c in filename if c.isalnum() or c in (' ', '-')).strip()[:170].rstrip()
        return name or 'Track'

    def network_options(self):
        options = dict(quiet=True, noprogress=True, logger=self, socket_timeout=15,
                       retries=2, extractor_retries=2, noplaylist=True)
        if os.path.isfile('youtube-cookies.txt'):
            options['cookiefile'] = 'youtube-cookies.txt'
        return options

    def download_options(self, mp3_filepath, ffmpeg_path):
        return dict(self.network_options(), **{
            'format': 'bestaudio/best', 'concurrent_fragment_downloads': 4,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': self.quality}],
            'outtmpl': os.path.splitext(mp3_filepath)[0].replace('%', '%%') + '.%(ext)s',
            'ffmpeg_location': ffmpeg_path, 'progress_hooks': [self.progress_hook],
            'postprocessor_hooks': [self.postprocessor_hook],
        })

    def select_audio(self, track):
        self.progress('searching', percent=None)
        self.check_cancel()
        if not track.get('duration_ms'):
            raise ValueError(self.tr('match_duration_missing'))
        query = f"{track['artists'][0]['name']} - {track['name']} official audio"
        rejected = Counter()
        with yt_dlp.YoutubeDL(dict(self.network_options(), extract_flat=True)) as search:
            found = search.extract_info('ytsearch8:' + query, download=False) or {}
        candidates = []
        for video in found.get('entries') or []:
            if not video:
                continue
            score, reason = score_candidate(track, video)
            # Details can establish auto-generated audio omitted in flat results.
            if score or reason in ('match_source', 'match_duration_missing', 'match_metadata'):
                candidates.append((score, video))
            else:
                rejected[reason] += 1
        with yt_dlp.YoutubeDL(self.network_options()) as detail:
            for _, video in sorted(candidates, key=lambda pair: pair[0], reverse=True):
                self.check_cancel()
                url = video.get('webpage_url') or video.get('url')
                if not url:
                    continue
                try:
                    info = detail.extract_info(url, download=False)
                except Exception as error:
                    self.check_cancel()
                    self.issue(self.tr('candidate_failed', error=error), 'warning')
                    continue
                score, reason = score_candidate(track, info or {})
                if score:
                    self.log(self.tr('selected', title=info['title'], channel=info.get('channel', ''), duration=info['duration']))
                    return info.get('webpage_url') or url
                rejected[reason] += 1
        reasons = '; '.join(f'{self.tr(reason)} ({count})' for reason, count in rejected.items())
        raise ValueError(self.tr('no_match') + (' ' + reasons if reasons else ''))

    def download_audio(self, url, path, ffmpeg_path):
        # Publish only a finished, readable MP3. Failed/cancelled jobs cannot
        # become "existing files" that are silently reused on the next run.
        with tempfile.TemporaryDirectory(prefix='.spotidown-download-', dir=self.download_path) as folder:
            staged = os.path.join(folder, 'audio.mp3')
            with yt_dlp.YoutubeDL(self.download_options(staged, ffmpeg_path)) as ydl:
                if ydl.download([url]):
                    raise RuntimeError(self.tr('download_failed'))
            self.check_cancel()
            if not os.path.isfile(staged) or MP3(staged).info.length <= 0:
                raise RuntimeError(self.tr('download_failed'))
            os.replace(staged, path)

    def process_spotify_download(self, ffmpeg_path, sp, genius):
        tracks = []
        url = self.url_or_payload
        if '/playlist/' in url or url.startswith('spotify:playlist:'):
            result = sp.playlist_items(url)
            while result:
                self.check_cancel()
                tracks.extend(item.get('track') for item in result.get('items', []) if item)
                result = sp.next(result) if result.get('next') else None
        elif '/track/' in url or url.startswith('spotify:track:'):
            tracks.append(sp.track(url))
        else:
            raise ValueError(self.tr('spotify_url'))
        self.process_tracks(tracks, ffmpeg_path, genius)

    def process_tracks(self, tracks, ffmpeg_path, genius):
        self.stats['total'] = len(tracks)
        if not tracks:
            raise ValueError(self.tr('no_tracks'))
        for index, track in enumerate(tracks, 1):
            self.check_cancel()
            self.current_track = self.tr('track_number', number=index)
            self.progress('searching', percent=None)
            try:
                if not track or track.get('is_local') or track.get('type', 'track') != 'track' or not track.get('artists'):
                    raise ValueError(self.tr('unavailable_track'))
                self.current_track = f"{track['artists'][0]['name']} - {track['name']}"
                path = os.path.join(self.download_path, self.clean_filename(self.current_track) + '.mp3')
                if os.path.exists(path):
                    self.progress('metadata', percent=None)
                    self.log(self.tr('existing_audio'))
                    self.add_metadata(path, track, None)
                    self.stats['updated'] += 1
                else:
                    url = self.select_audio(track)
                    self.check_cancel()
                    self.progress('downloading', percent=0)
                    self.download_audio(url, path, ffmpeg_path)
                    self.progress('metadata', percent=None)
                    self.add_downloaded_metadata(path, track, genius)
                    self.stats['downloaded'] += 1
                self.log(self.tr('song_done') + ' ' + self.current_track)
            except Cancelled:
                raise
            except Exception as error:
                self.check_cancel()
                self.stats['failed'] += 1
                self.issue(error)
            self.stats['completed'] += 1
            self.progress('track_finished', percent=100)

    def process_scraped_download(self, ffmpeg_path, sp, genius):
        tracks = self.url_or_payload
        if isinstance(tracks, str):
            if self.download_type == 'apple_music':
                from apple_music_scraper import AppleMusicScraper
                tracks = AppleMusicScraper().get_playlist_tracks(tracks)
            else:
                from deezer_scraper import DeezerScraper
                tracks = DeezerScraper().get_playlist_tracks(tracks)
        resolved = []
        for item in tracks or []:
            self.check_cancel()
            track = dict(name=item.get('name', ''), artists=[{'name': item.get('artist', '')}],
                         duration_ms=item.get('duration_ms'), album={'name': '', 'images': []})
            if sp:
                try:
                    results = sp.search(q=f"artist:\"{item.get('artist', '')}\" track:\"{item.get('name', '')}\"", type='track', limit=5)
                    for candidate in results['tracks']['items']:
                        if normalize(candidate['name']) == normalize(track['name']) and any(
                                normalize(a['name']) == normalize(item.get('artist')) for a in candidate['artists']):
                            track = candidate
                            break
                except Exception as error:
                    self.current_track = f"{item.get('artist')} - {item.get('name')}"
                    self.issue(error, 'warning', 'reading')
            resolved.append(track)
        self.process_tracks(resolved, ffmpeg_path, genius)

    def find_best_spotify_match(self, video_info, sp):
        try:
            results = sp.search(q=video_info.get('title', ''), type='track', limit=5)
            scored = [(score_candidate(track, video_info)[0], track)
                      for track in results['tracks']['items']]
            score, track = max(scored, key=lambda pair: pair[0], default=(0, None))
            return (track, score) if score else (None, 0)
        except Exception as error:
            self.issue(error, 'warning', 'metadata')
            return None, 0

    def process_youtube_download(self, ffmpeg_path, sp, genius):
        self.issue(self.tr('direct_youtube'), 'warning', 'reading')
        with yt_dlp.YoutubeDL(dict(self.network_options(), noplaylist=False, extract_flat=True)) as ydl:
            info = ydl.extract_info(self.url_or_payload, download=False) or {}
        videos = list(info.get('entries', [info]))
        self.stats['total'] = len(videos)
        for index, video in enumerate(videos, 1):
            self.check_cancel()
            self.current_track = (video or {}).get('title') or self.tr('track_number', number=index)
            self.progress('downloading', percent=0)
            try:
                url = (video or {}).get('webpage_url') or (video or {}).get('url')
                if not url:
                    raise ValueError(self.tr('unavailable_track'))
                spotify_track = self.find_best_spotify_match(video, sp)[0] if sp else None
                if spotify_track:
                    self.current_track = f"{spotify_track['artists'][0]['name']} - {spotify_track['name']}"
                path = os.path.join(self.download_path, self.clean_filename(self.current_track) + '.mp3')
                if os.path.exists(path):
                    self.stats['skipped'] += 1
                else:
                    self.download_audio(url, path, ffmpeg_path)
                    self.progress('metadata', percent=None)
                    self.add_downloaded_metadata(path, spotify_track, genius, self.current_track, video.get('channel', ''))
                    self.stats['downloaded'] += 1
            except Cancelled:
                raise
            except Exception as error:
                self.check_cancel()
                self.stats['failed'] += 1
                self.issue(error)
            self.stats['completed'] += 1
            self.progress('track_finished', percent=100)

    def add_downloaded_metadata(self, mp3_filepath, track, genius, name='', artist=''):
        try:
            if track:
                self.add_metadata(mp3_filepath, track, genius)
            else:
                self.add_basic_metadata(mp3_filepath, name, artist)
        except Exception as error:
            self.issue(self.tr('metadata_kept', error=error), 'warning', 'metadata')

    def cover_log(self, message):
        if 'No usable cover' in message:
            self.issue(self.tr('no_cover'), 'warning', 'artwork')
        else:
            self.issue(self.tr('cover_error', error=message.split(': ', 1)[-1]), 'warning', 'artwork')

    def add_metadata(self, mp3_filepath, track, genius):
        audio = MP3(mp3_filepath, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        album = track.get('album') or {}
        audio.tags.add(TIT2(encoding=1, text=track['name']))
        audio.tags.add(TPE1(encoding=1, text=' / '.join(a['name'] for a in track['artists'])))
        audio.tags.add(TALB(encoding=1, text=album.get('name', '')))
        audio.tags.add(TPE2(encoding=1, text=' / '.join(a['name'] for a in album.get('artists') or track['artists'])))
        if track.get('track_number'):
            audio.tags.add(TRCK(encoding=1, text=str(track['track_number'])))
        if track.get('disc_number'):
            audio.tags.add(TPOS(encoding=1, text=str(track['disc_number'])))
        if album.get('release_date'):
            audio.tags.add(TDRC(encoding=1, text=album['release_date']))
        has_cover = embed_cover(audio.tags, track, self.cover_log, cache=self.cover_cache)
        if genius:
            try:
                song = genius.search_song(track['name'], track['artists'][0]['name'], get_full_info=False)
                if song and song.lyrics and song.lyrics.strip():
                    audio.tags.add(USLT(encoding=1, lang='eng', desc='Lyrics', text=song.lyrics.strip()))
                else:
                    self.issue(self.tr('no_lyrics'), 'warning', 'lyrics')
            except Exception as error:
                self.issue(self.tr('lyrics_error', error=error), 'warning', 'lyrics')
        save_id3v23(audio, mp3_filepath)
        if has_cover:
            self.log(self.tr('cover_done'))

    def add_basic_metadata(self, mp3_filepath, name, artist):
        audio = MP3(mp3_filepath, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TIT2(encoding=1, text=name))
        audio.tags.add(TPE1(encoding=1, text=artist))
        save_id3v23(audio, mp3_filepath)
