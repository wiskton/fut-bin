"""
assistente_web.py - assistente no navegador para o pipeline completo do fut-bin.

Faz a mesma coisa que rodar os 4 scripts na mao (ver README.md), so que como
um passo-a-passo num site local: escolher o video, marcar a regiao do
placar, revisar os gols achados automaticamente (ajustando o que precisar),
cortar os clipes, marcar autor/assistencia e montar o video final - sem abrir
terminal, sem editar gols.txt/placar.json na mao, sem usar Paint.

Roda 100% local (voce mesmo na sua maquina): o servidor sobe em
127.0.0.1 e os videos nunca saem dela. As etapas pesadas (achar gols,
cortar, montar) continuam sendo os mesmos scripts de sempre
(detectar_gols.py / montar_video.py), so que chamados em segundo plano
como um processo, com o log ao vivo aparecendo na tela.

Uso:
    python assistente_web.py [--port 8000] [--host 127.0.0.1]
    (ou, mais facil: ./run.sh site)
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import List, Optional

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

from detectar_gols import ANTES_S, DEPOIS_S

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(PROJECT_DIR, "web")
VIDEOS_DIR = os.path.join(PROJECT_DIR, "videos")
PLACAR_FILE = os.path.join(PROJECT_DIR, "placar.json")
ZONAS_FILE = os.path.join(PROJECT_DIR, "zonas.json")
GOLS_DIR = os.path.join(PROJECT_DIR, "gols")
GOLS_JSON = os.path.join(GOLS_DIR, "gols.json")
CLIPES_DIR = os.path.join(GOLS_DIR, "clipes")
PARTIDA_JSON = os.path.join(PROJECT_DIR, "partida.json")
FINAL_DIR = os.path.join(PROJECT_DIR, "final")
FINAL_VIDEO = os.path.join(FINAL_DIR, "melhores_momentos.mp4")
FINAL_VIDEO_GOLS = os.path.join(FINAL_DIR, "apenas_gols.mp4")

os.makedirs(VIDEOS_DIR, exist_ok=True)
GOLS_LOCK = threading.Lock()

app = FastAPI(title="fut-bin - assistente")


# --------------------------------------------------------------- utilitarios

def _resolver_video(caminho: str) -> str:
    """Resolve o caminho do video (absoluto, vindo do navegador de pastas, ou
    relativo a pasta do projeto). Se nao achar no caminho exato, procura nas
    pastas comuns pelo nome do arquivo."""
    if not caminho:
        raise HTTPException(400, "caminho de video nao informado")
    alvo = os.path.abspath(os.path.expanduser(caminho))
    if os.path.isfile(alvo):
        return alvo
    nome = os.path.basename(caminho)
    home = os.path.expanduser("~")
    candidatos = [
        os.path.join(VIDEOS_DIR, nome),
        os.path.join(PROJECT_DIR, nome),
        os.path.join(home, "Downloads", nome),
        os.path.join(home, "Vídeos", nome),
        os.path.join(home, "Videos", nome),
    ]
    for c in candidatos:
        if os.path.isfile(c):
            return c
    raise HTTPException(404, f"video nao encontrado: {caminho}")


def _pasta_inicial() -> str:
    home = os.path.expanduser("~")
    for nome in ("Vídeos", "Videos", "Downloads"):
        candidato = os.path.join(home, nome)
        if os.path.isdir(candidato):
            return candidato
    return home


def _ffprobe_duracao(caminho: str) -> Optional[float]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", caminho],
            capture_output=True, text=True, timeout=15,
        )
        return round(float(r.stdout.strip()), 1) if r.stdout.strip() else None
    except Exception:
        return None


def _fmt_tempo(s: float) -> str:
    s = max(0, s)
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def _capturar_frame(video_path: str, tempo_s: float) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(tempo_s, 0) * 1000)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _png_response(img: np.ndarray) -> Response:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "falha ao gerar imagem")
    return Response(content=buf.tobytes(), media_type="image/png")


def _png_base64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return ""
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _carregar_placar_rect() -> Optional[List[int]]:
    if not os.path.exists(PLACAR_FILE):
        return None
    try:
        with open(PLACAR_FILE, encoding="utf-8-sig") as f:
            return json.load(f)["placar"]
    except Exception:
        return None


def _recorte_zoom(frame: np.ndarray, rect: List[int], zoom: int = 8) -> np.ndarray:
    x, y, w, h = rect
    crop = frame[max(y, 0):y + h, max(x, 0):x + w]
    if crop.size == 0:
        raise HTTPException(400, "regiao do placar cai fora do quadro")
    return cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)


# --------------------------------------------------------------- jobs (processos em segundo plano)

JOBS: dict = {}


def _iniciar_job(cmd: List[str]) -> str:
    job_id = uuid.uuid4().hex[:8]
    job = {"status": "queued", "log": [], "linha_atual": "", "returncode": None,
           "lock": threading.Lock(), "iniciado_em": time.time()}
    JOBS[job_id] = job
    threading.Thread(target=_rodar_job, args=(job, cmd), daemon=True).start()
    return job_id


def _rodar_job(job: dict, cmd: List[str]) -> None:
    job["status"] = "running"
    try:
        kwargs = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            cmd, cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            **kwargs,
        )
        with job["lock"]:
            job["proc"] = proc
        buf = ""
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            buf += chunk
            while True:
                candidatos = [i for i in (buf.find("\n"), buf.find("\r")) if i != -1]
                if not candidatos:
                    break
                idx = min(candidatos)
                linha, buf = buf[:idx], buf[idx + 1:]
                if linha.strip():
                    with job["lock"]:
                        job["log"].append(linha.strip())
                        job["log"] = job["log"][-500:]
            with job["lock"]:
                job["linha_atual"] = buf.strip()
        proc.wait()
        with job["lock"]:
            if job["status"] == "canceled":
                return
            if buf.strip():
                job["log"].append(buf.strip())
            job["linha_atual"] = ""
            job["status"] = "done" if proc.returncode == 0 else "error"
            job["returncode"] = proc.returncode
    except Exception as exc:  # processo nao subiu, script sumiu, etc.
        with job["lock"]:
            if job["status"] != "canceled":
                job["status"] = "error"
                job["log"].append(f"ERRO: {exc}")


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job desconhecido")
    with job["lock"]:
        return {
            "status": job["status"], "log": job["log"][-200:],
            "linha_atual": job["linha_atual"], "returncode": job["returncode"],
        }


@app.post("/api/job/{job_id}/cancelar")
def api_cancelar_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job desconhecido")
    with job["lock"]:
        proc = job.get("proc")
        if proc and job["status"] in ("running", "queued"):
            job["status"] = "canceled"
            try:
                if sys.platform != "win32":
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    time.sleep(0.15)
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    proc.terminate()
                    proc.kill()
            except Exception:
                try:
                    proc.terminate()
                    proc.kill()
                except Exception:
                    pass
            job["log"].append("⚠ Processamento cancelado pelo usuário.")
            job["linha_atual"] = ""
            return {"ok": True, "status": "canceled"}
        return {"ok": True, "status": job["status"]}


# --------------------------------------------------------------- videos

@app.get("/api/videos")
def api_videos():
    """Atalhos: videos ja vistos na pasta videos/ do projeto (se a pessoa
    preferir continuar organizando os jogos ali) ou na raiz do projeto."""
    pastas = [VIDEOS_DIR, PROJECT_DIR]
    vistos, resultado = set(), []
    for pasta in pastas:
        if not os.path.isdir(pasta):
            continue
        for nome in sorted(os.listdir(pasta)):
            if not nome.lower().endswith((".mp4", ".mov", ".mkv", ".avi")):
                continue
            caminho = os.path.abspath(os.path.join(pasta, nome))
            if caminho in vistos:
                continue
            vistos.add(caminho)
            resultado.append({
                "nome": nome, "caminho": caminho,
                "duracao_s": _ffprobe_duracao(caminho),
            })
    return resultado


VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi")


@app.get("/api/videos/buscar")
def api_buscar_videos(q: Optional[str] = None):
    """Busca videos pelo nome em pastas comuns (~/Videos, ~/Downloads, ~, VIDEOS_DIR, PROJECT_DIR)."""
    pastas_busca = []
    home = os.path.expanduser("~")
    for d in (VIDEOS_DIR, os.path.join(home, "Vídeos"), os.path.join(home, "Videos"), os.path.join(home, "Downloads"), PROJECT_DIR, home):
        if os.path.isdir(d) and d not in pastas_busca:
            pastas_busca.append(d)

    q_limpo = (q or "").strip().lower()
    resultados = []
    vistos = set()

    for pasta in pastas_busca:
        try:
            for root, dirs, files in os.walk(pasta):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".venv", "venv", ".git", "brain", ".gemini")]
                rel = os.path.relpath(root, pasta)
                if rel != "." and rel.count(os.sep) >= 2:
                    dirs.clear()
                for f in files:
                    if f.lower().endswith(VIDEO_EXTS):
                        if not q_limpo or q_limpo in f.lower():
                            caminho = os.path.abspath(os.path.join(root, f))
                            if caminho not in vistos and os.path.isfile(caminho):
                                vistos.add(caminho)
                                resultados.append({
                                    "nome": f,
                                    "caminho": caminho,
                                    "pasta": root,
                                    "duracao_s": _ffprobe_duracao(caminho),
                                })
                                if len(resultados) >= 30:
                                    return resultados
        except Exception:
            continue
    return resultados


@app.api_route("/video/completo", methods=["GET", "HEAD"])
def video_completo(video: Optional[str] = None):
    """Stream do video completo com suporte a Range requests para visualizacao e corte no navegador."""
    caminho = None
    if video:
        try:
            caminho = _resolver_video(video)
        except Exception:
            pass
    if not caminho and os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p_meta = json.load(f).get("meta", {})
                if p_meta.get("video"):
                    caminho = _resolver_video(p_meta["video"])
        except Exception:
            pass
    if not caminho and os.path.exists(GOLS_JSON):
        try:
            with open(GOLS_JSON, encoding="utf-8-sig") as f:
                g_meta = json.load(f)
                if g_meta.get("video"):
                    caminho = _resolver_video(g_meta["video"])
        except Exception:
            pass
    if not caminho or not os.path.isfile(caminho):
        raise HTTPException(404, "video nao encontrado")
    return FileResponse(caminho, media_type="video/mp4")


@app.get("/api/explorar")
def api_explorar(caminho: Optional[str] = None):
    """Navegador de pastas do computador (pra escolher o video de qualquer
    lugar, sem precisar copiar/mover pra dentro do projeto)."""
    alvo = os.path.abspath(os.path.expanduser(caminho)) if caminho else _pasta_inicial()
    if not os.path.isdir(alvo):
        alvo = _pasta_inicial()
    try:
        nomes = sorted(os.listdir(alvo), key=str.lower)
    except PermissionError:
        pai = os.path.dirname(alvo)
        return {"atual": alvo, "pai": pai if pai != alvo else None,
                "pastas": [], "videos": [], "erro": "sem permissão para ler esta pasta"}
    pastas, videos = [], []
    for nome in nomes:
        if nome.startswith("."):
            continue
        caminho_item = os.path.join(alvo, nome)
        if os.path.isdir(caminho_item):
            pastas.append({"nome": nome, "caminho": caminho_item})
        elif nome.lower().endswith(VIDEO_EXTS):
            videos.append({"nome": nome, "caminho": caminho_item,
                           "duracao_s": _ffprobe_duracao(caminho_item)})
    pai = os.path.dirname(alvo)
    pai_caminho = pai if pai != alvo else None

    # No Windows, se estivermos na raiz de uma unidade (ex: C:\), lista outras unidades disponiveis
    if sys.platform == "win32" and pai_caminho is None:
        import string
        for letra in string.ascii_uppercase:
            unidade = f"{letra}:\\"
            if unidade.lower() != alvo.lower() and os.path.exists(unidade):
                pastas.insert(0, {"nome": f"Unidade ({letra}:)", "caminho": unidade})

    return {"atual": alvo, "pai": pai_caminho,
            "pastas": pastas, "videos": videos}


# --------------------------------------------------------------- download do YouTube

class YoutubeDownload(BaseModel):
    url: str


@app.post("/api/video/youtube")
def api_baixar_youtube(body: YoutubeDownload):
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "Informe a URL do vídeo do YouTube")
    if not ("youtube.com" in url or "youtu.be" in url):
        raise HTTPException(400, "URL precisa ser do YouTube (ex: youtube.com ou youtu.be)")

    meta_file = os.path.join(VIDEOS_DIR, f".yt_job_{uuid.uuid4().hex[:8]}.json")
    cmd = [
        sys.executable, "baixar_youtube.py",
        "--url", url,
        "--output_dir", VIDEOS_DIR,
        "--meta_file", meta_file
    ]
    job_id = _iniciar_job(cmd)
    with JOBS[job_id]["lock"]:
        JOBS[job_id]["meta_file"] = meta_file
    return {"job_id": job_id}


@app.get("/api/video/youtube/resultado/{job_id}")
def api_resultado_youtube(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    meta_file = job.get("meta_file")
    if meta_file and os.path.exists(meta_file):
        try:
            with open(meta_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    with job["lock"]:
        for linha in reversed(job.get("log", [])):
            if "METADADOS_JSON:" in linha:
                try:
                    payload = linha.split("METADADOS_JSON:", 1)[1].strip()
                    return json.loads(payload)
                except Exception:
                    pass
    raise HTTPException(400, "Resultado do vídeo ainda não disponível ou o download falhou")


# --------------------------------------------------------------- placar (regiao)

@app.post("/api/frame")
def api_frame(payload: dict = Body(...)):
    video = _resolver_video(payload["video"])
    tempo_s = float(payload.get("tempo_s", 0))
    frame = _capturar_frame(video, tempo_s)
    if frame is None:
        raise HTTPException(400, "nao consegui ler um frame nesse instante")
    return _png_response(frame)


class PlacarRect(BaseModel):
    video: str
    rect: List[int]
    tempo_s: float = 0.0


@app.post("/api/placar")
def api_salvar_placar(body: PlacarRect):
    if len(body.rect) != 4 or body.rect[2] <= 0 or body.rect[3] <= 0:
        raise HTTPException(400, "retangulo invalido")
    video = _resolver_video(body.video)
    with open(PLACAR_FILE, "w", encoding="utf-8") as f:
        json.dump({"placar": body.rect}, f)
    frame = _capturar_frame(video, body.tempo_s)
    if frame is None:
        return {"ok": True, "preview": None}
    return {"ok": True, "preview": _png_base64(_recorte_zoom(frame, body.rect))}


@app.get("/api/placar")
def api_get_placar():
    rect = _carregar_placar_rect()
    return {"rect": rect}


@app.post("/api/placar/preview")
def api_preview_placar(payload: dict = Body(...)):
    video = _resolver_video(payload["video"])
    tempo_s = float(payload.get("tempo_s", 0))
    rect = payload.get("rect") or _carregar_placar_rect()
    if not rect:
        raise HTTPException(400, "regiao do placar ainda nao definida")
    frame = _capturar_frame(video, tempo_s)
    if frame is None:
        raise HTTPException(400, "nao consegui ler um frame nesse instante")
    return _png_response(_recorte_zoom(frame, rect))


# --------------------------------------------------------------- zonas-gatilho (varias regioes)

def _carregar_zonas() -> List[List[int]]:
    if not os.path.exists(ZONAS_FILE):
        return []
    try:
        with open(ZONAS_FILE, encoding="utf-8-sig") as f:
            return json.load(f).get("zonas", [])
    except Exception:
        return []


class ZonasBody(BaseModel):
    video: str
    zonas: List[List[int]]


@app.post("/api/zonas")
def api_salvar_zonas(body: ZonasBody):
    """Salva a lista de zonas-gatilho (retangulos no quadro, ex.: a boca de
    cada gol) usadas pela deteccao por movimento (detectar_zonas.py) - ver
    /api/zonas/detectar/iniciar. Sobrescreve a lista inteira a cada chamada,
    igual ao /api/placar faz com o retangulo unico do placar."""
    for r in body.zonas:
        if len(r) != 4 or r[2] <= 0 or r[3] <= 0:
            raise HTTPException(400, "retangulo invalido")
    _resolver_video(body.video)
    with open(ZONAS_FILE, "w", encoding="utf-8") as f:
        json.dump({"zonas": body.zonas}, f)
    return {"ok": True, "total": len(body.zonas)}


@app.get("/api/zonas")
def api_get_zonas():
    return {"zonas": _carregar_zonas()}


# --------------------------------------------------------------- deteccao de gols

class IniciarDeteccao(BaseModel):
    video: str
    gols_totais: Optional[int] = None
    limiar: Optional[float] = None
    fixo: bool = False
    metade: str = "baixo"
    inicio: Optional[str] = None
    fim: Optional[str] = None


@app.post("/api/detectar/iniciar")
def api_iniciar_deteccao(body: IniciarDeteccao):
    video = _resolver_video(body.video)
    if not os.path.exists(PLACAR_FILE):
        raise HTTPException(400, "marque a regiao do placar antes")
    cmd = [sys.executable, "detectar_gols.py", "--source_video_path", video,
           "--output_dir", "gols", "--placar_file", "placar.json",
           "--metade", body.metade]
    if body.fixo:
        cmd.append("--fixo")
    if body.gols_totais:
        cmd += ["--gols", str(body.gols_totais)]
    if body.limiar is not None:
        cmd += ["--limiar", str(body.limiar)]
    if body.inicio:
        cmd += ["--inicio", body.inicio]
    if body.fim:
        cmd += ["--fim", body.fim]
    return {"job_id": _iniciar_job(cmd)}


class IniciarDeteccaoZonas(BaseModel):
    video: str
    eventos_esperados: Optional[int] = None
    limiar: Optional[float] = None
    inicio: Optional[str] = None
    fim: Optional[str] = None


@app.post("/api/zonas/detectar/iniciar")
def api_iniciar_deteccao_zonas(body: IniciarDeteccaoZonas):
    """Roda detectar_zonas.py: acha jogadas por MOVIMENTO nas zonas-gatilho
    marcadas (ver /api/zonas) e ACRESCENTA os eventos achados ao gols.json
    existente (nao apaga o que ja tinha - gol do placar, jogada manual etc),
    continuando a sequencia de indice. Depois e so chamar
    POST /api/cortar/iniciar de novo pra cortar os clipes novos junto com
    os demais."""
    video = _resolver_video(body.video)
    if not _carregar_zonas():
        raise HTTPException(400, "marque ao menos uma zona-gatilho antes (passo 2)")
    cmd = [sys.executable, "detectar_zonas.py", "--source_video_path", video,
           "--zonas_file", "zonas.json", "--output_dir", "gols"]
    if body.eventos_esperados:
        cmd += ["--eventos", str(body.eventos_esperados)]
    if body.limiar is not None:
        cmd += ["--limiar", str(body.limiar)]
    if body.inicio:
        cmd += ["--inicio", body.inicio]
    if body.fim:
        cmd += ["--fim", body.fim]
    return {"job_id": _iniciar_job(cmd)}


@app.get("/api/gols")
def api_get_gols(video: Optional[str] = None):
    """Le o gols.json (gerado pela deteccao ou ja confirmado). A revisao de
    verdade (foi gol ou nao) acontece assistindo o clipe ja cortado - ver
    /api/gols/descartar - entao aqui e so a lista, sem miniaturas."""
    if video:
        try:
            _resolver_video(video)
        except Exception:
            pass
    if not os.path.exists(GOLS_JSON):
        return {"eventos": [], "video": None}
    with open(GOLS_JSON, encoding="utf-8-sig") as f:
        dados = json.load(f)
        eventos = dados.get("gols", [])
        v_nome = dados.get("video")
    return {"eventos": eventos, "video": v_nome}


class GolEvento(BaseModel):
    tempo_s: float


class ConfirmarGols(BaseModel):
    video: str
    eventos: List[GolEvento]


@app.post("/api/gols")
def api_confirmar_gols(body: ConfirmarGols):
    video = _resolver_video(body.video)
    tempos = sorted(ev.tempo_s for ev in body.eventos)
    eventos = []
    for k, t in enumerate(tempos, 1):
        eventos.append({
            "indice": k, "tempo_s": round(t, 2), "tempo": _fmt_tempo(t),
            "inicio_s": round(max(t - ANTES_S, 0), 2),
            "fim_s": round(t + DEPOIS_S, 2), "fonte": "revisado",
            "status": None, "lance": None,
        })
    os.makedirs(GOLS_DIR, exist_ok=True)
    with open(GOLS_JSON, "w", encoding="utf-8") as f:
        json.dump({"video": os.path.basename(video), "fonte": "revisado",
                   "gols": eventos}, f, indent=2, ensure_ascii=False)
    return {"ok": True, "total": len(eventos)}


# --------------------------------------------------------------- corte dos clipes

class IniciarCorte(BaseModel):
    video: str


@app.post("/api/cortar/iniciar")
def api_iniciar_corte(body: IniciarCorte):
    video = _resolver_video(body.video)
    if not os.path.exists(GOLS_JSON):
        raise HTTPException(400, "confirme os gols antes de cortar")
    cmd = [sys.executable, "detectar_gols.py", "--source_video_path", video,
           "--cortar", "--output_dir", "gols", "--placar_file", "placar.json"]
    return {"job_id": _iniciar_job(cmd)}


class AdicionarGol(BaseModel):
    video: Optional[str] = None
    tempo_s: Optional[float] = None
    inicio_s: Optional[float] = None
    fim_s: Optional[float] = None
    status: Optional[str] = None
    lance: Optional[str] = None


def _atualizar_partida_indices(mapa_indices: dict):
    if not os.path.exists(PARTIDA_JSON) or not mapa_indices:
        return
    try:
        with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
            partida = json.load(f)
        for chave in ("gols", "lances", "_todosGols"):
            if chave in partida and isinstance(partida[chave], list):
                for item in partida[chave]:
                    if isinstance(item, dict) and "indice" in item:
                        old = item["indice"]
                        if old in mapa_indices:
                            item["indice"] = mapa_indices[old]
        if "roteiro" in partida and isinstance(partida["roteiro"], list):
            for item in partida["roteiro"]:
                if isinstance(item, dict) and "i" in item:
                    old = item["i"]
                    if old in mapa_indices:
                        item["i"] = mapa_indices[old]
        if "descartados" in partida and isinstance(partida["descartados"], list):
            partida["descartados"] = [mapa_indices.get(idx, idx) for idx in partida["descartados"]]
        with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
            json.dump(partida, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


@app.post("/api/gols/adicionar")
def api_adicionar_gol(body: AdicionarGol):
    """Cria um novo clipe sem alterar, renomear ou apagar nenhum clipe existente.
    O clipe recebe um índice novo exclusivo e é cortado para gol_{novo_indice:02d}.mp4.
    A ordenação cronológica é garantida por tempo_s."""
    if body.inicio_s is not None and body.fim_s is not None:
        if body.fim_s <= body.inicio_s:
            raise HTTPException(400, "fim tem que ser maior que o inicio")
        inicio_s, fim_s = body.inicio_s, body.fim_s
        tempo_s = body.tempo_s if body.tempo_s is not None else inicio_s
    elif body.tempo_s is not None:
        tempo_s = body.tempo_s
        inicio_s = max(tempo_s - ANTES_S, 0)
        fim_s = tempo_s + DEPOIS_S
    else:
        raise HTTPException(400, "informe tempo_s ou inicio_s/fim_s")

    video_caminho = body.video
    if not video_caminho and os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p_meta = json.load(f).get("meta", {})
                if p_meta.get("video"):
                    video_caminho = p_meta["video"]
        except Exception:
            pass
    if not video_caminho and os.path.exists(GOLS_JSON):
        try:
            with open(GOLS_JSON, encoding="utf-8-sig") as f:
                g_meta = json.load(f)
                if g_meta.get("video"):
                    video_caminho = g_meta["video"]
        except Exception:
            pass

    video = _resolver_video(video_caminho)
    dados = {"video": os.path.basename(video), "fonte": "manual", "gols": []}
    if os.path.exists(GOLS_JSON):
        with open(GOLS_JSON, encoding="utf-8-sig") as f:
            dados = json.load(f)
    existentes = dados.get("gols", [])

    # Descobre todos os índices já em uso para NUNCA colidir nem sobrescrever
    indices_usados = set()
    for ev in existentes:
        if "indice" in ev and isinstance(ev["indice"], int):
            indices_usados.add(ev["indice"])

    os.makedirs(CLIPES_DIR, exist_ok=True)
    for f in os.listdir(CLIPES_DIR):
        m = re.search(r"gol_(\d+)", f)
        if m:
            indices_usados.add(int(m.group(1)))

    novo_indice = max(indices_usados, default=0) + 1
    while os.path.exists(os.path.join(CLIPES_DIR, f"gol_{novo_indice:02d}.mp4")):
        novo_indice += 1

    novo_evento = {
        "indice": novo_indice,
        "tempo_s": round(tempo_s, 2),
        "tempo": _fmt_tempo(tempo_s),
        "inicio_s": round(inicio_s, 2),
        "fim_s": round(fim_s, 2),
        "fonte": "manual",
        "status": body.status,
        "lance": body.lance,
    }
    existentes.append(novo_evento)

    dados["gols"] = existentes
    os.makedirs(GOLS_DIR, exist_ok=True)
    with open(GOLS_JSON, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

    # Corta APENAS o novo clipe diretamente com ffmpeg para o arquivo exclusivo
    dur = round(fim_s - inicio_s, 2)
    saida_clipe = os.path.join(CLIPES_DIR, f"gol_{novo_indice:02d}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(inicio_s), "-i", video, "-t", str(dur),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-avoid_negative_ts", "make_zero", saida_clipe,
    ], check=False)

    # Se partida.json existir, inclui o novo evento sem alterar os existentes
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                partida = json.load(f)
            if "_todosGols" in partida and isinstance(partida["_todosGols"], list):
                novo_p = dict(novo_evento)
                novo_p["tipo"] = "gol" if (body.status == "gol" or not body.status) else "lance"
                novo_p["descartado"] = False
                novo_p["time"] = None
                novo_p["autor"] = None
                novo_p["assist"] = None
                novo_p["destaque"] = None
                partida["_todosGols"].append(novo_p)
            with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                json.dump(partida, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return {"ok": True, "indice": novo_indice, "total": len(existentes)}


class ConfirmarGol(BaseModel):
    indice: int
    status: Optional[str] = None  # "gol", "defesaca", "trave", "quase_gol", "drible", "bola_perdida", "confusao", "lance" ou None (limpa)
    lance: Optional[str] = None
    time: Optional[int] = None
    autor: Optional[str] = None
    assist: Optional[str] = None
    destaque: Optional[str] = None


@app.post("/api/gols/confirmar")
def api_confirmar_gol(body: ConfirmarGol):
    """Usado na tela de revisao dos cortes e na tela de marcacao: marca tipo de clipe, time, autor, assistencia e destaque."""
    with GOLS_LOCK:
        if not os.path.exists(GOLS_JSON):
            raise HTTPException(400, "gols.json nao existe")
        with open(GOLS_JSON, encoding="utf-8-sig") as f:
            dados = json.load(f)
        achou = False
        ev_modificado = None
        for ev in dados.get("gols", []):
            if ev["indice"] == body.indice:
                fields = body.model_fields_set
                if body.status is None:
                    ev.pop("status", None)
                    ev.pop("lance", None)
                    ev.pop("time", None)
                    ev.pop("autor", None)
                    ev.pop("assist", None)
                    ev.pop("destaque", None)
                else:
                    ev["status"] = body.status
                    if "lance" in fields:
                        if body.lance is not None: ev["lance"] = body.lance
                        else: ev.pop("lance", None)
                    elif body.status == "gol":
                        ev.pop("lance", None)

                    if "time" in fields:
                        if body.time is not None: ev["time"] = body.time
                        else: ev.pop("time", None)

                    if ev.get("time") is None:
                        ev.pop("autor", None)
                        ev.pop("assist", None)
                        ev.pop("destaque", None)
                    else:
                        if "autor" in fields:
                            if body.autor is not None: ev["autor"] = body.autor
                            else: ev.pop("autor", None)
                        elif body.status != "gol":
                            ev.pop("autor", None)

                        if "assist" in fields:
                            if body.assist is not None: ev["assist"] = body.assist
                            else: ev.pop("assist", None)
                        elif body.status != "gol":
                            ev.pop("assist", None)

                        if "destaque" in fields:
                            if body.destaque is not None: ev["destaque"] = body.destaque
                            else: ev.pop("destaque", None)
                        elif body.status == "gol":
                            ev.pop("destaque", None)
                achou = True
                ev_modificado = ev
                break
        if not achou:
            ev = None
            if os.path.exists(PARTIDA_JSON):
                try:
                    with open(PARTIDA_JSON, encoding="utf-8-sig") as pf:
                        p_tmp = json.load(pf)
                    for g in p_tmp.get("_todosGols", []):
                        if g.get("indice") == body.indice:
                            ev = {
                                "indice": body.indice,
                                "tempo": g.get("tempo"),
                                "tempo_s": g.get("tempo_s"),
                                "inicio_s": g.get("inicio_s"),
                                "fim_s": g.get("fim_s"),
                                "fonte": g.get("fonte") or "revisado"
                            }
                            break
                except Exception:
                    pass
            if not ev:
                ev = {"indice": body.indice, "fonte": "revisado"}
            dados.setdefault("gols", []).append(ev)
            achou = True
            ev_modificado = ev
            fields = body.model_fields_set
            if body.status is not None:
                ev["status"] = body.status
                if "lance" in fields and body.lance is not None: ev["lance"] = body.lance
                if "time" in fields and body.time is not None: ev["time"] = body.time
                if ev.get("time") is not None:
                    if "autor" in fields and body.autor is not None: ev["autor"] = body.autor
                    if "assist" in fields and body.assist is not None: ev["assist"] = body.assist
                    if "destaque" in fields and body.destaque is not None: ev["destaque"] = body.destaque

        with open(GOLS_JSON, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)

        # Atualiza em partida.json se existir
        if os.path.exists(PARTIDA_JSON):
            try:
                with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                    p = json.load(f)

                fields = body.model_fields_set
                if "_todosGols" in p and isinstance(p["_todosGols"], list):
                    for g in p["_todosGols"]:
                        if g.get("indice") == body.indice:
                            g["status"] = body.status
                            if body.status is None:
                                g["tipo"] = None
                                g["lance"] = None
                                g["time"] = None
                                g["autor"] = None
                                g["assist"] = None
                                g["destaque"] = None
                            elif body.status == "gol":
                                g["tipo"] = "gol"
                                g["lance"] = None
                                g.pop("destaque", None)
                                if "time" in fields: g["time"] = body.time
                                if g.get("time") is None:
                                    g["autor"] = None
                                    g["assist"] = None
                                else:
                                    if "autor" in fields: g["autor"] = body.autor
                                    if "assist" in fields: g["assist"] = body.assist
                            else:
                                g["tipo"] = "lance"
                                if "lance" in fields: g["lance"] = body.lance
                                elif not g.get("lance"): g["lance"] = body.lance or "Lance"
                                if "time" in fields: g["time"] = body.time
                                if g.get("time") is None:
                                    g["destaque"] = None
                                else:
                                    if "destaque" in fields: g["destaque"] = body.destaque
                                g.pop("autor", None)
                                g.pop("assist", None)

                # Mantem sincronizadas as listas gols e lances em partida.json
                p["gols"] = [g for g in p.get("gols", []) if g.get("indice") != body.indice]
                p["lances"] = [l for l in p.get("lances", []) if l.get("indice") != body.indice]

                ev_info = ev_modificado or {}
                time_val = body.time if body.time is not None else ev_info.get("time")
                autor_val = body.autor if body.autor is not None else ev_info.get("autor")
                assist_val = body.assist if body.assist is not None else ev_info.get("assist")
                destaque_val = body.destaque if body.destaque is not None else ev_info.get("destaque")

                if body.status == "gol" and autor_val and time_val is not None:
                    times_list = p.get("times", [])
                    time_nome = times_list[time_val]["nome"] if (time_val is not None and time_val < len(times_list)) else None
                    p["gols"].append({
                        "indice": body.indice,
                        "tempo": ev_info.get("tempo"),
                        "tempo_s": ev_info.get("tempo_s"),
                        "inicio_s": ev_info.get("inicio_s"),
                        "fim_s": ev_info.get("fim_s"),
                        "tipo": "gol",
                        "status": "gol",
                        "time": time_val,
                        "time_nome": time_nome,
                        "autor": autor_val,
                        "assist": assist_val,
                        "fonte": ev_info.get("fonte")
                    })
                elif body.status and body.status != "gol":
                    p["lances"].append({
                        "indice": body.indice,
                        "tempo": ev_info.get("tempo"),
                        "tempo_s": ev_info.get("tempo_s"),
                        "inicio_s": ev_info.get("inicio_s"),
                        "fim_s": ev_info.get("fim_s"),
                        "tipo": "lance",
                        "status": body.status,
                        "lance": body.lance or ev_info.get("lance") or "Lance",
                        "time": time_val,
                        "destaque": destaque_val,
                        "fonte": ev_info.get("fonte")
                    })

                with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                    json.dump(p, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return {"ok": True}


class DescartarGol(BaseModel):
    indice: int


@app.post("/api/gols/descartar")
def api_descartar_gol(body: DescartarGol):
    """Usado na tela de revisao dos cortes: apaga o arquivo do clipe selecionado e remove de gols.json e partida.json.
    Nao falha se o arquivo ja tiver sido apagado ou for orfao. Exclusivamente apaga o clipe do indice informado."""
    with GOLS_LOCK:
        # Apaga o clipe correspondente ao índice no diretório de clipes
        if os.path.isdir(CLIPES_DIR):
            for nome_arq in os.listdir(CLIPES_DIR):
                m = re.match(r"^gol_0*(\d+)\.mp4$", nome_arq, re.IGNORECASE)
                if m and int(m.group(1)) == body.indice:
                    caminho_clipe = os.path.join(CLIPES_DIR, nome_arq)
                    try:
                        os.remove(caminho_clipe)
                    except Exception:
                        pass

        restantes = []
        if os.path.exists(GOLS_JSON):
            try:
                with open(GOLS_JSON, encoding="utf-8-sig") as f:
                    dados = json.load(f)
                restantes = [ev for ev in dados.get("gols", []) if ev.get("indice") != body.indice]
                dados["gols"] = restantes
                with open(GOLS_JSON, "w", encoding="utf-8") as f:
                    json.dump(dados, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        if os.path.exists(PARTIDA_JSON):
            try:
                with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                    p = json.load(f)
                p["gols"] = [g for g in p.get("gols", []) if g.get("indice") != body.indice]
                p["lances"] = [l for l in p.get("lances", []) if l.get("indice") != body.indice]
                if "roteiro" in p and isinstance(p["roteiro"], list):
                    p["roteiro"] = [r for r in p["roteiro"] if r.get("i") != body.indice and r.get("indice") != body.indice]
                if "_todosGols" in p and isinstance(p["_todosGols"], list):
                    p["_todosGols"] = [g for g in p["_todosGols"] if g.get("indice") != body.indice]
                if "descartados" in p and isinstance(p["descartados"], list):
                    p["descartados"] = [d for d in p["descartados"] if d != body.indice]
                with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                    json.dump(p, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return {"ok": True, "indice": body.indice, "restantes": len(restantes)}


@app.get("/api/clipes")
def api_clipes():
    if not os.path.exists(GOLS_JSON) or not os.path.isdir(CLIPES_DIR):
        return {"clipes": []}
    with open(GOLS_JSON, encoding="utf-8-sig") as f:
        eventos = {ev["indice"]: ev for ev in json.load(f).get("gols", [])}

    partida_meta = {}
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as pf:
                p_data = json.load(pf)
                for g in p_data.get("_todosGols", []):
                    if "indice" in g:
                        partida_meta[g["indice"]] = g
        except Exception:
            pass

    clipes = []
    for nome in sorted(os.listdir(CLIPES_DIR)):
        if not nome.lower().endswith(".mp4"):
            continue
        m = re.search(r"gol_(\d+)", nome)
        if not m:
            continue
        indice = int(m.group(1))
        ev = eventos.get(indice, {})
        p_ev = partida_meta.get(indice, {})

        inicio_s = ev.get("inicio_s")
        fim_s = ev.get("fim_s")
        tempo_s = ev.get("tempo_s")
        if inicio_s is None and tempo_s is not None:
            inicio_s = max(0.0, tempo_s - 20.0)
        if fim_s is None and tempo_s is not None:
            fim_s = tempo_s + 4.0
        if tempo_s is None and inicio_s is not None:
            tempo_s = inicio_s + 20.0

        status_val = ev.get("status")
        lance_val = ev.get("lance")
        if status_val is None and p_ev:
            p_st = p_ev.get("status")
            if p_st and (p_ev.get("time") is not None or p_ev.get("autor") or p_ev.get("lance") or p_st != "gol"):
                status_val = p_st
                lance_val = p_ev.get("lance")
        time_val = ev.get("time") if ev.get("time") is not None else p_ev.get("time")
        autor_val = ev.get("autor") or p_ev.get("autor")
        assist_val = ev.get("assist") or p_ev.get("assist")
        destaque_val = ev.get("destaque") or p_ev.get("destaque")

        clipes.append({
            "indice": indice, "arquivo": nome, "url": f"/video/clipes/{nome}",
            "tempo": ev.get("tempo") or (_fmt_tempo(tempo_s) if tempo_s is not None else None),
            "tempo_s": tempo_s,
            "inicio_s": inicio_s,
            "fim_s": fim_s,
            "duracao_s": round(fim_s - inicio_s, 2) if (fim_s is not None and inicio_s is not None) else None,
            "status": status_val, "lance": lance_val, "placar": ev.get("placar"),
            "time": time_val, "autor": autor_val, "assist": assist_val, "destaque": destaque_val,
        })
    # Ordenado cronologicamente pelo tempo_s (ou inicio_s) do clip
    return {"clipes": sorted(clipes, key=lambda c: (c.get("tempo_s") if c.get("tempo_s") is not None else 999999, c["indice"]))}


@app.api_route("/video/clipes/{nome}", methods=["GET", "HEAD"])
def video_clipe(nome: str):
    caminho = os.path.join(CLIPES_DIR, nome)
    if not os.path.isfile(caminho):
        raise HTTPException(404)
    return FileResponse(caminho, media_type="video/mp4")


# --------------------------------------------------------------- partida (marcacao)

@app.get("/api/partida")
def api_get_partida():
    if not os.path.exists(PARTIDA_JSON):
        return JSONResponse(None)
    with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
        return json.load(f)


@app.post("/api/partida")
def api_salvar_partida(payload: dict = Body(...)):
    with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return {"ok": True}


# --------------------------------------------------------------- uploads: logo e fotos dos jogadores

FOTOS_DIR = os.path.join(WEB_DIR, "fotos")
os.makedirs(FOTOS_DIR, exist_ok=True)


class UploadLogoPayload(BaseModel):
    imagem_b64: str


@app.post("/api/upload_logo")
def api_upload_logo(body: UploadLogoPayload):
    try:
        from io import BytesIO
        from PIL import Image

        b64 = body.imagem_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        img = Image.open(BytesIO(raw)).convert("RGBA")

        # Salva tanto na raiz quanto em web/ para servir estático
        caminho_raiz = os.path.join(PROJECT_DIR, "logo_campeonato.png")
        caminho_web = os.path.join(WEB_DIR, "logo_campeonato.png")
        img.save(caminho_raiz, "PNG")
        img.save(caminho_web, "PNG")

        return {"ok": True, "url": "/web/logo_campeonato.png"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao salvar logo: {e}")


class UploadFotoJogadorPayload(BaseModel):
    jogador: str
    time_idx: Optional[int] = None
    imagem_b64: str


@app.post("/api/upload_foto_jogador")
def api_upload_foto_jogador(body: UploadFotoJogadorPayload):
    try:
        from io import BytesIO
        from PIL import Image

        jogador = body.jogador.strip()
        if not jogador:
            raise HTTPException(status_code=400, detail="Nome do jogador obrigatorio")

        b64 = body.imagem_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        img = Image.open(BytesIO(raw)).convert("RGBA")

        # Redimensiona para maximo 300x300 mantendo proporcao
        img.thumbnail((300, 300), Image.Resampling.LANCZOS)

        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', jogador.lower())
        nome_arquivo = f"{slug}.png"
        caminho_foto = os.path.join(FOTOS_DIR, nome_arquivo)
        img.save(caminho_foto, "PNG")

        rel_url = f"/web/fotos/{nome_arquivo}"

        # Se partida.json existir, atualiza o mapa de fotos do time
        if os.path.exists(PARTIDA_JSON):
            try:
                with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                    p = json.load(f)
                times = p.get("times", [])
                if body.time_idx is not None and 0 <= body.time_idx < len(times):
                    times[body.time_idx].setdefault("fotos", {})[jogador] = rel_url
                else:
                    for t in times:
                        if jogador in t.get("jogadores", []):
                            t.setdefault("fotos", {})[jogador] = rel_url
                with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                    json.dump(p, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return {"ok": True, "url": rel_url, "jogador": jogador}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao salvar foto do jogador: {e}")


class RemoverFotoJogadorPayload(BaseModel):
    jogador: str
    time_idx: Optional[int] = None


@app.post("/api/remover_foto_jogador")
def api_remover_foto_jogador(body: RemoverFotoJogadorPayload):
    jogador = body.jogador.strip()
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', jogador.lower())
    nome_arquivo = f"{slug}.png"
    caminho_foto = os.path.join(FOTOS_DIR, nome_arquivo)
    if os.path.exists(caminho_foto):
        try:
            os.remove(caminho_foto)
        except Exception:
            pass

    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p = json.load(f)
            times = p.get("times", [])
            if body.time_idx is not None and 0 <= body.time_idx < len(times):
                times[body.time_idx].get("fotos", {}).pop(jogador, None)
            else:
                for t in times:
                    t.get("fotos", {}).pop(jogador, None)
            with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                json.dump(p, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return {"ok": True}


# --------------------------------------------------------------- fundo e ajustes das cartelas

class CapturarFundoPayload(BaseModel):
    video: Optional[str] = None
    tempo_s: float = 0.0


@app.post("/api/cartelas/fundo/capturar")
def api_capturar_fundo_cartela(body: CapturarFundoPayload):
    from PIL import Image
    video = _resolver_video(body.video) if body.video else None
    if not video and os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p = json.load(f)
            video = p.get("meta", {}).get("video")
        except Exception:
            pass
    if not video:
        raise HTTPException(400, "Vídeo da partida não especificado")
    
    video = _resolver_video(video)
    frame = _capturar_frame(video, body.tempo_s)
    if frame is None:
        raise HTTPException(400, "Não consegui capturar um frame neste instante do vídeo")
    
    try:
        rgb_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_raw = Image.fromarray(rgb_raw).resize((1920, 1080), Image.Resampling.LANCZOS)
        img_raw.save(os.path.join(PROJECT_DIR, "fundo_raw.png"), "PNG")
        img_raw.save(os.path.join(WEB_DIR, "fundo_raw.png"), "PNG")
    except Exception as e:
        print(f"Aviso ao salvar fundo_raw: {e}")

    return {
        "ok": True,
        "preview": _png_base64(frame),
        "raw_url": f"/web/fundo_raw.png?t={int(time.time()*1000)}",
        "tempo_s": body.tempo_s
    }


class AjustarFundoPayload(BaseModel):
    video: Optional[str] = None
    tempo_s: float = 0.0
    brilho: float = 1.25
    saturacao: float = 1.45
    contraste: float = 1.12
    desfoque: float = 0.0
    vinheta: float = 0.0
    aplicar_video_clipes: bool = False


@app.post("/api/cartelas/fundo/salvar")
def api_salvar_fundo_cartela(body: AjustarFundoPayload):
    from PIL import Image, ImageEnhance, ImageFilter
    video = _resolver_video(body.video) if body.video else None
    if not video and os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p = json.load(f)
            video = p.get("meta", {}).get("video")
        except Exception:
            pass
    if not video:
        raise HTTPException(400, "Vídeo da partida não especificado")
    
    video = _resolver_video(video)
    frame = _capturar_frame(video, body.tempo_s)
    if frame is None:
        raise HTTPException(400, "Não consegui ler o frame do vídeo")
    
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    raw_pil = Image.fromarray(rgb).resize((1920, 1080), Image.Resampling.LANCZOS)
    try:
        raw_pil.save(os.path.join(PROJECT_DIR, "fundo_raw.png"), "PNG")
        raw_pil.save(os.path.join(WEB_DIR, "fundo_raw.png"), "PNG")
    except Exception:
        pass
    img = raw_pil.copy()
    
    if body.brilho != 1.0:
        img = ImageEnhance.Brightness(img).enhance(body.brilho)
    if body.saturacao != 1.0:
        img = ImageEnhance.Color(img).enhance(body.saturacao)
    if body.contraste != 1.0:
        img = ImageEnhance.Contrast(img).enhance(body.contraste)
    if body.desfoque > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=body.desfoque))
    if body.vinheta > 0:
        alpha = int(255 * min(max(body.vinheta / 100.0, 0.0), 1.0))
        overlay = Image.new("RGBA", (1920, 1080), (11, 15, 23, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    
    caminho_raiz = os.path.join(PROJECT_DIR, "fundo_cartela.png")
    caminho_web = os.path.join(WEB_DIR, "fundo_cartela.png")
    img.save(caminho_raiz, "PNG")
    img.save(caminho_web, "PNG")
    
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p = json.load(f)
            if "meta" not in p:
                p["meta"] = {}
            p["meta"]["fundo_cartela"] = "fundo_cartela.png"
            p["meta"]["fundo_config"] = body.model_dump() if hasattr(body, "model_dump") else body.dict()
            with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                json.dump(p, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    return {"ok": True, "url": f"/web/fundo_cartela.png?t={int(time.time()*1000)}"}


@app.post("/api/cartelas/fundo/restaurar")
def api_restaurar_fundo_cartela():
    for cand in [os.path.join(PROJECT_DIR, "fundo_cartela.png"), os.path.join(WEB_DIR, "fundo_cartela.png")]:
        if os.path.exists(cand):
            try:
                os.remove(cand)
            except Exception:
                pass
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                p = json.load(f)
            if "meta" in p:
                p["meta"].pop("fundo_cartela", None)
                p["meta"].pop("fundo_config", None)
            with open(PARTIDA_JSON, "w", encoding="utf-8") as f:
                json.dump(p, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/cartelas/preview/{tipo}")
def api_preview_cartela(tipo: str):
    import io
    from PIL import Image
    import montar_video
    if not os.path.exists(PARTIDA_JSON):
        raise HTTPException(400, "partida.json não encontrado")
    with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
        d = json.load(f)
    
    if tipo == "abertura":
        img = montar_video.cartela_abertura(d)
    elif tipo == "fim_de_jogo":
        img = montar_video.cartela_fim_de_jogo(d)
    elif tipo == "destaques":
        img = montar_video.cartela_destaques(d)
    elif tipo == "cronologia":
        img = montar_video.cartela_cronologia(d)
    elif tipo in ("placar", "lance", "jogo"):
        ev = None
        for g in d.get("gols", []):
            if g.get("autor"):
                ev = g
                break
        if not ev:
            ev = {"autor": "Jogador", "tempo": "10:00", "time": 0, "assist": "Companheiro"}
        t_gol = ev.get("time", 0)
        ov = montar_video.cartela_lance(
            ev, d["times"], "gol", 1, 0,
            gol_neste_clipe=True, time_gol=t_gol, d_=d
        )
        bg = montar_video.criar_fundo_base(d)
        img = Image.alpha_composite(bg.convert("RGBA"), ov).convert("RGB")
    else:
        raise HTTPException(400, f"Tipo de cartela desconhecido: {tipo}")
    
    prev = img.resize((960, 540), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    prev.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# --------------------------------------------------------------- montagem final

class IniciarMontagem(BaseModel):
    abertura: float = 7.0
    fechamento: float = 8.0
    sem_audio: bool = False
    sem_abertura: bool = False
    sem_fechamento: bool = False
    roteiro: list[int] | None = None


@app.post("/api/montar/iniciar")
def api_iniciar_montagem(body: IniciarMontagem):
    if not os.path.exists(PARTIDA_JSON):
        raise HTTPException(400, "marque autor/assistencia antes de montar")
    cmd = [sys.executable, "montar_video.py", "--partida", "partida.json",
           "--clipes", "gols/clipes", "--saida", "final/melhores_momentos.mp4",
           "--saida_gols", "final/apenas_gols.mp4",
           "--abertura", str(body.abertura), "--fechamento", str(body.fechamento)]
    if body.roteiro:
        cmd.extend(["--roteiro", ",".join(str(i) for i in body.roteiro)])
    if body.sem_audio:
        cmd.append("--sem_audio")
    if body.sem_abertura:
        cmd.append("--sem_abertura")
    if body.sem_fechamento:
        cmd.append("--sem_fechamento")
    
    fc = {}
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                fc = json.load(f).get("meta", {}).get("fundo_config", {})
        except Exception:
            pass

    if os.path.isfile(os.path.join(PROJECT_DIR, "fundo_cartela.png")):
        cmd.extend(["--fundo", "fundo_cartela.png"])
    if fc.get("aplicar_video_clipes"):
        if fc.get("brilho") is not None:
            cmd.extend(["--brilho", str(fc["brilho"])])
        if fc.get("saturacao") is not None:
            cmd.extend(["--saturacao", str(fc["saturacao"])])
        if fc.get("contraste") is not None:
            cmd.extend(["--contraste", str(fc["contraste"])])

    return {"job_id": _iniciar_job(cmd)}


@app.api_route("/video/final", methods=["GET", "HEAD"])
def video_final():
    if not os.path.isfile(FINAL_VIDEO):
        raise HTTPException(404)
    return FileResponse(FINAL_VIDEO, media_type="video/mp4", filename="melhores_momentos.mp4")


@app.api_route("/video/final/gols", methods=["GET", "HEAD"])
def video_final_gols():
    if not os.path.isfile(FINAL_VIDEO_GOLS):
        raise HTTPException(404)
    return FileResponse(FINAL_VIDEO_GOLS, media_type="video/mp4", filename="apenas_gols.mp4")


# --------------------------------------------------------------- estado (retomar de onde parou)

@app.get("/api/estado")
def api_estado():
    n_gols = 0
    if os.path.exists(GOLS_JSON):
        try:
            with open(GOLS_JSON, encoding="utf-8-sig") as f:
                n_gols = len(json.load(f).get("gols", []))
        except Exception:
            n_gols = 0
    n_clipes = len([n for n in os.listdir(CLIPES_DIR) if n.endswith(".mp4")]) if os.path.isdir(CLIPES_DIR) else 0
    return {
        "placar_ok": os.path.exists(PLACAR_FILE),
        "gols_ok": n_gols > 0,
        "n_gols": n_gols,
        "clipes_ok": n_clipes > 0,
        "n_clipes": n_clipes,
        "partida_ok": os.path.exists(PARTIDA_JSON),
        "final_ok": os.path.isfile(FINAL_VIDEO),
        "final_gols_ok": os.path.isfile(FINAL_VIDEO_GOLS),
    }


# --------------------------------------------------------------- estatico / boot

@app.get("/")
def index():
    return FileResponse(
        os.path.join(WEB_DIR, "assistente.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    fav_ico = os.path.join(WEB_DIR, "favicon.ico")
    if os.path.isfile(fav_ico):
        return FileResponse(fav_ico, media_type="image/x-icon")
    fav_png = os.path.join(WEB_DIR, "favicon.png")
    if os.path.isfile(fav_png):
        return FileResponse(fav_png, media_type="image/png")
    return Response(status_code=404)


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", default=False)
    args = ap.parse_args()
    print(f"⚽ fut-bin assistente em http://{args.host}:{args.port}")
    if args.reload:
        uvicorn.run("assistente_web:app", host=args.host, port=args.port, reload=True, log_level="info")
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
