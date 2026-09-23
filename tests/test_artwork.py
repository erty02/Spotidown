import copy
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from mutagen.id3 import APIC, ID3
from mutagen.mp3 import MP3
import requests

from artwork import embed_cover, fetch_cover, prepare_cover
from downloader import DownloaderThread


ROOT = Path(__file__).resolve().parents[1]
TRACK = {
    "id": "test-track", "type": "track", "name": "Песня", "track_number": 2,
    "disc_number": 1, "artists": [{"name": "Исполнитель"}],
    "album": {"name": "Альбом", "release_date": "2024-01-02",
              "artists": [{"name": "Исполнитель"}],
              "images": [{"url": "https://example.test/cover"}]},
}


def image_bytes(mode="RGBA", size=(1200, 800), fmt="PNG", **kwargs):
    output = BytesIO()
    Image.new(mode, size).save(output, format=fmt, **kwargs)
    return output.getvalue()


def response_for(data):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [data]
    return response


class CoverTests(unittest.TestCase):
    def test_transparent_png_becomes_small_baseline_rgb_jpeg(self):
        with Image.open(BytesIO(prepare_cover(image_bytes()))) as cover:
            self.assertEqual((cover.format, cover.mode, cover.size),
                             ("JPEG", "RGB", (600, 400)))
            self.assertFalse(cover.info.get("progressive"))
            self.assertEqual(cover.getpixel((10, 10)), (255, 255, 255))

    def test_progressive_and_cmyk_jpeg_are_normalized(self):
        for mode in ("RGB", "CMYK"):
            with self.subTest(mode=mode):
                data = image_bytes(mode, (640, 640), "JPEG", progressive=True)
                with Image.open(BytesIO(prepare_cover(data))) as cover:
                    self.assertEqual(cover.mode, "RGB")
                    self.assertEqual(cover.size, (600, 600))
                    self.assertFalse(cover.info.get("progressive"))

    def test_small_cover_is_not_enlarged(self):
        with Image.open(BytesIO(prepare_cover(image_bytes(size=(100, 100))))) as cover:
            self.assertEqual(cover.size, (100, 100))

    def test_invalid_image_is_rejected(self):
        with self.assertRaises(OSError):
            prepare_cover(b"<html>error page</html>")

    def test_download_size_is_bounded(self):
        with patch("artwork.MAX_DOWNLOAD_BYTES", 4), patch(
                "artwork.requests.get", return_value=response_for(b"12345")):
            with self.assertRaises(ValueError):
                fetch_cover("https://example.test/cover")

    def test_http_error_is_not_embedded(self):
        response = response_for(b"not a cover")
        response.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("artwork.requests.get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                fetch_cover("https://example.test/cover")

    def test_next_spotify_image_used_when_first_fails(self):
        track = copy.deepcopy(TRACK)
        track["album"]["images"].append({"url": "https://example.test/backup"})
        tags = ID3()
        with patch("artwork.requests.get", side_effect=[
                requests.Timeout(), response_for(image_bytes())]) as get:
            self.assertTrue(embed_cover(tags, track, Mock()))
        self.assertEqual(get.call_count, 2)
        self.assertEqual(tags.getall("APIC")[0].mime, "image/jpeg")

    def test_failed_download_uses_existing_front_cover(self):
        tags = ID3()
        tags.add(APIC(type=4, desc="back", data=b"invalid"))
        tags.add(APIC(type=3, desc="front", data=image_bytes(size=(80, 80))))
        with patch("artwork.requests.get", side_effect=requests.Timeout()):
            self.assertTrue(embed_cover(tags, TRACK, Mock()))
        self.assertEqual(len(tags.getall("APIC")), 1)
        with Image.open(BytesIO(tags.getall("APIC")[0].data)) as cover:
            self.assertEqual(cover.size, (80, 80))


class MP3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "source.mp3"
        cls.ffmpeg = ROOT / "ffmpeg" / "bin" / "ffmpeg.exe"
        if not cls.ffmpeg.exists():
            cls.ffmpeg = shutil.which("ffmpeg")
        if not cls.ffmpeg:
            cls.temp.cleanup()
            raise unittest.SkipTest("FFmpeg is needed to generate the test MP3")
        subprocess.run([str(cls.ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.3", "-c:a", "libmp3lame",
                        "-b:a", "192k", str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.file = self.folder / "Исполнитель - Песня.mp3"
        shutil.copyfile(self.source, self.file)
        self.logs = []
        self.worker = DownloaderThread(
            "https://open.spotify.com/playlist/test", "spotify", {}, "en",
            self.logs.append, Mock(), str(self.folder), "192", threading.Event())

    def pcm(self):
        return subprocess.check_output([
            str(self.ffmpeg), "-v", "error", "-i", str(self.file),
            "-map", "0:a:0", "-f", "s16le", "-"])

    def test_round_trip_tags_cover_and_audio_with_independent_decoder(self):
        audio_before = self.pcm()
        with patch("artwork.requests.get", return_value=response_for(image_bytes())):
            self.worker.add_metadata(str(self.file), TRACK, None)
            self.worker.add_metadata(str(self.file), TRACK, None)
        tags = ID3(self.file)
        self.assertEqual(tags.version, (2, 3, 0))
        self.assertEqual(str(tags["TIT2"]), "Песня")
        self.assertEqual(str(tags["TPE2"]), "Исполнитель")
        self.assertEqual(str(tags["TALB"]), "Альбом")
        self.assertEqual(tags["TIT2"].encoding, 1)
        self.assertEqual(str(tags["TDRC"]), "2024-01-02")
        self.assertEqual(len(tags.getall("APIC")), 1)
        picture = tags.getall("APIC")[0]
        self.assertEqual((picture.mime, picture.type), ("image/jpeg", 3))
        with Image.open(BytesIO(picture.data)) as cover:
            self.assertEqual(cover.format, "JPEG")
        self.assertEqual(self.pcm(), audio_before)
        self.assertGreater(MP3(self.file).info.length, 0)

    def test_rerunning_playlist_repairs_existing_file_without_downloading(self):
        spotify = Mock()
        spotify.playlist_items.return_value = {"items": [{"track": TRACK}], "next": None}
        with patch("downloader.yt_dlp.YoutubeDL") as youtube, patch(
                "artwork.requests.get", return_value=response_for(image_bytes())):
            self.worker.process_spotify_download(str(self.ffmpeg.parent), spotify, None)
        youtube.assert_not_called()
        self.assertEqual(len(ID3(self.file).getall("APIC")), 1)

    def test_new_download_gets_artwork(self):
        self.file.unlink()
        spotify = Mock()
        spotify.playlist_items.return_value = {"items": [{"track": TRACK}], "next": None}
        with patch("downloader.yt_dlp.YoutubeDL") as youtube, patch(
                "artwork.requests.get", return_value=response_for(image_bytes())):
            youtube.return_value.__enter__.return_value.download.side_effect = (
                lambda urls: shutil.copyfile(self.source, self.file))
            self.worker.process_spotify_download(str(self.ffmpeg.parent), spotify, None)
        self.assertEqual(len(ID3(self.file).getall("APIC")), 1)
        self.assertEqual(ID3(self.file).version, (2, 3, 0))

    def test_failed_save_keeps_original_bytes_and_cleans_temporary_copy(self):
        original = self.file.read_bytes()
        with patch("artwork.requests.get", return_value=response_for(image_bytes())), patch(
                "artwork.os.replace", side_effect=PermissionError("file is locked")):
            with self.assertRaises(PermissionError):
                self.worker.add_metadata(str(self.file), TRACK, None)
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(list(self.folder.glob(".spotidown-*")), [])

    def test_new_audio_survives_tagging_failure(self):
        self.file.unlink()
        spotify = Mock()
        spotify.playlist_items.return_value = {"items": [{"track": TRACK}], "next": None}
        with patch("downloader.yt_dlp.YoutubeDL") as youtube, patch.object(
                self.worker, "add_metadata", side_effect=OSError("cannot write tags")):
            youtube.return_value.__enter__.return_value.download.side_effect = (
                lambda urls: shutil.copyfile(self.source, self.file))
            self.worker.process_spotify_download(str(self.ffmpeg.parent), spotify, None)
        self.assertEqual(self.file.read_bytes(), self.source.read_bytes())
        self.assertTrue(any("Audio kept" in message for message in self.logs))

    def test_missing_art_keeps_audio_and_reports_warning(self):
        track = copy.deepcopy(TRACK)
        track["album"].pop("images")
        audio_before = self.pcm()
        self.worker.add_metadata(str(self.file), track, None)
        self.assertEqual(self.pcm(), audio_before)
        self.assertEqual(ID3(self.file).getall("APIC"), [])
        self.assertTrue(any("No usable cover" in message for message in self.logs))


if __name__ == "__main__":
    unittest.main()
