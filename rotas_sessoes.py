"""Rotas HTTP para criar e administrar as sessões do fut-bin."""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

import gerenciador_sessoes

router = APIRouter()


class CriarSessaoBody(BaseModel):
    nome: Optional[str] = None
    reaproveitar_times: bool = True


class RenomearSessaoBody(BaseModel):
    nome: str


class DuplicarSessaoBody(BaseModel):
    nome: Optional[str] = None


def _verificar_sem_processamento(request: Request, acao: str) -> None:
    jobs = list(request.app.state.jobs.values()) + list(request.app.state.sync_jobs.values())
    ocupados = [job for job in jobs if job.get("status") in ("running", "queued", "executando")]
    if ocupados:
        raise HTTPException(409, f"Há um processamento em andamento. Aguarde antes de {acao}.")


@router.get("/api/sessoes")
def api_sessoes_listar():
    return {
        "sessao_ativa_id": gerenciador_sessoes.obter_id_sessao_ativa(),
        "sessoes": gerenciador_sessoes.listar_sessoes(),
    }


@router.post("/api/sessoes/criar")
def api_sessoes_criar(request: Request, body: CriarSessaoBody = Body(default_factory=CriarSessaoBody)):
    _verificar_sem_processamento(request, "criar outra sessão")
    try:
        sessao = gerenciador_sessoes.criar_nova_sessao(nome=body.nome, reaproveitar_times=body.reaproveitar_times)
        request.app.state.duracao_cache.clear()
        return {"ok": True, "sessao": sessao}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/sessoes/{sessao_id}/ativar")
def api_sessoes_ativar(sessao_id: str, request: Request):
    _verificar_sem_processamento(request, "trocar de sessão")
    try:
        sessao = gerenciador_sessoes.ativar_sessao(sessao_id)
        request.app.state.duracao_cache.clear()
        return {"ok": True, "sessao": sessao}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/sessoes/{sessao_id}/renomear")
def api_sessoes_renomear(sessao_id: str, body: RenomearSessaoBody):
    try:
        sessao = gerenciador_sessoes.renomear_sessao(sessao_id, body.nome)
        return {"ok": True, "sessao": sessao}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/sessoes/{sessao_id}/duplicar")
def api_sessoes_duplicar(sessao_id: str, body: DuplicarSessaoBody = Body(default_factory=DuplicarSessaoBody)):
    try:
        sessao = gerenciador_sessoes.duplicar_sessao(sessao_id, body.nome)
        return {"ok": True, "sessao": sessao}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.delete("/api/sessoes/{sessao_id}")
def api_sessoes_excluir(sessao_id: str):
    try:
        return gerenciador_sessoes.excluir_sessao(sessao_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/sessoes/salvar")
def api_sessoes_salvar():
    try:
        gerenciador_sessoes.salvar_sessao_atual()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))
