"""
folha_placar.py - gera folhas de contato do PLACAR ao longo do jogo.

POR QUE ISTO EXISTE:
  O placar ocupa ~24x20 pixels para quatro digitos, ou seja ~5 pixels por
  digito. Nesse tamanho, uma mudanca de gol mexe em menos pixels do que a
  compressao e a variacao de luz ao longo da tarde. Nenhum algoritmo de
  diferenca resolve isso - a informacao nao esta la em quantidade suficiente.

  Mas o olho humano le esse placar sem esforco. Entao em vez de tentar
  detectar, o script apresenta: uma grade com o placar a cada N segundos,
  ampliado e com a hora. Voce percorre e anota onde o numero muda.

USO:
    python folha_placar.py --source_video_path pelada2.mp4 --fim 58:23

    (revise as folhas, anote os tempos, e crie gols.txt com um por linha:
       03:12
       07:45
       ...)

    python folha_placar.py --source_video_path pelada2.mp4 --tempos gols.txt

  O segundo comando gera gols/gols.json no formato que o marcador.html le,
  e dai o corte segue igual:
    python detectar_gols.py --source_video_path pelada2.mp4 --cortar --output_dir gols

DICA: percorra olhando so o SEGUNDO numero de cada par. Quando ele mudar,
volte uma miniatura e anote o horario da PRIMEIRA que ja mostra o valor novo.
"""

import argparse
import json
import os

import cv2
import numpy as np
from tqdm import tqdm

ZOOM = 7           # ampliacao de cada miniatura
POR_LINHA = 8      # miniaturas por linha
MIN_POR_FOLHA = 10  # minutos de jogo por arquivo de folha
ANTES_S = 16.0
DEPOIS_S = 5.0


def parse_tempo(txt):
    if txt is None:
        return None
    txt = str(txt).strip()
    if not txt or txt.startswith("#"):
        return None
    if ":" not in txt:
        return float(txt)
    seg = 0.0
    for p in txt.split(":"):
        seg = seg * 60 + float(p)
    return seg


def load_placar(arquivo):
    with open(arquivo, encoding="utf-8-sig") as f:
        return json.load(f)["placar"]


def montar_folhas(video_path, rect, intervalo, inicio, fim, saida):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    x, y, w, h = rect

    ini_f = int((inicio or 0) * fps)
    fim_f = int(fim * fps) if fim else total
    passo = max(int(round(intervalo * fps)), 1)
    if ini_f:
        cap.set(cv2.CAP_PROP_POS_FRAMES, ini_f)

    os.makedirs(saida, exist_ok=True)
    celulas, folhas, i = [], 0, ini_f
    por_folha = int(MIN_POR_FOLHA * 60 / intervalo)

    def gravar(lista, numero):
        if not lista:
            return
        larg = max(c.shape[1] for c in lista)
        alt = max(c.shape[0] for c in lista)
        lista = [cv2.copyMakeBorder(c, 0, alt - c.shape[0], 0, larg - c.shape[1],
                                    cv2.BORDER_CONSTANT, value=(25, 25, 25)) for c in lista]
        linhas = [np.hstack(lista[k:k + POR_LINHA]) for k in range(0, len(lista), POR_LINHA)]
        maior = max(l.shape[1] for l in linhas)
        linhas = [cv2.copyMakeBorder(l, 0, 0, 0, maior - l.shape[1],
                                     cv2.BORDER_CONSTANT, value=(25, 25, 25)) for l in linhas]
        caminho = os.path.join(saida, f"folha_{numero:02d}.png")
        cv2.imwrite(caminho, np.vstack(linhas))
        print(f"  {caminho}  ({len(lista)} miniaturas)")

    with tqdm(total=(fim_f - ini_f) // passo, desc="montando folhas") as barra:
        while i < fim_f:
            ok = cap.grab()
            if not ok:
                break
            if (i - ini_f) % passo == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                barra.update(1)
                crop = frame[y:y + h, x:x + w]
                if crop.size:
                    amp = cv2.resize(crop, None, fx=ZOOM, fy=ZOOM,
                                     interpolation=cv2.INTER_NEAREST)
                    amp = cv2.copyMakeBorder(amp, 22, 5, 3, 3, cv2.BORDER_CONSTANT,
                                             value=(25, 25, 25))
                    t = i / fps
                    cv2.putText(amp, f"{int(t // 60):02d}:{int(t % 60):02d}", (5, 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    celulas.append(amp)
                    if len(celulas) >= por_folha:
                        folhas += 1
                        gravar(celulas, folhas)
                        celulas = []
            i += 1
    cap.release()
    if celulas:
        folhas += 1
        gravar(celulas, folhas)
    return folhas


def gerar_json(caminho_tempos, video_path, saida):
    with open(caminho_tempos, encoding="utf-8-sig") as f:
        tempos = [parse_tempo(l) for l in f]
    tempos = sorted(t for t in tempos if t is not None)
    if not tempos:
        print("nenhum tempo valido no arquivo.")
        return

    eventos = []
    for k, t in enumerate(tempos, 1):
        eventos.append({
            "indice": k,
            "tempo_s": round(t, 2),
            "tempo": f"{int(t // 60):02d}:{int(t % 60):02d}",
            "inicio_s": round(max(t - ANTES_S, 0), 2),
            "fim_s": round(t + DEPOIS_S, 2),
            "fonte": "manual",
        })
    os.makedirs(saida, exist_ok=True)
    destino = os.path.join(saida, "gols.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({"video": os.path.basename(video_path), "fonte": "manual",
                   "gols": eventos}, f, indent=2, ensure_ascii=False)
    print(f"{len(eventos)} gols gravados em {destino}")
    for ev in eventos:
        print(f"  #{ev['indice']:02d}  {ev['tempo']}   "
              f"corte {ev['inicio_s']:.0f}s -> {ev['fim_s']:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source_video_path", required=True)
    ap.add_argument("--placar_file", default="placar.json")
    ap.add_argument("--intervalo", type=float, default=10.0,
                    help="segundos entre miniaturas")
    ap.add_argument("--inicio", default=None)
    ap.add_argument("--fim", default=None)
    ap.add_argument("--tempos", default=None,
                    help="arquivo com os tempos anotados; gera o gols.json")
    ap.add_argument("--output_dir", default="gols")
    ap.add_argument("--folhas_dir", default="folhas")
    args = ap.parse_args()

    if args.tempos:
        gerar_json(args.tempos, args.source_video_path, args.output_dir)
        return

    rect = load_placar(args.placar_file)
    print(f"regiao do placar: {rect}  |  miniatura a cada {args.intervalo:.0f}s")
    n = montar_folhas(args.source_video_path, rect, args.intervalo,
                      parse_tempo(args.inicio), parse_tempo(args.fim), args.folhas_dir)
    print(f"\n{n} folhas em {os.path.abspath(args.folhas_dir)}")
    print("\nPercorra olhando so o SEGUNDO numero de cada par. Quando mudar,")
    print("anote o horario da PRIMEIRA miniatura que ja mostra o valor novo.")
    print("Junte os horarios num gols.txt (um por linha, formato mm:ss) e rode:")
    print(f"  python folha_placar.py --source_video_path {args.source_video_path} --tempos gols.txt")


if __name__ == "__main__":
    main()
