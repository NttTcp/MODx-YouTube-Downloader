import os
import re
import uuid
import time
import tempfile

from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, send_file

import yt_dlp


app = Flask(__name__)

TEMP_DIR = os.path.join(
    tempfile.gettempdir(),
    "ytmp3x"
)

os.makedirs(TEMP_DIR, exist_ok=True)


def valid_youtube(url):

    try:

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        p = urlparse(url)

        host = p.netloc.lower().split(":")[0]
        path = p.path.strip("/")

        if host in ("youtu.be", "www.youtu.be"):
            return bool(path)

        if host not in (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com"
        ):
            return False

        if path == "watch":

            return bool(
                parse_qs(p.query)
                .get("v", [""])[0]
            )

        for prefix in (
            "shorts/",
            "embed/",
            "live/"
        ):

            if path.startswith(prefix):

                video_id = (
                    path[len(prefix):]
                    .split("/")[0]
                )

                return bool(video_id)

        return False

    except Exception:

        return False


def error(message, code=400):

    return jsonify({
        "ok": False,
        "error": message
    }), code


def ydl_options():

    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        }
    }


def find_file(uid, ext):

    prefix = uid + "."

    for filename in os.listdir(TEMP_DIR):

        if (
            filename.startswith(prefix)
            and filename.endswith("." + ext)
        ):
            return os.path.join(
                TEMP_DIR,
                filename
            )

    return None


# ------------------------------------------------
# HEALTH
# ------------------------------------------------

@app.route("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service": "YTMP3 X",
        "status": "online"
    })


# ------------------------------------------------
# MP3
# ------------------------------------------------

@app.route("/api/mp3")
def mp3():

    url = request.args.get(
        "url",
        ""
    ).strip()

    quality = request.args.get(
        "quality",
        "192"
    )

    if not valid_youtube(url):

        return error(
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
        uid + ".%(ext)s"
    )

    options = ydl_options()

    options.update({

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

        "prefer_ffmpeg":
            True
    })

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

        path = find_file(
            uid,
            "mp3"
        )

        if not path:

            return error(
                "MP3 conversion failed. FFmpeg is probably unavailable.",
                500
            )

        return send_file(
            path,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="audio.mp3"
        )

    except Exception as e:

        return error(
            str(e)[:500],
            500
        )


# ------------------------------------------------
# MP4
# ------------------------------------------------

@app.route("/api/mp4")
def mp4():

    url = request.args.get(
        "url",
        ""
    ).strip()

    quality = request.args.get(
        "quality",
        "best"
    )

    if not valid_youtube(url):

        return error(
            "Invalid YouTube URL.",
            400
        )

    if quality in (
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
            f"best[height<={quality}]/best"
        )

    else:

        fmt = (
            "bestvideo[ext=mp4]+"
            "bestaudio[ext=m4a]/best"
        )

    uid = uuid.uuid4().hex

    output = os.path.join(
        TEMP_DIR,
        uid + ".%(ext)s"
    )

    options = ydl_options()

    options.update({

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
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

        path = find_file(
            uid,
            "mp4"
        )

        if not path:

            return error(
                "MP4 conversion failed. FFmpeg is probably unavailable.",
                500
            )

        return send_file(
            path,
            mimetype="video/mp4",
            as_attachment=True,
            download_name="video.mp4"
        )

    except Exception as e:

        return error(
            str(e)[:500],
            500
        )
