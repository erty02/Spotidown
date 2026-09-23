"""Embedded artwork and ID3 settings intended for iTunes and older iPods."""

from io import BytesIO
import os
import shutil
import tempfile
import warnings

from PIL import Image, ImageOps
import requests
from mutagen.id3 import APIC


COVER_SIZE = (600, 600)
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def prepare_cover(data):
    """Decode the actual image, then produce a small baseline RGB JPEG."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Cover image is too large")
            cover = ImageOps.exif_transpose(source)
            cover.thumbnail(COVER_SIZE, Image.Resampling.LANCZOS)
            # Flatten transparency against white, without cropping or stretching.
            rgba = cover.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
            result = BytesIO()
            rgb.save(result, format="JPEG", quality=85, progressive=False)
            return result.getvalue()


def fetch_cover(url):
    # Bound both download size and time; do not trust the HTTP MIME type.
    with requests.get(url, timeout=(5, 15), stream=True) as response:
        response.raise_for_status()
        result = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            result.extend(chunk)
            if len(result) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Cover download exceeds 10 MB")
        return prepare_cover(bytes(result))


def embed_cover(tags, track, log):
    """Prefer this Spotify release's art, then an existing embedded picture.

    Return False if no usable cover exists. Failed downloads never erase old art.
    """
    album = track.get("album") or {}
    images = album.get("images") or []
    cover_data = None
    seen = set()
    for image in images:
        url = image.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            cover_data = fetch_cover(url)
            break
        except (requests.RequestException, OSError, ValueError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            log(f"   -> WARNING: Could not load Spotify artwork: {error}")

    if cover_data is None:
        # Prefer the old front cover to a back cover or artist photograph.
        pictures = sorted(tags.getall("APIC"), key=lambda pic: pic.type != 3)
        for picture in pictures:
            try:
                cover_data = prepare_cover(picture.data)
                break
            except (OSError, ValueError, Image.DecompressionBombError,
                    Image.DecompressionBombWarning):
                continue

    if cover_data is None:
        log("   -> WARNING: No usable cover. Audio is kept; run the playlist again to retry artwork.")
        return False

    # A single front cover avoids players choosing a stale/different APIC frame.
    tags.delall("APIC")
    tags.add(APIC(encoding=0, mime="image/jpeg", type=3,
                  desc="Cover", data=cover_data))
    return True


def save_id3v23(audio, filepath):
    """Save through a sibling temporary copy so failed edits leave audio intact."""
    filepath = os.path.abspath(filepath)
    fd, temporary_path = tempfile.mkstemp(prefix=".spotidown-", suffix=".mp3",
                                          dir=os.path.dirname(filepath))
    os.close(fd)
    try:
        shutil.copyfile(filepath, temporary_path)
        audio.tags.update_to_v23()
        audio.tags.save(temporary_path, v2_version=3, v23_sep="/",
                        padding=lambda info: 1024)
        os.replace(temporary_path, filepath)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
