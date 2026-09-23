"""Optional Genius integration must never prevent audio/artwork processing."""

import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import lyricsgenius

from downloader import DownloaderThread


class DownloaderStartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.logs = []
        self.finish = Mock()
        self.worker = DownloaderThread(
            'https://open.spotify.com/playlist/test', 'spotify',
            {'spotify_id': 'test-id', 'spotify_secret': 'test-secret',
             'genius_token': 'test-token'},
            'en', self.logs.append, self.finish, self.folder.name, '192',
            threading.Event())
        # No external requests: exercise startup with the installed Genius client,
        # but replace Spotify credentials, playlist processing and FFmpeg lookup.
        for target in ('downloader.SpotifyClientCredentials',
                       'downloader.spotipy.Spotify', 'downloader.os.path.exists'):
            patcher = patch(target, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.process = Mock()
        self.worker.process_spotify_download = self.process

    def test_installed_genius_initializes_and_playlist_processing_starts(self):
        with patch('requests.sessions.Session.request',
                   side_effect=AssertionError('Startup must not use the network')):
            self.worker.run()
        self.process.assert_called_once()
        genius = self.process.call_args.args[2]
        self.assertIsInstance(genius, lyricsgenius.Genius)
        self.assertTrue(genius.remove_section_headers)
        self.assertEqual(genius.timeout, 15)
        self.finish.assert_called_once()
        self.assertFalse(any('CRITICAL ERROR' in message for message in self.logs))

    def test_genius_failure_does_not_abort_playlist(self):
        with patch('downloader.lyricsgenius.Genius', side_effect=TypeError('API changed')):
            self.worker.run()
        self.process.assert_called_once()
        self.assertIsNone(self.process.call_args.args[2])
        self.assertTrue(any('Lyrics disabled' in message for message in self.logs))
        self.finish.assert_called_once()

    def test_no_token_skips_genius_and_processes_playlist(self):
        self.worker.keys.pop('genius_token')
        with patch('downloader.lyricsgenius.Genius') as constructor:
            self.worker.run()
        constructor.assert_not_called()
        self.process.assert_called_once()
        self.assertIsNone(self.process.call_args.args[2])
        self.finish.assert_called_once()

    def test_older_genius_verbose_attribute_is_disabled(self):
        client = Mock(verbose=True)
        with patch('downloader.lyricsgenius.Genius', return_value=client):
            self.worker.run()
        self.assertFalse(client.verbose)
        self.process.assert_called_once()


if __name__ == '__main__':
    unittest.main()
