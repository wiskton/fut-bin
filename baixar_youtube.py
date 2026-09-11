"""
baixar_youtube.py - Baixa vídeo do YouTube em formato MP4 compatível para uso no fut-bin.

Uso:
    python baixar_youtube.py --url "https://www.youtube.com/watch?v=..." [--output_dir videos] [--meta_file arquivo.json]
"""

import argparse
import json
import os
import re
import sys
import yt_dlp


def main():
    parser = argparse.ArgumentParser(description="Baixar vídeo do YouTube")
    parser.add_argument("--url", required=True, help="URL do vídeo no YouTube")
    parser.add_argument("--output_dir", default="videos", help="Diretório de saída")
    parser.add_argument("--meta_file", default=None, help="Caminho do arquivo JSON para salvar metadados")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"Obtendo informações do vídeo: {args.url}", flush=True)

    ultimo_pct = -1

    def progress_hook(d):
        nonlocal ultimo_pct
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            pct = (downloaded / total * 100) if total > 0 else 0
            pct_int = int(pct)
            if pct_int != ultimo_pct and (pct_int % 2 == 0 or pct_int >= 99):
                ultimo_pct = pct_int
                mb_down = downloaded / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                vel = (speed / (1024 * 1024)) if speed else 0
                eta_fmt = f"{int(eta // 60):02d}:{int(eta % 60):02d}" if eta else "--:--"
                print(f"[download] {pct:5.1f}% de {mb_tot:6.1f}MB a {vel:4.1f}MB/s (restam ~{eta_fmt})", flush=True)
        elif status == "finished":
            print("[download] Concluído download das faixas, mesclando em MP4...", flush=True)

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(args.output_dir, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
        "quiet": False,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
            arquivo_final = ydl.prepare_filename(info)
            base, _ = os.path.splitext(arquivo_final)
            arquivo_mp4 = base + ".mp4"
            if not os.path.exists(arquivo_mp4) and os.path.exists(arquivo_final):
                arquivo_mp4 = arquivo_final

            if not os.path.exists(arquivo_mp4):
                candidatos = [
                    os.path.join(args.output_dir, f)
                    for f in os.listdir(args.output_dir)
                    if f.lower().endswith(".mp4")
                ]
                if candidatos:
                    arquivo_mp4 = max(candidatos, key=os.path.getmtime)

            duracao = info.get("duration")
            titulo = info.get("title") or os.path.basename(arquivo_mp4)

            meta = {
                "ok": True,
                "nome": os.path.basename(arquivo_mp4),
                "caminho": os.path.abspath(arquivo_mp4),
                "duracao_s": duracao,
                "titulo": titulo,
            }

            meta_caminho = args.meta_file or os.path.join(args.output_dir, ".ultimo_download.json")
            with open(meta_caminho, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            print(f"\n✓ Vídeo pronto! Salvo em: {os.path.abspath(arquivo_mp4)}", flush=True)
            print(f"METADADOS_JSON: {json.dumps(meta)}", flush=True)
    except Exception as e:
        print(f"\nERRO ao baixar vídeo do YouTube: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
