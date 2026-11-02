import os
import tempfile
import unittest
from unittest import mock

import montar_video


class ReservasEscalacaoTest(unittest.TestCase):
    def setUp(self):
        self._tema_original = montar_video.TEMA
        self.partida = {
            "meta": {
                "pelada": "Will Cup",
                "comp": "Rodada 12",
                "data": "01/11/2026",
                "local": "Arena Fut",
            },
            "times": [
                {
                    "nome": "Time Amarelo",
                    "cor": "#eab308",
                    "jogadores": [
                        "Pedro Reserva",
                        "Will",
                        "João",
                        "Lucas",
                        "Mateus",
                        "Caio",
                        "Bruno Sub",
                    ],
                    "posicoes": {},
                    "reservas": ["Pedro Reserva", "Bruno Sub"],
                },
                {
                    "nome": "Time Azul",
                    "cor": "#2563eb",
                    "jogadores": [
                        "Arthur",
                        "Marcão",
                        "Igor",
                        "Nandrey",
                        "Zé",
                        "Luiz Banco",
                    ],
                    "posicoes": {
                        "Arthur": "goleiro",
                        "Marcão": "zagueiro",
                        "Igor": "meio",
                        "Nandrey": "meio",
                        "Zé": "atacante",
                    },
                    "reservas": ["Luiz Banco"],
                },
            ],
        }

    def tearDown(self):
        montar_video.TEMA = self._tema_original

    def test_separar_titulares_e_reservas_preserva_goleiro_nos_titulares(self):
        titulares_a, reservas_a = montar_video.separar_titulares_e_reservas(self.partida["times"][0])
        self.assertEqual([n for n, _ in reservas_a], ["Pedro Reserva", "Bruno Sub"])
        self.assertTrue(all(pos == "reserva" for _, pos in reservas_a))
        self.assertEqual([n for n, _ in titulares_a], ["Will", "João", "Lucas", "Mateus", "Caio"])
        # Mesmo com "Pedro Reserva" na primeira linha do elenco, "Will" (1º titular) vira o goleiro
        self.assertEqual(titulares_a[0], ("Will", "goleiro"))

    def test_suporta_formatos_alternativos_de_reserva(self):
        time_dict = {
            "nome": "Teste",
            "cor": "#22c55e",
            "jogadores": ["A", "B", "C", {"nome": "D", "reserva": True}],
            "posicoes": {"B": "reserva"},
            "reservas": {"C": True, "A": False},
        }
        titulares, reservas = montar_video.separar_titulares_e_reservas(time_dict)
        self.assertEqual([n for n, _ in titulares], ["A"])
        self.assertEqual(titulares[0], ("A", "goleiro"))
        self.assertEqual([n for n, _ in reservas], ["B", "C", "D"])

    def test_cartela_abertura_nao_desenha_reservas_no_campo_em_nenhum_tema(self):
        for tema in ("atual", "fifa", "tv"):
            montar_video.TEMA = tema
            chamadas_campo = []
            chamadas_avatar = []
            orig_campo = montar_video.desenhar_campo_tatico
            orig_avatar = montar_video.obter_avatar_jogador

            def spy_campo(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=None, times=None):
                chamadas_campo.append((list(time_a), list(time_b)))
                return orig_campo(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=img_base, times=times)

            def spy_avatar(nome, time_obj=None, tamanho=(50, 50), cor_time=None, pos="MEI"):
                chamadas_avatar.append((nome, tamanho, pos))
                return orig_avatar(nome, time_obj=time_obj, tamanho=tamanho, cor_time=cor_time, pos=pos)

            with mock.patch.object(montar_video, "desenhar_campo_tatico", side_effect=spy_campo), \
                 mock.patch.object(montar_video, "obter_avatar_jogador", side_effect=spy_avatar):
                img = montar_video.cartela_abertura(self.partida)

            self.assertEqual(img.size, (1920, 1080))
            self.assertEqual(len(chamadas_campo), 1)
            campo_a, campo_b = chamadas_campo[0]
            nomes_campo_a = {n for n, _ in campo_a}
            nomes_campo_b = {n for n, _ in campo_b}

            # Reservas NUNCA aparecem no campo tático
            self.assertNotIn("Pedro Reserva", nomes_campo_a)
            self.assertNotIn("Bruno Sub", nomes_campo_a)
            self.assertNotIn("Luiz Banco", nomes_campo_b)
            # Titulares aparecem no campo tático
            self.assertEqual(nomes_campo_a, {"Will", "João", "Lucas", "Mateus", "Caio"})
            self.assertEqual(nomes_campo_b, {"Arthur", "Marcão", "Igor", "Nandrey", "Zé"})

            # Reservas APARECEM nos painéis laterais (avatar menor <= 32px, pos="reserva")
            avatares_laterais = {(n, pos) for n, tam, pos in chamadas_avatar if tam[0] <= 32}
            self.assertIn(("Pedro Reserva", "reserva"), avatares_laterais)
            self.assertIn(("Bruno Sub", "reserva"), avatares_laterais)
            self.assertIn(("Luiz Banco", "reserva"), avatares_laterais)

    def test_sequencia_abertura_animada_revela_titulares_no_campo_e_reservas_ao_lado(self):
        seq = montar_video._montar_sequencia_abertura(self.partida)
        # 1 vazio + 5 titulares A + 5 titulares B = 11 passos (não cria passos mortos no campo para reservas)
        self.assertEqual(len(seq), 1 + 5 + 5)

        va_final, vb_final, dur_final = seq[-1]
        self.assertEqual(dur_final, 3.0)
        # No frame final da abertura animada, titulares e reservas estão visíveis na lista lateral
        self.assertIn("Pedro Reserva", va_final)
        self.assertIn("Bruno Sub", va_final)
        self.assertIn("Will", va_final)
        self.assertIn("Luiz Banco", vb_final)
        self.assertIn("Arthur", vb_final)

        # Renderizando o último frame da abertura animada, reservas ficam fora do campo e dentro da lateral
        chamadas_campo = []
        orig_campo = montar_video.desenhar_campo_tatico

        def spy_campo(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=None, times=None):
            chamadas_campo.append((list(time_a), list(time_b)))
            return orig_campo(draw, x0, y0, w, h, time_a, time_b, ca, cb, img_base=img_base, times=times)

        with mock.patch.object(montar_video, "desenhar_campo_tatico", side_effect=spy_campo):
            montar_video.cartela_abertura(self.partida, visiveis_a=va_final, visiveis_b=vb_final)

        campo_a, campo_b = chamadas_campo[0]
        self.assertNotIn("Pedro Reserva", {n for n, _ in campo_a})
        self.assertNotIn("Luiz Banco", {n for n, _ in campo_b})

    def test_gerar_abertura_animada_video_real_curto(self):
        partida_curta = {
            "meta": {"pelada": "Will Cup"},
            "times": [
                {"nome": "Time A", "cor": "#eab308", "jogadores": ["Will", "Pedro Res"], "reservas": ["Pedro Res"]},
                {"nome": "Time B", "cor": "#2563eb", "jogadores": ["Arthur", "Luiz Res"], "reservas": ["Luiz Res"]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            saida = montar_video.gerar_abertura_animada(
                partida_curta, tmp, dur_total=5.0, crf=30, preset="ultrafast", codec="libx264"
            )
            self.assertTrue(os.path.isfile(saida))
            self.assertGreater(os.path.getsize(saida), 1000)


if __name__ == "__main__":
    unittest.main()
