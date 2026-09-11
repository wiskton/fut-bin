"""
diagnosticar_placar.py - mostra o que a camera realmente registra na regiao do placar.

Gera duas coisas:
  filmstrip_placar.png - o recorte do placar a cada N segundos, ampliado e datado
  curva_placar.png     - distancia da assinatura ao longo do tempo

Rode:
    python diagnosticar_placar.py --source_video_path data/pelada_5min.mp4

O que procurar no filmstrip:
  - os digitos estao legiveis e estaveis?  -> problema e de limiar
  - somem/piscam entre um quadro e outro?  -> LED multiplexado, precisa de media temporal
  - a regiao esta cortada ou inclui o cronometro? -> refazer o --pick_placar
"""

import argparse
import json
import os

import cv2
import numpy as np
from tqdm import tqdm

SIG_W, SIG_H = 48, 16


def assinatura(crop):
    b, g, r = cv2.split(crop.astype(np.int16))
    realce = np.clip(r - np.maximum(g, b), 0, 255).astype(np.uint8)
    realce = cv2.resize(realce, (SIG_W, SIG_H), interpolation=cv2.INTER_AREA)
    if realce.max() < 12:
        return None
    realce = cv2.normalize(realce, None, 0, 255, cv2.NORM_MINMAX)
    _, bina = cv2.threshold(realce, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bina > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source_video_path", required=True)
    ap.add_argument("--placar_file", default="placar.json")
    ap.add_argument("--intervalo", type=float, default=5.0,
                    help="segundos entre quadros do filmstrip")
    ap.add_argument("--media", type=int, default=1,
                    help="quantos frames consecutivos mediar (1 = sem media)")
    ap.add_argument("--zoom", type=int, default=6)
    args = ap.parse_args()

    if not os.path.exists(args.placar_file):
        print(f"{args.placar_file} nao encontrado. Rode detectar_gols.py --pick_placar antes.")
        return
    with open(args.placar_file, encoding="utf-8") as f:
        x, y, w, h = json.load(f)["placar"]

    print(f"regiao do placar: {w}x{h} pixels", end="")
    if w * h < 2000:
        print("  <-- PEQUENA. Marque uma area maior, com folga em volta dos digitos.")
    else:
        print()

    cap = cv2.VideoCapture(args.source_video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    passo_tira = max(int(round(args.intervalo * fps)), 1)
    tira, buffer, curva, anterior = [], [], [], None

    with tqdm(total=total, desc="lendo") as barra:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            barra.update(1)
            crop = frame[y:y + h, x:x + w].astype(np.float32)

            buffer.append(crop)
            if len(buffer) > args.media:
                buffer.pop(0)
            suave = np.mean(buffer, axis=0).astype(np.uint8)

            sig = assinatura(suave)
            if sig is None:
                curva.append((i / fps, np.nan))
            else:
                d = np.nan if anterior is None else float(np.mean(sig != anterior))
                curva.append((i / fps, d))
                anterior = sig

            if i % passo_tira == 0 and len(tira) < 60:
                amp = cv2.resize(suave, None, fx=args.zoom, fy=args.zoom,
                                 interpolation=cv2.INTER_NEAREST)
                amp = cv2.copyMakeBorder(amp, 20, 4, 4, 4, cv2.BORDER_CONSTANT,
                                         value=(20, 20, 20))
                t = i / fps
                cv2.putText(amp, f"{int(t // 60):02d}:{int(t % 60):02d}", (5, 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                tira.append(amp)
            i += 1
    cap.release()

    if tira:
        larg = max(t.shape[1] for t in tira)
        alt = max(t.shape[0] for t in tira)
        tira = [cv2.copyMakeBorder(t, 0, alt - t.shape[0], 0, larg - t.shape[1],
                                   cv2.BORDER_CONSTANT, value=(20, 20, 20)) for t in tira]
        por_linha = 10
        linhas = [np.hstack(tira[k:k + por_linha]) for k in range(0, len(tira), por_linha)]
        largura = max(l.shape[1] for l in linhas)
        linhas = [cv2.copyMakeBorder(l, 0, 0, 0, largura - l.shape[1],
                                     cv2.BORDER_CONSTANT, value=(20, 20, 20)) for l in linhas]
        cv2.imwrite("filmstrip_placar.png", np.vstack(linhas))
        print(f"filmstrip_placar.png  ({len(tira)} quadros)")

    arr = np.array([d for _, d in curva], dtype=np.float32)
    validos = arr[~np.isnan(arr)]
    if len(validos):
        print("\n=== ESTABILIDADE DA ASSINATURA ===")
        print(f"frames legiveis.............: {len(validos)} de {len(arr)}")
        print(f"distancia mediana entre frames: {np.median(validos):.4f}")
        print(f"percentil 95................: {np.percentile(validos, 95):.4f}")
        print(f"frames acima do limiar 0.06.: {int((validos > 0.06).sum())} "
              f"({100 * (validos > 0.06).mean():.1f}%)")
        print("\nLEITURA: com o placar parado, a mediana deveria ser ~0.000 e quase")
        print("nenhum frame acima do limiar. Se muitos passam, a assinatura esta")
        print("instavel - rode de novo com --media 15 e compare os numeros.")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        t = np.array([tt for tt, _ in curva])
        fig, ax = plt.subplots(figsize=(14, 3.2))
        ax.plot(t, arr, lw=0.7)
        ax.axhline(0.06, color="r", ls="--", lw=1, label="limiar atual (0.06)")
        ax.set_xlabel("tempo (s)")
        ax.set_ylabel("distancia")
        ax.set_title(f"Estabilidade do placar (media temporal = {args.media} frames)")
        ax.legend()
        fig.tight_layout()
        fig.savefig("curva_placar.png", dpi=110)
        print("curva_placar.png")
    except Exception as e:
        print(f"(curva nao gerada: {e})")


if __name__ == "__main__":
    main()
