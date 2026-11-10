"""Junta os arquivos soltos de uma câmera e corta só a janela da partida.

A câmera grava a pelada em vários arquivos. Esta etapa coloca esses arquivos
em ordem, descarta o que ficou de fora do apito inicial e do apito final, e
gera um vídeo contínuo. Os gols são separados depois, a partir desse arquivo.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Iterable, List, Optional


def segmentos_da_janela(duracoes: Iterable[float], inicio_s: float, fim_s: float) -> List[dict]:
    """Recorta a janela [inicio, fim] na linha do tempo da junção.

    Cada item devolve o arquivo (pelo índice), o início dentro dele e a duração
    que entra na partida.
    """
    duracoes = [float(d) for d in duracoes]
    if not duracoes:
        raise ValueError("Adicione pelo menos um arquivo da câmera.")
    if any(d <= 0 for d in duracoes):
        raise ValueError("Todo arquivo precisa ter duração maior que zero.")
    inicio_s = float(inicio_s)
    fim_s = float(fim_s)
    if inicio_s < 0:
        raise ValueError("O início da partida não pode ser negativo.")
    if fim_s <= inicio_s:
        raise ValueError("O fim da partida precisa ser depois do início.")
    total = sum(duracoes)
    if inicio_s >= total:
        raise ValueError("O início marcado fica depois do fim da gravação.")
    # A duração exibida na tela é arredondada; até 1 s além do total ainda é o fim do arquivo.
    if fim_s > total + 1:
        raise ValueError("O fim marcado passa do final da gravação.")
    fim_s = min(fim_s, total)

    cortes = []
    cursor = 0.0
    for indice, duracao in enumerate(duracoes):
        comeco = cursor
        final = cursor + duracao
        esquerda = max(inicio_s, comeco)
        direita = min(fim_s, final)
        if direita - esquerda > 0.05:
            cortes.append({
                "indice": indice,
                "inicio": round(esquerda - comeco, 3),
                "duracao": round(direita - esquerda, 3),
            })
        cursor = final
    if not cortes:
        raise ValueError("A janela marcada não cobre nenhum trecho.")
    return cortes


def _fps_valido(texto: Optional[str]) -> str:
    if not texto or texto in ("0/0", "N/A"):
        return "30/1"
    num, sep, den = texto.partition("/")
    if not sep:
        return "30/1"
    try:
        if float(num) <= 0 or float(den) <= 0:
            return "30/1"
    except ValueError:
        return "30/1"
    return texto


def info_midia(caminho: str) -> dict:
    """Lê duração, tamanho e se o arquivo tem áudio."""
    if not os.path.isfile(caminho):
        raise ValueError(f"Arquivo não encontrado: {caminho}")
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,avg_frame_rate",
             "-of", "json", caminho],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError as exc:
        raise ValueError("ffprobe não está instalado.") from exc
    if proc.returncode != 0:
        raise ValueError(f"Não consegui ler o vídeo: {os.path.basename(caminho)}")
    try:
        dados = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Não consegui ler o vídeo: {os.path.basename(caminho)}") from exc
    streams = dados.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
    if not video:
        raise ValueError(f"O arquivo não tem imagem: {os.path.basename(caminho)}")
    try:
        duracao = float((dados.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duracao = 0
    if duracao <= 0:
        raise ValueError(f"Não consegui ler a duração de {os.path.basename(caminho)}")
    return {
        "caminho": os.path.abspath(caminho),
        "duracao_s": duracao,
        "largura": int(video["width"]),
        "altura": int(video["height"]),
        "fps": _fps_valido(video.get("avg_frame_rate")),
        "tem_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def montar_segmentos(infos: List[dict], inicio_s: float, fim_s: float):
    """Aplica a janela da partida e devolve os trechos com o tamanho do primeiro."""
    cortes = segmentos_da_janela([i["duracao_s"] for i in infos], inicio_s, fim_s)
    segmentos = []
    for corte in cortes:
        info = infos[corte["indice"]]
        segmentos.append({
            "caminho": info["caminho"],
            "inicio": corte["inicio"],
            "duracao": corte["duracao"],
            "tem_audio": bool(info.get("tem_audio")),
        })
    ref = infos[cortes[0]["indice"]]
    return segmentos, int(ref["largura"]), int(ref["altura"]), ref["fps"]


def _filtro(segmentos: List[dict], largura: int, altura: int, fps: str) -> str:
    partes = []
    for i, seg in enumerate(segmentos):
        partes.append(
            f"[{i}:v:0]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
            f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
            f"format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
        )
        if seg["tem_audio"]:
            partes.append(
                f"[{i}:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        else:
            partes.append(
                f"anullsrc=r=48000:cl=stereo,atrim=0:{seg['duracao']:.3f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
    entradas = "".join(f"[v{i}][a{i}]" for i in range(len(segmentos)))
    partes.append(f"{entradas}concat=n={len(segmentos)}:v=1:a=1[outv][outa]")
    return ";".join(partes)


def comando_juntar(segmentos: List[dict], saida: str, largura: int, altura: int,
                    fps: str, args_encode: List[str]) -> List[str]:
    """Monta o ffmpeg que junta os trechos e grava só a partida."""
    if not segmentos:
        raise ValueError("A janela marcada não cobre nenhum trecho.")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    if len(segmentos) == 1:
        seg = segmentos[0]
        cmd += ["-ss", f"{seg['inicio']:.3f}", "-t", f"{seg['duracao']:.3f}", "-i", seg["caminho"]]
        if seg["tem_audio"]:
            cmd += ["-map", "0:v:0", "-map", "0:a:0"]
        else:
            cmd += ["-f", "lavfi", "-t", f"{seg['duracao']:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
        cmd += [*args_encode, saida]
        return cmd
    for seg in segmentos:
        cmd += ["-ss", f"{seg['inicio']:.3f}", "-t", f"{seg['duracao']:.3f}", "-i", seg["caminho"]]
    cmd += ["-filter_complex", _filtro(segmentos, largura, altura, fps),
            "-map", "[outv]", "-map", "[outa]", *args_encode, saida]
    return cmd


def preparar(caminhos: List[str], inicio_s: float, fim_s: float, saida: str,
             args_encode: Optional[List[str]] = None) -> List[str]:
    """Lê os arquivos e devolve o comando ffmpeg da partida já cortada."""
    if args_encode is None:
        from video_quality import obter_args_corte
        args_encode = obter_args_corte()
    infos = [info_midia(c) for c in caminhos]
    segmentos, largura, altura, fps = montar_segmentos(infos, inicio_s, fim_s)
    return comando_juntar(segmentos, saida, largura, altura, fps, list(args_encode))
