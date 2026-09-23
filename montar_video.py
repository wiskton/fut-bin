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
VERDE = (34, 197, 94)
BRANCO = (255, 255, 255)
AMARELO_GOL = (250, 204, 21)
DOURADO = (255, 215, 0)

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
            f_nome = fonte(15, True)
            bb = draw.textbbox((0, 0), nome, font=f_nome)
            nw = bb[2] - bb[0]
            nh = bb[3] - bb[1]
            nx0 = cx - nw // 2 - 8
            ny0 = cy + r + 5
            draw.rounded_rectangle([nx0, ny0, nx0 + nw + 16, ny0 + nh + 6], radius=5,
                                   fill=(12, 16, 26, 230), outline=(65, 80, 105), width=1)
            draw.text((cx - nw // 2, ny0 + 2), nome, font=f_nome, fill=(255, 255, 255))


def cartela_abertura(d_):
    img = criar_fundo_base(d_)
    d = ImageDraw.Draw(img)
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])

    # Barra superior de acabamento
    d.rectangle([0, 0, L, 6], fill=VERDE)

    # 1. LOGO DO CAMPEONATO CENTRALIZADA NO TOPO (Estilo transmissão oficial)
    logo_ab = obter_logo_campeonato(d_, tamanho=(110, 110))
    y_logo = 16
    if logo_ab:
        lw, lh = logo_ab.size
        lx = (L - lw) // 2
        # Fundo brilhante para a logo
        d.ellipse([lx - 10, y_logo - 6, lx + lw + 10, y_logo + lh + 6],
                  fill=(16, 24, 38), outline=DOURADO, width=2)
        if logo_ab.mode != "RGBA":
            logo_ab = logo_ab.convert("RGBA")
        img.paste(logo_ab, (lx, y_logo), logo_ab)
        y_textos = y_logo + lh + 14
    else:
        y_textos = 28

    nome_torneio = (meta.get("pelada") or meta.get("torneio") or "COPA FUT-BIN").upper()
    centralizado(d, y_textos, nome_torneio, fonte(38), DOURADO)
    sub = " · ".join(x for x in [meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")] if x)
    if sub:
        centralizado(d, y_textos + 46, sub, fonte(20, False), FRACO)

    # 2. CONFRONTO INICIAL (Estilo TV pré-jogo)
    y_vs = y_textos + 80
    w_pill = 380
    h_pill = 54
    # Time A pill
    x_pill_a = L // 2 - w_pill - 50
    d.rounded_rectangle([x_pill_a, y_vs, x_pill_a + w_pill, y_vs + h_pill], radius=10,
                        fill=ca, outline=(255, 255, 255), width=2)
    d.text((x_pill_a + w_pill // 2, y_vs + h_pill // 2), times[0]["nome"].upper(),
           font=fonte(26, True), fill=contraste_cor(ca), anchor="mm")

    # VS badge
    d.ellipse([L // 2 - 28, y_vs + h_pill // 2 - 28, L // 2 + 28, y_vs + h_pill // 2 + 28],
              fill=(16, 22, 34), outline=DOURADO, width=2)
    d.text((L // 2, y_vs + h_pill // 2), "VS", font=fonte(22, True), fill=DOURADO, anchor="mm")

    # Time B pill
    x_pill_b = L // 2 + 50
    d.rounded_rectangle([x_pill_b, y_vs, x_pill_b + w_pill, y_vs + h_pill], radius=10,
                        fill=cb, outline=(255, 255, 255), width=2)
    d.text((x_pill_b + w_pill // 2, y_vs + h_pill // 2), times[1]["nome"].upper(),
           font=fonte(26, True), fill=contraste_cor(cb), anchor="mm")

    # Tag de Escalação
    centralizado(d, y_vs + h_pill + 14, "ESCALAÇÃO & DISPOSIÇÃO TÁTICA", fonte(16, True), (180, 200, 225))

    # 3. CAMPO TÁTICO
    j_a = completar_escalacao(normalizar_jogadores(times[0]))
    j_b = completar_escalacao(normalizar_jogadores(times[1]))

    campo_w = 1240
    campo_h = 710
    campo_x0 = (L - campo_w) // 2
    campo_y0 = y_vs + h_pill + 40
    desenhar_campo_tatico(d, campo_x0, campo_y0, campo_w, campo_h, j_a, j_b, ca, cb, img_base=img, times=times)

    # 4. PAINÉIS LATERAIS DE ELENCO
    def desenhar_painel_elenco(x0, time_obj, jgs, cor):
        w_p = 275
        d.rounded_rectangle([x0, campo_y0, x0 + w_p, campo_y0 + campo_h], radius=10,
                            fill=PAINEL, outline=PAINEL_BORDA, width=1)
        d.rectangle([x0, campo_y0, x0 + w_p, campo_y0 + 6], fill=cor)
        d.text((x0 + 16, campo_y0 + 16), time_obj["nome"], font=fonte(22), fill=cor)
        d.text((x0 + 16, campo_y0 + 44), "ELENCO OFICIAL", font=fonte(13), fill=FRACO)

        y_item = campo_y0 + 72
        tags = {"goleiro": "GOL", "zagueiro": "ZAG", "meio": "MEI", "atacante": "ATA"}
        for nm, pos in jgs[:12]:
            tag = tags.get(pos, "MEI")
            # Avatar ou foto do jogador (30x30)
            av = obter_avatar_jogador(nm, time_obj, tamanho=(30, 30), cor_time=cor, pos=pos)
            if av:
                img.paste(av, (x0 + 14, y_item - 2), av)
                d.text((x0 + 52, y_item + 3), nm, font=fonte(18, False), fill=TEXTO)
            else:
                d.text((x0 + 16, y_item + 3), nm, font=fonte(18, False), fill=TEXTO)

            # Badge de posição estilizado
            d.rounded_rectangle([x0 + w_p - 58, y_item + 2, x0 + w_p - 14, y_item + 24], radius=4,
                                fill=(24, 32, 48), outline=(60, 75, 100), width=1)
            d.text((x0 + w_p - 36, y_item + 13), tag, font=fonte(11, True), fill=FRACO, anchor="mm")
            y_item += 40

    desenhar_painel_elenco(35, times[0], j_a, ca)
    desenhar_painel_elenco(L - 310, times[1], j_b, cb)

    return img


# --------------------------------------------------------------- PLACAR ELETRÔNICO E LANCE

def cartela_lance(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """
    Faixa inferior de lance/gol + Placar Eletrônico estilo SporTV no canto superior esquerdo.
    Atualiza dinamicamente conforme os gols são marcados!
    """
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 1. MARCA D'ÁGUA OFICIAL DA TRANSMISSÃO NO CANTO SUPERIOR DIREITO
    desenhar_tv_watermark(img, d_, tamanho=(80, 80))

    # 2. PLACAR ELETRÔNICO ESTILO SPORTV / PREMIERE NO CANTO SUPERIOR ESQUERDO
    pb_x0 = 60
    pb_y0 = 42
    pb_h = 56

    nome_a = times[0]["nome"].upper()
    nome_b = times[1]["nome"].upper()
    ca = hex_rgb(times[0]["cor"])
    cb = hex_rgb(times[1]["cor"])
    txt_ca = contraste_cor(ca)
    txt_cb = contraste_cor(cb)

    f_score = fonte(32, True)
    f_team = fonte(20, True)
    f_timer = fonte(22, True)

    bb_ta = d.textbbox((0, 0), nome_a, font=f_team)
    bb_tb = d.textbbox((0, 0), nome_b, font=f_team)
    w_ta = max(bb_ta[2] - bb_ta[0] + 32, 110)
    w_tb = max(bb_tb[2] - bb_tb[0] + 32, 110)
    w_score = 120
    w_timer = 110

    # Sombra do placar
    total_w = w_ta + w_score + w_tb + w_timer + 6
    d.rounded_rectangle([pb_x0 + 3, pb_y0 + 3, pb_x0 + total_w + 3, pb_y0 + pb_h + 4],
                        radius=8, fill=(0, 0, 0, 150))

    # Time A
    xa0 = pb_x0
    xa1 = xa0 + w_ta
    d.rounded_rectangle([xa0, pb_y0, xa1, pb_y0 + pb_h], radius=8, fill=ca + (250,))
    d.rectangle([xa1 - 8, pb_y0, xa1, pb_y0 + pb_h], fill=ca + (250,))
    d.text(((xa0 + xa1) // 2, pb_y0 + pb_h // 2), nome_a, font=f_team, fill=txt_ca + (255,), anchor="mm")

    # Placar central
    xc0 = xa1
    xc1 = xc0 + w_score
    d.rectangle([xc0, pb_y0, xc1, pb_y0 + pb_h], fill=(12, 16, 26, 250))
    d.text((xc0 + 32, pb_y0 + pb_h // 2), str(placar_a), font=f_score, fill=(255, 255, 255, 255), anchor="mm")
    d.text((xc0 + w_score // 2, pb_y0 + pb_h // 2 - 2), "×", font=fonte(24), fill=(160, 175, 195, 255), anchor="mm")
    d.text((xc1 - 32, pb_y0 + pb_h // 2), str(placar_b), font=f_score, fill=(255, 255, 255, 255), anchor="mm")

    # Time B
    xb0 = xc1
    xb1 = xb0 + w_tb
    d.rounded_rectangle([xb0, pb_y0, xb1, pb_y0 + pb_h], radius=8, fill=cb + (250,))
    d.rectangle([xb0, pb_y0, xb0 + 8, pb_y0 + pb_h], fill=cb + (250,))
    d.text(((xb0 + xb1) // 2, pb_y0 + pb_h // 2), nome_b, font=f_team, fill=txt_cb + (255,), anchor="mm")

    # Cronômetro / Tempo de jogo
    xt0 = xb1 + 6
    xt1 = xt0 + w_timer
    tempo_str = str(ev.get("tempo") or "00:00")
    d.rounded_rectangle([xt0, pb_y0, xt1, pb_y0 + pb_h], radius=8,
                        fill=(20, 26, 40, 250), outline=(55, 68, 92, 255), width=2)
    # Ponto indicador no cronômetro
    d.ellipse([xt0 + 12, pb_y0 + pb_h // 2 - 4, xt0 + 20, pb_y0 + pb_h // 2 + 4], fill=VERDE + (255,))
    d.text((xt0 + (w_timer + 16) // 2, pb_y0 + pb_h // 2), tempo_str, font=f_timer, fill=(255, 255, 255, 255), anchor="mm")

    # Destaque dinâmico de GOL!
    if gol_neste_clipe and time_gol in (0, 1):
        xg = xa0 if time_gol == 0 else xb0
        wg = w_ta if time_gol == 0 else w_tb
        yg0 = pb_y0 + pb_h + 6
        d.rounded_rectangle([xg, yg0, xg + wg, yg0 + 34], radius=8,
                            fill=AMARELO_GOL + (255,), outline=(255, 255, 255, 255), width=2)
        d.text((xg + wg // 2, yg0 + 17), "GOL!", font=fonte(20, True), fill=(10, 15, 20, 255), anchor="mm")

    # 3. FAIXA INFERIOR COMPACTA (LOWER-THIRD ELEGANTE, NÃO POLUI A TELA)
    card_x0 = 60
    card_y0 = A - 150
    card_h = 92

    if tipo == "gol":
        t_idx = ev.get("time", 0)
        cor_lance = hex_rgb(times[t_idx]["cor"])
        time_nome = times[t_idx]["nome"]
        rotulo_pill = f"GOL · {time_nome.upper()}"
        jogador_principal = ev.get("autor", "Gol")
    else:
        tem_time = ev.get("time") is not None and isinstance(ev["time"], int) and 0 <= ev["time"] < len(times)
        cor_lance = hex_rgb(times[ev["time"]]["cor"]) if tem_time else VERDE
        time_nome = times[ev["time"]]["nome"] if tem_time else ""
        nome_lance = (ev.get("lance") or "MELHOR MOMENTO").upper()
        rotulo_pill = nome_lance
        jogador_principal = ev.get("destaque") or ev.get("autor") or ev.get("lance") or "Lance"

    assist_nome = ev.get("assist") if tipo == "gol" else None

    # Tipografia refinada e proporcional (não polui a tela)
    f_nome = fonte(28, True)
    f_pill = fonte(11, True)
    f_ass = fonte(14, False)

    bb_nm = d.textbbox((0, 0), jogador_principal, font=f_nome)
    w_nome = bb_nm[2] - bb_nm[0]

    w_ass = 0
    if assist_nome:
        bb_ass = d.textbbox((0, 0), f"assistência: {assist_nome}", font=f_ass)
        w_ass = bb_ass[2] - bb_ass[0] + 30

    bb_pill = d.textbbox((0, 0), rotulo_pill, font=f_pill)
    pw = bb_pill[2] - bb_pill[0] + 16

    # Largura dinâmica compacta (ocupa apenas o espaço necessário)
    card_w = max(420, max(w_nome, w_ass, pw) + 150)
    card_w = min(card_w, 640)

    # Sombra suave
    d.rounded_rectangle([card_x0 + 3, card_y0 + 4, card_x0 + card_w + 3, card_y0 + card_h + 4],
                        radius=12, fill=(0, 0, 0, 130))

    # Fundo translúcido com borda no tom do lance
    d.rounded_rectangle([card_x0, card_y0, card_x0 + card_w, card_y0 + card_h], radius=12,
                        fill=(12, 16, 26, 235), outline=cor_lance + (170,), width=2)

    # Filete lateral com a cor do time
    d.rounded_rectangle([card_x0 + 10, card_y0 + 12, card_x0 + 15, card_y0 + card_h - 12],
                        radius=3, fill=cor_lance + (255,))

    # Foto / Avatar compacto (68x68)
    av_tam = 68
    av_x = card_x0 + 26
    av_y = card_y0 + (card_h - av_tam) // 2

    time_obj_alvo = times[ev["time"]] if (ev.get("time") is not None and 0 <= ev["time"] < len(times)) else times[0]
    avatar_jog = obter_avatar_jogador(jogador_principal, time_obj_alvo, tamanho=(av_tam, av_tam), cor_time=cor_lance)
    if avatar_jog:
        img.paste(avatar_jog, (av_x, av_y), avatar_jog)

    x_txt = av_x + av_tam + 16

    # Pill identificadora compacta
    ph = 20
    py = card_y0 + 12
    d.rounded_rectangle([x_txt, py, x_txt + pw, py + ph], radius=4, fill=cor_lance + (255,))
    d.text((x_txt + pw // 2, py + ph // 2), rotulo_pill, font=f_pill,
           fill=contraste_cor(cor_lance) + (255,), anchor="mm")

    # Nome do autor (28px - limpo, legível e proporcional)
    d.text((x_txt, card_y0 + 36), jogador_principal, font=f_nome, fill=(255, 255, 255, 255))

    # Assistência compacta
    if assist_nome:
        y_ass = card_y0 + 68
        d.text((x_txt, y_ass), "assistência: ", font=f_ass, fill=FRACO + (255,))
        bb_lbl = d.textbbox((0, 0), "assistência: ", font=f_ass)
        w_lbl = bb_lbl[2] - bb_lbl[0]
        foto_ass = obter_avatar_jogador(assist_nome, time_obj_alvo, tamanho=(18, 18), cor_time=cor_lance)
        if foto_ass:
            img.paste(foto_ass, (x_txt + w_lbl, y_ass), foto_ass)
            d.text((x_txt + w_lbl + 24, y_ass), assist_nome, font=fonte(14, True), fill=(240, 244, 250, 255))
        else:
            d.text((x_txt + w_lbl, y_ass), assist_nome, font=fonte(14, True), fill=(240, 244, 250, 255))
    elif tipo != "gol" and ev.get("destaque"):
        y_det = card_y0 + 68
        d.text((x_txt, y_det), ev["destaque"], font=f_ass, fill=FRACO + (255,))

    return img


# --------------------------------------------------------------- CARTELAS FINAIS

FIM_DE_JOGO_GOLS_POR_TELA = 15


def paginas_fim_de_jogo(d_):
    n_a = sum(1 for g in d_.get("gols", []) if g.get("time") == 0)
    n_b = sum(1 for g in d_.get("gols", []) if g.get("time") == 1)
    return max(1, -(-n_a // FIM_DE_JOGO_GOLS_POR_TELA), -(-n_b // FIM_DE_JOGO_GOLS_POR_TELA))


def cartela_fim_de_jogo(d_, pagina=0):
    """
    Placar final profissional estilo transmissão esportiva pós-jogo (SporTV / Premiere).
    Mostra o placar oficial e a lista de todos os gols de cada time.
    """
    img = criar_fundo_base(d_)
    d = ImageDraw.Draw(img)
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])

    d.rectangle([0, 0, L, 6], fill=VERDE)

    # Logo do campeonato centralizada no topo
    logo_fim = obter_logo_campeonato(d_, tamanho=(105, 105))
    y_logo = 16
    if logo_fim:
        lw, lh = logo_fim.size
        lx = (L - lw) // 2
        d.ellipse([lx - 8, y_logo - 6, lx + lw + 8, y_logo + lh + 6],
                  fill=(16, 24, 38), outline=DOURADO, width=2)
        if logo_fim.mode != "RGBA":
            logo_fim = logo_fim.convert("RGBA")
        img.paste(logo_fim, (lx, y_logo), logo_fim)
        y_textos = y_logo + lh + 14
    else:
        y_textos = 28

    total_pag = paginas_fim_de_jogo(d_)
    titulo_fim = "FIM DE JOGO · PLACAR FINAL"
    if total_pag > 1:
        titulo_fim += f" ({pagina + 1}/{total_pag})"
    centralizado(d, y_textos, titulo_fim, fonte(38), DOURADO)
    sub = " · ".join(x for x in [meta.get("pelada") or meta.get("torneio"), meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")] if x)
    if sub:
        # Dados da partida precisam permanecer legíveis mesmo no fundo da quadra.
        centralizado_contornado(d, y_textos + 46, sub, fonte(27, True),
                               BRANCO, (0, 0, 0), 3)

    gols_ordenados = sorted(d_.get("gols", []), key=_tempo_em_segundos)
    gols_a = [g for g in gols_ordenados if g.get("time") == 0]
    gols_b = [g for g in gols_ordenados if g.get("time") == 1]
    n_por = FIM_DE_JOGO_GOLS_POR_TELA
    gols_a_pag = gols_a[pagina * n_por:(pagina + 1) * n_por]
    gols_b_pag = gols_b[pagina * n_por:(pagina + 1) * n_por]
    total_a = len(gols_a)
    total_b = len(gols_b)
    if meta.get("placar_jogo"):
        if meta["placar_jogo"][0] is not None:
            total_a = meta["placar_jogo"][0]
        if meta["placar_jogo"][1] is not None:
            total_b = meta["placar_jogo"][1]

    # Placar Central Estilo Estádio
    y_p = y_textos + 80
    pw = 960
    px0 = (L - pw) // 2
    d.rounded_rectangle([px0, y_p, px0 + pw, y_p + 130], radius=16, fill=PAINEL, outline=PAINEL_BORDA, width=2)
    d.rectangle([px0 + 20, y_p + 124, px0 + pw // 2 - 10, y_p + 128], fill=ca)
    d.rectangle([px0 + pw // 2 + 10, y_p + 124, px0 + pw - 20, y_p + 128], fill=cb)

    d.text((px0 + 40, y_p + 65), times[0]["nome"], font=fonte(38), fill=ca, anchor="lm")
    d.text((px0 + pw - 40, y_p + 65), times[1]["nome"], font=fonte(38), fill=cb, anchor="rm")

    f_big = fonte(88, True)
    d.text((L // 2 - 75, y_p + 60), str(total_a), font=f_big, fill=(255, 255, 255), anchor="mm")
    d.text((L // 2, y_p + 60), "×", font=fonte(48), fill=FRACO, anchor="mm")
    d.text((L // 2 + 75, y_p + 60), str(total_b), font=f_big, fill=(255, 255, 255), anchor="mm")

    # Colunas com Lista de Gols (incluindo avatar/foto do autor!)
    col_w = 700
    topo_col = y_p + 155

    def desenhar_coluna_gols(x0, time_obj, lista_gols, cor):
        # Usa toda a parte inferior da tela: assim uma partida com muitos gols
        # continua mostrando a lista completa, sem cortar os últimos nomes.
        fim_col = A - 48
        altura_col = fim_col - topo_col
        espaco_itens = max(1, altura_col - 76)
        passo_item = max(27, min(38, espaco_itens // max(len(lista_gols), 1)))
        total_time = len(gols_a) if time_obj is times[0] else len(gols_b)
        tam_autor = max(17, min(19, passo_item - 12))
        tam_assist = max(12, min(14, passo_item - 17))
        tam_tempo = max(11, min(13, passo_item - 18))
        tam_avatar = max(20, min(26, passo_item - 8))

        d.rounded_rectangle([x0, topo_col, x0 + col_w, fim_col], radius=12,
                            fill=PAINEL, outline=PAINEL_BORDA, width=1)
        d.rectangle([x0, topo_col, x0 + col_w, topo_col + 6], fill=cor)
        d.text((x0 + 24, topo_col + 22), f"GOLS · {time_obj['nome'].upper()}", font=fonte(22), fill=cor)
        d.text((x0 + col_w - 24, topo_col + 24), f"{total_time} gol(s)", font=fonte(16, False), fill=FRACO, anchor="ra")

        y_item = topo_col + 64
        if not lista_gols:
            d.text((x0 + 24, y_item + 10), "Nenhum gol marcado", font=fonte(18, False), fill=FRACO)
            return

        for g in lista_gols:
            if y_item + passo_item > fim_col - 8:
                break
            t_str = g.get("tempo", "")
            # Badge com tempo
            badge_h = min(26, passo_item - 3)
            d.rounded_rectangle([x0 + 20, y_item - 2, x0 + 82, y_item - 2 + badge_h], radius=4,
                                fill=(24, 32, 48), outline=(60, 75, 100), width=1)
            d.text((x0 + 51, y_item - 2 + badge_h // 2), t_str, font=fonte(tam_tempo, True), fill=TEXTO, anchor="mm")

            autor = g.get("autor", "Gol")
            av = obter_avatar_jogador(autor, time_obj, tamanho=(tam_avatar, tam_avatar), cor_time=cor)
            if av:
                img.paste(av, (x0 + 96, y_item - 2), av)
                d.text((x0 + 96 + tam_avatar + 10, y_item), autor, font=fonte(tam_autor, True), fill=TEXTO)
            else:
                d.text((x0 + 96, y_item), autor, font=fonte(tam_autor, True), fill=TEXTO)

            if g.get("assist"):
                d.text((x0 + col_w - 24, y_item + 2), f"assist. {g['assist']}", font=fonte(tam_assist, False), fill=FRACO, anchor="ra")
            y_item += passo_item

    desenhar_coluna_gols(170, times[0], gols_a_pag, ca)
    desenhar_coluna_gols(L // 2 + 60, times[1], gols_b_pag, cb)

    return img


CRONOLOGIA_POR_TELA = 20


def paginas_cronologia(d_):
    n = len(d_.get("gols", []))
    return max(1, -(-n // CRONOLOGIA_POR_TELA))


def cartela_cronologia(d_, pagina=0):
    img = criar_fundo_base(d_)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 6], fill=VERDE)

    logo_cr = obter_logo_campeonato(d_, tamanho=(105, 105))
    y_logo = 16
    if logo_cr:
        lw, lh = logo_cr.size
        lx = (L - lw) // 2
        d.ellipse([lx - 8, y_logo - 6, lx + lw + 8, y_logo + lh + 6],
                  fill=(16, 24, 38), outline=DOURADO, width=2)
        if logo_cr.mode != "RGBA":
            logo_cr = logo_cr.convert("RGBA")
        img.paste(logo_cr, (lx, y_logo), logo_cr)
        y_textos = y_logo + lh + 14
    else:
        y_textos = 28

    total_pag = paginas_cronologia(d_)
    titulo = "COMO FOI O JOGO · CRONOLOGIA COMPLETA"
    if total_pag > 1:
        titulo += f" ({pagina + 1}/{total_pag})"
    centralizado(d, y_textos, titulo, fonte(38), DOURADO)

    gols_ordenados = sorted(d_.get("gols", []), key=_tempo_em_segundos)
    ini = pagina * CRONOLOGIA_POR_TELA
    gols_ordenados = gols_ordenados[ini:ini + CRONOLOGIA_POR_TELA]

    card_w = 1400
    card_x0 = (L - card_w) // 2
    card_y0 = y_textos + 65
    card_h = A - card_y0 - 25
    passo = (card_h - 30) // CRONOLOGIA_POR_TELA
    d.rounded_rectangle([card_x0, card_y0, card_x0 + card_w, card_y0 + card_h], radius=14,
                        fill=PAINEL, outline=PAINEL_BORDA, width=1)

    y = card_y0 + 25
    for g in gols_ordenados:
        t_idx = g.get("time", 0)
        t_obj = d_["times"][t_idx] if 0 <= t_idx < len(d_["times"]) else d_["times"][0]
        cor = hex_rgb(t_obj["cor"])

        # Linha colorida do time
        d.rounded_rectangle([card_x0 + 30, y + 4, card_x0 + 36, y + 36], radius=3, fill=cor)

        # Tempo
        d.rounded_rectangle([card_x0 + 50, y + 2, card_x0 + 125, y + 36], radius=6,
                            fill=(24, 32, 48), outline=(55, 70, 95), width=1)
        d.text((card_x0 + 87, y + 19), g.get("tempo", ""), font=fonte(16, True), fill=TEXTO, anchor="mm")

        # Foto / Avatar do autor
        autor = g.get("autor", "Gol")
        av = obter_avatar_jogador(autor, t_obj, tamanho=(34, 34), cor_time=cor)
        if av:
            img.paste(av, (card_x0 + 145, y + 2), av)
            d.text((card_x0 + 190, y + 7), autor, font=fonte(24, True), fill=TEXTO)
        else:
            d.text((card_x0 + 145, y + 7), autor, font=fonte(24, True), fill=TEXTO)

        if g.get("assist"):
            d.text((card_x0 + 540, y + 10), f"assistência: {g['assist']}", font=fonte(20, False), fill=FRACO)

        # Pill do time
        t_nome = t_obj["nome"]
        f_tag = fonte(15, True)
        bb = d.textbbox((0, 0), t_nome, font=f_tag)
        tw = bb[2] - bb[0] + 20
        tx = card_x0 + card_w - tw - 30
        d.rounded_rectangle([tx, y + 4, tx + tw, y + 34], radius=6, fill=cor)
        d.text((tx + tw // 2, y + 19), t_nome, font=f_tag, fill=contraste_cor(cor), anchor="mm")

        y += passo

    return img


def cartela_destaques(d_):
    img = criar_fundo_base(d_)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 6], fill=VERDE)

    logo_des = obter_logo_campeonato(d_, tamanho=(105, 105))
    y_logo = 16
    if logo_des:
        lw, lh = logo_des.size
        lx = (L - lw) // 2
        d.ellipse([lx - 8, y_logo - 6, lx + lw + 8, y_logo + lh + 6],
                  fill=(16, 24, 38), outline=DOURADO, width=2)
        if logo_des.mode != "RGBA":
            logo_des = logo_des.convert("RGBA")
        img.paste(logo_des, (lx, y_logo), logo_des)
        y_textos = y_logo + lh + 14
    else:
        y_textos = 28

    centralizado(d, y_textos, "DESTAQUES DA PARTIDA", fonte(40), DOURADO)

    medalha = [(255, 215, 0), (200, 210, 225), (205, 140, 90)]
    topo_cards = y_textos + 75
    h_card = 630
    w_card = 680

    for col, (titulo, chave, campo) in enumerate([
        ("ARTILHEIROS", "artilheiros", "gols"),
        ("LÍDERES EM ASSISTÊNCIAS", "garcons", "assistencias")
    ]):
        x0 = 170 if col == 0 else L // 2 + 60
        d.rounded_rectangle([x0, topo_cards, x0 + w_card, topo_cards + h_card], radius=14,
                            fill=PAINEL, outline=PAINEL_BORDA, width=1)
        # Header do card
        d.rounded_rectangle([x0, topo_cards, x0 + w_card, topo_cards + 56], radius=14, fill=(24, 34, 52))
        d.rectangle([x0, topo_cards + 50, x0 + w_card, topo_cards + 56], fill=(24, 34, 52))
        d.text((x0 + 24, topo_cards + 18), titulo, font=fonte(22, True), fill=DOURADO)

        itens = (d_.get(chave) or [])[:5]
        for k, item in enumerate(itens):
            y = topo_cards + 84 + k * 102
            cor_med = medalha[k] if k < 3 else (70, 85, 110)

            # Medalha / Posição
            d.ellipse([x0 + 24, y + 4, x0 + 72, y + 52], fill=cor_med)
            d.text((x0 + 48, y + 28), str(k + 1), font=fonte(24, True), fill=(10, 14, 22), anchor="mm")

            # Foto / Avatar do jogador (52x52px)
            av = obter_avatar_jogador(item["jogador"], d_.get("times"), tamanho=(52, 52), cor_time=cor_med)
            if av:
                img.paste(av, (x0 + 90, y + 2), av)
                d.text((x0 + 158, y + 14), item["jogador"], font=fonte(32, True), fill=TEXTO)
            else:
                d.text((x0 + 90, y + 14), item["jogador"], font=fonte(32, True), fill=TEXTO)

            # Contagem com badge
            qtd_str = str(item[campo])
            d.rounded_rectangle([x0 + w_card - 100, y + 8, x0 + w_card - 24, y + 48], radius=8,
                                fill=(24, 36, 56), outline=cor_med, width=2)
            d.text((x0 + w_card - 62, y + 28), qtd_str, font=fonte(26, True), fill=cor_med, anchor="mm")

    centralizado(d, topo_cards + h_card + 35, d_["meta"].get("pelada") or d_["meta"].get("torneio") or "", fonte(26), VERDE)
    return img


def cartela_assista_outros_videos(d_):
    """Tela final limpa, com espaço livre para os quadros recomendados do YouTube."""
    img = criar_fundo_base(d_)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 7], fill=VERDE)
    # Área central propositalmente vazia: o YouTube coloca os vídeos sugeridos aqui.
    d.rounded_rectangle([150, 100, L - 150, A - 70], radius=28,
                        fill=(10, 17, 29, 235), outline=(0, 255, 135, 210), width=3)
    centralizado(d, 155, "ASSISTA ESTES OUTROS VÍDEOS", fonte(52, True), BRANCO)
    centralizado(d, A - 125, "Obrigado por assistir", fonte(25, False), FRACO)
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
    referencia = None
    duracao_total = 0.0
    for parte in partes:
        dados = dados_midia(parte)
        assinatura = [tuple(s.get(k) for k in (
            "codec_type", "codec_name", "time_base", "width", "height",
            "pix_fmt", "sample_aspect_ratio", "sample_rate", "channels", "channel_layout"
        )) for s in dados["streams"]]
        if referencia is not None and assinatura != referencia:
            raise RuntimeError(f"Segmento incompativel para montagem em 1x: {parte}")
        referencia = assinatura
        duracao_total += float(dados["format"]["duration"])
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
    args = ap.parse_args()
    global ALTURA_SAIDA, VERTICAL, RECORTE
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
            print("  gerando cartela de abertura (campo tático e escalação)...")
            p = os.path.join(tmp, "abertura.png")
            cartela_abertura(d).save(p)
            s = os.path.join(tmp, "s000.mp4")
            seg_de_imagem(p, args.abertura, s, crf=args.crf, preset=args.preset, codec=args.codec)
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
                seg_de_clipe(clipe, png, s, args.sem_audio, ajuste_cor=ajuste_cor,
                              zoom=ev.get("zoom", 1.0), zoom_x=ev.get("zoom_x", 0.5), zoom_y=ev.get("zoom_y", 0.5),
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
