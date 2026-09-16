"""
detectar_gols.py (v2) - encontra os gols pela mudanca do PLACAR.

Por que mudou em relacao a v1:
  A v1 comparava frames consecutivos. Isso nao funciona porque o placar de LED
  e multiplexado (os digitos piscam sozinhos) e, ao mesmo tempo, uma mudanca
  real de placar acende poucos segmentos de um unico digito. O ruido era MAIOR
  que o sinal, entao nenhum limiar unico servia.

  A v2 compara a MEDIANA dos N segundos ANTES contra a MEDIANA dos N segundos
  DEPOIS de cada instante. A cintilacao desaparece na mediana; a mudanca de
  placar permanece. O limiar e calibrado a partir do proprio video.

FLUXO:
  1) python detectar_gols.py --source_video_path jogo.mp4 --pick_placar
  2) python detectar_gols.py --source_video_path jogo.mp4
  3) conferir contato_placar.png, ajustar --limiar se preciso
  4) python detectar_gols.py --source_video_path jogo.mp4 --cortar

SAIDAS (pasta --output_dir, padrao "gols/"):
  gols.json            - eventos com tempo e janela de corte
  contato_placar.png   - placar ANTES e DEPOIS de cada evento (conferencia visual)
  ranking_picos.txt    - os 40 maiores picos, para escolher o limiar com dado
  clipes/gol_NN.mp4    - os cortes (apenas com --cortar)
"""

import argparse
import json
import os
import subprocess

import cv2
import numpy as np
from tqdm import tqdm

# --- amostragem ---
SAMPLE_FPS = 5.0        # amostras por segundo
MEDIA_FRAMES = 15       # frames mediados por amostra (mata a cintilacao do LED)
SIG_W, SIG_H = 64, 20   # assinatura binaria

# --- deteccao de degrau ---
JANELA_S = 6.0          # segundos de cada lado usados na mediana
GUARDA_S = 1.5          # zona morta em volta do instante (placar demora a atualizar)

# Cada mudanca real produz um PLATO elevado de 2*(JANELA+GUARDA) segundos, porque
# a janela de antes e a de depois continuam diferentes enquanto a mudanca passa
# por dentro delas. Se a supressao de vizinhos for menor que esse plato, uma
# unica mudanca vira dois eventos. Por isso o minimo e amarrado ao plato.
MIN_INTERVALO_S = max(16.0, 2 * (JANELA_S + GUARDA_S) + 1)

# --- rastreio do placar ---
MARGEM_BUSCA = 3.0      # a area de busca e N vezes a regiao marcada
VERMELHO_MIN = 18       # intensidade minima de vermelho para considerar "aceso"

# --- corte ---
# 20s antes da mudanca do placar para pegar a jogada inteira do gol
ANTES_S = 20.0
DEPOIS_S = 4.0


# --------------------------------------------------------------- regiao


def parse_tempo(txt):
    """Aceita 520, '520', '8:40' ou '01:07:08' e devolve segundos."""
    if txt is None:
        return None
    txt = str(txt).strip()
    if ":" not in txt:
        return float(txt)
    partes = [float(p) for p in txt.split(":")]
    seg = 0.0
    for p in partes:
        seg = seg * 60 + p
    return seg

def pick_placar(video_path, arquivo):
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("nao consegui ler o primeiro frame")
        return None

    print("\nArraste um retangulo em volta do DISPLAY INTEIRO (as duas linhas).")
    print("O script rastreia o display e usa so a faixa do placar (--metade).")
    print("Pode marcar com folga: a camera cede ao longo do jogo e o rastreio")
    print("acompanha o deslocamento.")
    print("ENTER confirma, C cancela.\n")

    h, w = frame.shape[:2]
    escala = min(1600 / w, 900 / h, 1.0)
    view = cv2.resize(frame, (int(w * escala), int(h * escala)))
    x, y, cw, ch = cv2.selectROI("Selecione o PLACAR (sem o cronometro)", view,
                                 showCrosshair=True)
    cv2.destroyAllWindows()
    if cw == 0 or ch == 0:
        print("cancelado")
        return None

    rect = [int(x / escala), int(y / escala), int(cw / escala), int(ch / escala)]
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump({"placar": rect}, f)
    crop = frame[rect[1]:rect[1] + rect[3], rect[0]:rect[0] + rect[2]]
    cv2.imwrite("placar_recorte.png", cv2.resize(crop, None, fx=8, fy=8,
                                                 interpolation=cv2.INTER_NEAREST))
    print(f"regiao salva em {arquivo}: {rect}")
    print("Confira placar_recorte.png.")
    return rect


def load_placar(arquivo):
    if not os.path.exists(arquivo):
        return None
    with open(arquivo, encoding="utf-8-sig") as f:   # -sig tolera BOM do PowerShell
        return json.load(f)["placar"]


# --------------------------------------------------------------- assinatura

def area_busca(rect, largura, altura):
    """Expande a regiao marcada para dar folga ao deslocamento da camera."""
    x, y, w, h = rect
    cx, cy = x + w / 2, y + h / 2
    bw, bh = w * MARGEM_BUSCA, h * MARGEM_BUSCA
    bx = int(max(cx - bw / 2, 0))
    by = int(max(cy - bh / 2, 0))
    return [bx, by, int(min(bw, largura - bx)), int(min(bh, altura - by))]


def caixa_vermelha(frame, busca):
    """Acha o placar dentro da area de busca pelo centroide do vermelho aceso.

    A camera cede no apoio ao longo do jogo e o placar sobe algumas dezenas de
    pixels. Com recorte fixo isso faz a regiao sair de cima dos digitos no meio
    da partida. Rastreando o vermelho, o recorte acompanha o deslocamento.
    """
    bx, by, bw, bh = busca
    reg = frame[by:by + bh, bx:bx + bw]
    if reg.size == 0:
        return None
    b, g, r = cv2.split(reg.astype(np.int16))
    ex = np.clip(r - np.maximum(g, b), 0, 255).astype(np.uint8)
    ex = cv2.GaussianBlur(ex, (5, 5), 0)
    if int(ex.max()) < VERMELHO_MIN:
        return None
    _, mask = cv2.threshold(ex, int(ex.max() * 0.45), 255, cv2.THRESH_BINARY)
    ys, xs = np.nonzero(mask)
    if len(xs) < 10:
        return None
    # percentis em vez de min/max: um pixel vermelho perdido no alambrado nao
    # estica a caixa. O cronometro, sempre aceso, mantem a caixa estavel mesmo
    # quando o placar muda de valor.
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    return np.array([bx + x0, by + y0, bx + x1, by + y1], np.float32)


def recortar_caixa(frame, caixa, metade="baixo", alvo=(96, 32)):
    """Recorta EXATAMENTE o display, sem fundo, e devolve so a faixa util.

    Recortar colado nos digitos e o que faz a assinatura medir o placar em vez
    de medir ceu, alambrado e arvore. Redimensionar para um tamanho fixo tambem
    absorve a variacao de escala do rastreio.
    """
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = caixa
    alt = y1 - y0
    if metade == "baixo":
        y0 = y0 + alt * 0.46
    elif metade == "cima":
        y1 = y0 + alt * 0.54
    xa, ya = max(int(x0) - 1, 0), max(int(y0) - 1, 0)
    xb, yb = min(int(round(x1)) + 2, W), min(int(round(y1)) + 2, H)
    if xb - xa < 4 or yb - ya < 3:
        return None
    return cv2.resize(frame[ya:yb, xa:xb], alvo, interpolation=cv2.INTER_AREA)


def assinatura(crop):
    b, g, r = cv2.split(crop.astype(np.int16))
    realce = np.clip(r - np.maximum(g, b), 0, 255).astype(np.uint8)
    realce = cv2.resize(realce, (SIG_W, SIG_H), interpolation=cv2.INTER_AREA)
    if realce.max() < 12:
        return None
    realce = cv2.normalize(realce, None, 0, 255, cv2.NORM_MINMAX)
    _, bina = cv2.threshold(realce, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bina > 0


def amostrar(video_path, rect, inicio=None, fim=None, metade="baixo", fixo=False):
    """Percorre o video e devolve (tempos, assinaturas, recortes)."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    passo = max(int(round(fps / SAMPLE_FPS)), 1)
    x, y, w, h = rect
    largura = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    altura = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    busca = area_busca(rect, largura, altura)
    tam = (w, h)
    perdidos = 0
    # a posicao usada no recorte e a MEDIANA das ultimas leituras: a cintilacao
    # do LED faz o centroide pular a cada frame, mas a deriva da camera e lenta
    from collections import deque
    caixas = deque(maxlen=max(int(fps * 3), 15))

    ini_f = int((inicio or 0) * fps)
    fim_f = int(fim * fps) if fim else None
    if ini_f:
        cap.set(cv2.CAP_PROP_POS_FRAMES, ini_f)
    tempos, sigs, crops, buffer = [], [], [], []
    with tqdm(total=total or None, desc="lendo placar") as barra:
        i = ini_f
        while True:
            if fim_f and i > fim_f:
                break
            ok, frame = cap.read()
            if not ok:
                break
            barra.update(1)
            if fixo:
                # camera parada: recorte fixo, sem rastreio. Mais estavel, e nao
                # corre o risco de o rastreio travar em alambrado ou telhado.
                recorte = frame[y:y + h, x:x + w]
                if recorte.size == 0:
                    perdidos += 1
                    i += 1
                    continue
                buffer.append(cv2.resize(recorte, (96, 32),
                                         interpolation=cv2.INTER_AREA).astype(np.float32))
                if len(buffer) > MEDIA_FRAMES:
                    buffer.pop(0)
                if i % passo == 0 and len(buffer) >= min(MEDIA_FRAMES, 5):
                    suave_img = np.mean(buffer, axis=0).astype(np.uint8)
                    sig = assinatura(suave_img)
                    if sig is not None:
                        tempos.append(i / fps)
                        sigs.append(sig)
                        crops.append(suave_img)
                i += 1
                continue

            caixa = caixa_vermelha(frame, busca)
            if caixa is not None:
                caixas.append(caixa)
            if not caixas:
                perdidos += 1
                i += 1
                continue
            suave = np.median(np.array(caixas), axis=0)
            recorte = recortar_caixa(frame, suave, metade)
            if recorte is None:
                perdidos += 1
                i += 1
                continue
            buffer.append(recorte.astype(np.float32))
            if len(buffer) > MEDIA_FRAMES:
                buffer.pop(0)
            if i % passo == 0 and len(buffer) >= min(MEDIA_FRAMES, 5):
                suave = np.mean(buffer, axis=0).astype(np.uint8)
                sig = assinatura(suave)
                if sig is not None:
                    tempos.append(i / fps)
                    sigs.append(sig)
                    crops.append(suave)
            i += 1
    cap.release()
    if perdidos:
        print(f"(placar nao localizado em {perdidos} frames)")
    return np.array(tempos), np.array(sigs), crops, fps


def curva_degrau(tempos, sigs):
    """Para cada amostra: distancia entre a mediana de antes e a de depois."""
    n = len(tempos)
    dt = np.median(np.diff(tempos)) if n > 1 else 1.0 / SAMPLE_FPS
    jan = max(int(round(JANELA_S / dt)), 3)
    gua = max(int(round(GUARDA_S / dt)), 1)

    dist = np.full(n, np.nan, np.float32)
    for i in range(n):
        a0, a1 = i - gua - jan, i - gua
        d0, d1 = i + gua, i + gua + jan
        if a0 < 0 or d1 > n:
            continue
        antes = np.median(sigs[a0:a1], axis=0) > 0.5
        depois = np.median(sigs[d0:d1], axis=0) > 0.5
        dist[i] = float(np.mean(antes != depois))
    return dist


def custo_segmentos(C, i, j):
    """Custo de representar as amostras [i,j) por uma unica assinatura mediana.

    Para cada bit, o menor entre 'quantos estao ligados' e 'quantos desligados':
    e o numero de bits que discordam da mediana do trecho. Trecho com placar
    estavel tem custo baixo; trecho que contem uma mudanca tem custo alto.
    """
    n = j - i
    uns = C[j] - C[i]
    return float(np.minimum(uns, n - uns).sum())


def melhor_corte(C, i, j):
    """Ponto de corte em [i,j) que mais reduz o custo. Vetorizado."""
    if j - i < 4:
        return None, 0.0
    m = np.arange(i + 2, j - 1)
    esq_n = (m - i)[:, None]
    esq_uns = C[m] - C[i]
    dir_n = (j - m)[:, None]
    dir_uns = C[j] - C[m]
    custo = (np.minimum(esq_uns, esq_n - esq_uns).sum(axis=1)
             + np.minimum(dir_uns, dir_n - dir_uns).sum(axis=1))
    k = int(np.argmin(custo))
    ganho = custo_segmentos(C, i, j) - float(custo[k])
    return int(m[k]), ganho


def segmentar(sigs, n_cortes, min_amostras):
    """Segmentacao binaria: acha os n_cortes que mais reduzem o custo total.

    Nao usa limiar. Recebe QUANTAS mudancas procurar - que voce conhece pelo
    placar final - e devolve onde elas estao.
    """
    plano = sigs.reshape(len(sigs), -1).astype(np.int32)
    C = np.zeros((len(sigs) + 1, plano.shape[1]), np.int32)
    np.cumsum(plano, axis=0, out=C[1:])

    fronteiras = [0, len(sigs)]
    for _ in range(n_cortes):
        melhor = (None, 0.0, None)
        for a, b in zip(fronteiras[:-1], fronteiras[1:]):
            if b - a < 2 * min_amostras:
                continue
            corte, ganho = melhor_corte(C, a + min_amostras, b - min_amostras)
            if corte is not None and ganho > melhor[1]:
                melhor = (corte, ganho, (a, b))
        if melhor[0] is None:
            break
        fronteiras.append(melhor[0])
        fronteiras.sort()
    return fronteiras[1:-1]


def achar_eventos(tempos, dist, limiar):
    """Picos acima do limiar, com supressao de nao-maximos."""
    validos = np.where(~np.isnan(dist) & (dist >= limiar))[0]
    eventos = []
    usados = np.zeros(len(dist), bool)
    for i in sorted(validos, key=lambda k: -dist[k]):
        if usados[i]:
            continue
        perto = np.abs(tempos - tempos[i]) < MIN_INTERVALO_S
        usados |= perto
        eventos.append(i)
    return sorted(eventos, key=lambda k: tempos[k])


def sugerir_limiar(dist):
    """Ruido de fundo medido no proprio video; limiar com folga sobre ele.

    Usa a MEDIANA como piso de ruido, nao um percentil alto: perto de cada
    mudanca real a curva fica elevada por uma janela inteira, entao p75/p95
    incorporam o proprio sinal e o limiar sobe ate engolir os gols.
    O limiar erra para BAIXO de proposito - e mais facil apagar um evento
    sobrando do gols.json do que descobrir um que nunca foi detectado.
    """
    v = dist[~np.isnan(dist)]
    if not len(v):
        return 0.03, 0.0
    ruido = float(np.median(v))
    return max(round(ruido * 3 + 0.004, 4), 0.012), ruido


# --------------------------------------------------------------- saidas

def contact_sheet(eventos, caminho, altura=64):
    if not eventos:
        return
    linhas = []
    for ev in eventos:
        par = []
        for chave in ("_antes", "_depois"):
            img = ev[chave]
            esc = altura / img.shape[0]
            par.append(cv2.resize(img, None, fx=esc, fy=esc, interpolation=cv2.INTER_NEAREST))
        larg = max(p.shape[1] for p in par)
        par = [cv2.copyMakeBorder(p, 0, 0, 0, larg - p.shape[1],
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0)) for p in par]
        seta = np.zeros((altura, 34, 3), np.uint8)
        cv2.putText(seta, ">", (6, altura - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        rot = np.zeros((altura, 190, 3), np.uint8)
        placar_txt = f" [{ev.get('placar')}]" if ev.get('placar') else ""
        cv2.putText(rot, f"#{ev['indice']:02d} {ev['tempo']}{placar_txt}", (6, altura - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(rot, f"d={ev['forca']:.3f}", (6, altura - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1)
        linhas.append(np.hstack([rot, par[0], seta, par[1]]))
    larg = max(l.shape[1] for l in linhas)
    linhas = [cv2.copyMakeBorder(l, 3, 3, 0, larg - l.shape[1],
                                 cv2.BORDER_CONSTANT, value=(30, 30, 30)) for l in linhas]
    cv2.imwrite(caminho, np.vstack(linhas))


def ranking(tempos, dist, caminho, limiar, ruido):
    v = np.where(~np.isnan(dist))[0]
    ordem = sorted(v, key=lambda k: -dist[k])
    escolhidos, usados = [], np.zeros(len(dist), bool)
    for i in ordem:
        if usados[i]:
            continue
        usados |= np.abs(tempos - tempos[i]) < MIN_INTERVALO_S
        escolhidos.append(i)
        if len(escolhidos) >= 40:
            break
    linhas = [
        "40 MAIORES PICOS (ja com supressao de vizinhos)",
        f"ruido de fundo (mediana): {ruido:.4f}   |   limiar em uso: {limiar:.4f}",
        "",
        "Procure o DEGRAU na coluna forca: os gols de verdade ficam agrupados",
        "num patamar alto, e o ruido despenca depois. Ponha o limiar no meio.",
        "",
        f"{'#':>3} {'tempo':>8} {'forca':>8}",
    ]
    for k, i in enumerate(escolhidos, 1):
        t = tempos[i]
        marca = "  <-- limiar" if k > 1 and dist[escolhidos[k - 2]] >= limiar > dist[i] else ""
        linhas.append(f"{k:>3} {int(t // 60):02d}:{int(t % 60):02d}    {dist[i]:.4f}{marca}")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def cortar(video_path, eventos, output_dir):
    destino = os.path.join(output_dir, "clipes")
    os.makedirs(destino, exist_ok=True)
    for ev in tqdm(eventos, desc="cortando"):
        saida = os.path.join(destino, f"gol_{ev['indice']:02d}.mp4")
        dur = ev["fim_s"] - ev["inicio_s"]
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(ev["inicio_s"]), "-i", video_path, "-t", str(dur),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-avoid_negative_ts", "make_zero", saida,
        ], check=False)
    print(f"clipes em {os.path.abspath(destino)}")


# --------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source_video_path", required=True)
    ap.add_argument("--pick_placar", action="store_true")
    ap.add_argument("--cortar", action="store_true")
    ap.add_argument("--gols", type=int, default=None,
                    help="numero de gols do placar final; dispensa limiar")
    ap.add_argument("--limiar", type=float, default=None,
                    help="força mínima para valer como gol; omitido = calibra sozinho")
    ap.add_argument("--fixo", action="store_true",
                    help="camera parada: usa a regiao exata, sem rastrear o placar")
    ap.add_argument("--metade", default="baixo", choices=["baixo", "cima", "tudo"],
                    help="qual faixa do display e o PLACAR (a outra e o cronometro)")
    ap.add_argument("--inicio", default=None, help="inicio do jogo, ex 8:40")
    ap.add_argument("--fim", default=None, help="fim do jogo, ex 1:07:08")
    ap.add_argument("--placar_file", default="placar.json")
    ap.add_argument("--output_dir", default="gols")
    args = ap.parse_args()

    if args.pick_placar:
        pick_placar(args.source_video_path, args.placar_file)
        return

    rect = load_placar(args.placar_file)
    if rect is None:
        print(f"{args.placar_file} nao encontrado. Rode antes com --pick_placar.")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    caminho_json = os.path.join(args.output_dir, "gols.json")

    if args.cortar:
        if not os.path.exists(caminho_json):
            print("gols.json nao encontrado. Rode a deteccao primeiro.")
            return
        with open(caminho_json, encoding="utf-8-sig") as f:
            cortar(args.source_video_path, json.load(f)["gols"], args.output_dir)
        return

    if args.fixo:
        print("modo fixo: usando a regiao marcada, sem rastreio")
    else:
        print(f"faixa usada do display: {args.metade}")
    tempos, sigs, crops, fps = amostrar(
        args.source_video_path, rect, parse_tempo(args.inicio),
        parse_tempo(args.fim), args.metade, args.fixo)
    if len(tempos) < 50:
        print("amostras insuficientes: o placar esta ilegivel neste video.")
        return

    dist = curva_degrau(tempos, sigs)

    ruido = float(np.nanmedian(dist)) if np.any(~np.isnan(dist)) else 0.0
    limiar = 0.0
    if args.gols:
        dt = float(np.median(np.diff(tempos)))
        min_amostras = max(int(MIN_INTERVALO_S / dt / 2), 3)
        print(f"\nsegmentando em {args.gols + 1} trechos "
              f"({args.gols} mudancas) - sem limiar")
        idx = segmentar(sigs, args.gols, min_amostras)
    else:
        auto, ruido = sugerir_limiar(dist)
        limiar = args.limiar if args.limiar is not None else auto
        print(f"\nruido de fundo (mediana): {ruido:.4f}")
        print(f"limiar: {limiar:.4f}"
              + ("  (calibrado automaticamente)" if args.limiar is None else "  (manual)"))
        idx = achar_eventos(tempos, dist, limiar)
    dt = np.median(np.diff(tempos))
    jan = max(int(round(JANELA_S / dt)), 3)
    gua = max(int(round(GUARDA_S / dt)), 1)

    placar_a, placar_b = 0, 0
    eventos = []
    for k, i in enumerate(idx, 1):
        t = float(tempos[i])
        a = np.median(crops[max(i - gua - jan, 0):max(i - gua, 1)], axis=0).astype(np.uint8)
        d = np.median(crops[i + gua:i + gua + jan], axis=0).astype(np.uint8)
        forca_i = float(dist[i]) if not np.isnan(dist[i]) else 0.0

        # Estimar qual lado do placar teve maior variacao
        mid_x = a.shape[1] // 2
        var_l = float(np.mean(np.abs(d[:, :mid_x].astype(float) - a[:, :mid_x].astype(float))))
        var_r = float(np.mean(np.abs(d[:, mid_x:].astype(float) - a[:, mid_x:].astype(float))))
        time_provavel = 0 if var_l >= var_r else 1
        if time_provavel == 0:
            placar_a += 1
        else:
            placar_b += 1
        placar_str = f"{placar_a} x {placar_b}"

        eventos.append({
            "indice": k, "tempo_s": round(t, 2),
            "tempo": f"{int(t // 60):02d}:{int(t % 60):02d}",
            "inicio_s": round(max(t - ANTES_S, 0), 2), "fim_s": round(t + DEPOIS_S, 2),
            "forca": round(forca_i, 4), "status": None,
            "placar": placar_str, "time_provavel": time_provavel,
            "_antes": a, "_depois": d,
        })

    print(f"\n{len(eventos)} mudancas de placar detectadas:\n")
    for ev in eventos:
        print(f"  #{ev['indice']:02d}  {ev['tempo']}  placar {ev['placar']}  forca {ev['forca']:.3f}   "
              f"corte {ev['inicio_s']:.1f}s -> {ev['fim_s']:.1f}s")

    contact_sheet(eventos, os.path.join(args.output_dir, "contato_placar.png"))
    ranking(tempos, dist, os.path.join(args.output_dir, "ranking_picos.txt"), limiar, ruido)

    limpos = [{k: v for k, v in ev.items() if not k.startswith("_")} for ev in eventos]

    # NUNCA sobrescreve marcacoes ja feitas (gol/assistencia/tempo revisados a
    # mao): o que ja existe em gols.json - de qualquer fonte (placar, zona,
    # revisado) - e preservado tal como esta, e so entram como eventos NOVOS
    # os que nao caem perto (MIN_INTERVALO_S) de nenhum tempo ja conhecido.
    # Mesma logica de "so acrescenta" que detectar_zonas.py ja usa.
    existentes = []
    if os.path.exists(caminho_json):
        try:
            with open(caminho_json, encoding="utf-8-sig") as f:
                existentes = json.load(f).get("gols", [])
        except Exception:
            existentes = []
    tempos_existentes = [ev.get("tempo_s") for ev in existentes if ev.get("tempo_s") is not None]
    indice_base = max([ev["indice"] for ev in existentes], default=0)

    novos = []
    for ev in limpos:
        if any(abs(ev["tempo_s"] - t_ex) < MIN_INTERVALO_S for t_ex in tempos_existentes):
            continue  # ja tem um evento marcado perto desse instante - preserva o que ja existe
        indice_base += 1
        ev["indice"] = indice_base
        novos.append(ev)

    print(f"\n{len(novos)} eventos novos (de {len(limpos)} detectados agora); "
          f"{len(limpos) - len(novos)} ja estavam marcados e foram preservados.")

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump({"video": os.path.basename(args.source_video_path), "fps": fps,
                   "limiar": limiar, "fonte": "misto" if existentes else "placar",
                   "gols": existentes + novos}, f, indent=2, ensure_ascii=False)

    print("\nCONFIRA contato_placar.png: cada linha mostra o placar antes -> depois.")
    print("Se o numero de eventos nao bate com o placar final do jogo, abra")
    print("ranking_picos.txt, ache o degrau na coluna 'forca' e rode de novo")
    print("com --limiar <valor no meio do degrau>.")


if __name__ == "__main__":
    main()
