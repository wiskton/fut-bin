"""
detectar_zonas.py - encontra jogadas por MOVIMENTO em zonas-gatilho marcadas no quadro.

Complementa detectar_gols.py (que le o PLACAR): aqui voce marca uma ou mais
areas no quadro - por exemplo a boca de cada gol - e o script mede, pra cada
zona, o quanto os pixels mudam de um frame pro outro dentro dela. A boca do
gol fica parada a maior parte do tempo (rede e gramado parados); quando ha
um pico de movimento (bola, jogadores, comemoracao) bem acima do ruido de
fundo do proprio video, vira um evento - reaproveitando a mesma logica de
pico/supressao e o mesmo corte (ANTES_S/DEPOIS_S) que detectar_gols.py usa
pro placar.

RISCO CONHECIDO (mesma familia de problema ja documentada no README, secao
"O que nao funcionou"): jogador passando perto, goleiro se mexendo ou torcida
atras do alambrado tambem geram movimento. Zona-gatilho tende a errar mais
que o placar - por isso os eventos aqui sempre entram no gols.json pra
REVISAR no passo 4 do assistente (assistindo o clipe), igual a qualquer
outro evento.

Ao contrario de detectar_gols.py, este script NUNCA sobrescreve o
gols.json - ele ACRESCENTA os eventos achados aos que ja existirem (gol do
placar, jogada adicionada a mao etc.), continuando a sequencia de indice.

FLUXO:
  1) marcar as zonas em zonas.json (passo 2 do assistente web, ou a mao:
     {"zonas": [[x,y,w,h], [x,y,w,h], ...]})
  2) python detectar_zonas.py --source_video_path jogo.mp4
  3) conferir ranking_picos_zonas.txt, ajustar --limiar se precisar e rodar nao
  4) python detectar_zonas.py --source_video_path jogo.mp4 --cortar
"""

import argparse
import json
import os

import cv2
import numpy as np
from tqdm import tqdm

from detectar_gols import (
    ANTES_S, DEPOIS_S, MIN_INTERVALO_S, SAMPLE_FPS,
    achar_eventos, cortar, parse_tempo, ranking, sugerir_limiar,
)


def load_zonas(arquivo):
    if not os.path.exists(arquivo):
        return None
    with open(arquivo, encoding="utf-8-sig") as f:
        zonas = json.load(f).get("zonas", [])
    return zonas or None


def amostrar_zonas(video_path, zonas, inicio=None, fim=None):
    """Percorre o video e devolve (tempos, sinais, fps).

    sinais tem uma coluna por zona: a media, dentro da janela de amostragem
    (~1/SAMPLE_FPS segundos), da diferenca absoluta entre frames CONSECUTIVOS
    restrita ao retangulo da zona. Zona parada = sinal perto de zero; zona com
    movimento sustentado pela janela inteira = sinal alto.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    passo = max(int(round(fps / SAMPLE_FPS)), 1)

    ini_f = int((inicio or 0) * fps)
    fim_f = int(fim * fps) if fim else None
    if ini_f:
        cap.set(cv2.CAP_PROP_POS_FRAMES, ini_f)

    anteriores = [None] * len(zonas)
    acumulado = np.zeros(len(zonas), np.float64)
    contagem = 0
    tempos, sinais = [], []
    i = ini_f
    with tqdm(total=total or None, desc="lendo zonas") as barra:
        while True:
            if fim_f and i > fim_f:
                break
            ok, frame = cap.read()
            if not ok:
                break
            barra.update(1)
            cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for k, (x, y, w, h) in enumerate(zonas):
                recorte = cinza[y:y + h, x:x + w]
                if recorte.size == 0:
                    continue
                anterior = anteriores[k]
                if anterior is not None and anterior.shape == recorte.shape:
                    acumulado[k] += float(np.mean(cv2.absdiff(recorte, anterior)))
                anteriores[k] = recorte
            contagem += 1
            if i % passo == 0 and contagem > 1:
                tempos.append(i / fps)
                sinais.append(acumulado / contagem)
                acumulado[:] = 0
                contagem = 0
            i += 1
    cap.release()
    return np.array(tempos), np.array(sinais), fps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source_video_path", required=True)
    ap.add_argument("--zonas_file", default="zonas.json")
    ap.add_argument("--cortar", action="store_true")
    ap.add_argument("--eventos", type=int, default=None,
                    help="numero esperado de jogadas; dispensa limiar (pega os N maiores picos)")
    ap.add_argument("--limiar", type=float, default=None,
                    help="energia minima de movimento pra virar evento; omitido = calibra sozinho")
    ap.add_argument("--inicio", default=None, help="inicio do jogo, ex 8:40")
    ap.add_argument("--fim", default=None, help="fim do jogo, ex 1:07:08")
    ap.add_argument("--output_dir", default="gols")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    caminho_json = os.path.join(args.output_dir, "gols.json")

    if args.cortar:
        if not os.path.exists(caminho_json):
            print("gols.json nao encontrado. Rode a deteccao primeiro.")
            return
        with open(caminho_json, encoding="utf-8-sig") as f:
            cortar(args.source_video_path, json.load(f)["gols"], args.output_dir)
        return

    zonas = load_zonas(args.zonas_file)
    if not zonas:
        print(f"{args.zonas_file} nao encontrado ou vazio. Marque as zonas antes "
              "(passo 2 do assistente web).")
        return

    tempos, sinais, fps = amostrar_zonas(
        args.source_video_path, zonas, parse_tempo(args.inicio), parse_tempo(args.fim))
    if len(tempos) < 10:
        print("amostras insuficientes: confira o video/as zonas marcadas.")
        return

    dist = sinais.max(axis=1)
    zona_de = sinais.argmax(axis=1)

    if args.eventos:
        ordem = np.argsort(-dist)
        idx, usados = [], np.zeros(len(dist), bool)
        for i in ordem:
            if usados[i]:
                continue
            usados |= np.abs(tempos - tempos[i]) < MIN_INTERVALO_S
            idx.append(int(i))
            if len(idx) >= args.eventos:
                break
        idx.sort()
        limiar = min((dist[i] for i in idx), default=0.0)
        ruido = float(np.nanmedian(dist)) if len(dist) else 0.0
        print(f"\npegando os {args.eventos} maiores picos - sem limiar")
    else:
        auto, ruido = sugerir_limiar(dist)
        limiar = args.limiar if args.limiar is not None else auto
        print(f"\nruido de fundo (mediana): {ruido:.4f}")
        print(f"limiar: {limiar:.4f}"
              + ("  (calibrado automaticamente)" if args.limiar is None else "  (manual)"))
        idx = achar_eventos(tempos, dist, limiar)

    dados_existentes = {"gols": []}
    if os.path.exists(caminho_json):
        with open(caminho_json, encoding="utf-8-sig") as f:
            dados_existentes = json.load(f)
    existentes = dados_existentes.get("gols", [])
    indice_base = max([ev["indice"] for ev in existentes], default=0)

    eventos = []
    for k, i in enumerate(idx, 1):
        t = float(tempos[i])
        eventos.append({
            "indice": indice_base + k, "tempo_s": round(t, 2),
            "tempo": f"{int(t // 60):02d}:{int(t % 60):02d}",
            "inicio_s": round(max(t - ANTES_S, 0), 2), "fim_s": round(t + DEPOIS_S, 2),
            "forca": round(float(dist[i]), 4), "zona": int(zona_de[i]), "fonte": "zona",
        })

    print(f"\n{len(eventos)} jogadas detectadas por movimento nas zonas "
          f"(acrescentadas aos {len(existentes)} eventos ja existentes):\n")
    for ev in eventos:
        print(f"  #{ev['indice']:02d}  {ev['tempo']}  zona {ev['zona']}  forca {ev['forca']:.3f}   "
              f"corte {ev['inicio_s']:.1f}s -> {ev['fim_s']:.1f}s")

    ranking(tempos, dist, os.path.join(args.output_dir, "ranking_picos_zonas.txt"), limiar, ruido)

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump({"video": os.path.basename(args.source_video_path), "fps": fps,
                   "fonte": "misto", "gols": existentes + eventos},
                  f, indent=2, ensure_ascii=False)

    print("\nCONFIRA cada clipe novo no passo 4 do assistente (ou assistindo o arquivo direto) -")
    print("movimento na zona erra mais que o placar: jogador passando perto ou goleiro se")
    print("mexendo tambem disparam. Ajuste --limiar (ranking_picos_zonas.txt tem os 40")
    print("maiores picos) ou --eventos <numero de jogadas esperado> e rode de novo.")


if __name__ == "__main__":
    main()
