# deezer_scraper.py
import requests
from bs4 import BeautifulSoup
import time

class DeezerScraper:
    """
    Финален скрейпър, който използва най-стабилния метод за всеки тип страница:
    - За Албуми: Събира track URL-ове от meta тагове и ги обхожда.
    - За Плейлисти: Директен HTML анализ на таблица.
    - За Песни: Директен анализ на meta тагове.
    """

    def get_playlist_tracks(self, url):
        """
        Основен метод. Приема URL и го насочва към правилната стратегия за скрейпинг.
        """
        clean_url = url.split('?')[0]
        print(f"--- Стартиране на Deezer скрейпър за: {clean_url} ---")

        try:
            soup = self._get_soup(clean_url)
            if not soup:
                return None # Връщаме None при мрежова грешка

            # --- Насочване според типа на URL ---
            if '/track/' in clean_url:
                print("[INFO] URL на песен -> Изпълнява се директен метод...")
                track = self._scrape_single_track_from_meta(soup, clean_url)
                return [track] if track else []

            elif '/album/' in clean_url:
                print("[INFO] URL на албум -> Изпълнява се двустепенният META метод...")
                return self._scrape_album_via_track_links(soup)

            elif '/playlist/' in clean_url:
                print("[INFO] URL на плейлист -> Изпълнява се HTML табличен метод...")
                return self._scrape_playlist_table(soup)

            else:
                print(f"URL type not recognized: {clean_url}")
                return []

        except Exception as e:
            print(f"An unexpected error occurred in DeezerScraper: {e}")
            return None

    def _get_soup(self, url):
        """Помощна функция за взимане и парсване на HTML съдържание."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,bg;q=0.8',
        }
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            print(f"Network error while fetching {url}: {e}")
            return None

    def _scrape_single_track_from_meta(self, soup, url):
        """Извлича данни за единична песен от нейните meta тагове."""
        print(f"    -> Извличане на данни от {url}")
        og_title_tag = soup.find('meta', property='og:title')
        og_desc_tag = soup.find('meta', property='og:description')
        if og_title_tag and og_desc_tag:
            title = og_title_tag.get('content')
            artist = og_desc_tag.get('content').split(' - ')[0]
            if title and artist:
                return {'name': title.strip(), 'artist': artist.strip()}
        print(f"    [ГРЕШКА] Не са намерени meta тагове за {url}")
        return None

    def _scrape_album_via_track_links(self, soup):
        """
        Извлича песните от албум, като първо събира линковете на всяка песен
        от 'music:song' meta таговете и след това ги обхожда.
        """
        song_meta_tags = soup.find_all('meta', property='music:song')
        track_urls = [tag.get('content') for tag in song_meta_tags if tag.get('content')]
        
        if not track_urls:
            print("[ГРЕШКА] Не са намерени 'music:song' meta тагове на страницата на албума.")
            return []

        print(f"[INFO] Намерени {len(track_urls)} линка към песни. Започва обхождане...")
        
        all_tracks = []
        for i, track_url in enumerate(track_urls):
            try:
                # Правим малка пауза, за да не претоварим сървъра
                time.sleep(0.1) 
                track_soup = self._get_soup(track_url)
                if track_soup:
                    track_info = self._scrape_single_track_from_meta(track_soup, track_url)
                    if track_info:
                        all_tracks.append(track_info)
                print(f"    ({i+1}/{len(track_urls)}) Готово.")
            except Exception as e:
                print(f"    [ГРЕШКА] Проблем при извличане на {track_url}: {e}")
        
        return all_tracks

    def _scrape_playlist_table(self, soup):
        """
        Извлича песните от плейлист чрез директно четене на HTML таблицата.
        """
        tracklist_container = soup.find('div', id='tab_tracks_content')
        if not tracklist_container:
            print("HTML container 'div#tab_tracks_content' not found for playlist.")
            return []

        song_rows = tracklist_container.find_all('tr', class_='song')
        if not song_rows:
            print("No tracks with class 'song' found within the container.")
            return []

        tracks_found = []
        for row in song_rows:
            song_el = row.find('span', attrs={'itemprop': 'name'})
            artist_el = row.find('a', attrs={'itemprop': 'byArtist'})
            if song_el and artist_el:
                tracks_found.append({
                    'name': song_el.get_text(strip=True),
                    'artist': artist_el.get_text(strip=True)
                })

        print(f"Found {len(tracks_found)} tracks in HTML table.")
        return tracks_found