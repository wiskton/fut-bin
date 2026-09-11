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
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from PIL import Image, ImageDraw, ImageFont

L, A = 1920, 1080
FPS = 30
FUNDO = (11, 15, 23)
PAINEL = (18, 24, 38)
PAINEL_BORDA = (45, 55, 75)
TEXTO = (240, 244, 248)
FRACO = (145, 158, 175)
VERDE = (34, 197, 94)
BRANCO = (255, 255, 255)
AMARELO_GOL = (250, 204, 21)

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


def obter_foto_jogador(nome, time_obj=None, tamanho=(50, 50)):
    """
    Carrega e formata a foto do jogador com recorte circular transparente (PNG).
    Procura em time_obj['fotos'][nome], ou em web/fotos/{slug}.png, ou fotos/{slug}.png.
    """
    if not nome or not str(nome).strip():
        return None
    nome_str = str(nome).strip()
    candidatos = []
    if time_obj and isinstance(time_obj, dict):
        fotos_map = time_obj.get("fotos", {})
        if isinstance(fotos_map, dict) and fotos_map.get(nome_str):
            p = fotos_map[nome_str]
            if p.startswith("/web/"):
                candidatos.append(os.path.join(SCRIPT_DIR, p.lstrip("/")))
            elif p.startswith("/"):
                candidatos.append(p)
            else:
                candidatos.append(os.path.join(SCRIPT_DIR, p))
                candidatos.append(p)

    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', nome_str.lower())
    candidatos.extend([
        os.path.join(SCRIPT_DIR, "web", "fotos", f"{slug}.png"),
        os.path.join(SCRIPT_DIR, "web", "fotos", f"{slug}.jpg"),
        os.path.join(SCRIPT_DIR, "web", "fotos", f"{slug}.jpeg"),
        os.path.join(SCRIPT_DIR, "fotos", f"{slug}.png"),
        os.path.join(SCRIPT_DIR, "fotos", f"{slug}.jpg"),
    ])

    for c in candidatos:
        if c and os.path.isfile(c):
            try:
                im = Image.open(c).convert("RGBA")
                if tamanho:
                    w, h = tamanho
                    im = im.resize((w, h), Image.Resampling.LANCZOS)
                    # Cria mascara circular com anti-aliasing
                    mask = Image.new("L", (w, h), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, w - 1, h - 1), fill=255)
                    circular = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    circular.paste(im, (0, 0), mask)
                    return circular
                return im
            except Exception:
                continue
    return None


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


def normalizar_jogadores(time_obj):
    raw = time_obj.get("jogadores", [])
    pos_map = time_obj.get("posicoes", {})
    resultado = []
    for j in raw:
        if isinstance(j, dict):
            nome = j.get("nome", "").strip()
            pos = j.get("posicao") or pos_map.get(nome, "meio")
        else:
            nome = str(j).strip()
            pos = pos_map.get(nome, "meio")
        if nome:
            resultado.append((nome, pos.lower()))
    return resultado


def preencher_padrao_se_necessario(j_list):
    if not any(pos != "meio" for _, pos in j_list) and len(j_list) >= 4:
        novos = []
        for i, (nm, _) in enumerate(j_list):
            if i == 0:
                novos.append((nm, "goleiro"))
            elif i in (1, 2):
                novos.append((nm, "zagueiro"))
            elif i in (3, 4):
                novos.append((nm, "meio"))
            else:
                novos.append((nm, "atacante"))
        return novos
    return j_list


# --------------------------------------------------------------- campo tático e abertura

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
            pos_norm = pos.lower()
            if "gol" in pos_norm:
                grupos["goleiro"].append(nome)
            elif "zag" in pos_norm or "def" in pos_norm:
                grupos["zagueiro"].append(nome)
            elif "ata" in pos_norm or "pon" in pos_norm or "cen" in pos_norm:
                grupos["atacante"].append(nome)
            else:
                grupos["meio"].append(nome)

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
        for cat, jgs in grupos.items():
            cx = col_x[cat]
            qtd = len(jgs)
            if qtd == 0:
                continue
            step = area_util_y / (qtd + 1)
            for idx, nome in enumerate(jgs, 1):
                cy = y0 + margem_y + int(idx * step)
                coords.append((nome, cat, cx, cy))
        return coords

    coords_a = posicionar_jogadores(time_a, True)
    coords_b = posicionar_jogadores(time_b, False)

    grupos_times = [
        (coords_a, ca, contraste_cor(ca), times[0] if times else None),
        (coords_b, cb, contraste_cor(cb), times[1] if times and len(times) > 1 else None)
    ]

    for coords, cor, txt_cor, time_obj in grupos_times:
        for nome, cat, cx, cy in coords:
            r = 18
            draw.ellipse([cx - r - 2, cy - r + 2, cx + r + 2, cy + r + 4], fill=(10, 15, 20, 140))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=cor, outline=(255, 255, 255), width=2)

            foto_j = obter_foto_jogador(nome, time_obj, tamanho=(r * 2 - 4, r * 2 - 4))
            if foto_j and img_base:
                img_base.paste(foto_j, (cx - r + 2, cy - r + 2), foto_j)
            else:
                sigla = {"goleiro": "GOL", "zagueiro": "ZAG", "meio": "MEI", "atacante": "ATA"}.get(cat, "JOG")
                f_sig = fonte(12, True)
                bb_sig = draw.textbbox((0, 0), sigla, font=f_sig)
                sw = bb_sig[2] - bb_sig[0]
                sh = bb_sig[3] - bb_sig[1]
                draw.text((cx - sw // 2, cy - sh // 2 - 1), sigla, font=f_sig, fill=txt_cor)

            f_nome = fonte(15, True)
            bb = draw.textbbox((0, 0), nome, font=f_nome)
            nw = bb[2] - bb[0]
            nh = bb[3] - bb[1]
            nx0 = cx - nw // 2 - 7
            ny0 = cy + r + 4
            draw.rounded_rectangle([nx0, ny0, nx0 + nw + 14, ny0 + nh + 6], radius=4,
                                   fill=(15, 20, 30, 220), outline=(60, 75, 95), width=1)
            draw.text((cx - nw // 2, ny0 + 2), nome, font=f_nome, fill=(255, 255, 255))


def cartela_abertura(d_):
    img = Image.new("RGB", (L, A), FUNDO)
    d = ImageDraw.Draw(img)
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])

    d.rectangle([0, 0, L, 8], fill=VERDE)

    # Logo do campeonato na abertura
    logo_ab = obter_logo_campeonato(d_, tamanho=(130, 130))
    if logo_ab:
        img.paste(logo_ab, (60, 25), logo_ab)
        img.paste(logo_ab, (L - 60 - logo_ab.width, 25), logo_ab)

    nome_torneio = (meta.get("pelada") or meta.get("torneio") or "COPA FUT-BIN").upper()
    centralizado(d, 40, nome_torneio, fonte(42), VERDE)
    sub = " · ".join(x for x in [meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")] if x)
    if sub:
        centralizado(d, 95, sub, fonte(24, False), FRACO)

    # Confronto inicial SEM PLACAR (igual transmissão ao vivo antes do jogo)
    y_vs = 145
    d.text((L // 2 - 100, y_vs), times[0]["nome"], font=fonte(42), fill=ca, anchor="ra")
    d.text((L // 2, y_vs + 5), "VS", font=fonte(32), fill=FRACO, anchor="ma")
    d.text((L // 2 + 100, y_vs), times[1]["nome"], font=fonte(42), fill=cb, anchor="la")

    centralizado(d, 205, "ESCALAÇÃO & DISPOSIÇÃO TÁTICA", fonte(20, True), (180, 195, 215))

    j_a = preencher_padrao_se_necessario(normalizar_jogadores(times[0]))
    j_b = preencher_padrao_se_necessario(normalizar_jogadores(times[1]))

    campo_w = 1260
    campo_h = 750
    campo_x0 = (L - campo_w) // 2
    campo_y0 = 245
    desenhar_campo_tatico(d, campo_x0, campo_y0, campo_w, campo_h, j_a, j_b, ca, cb, img_base=img, times=times)

    # Painéis laterais com elenco e posições
    def desenhar_painel_elenco(x0, time_obj, jgs, cor):
        w_p = 270
        d.rounded_rectangle([x0, campo_y0, x0 + w_p, campo_y0 + campo_h], radius=8,
                               fill=PAINEL, outline=PAINEL_BORDA, width=1)
        d.rectangle([x0, campo_y0, x0 + w_p, campo_y0 + 6], fill=cor)
        d.text((x0 + 16, campo_y0 + 20), time_obj["nome"], font=fonte(22), fill=cor)
        d.text((x0 + 16, campo_y0 + 48), "ELENCO", font=fonte(14), fill=FRACO)

        y_item = campo_y0 + 78
        tags = {"goleiro": "GOL", "zagueiro": "ZAG", "meio": "MEI", "atacante": "ATA"}
        for nm, pos in jgs[:12]:
            tag = tags.get(pos, "MEI")
            foto_j = obter_foto_jogador(nm, time_obj, tamanho=(26, 26))
            if foto_j:
                img.paste(foto_j, (x0 + 14, y_item - 3), foto_j)
                d.text((x0 + 46, y_item), nm, font=fonte(18, False), fill=TEXTO)
            else:
                d.text((x0 + 16, y_item), nm, font=fonte(18, False), fill=TEXTO)
            d.text((x0 + w_p - 16, y_item + 2), f"[{tag}]", font=fonte(13, True), fill=FRACO, anchor="ra")
            y_item += 38

    desenhar_painel_elenco(35, times[0], j_a, ca)
    desenhar_painel_elenco(L - 305, times[1], j_b, cb)

    return img


# --------------------------------------------------------------- placar eletrônico & lance

def cartela_lance(ev, times, tipo, placar_a, placar_b, gol_neste_clipe=False, time_gol=None, d_=None):
    """
    Faixa inferior de lance/gol + Placar Eletrônico estilo SporTV no canto superior esquerdo.
    Atualiza dinamicamente conforme os gols são marcados!
    """
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Logo do campeonato no canto superior direito (watermark de transmissão estilo TV)
    logo_tv = obter_logo_campeonato(d_, tamanho=(105, 105))
    if logo_tv:
        if logo_tv.mode != "RGBA":
            logo_tv = logo_tv.convert("RGBA")
        img.paste(logo_tv, (L - 75 - logo_tv.width, 35), logo_tv)

    # ==================== 1. PLACAR ELETRÔNICO ESTILO SPORTV ====================
    pb_x0 = 70
    pb_y0 = 50
    pb_h = 60

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
    w_ta = max(bb_ta[2] - bb_ta[0] + 30, 110)
    w_tb = max(bb_tb[2] - bb_tb[0] + 30, 110)
    w_score = 120
    w_timer = 110
    total_w = w_ta + w_score + w_tb + w_timer

    d.rounded_rectangle([pb_x0 + 2, pb_y0 + 3, pb_x0 + total_w + 2, pb_y0 + pb_h + 3],
                           radius=10, fill=(0, 0, 0, 140))

    # Time A
    xa0 = pb_x0
    xa1 = xa0 + w_ta
    d.rounded_rectangle([xa0, pb_y0, xa1, pb_y0 + pb_h], radius=10, fill=ca + (245,))
    d.rectangle([xa1 - 10, pb_y0, xa1, pb_y0 + pb_h], fill=ca + (245,))
    d.text(((xa0 + xa1) // 2, pb_y0 + pb_h // 2), nome_a, font=f_team, fill=txt_ca + (255,), anchor="mm")

    # Placar central
    xc0 = xa1
    xc1 = xc0 + w_score
    d.rectangle([xc0, pb_y0, xc1, pb_y0 + pb_h], fill=(15, 20, 30, 245))
    d.text((xc0 + 32, pb_y0 + pb_h // 2), str(placar_a), font=f_score, fill=(255, 255, 255, 255), anchor="mm")
    d.text((xc0 + w_score // 2, pb_y0 + pb_h // 2 - 2), "×", font=fonte(24), fill=(160, 175, 195, 255), anchor="mm")
    d.text((xc1 - 32, pb_y0 + pb_h // 2), str(placar_b), font=f_score, fill=(255, 255, 255, 255), anchor="mm")

    # Time B
    xb0 = xc1
    xb1 = xb0 + w_tb
    d.rounded_rectangle([xb0, pb_y0, xb1, pb_y0 + pb_h], radius=10, fill=cb + (245,))
    d.rectangle([xb0, pb_y0, xb0 + 10, pb_y0 + pb_h], fill=cb + (245,))
    d.text(((xb0 + xb1) // 2, pb_y0 + pb_h // 2), nome_b, font=f_team, fill=txt_cb + (255,), anchor="mm")

    # Cronômetro / Tempo de jogo
    xt0 = xb1 + 6
    xt1 = xt0 + w_timer
    tempo_str = str(ev.get("tempo") or "00:00")
    d.rounded_rectangle([xt0, pb_y0, xt1, pb_y0 + pb_h], radius=10,
                           fill=(22, 28, 42, 245), outline=(55, 68, 90, 255), width=2)
    d.text(((xt0 + xt1) // 2, pb_y0 + pb_h // 2), tempo_str, font=f_timer, fill=(255, 255, 255, 255), anchor="mm")

    # Destaque dinâmico de GOL!
    if gol_neste_clipe and time_gol in (0, 1):
        xg = xa0 if time_gol == 0 else xb0
        wg = w_ta if time_gol == 0 else w_tb
        yg0 = pb_y0 + pb_h + 6
        d.rounded_rectangle([xg, yg0, xg + wg, yg0 + 32], radius=6,
                               fill=AMARELO_GOL + (250,), outline=(255, 255, 255, 255), width=2)
        d.text((xg + wg // 2, yg0 + 16), "★ GOL! ★", font=fonte(17, True), fill=(10, 15, 20, 255), anchor="mm")

    # ==================== 2. FAIXA INFERIOR DE LANCE / GOL ====================
    y0 = A - 250
    d.rectangle([0, y0, L, A], fill=(13, 17, 23, 215))

    if tipo == "gol":
        t_idx = ev.get("time", 0)
        cor_time = hex_rgb(times[t_idx]["cor"])
        d.rectangle([110, y0 + 36, 122, y0 + 170], fill=cor_time + (255,))

        autor_nome = ev.get("autor", "Gol")
        foto_autor = obter_foto_jogador(autor_nome, times[t_idx], tamanho=(95, 95))
        if foto_autor:
            img.paste(foto_autor, (140, y0 + 55), foto_autor)
            x_txt = 255
        else:
            x_txt = 150

        rotulo = f"GOL · {times[t_idx]['nome'].upper()}  ({placar_a} × {placar_b})"
        d.text((x_txt, y0 + 32), rotulo, font=fonte(28), fill=cor_time + (255,))
        d.text((x_txt, y0 + 72), autor_nome, font=fonte(64), fill=TEXTO + (255,))

        if ev.get("assist"):
            d.text((x_txt, y0 + 154), f"assistência: {ev['assist']}", font=fonte(28, False), fill=FRACO + (255,))

        d.text((L - 110, y0 + 72), ev.get("tempo", ""), font=fonte(56), fill=FRACO + (255,), anchor="ra")
        d.text((L - 110, y0 + 36), times[t_idx]["nome"], font=fonte(26), fill=cor_time + (255,), anchor="ra")
    else:
        tem_time = ev.get("time") is not None and isinstance(ev["time"], int) and 0 <= ev["time"] < len(times)
        cor_lance = hex_rgb(times[ev["time"]]["cor"]) if tem_time else VERDE
        d.rectangle([110, y0 + 36, 122, y0 + 170], fill=cor_lance + (255,))

        rotulo_lance = (ev.get("lance") or "MELHOR MOMENTO").upper()
        jogador = ev.get("destaque") or ev.get("autor")
        foto_jog = obter_foto_jogador(jogador, times[ev["time"]] if tem_time else None, tamanho=(95, 95)) if jogador else None

        if foto_jog:
            img.paste(foto_jog, (140, y0 + 55), foto_jog)
            x_txt = 255
        else:
            x_txt = 150

        if jogador:
            d.text((x_txt, y0 + 32), f"{rotulo_lance}  ({placar_a} × {placar_b})", font=fonte(28), fill=cor_lance + (255,))
            d.text((x_txt, y0 + 72), jogador, font=fonte(64), fill=TEXTO + (255,))
        else:
            d.text((x_txt, y0 + 32), f"MELHOR MOMENTO  ({placar_a} × {placar_b})", font=fonte(28), fill=cor_lance + (255,))
            d.text((x_txt, y0 + 72), ev.get("lance") or "Lance", font=fonte(58), fill=TEXTO + (255,))

        d.text((L - 110, y0 + 72), ev.get("tempo", ""), font=fonte(56), fill=FRACO + (255,), anchor="ra")
        if tem_time:
            d.text((L - 110, y0 + 36), times[ev["time"]]["nome"], font=fonte(26), fill=cor_lance + (255,), anchor="ra")

    return img


# --------------------------------------------------------------- cartelas finais

def cartela_fim_de_jogo(d_):
    """
    Placar final profissional estilo transmissão esportiva pós-jogo (SporTV / Premiere).
    Mostra o placar oficial e a lista de todos os gols de cada time.
    """
    img = Image.new("RGB", (L, A), FUNDO)
    d = ImageDraw.Draw(img)
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])

    d.rectangle([0, 0, L, 8], fill=VERDE)

    # Logo do campeonato no topo do placar final
    logo_fim = obter_logo_campeonato(d_, tamanho=(110, 110))
    if logo_fim:
        img.paste(logo_fim, (60, 25), logo_fim)
        img.paste(logo_fim, (L - 60 - logo_fim.width, 25), logo_fim)

    centralizado(d, 40, "FIM DE JOGO · PLACAR FINAL", fonte(40), VERDE)
    sub = " · ".join(x for x in [meta.get("pelada") or meta.get("torneio"), meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")] if x)
    if sub:
        centralizado(d, 95, sub, fonte(24, False), FRACO)

    gols_ordenados = sorted(d_.get("gols", []), key=_tempo_em_segundos)
    gols_a = [g for g in gols_ordenados if g.get("time") == 0]
    gols_b = [g for g in gols_ordenados if g.get("time") == 1]
    total_a = len(gols_a)
    total_b = len(gols_b)
    if meta.get("placar_jogo"):
        if meta["placar_jogo"][0] is not None:
            total_a = meta["placar_jogo"][0]
        if meta["placar_jogo"][1] is not None:
            total_b = meta["placar_jogo"][1]

    y_p = 155
    pw = 900
    px0 = (L - pw) // 2
    d.rounded_rectangle([px0, y_p, px0 + pw, y_p + 140], radius=16, fill=PAINEL, outline=PAINEL_BORDA, width=2)
    d.rectangle([px0, y_p, px0 + pw // 2, y_p + 6], fill=ca)
    d.rectangle([px0 + pw // 2, y_p, px0 + pw, y_p + 6], fill=cb)

    d.text((px0 + 40, y_p + 70), times[0]["nome"], font=fonte(42), fill=ca, anchor="lm")
    d.text((px0 + pw - 40, y_p + 70), times[1]["nome"], font=fonte(42), fill=cb, anchor="rm")

    f_big = fonte(96, True)
    d.text((L // 2 - 80, y_p + 65), str(total_a), font=f_big, fill=(255, 255, 255), anchor="mm")
    d.text((L // 2, y_p + 65), "×", font=fonte(54), fill=FRACO, anchor="mm")
    d.text((L // 2 + 80, y_p + 65), str(total_b), font=f_big, fill=(255, 255, 255), anchor="mm")

    col_w = 700
    topo_col = 325

    def desenhar_coluna_gols(x0, time_obj, lista_gols, cor):
        d.rounded_rectangle([x0, topo_col, x0 + col_w, topo_col + 690], radius=12,
                               fill=PAINEL, outline=PAINEL_BORDA, width=1)
        d.rectangle([x0, topo_col, x0 + col_w, topo_col + 6], fill=cor)
        d.text((x0 + 24, topo_col + 24), f"GOLS · {time_obj['nome'].upper()}", font=fonte(24), fill=cor)
        d.text((x0 + col_w - 24, topo_col + 26), f"{len(lista_gols)} gol(s)", font=fonte(18, False), fill=FRACO, anchor="ra")

        y_item = topo_col + 74
        if not lista_gols:
            d.text((x0 + 24, y_item), "Nenhum gol marcado", font=fonte(20, False), fill=FRACO)
            return

        for g in lista_gols[:14]:
            t_str = g.get("tempo", "")
            d.text((x0 + 24, y_item), f"{t_str}", font=fonte(20, True), fill=FRACO)
            autor = g.get("autor", "Gol")
            d.text((x0 + 110, y_item), autor, font=fonte(22, True), fill=TEXTO)
            if g.get("assist"):
                d.text((x0 + col_w - 24, y_item + 2), f"assist. {g['assist']}", font=fonte(16, False), fill=FRACO, anchor="ra")
            y_item += 42

    desenhar_coluna_gols(170, times[0], gols_a, ca)
    desenhar_coluna_gols(L // 2 + 60, times[1], gols_b, cb)

    return img


def cartela_cronologia(d_):
    img = Image.new("RGB", (L, A), FUNDO)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 8], fill=VERDE)

    logo_cr = obter_logo_campeonato(d_, tamanho=(100, 100))
    if logo_cr:
        img.paste(logo_cr, (60, 25), logo_cr)
        img.paste(logo_cr, (L - 60 - logo_cr.width, 25), logo_cr)

    centralizado(d, 60, "COMO FOI O JOGO · CRONOLOGIA", fonte(44), VERDE)

    # Ordena os gols por tempo cronológico
    gols_ordenados = sorted(d_.get("gols", []), key=_tempo_em_segundos)

    y = 165
    for g in gols_ordenados:
        t_idx = g.get("time", 0)
        t_obj = d_["times"][t_idx] if 0 <= t_idx < len(d_["times"]) else d_["times"][0]
        cor = hex_rgb(t_obj["cor"])
        d.rectangle([300, y + 8, 310, y + 40], fill=cor)
        d.text((340, y), g.get("tempo", ""), font=fonte(32, False), fill=FRACO)
        d.text((470, y), g.get("autor", "Gol"), font=fonte(34), fill=TEXTO)
        if g.get("assist"):
            d.text((470 + 330, y + 4), f"assist. {g['assist']}", font=fonte(28, False), fill=FRACO)
        d.text((1620, y), t_obj["nome"], font=fonte(28), fill=cor, anchor="ra")
        y += 56
        if y > A - 90:
            break
    return img


def cartela_destaques(d_):
    img = Image.new("RGB", (L, A), FUNDO)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, L, 8], fill=VERDE)

    logo_des = obter_logo_campeonato(d_, tamanho=(100, 100))
    if logo_des:
        img.paste(logo_des, (60, 25), logo_des)
        img.paste(logo_des, (L - 60 - logo_des.width, 25), logo_des)

    centralizado(d, 60, "DESTAQUES DA PARTIDA", fonte(44), VERDE)

    medalha = [(255, 200, 60), (190, 195, 205), (190, 130, 80)]
    for col, (titulo, chave, campo) in enumerate(
            [("ARTILHEIROS", "artilheiros", "gols"),
             ("ASSISTÊNCIAS", "garcons", "assistencias")]):
        x0 = 170 if col == 0 else L // 2 + 60
        d.rectangle([x0, 190, x0 + 640, 800], fill=PAINEL)
        d.text((x0 + 36, 220), titulo, font=fonte(30), fill=FRACO)
        for k, item in enumerate((d_.get(chave) or [])[:5]):
            y = 290 + k * 92
            cor = medalha[k] if k < 3 else FRACO
            d.ellipse([x0 + 36, y, x0 + 84, y + 48], fill=cor)
            d.text((x0 + 60, y + 24), str(k + 1), font=fonte(26), fill=FUNDO, anchor="mm")

            foto_j = obter_foto_jogador(item["jogador"], tamanho=(48, 48))
            if foto_j:
                img.paste(foto_j, (x0 + 96, y), foto_j)
                d.text((x0 + 154, y + 4), item["jogador"], font=fonte(36), fill=TEXTO)
            else:
                d.text((x0 + 110, y + 4), item["jogador"], font=fonte(36), fill=TEXTO)

            d.text((x0 + 600, y + 8), str(item[campo]), font=fonte(34), fill=cor, anchor="ra")
    centralizado(d, 900, d_["meta"].get("pelada") or d_["meta"].get("torneio") or "", fonte(34), VERDE)
    return img


# --------------------------------------------------------------- ffmpeg

def roda(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERRO ffmpeg:\n", r.stderr[-1500:])
        raise SystemExit(1)


def seg_de_imagem(img_path, dur, saida, fade=0.5):
    roda(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img_path,
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
          "-t", str(dur), "-r", str(FPS),
          "-vf", f"format=yuv420p,fade=t=in:st=0:d={fade},"
                 f"fade=t=out:st={max(dur - fade, 0.1)}:d={fade}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-pix_fmt", "yuv420p", "-movflags", "+faststart",
          "-c:a", "aac", "-b:a", "160k", "-shortest", saida])


def seg_de_clipe(clipe, overlay_png, saida, sem_audio, fade=0.4):
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", clipe], capture_output=True, text=True).stdout.strip() or 6)

    ini = 0.5
    fim = max(dur - 0.4, ini + 2.0)

    vf = (f"scale={L}:{A}:force_original_aspect_ratio=decrease,"
          f"pad={L}:{A}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p")
    filtro = (f"[0:v]{vf}[v0];"
              f"[1:v]format=rgba,fade=t=in:st={ini}:d=0.35:alpha=1,"
              f"fade=t=out:st={fim - 0.35}:d=0.35:alpha=1[ov];"
              f"[v0][ov]overlay=0:0:enable='between(t,{ini},{fim})',"
              f"fade=t=in:st=0:d={fade},fade=t=out:st={max(dur - fade, 0.1):.2f}:d={fade}[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clipe,
           "-loop", "1", "-t", str(dur), "-i", overlay_png]
    if sem_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter_complex", filtro, "-map", "[v]", "-map", "2:a"]
    else:
        cmd += ["-filter_complex",
                filtro + f";[0:a]afade=t=in:st=0:d={fade},"
                         f"afade=t=out:st={max(dur - fade, 0.1):.2f}:d={fade}[a]",
                "-map", "[v]", "-map", "[a]"]
    cmd += ["-t", str(dur), "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "160k", saida]
    roda(cmd)


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
    args = ap.parse_args()

    with open(args.partida, encoding="utf-8-sig") as f:
        d = json.load(f)

    por_indice = {g["indice"]: ("gol", g) for g in d.get("gols", [])}
    por_indice.update({l["indice"]: ("lance", l) for l in d.get("lances", [])})

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
        print("gerando cartelas...")
        if not args.sem_abertura:
            print("  gerando cartela de abertura (campo tático e escalação)...")
            p = os.path.join(tmp, "abertura.png")
            cartela_abertura(d).save(p)
            s = os.path.join(tmp, "s000.mp4")
            seg_de_imagem(p, args.abertura, s)
            partes.append(s)
            partes_gols.append(s)

        faltando = []
        placar_a = 0
        placar_b = 0

        for n, item in enumerate(roteiro, 1):
            idx = item["i"]
            if idx not in por_indice:
                continue
            tipo, ev = por_indice[idx]
            clipe = os.path.join(args.clipes, f"gol_{idx:02d}.mp4")
            if not os.path.exists(clipe):
                faltando.append(os.path.basename(clipe))
                continue

            gol_neste_clipe = False
            time_gol = None
            if tipo == "gol":
                time_gol = ev.get("time")
                if time_gol == 0:
                    placar_a += 1
                elif time_gol == 1:
                    placar_b += 1
                gol_neste_clipe = True

            png = os.path.join(tmp, f"ov{n:03d}.png")
            cartela_lance(ev, d["times"], tipo, placar_a, placar_b,
                          gol_neste_clipe=gol_neste_clipe, time_gol=time_gol, d_=d).save(png)

            s = os.path.join(tmp, f"s{n:03d}.mp4")
            rot = ev.get("autor") or ev.get("lance") or "lance"
            status_placar = f"[{placar_a} × {placar_b}]"
            print(f"  [{n:02d}/{len(roteiro)}] {ev.get('tempo','')} {status_placar} {tipo}: {rot}")
            seg_de_clipe(clipe, png, s, args.sem_audio)
            partes.append(s)
            if tipo == "gol":
                partes_gols.append(s)

        if faltando:
            print("AVISO: clipes nao encontrados:", ", ".join(faltando))

        if not args.sem_fechamento:
            print("  gerando cartelas de fechamento e placar final...")
            cartelas = [
                ("fim_de_jogo", cartela_fim_de_jogo, args.fechamento),
                ("cronologia", cartela_cronologia, args.fechamento),
                ("destaques", cartela_destaques, args.fechamento),
            ]
            for nome, func, dur in cartelas:
                p = os.path.join(tmp, f"{nome}.png")
                func(d).save(p)
                s = os.path.join(tmp, f"z_{nome}.mp4")
                seg_de_imagem(p, dur, s)
                partes.append(s)
                partes_gols.append(s)

        lista = os.path.join(tmp, "lista.txt")
        with open(lista, "w", encoding="utf-8") as f:
            for p in partes:
                f.write(f"file '{p.replace(chr(92), '/')}'\n")
        print("\njuntando vídeo completo (todos os clipes)...")
        roda(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", lista, "-c", "copy", args.saida])

        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", args.saida],
                             capture_output=True, text=True).stdout.strip()
        print(f"\npronto (todos os clipes): {os.path.abspath(args.saida)}")
        if dur:
            t = float(dur)
            print(f"duracao: {int(t // 60)}min {int(t % 60)}s | {len(partes)} segmentos")

        if args.saida_gols and any(item["i"] in por_indice and por_indice[item["i"]][0] == "gol" for item in roteiro):
            lista_gols = os.path.join(tmp, "lista_gols.txt")
            with open(lista_gols, "w", encoding="utf-8") as f:
                for p in partes_gols:
                    f.write(f"file '{p.replace(chr(92), '/')}'\n")
            print("\njuntando vídeo só dos gols...")
            roda(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                  "-i", lista_gols, "-c", "copy", args.saida_gols])
            dur_g = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                  "format=duration", "-of", "csv=p=0", args.saida_gols],
                                 capture_output=True, text=True).stdout.strip()
            print(f"\npronto (só gols): {os.path.abspath(args.saida_gols)}")
            if dur_g:
                tg = float(dur_g)
                print(f"duracao só gols: {int(tg // 60)}min {int(tg % 60)}s | {len(partes_gols)} segmentos")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
