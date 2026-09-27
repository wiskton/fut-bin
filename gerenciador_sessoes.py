"""
gerenciador_sessoes.py - Gerenciamento de múltiplas sessões / projetos de vídeo para o fut-bin.

Permite manter sessões separadas para cortar mais de um vídeo sem perder o histórico,
gols, clipes, placar e marcações de partidas anteriores.

Cada sessão guarda:
  - partida.json (vídeo, câmeras, times, elenco, placar final, lances/gols e roteiro)
  - placar.json (coordenadas do retângulo do placar calibradas para aquele vídeo)
  - zonas.json (regiões dos dígitos/placar)
  - gols/ (gols.json, clipes/ em MP4, imagens de contato/diagnóstico)
  - final/ (melhores_momentos.mp4, apenas_gols.mp4)
  - videos_jogadores/ (destaques individuais)
  - sessao.json (metadados da sessão: nome, data, vídeo, contagem de gols/clipes)

A sessão ATIVA fica nos arquivos raiz do projeto (PROJECT_DIR), garantindo compatibilidade
100% transparente com todos os scripts CLI e endpoints existentes. Ao alternar entre
sessões, os dados da sessão atual são salvos e os da sessão escolhida são restaurados
instantaneamente.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSOES_DIR = os.path.join(PROJECT_DIR, "sessoes")
INDEX_FILE = os.path.join(SESSOES_DIR, "sessoes.json")
ATIVA_FILE = os.path.join(SESSOES_DIR, "sessao_ativa.txt")

# Arquivos e pastas pertencentes à sessão ativa
PARTIDA_JSON = os.path.join(PROJECT_DIR, "partida.json")
PLACAR_FILE = os.path.join(PROJECT_DIR, "placar.json")
ZONAS_FILE = os.path.join(PROJECT_DIR, "zonas.json")
GOLS_DIR = os.path.join(PROJECT_DIR, "gols")
GOLS_JSON = os.path.join(GOLS_DIR, "gols.json")
CLIPES_DIR = os.path.join(GOLS_DIR, "clipes")
FINAL_DIR = os.path.join(PROJECT_DIR, "final")
PLAYER_VIDEOS_DIR = os.path.join(PROJECT_DIR, "videos_jogadores")


def _agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _garantir_pasta_sessoes():
    os.makedirs(SESSOES_DIR, exist_ok=True)


def _ler_json_seguro(caminho: str) -> dict:
    if not os.path.isfile(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _gravar_json_atomico(caminho: str, dados: Any):
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    tmp = caminho + f".tmp_{uuid.uuid4().hex[:6]}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def obter_id_sessao_ativa() -> str:
    _garantir_pasta_sessoes()
    if os.path.isfile(ATIVA_FILE):
        try:
            with open(ATIVA_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass
    return "sessao_padrao"


def definir_id_sessao_ativa(sessao_id: str):
    _garantir_pasta_sessoes()
    with open(ATIVA_FILE, "w", encoding="utf-8") as f:
        f.write(sessao_id.strip())


def _extrair_resumo_raiz() -> dict:
    """Extrai métricas e metadados da sessão que está atualmente na raiz do projeto."""
    partida = _ler_json_seguro(PARTIDA_JSON)
    meta = partida.get("meta") or {}
    times = partida.get("times") or []

    video_caminho = meta.get("video") or ""
    video_nome = os.path.basename(video_caminho) if video_caminho else ""

    # Contagem de gols em gols/gols.json ou partida.json
    n_gols = 0
    if os.path.isfile(GOLS_JSON):
        gols_data = _ler_json_seguro(GOLS_JSON)
        n_gols = len(gols_data.get("gols") or [])
    elif "lances" in partida or "gols" in partida:
        n_gols = len(partida.get("lances") or partida.get("gols") or [])

    # Contagem de clipes MP4
    n_clipes = 0
    if os.path.isdir(CLIPES_DIR):
        n_clipes = len([f for f in os.listdir(CLIPES_DIR) if f.lower().endswith(".mp4")])

    placar_ok = os.path.isfile(PLACAR_FILE)
    final_ok = os.path.isfile(os.path.join(FINAL_DIR, "melhores_momentos.mp4")) or os.path.isfile(os.path.join(FINAL_DIR, "apenas_gols.mp4"))

    # Gera um nome amigável a partir da partida
    pelada = meta.get("pelada") or meta.get("torneio") or ""
    comp = meta.get("comp") or meta.get("rodada") or ""
    placar_j = meta.get("placar_jogo") or []
    placar_str = f" ({placar_j[0]}x{placar_j[1]})" if len(placar_j) >= 2 and (placar_j[0] or placar_j[1]) else ""

    partes = [str(x).strip() for x in (pelada, comp) if str(x or "").strip()]
    if partes:
        nome_sugerido = " - ".join(partes) + placar_str
    elif video_nome:
        nome_sugerido = f"Partida: {video_nome}"
    else:
        nome_sugerido = "Sessão Inicial"

    return {
        "nome_sugerido": nome_sugerido,
        "video": video_caminho,
        "video_nome": video_nome,
        "pelada": pelada,
        "comp": comp,
        "data": meta.get("data") or "",
        "placar_jogo": placar_j,
        "times": [t.get("nome", "") for t in times if isinstance(t, dict)],
        "n_gols": n_gols,
        "n_clipes": n_clipes,
        "placar_ok": placar_ok,
        "final_ok": final_ok,
    }


def _carregar_indice_sessoes() -> List[dict]:
    _garantir_pasta_sessoes()
    dados = _ler_json_seguro(INDEX_FILE)
    sessoes = dados.get("sessoes")
    if isinstance(sessoes, list):
        return sessoes
    return []


def _salvar_indice_sessoes(sessoes: List[dict]):
    _garantir_pasta_sessoes()
    _gravar_json_atomico(INDEX_FILE, {"sessoes": sessoes, "atualizado_em": _agora_iso()})


def inicializar() -> dict:
    """Inicializa o sistema de sessões.
    Se nenhuma sessão existir ainda, cria a Sessão #1 espelhando os arquivos atuais
    da raiz (sem mover nada da raiz, preservando tudo intacto!).
    """
    _garantir_pasta_sessoes()
    sessoes = _carregar_indice_sessoes()
    id_ativa = obter_id_sessao_ativa()

    if not sessoes:
        # Cria a primeira sessão a partir do que já existe na raiz
        resumo = _extrair_resumo_raiz()
        sessao_id = f"sessao_{int(time.time())}"
        nome = resumo["nome_sugerido"]

        pasta_sessao = os.path.join(SESSOES_DIR, sessao_id)
        os.makedirs(pasta_sessao, exist_ok=True)

        meta_sessao = {
            "id": sessao_id,
            "nome": nome,
            "video": resumo["video"],
            "video_nome": resumo["video_nome"],
            "pelada": resumo["pelada"],
            "comp": resumo["comp"],
            "data": resumo["data"],
            "n_gols": resumo["n_gols"],
            "n_clipes": resumo["n_clipes"],
            "placar_ok": resumo["placar_ok"],
            "final_ok": resumo["final_ok"],
            "criado_em": _agora_iso(),
            "atualizado_em": _agora_iso(),
            "status": "em_andamento",
        }
        _gravar_json_atomico(os.path.join(pasta_sessao, "sessao.json"), meta_sessao)

        # Copia cópia de segurança dos JSONs atuais para a pasta da sessão
        for origem, nome_arq in [(PARTIDA_JSON, "partida.json"),
                                 (PLACAR_FILE, "placar.json"),
                                 (ZONAS_FILE, "zonas.json")]:
            if os.path.isfile(origem):
                try:
                    shutil.copy2(origem, os.path.join(pasta_sessao, nome_arq))
                except Exception:
                    pass

        if os.path.isfile(GOLS_JSON):
            gols_dest = os.path.join(pasta_sessao, "gols")
            os.makedirs(gols_dest, exist_ok=True)
            try:
                shutil.copy2(GOLS_JSON, os.path.join(gols_dest, "gols.json"))
            except Exception:
                pass

        sessoes = [meta_sessao]
        _salvar_indice_sessoes(sessoes)
        definir_id_sessao_ativa(sessao_id)
        id_ativa = sessao_id

    # Garante que a sessão ativa existe no índice
    encontrou_ativa = any(s.get("id") == id_ativa for s in sessoes)
    if not encontrou_ativa and sessoes:
        id_ativa = sessoes[0].get("id")
        definir_id_sessao_ativa(id_ativa)

    return {"sessao_ativa_id": id_ativa, "total_sessoes": len(sessoes)}


def salvar_sessao_atual():
    """Salva / sincroniza os dados da sessão ativa para sua pasta em sessoes/<id>/
    e atualiza as métricas no sessoes.json.
    """
    _garantir_pasta_sessoes()
    sessao_id = obter_id_sessao_ativa()
    pasta_sessao = os.path.join(SESSOES_DIR, sessao_id)
    os.makedirs(pasta_sessao, exist_ok=True)

    # 1. Copia JSONs principais
    for origem, nome_arq in [(PARTIDA_JSON, "partida.json"),
                             (PLACAR_FILE, "placar.json"),
                             (ZONAS_FILE, "zonas.json")]:
        destino = os.path.join(pasta_sessao, nome_arq)
        if os.path.isfile(origem):
            try:
                shutil.copy2(origem, destino)
            except Exception:
                pass
        elif os.path.isfile(destino):
            try:
                os.remove(destino)
            except OSError:
                pass

    # 2. Copia gols.json se existir
    if os.path.isfile(GOLS_JSON):
        gols_dest = os.path.join(pasta_sessao, "gols")
        os.makedirs(gols_dest, exist_ok=True)
        try:
            shutil.copy2(GOLS_JSON, os.path.join(gols_dest, "gols.json"))
        except Exception:
            pass

    # 3. Atualiza metadados no índice
    resumo = _extrair_resumo_raiz()
    sessoes = _carregar_indice_sessoes()
    for s in sessoes:
        if s.get("id") == sessao_id:
            s["video"] = resumo["video"]
            s["video_nome"] = resumo["video_nome"]
            s["pelada"] = resumo["pelada"]
            s["comp"] = resumo["comp"]
            s["data"] = resumo["data"]
            s["n_gols"] = resumo["n_gols"]
            s["n_clipes"] = resumo["n_clipes"]
            s["placar_ok"] = resumo["placar_ok"]
            s["final_ok"] = resumo["final_ok"]
            s["atualizado_em"] = _agora_iso()
            _gravar_json_atomico(os.path.join(pasta_sessao, "sessao.json"), s)
            break

    _salvar_indice_sessoes(sessoes)


def _trocar_pastas_sessao(sessao_saindo_id: str, sessao_entrando_id: str):
    """Executa a movimentação atômica e ultrarrápida dos diretórios pesados
    (gols, final, videos_jogadores) e JSONs entre a raiz e a pasta de cada sessão.
    """
    pasta_saindo = os.path.join(SESSOES_DIR, sessao_saindo_id)
    pasta_entrando = os.path.join(SESSOES_DIR, sessao_entrando_id)
    os.makedirs(pasta_saindo, exist_ok=True)
    os.makedirs(pasta_entrando, exist_ok=True)

    # 1. Guarda tudo o que pertence à sessão que está SAINDO da raiz
    # Move gols/
    if os.path.isdir(GOLS_DIR):
        dest_gols = os.path.join(pasta_saindo, "gols")
        if os.path.exists(dest_gols):
            shutil.rmtree(dest_gols, ignore_errors=True)
        os.rename(GOLS_DIR, dest_gols)

    # Move final/
    if os.path.isdir(FINAL_DIR):
        dest_final = os.path.join(pasta_saindo, "final")
        if os.path.exists(dest_final):
            shutil.rmtree(dest_final, ignore_errors=True)
        os.rename(FINAL_DIR, dest_final)

    # Move videos_jogadores/
    if os.path.isdir(PLAYER_VIDEOS_DIR):
        dest_jogadores = os.path.join(pasta_saindo, "videos_jogadores")
        if os.path.exists(dest_jogadores):
            shutil.rmtree(dest_jogadores, ignore_errors=True)
        os.rename(PLAYER_VIDEOS_DIR, dest_jogadores)

    # Copia os JSONs para a pasta saindo
    for raiz_arq, nome_arq in [(PARTIDA_JSON, "partida.json"),
                               (PLACAR_FILE, "placar.json"),
                               (ZONAS_FILE, "zonas.json")]:
        dest_arq = os.path.join(pasta_saindo, nome_arq)
        if os.path.isfile(raiz_arq):
            try:
                shutil.copy2(raiz_arq, dest_arq)
                os.remove(raiz_arq)
            except OSError:
                pass
        elif os.path.isfile(dest_arq):
            try:
                os.remove(dest_arq)
            except OSError:
                pass

    # 2. Restaura o que pertence à sessão que está ENTRANDO na raiz
    # Move ou cria gols/
    src_gols = os.path.join(pasta_entrando, "gols")
    if os.path.isdir(src_gols):
        os.rename(src_gols, GOLS_DIR)
    else:
        os.makedirs(CLIPES_DIR, exist_ok=True)

    # Move ou cria final/
    src_final = os.path.join(pasta_entrando, "final")
    if os.path.isdir(src_final):
        os.rename(src_final, FINAL_DIR)
    else:
        os.makedirs(FINAL_DIR, exist_ok=True)

    # Move ou cria videos_jogadores/
    src_jogadores = os.path.join(pasta_entrando, "videos_jogadores")
    if os.path.isdir(src_jogadores):
        os.rename(src_jogadores, PLAYER_VIDEOS_DIR)
    else:
        os.makedirs(PLAYER_VIDEOS_DIR, exist_ok=True)

    # Restaura JSONs
    src_partida = os.path.join(pasta_entrando, "partida.json")
    if os.path.isfile(src_partida):
        shutil.copy2(src_partida, PARTIDA_JSON)

    src_placar = os.path.join(pasta_entrando, "placar.json")
    if os.path.isfile(src_placar):
        shutil.copy2(src_placar, PLACAR_FILE)
    elif os.path.isfile(PLACAR_FILE):
        try:
            os.remove(PLACAR_FILE)
        except OSError:
            pass

    src_zonas = os.path.join(pasta_entrando, "zonas.json")
    if os.path.isfile(src_zonas):
        shutil.copy2(src_zonas, ZONAS_FILE)
    elif os.path.isfile(ZONAS_FILE):
        try:
            os.remove(ZONAS_FILE)
        except OSError:
            pass


def listar_sessoes() -> List[dict]:
    """Retorna todas as sessões cadastradas com seus detalhes e status."""
    inicializar()
    id_ativa = obter_id_sessao_ativa()
    sessoes = _carregar_indice_sessoes()

    # Atualiza as métricas da ativa em tempo real
    resumo_ativa = _extrair_resumo_raiz()

    resultado = []
    for s in sessoes:
        item = dict(s)
        is_ativa = (s.get("id") == id_ativa)
        item["is_ativa"] = is_ativa
        if is_ativa:
            item["n_gols"] = resumo_ativa["n_gols"]
            item["n_clipes"] = resumo_ativa["n_clipes"]
            item["placar_ok"] = resumo_ativa["placar_ok"]
            item["final_ok"] = resumo_ativa["final_ok"]
            item["video"] = resumo_ativa["video"]
            item["video_nome"] = resumo_ativa["video_nome"]
        resultado.append(item)

    # Ordena: sessão ativa primeiro, depois as demais por data de atualização decrescente
    resultado.sort(key=lambda x: (not x.get("is_ativa", False), x.get("atualizado_em", "")), reverse=True)
    return resultado


def obter_sessao(sessao_id: str) -> Optional[dict]:
    for s in listar_sessoes():
        if s.get("id") == sessao_id:
            return s
    return None


def criar_nova_sessao(nome: Optional[str] = None, reaproveitar_times: bool = True) -> dict:
    """Cria uma nova sessão de vídeo.
    1. Salva a sessão atual completamente para não perder nada.
    2. Gera nova sessão limpa (ou com times/campeonato reaproveitados se solicitado).
    3. Ativa a nova sessão imediatamente.
    """
    inicializar()
    id_anterior = obter_id_sessao_ativa()

    # Salva a anterior
    salvar_sessao_atual()

    # Gera id único
    timestamp = int(time.time())
    novo_id = f"sessao_{timestamp}"

    # Carrega dados a reaproveitar se solicitado
    times = []
    meta_base = {}
    if reaproveitar_times and os.path.isfile(PARTIDA_JSON):
        partida_antiga = _ler_json_seguro(PARTIDA_JSON)
        times = partida_antiga.get("times") or []
        meta_antiga = partida_antiga.get("meta") or {}
        for k in ("pelada", "comp", "local", "torneio"):
            if k in meta_antiga:
                meta_base[k] = meta_antiga[k]

    if not nome or not str(nome).strip():
        data_hoje = datetime.date.today().strftime("%d/%m")
        nome = f"Nova Partida ({data_hoje})"

    nome = str(nome).strip()

    nova_meta = {
        "id": novo_id,
        "nome": nome,
        "video": "",
        "video_nome": "",
        "pelada": meta_base.get("pelada", ""),
        "comp": meta_base.get("comp", ""),
        "data": datetime.date.today().isoformat(),
        "n_gols": 0,
        "n_clipes": 0,
        "placar_ok": False,
        "final_ok": False,
        "criado_em": _agora_iso(),
        "atualizado_em": _agora_iso(),
        "status": "em_andamento",
    }

    pasta_nova = os.path.join(SESSOES_DIR, novo_id)
    os.makedirs(pasta_nova, exist_ok=True)
    _gravar_json_atomico(os.path.join(pasta_nova, "sessao.json"), nova_meta)

    # Cria partida.json inicial na pasta da nova sessão
    partida_inicial = {
        "meta": {
            **meta_base,
            "data": datetime.date.today().isoformat(),
            "video": "",
            "placar_jogo": [0, 0],
            "cameras": [],
            "camera_placar": 0,
        },
        "times": times,
        "lances": [],
        "gols": [],
        "roteiro": [],
    }
    _gravar_json_atomico(os.path.join(pasta_nova, "partida.json"), partida_inicial)

    # Adiciona ao índice
    sessoes = _carregar_indice_sessoes()
    sessoes.append(nova_meta)
    _salvar_indice_sessoes(sessoes)

    # Executa a troca para a nova sessão
    _trocar_pastas_sessao(id_anterior, novo_id)
    definir_id_sessao_ativa(novo_id)

    return nova_meta


def ativar_sessao(sessao_id: str) -> dict:
    """Alterna para uma sessão existente.
    Salva a sessão atual e restaura a sessão de destino instantaneamente.
    """
    inicializar()
    id_atual = obter_id_sessao_ativa()

    if id_atual == sessao_id:
        return obter_sessao(sessao_id) or {}

    sessoes = _carregar_indice_sessoes()
    alvo = next((s for s in sessoes if s.get("id") == sessao_id), None)
    if not alvo:
        raise ValueError(f"Sessão não encontrada: {sessao_id}")

    # Salva a atual
    salvar_sessao_atual()

    # Troca as pastas
    _trocar_pastas_sessao(id_atual, sessao_id)
    definir_id_sessao_ativa(sessao_id)

    # Atualiza timestamp
    alvo["atualizado_em"] = _agora_iso()
    _salvar_indice_sessoes(sessoes)

    return obter_sessao(sessao_id) or alvo


def renomear_sessao(sessao_id: str, novo_nome: str) -> dict:
    inicializar()
    novo_nome = str(novo_nome).strip()
    if not novo_nome:
        raise ValueError("O nome da sessão não pode ser vazio.")

    sessoes = _carregar_indice_sessoes()
    alvo = next((s for s in sessoes if s.get("id") == sessao_id), None)
    if not alvo:
        raise ValueError(f"Sessão não encontrada: {sessao_id}")

    alvo["nome"] = novo_nome
    alvo["atualizado_em"] = _agora_iso()
    _salvar_indice_sessoes(sessoes)

    pasta_sessao = os.path.join(SESSOES_DIR, sessao_id)
    if os.path.isdir(pasta_sessao):
        _gravar_json_atomico(os.path.join(pasta_sessao, "sessao.json"), alvo)

    return obter_sessao(sessao_id) or alvo


def duplicar_sessao(sessao_id: str, novo_nome: Optional[str] = None) -> dict:
    """Duplica uma sessão para permitir testes ou cortes alternativos."""
    inicializar()
    salvar_sessao_atual()

    origem_meta = obter_sessao(sessao_id)
    if not origem_meta:
        raise ValueError(f"Sessão não encontrada: {sessao_id}")

    novo_id = f"sessao_{int(time.time())}"
    if not novo_nome:
        novo_nome = f"{origem_meta.get('nome', 'Sessão')} (Cópia)"

    nova_meta = dict(origem_meta)
    nova_meta["id"] = novo_id
    nova_meta["nome"] = novo_nome
    nova_meta["criado_em"] = _agora_iso()
    nova_meta["atualizado_em"] = _agora_iso()
    nova_meta["is_ativa"] = False

    pasta_origem = os.path.join(SESSOES_DIR, sessao_id)
    pasta_nova = os.path.join(SESSOES_DIR, novo_id)
    os.makedirs(pasta_nova, exist_ok=True)

    # Copia arquivos da sessão
    for arq in ("sessao.json", "partida.json", "placar.json", "zonas.json"):
        p = os.path.join(pasta_origem, arq)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(pasta_nova, arq))

    _gravar_json_atomico(os.path.join(pasta_nova, "sessao.json"), nova_meta)

    # Copia gols/ e clipes se existirem na pasta da sessão
    gols_origem = os.path.join(pasta_origem, "gols")
    if os.path.isdir(gols_origem):
        shutil.copytree(gols_origem, os.path.join(pasta_nova, "gols"), dirs_exist_ok=True)

    sessoes = _carregar_indice_sessoes()
    sessoes.append(nova_meta)
    _salvar_indice_sessoes(sessoes)

    return nova_meta


def excluir_sessao(sessao_id: str) -> dict:
    """Exclui uma sessão e seus clipes/dados salvos."""
    inicializar()
    id_ativa = obter_id_sessao_ativa()

    if id_ativa == sessao_id:
        raise ValueError("Não é possível excluir a sessão ativa diretamente. Alterne para outra sessão antes de excluir.")

    sessoes = _carregar_indice_sessoes()
    sessoes_novas = [s for s in sessoes if s.get("id") != sessao_id]
    _salvar_indice_sessoes(sessoes_novas)

    pasta_sessao = os.path.join(SESSOES_DIR, sessao_id)
    if os.path.isdir(pasta_sessao):
        shutil.rmtree(pasta_sessao, ignore_errors=True)

    return {"ok": True, "excluido_id": sessao_id}
