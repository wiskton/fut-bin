"""A junção corta só a janela marcada, na ordem dos arquivos."""
import os
import shutil
import subprocess
import tempfile
import unittest

import juntar_videos as juntar


class JanelaPartidaTest(unittest.TestCase):
    def test_recorta_o_fim_do_primeiro_e_o_comeco_do_segundo(self):
        cortes = juntar.segmentos_da_janela([10, 10, 10], 8, 22)
        self.assertEqual(cortes, [
            {"indice": 0, "inicio": 8.0, "duracao": 2.0},
            {"indice": 1, "inicio": 0.0, "duracao": 10.0},
            {"indice": 2, "inicio": 0.0, "duracao": 2.0},
        ])

    def test_um_arquivo_so_usa_a_janela_interna(self):
        cortes = juntar.segmentos_da_janela([60], 5, 40)
        self.assertEqual(cortes, [{"indice": 0, "inicio": 5.0, "duracao": 35.0}])

    def test_fim_arredondado_alem_do_total_ainda_vale(self):
        cortes = juntar.segmentos_da_janela([10.04], 0, 10.1)
        self.assertEqual(cortes[0]["inicio"], 0.0)
        self.assertAlmostEqual(cortes[0]["duracao"], 10.04, places=2)

    def test_rejeita_janela_invertida(self):
        with self.assertRaises(ValueError):
            juntar.segmentos_da_janela([10, 10], 12, 12)

    def test_comando_de_um_trecho_nao_usa_concat(self):
        cmd = juntar.comando_juntar(
            [{"caminho": "a.mp4", "inicio": 1.5, "duracao": 8, "tem_audio": True}],
            "partida.mp4", 1920, 1080, "30/1", ["-c:v", "libx264"],
        )
        self.assertNotIn("-filter_complex", cmd)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "1.500")
        self.assertEqual(cmd[cmd.index("-t") + 1], "8.000")
        self.assertEqual(cmd[-1], "partida.mp4")

    def test_comando_de_varios_trechos_concatena_na_ordem(self):
        cmd = juntar.comando_juntar(
            [
                {"caminho": "a.mp4", "inicio": 4, "duracao": 6, "tem_audio": False},
                {"caminho": "b.mp4", "inicio": 0, "duracao": 9, "tem_audio": True},
            ],
            "partida.mp4", 1280, 720, "30/1", ["-c:v", "libx264"],
        )
        self.assertLess(cmd.index("a.mp4"), cmd.index("b.mp4"))
        filtro = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=2:v=1:a=1", filtro)
        self.assertIn("anullsrc=", filtro)
        self.assertIn("[1:a:0]", filtro)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requer FFmpeg")
class JuntarFfmpegTest(unittest.TestCase):
    def test_dois_arquivos_viram_so_a_partida(self):
        with tempfile.TemporaryDirectory(prefix="juntar_") as tmp:
            arquivos = []
            for indice, cor in enumerate(("red", "blue")):
                caminho = os.path.join(tmp, f"parte{indice}.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={cor}:s=320x180:r=30", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=44100", "-t", "2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", caminho,
                ], check=True)
                arquivos.append(caminho)
            saida = os.path.join(tmp, "partida.mp4")
            cmd = juntar.preparar(
                arquivos, 1.0, 3.0, saida,
                ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k"],
            )
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
            duracao = juntar.info_midia(saida)["duracao_s"]
            self.assertAlmostEqual(duracao, 2.0, delta=0.15)
            self.assertTrue(juntar.info_midia(saida)["tem_audio"])
