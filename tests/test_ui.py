"""Tk integration smoke tests; no network and no personal config writes."""
import threading
import unittest
from unittest.mock import patch
from lang import LANGUAGES, MESSAGES


class LanguageTests(unittest.TestCase):
    def test_every_new_message_has_english_and_russian(self):
        import string
        for key in MESSAGES:
            en, ru = LANGUAGES[key]['en'], LANGUAGES[key]['ru']
            self.assertTrue(en and ru, key)
            fields = lambda text: {name for _, name, _, _ in string.Formatter().parse(text) if name}
            self.assertEqual(fields(en), fields(ru), key)


class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from main import App
        config = dict(api_keys={}, download_path='downloads', quality='192', source_type='Spotify', language='ru', lyrics_enabled=False)
        try:
            with patch.object(App, 'load_config', return_value=config):
                self.app = App()
        except tk.TclError as error:
            self.skipTest(f'Tk display not available: {error}')
        self.addCleanup(self.app.destroy)
        self.app.update_idletasks()

    def test_russian_layout_and_minimum_size(self):
        self.assertEqual(self.app.start_button['text'], 'Скачать музыку')
        for width, height in [(850, 790), (740, 700)]:
            self.app.geometry(f'{width}x{height}')
            self.app.update()
            self.assertGreater(self.app.notebook.winfo_height(), 65)
            self.assertLessEqual(self.app.notebook.winfo_rooty() + self.app.notebook.winfo_height(),
                                 self.app.winfo_rooty() + self.app.winfo_height())

    def test_worker_event_queue_renders_report_and_reenables_controls(self):
        stats = dict(total=3, completed=2, downloaded=1, updated=0, skipped=0, failed=1)
        report = dict(**stats, cancelled=True, issues=[dict(track='Песня', stage='searching', severity='error', message='Не найден оригинал')])
        self.app.set_busy(True)
        def worker():
            self.app.events.put(('progress', dict(**stats, stage='downloading', track='Песня', percent=25, speed=1048576, eta=5)))
            self.app.events.put(('report', report))
            self.app.events.put(('finish', None))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.app.drain_events()
        self.assertFalse(self.app.running)
        self.assertEqual(self.app.status_var.get(), 'Остановлено')
        self.assertIn('Не найден оригинал', self.app.issues_text.get('1.0', 'end'))
        self.assertEqual(str(self.app.save_report_button['state']), 'normal')
        self.assertAlmostEqual(float(self.app.overall_progress['value']), 200/3)

    def test_language_switch_preserves_url_and_saves_preference(self):
        self.app.url_entry.insert(0, 'https://open.spotify.com/track/test')
        self.app.lang_var.set('English')
        with patch.object(self.app, 'save_config') as save:
            self.app.on_lang_change()
        save.assert_called_once()
        self.assertEqual(self.app.app_config['language'], 'en')
        self.assertEqual(self.app.start_button['text'], 'Download music')
        self.assertEqual(self.app.url_entry.get(), 'https://open.spotify.com/track/test')


if __name__ == '__main__':
    unittest.main()
