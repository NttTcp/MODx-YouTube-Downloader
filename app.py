"""
YTMP3 Pro — Flask + yt-dlp backend
Install:  pip install flask yt-dlp
Run:      python app.py
"""

import os
import re
import uuid
import shutil
import tempfile
import threading
import time
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, send_file, send_from_directory, abort
import yt_dlp

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR      = os.path.join(tempfile.gettempdir(), "ytmp3pro")
FILE_TTL      = 600          # 10 min — auto delete converted files
FFMPEG_BIN    = None         # e.g. r"C:\ffmpeg\bin\ffmpeg.exe" if not in PATH
MAX_DURATION  = 60 * 60      # 1 hour cap for very long videos (optional)

os.makedirs(TEMP_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
YT_REGEX = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|embed/|live/)|youtu\.be/)",
    re.IGNORECASE,
)


def is_valid_youtube(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not YT_REGEX.match(url):
        return False
    try:
        p = urlparse(url)
        if "youtu.be" in p.netloc:
            return bool(p.path.strip("/"))
        qs = parse_qs(p.query)
        return bool(qs.get("v", [""])[0])
    except Exception:
        return False


def cleanup_worker():
    """Background thread: delete files older than FILE_TTL."""
    while True:
        try:
            now = time.time()
            for name in os.listdir(TEMP_DIR):
                path = os.path.join(TEMP_DIR, name)
                if os.path.isfile(path) and now - os.path.getmtime(path) > FILE_TTL:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        except Exception:
            pass
        time.sleep(120)


threading.Thread(target=cleanup_worker, daemon=True).start()


def ydl_base_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "retries": 3,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN
    return opts


def safe_filename(name: str, fallback: str = "download") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip("._ ")
    return (name[:120] or fallback)


def find_output(uid: str, ext: str):
    """yt-dlp ke output ko dhoondo (extension .mp3/.mp4)."""
    for name in os.listdir(TEMP_DIR):
        if name.startswith(uid) and name.lower().endswith("." + ext):
            return os.path.join(TEMP_DIR, name)
    return None


def error_json(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


# ------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "ytmp3pro", "time": int(time.time())})


@app.route("/api/info")
def api_info():
    url = request.args.get("url", "").strip()
    if not is_valid_youtube(url):
        return error_json("Invalid YouTube URL.", 400)

    try:
        with yt_dlp.YoutubeDL(ydl_base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        # Available video resolutions
        heights = set()
        for f in info.get("formats") or []:
            if f.get("vcodec") and f.get("vcodec") != "none" and f.get("height"):
                heights.add(int(f["height"]))

        return jsonify({
            "ok": True,
            "data": {
                "id":             info.get("id"),
                "title":          info.get("title"),
                "thumbnail":      info.get("thumbnail"),
                "duration":       info.get("duration"),
                "duration_string": info.get("duration_string")
                                    or time.strftime("%H:%M:%S", time.gmtime(info.get("duration") or 0)),
                "uploader":       info.get("uploader"),
                "view_count":     info.get("view_count"),
                "resolutions":    sorted(heights, reverse=True),
            },
        })
    except yt_dlp.utils.DownloadError as e:
        return error_json(f"YouTube error: {str(e)[:200]}", 400)
    except Exception as e:
        return error_json(f"Server error: {str(e)[:200]}", 500)


# -------------------------- MP3 --------------------------
@app.route("/api/mp3")
def api_mp3():
    url     = request.args.get("url", "").strip()
    quality = request.args.get("quality", "192").strip()

    if not is_valid_youtube(url):
        return error_json("Invalid YouTube URL.", 400)

    if quality not in ("128", "192", "256", "320"):
        quality = "192"

    uid      = uuid.uuid4().hex
    outtmpl  = os.path.join(TEMP_DIR, f"{uid}.%(ext)s")

    opts = ydl_base_opts()
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        }],
        "postprocessor_args": ["-ar", "44100"],
        "prefer_ffmpeg": True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title = safe_filename(info.get("title", "audio"))
        path  = find_output(uid, "mp3")
        if not path or not os.path.exists(path):
            return error_json("Conversion failed (MP3 not produced).", 500)

        return send_file(
            path,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{title}.mp3",
            conditional=True,
        )
    except yt_dlp.utils.DownloadError as e:
        return error_json(f"YouTube error: {str(e)[:200]}", 400)
    except Exception as e:
        return error_json(f"Server error: {str(e)[:200]}", 500)


# -------------------------- MP4 --------------------------
@app.route("/api/mp4")
def api_mp4():
    url     = request.args.get("url", "").strip()
    quality = request.args.get("quality", "best").strip().lower()

    if not is_valid_youtube(url):
        return error_json("Invalid YouTube URL.", 400)

    # build format string
    if quality in ("best", ""):
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    elif quality in ("2160", "1440", "1080", "720", "480", "360"):
        h = quality
        fmt = (f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
               f"bestvideo[height<={h}]+bestaudio/best[height<={h}]")
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"

    uid     = uuid.uuid4().hex
    outtmpl = os.path.join(TEMP_DIR, f"{uid}.%(ext)s")

    opts = ydl_base_opts()
    opts.update({
        "format": fmt,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "prefer_ffmpeg": True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title = safe_filename(info.get("title", "video"))
        path  = find_output(uid, "mp4")
        if not path or not os.path.exists(path):
            return error_json("Conversion failed (MP4 not produced).", 500)

        return send_file(
            path,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"{title}.mp4",
            conditional=True,
        )
    except yt_dlp.utils.DownloadError as e:
        return error_json(f"YouTube error: {str(e)[:200]}", 400)
    except Exception as e:
        return error_json(f"Server error: {str(e)[:200]}", 500)


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  YTMP3 Pro running →  http://127.0.0.1:5000")
    print("  API:")
    print("    /api/mp3?url=...&quality=320")
    print("    /api/mp4?url=...&quality=1080")
    print("    /api/info?url=...")
    print("    /api/health")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
