import os
import re
import uuid
import tempfile
import time

from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, send_file, send_from_directory

import yt_dlp


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

TEMP_DIR = os.path.join(
    tempfile.gettempdir(),
    "ytmp3x"
)

os.makedirs(
    TEMP_DIR,
    exist_ok=True
)


app = Flask(
    __name__,
    static_folder=None
)


# ============================================================
# YOUTUBE URL CHECK
# ============================================================

def valid(url):

    try:

        if not url.startswith(
            ("http://", "https://")
        ):
            url = "https://" + url

        p = urlparse(url)

        host = p.netloc.lower().split(":")[0]

        path = p.path.strip("/")

        # youtu.be
        if host in (
            "youtu.be",
            "www.youtu.be"
        ):

            return bool(path)

        # youtube.com
        if host in (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com"
        ):

            if path == "watch":

                return bool(
                    parse_qs(
                        p.query
                    ).get(
                        "v",
                        [""]
                    )[0]
                )

            for prefix in (
                "shorts/",
                "embed/",
                "live/"
            ):

                if path.startswith(prefix):

                    parts = path.split(
                        "/",
                        1
                    )

                    if len(parts) > 1:

                        video_id = (
                            parts[1]
                            .split("/")[0]
                        )

                        return bool(video_id)

        return False

    except Exception:

        return False


# ============================================================
# ERROR
# ============================================================

def err(message, code=400):

    return jsonify({
        "ok": False,
        "error": message
    }), code


# ============================================================
# YT-DLP
# ============================================================

def opts():

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


# ============================================================
# FIND FILE
# ============================================================

def find(uid, ext):

    try:

        for name in os.listdir(
            TEMP_DIR
        ):

            if (
                name.startswith(uid)
                and name.endswith(
                    "." + ext
                )
            ):

                return os.path.join(
                    TEMP_DIR,
                    name
                )

    except Exception:

        pass

    return None


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    path = os.path.join(
        BASE_DIR,
        "index.html"
    )

    if os.path.exists(path):

        return send_from_directory(
            BASE_DIR,
            "index.html"
        )

    return jsonify({
        "ok": True,
        "service": "YTMP3 X"
    })


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    return jsonify({

        "ok": True,

        "service": "ytmp3x",

        "time": int(
            time.time()
        )

    })


# ============================================================
# CONVERT
# ============================================================

@app.get("/api/<kind>")
def convert(kind):

    if kind not in (
        "mp3",
        "mp4"
    ):

        return err(
            "Unknown endpoint",
            404
        )


    url = request.args.get(
        "url",
        ""
    ).strip()


    quality = request.args.get(
        "quality",
        "192"
        if kind == "mp3"
        else "best"
    ).lower()


    if not valid(url):

        return err(
            "Invalid YouTube URL."
        )


    uid = uuid.uuid4().hex


    output = os.path.join(
        TEMP_DIR,
        uid + ".%(ext)s"
    )


    options = opts()


    # --------------------------------------------------------
    # MP3
    # --------------------------------------------------------

    if kind == "mp3":

        if quality not in (
            "128",
            "192",
            "256",
            "320"
        ):

            quality = "192"


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


    # --------------------------------------------------------
    # MP4
    # --------------------------------------------------------

    else:

        height = None


        if quality in (
            "2160",
            "1440",
            "1080",
            "720",
            "480",
            "360"
        ):

            height = quality


        if height:

            fmt = (

                f"bestvideo"
                f"[height<={height}]"
                f"[ext=mp4]+"
                f"bestaudio[ext=m4a]/"

                f"best[height<={height}]"

            )

        else:

            fmt = (

                "bestvideo[ext=mp4]+"
                "bestaudio[ext=m4a]/"
                "best"

            )


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


    # --------------------------------------------------------
    # DOWNLOAD
    # --------------------------------------------------------

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )


        path = find(
            uid,
            kind
        )


        if not path:

            return err(

                "Conversion failed. "
                "FFmpeg may be unavailable "
                "on the server.",

                500

            )


        return jsonify({

            "ok": True,

            "title":
                info.get(
                    "title",
                    "download"
                ),

            "download_url":
                "/api/download/"
                + os.path.basename(path)

        })


    except Exception as e:

        return err(
            str(e)[:400],
            500
        )


# ============================================================
# FILE DOWNLOAD
# ============================================================

@app.get("/api/download/<name>")
def download(name):

    if not re.fullmatch(
        r"[a-f0-9]{32}\.(mp3|mp4)",
        name,
        re.I
    ):

        return err(
            "Not found",
            404
        )


    path = os.path.join(
        TEMP_DIR,
        name
    )


    if not os.path.isfile(path):

        return err(
            "File expired or not found",
            404
        )


    return send_file(
        path,
        as_attachment=True,
        download_name=name
    )
