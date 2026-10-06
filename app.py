"""
YTMP3 Pro — Flask + yt-dlp backend
Vercel compatible
"""

import os
import re
import uuid
import time
import tempfile
import threading
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, send_file, send_from_directory
import yt_dlp


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(tempfile.gettempdir(), "ytmp3pro")

FILE_TTL = 600
MAX_DURATION = 60 * 60

# If FFmpeg is installed and available in PATH, keep None.
FFMPEG_BIN = os.environ.get("FFMPEG_BIN") or None

os.makedirs(TEMP_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)


# ============================================================
# YOUTUBE URL VALIDATION
# ============================================================

def is_valid_youtube(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False

    url = url.strip()

    if not url:
        return False

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower().split(":")[0]
        path = parsed.path.strip("/")

        valid_hosts = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be"
        }

        if host not in valid_hosts:
            return False

        # youtu.be/VIDEO_ID
        if host in ("youtu.be", "www.youtu.be"):
            return bool(path)

        # youtube.com/watch?v=VIDEO_ID
        if path == "watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            return bool(video_id)

        # youtube.com/shorts/VIDEO_ID
        if path.startswith("shorts/"):
            video_id = path.split("/", 1)[1].split("/")[0]
            return bool(video_id)

        # youtube.com/embed/VIDEO_ID
        if path.startswith("embed/"):
            video_id = path.split("/", 1)[1].split("/")[0]
            return bool(video_id)

        # youtube.com/live/VIDEO_ID
        if path.startswith("live/"):
            video_id = path.split("/", 1)[1].split("/")[0]
            return bool(video_id)

        return False

    except Exception:
        return False


# ============================================================
# CLEANUP
# ============================================================

def cleanup_worker():
    while True:
        try:
            now = time.time()

            for name in os.listdir(TEMP_DIR):
                path = os.path.join(TEMP_DIR, name)

                if not os.path.isfile(path):
                    continue

                age = now - os.path.getmtime(path)

                if age > FILE_TTL:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

        except Exception:
            pass

        time.sleep(120)


threading.Thread(
    target=cleanup_worker,
    daemon=True
).start()


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def ydl_base_opts():

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,

        "nocheckcertificate": True,
        "geo_bypass": True,

        "socket_timeout": 30,
        "retries": 3,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        }
    }

    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN

    return opts


# ============================================================
# HELPERS
# ============================================================

def safe_filename(name, fallback="download"):

    name = re.sub(
        r'[\\/:*?"<>|\r\n\t]+',
        "_",
        name or ""
    )

    name = name.strip("._ ")

    return name[:120] or fallback


def find_output(uid, ext):

    prefix = uid.lower()
    extension = "." + ext.lower()

    try:
        for name in os.listdir(TEMP_DIR):

            if (
                name.lower().startswith(prefix)
                and name.lower().endswith(extension)
            ):
                return os.path.join(TEMP_DIR, name)

    except Exception:
        pass

    return None


def error_json(message, code=400):

    return jsonify({
        "ok": False,
        "error": message
    }), code


# ============================================================
# HOME
# ============================================================

@app.route("/", methods=["GET"])
def index():

    index_file = os.path.join(
        BASE_DIR,
        "index.html"
    )

    if os.path.exists(index_file):

        return send_from_directory(
            BASE_DIR,
            "index.html"
        )

    return jsonify({
        "ok": True,
        "service": "YTMP3 Pro",
        "message": "API is running"
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "service": "ytmp3pro",
        "time": int(time.time())
    })


# ============================================================
# INFO
# ============================================================

@app.route("/api/info", methods=["GET"])
def api_info():

    url = request.args.get(
        "url",
        ""
    ).strip()

    if not is_valid_youtube(url):

        return error_json(
            "Invalid YouTube URL.",
            400
        )

    try:

        with yt_dlp.YoutubeDL(
            ydl_base_opts()
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        duration = info.get(
            "duration"
        ) or 0

        if duration > MAX_DURATION:

            return error_json(
                "Video is longer than 1 hour.",
                400
            )

        heights = set()

        for fmt in info.get("formats") or []:

            if (
                fmt.get("vcodec")
                and fmt.get("vcodec") != "none"
                and fmt.get("height")
            ):

                try:
                    heights.add(
                        int(fmt["height"])
                    )
                except Exception:
                    pass

        return jsonify({

            "ok": True,

            "data": {

                "id": info.get("id"),

                "title": info.get("title"),

                "thumbnail": info.get(
                    "thumbnail"
                ),

                "duration": duration,

                "duration_string":
                    info.get("duration_string")
                    or time.strftime(
                        "%H:%M:%S",
                        time.gmtime(duration)
                    ),

                "uploader":
                    info.get("uploader"),

                "view_count":
                    info.get("view_count"),

                "resolutions":
                    sorted(
                        heights,
                        reverse=True
                    )
            }
        })

    except yt_dlp.utils.DownloadError as e:

        return error_json(
            "YouTube error: "
            + str(e)[:300],
            400
        )

    except Exception as e:

        return error_json(
            "Server error: "
            + str(e)[:300],
            500
        )


# ============================================================
# MP3
# ============================================================

@app.route("/api/mp3", methods=["GET"])
def api_mp3():

    url = request.args.get(
        "url",
        ""
    ).strip()

    quality = request.args.get(
        "quality",
        "192"
    ).strip()

    if not is_valid_youtube(url):

        return error_json(
            "Invalid YouTube URL.",
            400
        )

    if quality not in (
        "128",
        "192",
        "256",
        "320"
    ):

        quality = "192"

    uid = uuid.uuid4().hex

    output = os.path.join(
        TEMP_DIR,
        f"{uid}.%(ext)s"
    )

    opts = ydl_base_opts()

    opts.update({

        "format":
            "bestaudio/best",

        "outtmpl":
            output,

        "postprocessors": [

            {
                "key":
                    "FFmpegExtractAudio",

                "preferredcodec":
                    "mp3",

                "preferredquality":
                    quality
            }

        ],

        "postprocessor_args":
            ["-ar", "44100"],

        "prefer_ffmpeg":
            True
    })

    try:

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

        path = find_output(
            uid,
            "mp3"
        )

        if not path:

            return error_json(
                "MP3 conversion failed. FFmpeg may be unavailable.",
                500
            )

        title = safe_filename(
            info.get(
                "title",
                "audio"
            )
        )

        return send_file(

            path,

            mimetype="audio/mpeg",

            as_attachment=True,

            download_name=
                f"{title}.mp3",

            conditional=True
        )

    except yt_dlp.utils.DownloadError as e:

        return error_json(
            "YouTube error: "
            + str(e)[:300],
            400
        )

    except Exception as e:

        return error_json(
            "Server error: "
            + str(e)[:300],
            500
        )


# ============================================================
# MP4
# ============================================================

@app.route("/api/mp4", methods=["GET"])
def api_mp4():

    url = request.args.get(
        "url",
        ""
    ).strip()

    quality = request.args.get(
        "quality",
        "best"
    ).strip().lower()

    if not is_valid_youtube(url):

        return error_json(
            "Invalid YouTube URL.",
            400
        )

    # ----------------------------
    # QUALITY
    # ----------------------------

    if quality in (
        "",
        "best"
    ):

        fmt = (
            "bestvideo[ext=mp4]+"
            "bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best"
        )

    elif quality in (
        "2160",
        "1440",
        "1080",
        "720",
        "480",
        "360"
    ):

        fmt = (

            f"bestvideo[height<={quality}]"
            "[ext=mp4]+"
            "bestaudio[ext=m4a]/"

            f"bestvideo[height<={quality}]"
            "+bestaudio/"

            f"best[height<={quality}]/best"
        )

    else:

        fmt = (
            "bestvideo[ext=mp4]+"
            "bestaudio[ext=m4a]/"
            "best"
        )

    uid = uuid.uuid4().hex

    output = os.path.join(
        TEMP_DIR,
        f"{uid}.%(ext)s"
    )

    opts = ydl_base_opts()

    opts.update({

        "format":
            fmt,

        "outtmpl":
            output,

        "merge_output_format":
            "mp4",

        "prefer_ffmpeg":
            True
    })

    try:

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

        path = find_output(
            uid,
            "mp4"
        )

        if not path:

            return error_json(
                "MP4 conversion failed. FFmpeg may be unavailable.",
                500
            )

        title = safe_filename(
            info.get(
                "title",
                "video"
            )
        )

        return send_file(

            path,

            mimetype="video/mp4",

            as_attachment=True,

            download_name=
                f"{title}.mp4",

            conditional=True
        )

    except yt_dlp.utils.DownloadError as e:

        return error_json(
            "YouTube error: "
            + str(e)[:300],
            400
        )

    except Exception as e:

        return error_json(
            "Server error: "
            + str(e)[:300],
            500
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
