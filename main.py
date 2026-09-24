import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path

from downloader import DownloaderThread
from lang import get_string

CONFIG_FILE = 'config.json'
LANGUAGE_NAMES = {'Русский': 'ru', 'English': 'en', 'Български': 'bg', 'Español': 'es'}


def context_menu(entry, lang):
    menu = tk.Menu(entry, tearoff=0)
    for key, event in [('cut', '<<Cut>>'), ('copy', '<<Copy>>'), ('paste', '<<Paste>>')]:
        menu.add_command(label=get_string(key, lang), command=lambda value=event: entry.event_generate(value))
    entry.bind('<Button-3>', lambda event: menu.tk_popup(event.x_root, event.y_root))


class ApiKeysPrompt(tk.Toplevel):
    def __init__(self, parent, lang, current_keys=None):
        super().__init__(parent)
        self.keys = None
        self.lang = lang
        self.title(get_string('keys_prompt_title', lang))
        self.transient(parent)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=get_string('keys_prompt_message', lang), wraplength=440).pack(anchor='w', pady=(0, 16))
        self.variables = {}
        for key, title in [('spotify_id', 'Spotify Client ID'), ('spotify_secret', 'Spotify Client Secret'), ('genius_token', 'Genius Access Token')]:
            ttk.Label(frame, text=title).pack(anchor='w', pady=(8, 4))
            variable = tk.StringVar(value=(current_keys or {}).get(key, ''))
            entry = ttk.Entry(frame, textvariable=variable, width=55, show='*' if key != 'spotify_id' else '')
            entry.pack(fill='x')
            context_menu(entry, lang)
            self.variables[key] = variable
        ttk.Button(frame, text=get_string('save_keys_button', lang), style='Accent.TButton', command=self.save).pack(anchor='e', pady=(24, 0))
        self.grab_set()
        self.wait_window()

    def save(self):
        self.keys = {key: value.get().strip() for key, value in self.variables.items()}
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.running = False
        self.closing = False
        self.report = None
        self.report_text = ''
        self.labels = []
        self.app_config = self.load_config()
        self.current_lang = self.app_config.get('language', 'ru')
        if self.current_lang not in LANGUAGE_NAMES.values():
            self.current_lang = 'ru'
        self.setup_ui()
        self.update_language()
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self._pump = self.after(80, self.drain_events)

    def tr(self, key, **values):
        return get_string(key, self.current_lang).format(**values)

    def load_config(self):
        defaults = dict(api_keys={}, download_path='downloads', quality='192', source_type='Spotify', language='ru', lyrics_enabled=False)
        try:
            config = json.loads(Path(CONFIG_FILE).read_text(encoding='utf-8-sig'))
            if isinstance(config, dict):
                defaults.update(config)
        except (OSError, ValueError):
            pass
        return defaults

    def save_config(self):
        try:
            Path(CONFIG_FILE).write_text(json.dumps(self.app_config, ensure_ascii=False, indent=4), encoding='utf-8')
        except OSError as error:
            messagebox.showerror(self.tr('error'), str(error), parent=self)

    def label(self, parent, key, **kwargs):
        widget = ttk.Label(parent, **kwargs)
        self.labels.append((widget, key))
        return widget

    def setup_ui(self):
        self.title('SpotiDown')
        self.geometry('850x790')
        self.minsize(740, 700)
        self.configure(background='#edf1f7')
        self.option_add('*Font', ('Segoe UI', 10))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#ffffff', foreground='#172b4d')
        style.configure('TFrame', background='#ffffff')
        style.configure('TButton', padding=(12, 5))
        style.configure('Accent.TButton', background='#176b50', foreground='white', font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('disabled', '#a6b8b2'), ('active', '#125640')])
        style.configure('TEntry', padding=7, fieldbackground='#f7f9fc')
        style.configure('TCombobox', padding=6)
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Muted.TLabel', foreground='#586881')
        style.configure('Status.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Horizontal.TProgressbar', background='#208665', troughcolor='#e5ebf2', borderwidth=0)
        root = ttk.Frame(self, padding=16)
        root.pack(fill='both', expand=True, padx=8, pady=8)
        header = ttk.Frame(root)
        header.pack(fill='x')
        ttk.Label(header, text='SpotiDown', style='Title.TLabel').pack(side='left')
        self.settings_button = ttk.Button(header, command=self.prompt_for_keys)
        self.settings_button.pack(side='right')
        self.label(root, 'subtitle', style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        row = ttk.Frame(root)
        row.pack(fill='x')
        self.label(row, 'source_type_label').pack(side='left', padx=(0, 8))
        self.source_type_var = tk.StringVar(value=self.app_config['source_type'])
        self.source_type_combo = ttk.Combobox(row, textvariable=self.source_type_var, values=['Spotify', 'YouTube', 'Apple Music', 'Deezer'], state='readonly', width=16)
        self.source_type_combo.pack(side='left')
        self.lang_var = tk.StringVar(value=next(name for name, code in LANGUAGE_NAMES.items() if code == self.current_lang))
        self.lang_combo = ttk.Combobox(row, textvariable=self.lang_var, values=list(LANGUAGE_NAMES), state='readonly', width=12)
        self.lang_combo.pack(side='right')
        self.lang_combo.bind('<<ComboboxSelected>>', self.on_lang_change)
        self.label(row, 'lang_label').pack(side='right', padx=8)
        self.label(root, 'url_label').pack(anchor='w', pady=(8, 3))
        self.url_entry = ttk.Entry(root)
        self.url_entry.pack(fill='x')
        self.label(root, 'download_folder_label').pack(anchor='w', pady=(8, 3))
        folder = ttk.Frame(root)
        folder.pack(fill='x')
        self.download_path_var = tk.StringVar(value=self.app_config['download_path'])
        self.folder_entry = ttk.Entry(folder, textvariable=self.download_path_var, state='readonly')
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.browse_button = ttk.Button(folder, command=self.browse_folder)
        self.browse_button.pack(side='right', padx=(8, 0))
        options = ttk.Frame(root)
        options.pack(fill='x', pady=8)
        self.label(options, 'quality_label').pack(side='left', padx=(0, 8))
        self.quality_var = tk.StringVar(value=self.app_config['quality'])
        self.quality_combo = ttk.Combobox(options, textvariable=self.quality_var, values=['128', '192', '256', '320'], width=6, state='readonly')
        self.quality_combo.pack(side='left')
        self.lyrics_var = tk.BooleanVar(value=self.app_config['lyrics_enabled'])
        self.lyrics_check = ttk.Checkbutton(options, variable=self.lyrics_var)
        self.lyrics_check.pack(side='right')
        self.label(root, 'strict_hint', style='Muted.TLabel', wraplength=760).pack(anchor='w')
        self.label(root, 'existing_hint', style='Muted.TLabel', wraplength=760).pack(anchor='w', pady=(4, 8))
        actions = ttk.Frame(root)
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, style='Accent.TButton', command=self.start_download)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(actions, command=self.cancel_download, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        self.save_report_button = ttk.Button(actions, command=self.save_report, state='disabled')
        self.save_report_button.pack(side='right')
        ttk.Separator(root).pack(fill='x', pady=10)
        self.status_var = tk.StringVar()
        ttk.Label(root, textvariable=self.status_var, style='Status.TLabel').pack(anchor='w')
        self.track_var = tk.StringVar()
        self.track_label = ttk.Label(root, textvariable=self.track_var, style='Muted.TLabel', wraplength=760)
        self.track_label.pack(anchor='w', pady=(4, 4))
        self.track_progress = ttk.Progressbar(root, maximum=100)
        self.track_progress.pack(fill='x')
        self.transfer_var = tk.StringVar(value='—')
        ttk.Label(root, textvariable=self.transfer_var, style='Muted.TLabel').pack(anchor='e', pady=(3, 6))
        self.count_var = tk.StringVar()
        ttk.Label(root, textvariable=self.count_var).pack(anchor='w')
        self.overall_progress = ttk.Progressbar(root, maximum=100)
        self.overall_progress.pack(fill='x', pady=(5, 10))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        self.progress_text = scrolledtext.ScrolledText(self.notebook, height=5, state='disabled', wrap='word', relief='flat', font=('Segoe UI', 10), background='#f7f9fc', foreground='#172b4d')
        self.issues_text = scrolledtext.ScrolledText(self.notebook, height=5, state='disabled', wrap='word', relief='flat', font=('Segoe UI', 10), background='#fff9f2', foreground='#653d20')
        self.notebook.add(self.progress_text)
        self.notebook.add(self.issues_text)
        self.bind('<Configure>', self.on_resize)

    def on_resize(self, event):
        if event.widget is self:
            for widget, key in self.labels:
                if key in ('strict_hint', 'existing_hint'):
                    widget.configure(wraplength=max(400, event.width - 90))
            self.track_label.configure(wraplength=max(400, event.width - 90))

    def update_language(self):
        for widget, key in self.labels:
            widget.configure(text=self.tr(key))
        for widget, key in [(self.settings_button, 'settings_menu_change_keys'), (self.browse_button, 'browse_button'), (self.start_button, 'start_button'), (self.cancel_button, 'cancel_button'), (self.save_report_button, 'save_report'), (self.lyrics_check, 'lyrics_option')]:
            widget.configure(text=self.tr(key))
        self.notebook.tab(0, text=self.tr('progress_label'))
        self.notebook.tab(1, text=self.tr('issues_tab'))
        context_menu(self.url_entry, self.current_lang)
        if self.report:
            self.show_report(self.report)
        elif not self.running:
            self.status_var.set(self.tr('ready'))
            self.count_var.set(self.tr('count_progress', completed=0, total=0))
            self.set_text(self.issues_text, self.tr('empty_report'))

    def on_lang_change(self, event=None):
        self.current_lang = LANGUAGE_NAMES[self.lang_var.get()]
        self.app_config['language'] = self.current_lang
        self.save_config()
        self.update_language()

    def set_busy(self, busy):
        self.running = busy
        for widget in (self.start_button, self.settings_button, self.browse_button, self.lyrics_check, self.url_entry):
            widget.configure(state='disabled' if busy else 'normal')
        for widget in (self.lang_combo, self.source_type_combo, self.quality_combo):
            widget.configure(state='disabled' if busy else 'readonly')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        self.save_report_button.configure(state='normal' if self.report and not busy else 'disabled')

    def start_download(self):
        if self.running:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showinfo('SpotiDown', self.tr('enter_url'), parent=self)
            return
        keys = self.app_config.get('api_keys') or {}
        if self.source_type_var.get() == 'Spotify' and not (keys.get('spotify_id') and keys.get('spotify_secret')):
            self.prompt_for_keys()
            keys = self.app_config.get('api_keys') or {}
            if not (keys.get('spotify_id') and keys.get('spotify_secret')):
                return
        self.app_config.update(source_type=self.source_type_var.get(), quality=self.quality_var.get(), lyrics_enabled=self.lyrics_var.get())
        self.save_config()
        self.cancel_event.clear()
        self.report = None
        self.set_busy(True)
        self.set_text(self.progress_text, '')
        self.set_text(self.issues_text, self.tr('empty_report'))
        self.notebook.tab(1, text=self.tr('issues_tab'))
        self.notebook.select(0)
        self.overall_progress['value'] = 0
        self.worker = DownloaderThread(
            url, self.source_type_var.get().lower().replace(' ', '_'), keys,
            self.current_lang, lambda message: self.events.put(('log', message)),
            lambda: self.events.put(('finish', None)), self.download_path_var.get(),
            self.quality_var.get(), self.cancel_event,
            progress_callback=lambda data: self.events.put(('progress', data)),
            report_callback=lambda data: self.events.put(('report', data)),
            lyrics_enabled=self.lyrics_var.get())
        self.worker.start()

    def drain_events(self):
        # Every widget update happens on the Tk thread, including after cancellation.
        if self._pump:
            self.after_cancel(self._pump)
            self._pump = None
        for _ in range(500):
            try:
                event, data = self.events.get_nowait()
            except queue.Empty:
                break
            if event == 'log':
                self.log_message(data)
            elif event == 'progress':
                self.show_progress(data)
            elif event == 'report':
                self.show_report(data)
            elif event == 'finish':
                self.track_progress.stop()
                self.set_busy(False)
                if self.closing:
                    self.destroy()
                    return
        self._pump = self.after(80, self.drain_events)

    def destroy(self):
        if getattr(self, '_pump', None):
            self.after_cancel(self._pump)
            self._pump = None
        super().destroy()

    def show_progress(self, data):
        self.status_var.set(self.tr(data['stage']))
        self.track_var.set(data.get('track', ''))
        self.count_var.set(self.tr('count_progress', **data))
        self.overall_progress['value'] = 100 * data['completed'] / data['total'] if data['total'] else 0
        percent = data.get('percent')
        self.track_progress.stop()
        self.track_progress.configure(mode='indeterminate' if percent is None else 'determinate')
        if percent is None:
            self.track_progress.start(20)
        else:
            self.track_progress['value'] = percent
        transfer = f'{percent:.0f}%' if percent is not None else '—'
        if data.get('speed') is not None and data.get('eta') is not None:
            transfer += ' · ' + self.tr('speed_eta', speed=data['speed'] / 1048576, eta=int(data['eta']))
        self.transfer_var.set(transfer)

    def show_report(self, report):
        self.report = report
        self.track_progress.stop()
        state = 'cancelled' if report['cancelled'] else ('finished_issues' if report['issues'] else 'finished')
        self.status_var.set(self.tr(state))
        self.track_var.set(self.tr('summary', **report))
        self.count_var.set(self.tr('count_progress', **report))
        self.transfer_var.set('—')
        self.track_progress.configure(mode='determinate', value=0)
        lines = [self.tr(state), self.tr('summary', **report), self.tr('count_progress', **report), '']
        for item in report['issues']:
            lines.append(f"{self.tr(item['severity'])} · {item['track']}\n{self.tr(item['stage'])}: {item['message']}\n")
        if not report['issues']:
            lines.append(self.tr('no_issues'))
        self.report_text = '\n'.join(lines)
        self.set_text(self.issues_text, self.report_text)
        self.notebook.tab(1, text=f"{self.tr('issues_tab')} ({len(report['issues'])})")
        self.notebook.select(1)

    def set_text(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('end', text)
        widget.configure(state='disabled')

    def log_message(self, message):
        self.progress_text.configure(state='normal')
        self.progress_text.insert('end', message + '\n')
        self.progress_text.see('end')
        self.progress_text.configure(state='disabled')

    def save_report(self):
        path = filedialog.asksaveasfilename(parent=self, title=self.tr('save_report'), initialfile='SpotiDown-report.txt', defaultextension='.txt', filetypes=[(self.tr('report_file'), '*.txt')])
        if path:
            try:
                Path(path).write_text(self.report_text, encoding='utf-8-sig')
            except OSError as error:
                messagebox.showerror(self.tr('error'), str(error), parent=self)

    def prompt_for_keys(self):
        prompt = ApiKeysPrompt(self, self.current_lang, self.app_config.get('api_keys'))
        if prompt.keys is not None:
            self.app_config['api_keys'] = prompt.keys
            self.save_config()

    def browse_folder(self):
        folder = filedialog.askdirectory(parent=self)
        if folder:
            self.download_path_var.set(folder)
            self.app_config['download_path'] = folder
            self.save_config()

    def cancel_download(self):
        self.cancel_event.set()
        self.status_var.set(self.tr('cancelling_message'))
        self.cancel_button.configure(state='disabled')

    def close_app(self):
        if self.running:
            if messagebox.askyesno('SpotiDown', self.tr('close_running'), parent=self):
                self.closing = True
                self.cancel_download()
        else:
            self.destroy()


if __name__ == '__main__':
    import traceback
    app_dir = Path(__file__).resolve().parent
    os.chdir(app_dir)
    try:
        app = App()
        app.mainloop()
    except Exception:
        error_log = app_dir / 'startup-error.log'
        error_log.write_text(traceback.format_exc(), encoding='utf-8')
        try:
            messagebox.showerror('SpotiDown', f'Не удалось запустить / Could not start SpotiDown. {error_log}')
        except Exception:
            pass
        raise
