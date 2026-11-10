"""Uma câmera que acaba antes do lance não entra no corte."""
import unittest

from video_quality import janela_no_arquivo


class JanelaNoArquivoTest(unittest.TestCase):
    def test_corte_inteiro_quando_cabe(self):
        self.assertEqual(janela_no_arquivo(10, 15, 80), 15)

    def test_encurta_quando_a_gravacao_acaba_no_meio(self):
        self.assertEqual(janela_no_arquivo(50, 20, 60), 10)

    def test_sem_filmagem_quando_o_lance_comeca_depois_do_fim(self):
        self.assertIsNone(janela_no_arquivo(70, 15, 60))

    def test_sem_duracao_conhecida_corta_o_pedido(self):
        self.assertEqual(janela_no_arquivo(4, 8, None), 8)
