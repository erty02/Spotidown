# apple_music_scraper.py
import requests
import re
import time

class AppleMusicScraper:
    """
    This is the definitive scraper, built on the user's successful debug script.
    - For albums/singles, it uses the fast iTunes API directly.
    - For playlists, it uses the user's precise HTML regex scraping method.
    """
    def get_playlist_tracks(self, url):
        print("--- Running Final Hybrid Scraper (API + HTML Regex) ---")

        # --- МЕТОД 1: За Албуми и Единични Песни ---
        if "/album/" in url or "/song/" in url:
            print("Album/Single Track URL detected. Using iTunes API.")
            tracks = self._get_tracks_from_itunes_api(url)
            return tracks if tracks else []

        # --- МЕТОД 2: За Плейлисти (твоят метод) ---
        elif "/playlist/" in url:
            print("Playlist URL detected. Using direct HTML scraping...")
            return self._get_playlist_tracks_from_html(url)
            
        else:
            print("URL type not recognized.")
            return None

    def _get_tracks_from_itunes_api(self, url):
        """
        Взима URL на песен/албум и връща чиста информация от iTunes API.
        """
        match = re.search(r'/(\d+)', url)
        if not match: return None
        item_id = match.group(1)
        
        is_single_track = "?i=" in url

        try:
            api_url = f"https://itunes.apple.com/lookup?id={item_id}&entity=song"
            response = requests.get(api_url, timeout=15).json()
            results = response.get('results', [])
            
            if not results: return None

            # Ако е единична песен, намираме я по нейното ID
            if is_single_track:
                single_track_id_match = re.search(r'i=(\d+)', url)
                if not single_track_id_match: return None
                
                single_track_id = int(single_track_id_match.group(1))
                for item in results:
                    if item.get('trackId') == single_track_id:
                        # Връщаме списък с един елемент, за консистентност
                        return [{'name': item['trackName'].strip(), 'artist': item['artistName'].strip()}]
                return None
            
            # Ако е албум, връщаме всички песни
            return [{'name': item['trackName'].strip(), 'artist': item['artistName'].strip()}
                    for item in results if item.get('wrapperType') == 'track']

        except Exception:
            return None

    def _get_playlist_tracks_from_html(self, url):
        """
        Имплементира твоя метод с "не-лаком" regex.
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        try:
            print("Fetching playlist HTML...")
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            html_content = response.text
            
            print("Searching for song blocks in HTML...")
            pattern = re.compile(r'(\{\"id\":\"track-lockup.*?\"subtitleLinks\":\[.*?\])')
            item_blocks = pattern.findall(html_content)
            
            if not item_blocks:
                print("ERROR: No song blocks ('track-lockup') found in HTML.")
                return []
            
            tracks_found = []
            seen = set()
            for block in item_blocks:
                title_match = re.search(r'\"title\":\"([^\"]+)\"', block)
                artist_match = re.search(r'\"subtitleLinks\":\[\{\"title\":\"([^\"]+)\"', block)
                
                if title_match and artist_match:
                    song_title = title_match.group(1)
                    artist_name = artist_match.group(1)
                    
                    identifier = (song_title, artist_name)
                    if identifier not in seen:
                        seen.add(identifier)
                        tracks_found.append({'name': song_title, 'artist': artist_name})

            print(f"Finished scraping. Found {len(tracks_found)} unique tracks.")
            return tracks_found

        except Exception as e:
            print(f"An error occurred during playlist scraping: {e}")
            return None