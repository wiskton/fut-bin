import sys, os, json, math
sys.path.insert(0, r'C:\Users\willem\Documents\GitHub\fut-bin')
from PIL import Image, ImageDraw, ImageFilter
import montar_video
from montar_video import (
    L, A, hex_rgb, fonte, _limpar_nome_pillow, _texto_ajustado,
    obter_avatar_jogador, classificar_posicao, separar_titulares_e_reservas,
    _fundo_premium, _cabecalho_premium, _painel_premium,
    PREMIUM_BG, PREMIUM_PANEL, PREMIUM_PANEL_ALT, PREMIUM_LINE,
    PREMIUM_TEXT, PREMIUM_MUTED, PREMIUM_ACCENT
)

def desenhar_campo_tatico_novo(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=None, times=None):
    # Gramado moderno com listras vibrantes e ricas
    n_faixas = 10
    faixa_w = w / n_faixas
    c_grama1 = (24, 104, 60)
    c_grama2 = (19, 88, 50)
    for i in range(n_faixas):
        gx0 = int(x0 + i * faixa_w)
        gx1 = int(x0 + (i + 1) * faixa_w)
        draw.rectangle([gx0, y0, gx1, y0 + h], fill=c_grama1 if i % 2 == 0 else c_grama2)

    # Brilho radial sutil dos refletores no centro do gramado
    if img_base:
        overlay_glow = Image.new("RGBA", img_base.size, (0, 0, 0, 0))
        d_glow = ImageDraw.Draw(overlay_glow)
        cx_campo = x0 + w // 2
        cy_campo = y0 + h // 2
        r_glow_x = int(w * 0.42)
        r_glow_y = int(h * 0.42)
        d_glow.ellipse([cx_campo - r_glow_x, cy_campo - r_glow_y, cx_campo + r_glow_x, cy_campo + r_glow_y],
                       fill=(255, 255, 255, 14))
        r_glow2_x = int(w * 0.22)
        r_glow2_y = int(h * 0.22)
        d_glow.ellipse([cx_campo - r_glow2_x, cy_campo - r_glow2_y, cx_campo + r_glow2_x, cy_campo + r_glow2_y],
                       fill=(255, 255, 255, 18))
        img_base.paste(Image.alpha_composite(img_base.convert("RGBA"), overlay_glow).convert("RGB"))
        draw = ImageDraw.Draw(img_base)

    cor_linha = (248, 255, 250)
    larg_linha = 3

    # Bordas e linhas de marcação oficiais
    draw.rectangle([x0, y0, x0 + w, y0 + h], outline=cor_linha, width=larg_linha)
    meio_x = x0 + w // 2
    draw.line([meio_x, y0, meio_x, y0 + h], fill=cor_linha, width=larg_linha)

    # Círculo central e ponto do meio-campo
    r_circ = int(h * 0.18)
    draw.ellipse([meio_x - r_circ, y0 + h // 2 - r_circ, meio_x + r_circ, y0 + h // 2 + r_circ],
                 outline=cor_linha, width=larg_linha)
    draw.ellipse([meio_x - 5, y0 + h // 2 - 5, meio_x + 5, y0 + h // 2 + 5], fill=cor_linha)

    # Escanteios (4 cantos com arcos suaves de 18px)
    r_esc = 18
    draw.arc([x0 - r_esc, y0 - r_esc, x0 + r_esc, y0 + r_esc], start=0, end=90, fill=cor_linha, width=2)
    draw.arc([x0 - r_esc, y0 + h - r_esc, x0 + r_esc, y0 + h + r_esc], start=270, end=360, fill=cor_linha, width=2)
    draw.arc([x0 + w - r_esc, y0 - r_esc, x0 + w + r_esc, y0 + r_esc], start=90, end=180, fill=cor_linha, width=2)
    draw.arc([x0 + w - r_esc, y0 + h - r_esc, x0 + w + r_esc, y0 + h + r_esc], start=180, end=270, fill=cor_linha, width=2)

    # Grande Área e Pequena Área
    area_w = int(w * 0.18)
    area_h = int(h * 0.58)
    area_y = y0 + (h - area_h) // 2
    draw.rectangle([x0, area_y, x0 + area_w, area_y + area_h], outline=cor_linha, width=larg_linha)

    parea_w = int(w * 0.07)
    parea_h = int(h * 0.32)
    parea_y = y0 + (h - parea_h) // 2
    draw.rectangle([x0, parea_y, x0 + parea_w, parea_y + parea_h], outline=cor_linha, width=2)

    # Ponto penal esquerdo e Meia-lua da grande área (arco D-box)
    ponto_penalti_a = x0 + int(w * 0.12)
    draw.ellipse([ponto_penalti_a - 4, y0 + h // 2 - 4, ponto_penalti_a + 4, y0 + h // 2 + 4], fill=cor_linha)
    draw.arc([ponto_penalti_a - r_circ, y0 + h // 2 - r_circ, ponto_penalti_a + r_circ, y0 + h // 2 + r_circ],
             start=-54, end=54, fill=cor_linha, width=2)

    # Grande Área, Pequena Área e Meia-lua no lado direito
    draw.rectangle([x0 + w - area_w, area_y, x0 + w, area_y + area_h], outline=cor_linha, width=larg_linha)
    draw.rectangle([x0 + w - parea_w, parea_y, x0 + w, parea_y + parea_h], outline=cor_linha, width=2)

    ponto_penalti_b = x0 + w - int(w * 0.12)
    draw.ellipse([ponto_penalti_b - 4, y0 + h // 2 - 4, ponto_penalti_b + 4, y0 + h // 2 + 4], fill=cor_linha)
    draw.arc([ponto_penalti_b - r_circ, y0 + h // 2 - r_circ, ponto_penalti_b + r_circ, y0 + h // 2 + r_circ],
             start=126, end=234, fill=cor_linha, width=2)

    # Traves sutis atrás das linhas de fundo
    gol_w = 8
    draw.rectangle([x0 - gol_w, parea_y + 10, x0, parea_y + parea_h - 10], outline=(200, 220, 235), fill=(8, 24, 18), width=2)
    draw.rectangle([x0 + w, parea_y + 10, x0 + w + gol_w, parea_y + parea_h - 10], outline=(200, 220, 235), fill=(8, 24, 18), width=2)

    # Posicionamento inteligente dos jogadores
    def posicionar_jogadores(jogadores_pos, lado_esquerdo):
        grupos = {"goleiro": [], "zagueiro": [], "meio": [], "atacante": []}
        for nome, pos in jogadores_pos:
            grupos[classificar_posicao(pos) or "meio"].append(nome)

        coords = []
        if lado_esquerdo:
            col_x = {
                "goleiro": x0 + int(w * 0.08),
                "zagueiro": x0 + int(w * 0.20),
                "meio": x0 + int(w * 0.32),
                "atacante": x0 + int(w * 0.43),
            }
        else:
            col_x = {
                "atacante": x0 + int(w * 0.57),
                "meio": x0 + int(w * 0.68),
                "zagueiro": x0 + int(w * 0.80),
                "goleiro": x0 + int(w * 0.92),
            }

        margem_y = int(h * 0.10)
        area_util_y = h - 2 * margem_y
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
            r = 28  # Nó do jogador com presença marcante (56x56 px)

            # Sombra suave sob o avatar
            draw.ellipse([cx - r - 4, cy - r + 8, cx + r + 4, cy + r + 12], fill=(5, 15, 12, 170))

            # Anel de luz neon da cor do time em volta do avatar
            draw.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], outline=cor, width=2)
            draw.ellipse([cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1], outline=(10, 16, 26), width=1)

            av = obter_avatar_jogador(nome, time_obj, tamanho=(r * 2, r * 2), cor_time=cor, pos=cat)
            if av and img_base:
                img_base.paste(av, (cx - r, cy - r), av)

            # Mini badge de posição acoplado ao nó (GOL, ZAG, MEI, ATA)
            pos_labels = {"goleiro": "GOL", "zagueiro": "ZAG", "meio": "MEI", "atacante": "ATA"}
            tag_pos = pos_labels.get(cat, "MEI")
            f_tag = fonte(10, True)
            bx0 = cx + r - 14
            by0 = cy - r - 3
            draw.rounded_rectangle([bx0, by0, bx0 + 26, by0 + 15], radius=6, fill=cor, outline=(10, 16, 26), width=1)
            # Contraste de texto do badge
            lum = 0.299 * cor[0] + 0.587 * cor[1] + 0.114 * cor[2]
            cor_txt_tag = (10, 16, 26) if lum > 140 else (255, 255, 255)
            draw.text((bx0 + 13, by0 + 7), tag_pos, font=f_tag, fill=cor_txt_tag, anchor="mm")

            # Plaqueta de identificação estilo EA Sports FC / Champions League
            nome_limpo = _limpar_nome_pillow(nome)
            f_nome = fonte(15, True)
            bb = draw.textbbox((0, 0), nome_limpo, font=f_nome)
            nw = bb[2] - bb[0]
            nh = bb[3] - bb[1]
            pad_w = 12
            nx0 = cx - nw // 2 - pad_w
            ny0 = cy + r + 7
            nx1 = cx + nw // 2 + pad_w
            ny1 = ny0 + nh + 8

            # Fundo translúcido com borda suave
            draw.rounded_rectangle([nx0, ny0, nx1, ny1], radius=7,
                                   fill=(8, 14, 25, 240), outline=(55, 75, 105), width=1)
            # Friso inferior na cor do time
            draw.rounded_rectangle([nx0 + 4, ny1 - 2, nx1 - 4, ny1], radius=1, fill=cor)
            # Nome nítido com sombra sutil
            draw.text((cx - nw // 2 + 1, ny0 + 4), nome_limpo, font=f_nome, fill=(0, 0, 0, 180))
            draw.text((cx - nw // 2, ny0 + 3), nome_limpo, font=f_nome, fill=(255, 255, 255))


def cartela_abertura_premium_nova(d_, visiveis_a=None, visiveis_b=None):
    meta, times = d_["meta"], d_["times"]
    ca, cb = hex_rgb(times[0]["cor"]), hex_rgb(times[1]["cor"])
    img = _fundo_premium(d_)
    draw = ImageDraw.Draw(img)
    subtitle = " · ".join(str(x) for x in (
        meta.get("comp") or meta.get("rodada"), meta.get("data"), meta.get("local")
    ) if x)
    _cabecalho_premium(img, draw, d_, "PRÉ-JOGO", "ESCALAÇÕES", subtitle, etiqueta="APRESENTAÇÃO")

    titulares_a, reservas_a = separar_titulares_e_reservas(times[0])
    titulares_b, reservas_b = separar_titulares_e_reservas(times[1])
    jogadores_a = titulares_a + reservas_a
    jogadores_b = titulares_b + reservas_b

    def _resumo_atletas(titulares, reservas):
        if reservas:
            suf = "RESERVA" if len(reservas) == 1 else "RESERVAS"
            tit_suf = "TITULAR" if len(titulares) == 1 else "TITULARES"
            return f"{len(titulares)} {tit_suf} · {len(reservas)} {suf}"
        return f"{len(titulares)} ATLETAS"

    # Confronto no centro (Banner VS estilizado)
    mx0, my0, mx1, my1 = 50, 176, L - 50, 302
    _painel_premium(draw, (mx0, my0, mx1, my1), fill=PREMIUM_PANEL_ALT, radius=20)

    # Brilho de cor dos times nos cantos do painel de confronto
    draw.rounded_rectangle([mx0 + 2, my0 + 16, mx0 + 12, my1 - 16], radius=5, fill=ca)
    draw.rounded_rectangle([mx1 - 12, my0 + 16, mx1 - 2, my1 - 16], radius=5, fill=cb)

    f_time = fonte(36, True)
    f_label = fonte(13, True)
    f_aux = fonte(15, False)
    nome_a = _texto_ajustado(draw, times[0]["nome"].upper(), f_time, 560)
    nome_b = _texto_ajustado(draw, times[1]["nome"].upper(), f_time, 560)

    # Badge Pill TIME 01
    draw.rounded_rectangle([mx0 + 40, my0 + 38, mx0 + 115, my0 + 60], radius=11,
                           fill=(ca[0]//4, ca[1]//4, ca[2]//4, 180), outline=ca, width=1)
    draw.text((mx0 + 77, my0 + 49), "TIME 01", font=fonte(11, True), fill=ca, anchor="mm")
    draw.text((mx0 + 40, my0 + 68), nome_a, font=f_time, fill=PREMIUM_TEXT)
    draw.text((mx0 + 40, my0 + 110), _resumo_atletas(titulares_a, reservas_a), font=f_aux, fill=PREMIUM_MUTED)

    # Badge Pill TIME 02
    draw.rounded_rectangle([mx1 - 115, my0 + 38, mx1 - 40, my0 + 60], radius=11,
                           fill=(cb[0]//4, cb[1]//4, cb[2]//4, 180), outline=cb, width=1)
    draw.text((mx1 - 77, my0 + 49), "TIME 02", font=fonte(11, True), fill=cb, anchor="mm")
    draw.text((mx1 - 40, my0 + 68), nome_b, font=f_time, fill=PREMIUM_TEXT, anchor="ra")
    draw.text((mx1 - 40, my0 + 110), _resumo_atletas(titulares_b, reservas_b), font=f_aux, fill=PREMIUM_MUTED, anchor="ra")

    # Emblema central VS moderno estilizado
    cx_vs = L // 2
    cy_vs = my0 + (my1 - my0) // 2
    draw.ellipse([cx_vs - 38, cy_vs - 38, cx_vs + 38, cy_vs + 38], fill=(6, 11, 19), outline=(45, 62, 85), width=2)
    draw.ellipse([cx_vs - 32, cy_vs - 32, cx_vs + 32, cy_vs + 32], fill=(12, 20, 32), outline=(75, 100, 135), width=1)
    draw.text((cx_vs, cy_vs - 1), "VS", font=fonte(22, True), fill=PREMIUM_TEXT, anchor="mm")

    vis_a = set(n for n, _ in jogadores_a) if visiveis_a is None else set(visiveis_a)
    vis_b = set(n for n, _ in jogadores_b) if visiveis_b is None else set(visiveis_b)

    y, h = 326, 704
    x_left, w_side = 50, 305
    x_field, w_field = 375, 1170
    x_right = 1565

    # Cores temáticas para as tags de posição
    tags_info = {
        "goleiro":  {"sigla": "GOL", "fill": (52, 38, 12),  "borda": (245, 158, 11),  "txt": (251, 191, 36)},
        "zagueiro": {"sigla": "ZAG", "fill": (14, 38, 58),  "borda": (56, 189, 248),  "txt": (125, 211, 252)},
        "meio":     {"sigla": "MEI", "fill": (12, 44, 32),  "borda": (16, 185, 129),  "txt": (110, 231, 183)},
        "atacante": {"sigla": "ATA", "fill": (50, 18, 28),  "borda": (244, 63, 94),   "txt": (253, 164, 175)},
        "reserva":  {"sigla": "RES", "fill": (28, 36, 48),  "borda": (148, 163, 184), "txt": (203, 213, 225)},
    }

    def desenhar_elenco_novo(x0, time_obj, jogadores, visiveis, cor):
        _painel_premium(draw, (x0, y, x0 + w_side, y + h), radius=18)
        # Cabeçalho do Elenco
        draw.rounded_rectangle([x0 + 18, y + 18, x0 + 24, y + 58], radius=3, fill=cor)
        draw.text((x0 + 36, y + 23), "ELENCO", font=fonte(15, True), fill=PREMIUM_TEXT)
        # Badge contagem de atletas
        draw.rounded_rectangle([x0 + w_side - 58, y + 21, x0 + w_side - 18, y + 51], radius=8,
                               fill=(cor[0]//4, cor[1]//4, cor[2]//4), outline=cor, width=1)
        draw.text((x0 + w_side - 38, y + 36), f"{len(jogadores):02d}", font=fonte(15, True), fill=cor, anchor="mm")
        draw.line([x0 + 18, y + 68, x0 + w_side - 18, y + 68], fill=PREMIUM_LINE, width=1)

        row_y = y + 80
        total_j = len(jogadores)
        # Espaçamento dinâmico: se há poucos atletas (ex: 6), preenche com harmonia e elegância
        if total_j <= 7:
            row_h = 58
            gap = 10
            av_sz = 38
            f_sz = 17
        elif total_j <= 10:
            row_h = 50
            gap = 8
            av_sz = 34
            f_sz = 16
        else:
            row_h = 42
            gap = 5
            av_sz = 30
            f_sz = 14

        for idx, (nome, pos) in enumerate(jogadores):
            yy = row_y + idx * (row_h + gap)
            if yy + row_h > y + h - 16:
                break
            eh_res = (pos == "reserva")
            cat = classificar_posicao(pos) or ("reserva" if eh_res else "meio")
            tag_cfg = tags_info.get(cat, tags_info["meio"])

            # Card individual translúcido para cada atleta
            card_fill = (14, 23, 37, 210) if (nome in visiveis) else (11, 17, 27, 130)
            card_borda = (35, 52, 78) if (nome in visiveis) else (22, 33, 50)
            draw.rounded_rectangle([x0 + 14, yy, x0 + w_side - 14, yy + row_h], radius=9,
                                   fill=card_fill, outline=card_borda, width=1)

            if nome in visiveis:
                avatar = obter_avatar_jogador(nome, time_obj, tamanho=(av_sz, av_sz), cor_time=cor, pos=pos)
                if avatar:
                    img.paste(avatar, (x0 + 22, yy + (row_h - av_sz) // 2), avatar)
                nome_x = x0 + 22 + av_sz + 12
                f_nome = fonte(f_sz, True)
                nome_fit = _texto_ajustado(draw, nome, f_nome, 130)
                cor_txt = (190, 202, 218) if eh_res else PREMIUM_TEXT
                draw.text((nome_x, yy + (row_h - f_sz) // 2 - 1), nome_fit, font=f_nome, fill=cor_txt)

                # Tag de posição com cor vibrante
                tag_str = tag_cfg["sigla"]
                tag_w = 38
                tag_h = 24
                tag_x = x0 + w_side - 24 - tag_w
                tag_y = yy + (row_h - tag_h) // 2
                draw.rounded_rectangle([tag_x, tag_y, tag_x + tag_w, tag_y + tag_h], radius=6,
                                       fill=tag_cfg["fill"], outline=tag_cfg["borda"], width=1)
                draw.text((tag_x + tag_w // 2, tag_y + tag_h // 2), tag_str, font=fonte(10, True),
                          fill=tag_cfg["txt"], anchor="mm")

    desenhar_elenco_novo(x_left, times[0], jogadores_a, vis_a, ca)
    desenhar_elenco_novo(x_right, times[1], jogadores_b, vis_b, cb)

    # Painel do Campo Tático com moldura chanfrada de alta qualidade
    _painel_premium(draw, (x_field, y, x_field + w_field, y + h), radius=18)
    desenhar_campo_tatico_novo(
        draw, x_field + 18, y + 18, w_field - 36, h - 36,
        [(n, p) for n, p in titulares_a if n in vis_a],
        [(n, p) for n, p in titulares_b if n in vis_b],
        ca, cb, img_base=img, times=times,
    )
    return img

if __name__ == '__main__':
    with open(r'C:\Users\willem\Documents\GitHub\fut-bin\partida.json', encoding='utf-8-sig') as f:
        d = json.load(f)
    img = cartela_abertura_premium_nova(d)
    out = r'C:\Users\willem\.gemini\antigravity\brain\b0525ebb-8393-448d-a191-e679f76852fb\scratch\abertura_nova.jpg'
    img.save(out, quality=95)
    print('Salvo:', out)
