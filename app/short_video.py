"""Deterministic 15-second vertical release video. No external assets fetched."""
import os
import shutil
import subprocess
import tempfile
import textwrap
import threading
from pathlib import Path

_RENDER_LOCK = threading.BoundedSemaphore(1)


def render_short_video(payload):
    binary = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        raise ValueError("Video rendering needs FFmpeg installed on the application server")
    if not _RENDER_LOCK.acquire(blocking=False):
        raise ValueError("Another video is rendering. Please try again shortly")
    try:
        with tempfile.TemporaryDirectory(prefix="growthos-video-") as folder:
            root = Path(folder)
            texts = [payload.get("title") or "Product update",
                     payload.get("summary") or payload.get("body") or "",
                     payload.get("cta_url") or "Discover what is new"]
            filters = []
            for n, text in enumerate(texts):
                clean = " ".join(str(text).split())
                if len(clean) > 180:
                    clean = clean[:177].rsplit(" ", 1)[0] + "..."
                (root / f"scene{n}.txt").write_text(textwrap.fill(clean, 27), encoding="utf-8")
                filters.append(f"drawtext=textfile=scene{n}.txt:expansion=none:fontcolor=white:fontsize=48:line_spacing=18:x=(w-text_w)/2:y=(h-text_h)/2:enable='gte(t,{n*5})*lt(t,{(n+1)*5})'")
            cmd = [str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-f", "lavfi", "-i", "color=c=0x10233f:s=720x1280:r=30:d=15",
                   "-vf", ",".join(filters), "-an", "-c:v", "libx264", "-preset", "veryfast",
                   "-threads", "2", "-pix_fmt", "yuv420p", "-t", "15", "-movflags", "+faststart", "video.mp4"]
            try:
                subprocess.run(cmd, cwd=root, capture_output=True, check=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ValueError("Video rendering failed; check the server FFmpeg installation") from exc
            return (root / "video.mp4").read_bytes()
    finally:
        _RENDER_LOCK.release()
