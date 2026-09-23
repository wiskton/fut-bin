"""Cópia leve para revisão: mantém a linha do tempo e preserva o original."""
import argparse
import hashlib
import os
import subprocess
import time
from pathlib import Path


def preview_key(source, height):
    if height not in (360, 480):
        raise ValueError("Escolha 360p ou 480p")
    path = Path(source).resolve()
    stat = path.stat()
    identity = f"preview-v1|{path}|{stat.st_size}|{stat.st_mtime_ns}|{height}"
    return hashlib.sha256(identity.encode()).hexdigest()


def preview_command(source, height, output):
    if height not in (360, 480):
        raise ValueError("Escolha 360p ou 480p")
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-threads", "2", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", f"scale=-2:'trunc(min({height},ih)/2)*2':flags=fast_bilinear,fps=15",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-pix_fmt", "yuv420p", "-threads", "2", "-filter_threads", "1",
        "-g", "15", "-keyint_min", "15", "-sc_threshold", "0", "-bf", "0",
        "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-ar", "48000",
        "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(output),
    ]


def generate_preview(source, height, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".partial.mp4")
    lock = output.with_suffix(".lock")
    lock_fd = None
    # Evita duas instâncias/portas renderizando a mesma prévia simultaneamente.
    while lock_fd is None:
        if output.is_file() and output.stat().st_size > 0:
            return
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(lock_fd, str(os.getpid()).encode())
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 6 * 60 * 60:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            time.sleep(1)
    try:
        subprocess.run(preview_command(source, height, partial), check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        os.replace(partial, output)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        partial.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("height", type=int, choices=(360, 480))
    parser.add_argument("output")
    args = parser.parse_args()
    generate_preview(args.source, args.height, args.output)
