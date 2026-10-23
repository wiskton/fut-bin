"""Helpers para salvar dados do projeto sem deixar arquivos parcialmente escritos."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def gravar_json_atomico(caminho: str, dados: Any, *, indent: int = 2) -> None:
    """Serializa JSON em arquivo temporário e o troca no destino atomicamente."""
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=".json-", suffix=".tmp", dir=pasta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=indent)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    except BaseException:
        try:
            os.unlink(temporario)
        except FileNotFoundError:
            pass
        raise
