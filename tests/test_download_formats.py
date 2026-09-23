import tempfile
import threading
import unittest
from unittest.mock import Mock

import yt_dlp

from downloader import DownloaderThread


class DownloadFormatTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.worker = DownloaderThread('', 'spotify', {}, 'en', Mock(), Mock(),
                                       self.folder.name, '320', threading.Event())

    def select(self, formats):
        options = self.worker.download_options('song.mp3', 'ffmpeg/bin')
        # Evaluate yt-dlp's real format selection without cookies or network access.
        options.update(cookiefile=None, skip_download=True, no_warnings=True)
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.process_ie_result({
                'id': 'test', 'title': 'Test', 'extractor': 'test',
                'webpage_url': 'https://example.test/song', 'formats': formats,
            }, download=False)

    def test_prefers_best_audio_without_fetching_video(self):
        result = self.select([
            {'format_id': 'audio-low', 'url': 'https://example.test/low.m4a',
             'ext': 'm4a', 'acodec': 'aac', 'vcodec': 'none', 'abr': 64},
            {'format_id': 'audio-high', 'url': 'https://example.test/high.m4a',
             'ext': 'm4a', 'acodec': 'aac', 'vcodec': 'none', 'abr': 192},
            {'format_id': 'video', 'url': 'https://example.test/video.mp4',
             'ext': 'mp4', 'acodec': 'none', 'vcodec': 'h264', 'height': 2160},
            {'format_id': 'combined', 'url': 'https://example.test/both.mp4',
             'ext': 'mp4', 'acodec': 'aac', 'vcodec': 'h264', 'height': 720},
        ])
        self.assertEqual(result['format_id'], 'audio-high')
        self.assertEqual(result['vcodec'], 'none')
        self.assertNotIn('requested_formats', result)

    def test_combined_stream_is_fallback_when_no_audio_only_stream_exists(self):
        result = self.select([
            {'format_id': 'combined', 'url': 'https://example.test/both.mp4',
             'ext': 'mp4', 'acodec': 'aac', 'vcodec': 'h264', 'height': 720},
        ])
        self.assertEqual(result['format_id'], 'combined')

    def test_selected_mp3_bitrate_is_preserved(self):
        for quality in ('128', '192', '256', '320'):
            self.worker.quality = quality
            options = self.worker.download_options('song.mp3', 'ffmpeg/bin')
            processor = options['postprocessors'][0]
            self.assertEqual(processor['preferredcodec'], 'mp3')
            self.assertEqual(processor['preferredquality'], quality)


if __name__ == '__main__':
    unittest.main()
