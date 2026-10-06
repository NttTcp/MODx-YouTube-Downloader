from flask import Flask, request, jsonify, Response
import yt_dlp
import re
import requests

app = Flask(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def clean_url(url):
    if not url:
        return None
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([a-zA-Z0-9_-]{11})", url)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


@app.route("/info")
def info():
    url = clean_url(request.args.get("url"))
    if not url:
        return jsonify(error="Invalid YouTube URL"), 400

    opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)

        formats = []
        seen = set()
        for f in data.get("formats", []):
            if f.get("vcodec") == "none":
                continue
            if f.get("acodec") == "none":
                continue
            q = f.get("format_note") or f.get("resolution") or "?"
            if q in seen:
                continue
            seen.add(q)
            formats.append({
                "format_id": f["format_id"],
                "quality": q,
                "ext": f.get("ext", "mp4"),
                "size": f.get("filesize") or f.get("filesize_approx"),
            })

        formats.sort(key=lambda x: int(re.sub(r"\D", "", x["quality"]) or 0))

        return jsonify({
            "title": data.get("title"),
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration") or 0,
            "author": data.get("uploader", ""),
            "formats": formats,
        })
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/download")
def download():
    url = clean_url(request.args.get("url"))
    if not url:
        return jsonify(error="Invalid URL"), 400

    kind = request.args.get("type", "video")
    fmt_id = request.args.get("format_id")

    if kind == "audio":
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
    else:
        fmt = fmt_id or "best[ext=mp4]/best"

    opts = {"quiet": True, "noplaylist": True, "format": fmt}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)

        direct = data["url"]
        ext = data.get("ext", "mp4")

        headers = {
            "User-Agent": UA,
            "Referer": "https://www.youtube.com/",
            "Range": request.headers.get("Range", ""),
        }
        r = requests.get(direct, headers=headers, stream=True, timeout=60)

        def generate():
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

        mime = "audio/mp4" if kind == "audio" else f"video/{ext}"
        filename = f"{kind}-{data.get('id', 'file')}.{ext}"

        return Response(
            generate(),
            mimetype=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


# Vercel needs this
handler = app
