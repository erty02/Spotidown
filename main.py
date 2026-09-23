# main.py
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import os
import threading
from lang import get_string
from downloader import DownloaderThread
from apple_music_scraper import AppleMusicScraper
from deezer_scraper import DeezerScraper 

CONFIG_FILE = 'config.json'

class ApiKeysPrompt(tk.Toplevel):
    # ... (съдържанието на този клас не се променя) ...
    def __init__(self, parent, lang, current_keys=None):
        super().__init__(parent)
        self.lang = lang
        self.keys = None
        self.transient(parent)
        self.title(get_string('keys_prompt_title', self.lang))
        self.geometry("500x420")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.grab_set()
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text=get_string('keys_prompt_message', self.lang), wraplength=480).pack(pady=10)
        
        self.spotify_id_var = tk.StringVar()
        self.spotify_secret_var = tk.StringVar()
        self.genius_token_var = tk.StringVar()
    

        if current_keys:
            self.spotify_id_var.set(current_keys.get('spotify_id', ''))
            self.spotify_secret_var.set(current_keys.get('spotify_secret', ''))
            self.genius_token_var.set(current_keys.get('genius_token', ''))
          

        self.entries = []
        ttk.Label(main_frame, text="Spotify Client ID:").pack(anchor=tk.W, padx=10)
        spotify_id_entry = ttk.Entry(main_frame, textvariable=self.spotify_id_var, width=70)
        spotify_id_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.entries.append(spotify_id_entry)
        
        ttk.Label(main_frame, text="Spotify Client Secret:").pack(anchor=tk.W, padx=10)
        spotify_secret_entry = ttk.Entry(main_frame, textvariable=self.spotify_secret_var, width=70)
        spotify_secret_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.entries.append(spotify_secret_entry)
        
        ttk.Label(main_frame, text="Genius.com Access Token:").pack(anchor=tk.W, padx=10)
        genius_token_entry = ttk.Entry(main_frame, textvariable=self.genius_token_var, width=70)
        genius_token_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.entries.append(genius_token_entry)

        
        
        ttk.Button(main_frame, text=get_string('save_keys_button', self.lang), command=self.save).pack(pady=20)
        self.make_context_menu()
        self.wait_window(self)

    def make_context_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cut", command=lambda: self.focus_get().event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self.focus_get().event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self.focus_get().event_generate("<<Paste>>"))
        for entry in self.entries:
            entry.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def save(self):
        self.keys = {
            'spotify_id': self.spotify_id_var.get().strip(), 
            'spotify_secret': self.spotify_secret_var.get().strip(), 
            'genius_token': self.genius_token_var.get().strip(),
            
            }
        if self.keys['spotify_id'] and self.keys['spotify_secret']: self.destroy()
        else: messagebox.showwarning("Warning", "Spotify Client ID and Secret are required.", parent=self)

    def on_closing(self):
        self.keys = None; self.destroy()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()
        self.current_lang = 'en'
        self.app_config = self.load_config()
        self.setup_ui()
        self.update_language()
        if not self.app_config.get('api_keys') or not self.app_config['api_keys'].get('spotify_id'):
            self.prompt_for_keys()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    config.setdefault('quality', '192')
                    config.setdefault('source_type', 'Spotify')
                    return config
            except (json.JSONDecodeError, AttributeError): pass
        return {'api_keys': None, 'download_path': 'downloads', 'quality': '192', 'source_type': 'Spotify'}

    def save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.app_config, f, indent=4, ensure_ascii=False)

    def setup_ui(self):
        self.title(get_string('window_title', self.current_lang))
        self.geometry("600x500")
        self.minsize(500, 450)
        self.config(menu=self.create_menubar())
        
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        lang_frame = ttk.Frame(main_frame)
        lang_frame.pack(fill=tk.X, pady=(0, 10))
        self.lang_label = ttk.Label(lang_frame, text=get_string('lang_label', self.current_lang))
        self.lang_label.pack(side=tk.LEFT, padx=(0, 5))
        self.lang_var = tk.StringVar(value='English')
        self.lang_combo = ttk.Combobox(lang_frame, textvariable=self.lang_var, values=['English', 'Български', 'Español'], state='readonly')
        self.lang_combo.pack(side=tk.LEFT)
        self.lang_combo.bind('<<ComboboxSelected>>', self.on_lang_change)
        
        source_type_frame = ttk.Frame(main_frame)
        source_type_frame.pack(fill=tk.X, pady=5)
        self.source_type_label = ttk.Label(source_type_frame, text="Source Type:")
        self.source_type_label.pack(side=tk.LEFT, anchor=tk.W)
        self.source_type_var = tk.StringVar(value=self.app_config.get('source_type'))
        
        self.source_type_combo = ttk.Combobox(source_type_frame, textvariable=self.source_type_var, values=['Spotify', 'YouTube', 'Apple Music', 'Deezer'], state='readonly')
        self.source_type_combo.pack(side=tk.LEFT, padx=5)
        self.source_type_combo.bind('<<ComboboxSelected>>', self.on_source_type_change)

        self.url_label = ttk.Label(main_frame, text=get_string('url_label', self.current_lang))
        self.url_label.pack(anchor=tk.W)
        self.url_entry = ttk.Entry(main_frame, width=70)
        self.url_entry.pack(fill=tk.X, pady=5)
        self.make_context_menu_for_entry(self.url_entry)
        
        folder_frame = ttk.Frame(main_frame)
        folder_frame.pack(fill=tk.X, pady=5)
        self.folder_label = ttk.Label(folder_frame, text=get_string('download_folder_label', self.current_lang))
        self.folder_label.pack(side=tk.LEFT, anchor=tk.W)
        self.download_path_var = tk.StringVar(value=self.app_config.get('download_path', 'downloads'))
        folder_entry = ttk.Entry(folder_frame, textvariable=self.download_path_var, state='readonly')
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.browse_button = ttk.Button(folder_frame, text=get_string('browse_button', self.current_lang), command=self.browse_folder)
        self.browse_button.pack(side=tk.LEFT)

        quality_frame = ttk.Frame(main_frame)
        quality_frame.pack(fill=tk.X, pady=5)
        self.quality_label = ttk.Label(quality_frame, text="Audio Quality:")
        self.quality_label.pack(side=tk.LEFT, anchor=tk.W)
        self.quality_var = tk.StringVar(value=self.app_config.get('quality', '192'))
        self.quality_combo = ttk.Combobox(quality_frame, textvariable=self.quality_var, values=['128', '192', '256', '320'], state='readonly', width=10)
        self.quality_combo.pack(side=tk.LEFT, padx=5)
        self.quality_combo.bind('<<ComboboxSelected>>', self.on_quality_change)
        
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(pady=10)
        self.start_button = ttk.Button(buttons_frame, text=get_string('start_button', self.current_lang), command=self.start_download)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.cancel_button = ttk.Button(buttons_frame, text=get_string('cancel_button', self.current_lang), command=self.cancel_download, state='disabled')
        self.cancel_button.pack(side=tk.LEFT, padx=5)

        self.progress_label = ttk.Label(main_frame, text=get_string('progress_label', self.current_lang))
        self.progress_label.pack(anchor=tk.W)
        self.progress_text = scrolledtext.ScrolledText(main_frame, height=15, state='disabled', wrap=tk.WORD)
        self.progress_text.pack(fill=tk.BOTH, expand=True, pady=(5,0))
    
    def start_download(self):
        url = self.url_entry.get()
        source_type = self.source_type_var.get()
        if not url: return

        if source_type == 'Spotify' and (not self.app_config.get('api_keys') or not self.app_config['api_keys'].get('spotify_id')):
            messagebox.showerror("Error", "Spotify API Keys are required for this source."); return

        self.cancel_event.clear()
        self.start_button.config(state='disabled'); self.cancel_button.config(state='normal')
        self.progress_text.config(state='normal'); self.progress_text.delete(1.0, tk.END); self.progress_text.config(state='disabled')
        
        download_payload = url
        
        tracks = None
        if source_type == 'Apple Music':
            scraper = AppleMusicScraper()
            tracks = scraper.get_playlist_tracks(url)
        elif source_type == 'Deezer':
            scraper = DeezerScraper()
            tracks = scraper.get_playlist_tracks(url)

        if tracks is not None:
            if not tracks: 
                self.log_message(f"No tracks found on the {source_type} page.")
                self.on_download_finish()
                return
            download_payload = tracks
        elif source_type in ['Apple Music', 'Deezer']:
            self.log_message(f"Failed to scrape {source_type} page. Please check URL and connection.")
            self.on_download_finish()
            return
        
        downloader = DownloaderThread(
            url_or_payload=download_payload, 
            download_type=source_type.lower().replace(' ', '_'),
            keys=self.app_config.get('api_keys'), 
            lang=self.current_lang,
            log_callback=self.log_message, 
            finish_callback=self.on_download_finish,
            download_path=self.download_path_var.get(), 
            quality=self.app_config.get('quality', '192'),
            cancel_event=self.cancel_event
        )
        downloader.start()

    def on_download_finish(self):
        self.start_button.config(state='normal'); self.cancel_button.config(state='disabled')

    def prompt_for_keys(self):
        prompt = ApiKeysPrompt(self, self.current_lang, self.app_config.get('api_keys'))
        if prompt.keys:
            self.app_config['api_keys'] = prompt.keys; self.save_config()
            messagebox.showinfo("Success", "API Keys saved successfully!", parent=self)
        elif not self.app_config.get('api_keys') or not self.app_config['api_keys'].get('spotify_id'):
            self.destroy()

    def on_source_type_change(self, event=None):
        self.app_config['source_type'] = self.source_type_var.get(); self.save_config()
    def on_quality_change(self, event=None):
        self.app_config['quality'] = self.quality_var.get(); self.save_config()
    def cancel_download(self):
        self.log_message(get_string('cancelling_message', self.current_lang)); self.cancel_event.set(); self.cancel_button.config(state='disabled')
    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.download_path_var.set(folder); self.app_config['download_path'] = folder; self.save_config()
    def on_lang_change(self, event=None):
        self.current_lang = {'English': 'en', 'Български': 'bg', 'Español': 'es'}[self.lang_var.get()]; self.update_language()
    def make_context_menu_for_entry(self, entry):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
        entry.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))

    def update_language(self):
        self.title(get_string('window_title', self.current_lang))
        self.lang_label.config(text=get_string('lang_label', self.current_lang))
        self.source_type_label.config(text=get_string('source_type_label', self.current_lang))
        self.url_label.config(text=get_string('url_label', self.current_lang))
        self.start_button.config(text=get_string('start_button', self.current_lang))
        self.progress_label.config(text=get_string('progress_label', self.current_lang))
        self.folder_label.config(text=get_string('download_folder_label', self.current_lang))
        self.browse_button.config(text=get_string('browse_button', self.current_lang))
        self.quality_label.config(text=get_string('quality_label', self.current_lang))
        self.cancel_button.config(text=get_string('cancel_button', self.current_lang))
        self.winfo_toplevel().config(menu=self.create_menubar())

    def create_menubar(self):
        menubar = tk.Menu(self)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label=get_string('settings_menu_change_keys', self.current_lang), command=self.prompt_for_keys)
        menubar.add_cascade(label=get_string('settings_menu_label', self.current_lang), menu=settings_menu)
        return menubar
        
    def log_message(self, message):
        self.progress_text.config(state='normal'); self.progress_text.insert(tk.END, message + "\n")
        self.progress_text.see(tk.END); self.progress_text.config(state='disabled'); self.update_idletasks()

if __name__ == "__main__":
    # pythonw has no console; preserve startup errors instead of silently closing.
    import traceback
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent
    os.chdir(app_dir)
    try:
        app = App()
        app.mainloop()
    except Exception:
        error_log = app_dir / 'startup-error.log'
        error_log.write_text(traceback.format_exc(), encoding='utf-8')
        try:
            messagebox.showerror('SpotiDown', f'Could not start SpotiDown. Details: {error_log}')
        except Exception:
            pass
        raise
