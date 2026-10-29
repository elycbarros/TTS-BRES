#!/usr/bin/env python3
"""Testes de unidade para operações de áudio e fatiamento do pipeline TTS."""
import unittest
import numpy as np

from normalizador import normalizar_para_fala
from tts import (
    contar_palavras,
    cortar_silencio_pontas,
    dividir_frases,
    extrair_tags_expressividade,
    limpar_para_voz,
    montar_itens,
    pausa_ms,
)


class TestTagsExpressividade(unittest.TestCase):
    def test_tag_sobrevive_a_normalizacao_e_pausa_correta(self):
        # Regressão: "1.5s" virava "um vírgula cinco segundos" e a pausa caía em 1000 ms.
        texto, _ = normalizar_para_fala("Ele pensou [pausa:1.5s] e decidiu.", idioma="pt")
        self.assertIn("[pausa:1.5s]", texto)
        pausas = [m["pausa_extra_ms"] for _, m in extrair_tags_expressividade(texto) if "pausa_extra_ms" in m]
        self.assertEqual(pausas, [1500])

    def test_pausa_fica_entre_o_texto_anterior_e_o_posterior(self):
        # Regressão: a pausa era colada DEPOIS do texto seguinte à tag, em vez de no lugar da tag.
        itens = extrair_tags_expressividade("Ele pensou [pausa:1.5s] e decidiu.")
        self.assertEqual(
            itens,
            [("Ele pensou", {}), ("", {"pausa_extra_ms": 1500}), ("e decidiu.", {})],
        )

    def test_volume_vale_para_o_texto_seguinte(self):
        itens = extrair_tags_expressividade("antes [sussurro] depois")
        self.assertEqual(itens, [("antes", {}), ("depois", {"volume_offset_db": -4.0})])

    def test_tags_pausa_ms_enfase_sussurro(self):
        self.assertEqual(extrair_tags_expressividade("a [pausa:800ms] b")[1][1]["pausa_extra_ms"], 800)
        self.assertEqual(extrair_tags_expressividade("[enfase] oi")[0][1]["volume_offset_db"], 2.5)
        self.assertEqual(extrair_tags_expressividade("[sussurro] oi")[0][1]["volume_offset_db"], -4.0)


class MockArgs:
    pausa_frase = 600
    pausa_reticencias = 850
    pausa_ponto_virgula = 420
    pausa_virgula = 250
    pausa_paragrafo = 1150


class TestOperacoesAudioEPausas(unittest.TestCase):
    def test_limpar_para_voz_sem_ponto_final(self):
        # Garante que ponto final não é enviado ao XTTS para não falar "ponto"
        self.assertEqual(limpar_para_voz("Olá mundo."), "Olá mundo")
        self.assertEqual(limpar_para_voz("Frase com reticências..."), "Frase com reticências")
        self.assertEqual(limpar_para_voz("Item um; item dois:"), "Item um, item dois")

    def test_pausas_ms_corretas(self):
        args = MockArgs()
        self.assertEqual(pausa_ms("Fim de parágrafo.", fim_par=True, args=args), 1150)
        self.assertEqual(pausa_ms("Frase normal.", fim_par=False, args=args), 600)
        self.assertEqual(pausa_ms("Pensando...", fim_par=False, args=args), 850)
        self.assertEqual(pausa_ms("Dois pontos:", fim_par=False, args=args), 420)
        self.assertEqual(pausa_ms("Corte por vírgula,", fim_par=False, args=args), 250)

    def test_cortar_silencio_pontas(self):
        sr = 24000
        # Cria 0.5s de silêncio + 1s de sinal senoidal (áudio útil) + 0.5s de silêncio
        sil_ini = np.zeros(int(0.5 * sr), dtype=np.float32)
        tempo = np.linspace(0, 1.0, int(1.0 * sr), dtype=np.float32)
        tom = 0.5 * np.sin(2 * np.pi * 440 * tempo)
        sil_fim = np.zeros(int(0.5 * sr), dtype=np.float32)

        sinal_completo = np.concatenate([sil_ini, tom, sil_fim])
        recortado = cortar_silencio_pontas(sinal_completo, sr=sr)

        # O sinal resultante deve ser significativamente menor que o original (removeu ~1s de silêncio)
        self.assertLess(len(recortado), len(sinal_completo))
        # Mas deve preservar a maior parte do áudio útil (pelo menos 0.9s)
        self.assertGreater(len(recortado), int(0.9 * sr))

    def test_divisao_de_frases_longas(self):
        paragrafo = (
            "Esta é uma frase deliberadamente muito longa para testar o particionamento inteligente, "
            "onde o sistema deve preferir cortar nas vírgulas intermediárias em vez de palavras aleatórias, "
            "garantindo que cada pedaço respeite o limite máximo de caracteres estipulado pelo modelo."
        )
        partes = dividir_frases(paragrafo)
        self.assertGreaterEqual(len(partes), 2)
        for p in partes:
            self.assertLessEqual(len(p), 205)

    def test_montagem_itens_com_idioma_por_paragrafo(self):
        texto = "Primeiro parágrafo em português.\n\nSegundo párrafo en español con palabras claras."
        itens = montar_itens(texto, normalizar=True, idioma_padrao="pt", detectar_por_paragrafo=True)
        self.assertEqual(len(itens), 2)
        self.assertEqual(itens[0][2], "pt")
        self.assertEqual(itens[1][2], "es")

    def test_montagem_itens_com_dialogo_multi_locutor(self):
        roteiro = (
            "[Narrador]: O pesquisador fez uma descoberta.\n\n"
            "[Luis]: Conseguimos reduzir o erro para menos de 1%.\n\n"
            "[Alma]: Excelente, vamos testar em produção."
        )
        itens = montar_itens(roteiro, normalizar=True, idioma_padrao="pt", detectar_por_paragrafo=True)
        self.assertEqual(len(itens), 3)
        self.assertEqual(itens[0][3], "Luis Moray")
        self.assertEqual(itens[1][3], "Luis Moray")
        self.assertEqual(itens[2][3], "Alma María")
        self.assertFalse(itens[0][0].startswith("[Narrador]"))
        self.assertTrue(itens[0][0].startswith("O pesquisador"))


if __name__ == "__main__":
    unittest.main()
