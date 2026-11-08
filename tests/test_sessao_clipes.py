import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import assistente_web
import rotas_sessoes


class SessaoClipesTest(unittest.TestCase):
    def test_retry_da_criacao_reutiliza_a_sessao_da_mesma_solicitacao(self):
        rotas_sessoes._CRIAR_SESSAO_RESULTADOS.clear()
        sessao = {"id": "sessao_teste"}
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            jobs={}, sync_jobs={}, duracao_cache={"cache": 1})))
        body = rotas_sessoes.CriarSessaoBody(nome="Teste", request_id="acao-1")

        with mock.patch.object(rotas_sessoes.gerenciador_sessoes, "criar_nova_sessao", return_value=sessao) as criar:
            primeira = rotas_sessoes.api_sessoes_criar(request, body)
            segunda = rotas_sessoes.api_sessoes_criar(request, body)

        self.assertEqual(primeira, segunda)
        self.assertEqual(criar.call_count, 1)
        self.assertEqual(request.app.state.duracao_cache, {})
        rotas_sessoes._CRIAR_SESSAO_RESULTADOS.clear()

    def test_tombstone_remove_clipe_recriado_por_job_antigo(self):
        with tempfile.TemporaryDirectory() as pasta:
            clips = os.path.join(pasta, "gols", "clipes")
            os.makedirs(clips)
            caminho_clipe = os.path.join(clips, "gol_04.mp4")
            excluidos = os.path.join(pasta, "gols", "clipes_excluidos.json")

            with mock.patch.multiple(
                assistente_web,
                GOLS_DIR=os.path.join(pasta, "gols"),
                CLIPES_DIR=clips,
                EXCLUIDOS_JSON=excluidos,
                _arquivos_do_clipe=mock.Mock(return_value=[caminho_clipe]),
            ):
                assistente_web._gravar_excluidos({4})
                for _ in range(2):
                    with open(caminho_clipe, "wb") as arquivo:
                        arquivo.write(b"clipe")
                    encontrados = assistente_web._limpar_clipes_excluidos_pendentes({4})
                    self.assertEqual(encontrados, {4})
                    self.assertFalse(os.path.exists(caminho_clipe))
                    with open(excluidos, encoding="utf-8") as arquivo:
                        self.assertEqual(json.load(arquivo)["indices"], [4])

    def test_exclusao_registra_tombstone_apos_apagar_arquivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            gols = os.path.join(pasta, "gols")
            clips = os.path.join(gols, "clipes")
            os.makedirs(clips)
            caminho_clipe = os.path.join(clips, "gol_04.mp4")
            with open(caminho_clipe, "wb") as arquivo:
                arquivo.write(b"clipe")

            with mock.patch.multiple(
                assistente_web,
                GOLS_DIR=gols,
                CLIPES_DIR=clips,
                GOLS_JSON=os.path.join(gols, "gols.json"),
                PARTIDA_JSON=os.path.join(pasta, "partida.json"),
                EXCLUIDOS_JSON=os.path.join(gols, "clipes_excluidos.json"),
                _arquivos_do_clipe=mock.Mock(return_value=[caminho_clipe]),
            ):
                resposta = assistente_web.api_descartar_gol(
                    assistente_web.DescartarGol(indice=4))
                self.assertTrue(resposta["ok"])
                self.assertFalse(os.path.exists(caminho_clipe))
                self.assertEqual(assistente_web._ler_excluidos(), {4})

    def test_exclusao_remove_indice_de_todas_as_pastas_de_camera(self):
        with tempfile.TemporaryDirectory() as pasta:
            gols = os.path.join(pasta, "gols")
            clips = os.path.join(gols, "clipes")
            clips_cam2 = os.path.join(gols, "clipes_cam2")
            os.makedirs(clips)
            os.makedirs(clips_cam2)
            copias = [
                os.path.join(clips, "gol_20.mp4"),
                os.path.join(clips_cam2, "gol_020.mp4.corte"),
                os.path.join(clips_cam2, "gol_120.mp4"),
            ]
            for caminho in copias:
                with open(caminho, "wb") as arquivo:
                    arquivo.write(b"clipe")

            with mock.patch.multiple(
                assistente_web,
                GOLS_DIR=gols,
                CLIPES_DIR=clips,
                GOLS_JSON=os.path.join(gols, "gols.json"),
                PARTIDA_JSON=os.path.join(pasta, "partida.json"),
                EXCLUIDOS_JSON=os.path.join(gols, "clipes_excluidos.json"),
            ):
                resposta = assistente_web.api_descartar_gol(
                    assistente_web.DescartarGol(indice=20))

            self.assertTrue(resposta["ok"])
            self.assertFalse(os.path.exists(copias[0]))
            self.assertFalse(os.path.exists(copias[1]))
            self.assertTrue(os.path.exists(copias[2]))


if __name__ == "__main__":
    unittest.main()