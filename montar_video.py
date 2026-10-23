"""
montar_video.py - monta o vídeo final de melhores momentos estilo transmissão esportiva.

ENTRADA:
  partida.json           exportado pelo assistente ou marcador
  gols/clipes/*.mp4      os cortes gerados pelo detector / revisão

SAÍDA:
  final/melhores_momentos.mp4
  final/apenas_gols.mp4

ESTRUTURA:
  abertura   -> pelada, competição, data, local, confronto (sem placar) e escalação tática com campo
  clipes     -> cada lance ordenado por TEMPO CRONOLÓGICO com placar eletrônico estilo SporTV
                atualizado dinamicamente após cada gol e faixa inferior de autor/assistência
  fechamento -> placar final profissional (Fim de Jogo) com lista de gols de cada time,
                cronologia completa ordenada por tempo e destaques (artilharia/assistências)
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from PIL import Image, ImageDraw, ImageFont, ImageFile
from video_quality import clip_command
ImageFile.LOAD_TRUNCATED_IMAGES = True

L, A = 1920, 1080
# Resolução de saída (altura). As cartelas são desenhadas em 1920x1080 e o
# segmento final é reescalado; 1080 mantém o comportamento original.
ALTURA_SAIDA = 1080

# Formato vertical (9:16): as cartelas continuam sendo desenhadas em 1920x1080 e ficam centralizadas
# sobre um fundo desfocado; os clipes são recortados por um retângulo 9:16 escolhido no quadro.
VERTICAL = False
LV, AV = 1080, 1920            # tela vertical base; a resolução final escala a partir dela
RECORTE = (0.21875, 0.0, 1.0)   # x, y (canto superior esquerdo) e altura do recorte, tudo de 0 a 1 do quadro


def obter_zoom_camera(ev: dict, camera: int) -> tuple:
    """Zoom (zoom, zoom_x, zoom_y) marcado para a câmera indicada deste lance.

    A câmera 1 usa os campos legados zoom/zoom_x/zoom_y (compatibilidade com
    partida.json/gols.json antigos). As câmeras 2 e 3 têm enquadramento
    próprio, guardado em zoom_por_camera, porque cada câmera física filma o
    jogo de um ângulo/distância diferente - o recorte de uma não serve pra
    outra. Sem marcação própria, a câmera extra começa sem zoom (1.0).
    """
    if int(camera) <= 1:
        return (
            float(ev.get("zoom", 1.0) or 1.0),
            float(ev.get("zoom_x", 0.5) if ev.get("zoom_x") is not None else 0.5),
            float(ev.get("zoom_y", 0.5) if ev.get("zoom_y") is not None else 0.5),
        )
    dados = (ev.get("zoom_por_camera") or {}).get(str(int(camera))) or {}
    return (
        float(dados.get("zoom", 1.0) or 1.0),
        float(dados.get("zoom_x", 0.5) if dados.get("zoom_x") is not None else 0.5),
        float(dados.get("zoom_y", 0.5) if dados.get("zoom_y") is not None else 0.5),
    )


def definir_zoom_camera(ev: dict, camera: int, zoom: float, zoom_x: float, zoom_y: float) -> None:
    """Grava o zoom da câmera indicada em `ev`, no mesmo formato usado por obter_zoom_camera."""
    if int(camera) <= 1:
        ev["zoom"], ev["zoom_x"], ev["zoom_y"] = zoom, zoom_x, zoom_y
        return
    por_camera = ev.setdefault("zoom_por_camera", {})
    por_camera[str(int(camera))] = {"zoom": zoom, "zoom_x": zoom_x, "zoom_y": zoom_y}


def escala_saida():
    """Filtro ffmpeg que leva o quadro-base à resolução escolhida."""
    if VERTICAL:
        if ALTURA_SAIDA == LV:
            return ""
        return f",scale={ALTURA_SAIDA}:{int(round(ALTURA_SAIDA * AV / LV / 2)) * 2}:flags=lanczos"
    if ALTURA_SAIDA == A:
        return ""
    largura = int(round(ALTURA_SAIDA * L / A / 2)) * 2
    return f",scale={largura}:{ALTURA_SAIDA}:flags=lanczos"


def filtro_recorte_vertical():
    """Recorta o retângulo 9:16 escolhido e leva à tela vertical base."""
    x0, y0, hf = RECORTE
    return (f"crop=w=ih*{hf:.4f}*9/16:h=ih*{hf:.4f}:x='min(iw*{x0:.4f},iw-ow)':y='min(ih*{y0:.4f},ih-oh)',"
            f"scale={LV}:{AV}:flags=lanczos")


def overlay_para_vertical(img):
    """Reorganiza a faixa de lance (1920x1080) para a tela vertical: placar no topo,
    marca d'água no canto e a faixa do lance embaixo, maiores para ler no celular."""
    import numpy as np
    saida = Image.new("RGBA", (LV, AV), (0, 0, 0, 0))
    alfa = np.array(img.getchannel("A")) > 0
    if not alfa.any():
        return saida

    def bbox(mascara):
        ys, xs = np.where(mascara)
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None

    corte_y = A // 5
    topo = alfa.copy(); topo[corte_y:] = False
    base = alfa.copy(); base[:corte_y] = False
    # Topo: separa o placar (esquerda) da marca d'água (direita) pelo maior vazio entre eles.
    cols = np.where(topo.any(axis=0))[0]
    grupos, ini, ant = [], None, None
    for c in cols:
        if ini is None:
            ini = ant = int(c)
        elif c > ant + 40:
            grupos.append((ini, ant + 1)); ini = ant = int(c)
        else:
            ant = int(c)
    if ini is not None:
        grupos.append((ini, ant + 1))

    def colar(regiao, escala, x, y):
        b = bbox(regiao)
        if not b:
            return
        rec = img.crop(b)
        rec = rec.resize((max(1, int(rec.width * escala)), max(1, int(rec.height * escala))), Image.Resampling.LANCZOS)
        saida.alpha_composite(rec, (max(0, x if x >= 0 else LV + x - rec.width), y))

    margem = 40
    for k, (x0, x1) in enumerate(grupos):
        regiao = topo.copy(); regiao[:, :x0] = False; regiao[:, x1:] = False
        if k == 0 and len(grupos) > 1:
            colar(regiao, 1.4, margem, 150)        # placar
        else:
            colar(regiao, 1.6, -margem, 150)       # marca d'agua (alinhada a direita)
    b = bbox(base)
    if b:
        escala = min(2.0, (LV - 2 * margem) / (b[2] - b[0]))
        altura = int((b[3] - b[1]) * escala)
        colar(base, escala, margem, AV - 380 - altura)   # acima da area coberta pela interface do celular
    return saida
FPS = 30
AUDIO_HZ = 48000
VIDEO_TIMESCALE = 90000
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"
AUDIO_FORMAT = f"aformat=sample_rates={AUDIO_HZ}:channel_layouts=stereo"
FUNDO = (11, 15, 23)
PAINEL = (18, 24, 38)
PAINEL_BORDA = (45, 55, 75)
TEXTO = (240, 244, 248)
FRACO = (145, 158, 175)

# ---------------------------------------------------------------- TEMA VISUAL
# "atual"  → estilo SporTV/Premiere dark (padrão)
# "fifa"   → estilo EA FC: fundo preto, bordas brancas limpas, placar pill centralizado
# "iss"    → estilo ISS Deluxe/SNES: retrô pixelado, cores vibrantes, bordas quadradas
# "pes"    → estilo PES/eFootball: minimalista, overlay translúcido cinza, texto branco
# "tv"     → estilo transmissão simples: sem cartela de fundo, texto sobreposto limpo
TEMA = "atual"  # alterado via --tema na linha de comando
VERDE = (34, 197, 94)
BRANCO = (255, 255, 255)
AMARELO_GOL = (250, 204, 21)
DOURADO = (255, 215, 0)
PREMIUM_BG = (7, 13, 23)
PREMIUM_PANEL = (12, 21, 35)
PREMIUM_PANEL_ALT = (17, 29, 46)
PREMIUM_LINE = (45, 61, 82)
PREMIUM_TEXT = (242, 246, 251)
PREMIUM_MUTED = (157, 174, 194)
PREMIUM_ACCENT = (67, 220, 160)

FONTES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
FONTES_REG = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def fonte(tam, negrito=True):
    for caminho in (FONTES if negrito else FONTES_REG):
        if os.path.exists(caminho):
            try:
                return ImageFont.truetype(caminho, tam)
            except Exception:
                pass
    return ImageFont.load_default()


def hex_rgb(h):
    h = (h or "#22c55e").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (34, 197, 94)


def contraste_cor(rgb):
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (15, 20, 25) if lum > 160 else (255, 255, 255)


def centralizado(d, y, txt, f, cor):
    bb = d.textbbox((0, 0), txt, font=f)
    larg = bb[2] - bb[0]
    d.text(((L - larg) // 2, y), txt, font=f, fill=cor)
    return larg


def centralizado_contornado(d, y, txt, f, cor=BRANCO, contorno=(0, 0, 0), largura_contorno=3):
    """Texto centralizado com borda, para continuar legível sobre qualquer fundo."""
    bb = d.textbbox((0, 0), txt, font=f, stroke_width=largura_contorno)
    larg = bb[2] - bb[0]
    d.text(((L - larg) // 2, y), txt, font=f, fill=cor,
           stroke_width=largura_contorno, stroke_fill=contorno)
    return larg


def obter_logo_campeonato(d_=None, tamanho=None):
    """Carrega a logo do campeonato a partir de partida.json ou dos arquivos do projeto."""
    caminhos = []
    base_dir = SCRIPT_DIR
    if d_ and isinstance(d_, dict):
        meta = d_.get("meta") or {}
        if meta.get("logo"):
            p = str(meta["logo"]).strip()
            if p.startswith("/web/"):
                caminhos.append(os.path.join(base_dir, p.lstrip("/")))
            elif p.startswith("/"):
                caminhos.append(p)
            else:
                caminhos.append(os.path.join(base_dir, p))
                caminhos.append(p)
    caminhos.extend([
        os.path.join(base_dir, "logo_campeonato.png"),
        os.path.join(base_dir, "web", "logo_campeonato.png"),
        os.path.join(base_dir, "logo.png"),
        os.path.join(base_dir, "web", "icon.png"),
    ])
    for c in caminhos:
        if c and os.path.isfile(c):
            try:
                img = Image.open(c).convert("RGBA")
                if tamanho:
                    img = img.copy()
                    img.thumbnail(tamanho, Image.Resampling.LANCZOS)
                return img
            except Exception:
                pass
    return None


def obter_foto_jogador(nome, time_obj=None, tamanho=(50, 50), borda_cor=None, borda_largura=2):
    """
    Carrega e formata a foto do jogador com recorte circular transparente e anti-aliasing.
    Procura em time_obj['fotos'][nome], ou em web/fotos/{slug}.png, ou fotos/{slug}.png.
    """
    if not nome or not str(nome).strip():
        return None
    nome_str = str(nome).strip()
    candidatos = []

    if isinstance(time_obj, dict) and "times" in time_obj:
        for t in time_obj["times"]:
            fmap = t.get("fotos", {})
            if isinstance(fmap, dict) and fmap.get(nome_str):
                candidatos.append(os.path.join(SCRIPT_DIR, fmap[nome_str].lstrip("/")))
    elif isinstance(time_obj, list):
        for t in time_obj:
            if isinstance(t, dict):
                fmap = t.get("fotos", {})
                if isinstance(fmap, dict) and fmap.get(nome_str):
                    candidatos.append(os.path.join(SCRIPT_DIR, fmap[nome_str].lstrip("/")))
    elif isinstance(time_obj, dict):
        fmap = time_obj.get("fotos", {})
        if isinstance(fmap, dict) and fmap.get(nome_str):
            p = fmap[nome_str]
            candidatos.append(os.path.join(SCRIPT_DIR, p.lstrip("/")))

    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', nome_str.lower())
    candidatos.extend([
        os.path.join(SCRIPT_DIR, "web", "fotos", f"{slug}.png"),
        os.path.join(SCRIPT_DIR, "web", "fotos", f"{slug}.jpg"),
        os.path.join(SCRIPT_DIR, "fotos", f"{slug}.png"),
    ])

    for c in candidatos:
        if c and os.path.isfile(c):
            try:
                im = Image.open(c).convert("RGBA")
                if tamanho:
                    w, h = tamanho
                    im = im.resize((w, h), Image.Resampling.LANCZOS)
                    # Máscara circular com anti-aliasing (supersample x2)
                    mask = Image.new("L", (w * 2, h * 2), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, w * 2 - 1, h * 2 - 1), fill=255)
                    mask = mask.resize((w, h), Image.Resampling.LANCZOS)

                    circular = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    circular.paste(im, (0, 0), mask)

                    if borda_cor:
                        b_draw = ImageDraw.Draw(circular)
                        bw = borda_largura
                        c_rgba = borda_cor + ((255,) if len(borda_cor) == 3 else ())
                        b_draw.ellipse((bw // 2, bw // 2, w - 1 - bw // 2, h - 1 - bw // 2),
                                       outline=c_rgba, width=bw)
                    return circular
                return im
            except Exception:
                continue
    return None


def obter_avatar_jogador(nome, time_obj=None, tamanho=(50, 50), cor_time=None, pos="MEI"):
    """
    Retorna o avatar visual do atleta: sua foto real em alta qualidade ou um
    emblema esportivo moderno com as iniciais e borda na cor do time.
    """
    if not nome or not str(nome).strip():
        return None
    nome_str = str(nome).strip()
    cor_borda = cor_time or (34, 197, 94)
    bw = max(2, int(tamanho[0] * 0.04))

    foto = obter_foto_jogador(nome_str, time_obj, tamanho=tamanho, borda_cor=cor_borda, borda_largura=bw)
    if foto:
        return foto

    w, h = tamanho
    avatar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(avatar)

    fundo_cor = (20, 26, 38, 240)
    c_rgba = cor_borda + ((255,) if len(cor_borda) == 3 else ())
    d.ellipse((0, 0, w - 1, h - 1), fill=fundo_cor, outline=c_rgba, width=bw)

    partes = nome_str.split()
    if len(partes) >= 2:
        iniciais = (partes[0][0] + partes[-1][0]).upper()
    else:
        iniciais = nome_str[:2].upper()

    texto_tag = iniciais if w >= 44 else (pos[:3].upper() if pos else iniciais[:1])
    f_tam = max(11, int(w * 0.36))
    f_tag = fonte(f_tam, True)
    bb = d.textbbox((0, 0), texto_tag, font=f_tag)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((w - tw) // 2, (h - th) // 2 - 1), texto_tag, font=f_tag, fill=(255, 255, 255, 230))
    return avatar


def desenhar_tv_watermark(img, d_, pos=None, tamanho=(85, 85)):
    """
    Marca d'água oficial do campeonato com fundo translúcido estilo TV bug e tag AO VIVO.
    """
    logo = obter_logo_campeonato(d_, tamanho=tamanho)
    if not logo:
        return

    lw, lh = logo.size
    pad_x, pad_y = 14, 8
    total_w = lw + pad_x * 2
    total_h = lh + pad_y * 2 + 18

    x = pos[0] if pos else (L - total_w - 60)
    y = pos[1] if pos else 36

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + total_w, y + total_h], radius=12,
                        fill=(11, 15, 24, 185), outline=(255, 255, 255, 45), width=1)

    lx = x + (total_w - lw) // 2
    ly = y + pad_y
    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")
    img.paste(logo, (lx, ly), logo)

    tag_y = ly + lh + 3
    d.ellipse([x + 16, tag_y + 3, x + 23, tag_y + 10], fill=(239, 68, 68, 245))
    d.text((x + 27, tag_y), "AO VIVO", font=fonte(11, True), fill=(240, 244, 248, 230))


def criar_fundo_base(d_=None, fundo_custom=None):
    """
    Retorna a imagem base (1920x1080) para as cartelas do vídeo.
    Se houver um frame ajustado salvo (fundo_cartela.png) ou configurado em d_['meta']['fundo_cartela'],
    carrega e utiliza como plano de fundo cinematográfico de transmissão esportiva.
    Caso contrário, devolve uma imagem sólida com a cor FUNDO.
    """
    caminho = fundo_custom
    if not caminho and d_ and isinstance(d_.get("_fundo_custom"), str):
        caminho = d_["_fundo_custom"]
    if not caminho and d_ and isinstance(d_.get("meta"), dict):
        caminho = d_["meta"].get("fundo_cartela")
    if not caminho or not os.path.isfile(caminho):
        for cand in ["fundo_cartela.png", "web/fundo_cartela.png"]:
            if os.path.isfile(cand):
                caminho = cand
                break
    if caminho and os.path.isfile(caminho):
        try:
            bg = Image.open(caminho).convert("RGB")
            if bg.size != (L, A):
                bg = bg.resize((L, A), Image.Resampling.LANCZOS)
            return bg
        except Exception as e:
            print(f"Aviso ao carregar imagem de fundo ({caminho}): {e}")
    return Image.new("RGB", (L, A), FUNDO)


def _fundo_premium(d_=None):
    """Escurece a imagem de fundo sem apagar o clima da quadra."""
    base = criar_fundo_base(d_).convert("RGB")
    tinta = Image.new("RGB", (L, A), PREMIUM_BG)
    return Image.blend(base, tinta, 0.48)


def _texto_ajustado(draw, texto, f, largura_max):
    """Encurta rótulos longos para preservar alinhamento e não invadir outros cards."""
    texto = _limpar_nome_pillow(texto)
    if draw.textbbox((0, 0), texto, font=f)[2] <= largura_max:
        return texto
    while texto and draw.textbbox((0, 0), texto + "…", font=f)[2] > largura_max:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _cabecalho_premium(img, draw, d_, secao, titulo, subtitulo="", etiqueta=None):
    """Cabeçalho editorial comum às cartelas da identidade padrão."""
    draw.rectangle([0, 0, L, 6], fill=PREMIUM_ACCENT)
    draw.rounded_rectangle([48, 30, L - 48, 154], radius=22,
                           fill=PREMIUM_PANEL, outline=PREMIUM_LINE, width=2)
    draw.rounded_rectangle([48, 30, 56, 154], radius=4, fill=PREMIUM_ACCENT)

    logo = obter_logo_campeonato(d_, tamanho=(72, 72))
    texto_x = 82
    if logo:
        draw.ellipse([72, 49, 164, 141], fill=(5, 11, 20), outline=PREMIUM_LINE, width=2)
        if logo.mode != "RGBA":
            logo = logo.convert("RGBA")
        img.paste(logo, (82, 59), logo)
        texto_x = 184

    draw.text((texto_x, 47), str(secao).upper(), font=fonte(15, True), fill=PREMIUM_ACCENT)
    f_titulo = fonte(36, True)
    draw.text((texto_x, 69), _texto_ajustado(draw, titulo, f_titulo, 1080),
              font=f_titulo, fill=PREMIUM_TEXT)
    if subtitulo:
        f_sub = fonte(17, False)
        draw.text((texto_x, 118), _texto_ajustado(draw, subtitulo, f_sub, 1100),
                  font=f_sub, fill=PREMIUM_MUTED)

    if etiqueta:
        f_tag = fonte(14, True)
        tag = str(etiqueta).upper()
        bb = draw.textbbox((0, 0), tag, font=f_tag)
        w = bb[2] - bb[0] + 30
        x = L - 78 - w
        draw.rounded_rectangle([x, 75, x + w, 111], radius=18,
                               fill=PREMIUM_PANEL_ALT, outline=PREMIUM_LINE, width=1)
        draw.text((x + w // 2, 93), tag, font=f_tag, fill=PREMIUM_MUTED, anchor="mm")


def _painel_premium(draw, caixa, *, fill=PREMIUM_PANEL, radius=18, borda=PREMIUM_LINE):
    x0, y0, x1, y1 = caixa
    draw.rounded_rectangle([x0 + 4, y0 + 7, x1 + 4, y1 + 7], radius=radius,
                           fill=(0, 0, 0))
    draw.rounded_rectangle(caixa, radius=radius, fill=fill, outline=borda, width=2)


def _tempo_em_segundos(ev):
    if not ev or not isinstance(ev, dict):
        return 0.0
    for k in ("tempo_s", "inicio_s"):
        val = ev.get(k)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    tempo_str = str(ev.get("tempo") or "").strip()
    if tempo_str:
        partes = tempo_str.split(":")
        try:
            if len(partes) == 3:
                return int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2])
            elif len(partes) == 2:
                return int(partes[0]) * 60 + float(partes[1])
            elif len(partes) == 1:
                return float(partes[0])
        except (ValueError, TypeError):
            pass
    try:
        return float(ev.get("indice", 0))
    except (ValueError, TypeError):
        return 0.0


def classificar_posicao(pos):
    """Normaliza qualquer rotulo de posicao em goleiro/zagueiro/meio/atacante.

    Devolve None quando nao ha posicao escolhida, para diferenciar "sem
    escolha" de "escolheu meio" - quem nao tem escolha recebe o padrao por
    indice mais adiante.
    """
    p = str(pos or "").strip().lower()
    if not p:
        return None
    if "gol" in p or "gk" in p or p in ("g", "goalkeeper"):
        return "goleiro"
    if "zag" in p or "def" in p or "lat" in p or p in ("z", "zg"):
        return "zagueiro"
    if "ata" in p or "pon" in p or "cen" in p or p in ("a", "atk"):
        return "atacante"
    return "meio"


def normalizar_jogadores(time_obj):
    raw = time_obj.get("jogadores", [])
    pos_map = time_obj.get("posicoes", {}) or {}
    resultado = []
    for j in raw:
        if isinstance(j, dict):
            nome = (j.get("nome") or "").strip()
            pos = j.get("posicao") or pos_map.get(nome)
        else:
            nome = str(j).strip()
            pos = pos_map.get(nome)
        if nome:
            resultado.append((nome, classificar_posicao(pos)))
    return resultado


def _limpar_nome_pillow(nome):
    """Remove emojis e caracteres fora do BMP que Pillow não renderiza (virariam □)."""
    import re
    return re.sub(r'[^\u0000-\uFFFF]', '', str(nome or '')).strip()


def posicao_padrao_por_indice(i):
    if i == 0:
        return "goleiro"
    if i in (1, 2):
        return "zagueiro"
    if i in (3, 4):
        return "meio"
    return "atacante"


def completar_escalacao(j_list):
    """Completa as posicoes que faltam e garante um goleiro no time.

    O assistente já mostra o primeiro do elenco como goleiro mesmo sem escolha
    manual, mas só grava em `posicoes` quem foi marcado na mão. Sem completar
    aqui, esse goleiro caía no grupo do meio e era desenhado no meio-campo em
    vez da própria área.
    """
    jogadores = list(j_list)
    if not jogadores:
        return jogadores

    escolhidos = {i for i, (_, pos) in enumerate(jogadores) if pos}
    for i, (nome, pos) in enumerate(jogadores):
        if not pos:
            jogadores[i] = (nome, posicao_padrao_por_indice(i))

    if not any(pos == "goleiro" for _, pos in jogadores):
        alvo = next((i for i in range(len(jogadores)) if i not in escolhidos), 0)
        jogadores[alvo] = (jogadores[alvo][0], "goleiro")

    return jogadores


# --------------------------------------------------------------- CAMPO TÁTICO E ABERTURA

def desenhar_campo_tatico(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=None, times=None):
    n_faixas = 10
    faixa_w = w / n_faixas
    c_grama1 = (20, 68, 38)
    c_grama2 = (16, 58, 32)
    for i in range(n_faixas):
        gx0 = int(x0 + i * faixa_w)
        gx1 = int(x0 + (i + 1) * faixa_w)
        draw.rectangle([gx0, y0, gx1, y0 + h], fill=c_grama1 if i % 2 == 0 else c_grama2)

    draw.rectangle([x0, y0, x0 + w, y0 + h], outline=(240, 240, 240), width=3)
    meio_x = x0 + w // 2
    draw.line([meio_x, y0, meio_x, y0 + h], fill=(240, 240, 240), width=3)

    r_circ = int(h * 0.18)
    draw.ellipse([meio_x - r_circ, y0 + h // 2 - r_circ, meio_x + r_circ, y0 + h // 2 + r_circ],
                 outline=(240, 240, 240), width=3)
    draw.ellipse([meio_x - 5, y0 + h // 2 - 5, meio_x + 5, y0 + h // 2 + 5], fill=(240, 240, 240))

    area_w = int(w * 0.18)
    area_h = int(h * 0.58)
    area_y = y0 + (h - area_h) // 2
    draw.rectangle([x0, area_y, x0 + area_w, area_y + area_h], outline=(240, 240, 240), width=3)
    parea_w = int(w * 0.07)
    parea_h = int(h * 0.32)
    parea_y = y0 + (h - parea_h) // 2
    draw.rectangle([x0, parea_y, x0 + parea_w, parea_y + parea_h], outline=(240, 240, 240), width=2)
    ponto_penalti_a = x0 + int(w * 0.12)
    draw.ellipse([ponto_penalti_a - 4, y0 + h // 2 - 4, ponto_penalti_a + 4, y0 + h // 2 + 4], fill=(240, 240, 240))

    draw.rectangle([x0 + w - area_w, area_y, x0 + w, area_y + area_h], outline=(240, 240, 240), width=3)
    draw.rectangle([x0 + w - parea_w, parea_y, x0 + w, parea_y + parea_h], outline=(240, 240, 240), width=2)
    ponto_penalti_b = x0 + w - int(w * 0.12)
    draw.ellipse([ponto_penalti_b - 4, y0 + h // 2 - 4, ponto_penalti_b + 4, y0 + h // 2 + 4], fill=(240, 240, 240))

    def posicionar_jogadores(jogadores_pos, lado_esquerdo):
        grupos = {"goleiro": [], "zagueiro": [], "meio": [], "atacante": []}
        for nome, pos in jogadores_pos:
            grupos[classificar_posicao(pos) or "meio"].append(nome)

        coords = []
        if lado_esquerdo:
            col_x = {
                "goleiro": x0 + int(w * 0.07),
                "zagueiro": x0 + int(w * 0.19),
                "meio": x0 + int(w * 0.32),
                "atacante": x0 + int(w * 0.43),
            }
        else:
            col_x = {
                "atacante": x0 + int(w * 0.57),
                "meio": x0 + int(w * 0.68),
                "zagueiro": x0 + int(w * 0.81),
                "goleiro": x0 + int(w * 0.93),
            }

        margem_y = int(h * 0.10)
        area_util_y = h - 2 * margem_y
        # O goleiro fica confinado na altura da pequena área (0.32h), a mesma
        # faixa desenhada no campo — assim nunca sobe para a linha dos outros.
        faixa_gol_h = int(h * 0.32)
        faixa_gol_y0 = y0 + (h - faixa_gol_h) // 2
        for cat, jgs in grupos.items():
            cx = col_x[cat]
            qtd = len(jgs)
            if qtd == 0:
                continue
            if cat == "goleiro":
                step_gol = faixa_gol_h / (qtd + 1)
                for idx, nome in enumerate(jgs, 1):
                    coords.append((nome, cat, cx, faixa_gol_y0 + int(idx * step_gol)))
                continue
            step = area_util_y / (qtd + 1)
            for idx, nome in enumerate(jgs, 1):
                cy = y0 + margem_y + int(idx * step)
                coords.append((nome, cat, cx, cy))
        return coords

    coords_a = posicionar_jogadores(time_a, True)
    coords_b = posicionar_jogadores(time_b, False)

    grupos_times = [
        (coords_a, ca, times[0] if times else None),
        (coords_b, cb, times[1] if times and len(times) > 1 else None)
    ]

    for coords, cor, time_obj in grupos_times:
        for nome, cat, cx, cy in coords:
            r = 26  # Tamanho do nó no campo (52x52px)
            # Sombra suave sob o avatar
            draw.ellipse([cx - r - 3, cy - r + 3, cx + r + 3, cy + r + 7], fill=(5, 10, 15, 160))

            av = obter_avatar_jogador(nome, time_obj, tamanho=(r * 2, r * 2), cor_time=cor, pos=cat)
            if av and img_base:
                img_base.paste(av, (cx - r, cy - r), av)

            # Plaqueta de identificação translúcida estilo FIFA
            nome_limpo = _limpar_nome_pillow(nome)
            f_nome = fonte(15, True)
            bb = draw.textbbox((0, 0), nome_limpo, font=f_nome)
            nw = bb[2] - bb[0]
            nh = bb[3] - bb[1]
            nx0 = cx - nw // 2 - 8
            ny0 = cy + r + 5
            draw.rounded_rectangle([nx0, ny0, nx0 + nw + 16, ny0 + nh + 6], radius=5,
                                   fill=(12, 16, 26, 230), outline=(65, 80, 105), width=1)
            draw.text((cx - nw // 2, ny0 + 2), nome_limpo, font=f_nome, fill=(255, 255, 255))


def _logo_topo_tema(img, d, d_, logo_tam=(110, 110), y_logo=16):
    """Renderiza logo centralizada com estilo do tema. Retorna y após a logo."""
    _, pborda, ptitulo, _, _ = _paleta_tema()
    logo = obter_logo_campeonato(d_, tamanho=logo_tam)
    if not logo:
        return y_logo + 12
    lw, lh = logo.size
    lx = (L - lw) // 2
    if TEMA == "iss":
        d.rectangle([lx - 12, y_logo - 10, lx + lw + 12, y_logo + lh + 10], fill=(0, 0, 0))
        d.rectangle([lx - 14, y_logo - 12, lx + lw + 14, y_logo + lh + 12], outline=pborda, width=3)
    elif TEMA == "fifa":
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], fill=(0, 0, 0, 120))
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], outline=(255, 255, 255), width=2)
    elif TEMA == "pes":
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], fill=(20, 25, 38))
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], outline=(80, 90, 115), width=2)
    else:  # tv
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], fill=(0, 0, 0, 140))
        d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8], outline=(0, 220, 120), width=2)
    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")
    img.paste(logo, (lx, y_logo), logo)
    return y_logo + lh + 18


def _topo_minimalista(img, d, d_, accent):
    """Cabecalho elegante: logo + torneio + linha. Retorna y."""
    meta = d_["meta"]
    logo = obter_logo_campeonato(d_, tamanho=(72, 72))
    if logo:
        if logo.mode != "RGBA": logo = logo.convert("RGBA")
        img.paste(logo, (50, 20), logo)
        xn = 140
    else:
        xn = 50
    torneio = (meta.get("pelada") or meta.get("torneio") or "").upper()
    sub = " - ".join(x for x in [meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")] if x)
    d.text((xn, 34), torneio, font=fonte(28, True), fill=(240, 242, 248))
    if sub:
        d.text((xn, 70), sub, font=fonte(17, False), fill=(80, 90, 110))
    d.rectangle([0, 106, L, 109], fill=accent)
    return 118


def _col_gols(img, d, x0, col_w, topo, fim, time_obj, lista, cor_time, accent, psub):
    """Coluna de gols minimalista."""
    espaco = max(1, fim - topo - 70)
    passo = max(32, min(44, espaco // max(len(lista), 1)))
    t_au = max(18, min(21, passo - 10)); t_as = max(13, min(15, passo - 17))
    t_tm = max(13, min(15, passo - 18)); t_av = max(26, min(32, passo - 8))
    d.text((x0, topo + 12), time_obj["nome"].upper(), font=fonte(22, True), fill=cor_time)
    d.text((x0 + col_w, topo + 12), str(len(lista)), font=fonte(22, True), fill=accent, anchor="ra")
    d.rectangle([x0, topo + 38, x0 + col_w, topo + 40], fill=(30, 35, 50))
    y = topo + 50
    if not lista:
        d.text((x0, y + 10), "nenhum gol", font=fonte(17, False), fill=psub); return
    for g in lista:
        if y + passo > fim - 8: break
        t_str = g.get("tempo", ""); autor = _limpar_nome_pillow(g.get("autor", ""))
        d.text((x0, y + 4), t_str, font=fonte(t_tm, True), fill=accent)
        av = obter_avatar_jogador(autor, time_obj, tamanho=(t_av, t_av), cor_time=cor_time)
        ax = x0 + 72
        if av:
            img.paste(av, (ax, y), av)
            d.text((ax + t_av + 10, y + 4), autor, font=fonte(t_au, True), fill=(230, 235, 248))
        else:
            d.text((ax, y + 4), autor, font=fonte(t_au, True), fill=(230, 235, 248))
        if g.get("assist"):
            d.text((x0 + col_w, y + 6), "assist. " + _limpar_nome_pillow(g["assist"]),
                   font=fonte(t_as, False), fill=psub, anchor="ra")
        d.rectangle([x0, y + passo - 4, x0 + col_w, y + passo - 3], fill=(22, 26, 38))
        y += passo


def _cartela_abertura_tema(d_, visiveis_a=None, visiveis_b=None):
    """Abertura elegante e minimalista."""
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    cfg = {"fifa": ((8,10,16),(200,168,90)), "iss": ((10,10,20),(200,200,200)),
           "pes": ((10,14,22),(100,140,210)), "tv": ((8,10,14),(150,200,110))}
    bg, accent = cfg.get(TEMA, (PAINEL, DOURADO))
    img = Image.new("RGB", (L, A), bg)
    d = ImageDraw.Draw(img)
    y_top = _topo_minimalista(img, d, d_, accent)
    y_vs = y_top + 14; h_pill = 54; w_pill = 420
    x_a = L // 2 - w_pill - 40; x_b = L // 2 + 40
    for xp, cor, nome in [(x_a, ca, times[0]["nome"].upper()), (x_b, cb, times[1]["nome"].upper())]:
        d.rounded_rectangle([xp, y_vs, xp + w_pill, y_vs + h_pill], radius=8, fill=cor)
        d.text((xp + w_pill // 2, y_vs + h_pill // 2), nome, font=fonte(26, True),
               fill=contraste_cor(cor), anchor="mm")
    d.rounded_rectangle([L//2-32, y_vs+h_pill//2-22, L//2+32, y_vs+h_pill//2+22],
                        radius=6, fill=bg, outline=(45,52,70), width=2)
    d.text((L//2, y_vs+h_pill//2), "VS", font=fonte(20, True), fill=(160,168,190), anchor="mm")
    d.text((L//2, y_vs+h_pill+14), "ESCALACAO E DISPOSICAO TATICA",
           font=fonte(14, True), fill=(55,64,82), anchor="mm")
    j_a_todos = completar_escalacao(normalizar_jogadores(times[0]))
    j_b_todos = completar_escalacao(normalizar_jogadores(times[1]))
    j_a = [(nm,pos) for nm,pos in j_a_todos if visiveis_a is None or nm in visiveis_a]
    j_b = [(nm,pos) for nm,pos in j_b_todos if visiveis_b is None or nm in visiveis_b]
    campo_y0 = y_vs + h_pill + 36
    campo_w = 1240; campo_h = A - campo_y0 - 10
    campo_x0 = (L - campo_w) // 2
    desenhar_campo_tatico(d, campo_x0, campo_y0, campo_w, campo_h, j_a, j_b, ca, cb, img_base=img, times=times)
    def painel(x0, time_obj, jgs_todos, visiveis_set, cor):
        w_p = 265
        d.rounded_rectangle([x0, campo_y0, x0+w_p, campo_y0+campo_h], radius=8, fill=(13,17,26), outline=(24,30,44), width=1)
        d.rectangle([x0, campo_y0, x0+w_p, campo_y0+4], fill=cor)
        d.text((x0+12, campo_y0+14), time_obj["nome"], font=fonte(19, True), fill=cor)
        d.text((x0+12, campo_y0+38), "ELENCO", font=fonte(11, False), fill=(50,60,80))
        tags = {"goleiro":"G","zagueiro":"D","meio":"M","atacante":"A"}
        y_item = campo_y0 + 58
        for nm, pos in jgs_todos[:12]:
            visivel = visiveis_set is None or nm in visiveis_set
            nm_l = _limpar_nome_pillow(nm)
            if visivel:
                av = obter_avatar_jogador(nm, time_obj, tamanho=(24,24), cor_time=cor, pos=pos)
                if av:
                    img.paste(av, (x0+10, y_item), av)
                    d.text((x0+40, y_item+4), nm_l, font=fonte(15, False), fill=(205,212,228))
                else:
                    d.text((x0+10, y_item+4), nm_l, font=fonte(15, False), fill=(205,212,228))
                d.text((x0+w_p-10, y_item+5), tags.get(pos,"M"), font=fonte(11, True), fill=(55,65,85), anchor="ra")
            else:
                d.rectangle([x0+10, y_item+9, x0+w_p-10, y_item+16], fill=(20,26,38))
            y_item += 36
    vset_a = set(nm for nm,_ in (j_a if visiveis_a is not None else j_a_todos))
    vset_b = set(nm for nm,_ in (j_b if visiveis_b is not None else j_b_todos))
    painel(35, times[0], j_a_todos, vset_a if visiveis_a is not None else None, ca)
    painel(L-300, times[1], j_b_todos, vset_b if visiveis_b is not None else None, cb)
    return img

def _cartela_abertura_premium(d_, visiveis_a=None, visiveis_b=None):
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    img = _fundo_premium(d_)
    draw = ImageDraw.Draw(img)
    subtitle = " · ".join(str(x) for x in (
        meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")
    ) if x)
    _cabecalho_premium(img, draw, d_, "PRÉ-JOGO", "ESCALAÇÕES", subtitle,
                       etiqueta="APRESENTAÇÃO")

    # Confronto no centro, com as cores dos times como acentos.
    mx0, my0, mx1, my1 = 50, 176, L - 50, 300
    _painel_premium(draw, (mx0, my0, mx1, my1), fill=PREMIUM_PANEL_ALT, radius=20)
    draw.rounded_rectangle([mx0 + 2, my0 + 18, mx0 + 10, my1 - 18], radius=4, fill=ca)
    draw.rounded_rectangle([mx1 - 10, my0 + 18, mx1 - 2, my1 - 18], radius=4, fill=cb)
    f_time = fonte(34, True)
    f_label = fonte(13, True)
    f_aux = fonte(15, False)
    nome_a = _texto_ajustado(draw, times[0]["nome"].upper(), f_time, 600)
    nome_b = _texto_ajustado(draw, times[1]["nome"].upper(), f_time, 600)
    draw.text((mx0 + 40, my0 + 43), "TIME 01", font=f_label, fill=ca)
    draw.text((mx0 + 40, my0 + 65), nome_a, font=f_time, fill=PREMIUM_TEXT)
    draw.text((mx0 + 40, my0 + 106), f"{len(times[0].get('jogadores', []))} ATLETAS",
              font=f_aux, fill=PREMIUM_MUTED)
    draw.text((mx1 - 40, my0 + 43), "TIME 02", font=f_label, fill=cb, anchor="ra")
    draw.text((mx1 - 40, my0 + 65), nome_b, font=f_time, fill=PREMIUM_TEXT, anchor="ra")
    draw.text((mx1 - 40, my0 + 106), f"{len(times[1].get('jogadores', []))} ATLETAS",
              font=f_aux, fill=PREMIUM_MUTED, anchor="ra")
    draw.ellipse([L // 2 - 34, my0 + 29, L // 2 + 34, my0 + 97],
                 fill=PREMIUM_BG, outline=PREMIUM_LINE, width=2)
    draw.text((L // 2, my0 + 63), "VS", font=fonte(20, True),
              fill=PREMIUM_TEXT, anchor="mm")

    jogadores_a = completar_escalacao(normalizar_jogadores(times[0]))
    jogadores_b = completar_escalacao(normalizar_jogadores(times[1]))
    vis_a = set(n for n, _ in jogadores_a) if visiveis_a is None else set(visiveis_a)
    vis_b = set(n for n, _ in jogadores_b) if visiveis_b is None else set(visiveis_b)

    y, h = 324, 706
    x_left, w_side = 50, 300
    x_field, w_field = 372, 1176
    x_right = 1570

    def desenhar_elenco(x0, time_obj, jogadores, visiveis, cor):
        _painel_premium(draw, (x0, y, x0 + w_side, y + h), radius=18)
        draw.rounded_rectangle([x0 + 20, y + 18, x0 + 26, y + 61], radius=3, fill=cor)
        draw.text((x0 + 40, y + 19), "ELENCO", font=fonte(14, True), fill=PREMIUM_MUTED)
        draw.text((x0 + w_side - 22, y + 23), f"{len(jogadores):02d}",
                  font=fonte(17, True), fill=cor, anchor="ra")
        draw.line([x0 + 20, y + 72, x0 + w_side - 20, y + 72], fill=PREMIUM_LINE, width=1)
        tags = {"goleiro": "GOL", "zagueiro": "ZAG", "meio": "MEI", "atacante": "ATA"}
        row_y = y + 88
        row_h = 43
        for idx, (nome, pos) in enumerate(jogadores[:12]):
            yy = row_y + idx * row_h
            if yy + row_h > y + h - 28:
                break
            if nome in visiveis:
                avatar = obter_avatar_jogador(nome, time_obj, tamanho=(32, 32), cor_time=cor, pos=pos)
                if avatar:
                    img.paste(avatar, (x0 + 20, yy + 3), avatar)
                nome_x = x0 + 64
                f_nome = fonte(16, True)
                nome_fit = _texto_ajustado(draw, nome, f_nome, 158)
                draw.text((nome_x, yy + 8), nome_fit, font=f_nome, fill=PREMIUM_TEXT)
                tag = tags.get(pos, "MEI")
                draw.rounded_rectangle([x0 + w_side - 57, yy + 7, x0 + w_side - 19, yy + 30],
                                       radius=10, fill=(24, 38, 57), outline=cor, width=1)
                draw.text((x0 + w_side - 38, yy + 18), tag, font=fonte(9, True),
                          fill=PREMIUM_TEXT, anchor="mm")
            else:
                draw.rounded_rectangle([x0 + 20, yy + 9, x0 + w_side - 20, yy + 26],
                                       radius=7, fill=(22, 33, 49))
                draw.rounded_rectangle([x0 + 20, yy + 9, x0 + 24, yy + 26],
                                       radius=2, fill=cor)
        if len(jogadores) > 12:
            draw.text((x0 + 20, y + h - 30), f"+ {len(jogadores) - 12} reservas",
                      font=fonte(12, False), fill=PREMIUM_MUTED)

    desenhar_elenco(x_left, times[0], jogadores_a, vis_a, ca)
    desenhar_elenco(x_right, times[1], jogadores_b, vis_b, cb)

    _painel_premium(draw, (x_field, y, x_field + w_field, y + h), radius=18)
    draw.rounded_rectangle([x_field + 12, y + 12, x_field + w_field - 12, y + h - 12],
                           radius=12, fill=(8, 35, 27), outline=(48, 86, 69), width=1)
    desenhar_campo_tatico(
        draw, x_field + 18, y + 18, w_field - 36, h - 36,
        [(n, p) for n, p in jogadores_a if n in vis_a],
        [(n, p) for n, p in jogadores_b if n in vis_b],
        ca, cb, img_base=img, times=times,
    )
    return img


def cartela_abertura(d_, visiveis_a=None, visiveis_b=None):
    """Cartela pré-jogo com confronto, escalações e desenho tático."""
    if TEMA != "atual":
        return _cartela_abertura_tema(d_, visiveis_a, visiveis_b)
    return _cartela_abertura_premium(d_, visiveis_a, visiveis_b)

def gerar_abertura_animada(d_, tmp_dir, dur_total, crf=24, preset="medium", codec="libx264"):
    """
    Gera a abertura animada: revela um jogador de cada time por vez (alternando),
    no estilo broadcast. Retorna o caminho do .mp4 gerado.

    Cada jogador fica visível por ~0.9s antes do próximo aparecer.
    O frame final (todos visíveis) fica por 2s.
    """
    j_a_todos = completar_escalacao(normalizar_jogadores(d_["times"][0]))
    j_b_todos = completar_escalacao(normalizar_jogadores(d_["times"][1]))
    nomes_a = [nm for nm, _ in j_a_todos]
    nomes_b = [nm for nm, _ in j_b_todos]

    # Sequência: campo vazio → revela Time A completo → revela Time B completo
    sequencia = []  # (set_visiveis_a, set_visiveis_b, dur_frame_s)

    # 1. Campo vazio
    sequencia.append((frozenset(), frozenset(), 1.0))

    # 2. Revela Time A um por um (Time B ainda vazio)
    va = set()
    for i, nm in enumerate(nomes_a):
        va = va | {nm}
        dur = 1.2 if i < len(nomes_a) - 1 else 1.5
        sequencia.append((frozenset(va), frozenset(), dur))

    # 3. Revela Time B um por um (Time A já completo)
    vb = set()
    for i, nm in enumerate(nomes_b):
        vb = vb | {nm}
        dur = 1.2 if i < len(nomes_b) - 1 else 3.0
        sequencia.append((frozenset(va), frozenset(vb), dur))

    # Gera cada frame PNG e concatena com ffmpeg
    c_v = codec if codec in ("libx264", "libx265") else "libx264"
    segmentos = []

    for idx, (va_frame, vb_frame, dur_frame) in enumerate(sequencia):
        png_path = os.path.join(tmp_dir, f"aber_{idx:03d}.png")
        seg_path = os.path.join(tmp_dir, f"aber_{idx:03d}.mp4")

        frame_img = cartela_abertura(d_, visiveis_a=va_frame, visiveis_b=vb_frame)
        frame_img.save(png_path)

        fade_in  = 0.25 if idx == 0 else 0.0
        fade_out = 0.25 if idx == len(sequencia) - 1 else 0.0
        fade_filter = ""
        if fade_in:
            fade_filter += f"fade=t=in:st=0:d={fade_in},"
        if fade_out:
            fade_filter += f"fade=t=out:st={max(dur_frame - fade_out, 0.05):.2f}:d={fade_out},"

        roda(["ffmpeg", "-y", "-loglevel", "error",
              "-loop", "1", "-i", png_path,
              "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
              "-t", str(dur_frame), "-r", str(FPS),
              "-vf", f"{fade_filter}format=yuv420p{escala_saida()},setsar=1",
              "-c:v", c_v, "-preset", preset, "-crf", str(crf),
              "-pix_fmt", "yuv420p", "-movflags", "+faststart",
              "-video_track_timescale", str(VIDEO_TIMESCALE),
              "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_HZ), "-ac", "2",
              "-shortest", seg_path])
        segmentos.append(seg_path)

    # Concatena todos os segmentos
    lista_concat = os.path.join(tmp_dir, "aber_concat.txt")
    with open(lista_concat, "w", encoding="utf-8") as f:
        for seg in segmentos:
            f.write(f"file '{seg}'\n")

    saida = os.path.join(tmp_dir, "s000.mp4")
    roda(["ffmpeg", "-y", "-loglevel", "error",
          "-f", "concat", "-safe", "0", "-i", lista_concat,
          "-c", "copy", saida])

    return saida


# --------------------------------------------------------------- PLACAR ELETRÔNICO E LANCE

def _cartela_lance_fifa(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """Estilo EA FC / FIFA: placar centralizado no topo, fundo preto fosco, tipografia limpa."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ca = hex_rgb(times[0]["cor"]); cb = hex_rgb(times[1]["cor"])
    nome_a = times[0]["nome"].upper(); nome_b = times[1]["nome"].upper()
    ph = 52; f_team = fonte(18, True); f_score = fonte(30, True)
    bb_a = d.textbbox((0,0), nome_a, font=f_team); wta = max(bb_a[2]-bb_a[0]+36, 120)
    bb_b = d.textbbox((0,0), nome_b, font=f_team); wtb = max(bb_b[2]-bb_b[0]+36, 120)
    pw_s = 110; total_w = wta+pw_s+wtb; px0 = (L-total_w)//2; py0 = 28
    d.rounded_rectangle([px0+3, py0+3, px0+total_w+3, py0+ph+3], radius=4, fill=(0,0,0,140))
    d.rounded_rectangle([px0, py0, px0+wta, py0+ph], radius=4, fill=ca+(245,))
    d.text((px0+wta//2, py0+ph//2), nome_a, font=f_team, fill=contraste_cor(ca)+(255,), anchor="mm")
    d.rectangle([px0+wta, py0, px0+wta+pw_s, py0+ph], fill=(8,8,8,250))
    d.text((px0+wta+26, py0+ph//2), str(placar_a), font=f_score, fill=(255,255,255,255), anchor="mm")
    d.text((px0+wta+pw_s//2, py0+ph//2-2), "-", font=fonte(28), fill=(180,180,180,255), anchor="mm")
    d.text((px0+wta+pw_s-26, py0+ph//2), str(placar_b), font=f_score, fill=(255,255,255,255), anchor="mm")
    d.rounded_rectangle([px0+wta+pw_s, py0, px0+total_w, py0+ph], radius=4, fill=cb+(245,))
    d.text((px0+wta+pw_s+wtb//2, py0+ph//2), nome_b, font=f_team, fill=contraste_cor(cb)+(255,), anchor="mm")
    tempo_str = str(ev.get("tempo") or "")
    if tempo_str:
        # FIFA: quadrado preto com borda dourada ao lado do placar
        tw_box = 88
        tx0 = px0 + total_w + 8
        d.rounded_rectangle([tx0, py0, tx0 + tw_box, py0 + ph], radius=4, fill=(0, 0, 0, 240))
        d.rounded_rectangle([tx0, py0, tx0 + tw_box, py0 + ph], radius=4, outline=(255, 215, 0, 200), width=2)
        d.text((tx0 + tw_box // 2, py0 + ph // 2), tempo_str, font=fonte(18, True), fill=(255, 215, 0, 255), anchor="mm")
    if gol_neste_clipe and time_gol in (0,1):
        d.rounded_rectangle([px0+total_w+10, py0+ph+4, px0+total_w+80, py0+ph+28], radius=3, fill=(255,220,0,255))
        d.text((px0+total_w+45, py0+ph+16), "GOAL!", font=fonte(12, True), fill=(0,0,0,255), anchor="mm")
    if tipo == "gol":
        t_idx = ev.get("time", 0); cor_l = hex_rgb(times[t_idx]["cor"])
        jogador = ev.get("autor", ""); assist = ev.get("assist")
    else:
        tem = ev.get("time") is not None and 0 <= ev["time"] < len(times)
        cor_l = hex_rgb(times[ev["time"]]["cor"]) if tem else (200,200,200)
        jogador = ev.get("destaque") or ev.get("autor") or ""; assist = None
    barra_y = A - 90
    d.rectangle([0, barra_y, L, barra_y+3], fill=cor_l+(220,))
    d.rectangle([0, barra_y+3, L, A], fill=(0,0,0,185))
    f_nome = fonte(30, True); f_sub = fonte(15, False)
    d.text((60, barra_y+16), jogador, font=f_nome, fill=(255,255,255,255))
    if assist:
        bb = d.textbbox((0,0), jogador, font=f_nome)
        d.text((60+bb[2]-bb[0]+20, barra_y+22), f"assist: {assist}", font=f_sub, fill=(200,200,200,200))
    elif tipo == "gol":
        d.text((60, barra_y+54), times[ev.get("time",0)]["nome"], font=f_sub, fill=cor_l+(200,))
    return img


def _cartela_lance_iss(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """Estilo ISS Deluxe/SNES: retrô, cores vibrantes, bordas quadradas."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ca = hex_rgb(times[0]["cor"]); cb = hex_rgb(times[1]["cor"])
    nome_a = times[0]["nome"].upper(); nome_b = times[1]["nome"].upper()
    COL_BRD = (255, 255, 0, 255); COL_TXT = (255, 255, 255, 255); COL_DIM = (180, 180, 60, 255)
    ph = 48; f_team = fonte(20, True); f_score = fonte(32, True)
    bb_a = d.textbbox((0,0), nome_a, font=f_team); wta = bb_a[2]-bb_a[0]+24
    bb_b = d.textbbox((0,0), nome_b, font=f_team); wtb = bb_b[2]-bb_b[0]+24
    pw_s = 90; total_w = wta+pw_s+wtb; px0 = (L-total_w)//2; py0 = 24
    d.rectangle([px0-2, py0-2, px0+total_w+2, py0+ph+2], fill=COL_BRD)
    d.rectangle([px0, py0, px0+total_w, py0+ph], fill=(0,0,0,220))
    d.rectangle([px0, py0, px0+wta, py0+ph], fill=ca+(220,))
    d.text((px0+wta//2, py0+ph//2), nome_a, font=f_team, fill=contraste_cor(ca)+(255,), anchor="mm")
    d.rectangle([px0+wta, py0, px0+wta+pw_s, py0+ph], fill=(20,20,20,255))
    d.text((px0+wta+14, py0+ph//2), str(placar_a), font=f_score, fill=COL_TXT, anchor="lm")
    d.text((px0+wta+pw_s//2, py0+ph//2-2), "-", font=fonte(26), fill=COL_DIM, anchor="mm")
    d.text((px0+wta+pw_s-14, py0+ph//2), str(placar_b), font=f_score, fill=COL_TXT, anchor="rm")
    d.rectangle([px0+wta+pw_s, py0, px0+total_w, py0+ph], fill=cb+(220,))
    d.text((px0+wta+pw_s+wtb//2, py0+ph//2), nome_b, font=f_team, fill=contraste_cor(cb)+(255,), anchor="mm")
    # Tempo — quadrado retrô amarelo com borda (ISS style)
    tempo_str_iss = str(ev.get("tempo") or "")
    if tempo_str_iss:
        tx0_iss = px0 + total_w + 4
        tw_iss = 96
        d.rectangle([tx0_iss - 2, py0 - 2, tx0_iss + tw_iss + 2, py0 + ph + 2], fill=COL_BRD)
        d.rectangle([tx0_iss, py0, tx0_iss + tw_iss, py0 + ph], fill=(0, 0, 50, 240))
        d.text((tx0_iss + tw_iss // 2, py0 + ph // 2), tempo_str_iss, font=fonte(18, True),
               fill=(255, 255, 0, 255), anchor="mm")
    if gol_neste_clipe:
        gx = px0+total_w+10
        d.rectangle([gx-2, py0-2, gx+90, py0+ph+2], fill=COL_BRD)
        d.rectangle([gx, py0, gx+88, py0+ph], fill=(200,0,0,240))
        d.text((gx+44, py0+ph//2), "GOL!!!", font=fonte(18,True), fill=(255,255,0,255), anchor="mm")
    if tipo == "gol":
        t_idx = ev.get("time", 0); cor_l = hex_rgb(times[t_idx]["cor"])
        jogador = ev.get("autor", ""); assist = ev.get("assist")
    else:
        tem = ev.get("time") is not None and 0 <= ev["time"] < len(times)
        cor_l = hex_rgb(times[ev["time"]]["cor"]) if tem else (200,200,0)
        jogador = ev.get("destaque") or ev.get("autor") or ""; assist = None
    lt_y = A - 80
    d.rectangle([40-2, lt_y-2, 680+2, lt_y+68+2], fill=COL_BRD)
    d.rectangle([40, lt_y, 680, lt_y+68], fill=(10,10,10,240))
    d.rectangle([40, lt_y, 48, lt_y+68], fill=cor_l+(255,))
    d.text((60, lt_y+8), jogador, font=fonte(28,True), fill=COL_TXT)
    if assist:
        d.text((60, lt_y+42), f"ASSIST: {assist}", font=fonte(16,False), fill=COL_DIM)
    return img


def _cartela_lance_pes(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """Estilo PES/eFootball: overlay minimalista semitransparente."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ca = hex_rgb(times[0]["cor"]); cb = hex_rgb(times[1]["cor"])
    nome_a = times[0]["nome"].upper(); nome_b = times[1]["nome"].upper()
    ph = 44; py0 = 20; px0 = 24
    f_team = fonte(16, True); f_score = fonte(26, True)
    bb_a = d.textbbox((0,0), nome_a, font=f_team); wta = bb_a[2]-bb_a[0]+20
    bb_b = d.textbbox((0,0), nome_b, font=f_team); wtb = bb_b[2]-bb_b[0]+20
    pw_s = 72; total_w = wta+pw_s+wtb
    d.rounded_rectangle([px0, py0, px0+total_w, py0+ph], radius=3, fill=(30,30,30,200))
    d.rectangle([px0, py0+ph-3, px0+wta, py0+ph], fill=ca+(200,))
    d.rectangle([px0+wta+pw_s, py0+ph-3, px0+total_w, py0+ph], fill=cb+(200,))
    d.text((px0+wta//2, py0+ph//2-1), nome_a, font=f_team, fill=(255,255,255,230), anchor="mm")
    d.text((px0+wta+pw_s+wtb//2, py0+ph//2-1), nome_b, font=f_team, fill=(255,255,255,230), anchor="mm")
    sep_x = px0+wta+pw_s//2
    d.text((sep_x-16, py0+ph//2), str(placar_a), font=f_score, fill=(255,255,255,255), anchor="rm")
    d.text((sep_x, py0+ph//2-2), ":", font=fonte(20), fill=(160,160,160,200), anchor="mm")
    d.text((sep_x+16, py0+ph//2), str(placar_b), font=f_score, fill=(255,255,255,255), anchor="lm")
    tempo_str = str(ev.get("tempo") or "")
    if tempo_str:
        # PES: quadrado arredondado cinza-azul escuro com borda branca sutil
        tw_pes = 84
        tx0_pes = px0 + total_w + 8
        d.rounded_rectangle([tx0_pes, py0, tx0_pes + tw_pes, py0 + ph], radius=3, fill=(25, 30, 45, 210))
        d.rounded_rectangle([tx0_pes, py0, tx0_pes + tw_pes, py0 + ph], radius=3, outline=(220, 220, 240, 160), width=1)
        d.text((tx0_pes + tw_pes // 2, py0 + ph // 2), tempo_str, font=fonte(16, True),
               fill=(220, 220, 255, 230), anchor="mm")
    if gol_neste_clipe and time_gol in (0,1):
        cor_gol = ca if time_gol == 0 else cb
        d.rounded_rectangle([px0, py0+ph+5, px0+total_w, py0+ph+27], radius=3, fill=cor_gol+(200,))
        d.text((px0+total_w//2, py0+ph+16), "GOAL", font=fonte(13,True), fill=contraste_cor(cor_gol)+(255,), anchor="mm")
    if tipo == "gol":
        t_idx = ev.get("time", 0); cor_l = hex_rgb(times[t_idx]["cor"])
        jogador = ev.get("autor", ""); assist = ev.get("assist")
    else:
        tem = ev.get("time") is not None and 0 <= ev["time"] < len(times)
        cor_l = hex_rgb(times[ev["time"]]["cor"]) if tem else (150,150,150)
        jogador = ev.get("destaque") or ev.get("autor") or ""; assist = None
    lt_h = 60 if assist else 44; lt_y = A - lt_h - 30
    d.rounded_rectangle([30, lt_y, 600, lt_y+lt_h], radius=4, fill=(10,10,10,160))
    d.rectangle([30, lt_y, 34, lt_y+lt_h], fill=cor_l+(220,))
    d.text((48, lt_y+7), jogador, font=fonte(26, True), fill=(255,255,255,255))
    if assist:
        d.text((48, lt_y+36), f"assist.  {assist}", font=fonte(15, False), fill=(200,200,200,200))
    return img


def _cartela_lance_tv(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """Estilo transmissão simples: placar compacto no canto, lower third limpo."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ca = hex_rgb(times[0]["cor"]); cb = hex_rgb(times[1]["cor"])
    nome_a = times[0]["nome"].upper(); nome_b = times[1]["nome"].upper()
    ph = 34; py0 = 18; px0 = 16
    f_team = fonte(15, True); f_score = fonte(22, True)
    bb_a = d.textbbox((0,0), nome_a, font=f_team); wta = bb_a[2]-bb_a[0]+14
    bb_b = d.textbbox((0,0), nome_b, font=f_team); wtb = bb_b[2]-bb_b[0]+14
    pw_s = 56; total_w = wta+pw_s+wtb
    d.rounded_rectangle([px0, py0, px0+total_w, py0+ph], radius=3, fill=(0,0,0,200))
    d.text((px0+wta//2, py0+ph//2), nome_a, font=f_team, fill=ca+(230,), anchor="mm")
    d.text((px0+wta+pw_s//2-12, py0+ph//2), str(placar_a), font=f_score, fill=(255,255,255,255), anchor="mm")
    d.text((px0+wta+pw_s//2, py0+ph//2-1), "-", font=fonte(16), fill=(150,150,150,200), anchor="mm")
    d.text((px0+wta+pw_s//2+12, py0+ph//2), str(placar_b), font=f_score, fill=(255,255,255,255), anchor="mm")
    d.text((px0+wta+pw_s+wtb//2, py0+ph//2), nome_b, font=f_team, fill=cb+(230,), anchor="mm")
    tempo_str = str(ev.get("tempo") or "")
    if tempo_str:
        # TV: quadrado verde escuro com texto branco — destaca como cronômetro ao vivo
        tw_tv = 72
        tx0_tv = px0 + total_w + 6
        d.rounded_rectangle([tx0_tv, py0, tx0_tv + tw_tv, py0 + ph], radius=3, fill=(0, 60, 20, 220))
        d.rounded_rectangle([tx0_tv, py0, tx0_tv + tw_tv, py0 + ph], radius=3, outline=(0, 200, 80, 200), width=1)
        d.text((tx0_tv + tw_tv // 2, py0 + ph // 2), tempo_str, font=fonte(14, True),
               fill=(0, 240, 100, 240), anchor="mm")
    if tipo == "gol":
        t_idx = ev.get("time", 0); cor_l = hex_rgb(times[t_idx]["cor"])
        jogador = ev.get("autor", ""); assist = ev.get("assist")
    else:
        tem = ev.get("time") is not None and 0 <= ev["time"] < len(times)
        cor_l = hex_rgb(times[ev["time"]]["cor"]) if tem else (200,200,200)
        jogador = ev.get("destaque") or ev.get("autor") or ""; assist = None
    lt_y = A - 72
    d.rectangle([0, lt_y, L, lt_y+2], fill=cor_l+(200,))
    d.rectangle([0, lt_y+2, L, A], fill=(5,5,5,195))
    d.text((36, lt_y+12), jogador, font=fonte(28,True), fill=(255,255,255,255))
    if assist:
        d.text((36, lt_y+44), f"assistência: {assist}", font=fonte(15,False), fill=(180,180,180,200))
    elif gol_neste_clipe:
        d.text((36, lt_y+44), "GOOOOOL!", font=fonte(16,True), fill=cor_l+(220,))
    return img


def cartela_lance(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """Overlay de placar e identificação de lance em linguagem de transmissão."""
    args = (ev, times, tipo, placar_a, placar_b, gol_neste_clipe, time_gol, d_)
    if TEMA == "fifa":
        return _cartela_lance_fifa(*args)
    if TEMA == "iss":
        return _cartela_lance_iss(*args)
    if TEMA == "pes":
        return _cartela_lance_pes(*args)
    if TEMA == "tv":
        return _cartela_lance_tv(*args)

    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    nome_a = _texto_ajustado(draw, times[0]["nome"].upper(), fonte(16, True), 220)
    nome_b = _texto_ajustado(draw, times[1]["nome"].upper(), fonte(16, True), 220)
    widths = []
    for nome in (nome_a, nome_b):
        bb = draw.textbbox((0, 0), nome, font=fonte(16, True))
        widths.append(max(150, min(230, bb[2] - bb[0] + 34)))
    score_w, timer_w, score_h = 148, 110, 64
    total_w = widths[0] + score_w + widths[1] + timer_w + 12
    x0, y0 = 50, 42
    draw.rounded_rectangle([x0 + 3, y0 + 5, x0 + total_w + 3, y0 + score_h + 5],
                           radius=16, fill=(0, 0, 0, 145))
    draw.rounded_rectangle([x0, y0, x0 + total_w, y0 + score_h], radius=16,
                           fill=(8, 15, 26, 238), outline=(255, 255, 255, 42), width=1)

    xa = x0 + 1
    draw.rounded_rectangle([xa, y0 + 1, xa + widths[0], y0 + score_h - 1], radius=14,
                           fill=(15, 25, 39, 250))
    draw.rectangle([xa, y0 + score_h - 5, xa + widths[0], y0 + score_h - 1], fill=ca + (255,))
    draw.text((xa + widths[0] // 2, y0 + 29), nome_a, font=fonte(16, True),
              fill=PREMIUM_TEXT + (255,), anchor="mm")

    xs = xa + widths[0]
    draw.rectangle([xs, y0 + 1, xs + score_w, y0 + score_h - 1], fill=(5, 10, 18, 255))
    draw.text((xs + 42, y0 + 30), str(placar_a), font=fonte(31, True),
              fill=PREMIUM_TEXT + (255,), anchor="mm")
    draw.text((xs + score_w // 2, y0 + 29), "×", font=fonte(19, False),
              fill=PREMIUM_MUTED + (255,), anchor="mm")
    draw.text((xs + score_w - 42, y0 + 30), str(placar_b), font=fonte(31, True),
              fill=PREMIUM_TEXT + (255,), anchor="mm")

    xb = xs + score_w
    draw.rectangle([xb, y0 + 1, xb + widths[1], y0 + score_h - 1], fill=(15, 25, 39, 250))
    draw.rectangle([xb, y0 + score_h - 5, xb + widths[1], y0 + score_h - 1], fill=cb + (255,))
    draw.text((xb + widths[1] // 2, y0 + 29), nome_b, font=fonte(16, True),
              fill=PREMIUM_TEXT + (255,), anchor="mm")

    xt = xb + widths[1] + 8
    draw.rounded_rectangle([xt, y0, xt + timer_w, y0 + score_h], radius=14,
                           fill=(10, 25, 28, 246), outline=(51, 103, 91, 170), width=1)
    draw.ellipse([xt + 14, y0 + 27, xt + 23, y0 + 36], fill=PREMIUM_ACCENT + (255,))
    draw.text((xt + 67, y0 + 31), str(ev.get("tempo") or "00:00"), font=fonte(19, True),
              fill=PREMIUM_TEXT + (255,), anchor="mm")

    if gol_neste_clipe and time_gol in (0, 1):
        cor_gol = ca if time_gol == 0 else cb
        label_gol = "GOL · " + _texto_ajustado(draw, times[time_gol]["nome"].upper(), fonte(12, True), 220)
        bb = draw.textbbox((0, 0), label_gol, font=fonte(12, True))
        pill_w = bb[2] - bb[0] + 28
        gx = x0 + widths[0] + score_w // 2 - pill_w // 2
        gy = y0 + score_h + 8
        draw.rounded_rectangle([gx, gy, gx + pill_w, gy + 32], radius=16,
                               fill=(8, 15, 26, 240), outline=cor_gol + (255,), width=2)
        draw.text((gx + pill_w // 2, gy + 16), label_gol, font=fonte(12, True),
                  fill=PREMIUM_TEXT + (255,), anchor="mm")

    desenhar_tv_watermark(img, d_, tamanho=(74, 74))

    time_idx = ev.get("time")
    valido = isinstance(time_idx, int) and 0 <= time_idx < len(times)
    cor_lance = hex_rgb(times[time_idx]["cor"]) if valido else PREMIUM_ACCENT
    time_nome = times[time_idx]["nome"] if valido else ""
    if tipo == "gol":
        titulo = ev.get("autor") or "Autor não informado"
        kicker = "GOL · " + (time_nome.upper() if time_nome else "PARTIDA")
        assist = ev.get("assist")
        cor_kicker = AMARELO_GOL
        altura = 126
    else:
        titulo = ev.get("destaque") or ev.get("autor") or ev.get("lance") or "Melhor momento"
        kicker = (ev.get("lance") or "MELHOR MOMENTO").upper()
        assist = None
        cor_kicker = cor_lance
        altura = 100

    f_nome = fonte(32, True)
    nome_fit = _texto_ajustado(draw, titulo, f_nome, 570)
    f_ass = fonte(16, False)
    largura_detalhe = draw.textbbox((0, 0), nome_fit, font=f_nome)[2]
    if assist:
        largura_detalhe = max(largura_detalhe, draw.textbbox(
            (0, 0), f"ASSISTÊNCIA  {assist}", font=f_ass)[2])
    largura = min(860, max(510, 150 + largura_detalhe + 40))
    card_x, card_y = 58, A - altura - 34
    draw.rounded_rectangle([card_x + 4, card_y + 6, card_x + largura + 4, card_y + altura + 6],
                           radius=20, fill=(0, 0, 0, 150))
    draw.rounded_rectangle([card_x, card_y, card_x + largura, card_y + altura], radius=20,
                           fill=(8, 15, 26, 235), outline=(255, 255, 255, 55), width=1)
    draw.rounded_rectangle([card_x, card_y + 14, card_x + 7, card_y + altura - 14],
                           radius=3, fill=cor_lance + (255,))

    avatar_size = 76 if tipo == "gol" else 66
    avatar = obter_avatar_jogador(titulo, times[time_idx] if valido else times[0],
                                  tamanho=(avatar_size, avatar_size), cor_time=cor_lance)
    avatar_x, avatar_y = card_x + 24, card_y + (altura - avatar_size) // 2
    if avatar:
        img.paste(avatar, (avatar_x, avatar_y), avatar)
    tx = avatar_x + avatar_size + 20
    draw.text((tx, card_y + 14), kicker, font=fonte(13, True), fill=cor_kicker + (255,))
    draw.text((tx, card_y + (37 if tipo == "gol" else 34)), nome_fit,
              font=f_nome, fill=PREMIUM_TEXT + (255,))
    if assist:
        label = "ASSISTÊNCIA"
        draw.text((tx, card_y + 86), label, font=fonte(12, True), fill=PREMIUM_MUTED + (255,))
        bb_label = draw.textbbox((0, 0), label, font=fonte(12, True))
        ax = tx + bb_label[2] + 10
        assist_avatar = obter_avatar_jogador(assist, times[time_idx] if valido else times[0],
                                             tamanho=(22, 22), cor_time=cor_lance)
        if assist_avatar:
            img.paste(assist_avatar, (ax, card_y + 84), assist_avatar)
            ax += 30
        draw.text((ax, card_y + 85), _texto_ajustado(draw, assist, fonte(14, True), 280),
                  font=fonte(14, True), fill=PREMIUM_TEXT + (255,))
    return img


# ---------------------------------------------------------------- PALETA DE CORES POR TEMA
def _paleta_tema():
    """Retorna cores base para o tema atual: (fundo_painel, borda, titulo, sub_titulo, accent)"""
    if TEMA == "fifa":
        return (6, 8, 14), (255, 255, 255), (255, 255, 255), (190, 195, 210), (255, 215, 0)
    if TEMA == "iss":
        return (0, 0, 30), (255, 255, 0), (255, 255, 0), (200, 200, 50), (255, 40, 40)
    if TEMA == "pes":
        return (16, 20, 28), (80, 90, 115), (255, 255, 255), (160, 168, 188), (255, 255, 255)
    if TEMA == "tv":
        return (8, 10, 16), (40, 50, 70), (255, 255, 255), (170, 178, 195), (0, 220, 120)
    return PAINEL, PAINEL_BORDA, DOURADO, FRACO, VERDE


def _desenhar_topo_tema(img, d, d_, y_logo_base=16, logo_tam=(110, 110)):
    """Renderiza logo + título do torneio de acordo com o tema. Retorna y_textos."""
    meta = d_["meta"]
    pfundo, pborda, ptitulo, psub, paccent = _paleta_tema()

    logo = obter_logo_campeonato(d_, tamanho=logo_tam)
    y_logo = y_logo_base
    if logo:
        lw, lh = logo.size
        lx = (L - lw) // 2
        if TEMA == "iss":
            # Bordas quadradas retrô
            d.rectangle([lx - 8, y_logo - 6, lx + lw + 8, y_logo + lh + 6], fill=(0, 0, 0))
            d.rectangle([lx - 9, y_logo - 7, lx + lw + 9, y_logo + lh + 7], outline=pborda, width=3)
        else:
            d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8],
                      fill=(0, 0, 0, 80))
            d.ellipse([lx - 10, y_logo - 8, lx + lw + 10, y_logo + lh + 8],
                      outline=ptitulo if TEMA == "fifa" else DOURADO, width=3)
            d.ellipse([lx - 7, y_logo - 5, lx + lw + 7, y_logo + lh + 5],
                      fill=(12, 18, 32))
        if logo.mode != "RGBA":
            logo = logo.convert("RGBA")
        img.paste(logo, (lx, y_logo), logo)
        y_textos = y_logo + lh + 16
    else:
        y_textos = y_logo_base + 10

    return y_textos


def _barra_topo_tema(d):
    """Desenha barra superior de acordo com o tema."""
    _, pborda, _, _, paccent = _paleta_tema()
    if TEMA == "iss":
        d.rectangle([0, 0, L, 14], fill=pborda)
        d.rectangle([0, 14, L, 22], fill=(255, 40, 40))
    elif TEMA == "fifa":
        d.rectangle([0, 0, L, 6], fill=(255, 255, 255))
        d.rectangle([0, 6, L, 10], fill=(0, 80, 200))
    elif TEMA == "pes":
        d.rectangle([0, 0, L, 5], fill=(70, 80, 105))
    elif TEMA == "tv":
        d.rectangle([0, 0, L, 6], fill=paccent)
    else:
        d.rectangle([0, 0, L, 6], fill=VERDE)

FIM_DE_JOGO_GOLS_POR_TELA = 12


def paginas_fim_de_jogo(d_):
    n_a = sum(1 for g in d_.get("gols", []) if g.get("time") == 0)
    n_b = sum(1 for g in d_.get("gols", []) if g.get("time") == 1)
    return max(1, -(-n_a // FIM_DE_JOGO_GOLS_POR_TELA), -(-n_b // FIM_DE_JOGO_GOLS_POR_TELA))


def _cartela_fim_de_jogo_tema(d_, pagina=0):
    """Placar final minimalista."""
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    cfg = {"fifa": ((8,10,16),(200,168,90)), "iss": ((10,10,20),(200,200,200)),
           "pes": ((10,14,22),(100,140,210)), "tv": ((8,10,14),(150,200,110))}
    bg, accent = cfg.get(TEMA, (PAINEL, DOURADO))
    psub = (65, 75, 95)
    gols_ord = sorted(d_.get("gols",[]), key=_tempo_em_segundos)
    gols_a = [g for g in gols_ord if g.get("time")==0]
    gols_b = [g for g in gols_ord if g.get("time")==1]
    gols_a_p = gols_a[pagina*FIM_DE_JOGO_GOLS_POR_TELA:(pagina+1)*FIM_DE_JOGO_GOLS_POR_TELA]
    gols_b_p = gols_b[pagina*FIM_DE_JOGO_GOLS_POR_TELA:(pagina+1)*FIM_DE_JOGO_GOLS_POR_TELA]
    pj = meta.get("placar_jogo") or [None, None]
    total_a = pj[0] if pj[0] is not None else len(gols_a)
    total_b = pj[1] if pj[1] is not None else len(gols_b)
    img = Image.new("RGB", (L, A), bg)
    d = ImageDraw.Draw(img)
    y = _topo_minimalista(img, d, d_, accent)
    cx = L // 2; cy_p = y + 12
    d.text((cx, cy_p + 14), "FIM DE JOGO", font=fonte(18, True), fill=(50,60,78), anchor="mm")
    d.text((cx - 140, cy_p + 52), times[0]["nome"].upper(), font=fonte(30, True), fill=ca, anchor="mm")
    d.text((cx + 140, cy_p + 52), times[1]["nome"].upper(), font=fonte(30, True), fill=cb, anchor="mm")
    d.text((cx - 68, cy_p + 110), str(total_a), font=fonte(90, True), fill=(240,242,248), anchor="mm")
    d.text((cx, cy_p + 108), "x", font=fonte(36, False), fill=(40,48,65), anchor="mm")
    d.text((cx + 68, cy_p + 110), str(total_b), font=fonte(90, True), fill=(240,242,248), anchor="mm")
    d.rectangle([cx-140, cy_p+138, cx-20, cy_p+141], fill=ca)
    d.rectangle([cx+20, cy_p+138, cx+140, cy_p+141], fill=cb)
    topo_col = cy_p + 160; col_w = 790; gap = 60
    col_x_a = (L - col_w*2 - gap) // 2; col_x_b = col_x_a + col_w + gap
    _col_gols(img, d, col_x_a, col_w, topo_col, A-40, times[0], gols_a_p, ca, accent, psub)
    _col_gols(img, d, col_x_b, col_w, topo_col, A-40, times[1], gols_b_p, cb, accent, psub)
    return img

def _cartela_fim_de_jogo_premium(d_, pagina=0):
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    subtitle = " · ".join(str(x) for x in (
        meta.get("pelada") or meta.get("torneio"),
        meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")
    ) if x)
    total_pag = paginas_fim_de_jogo(d_)
    etiqueta = f"PÁGINA {pagina + 1} / {total_pag}" if total_pag > 1 else "RESULTADO OFICIAL"
    img = _fundo_premium(d_)
    draw = ImageDraw.Draw(img)
    _cabecalho_premium(img, draw, d_, "PÓS-JOGO", "RESULTADO FINAL", subtitle, etiqueta)

    gols = sorted(d_.get("gols", []), key=_tempo_em_segundos)
    gols_a = [g for g in gols if g.get("time") == 0]
    gols_b = [g for g in gols if g.get("time") == 1]
    inicio = pagina * FIM_DE_JOGO_GOLS_POR_TELA
    gols_a_pag = gols_a[inicio:inicio + FIM_DE_JOGO_GOLS_POR_TELA]
    gols_b_pag = gols_b[inicio:inicio + FIM_DE_JOGO_GOLS_POR_TELA]
    placar = meta.get("placar_jogo") or [None, None]
    total_a = placar[0] if len(placar) > 0 and placar[0] is not None else len(gols_a)
    total_b = placar[1] if len(placar) > 1 and placar[1] is not None else len(gols_b)

    sx0, sy0, sx1, sy1 = 70, 176, L - 70, 360
    _painel_premium(draw, (sx0, sy0, sx1, sy1), fill=PREMIUM_PANEL_ALT, radius=24)
    split = L // 2
    draw.rounded_rectangle([sx0 + 2, sy0 + 20, sx0 + 10, sy1 - 20], radius=4, fill=ca)
    draw.rounded_rectangle([sx1 - 10, sy0 + 20, sx1 - 2, sy1 - 20], radius=4, fill=cb)
    draw.rounded_rectangle([split - 160, sy0 + 23, split + 160, sy1 - 23], radius=22,
                           fill=(7, 13, 23), outline=PREMIUM_LINE, width=1)

    draw.text((sx0 + 54, sy0 + 40), "TIME 01", font=fonte(13, True), fill=ca)
    draw.text((sx0 + 54, sy0 + 68), _texto_ajustado(draw, times[0]["nome"], fonte(29, True), 500),
              font=fonte(29, True), fill=PREMIUM_TEXT)
    draw.text((sx1 - 54, sy0 + 40), "TIME 02", font=fonte(13, True), fill=cb, anchor="ra")
    draw.text((sx1 - 54, sy0 + 68), _texto_ajustado(draw, times[1]["nome"], fonte(29, True), 500),
              font=fonte(29, True), fill=PREMIUM_TEXT, anchor="ra")
    draw.text((split - 73, sy0 + 92), str(total_a), font=fonte(80, True),
              fill=PREMIUM_TEXT, anchor="mm")
    draw.text((split, sy0 + 92), "×", font=fonte(30, False),
              fill=PREMIUM_MUTED, anchor="mm")
    draw.text((split + 73, sy0 + 92), str(total_b), font=fonte(80, True),
              fill=PREMIUM_TEXT, anchor="mm")
    draw.rounded_rectangle([sx0 + 30, sy1 - 14, split - 180, sy1 - 8], radius=3, fill=ca)
    draw.rounded_rectangle([split + 180, sy1 - 14, sx1 - 30, sy1 - 8], radius=3, fill=cb)

    col_y, col_h, col_w, gap = 390, 630, 876, 32
    col_a = 68
    col_b = col_a + col_w + gap

    def desenhar_lista(x0, time_obj, itens, todos, cor):
        _painel_premium(draw, (x0, col_y, x0 + col_w, col_y + col_h), radius=20)
        draw.rounded_rectangle([x0 + 2, col_y + 2, x0 + col_w - 2, col_y + 74], radius=18,
                               fill=PREMIUM_PANEL_ALT)
        draw.rectangle([x0 + 2, col_y + 64, x0 + col_w - 2, col_y + 74], fill=PREMIUM_PANEL_ALT)
        draw.rounded_rectangle([x0 + 22, col_y + 20, x0 + 28, col_y + 54], radius=3, fill=cor)
        draw.text((x0 + 44, col_y + 18), "GOLEADORES", font=fonte(12, True), fill=PREMIUM_MUTED)
        draw.text((x0 + 44, col_y + 36), _texto_ajustado(draw, time_obj["nome"].upper(), fonte(20, True), 530),
                  font=fonte(20, True), fill=PREMIUM_TEXT)
        gols_total = len(todos)
        chip = f"{gols_total:02d} GOL" + ("S" if gols_total != 1 else "")
        draw.text((x0 + col_w - 26, col_y + 39), chip, font=fonte(13, True),
                  fill=cor, anchor="ra")

        max_rows = FIM_DE_JOGO_GOLS_POR_TELA
        body_top = col_y + 91
        area = col_y + col_h - body_top - 18
        if not itens:
            draw.text((x0 + 32, body_top + 24), "Nenhum gol registrado", font=fonte(17, False),
                      fill=PREMIUM_MUTED)
            return
        n_rows = min(len(itens), max_rows)
        row_h = area // n_rows
        if n_rows <= 9:
            row_h = min(70, row_h)
        row_h = max(34, row_h)
        body_top += max(0, (area - row_h * n_rows) // 2)
        for i, goal in enumerate(itens[:max_rows]):
            yy = body_top + i * row_h
            if yy + row_h > col_y + col_h - 8:
                break
            if i:
                draw.line([x0 + 24, yy, x0 + col_w - 24, yy], fill=PREMIUM_LINE, width=1)
            time_text = str(goal.get("tempo") or "--:--")
            draw.rounded_rectangle([x0 + 24, yy + 6, x0 + 99, yy + row_h - 6], radius=11,
                                   fill=(7, 14, 24), outline=(54, 71, 93), width=1)
            draw.text((x0 + 61, yy + row_h // 2), time_text, font=fonte(14, True),
                      fill=PREMIUM_TEXT, anchor="mm")
            autor = _limpar_nome_pillow(goal.get("autor") or "Gol")
            avatar = obter_avatar_jogador(autor, time_obj, tamanho=(34, 34), cor_time=cor)
            if avatar:
                img.paste(avatar, (x0 + 118, yy + (row_h - 34) // 2), avatar)
            nome_x = x0 + 164
            max_nome = 400 if goal.get("assist") else col_w - 194
            f_autor = fonte(19, True)
            draw.text((nome_x, yy + (row_h - 22) // 2),
                      _texto_ajustado(draw, autor, f_autor, max_nome),
                      font=f_autor, fill=PREMIUM_TEXT)
            if goal.get("assist"):
                assist = "ASSIST. " + _limpar_nome_pillow(goal["assist"])
                f_ass = fonte(13, False)
                draw.text((x0 + col_w - 24, yy + row_h // 2),
                          _texto_ajustado(draw, assist, f_ass, 245),
                          font=f_ass, fill=PREMIUM_MUTED, anchor="rm")

    desenhar_lista(col_a, times[0], gols_a_pag, gols_a, ca)
    desenhar_lista(col_b, times[1], gols_b_pag, gols_b, cb)
    return img


def cartela_fim_de_jogo(d_, pagina=0):
    """Placar final e lista de gols com hierarquia de leitura para TV."""
    if TEMA != "atual":
        return _cartela_fim_de_jogo_tema(d_, pagina)
    return _cartela_fim_de_jogo_premium(d_, pagina)


CRONOLOGIA_POR_TELA = 16


def paginas_cronologia(d_):
    n = len(d_.get("gols", []))
    return max(1, -(-n // CRONOLOGIA_POR_TELA))


def cartela_cronologia(d_, pagina=0):
    """Linha do tempo dos gols em uma página limpa e fácil de acompanhar."""
    eventos = sorted(d_.get("gols", []), key=_tempo_em_segundos)
    total_pag = paginas_cronologia(d_)
    inicio = pagina * CRONOLOGIA_POR_TELA
    eventos_pagina = eventos[inicio:inicio + CRONOLOGIA_POR_TELA]
    etiqueta = f"PÁGINA {pagina + 1} / {total_pag}" if total_pag > 1 else f"{len(eventos)} GOLS"
    meta = d_.get("meta", {})
    subtitle = " · ".join(str(x) for x in (
        meta.get("pelada") or meta.get("torneio"), meta.get("comp") or meta.get("rodada"), meta.get("data")
    ) if x)
    img = _fundo_premium(d_)
    draw = ImageDraw.Draw(img)
    _cabecalho_premium(img, draw, d_, "LINHA DO TEMPO", "COMO FOI O JOGO", subtitle, etiqueta)

    x0, y0, w, h = 100, 188, 1720, 826
    _painel_premium(draw, (x0, y0, x0 + w, y0 + h), radius=22)
    draw.text((x0 + 34, y0 + 28), "CRONOLOGIA DOS GOLS", font=fonte(14, True), fill=PREMIUM_MUTED)
    draw.text((x0 + w - 34, y0 + 28), "MINUTO  ·  AUTOR  ·  ASSISTÊNCIA  ·  TIME",
              font=fonte(12, True), fill=PREMIUM_MUTED, anchor="ra")
    draw.line([x0 + 28, y0 + 66, x0 + w - 28, y0 + 66], fill=PREMIUM_LINE, width=1)

    if not eventos_pagina:
        draw.text((L // 2, y0 + h // 2), "Nenhum gol registrado nesta partida",
                  font=fonte(24, True), fill=PREMIUM_MUTED, anchor="mm")
        return img

    row_top = y0 + 82
    row_h = (h - 100) // max(len(eventos_pagina), 1)
    timeline_x = x0 + 78
    if len(eventos_pagina) > 1:
        draw.line([timeline_x, row_top + 18, timeline_x,
                   row_top + (len(eventos_pagina) - 1) * row_h + 45],
                  fill=(47, 62, 82), width=2)

    for i, goal in enumerate(eventos_pagina):
        time_idx = goal.get("time", 0)
        if not isinstance(time_idx, int) or not 0 <= time_idx < len(d_["times"]):
            time_idx = 0
        team = d_["times"][time_idx]
        color = hex_rgb(team.get("cor"))
        yy = row_top + i * row_h
        if i:
            draw.line([x0 + 28, yy, x0 + w - 28, yy], fill=(35, 49, 68), width=1)
        draw.ellipse([timeline_x - 8, yy + 17, timeline_x + 8, yy + 33],
                     fill=PREMIUM_PANEL, outline=color, width=3)
        draw.rounded_rectangle([x0 + 112, yy + 7, x0 + 192, yy + 47], radius=12,
                               fill=(7, 14, 24), outline=(55, 72, 95), width=1)
        draw.text((x0 + 152, yy + 27), str(goal.get("tempo") or "--:--"),
                  font=fonte(16, True), fill=PREMIUM_TEXT, anchor="mm")

        autor = _limpar_nome_pillow(goal.get("autor") or "Gol")
        avatar = obter_avatar_jogador(autor, team, tamanho=(42, 42), cor_time=color)
        if avatar:
            img.paste(avatar, (x0 + 224, yy + 6), avatar)
        draw.text((x0 + 282, yy + 8), _texto_ajustado(draw, autor, fonte(22, True), 400),
                  font=fonte(22, True), fill=PREMIUM_TEXT)
        if goal.get("assist"):
            draw.text((x0 + 282, yy + 35),
                      _texto_ajustado(draw, "ASSIST. " + goal["assist"], fonte(13, False), 400),
                      font=fonte(13, False), fill=PREMIUM_MUTED)

        chip_w = min(300, max(180, draw.textbbox((0, 0), team["nome"], font=fonte(13, True))[2] + 48))
        chip_x = x0 + w - chip_w - 28
        draw.rounded_rectangle([chip_x, yy + 11, chip_x + chip_w, yy + 43], radius=16,
                               fill=(18, 29, 45), outline=color, width=1)
        draw.ellipse([chip_x + 12, yy + 22, chip_x + 20, yy + 30], fill=color)
        draw.text((chip_x + 30, yy + 27),
                  _texto_ajustado(draw, team["nome"].upper(), fonte(13, True), chip_w - 46),
                  font=fonte(13, True), fill=PREMIUM_TEXT, anchor="lm")

    return img


def _cartela_destaques_tema(d_):
    """Destaques minimalistas."""
    cfg = {"fifa": ((8,10,16),(200,168,90)), "iss": ((10,10,20),(200,200,200)),
           "pes": ((10,14,22),(100,140,210)), "tv": ((8,10,14),(150,200,110))}
    bg, accent = cfg.get(TEMA, (PAINEL, DOURADO))
    psub = (65, 75, 95)
    medalha = [(200,168,90),(175,180,195),(165,110,70)]
    img = Image.new("RGB", (L, A), bg)
    d = ImageDraw.Draw(img)
    y = _topo_minimalista(img, d, d_, accent)
    d.text((L//2, y+12), "DESTAQUES DA PARTIDA", font=fonte(18, True), fill=(50,60,78), anchor="mm")
    topo = y + 40; w_card = L//2 - 80
    for col, (titulo, chave, campo) in enumerate([("ARTILHEIROS","artilheiros","gols"),
                                                   ("ASSISTENCIAS","garcons","assistencias")]):
        x0 = 50 if col == 0 else L//2 + 30
        d.text((x0, topo), titulo, font=fonte(16, True), fill=(55,65,85))
        d.rectangle([x0, topo+24, x0+w_card, topo+26], fill=(22,28,40))
        itens = (d_.get(chave) or [])[:5]; y_i = topo + 36
        for k, item in enumerate(itens):
            cor_m = medalha[k] if k < 3 else (50,58,78)
            alt = 88 if k == 0 else 70
            d.rectangle([x0, y_i, x0+w_card, y_i+alt], fill=(13,17,26))
            d.text((x0+18, y_i+alt//2), str(k+1), font=fonte(30 if k==0 else 22, True), fill=cor_m, anchor="lm")
            av_sz = alt - 14
            av = obter_avatar_jogador(item["jogador"], d_.get("times"), tamanho=(av_sz,av_sz), cor_time=cor_m)
            if av: img.paste(av, (x0+58, y_i+7), av)
            ox = x0 + 58 + av_sz + 14
            d.text((ox, y_i + 14), _limpar_nome_pillow(item["jogador"]),
                   font=fonte(26 if k==0 else 20, True), fill=(225,230,245))
            d.text((ox, y_i + (46 if k==0 else 40)), str(item[campo]) + "  " + campo,
                   font=fonte(14, False), fill=psub)
            d.text((x0+w_card-16, y_i+alt//2), str(item[campo]),
                   font=fonte(38 if k==0 else 28, True), fill=cor_m, anchor="rm")
            d.rectangle([x0, y_i+alt, x0+w_card, y_i+alt+2], fill=(18,22,32))
            y_i += alt + 2
    return img

def _cartela_destaques_premium(d_):
    meta = d_.get("meta", {})
    subtitle = " · ".join(str(x) for x in (
        meta.get("pelada") or meta.get("torneio"), meta.get("comp") or meta.get("rodada"), meta.get("data")
    ) if x)
    img = _fundo_premium(d_)
    draw = ImageDraw.Draw(img)
    _cabecalho_premium(img, draw, d_, "PÓS-JOGO", "DESTAQUES DA PARTIDA", subtitle, "TOP 5")

    medalhas = [(246, 196, 82), (184, 198, 214), (194, 132, 91), (93, 111, 136), (93, 111, 136)]
    colunas = [
        ("ARTILHEIROS", "artilheiros", "gols", "GOLS MARCADOS"),
        ("LÍDERES EM ASSISTÊNCIAS", "garcons", "assistencias", "ASSISTÊNCIAS"),
    ]
    card_y, card_h, card_w, gap = 184, 836, 862, 34
    card_xs = [64, 64 + card_w + gap]

    for x0, (title, key, field, label) in zip(card_xs, colunas):
        _painel_premium(draw, (x0, card_y, x0 + card_w, card_y + card_h), radius=22)
        draw.rounded_rectangle([x0 + 2, card_y + 2, x0 + card_w - 2, card_y + 104], radius=20,
                               fill=PREMIUM_PANEL_ALT)
        draw.rectangle([x0 + 2, card_y + 91, x0 + card_w - 2, card_y + 104], fill=PREMIUM_PANEL_ALT)
        draw.text((x0 + 30, card_y + 23), title, font=fonte(22, True), fill=PREMIUM_TEXT)
        draw.text((x0 + 30, card_y + 59), label, font=fonte(12, True), fill=PREMIUM_MUTED)
        draw.rounded_rectangle([x0 + card_w - 64, card_y + 32, x0 + card_w - 30, card_y + 66],
                               radius=17, fill=PREMIUM_BG, outline=PREMIUM_LINE, width=1)
        for bar_idx, bar_h in enumerate((9, 15, 22)):
            bx = x0 + card_w - 55 + bar_idx * 7
            draw.rounded_rectangle([bx, card_y + 57 - bar_h, bx + 4, card_y + 57],
                                   radius=2, fill=PREMIUM_ACCENT)

        itens = (d_.get(key) or [])[:5]
        row_top = card_y + 120
        row_h = (card_h - 148) // 5
        if not itens:
            draw.text((x0 + 34, row_top + 38), "Ainda não há dados para este ranking",
                      font=fonte(17, False), fill=PREMIUM_MUTED)
            continue

        for i, item in enumerate(itens):
            yy = row_top + i * row_h
            medal = medalhas[min(i, len(medalhas) - 1)]
            is_top = i == 0
            row_box = [x0 + 18, yy + 4, x0 + card_w - 18, yy + row_h - 8]
            draw.rounded_rectangle(row_box, radius=16,
                                   fill=(20, 32, 49) if is_top else (10, 18, 30),
                                   outline=medal if i < 3 else (34, 48, 66), width=2 if i < 3 else 1)
            draw.ellipse([x0 + 34, yy + row_h // 2 - 25, x0 + 84, yy + row_h // 2 + 25],
                         fill=medal)
            draw.text((x0 + 59, yy + row_h // 2), f"{i + 1:02d}", font=fonte(17, True),
                      fill=(8, 14, 23), anchor="mm")

            jogador = _limpar_nome_pillow(item.get("jogador") or "Jogador")
            avatar = obter_avatar_jogador(jogador, d_.get("times"), tamanho=(64, 64), cor_time=medal)
            if avatar:
                img.paste(avatar, (x0 + 104, yy + (row_h - 64) // 2), avatar)
            text_x = x0 + 190
            max_text = card_w - 335
            nome_font = fonte(24 if is_top else 21, True)
            draw.text((text_x, yy + row_h // 2 - 23),
                      _texto_ajustado(draw, jogador, nome_font, max_text),
                      font=nome_font, fill=PREMIUM_TEXT)
            draw.text((text_x, yy + row_h // 2 + 12), label,
                      font=fonte(11, True), fill=PREMIUM_MUTED)

            numero = str(item.get(field, 0))
            draw.text((x0 + card_w - 44, yy + row_h // 2 - 2), numero,
                      font=fonte(46 if is_top else 38, True), fill=medal, anchor="rm")
            draw.text((x0 + card_w - 45, yy + row_h // 2 + 28),
                      "GOLS" if field == "gols" else "AST",
                      font=fonte(10, True), fill=PREMIUM_MUTED, anchor="rm")
    return img


def cartela_destaques(d_):
    if TEMA != "atual":
        return _cartela_destaques_tema(d_)
    return _cartela_destaques_premium(d_)


def _cartela_assista_outros_videos_tema(d_):
    """Tela final minimalista."""
    cfg = {"fifa": ((8,10,16),(200,168,90)), "iss": ((10,10,20),(200,200,200)),
           "pes": ((10,14,22),(100,140,210)), "tv": ((8,10,14),(150,200,110))}
    bg, accent = cfg.get(TEMA, (PAINEL, DOURADO))
    img = Image.new("RGB", (L, A), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 4], fill=accent)
    logo = obter_logo_campeonato(d_, tamanho=(140, 140))
    logo_y = 80
    if logo:
        if logo.mode != "RGBA": logo = logo.convert("RGBA")
        lw, lh = logo.size
        img.paste(logo, ((L-lw)//2, logo_y), logo)
        cy = logo_y + lh + 60
    else:
        cy = 280
    torneio = (d_["meta"].get("pelada") or d_["meta"].get("torneio") or "").upper()
    if torneio:
        d.text((L//2, cy - 20), torneio, font=fonte(20, False), fill=(50,60,78), anchor="mm")
    d.rectangle([L//2-180, cy+8, L//2+180, cy+11], fill=(28,34,50))
    d.text((L//2, cy+48), "ASSISTA OUTROS VIDEOS", font=fonte(52, True), fill=(225,228,240), anchor="mm")
    d.text((L//2, cy+112), "clique nos sugeridos abaixo", font=fonte(22, False), fill=(45,55,72), anchor="mm")
    d.text((L//2, A-44), "obrigado por assistir", font=fonte(20, False), fill=(38,46,62), anchor="mm")
    return img

def cartela_assista_outros_videos(d_):
    """Tela final limpa, com espaço livre para os quadros recomendados do YouTube."""
    if TEMA != "atual":
        return _cartela_assista_outros_videos_tema(d_)
    img = _fundo_premium(d_)
    d = ImageDraw.Draw(img)
    _cabecalho_premium(img, d, d_, "FIM DE JOGO", "OBRIGADO POR ASSISTIR",
                       "Acompanhe mais partidas e melhores momentos", "ATÉ A PRÓXIMA")
    # A área central fica livre para os quadros recomendados do YouTube.
    x0, y0, w, h = 250, 230, 1420, 570
    _painel_premium(d, (x0, y0, x0 + w, y0 + h), radius=26)
    d.text((L // 2, y0 + 94), "CONTINUE NO CLIMA DO JOGO", font=fonte(16, True),
           fill=PREMIUM_ACCENT, anchor="mm")
    d.text((L // 2, y0 + h - 78), "ESCOLHA UM VÍDEO PARA ASSISTIR", font=fonte(18, True),
           fill=PREMIUM_MUTED, anchor="mm")
    d.text((L // 2, A - 92), "Nos vemos na próxima partida", font=fonte(20, False),
           fill=PREMIUM_MUTED, anchor="mm")
    return img


# --------------------------------------------------------------- ffmpeg

def roda(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERRO ffmpeg:\n", r.stderr[-1500:])
        raise SystemExit(1)


def dados_midia(caminho):
    resultado = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-of", "json", caminho], capture_output=True, text=True, check=True)
    return json.loads(resultado.stdout)


def duracao_video(caminho):
    dados = dados_midia(caminho)
    video = next(s for s in dados["streams"] if s["codec_type"] == "video")
    return float(video.get("duration") or dados["format"]["duration"])


def validar_duracao(caminho, esperada, tolerancia=0.1):
    obtida = duracao_video(caminho)
    if abs(obtida - esperada) > tolerancia:
        raise RuntimeError(
            f"Duracao alterada em {caminho}: esperado {esperada:.3f}s, "
            f"obtido {obtida:.3f}s. Montagem interrompida para preservar 1x.")


def filtro_audio_normalizado(clipe):
    """Mede cada camera e aplica o mesmo alvo de volume, sem mudar o tempo.

    As duas passagens usam o mesmo downmix stereo. Silencio permanece silencio.
    """
    resultado = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", clipe,
        "-map", "0:a:0", "-vn", "-af", f"{AUDIO_FORMAT},{LOUDNESS}:print_format=json",
        "-f", "null", "-"
    ], capture_output=True, text=True, check=True)
    inicio = resultado.stderr.rfind("{")
    fim = resultado.stderr.rfind("}")
    if inicio < 0 or fim < inicio:
        raise RuntimeError(f"Nao foi possivel medir o volume de {clipe}")
    medidas = json.loads(resultado.stderr[inicio:fim + 1])
    campos = {"measured_I": "input_i", "measured_TP": "input_tp",
              "measured_LRA": "input_lra", "measured_thresh": "input_thresh",
              "offset": "target_offset"}
    if not all(math.isfinite(float(medidas[c])) for c in campos.values()):
        return AUDIO_FORMAT
    parametros = ":".join(f"{opcao}={float(medidas[campo])}" for opcao, campo in campos.items())
    return f"{AUDIO_FORMAT},{LOUDNESS}:{parametros}:linear=true"


def concatenar_segmentos(partes, lista, saida):
    # O concat com stream copy exige bases de tempo e formatos iguais.
    # Em especial, AAC 44,1 kHz nao pode ser interpretado como AAC 48 kHz.
    # Se houver incompatibilidade, recodifica TODOS os segmentos para o formato padrão
    referencia = None
    duracao_total = 0.0
    incompativeis = []
    for i, parte in enumerate(partes):
        dados = dados_midia(parte)
        assinatura = [tuple(s.get(k) for k in (
            "codec_type", "codec_name", "time_base", "width", "height",
            "pix_fmt", "sample_aspect_ratio", "sample_rate", "channels", "channel_layout"
        )) for s in dados["streams"]]
        if referencia is not None and assinatura != referencia:
            print(f"[!] Segmento {i+1} incompativel detectado: {os.path.basename(parte)}")
            incompativeis.append(i)
        elif referencia is None:
            referencia = assinatura
        duracao_total += float(dados["format"]["duration"])
    
    if incompativeis:
        nomes = ", ".join(os.path.basename(partes[i]) for i in incompativeis)
        raise RuntimeError(
            f"Segmento incompativel detectado para concatenacao: {nomes}. "
            "Gere novamente os clipes para padronizar o formato antes da montagem."
        )
    
    with open(lista, "w", encoding="utf-8") as f:
        for parte in partes:
            caminho = parte.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{caminho}'\n")
    roda(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", lista, "-c", "copy", "-movflags", "+faststart", saida])
    validar_duracao(saida, duracao_total, tolerancia=0.15)


def seg_de_imagem(img_path, dur, saida, fade=0.5, crf=24, preset="medium", codec="libx264"):
    c_v = codec if codec in ("libx264", "libx265") else "libx264"
    roda(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_path,
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
          "-t", str(dur), "-r", str(FPS),
          "-vf", (f"split[a][b];[a]scale={LV}:{AV}:force_original_aspect_ratio=increase,crop={LV}:{AV},"
                  f"boxblur=40:6,eq=brightness=-0.08[bg];[b]scale={LV}:-2[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2," if VERTICAL else "")
                 + f"format=yuv420p,fade=t=in:st=0:d={fade},"
                 f"fade=t=out:st={max(dur - fade, 0.1)}:d={fade}{escala_saida()},setsar=1",
          "-c:v", c_v, "-preset", str(preset), "-crf", str(crf),
          "-pix_fmt", "yuv420p", "-movflags", "+faststart",
          "-video_track_timescale", str(VIDEO_TIMESCALE),
          "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_HZ), "-ac", "2", "-shortest", saida])


def seg_de_clipe(clipe, overlay_png, saida, sem_audio, fade=0.4, ajuste_cor=None, zoom=1.0, zoom_x=0.5, zoom_y=0.5, crf=24, preset="medium", codec="libx264"):
    dur = duracao_video(clipe)
    sem_audio = sem_audio or not any(
        s["codec_type"] == "audio" for s in dados_midia(clipe)["streams"])

    ini = 0.5
    fim = max(dur - 0.4, ini + 2.0)

    filtro_cor = ""
    if ajuste_cor and isinstance(ajuste_cor, dict):
        eq_items = []
        if ajuste_cor.get("brilho") is not None:
            b = float(ajuste_cor["brilho"]) - 1.0
            eq_items.append(f"brightness={b:.2f}")
        if ajuste_cor.get("contraste") is not None:
            c = float(ajuste_cor["contraste"])
            eq_items.append(f"contrast={c:.2f}")
        if ajuste_cor.get("saturacao") is not None:
            s = float(ajuste_cor["saturacao"])
            eq_items.append(f"saturation={s:.2f}")
        if eq_items:
            filtro_cor = ",eq=" + ":".join(eq_items)

    try:
        zoom = min(2.2, max(1.0, float(zoom)))
    except (TypeError, ValueError):
        zoom = 1.0
    try:
        zoom_x = min(1.0, max(0.0, float(zoom_x)))
        zoom_y = min(1.0, max(0.0, float(zoom_y)))
    except (TypeError, ValueError):
        zoom_x, zoom_y = 0.5, 0.5
    filtro_zoom = "" if zoom <= 1.01 else (
        f"crop=iw/{zoom:.2f}:ih/{zoom:.2f}:(iw-ow)*{zoom_x:.4f}:(ih-oh)*{zoom_y:.4f},"
    )
    if VERTICAL:
        vf = f"{filtro_recorte_vertical()},fps={FPS}{filtro_cor},format=yuv420p"
    else:
        vf = (f"{filtro_zoom}scale={L}:{A}:force_original_aspect_ratio=decrease,"
              f"pad={L}:{A}:(ow-iw)/2:(oh-ih)/2,fps={FPS}{filtro_cor},format=yuv420p")
    filtro = (f"[0:v]{vf}[v0];"
              f"[1:v]format=rgba,fade=t=in:st={ini}:d=0.35:alpha=1,"
              f"fade=t=out:st={fim - 0.35}:d=0.35:alpha=1[ov];"
              f"[v0][ov]overlay=0:0:enable='between(t,{ini},{fim})',"
              f"fade=t=in:st=0:d={fade},fade=t=out:st={max(dur - fade, 0.1):.2f}:d={fade}"
              f"{escala_saida()},setsar=1[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clipe,
           "-loop", "1", "-t", str(dur), "-i", overlay_png]
    if sem_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter_complex", filtro, "-map", "[v]", "-map", "2:a"]
    else:
        audio_normalizado = filtro_audio_normalizado(clipe)
        cmd += ["-filter_complex",
                filtro + f";[0:a:0]{audio_normalizado},afade=t=in:st=0:d={fade},"
                         f"afade=t=out:st={max(dur - fade, 0.1):.2f}:d={fade}[a]",
                "-map", "[v]", "-map", "[a]"]
    c_v = codec if codec in ("libx264", "libx265") else "libx264"
    cmd += ["-t", str(dur), "-r", str(FPS), "-c:v", c_v, "-preset", str(preset),
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-video_track_timescale", str(VIDEO_TIMESCALE),
            "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_HZ), "-ac", "2", saida]
    roda(cmd)
    validar_duracao(saida, dur)


def _cameras_do_lance(ev):
    """Câmeras (1 a 3) marcadas para o lance, sem repetir e na ordem escolhida."""
    bruto = ev.get("cameras_clipe")
    if not isinstance(bruto, list) or not bruto:
        bruto = [ev.get("camera") or 1]
    cams = []
    for c in bruto:
        try:
            c = int(c)
        except (TypeError, ValueError):
            continue
        if 1 <= c <= 3 and c not in cams:
            cams.append(c)
    return cams or [1]


def clipe_da_camera_sincronizada(ev, cameras, pasta_tmp):
    """Cria o trecho equivalente numa câmera alternativa.

    inicio_jogo_s é o instante, dentro de cada arquivo, em que começa o jogo.
    Assim o mesmo segundo da partida cai na câmera correta mesmo se as gravações
    começaram em momentos diferentes.
    """
    try:
        camera = int(ev.get("camera") or 1)
    except (TypeError, ValueError):
        camera = 1
    if camera <= 1 or not isinstance(cameras, list) or len(cameras) < camera:
        return None
    principal, alternativa = cameras[0] or {}, cameras[camera - 1] or {}
    origem = alternativa.get("caminho")
    if not origem or not os.path.isfile(origem):
        return None
    try:
        inicio_ref = float(ev.get("inicio_s"))
        fim_ref = float(ev.get("fim_s"))
        if fim_ref <= inicio_ref:
            return None
        inicio_jogo_ref = float(principal.get("inicio_jogo_s") or 0)
        inicio_jogo_cam = float(alternativa.get("inicio_jogo_s") or 0)
    except (TypeError, ValueError):
        return None
    inicio_cam = max(0, inicio_ref - inicio_jogo_ref + inicio_jogo_cam)
    duracao = fim_ref - inicio_ref
    saida = os.path.join(pasta_tmp, f"cam{camera}_{int(ev.get('indice', 0)):02d}.mp4")
    try:
        roda(clip_command(origem, float(f"{inicio_cam:.3f}"),
                          float(f"{duracao:.3f}"), saida))
        return saida if os.path.exists(saida) else None
    except Exception:
        return None


def _normaliza_roteiro(raw_roteiro, por_indice):
    """
    Garante que os clipes sejam ordenados por TEMPO CRONOLÓGICO do jogo.
    """
    def chave_tempo(idx):
        if idx in por_indice:
            return _tempo_em_segundos(por_indice[idx][1])
        return 0.0

    if raw_roteiro is None:
        return [{"i": k} for k in sorted(por_indice.keys(), key=chave_tempo)]

    itens = []
    for item in raw_roteiro:
        if isinstance(item, dict):
            idx = item.get("i", item.get("indice"))
            if idx is not None:
                itens.append(int(idx))
        elif isinstance(item, (int, str)):
            try:
                itens.append(int(item))
            except (TypeError, ValueError):
                pass

    if not itens:
        return [{"i": k} for k in sorted(por_indice.keys(), key=chave_tempo)]

    vistos = set()
    unicos = []
    for idx in itens:
        if idx in por_indice and idx not in vistos:
            unicos.append(idx)
            vistos.add(idx)

    unicos_ordenados = sorted(unicos, key=chave_tempo)
    return [{"i": idx} for idx in unicos_ordenados]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partida", default="partida.json")
    ap.add_argument("--clipes", default="gols/clipes")
    ap.add_argument("--saida", default="final/melhores_momentos.mp4")
    ap.add_argument("--saida_gols", default="final/apenas_gols.mp4")
    ap.add_argument("--abertura", type=float, default=7.0)
    ap.add_argument("--fechamento", type=float, default=8.0)
    ap.add_argument("--roteiro", help="Indices dos clipes em ordem, ex.: 2,5,9")
    ap.add_argument("--sem_audio", action="store_true")
    ap.add_argument("--sem_abertura", action="store_true")
    ap.add_argument("--sem_fechamento", action="store_true")
    ap.add_argument("--fundo", help="Caminho da imagem de fundo para as cartelas")
    ap.add_argument("--brilho", type=float, default=None, help="Ajuste de brilho dos clipes (1.0 = normal)")
    ap.add_argument("--saturacao", type=float, default=None, help="Ajuste de saturacao dos clipes (1.0 = normal)")
    ap.add_argument("--contraste", type=float, default=None, help="Ajuste de contraste dos clipes (1.0 = normal)")
    ap.add_argument("--crf", type=int, default=24, help="Nível de compressão CRF (20=original/pesado, 24=otimizado/recomendado, 27=compacto, 29=ultraleve)")
    ap.add_argument("--preset", default="medium", help="Preset do encoder (ultrafast, fast, medium, slow)")
    ap.add_argument("--codec", default="libx264", help="Codec de vídeo (libx264, libx265)")
    ap.add_argument("--resolucao", type=int, default=1080, choices=[480, 720, 1080, 1440, 2160],
                    help="Altura do vídeo final em pixels (16:9)")
    ap.add_argument("--formato", choices=["16:9", "9:16"], default="16:9",
                    help="9:16 gera video vertical; a resolucao passa a ser a LARGURA (720, 1080, ...)")
    ap.add_argument("--recorte", default=None,
                    help="9:16: retangulo escolhido no quadro como x,y,altura (0 a 1), ex.: 0.22,0,1")
    ap.add_argument("--tema", default="atual",
                    choices=["atual", "fifa", "iss", "pes", "tv"],
                    help="Estilo visual das cartelas: atual, fifa, iss, pes, tv")
    args = ap.parse_args()
    global ALTURA_SAIDA, VERTICAL, RECORTE, TEMA
    TEMA = args.tema
    ALTURA_SAIDA = args.resolucao
    if args.formato == "9:16":
        VERTICAL = True
        if args.recorte:
            try:
                x0, y0, hf = (float(v) for v in args.recorte.split(","))
                hf = min(1.0, max(0.2, hf))
                RECORTE = (min(1.0, max(0.0, x0)), min(1.0, max(0.0, y0)), hf)
            except ValueError:
                print("AVISO: --recorte invalido; usando o recorte central.")

    with open(args.partida, encoding="utf-8-sig") as f:
        d = json.load(f)

    if args.fundo:
        d["_fundo_custom"] = args.fundo

    ajuste_cor = None
    fc = d.get("meta", {}).get("fundo_config", {}) if isinstance(d.get("meta"), dict) else {}
    if fc.get("aplicar_video_clipes") or args.brilho is not None or args.saturacao is not None or args.contraste is not None:
        ajuste_cor = {
            "brilho": args.brilho if args.brilho is not None else fc.get("brilho", 1.0),
            "saturacao": args.saturacao if args.saturacao is not None else fc.get("saturacao", 1.0),
            "contraste": args.contraste if args.contraste is not None else fc.get("contraste", 1.0),
        }

    por_indice = {g["indice"]: ("gol", g) for g in d.get("gols", [])}
    por_indice.update({l["indice"]: ("lance", l) for l in d.get("lances", [])})

    # O zoom (área escolhida no quadro) é gravado em gols/gols.json ao arrastar o quadro.
    # Ele é a fonte mais atual: o partida.json pode ter sido regravado sem esses campos.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(args.clipes)), "gols.json"), encoding="utf-8-sig") as f:
            zoom_por_indice = {e["indice"]: e for e in json.load(f).get("gols", []) if "indice" in e}
        for idx_z, (_, ev_z) in por_indice.items():
            src = zoom_por_indice.get(idx_z)
            if src and src.get("zoom") is not None:
                ev_z["zoom"] = src["zoom"]
                ev_z["zoom_x"] = src.get("zoom_x", 0.5)
                ev_z["zoom_y"] = src.get("zoom_y", 0.5)
            if src and src.get("zoom_por_camera"):
                ev_z["zoom_por_camera"] = src["zoom_por_camera"]
    except (OSError, ValueError):
        pass

    if args.roteiro:
        raw_roteiro = [{"i": int(x.strip())} for x in args.roteiro.split(",") if x.strip()]
    else:
        raw_roteiro = d.get("roteiro")

    roteiro = _normaliza_roteiro(raw_roteiro, por_indice)
    if not roteiro:
        print("nada para montar: o partida.json nao tem gols nem lances.")
        return

    os.makedirs(os.path.dirname(args.saida) or ".", exist_ok=True)
    if args.saida_gols:
        os.makedirs(os.path.dirname(args.saida_gols) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="montagem_")
    partes = []
    partes_gols = []
    try:
        print(f"gerando cartelas e clipes (codec={args.codec}, crf={args.crf}, preset={args.preset})...")
        if not args.sem_abertura:
            print("  gerando cartela de abertura animada (revelando jogadores um a um)...")
            s = gerar_abertura_animada(d, tmp, args.abertura,
                                       crf=args.crf, preset=args.preset, codec=args.codec)
            partes.append(s)
            partes_gols.append(s)

        faltando = []

        # O placar mostrado em cada lance é sempre o placar real da partida,
        # inclusive ao montar um vídeo filtrado para apenas um jogador.  Antes,
        # ele era contado só pelos itens do roteiro e um vídeo do Will, por
        # exemplo, podia mostrar 5 × 0 quando a partida já estava em 10 × 5.
        gols_da_partida = sorted(
            d.get("gols", []),
            key=lambda gol: (_tempo_em_segundos(gol), gol.get("indice", 0)),
        )

        def placar_no_momento(evento):
            tempo_evento = _tempo_em_segundos(evento)
            indice_evento = evento.get("indice", 0)
            time_a = 0
            time_b = 0
            for gol in gols_da_partida:
                tempo_gol = _tempo_em_segundos(gol)
                indice_gol = gol.get("indice", 0)
                # Inclui os gols anteriores e o gol deste próprio clipe.  Em
                # eventos simultâneos, respeita a ordem registrada no jogo.
                if tempo_gol > tempo_evento or (
                    tempo_gol == tempo_evento and indice_gol > indice_evento
                ):
                    continue
                if gol.get("time") == 0:
                    time_a += 1
                elif gol.get("time") == 1:
                    time_b += 1
            return time_a, time_b

        for n, item in enumerate(roteiro, 1):
            idx = item["i"]
            if idx not in por_indice:
                continue
            tipo, ev = por_indice[idx]
            # Câmeras marcadas para este lance: o lance é repetido, uma câmera depois da outra.
            cams = _cameras_do_lance(ev)
            fontes = []
            for cam in cams:
                if cam == 1:
                    principal = os.path.join(args.clipes, f"gol_{idx:02d}.mp4")
                    if os.path.exists(principal):
                        fontes.append((1, principal))
                    else:
                        faltando.append(os.path.basename(principal))
                    continue
                # Pasta própria de cada câmera (gols/clipes_cam2, clipes_cam3); se o
                # clipe ainda não foi cortado lá, corta agora a partir do vídeo da câmera.
                pasta_cam = os.path.join(os.path.dirname(os.path.abspath(args.clipes)), f"clipes_cam{cam}")
                arq_cam = os.path.join(pasta_cam, f"gol_{idx:02d}.mp4")
                if os.path.exists(arq_cam):
                    fontes.append((cam, arq_cam))
                    continue
                alternativo = clipe_da_camera_sincronizada(dict(ev, camera=cam), d.get("meta", {}).get("cameras", []), tmp)
                if alternativo:
                    fontes.append((cam, alternativo))
                else:
                    print(f"  AVISO: clipe #{idx} sem a camera {cam}; pulando essa camera.")
            if not fontes:
                continue

            gol_neste_clipe = tipo == "gol"
            time_gol = ev.get("time") if gol_neste_clipe else None
            placar_a, placar_b = placar_no_momento(ev)

            png = os.path.join(tmp, f"ov{n:03d}.png")
            ov = cartela_lance(ev, d["times"], tipo, placar_a, placar_b,
                               gol_neste_clipe=gol_neste_clipe, time_gol=time_gol, d_=d)
            (overlay_para_vertical(ov) if VERTICAL else ov).save(png)

            rot = ev.get("autor") or ev.get("lance") or "lance"
            status_placar = f"[{placar_a} × {placar_b}]"
            for cam, clipe in fontes:
                s = os.path.join(tmp, f"s{n:03d}_c{cam}.mp4")
                sufixo = f" (câmera {cam})" if len(fontes) > 1 else ""
                print(f"  [{n:02d}/{len(roteiro)}] {ev.get('tempo','')} {status_placar} {tipo}: {rot}{sufixo}")
                zoom_cam, zoom_x_cam, zoom_y_cam = obter_zoom_camera(ev, cam)
                seg_de_clipe(clipe, png, s, args.sem_audio, ajuste_cor=ajuste_cor,
                              zoom=zoom_cam, zoom_x=zoom_x_cam, zoom_y=zoom_y_cam,
                              crf=args.crf, preset=args.preset, codec=args.codec)
                partes.append(s)
                if tipo == "gol":
                    partes_gols.append(s)

        if faltando:
            print("AVISO: clipes nao encontrados:", ", ".join(faltando))

        if not args.sem_fechamento:
            print("  gerando cartelas de fechamento e placar final...")
            cartelas = []
            for pg in range(paginas_fim_de_jogo(d)):
                cartelas.append((f"fim_de_jogo_{pg + 1}",
                                 lambda d_, pg=pg: cartela_fim_de_jogo(d_, pg),
                                 args.fechamento))
            for pg in range(paginas_cronologia(d)):
                cartelas.append((f"cronologia_{pg + 1}",
                                 lambda d_, pg=pg: cartela_cronologia(d_, pg),
                                 args.fechamento))
            cartelas.append(("destaques", cartela_destaques, args.fechamento))
            for nome, func, dur in cartelas:
                p = os.path.join(tmp, f"{nome}.png")
                func(d).save(p)
                s = os.path.join(tmp, f"z_{nome}.mp4")
                seg_de_imagem(p, dur, s, crf=args.crf, preset=args.preset, codec=args.codec)
                partes.append(s)
                partes_gols.append(s)

        # Encerramento de retenção: sempre fica nos dois vídeos por 30 segundos.
        p = os.path.join(tmp, "assista_outros_videos.png")
        cartela_assista_outros_videos(d).save(p)
        s = os.path.join(tmp, "z_assista_outros_videos.mp4")
        seg_de_imagem(p, 30, s, crf=args.crf, preset=args.preset, codec=args.codec)
        partes.append(s)
        partes_gols.append(s)

        lista = os.path.join(tmp, "lista.txt")
        print("\njuntando vídeo completo (todos os clipes)...")
        concatenar_segmentos(partes, lista, args.saida)

        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", args.saida],
                             capture_output=True, text=True).stdout.strip()
        print(f"\npronto (todos os clipes): {os.path.abspath(args.saida)}")
        if dur:
            t = float(dur)
            print(f"duracao: {int(t // 60)}min {int(t % 60)}s | {len(partes)} segmentos")

        if args.saida_gols and any(item["i"] in por_indice and por_indice[item["i"]][0] == "gol" for item in roteiro):
            lista_gols = os.path.join(tmp, "lista_gols.txt")
            print("\njuntando vídeo só dos gols...")
            concatenar_segmentos(partes_gols, lista_gols, args.saida_gols)
            dur_g = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                  "format=duration", "-of", "csv=p=0", args.saida_gols],
                                 capture_output=True, text=True).stdout.strip()
            print(f"\npronto (só gols): {os.path.abspath(args.saida_gols)}")
            if dur_g:
                tg = float(dur_g)
                print(f"duracao só gols: {int(tg // 60)}min {int(tg % 60)}s | {len(partes_gols)} segmentos")

        try:
            if sys.platform != "win32":
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
                cmd_notif = ["notify-send", "-a", "fut-bin"]
                if os.path.isfile(icon_path):
                    cmd_notif.extend(["-i", icon_path])
                cmd_notif.extend([
                    "-u", "normal",
                    "⚽ Renderização Concluída! — fut-bin",
                    "A montagem dos vídeos de melhores momentos e gols foi finalizada com sucesso!"
                ])
                subprocess.Popen(cmd_notif)
        except Exception:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
