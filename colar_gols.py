"""Lê o texto colado na tela de detectar e transforma cada horário em um corte.

Os tempos do texto são o relógio do jogo. inicio_jogo_s é o instante do arquivo
em que esse relógio está em 0:00 (a gravação pode começar aos 3 minutos).
O clipe começa antes_s antes do horário já convertido e termina depois_s depois.
"""

from __future__ import annotations

import re

_SECAO = re.compile(r"^(GOLS|OUTROS\s+LANCES)\s*-\s*(.+)$", re.IGNORECASE)
_PLACAR = re.compile(r"^(.+?)\s+(\d+)\s*x\s*(\d+)\s+(.+)$", re.IGNORECASE)
_DURACAO = re.compile(r"^Dura[cç][aã]o\s*:\s*(\S+)", re.IGNORECASE)
_JA_MENOS = re.compile(r"(\d+)\s*s\s+a\s+menos", re.IGNORECASE)
_TEMPO = re.compile(r"^(\d{1,3}):(\d{2})(?::(\d{2}))?$")
_NENHUM = re.compile(r"^\(?nenhum\)?$", re.IGNORECASE)


def _tempo_para_segundos(texto: str):
    m = _TEMPO.match(texto.strip())
    if not m:
        return None
    if m.group(3) is not None:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return int(m.group(1)) * 60 + int(m.group(2))


def _fmt(segundos: float) -> str:
    segundos = max(0, int(round(segundos)))
    return f"{segundos // 60:02d}:{segundos % 60:02d}"


def parse_texto_gols(texto: str) -> dict:
    times = []
    placar = None
    duracao = None
    aviso_ajuste_s = None
    eventos = []
    secao = None
    time_idx = None
    time_nome = None

    for bruta in (texto or "").splitlines():
        linha = bruta.strip().replace("–", "-").replace("—", "-")
        if not linha:
            continue
        aviso = _JA_MENOS.search(linha)
        if aviso and aviso_ajuste_s is None:
            aviso_ajuste_s = int(aviso.group(1))
        sec = _SECAO.match(linha)
        if sec:
            secao = "gol" if sec.group(1).upper().startswith("GOLS") else "lance"
            time_nome = sec.group(2).strip()
            chave = time_nome.casefold()
            if chave not in [n.casefold() for n in times]:
                times.append(time_nome)
            time_idx = next(i for i, n in enumerate(times) if n.casefold() == chave)
            continue
        if secao is None:
            placar_m = _PLACAR.match(linha)
            if placar_m:
                esq, g_a, g_b, dire = placar_m.groups()
                times = [esq.strip(), dire.strip()]
                placar = [int(g_a), int(g_b)]
                continue
            dur_m = _DURACAO.match(linha)
            if dur_m:
                duracao = dur_m.group(1)
            continue
        if _NENHUM.match(linha):
            continue
        segundos = _tempo_para_segundos(linha)
        if segundos is None:
            continue
        eventos.append({
            "tipo": secao,
            "time": time_idx,
            "time_nome": time_nome,
            "tempo_jogo": linha,
            "tempo_jogo_s": segundos,
        })

    return {
        "times": times[:2],
        "placar": placar,
        "duracao": duracao,
        "aviso_ajuste_s": aviso_ajuste_s,
        "eventos": eventos,
    }


def montar_cortes(eventos: list, inicio_jogo_s: float, antes_s: float, depois_s: float) -> list:
    inicio_jogo_s = max(0.0, float(inicio_jogo_s or 0))
    antes_s = min(180.0, max(0.0, float(antes_s)))
    depois_s = min(180.0, max(0.0, float(depois_s)))
    cortes = []
    for ev in eventos:
        tempo_video = float(ev["tempo_jogo_s"]) + inicio_jogo_s
        if tempo_video < 0:
            continue
        inicio = max(0.0, tempo_video - antes_s)
        fim = tempo_video + depois_s
        if fim <= inicio:
            fim = inicio + 1.0
        item = dict(ev)
        item.update({
            "tempo_s": round(tempo_video, 2),
            "tempo": ev.get("tempo_jogo") or _fmt(ev["tempo_jogo_s"]),
            "inicio_s": round(inicio, 2),
            "fim_s": round(fim, 2),
        })
        cortes.append(item)
    return cortes
