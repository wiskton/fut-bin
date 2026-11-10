import unittest

from colar_gols import montar_cortes, parse_texto_gols

TEXTO = """
Time A 7 x 8 Time B
Duração: 71:04
Tempos já com 20s a menos (início do lance)

GOLS - Time A
08:56
09:24

GOLS - Time B
02:50

OUTROS LANCES - Time A
(nenhum)

OUTROS LANCES - Time B
15:40
"""


class ColarGolsTest(unittest.TestCase):
    def test_separa_gols_e_lances_por_time(self):
        dados = parse_texto_gols(TEXTO)
        self.assertEqual(dados["times"], ["Time A", "Time B"])
        self.assertEqual(dados["placar"], [7, 8])
        self.assertEqual(dados["duracao"], "71:04")
        self.assertEqual(dados["aviso_ajuste_s"], 20)
        tipos = [(e["tipo"], e["time"], e["tempo_jogo"]) for e in dados["eventos"]]
        self.assertEqual(tipos, [
            ("gol", 0, "08:56"),
            ("gol", 0, "09:24"),
            ("gol", 1, "02:50"),
            ("lance", 1, "15:40"),
        ])

    def test_inicio_do_jogo_soma_e_o_corte_volta_os_segundos(self):
        dados = parse_texto_gols(TEXTO)
        cortes = montar_cortes(dados["eventos"], inicio_jogo_s=180, antes_s=30, depois_s=8)
        primeiro = next(c for c in cortes if c["tempo_jogo"] == "08:56")
        # 08:56 do jogo + 3:00 de vídeo = 11:56; corte de 11:26 até 12:04
        self.assertEqual(primeiro["tempo_s"], 716)
        self.assertEqual(primeiro["inicio_s"], 686)
        self.assertEqual(primeiro["fim_s"], 724)
        self.assertEqual(primeiro["tempo"], "08:56")

    def test_sem_inicio_o_corte_comeca_30s_antes(self):
        dados = parse_texto_gols("GOLS - Time A\n02:50\n")
        corte = montar_cortes(dados["eventos"], 0, 30, 8)[0]
        self.assertEqual(corte["tempo_s"], 170)
        self.assertEqual(corte["inicio_s"], 140)
        self.assertEqual(corte["fim_s"], 178)

    def test_inicio_nao_passa_do_zero_do_arquivo(self):
        dados = parse_texto_gols("GOLS - Time A\n00:10\n")
        corte = montar_cortes(dados["eventos"], 0, 30, 8)[0]
        self.assertEqual(corte["inicio_s"], 0)
        self.assertEqual(corte["fim_s"], 18)
