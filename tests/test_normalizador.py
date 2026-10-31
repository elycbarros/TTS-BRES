#!/usr/bin/env python3
"""Testes de unidade para o normalizador fonético e detector de idioma (PT e ES)."""
import tempfile
import unicodedata
import unittest
from pathlib import Path

from normalizador import (
    carregar_glossario,
    detectar_idioma,
    expandir_abreviacoes,
    normalizar_numeros_e_simbolos_es,
    normalizar_numeros_e_simbolos_pt,
    normalizar_para_fala,
    normalizar_termos_tecnicos,
    numero_por_extenso,
    numero_por_extenso_es,
)


class TestDetectorIdioma(unittest.TestCase):
    def test_deteccao_portugues(self):
        textos = [
            "No aprendizado de máquina supervisionado, o modelo aprende padrões.",
            "Esta é uma reflexão baseada no capítulo 7 de Mateus.",
            "Não foi possível encontrar a solução para o problema.",
            "Você pode verificar os dados na nossa aplicação web.",
        ]
        for t in textos:
            with self.subTest(texto=t):
                self.assertEqual(detectar_idioma(t), "pt")

    def test_deteccao_espanhol(self):
        textos = [
            "En el aprendizaje supervisado, el modelo entrena con datos etiquetados.",
            "¿Cuáles son los parámetros más importantes de la red?",
            "El niño corrió hacia la escuela en el año 2024.",
            "Por ejemplo, los transformadores analizan secuencias masivas.",
        ]
        for t in textos:
            with self.subTest(texto=t):
                self.assertEqual(detectar_idioma(t), "es")


class TestNumerosPT(unittest.TestCase):
    def test_numeros_extenso_basicos(self):
        self.assertEqual(numero_por_extenso(0), "zero")
        self.assertEqual(numero_por_extenso(15), "quinze")
        self.assertEqual(numero_por_extenso(24), "vinte e quatro")
        self.assertEqual(numero_por_extenso(100), "cem")
        self.assertEqual(numero_por_extenso(105), "cento e cinco")
        self.assertEqual(numero_por_extenso(1000), "mil")
        self.assertEqual(numero_por_extenso(1500), "mil e quinhentos")
        self.assertEqual(numero_por_extenso(2024), "dois mil e vinte e quatro")

    def test_porcentagens_e_unidades_pt(self):
        t1 = normalizar_numeros_e_simbolos_pt("Acurácia de 95%")
        self.assertIn("noventa e cinco por cento", t1)

        t2 = normalizar_numeros_e_simbolos_pt("Memória de 16GB e pausa de 250ms")
        self.assertIn("dezesseis gigabytes", t2)
        self.assertIn("duzentos e cinquenta milissegundos", t2)

        t3 = normalizar_numeros_e_simbolos_pt("Constante pi é 3,14")
        self.assertIn("três vírgula quatorze", t3)

    def test_numeros_grandes_sem_virgula_interna_e_unicode_nfc(self):
        extenso = numero_por_extenso(1_250_500)
        self.assertNotIn(",", extenso)
        self.assertIn("um milhão duzentos e cinquenta mil e quinhentos", extenso)

        texto_nfd = unicodedata.normalize("NFD", "São milhões de criações que não param.")
        normalizado, lang = normalizar_para_fala(texto_nfd, idioma="auto")
        self.assertEqual(lang, "pt")
        self.assertEqual(normalizado, unicodedata.normalize("NFC", normalizado))
        self.assertIn("São", normalizado)
        self.assertIn("milhões", normalizado)
        self.assertIn("criações", normalizado)
        self.assertIn("não", normalizado)


class TestNumerosES(unittest.TestCase):
    def test_numeros_extenso_es_basicos(self):
        self.assertEqual(numero_por_extenso_es(0), "cero")
        self.assertEqual(numero_por_extenso_es(16), "dieciséis")
        self.assertEqual(numero_por_extenso_es(24), "veinticuatro")
        self.assertEqual(numero_por_extenso_es(35), "treinta y cinco")
        self.assertEqual(numero_por_extenso_es(100), "cien")
        self.assertEqual(numero_por_extenso_es(500), "quinientos")
        self.assertEqual(numero_por_extenso_es(1000), "mil")
        self.assertEqual(numero_por_extenso_es(1500), "mil quinientos")
        self.assertEqual(numero_por_extenso_es(2024), "dos mil veinticuatro")
        self.assertEqual(numero_por_extenso_es(1_000_000), "un millón")
        self.assertEqual(numero_por_extenso_es(2_000_000), "dos millones")

    def test_porcentagens_e_unidades_es(self):
        t1 = normalizar_numeros_e_simbolos_es("El 95% de los casos")
        self.assertIn("noventa y cinco por ciento", t1)

        t2 = normalizar_numeros_e_simbolos_es("Memoria de 16GB y 250ms")
        self.assertIn("dieciséis gigabytes", t2)
        self.assertIn("doscientos cincuenta milisegundos", t2)

        t3 = normalizar_numeros_e_simbolos_es("Valor de 3,14")
        self.assertIn("tres coma catorce", t3)


class TestTermosTecnicosESiglas(unittest.TestCase):
    def test_siglas_pt(self):
        res, _ = normalizar_para_fala("Se a condição X na GPU for IA", idioma="pt")
        self.assertIn("chís", res)
        self.assertIn("gê-pê-ú", res)
        self.assertIn("i-á", res)

    def test_siglas_es(self):
        res, _ = normalizar_para_fala("Si la condición X en la GPU es IA", idioma="es")
        self.assertIn("equis", res)
        self.assertIn("je-pe-ú", res)
        self.assertIn("i-a", res)

    def test_termos_ingles_pt_e_es(self):
        res_pt, _ = normalizar_para_fala("Usamos deep learning e machine learning", idioma="pt")
        self.assertIn("díp lérnin", res_pt)
        self.assertIn("maxíne lérnin", res_pt)

        res_es, _ = normalizar_para_fala("Usamos deep learning y machine learning", idioma="es")
        self.assertIn("díp lérnin", res_es)
        self.assertIn("machín lérnin", res_es)


class TestAbreviacoes(unittest.TestCase):
    def test_abreviacoes_pt(self):
        t = expandir_abreviacoes("O Dr. Silva e o Prof. Santos, p. ex.", idioma="pt")
        self.assertIn("Doutor", t)
        self.assertIn("Professor", t)
        self.assertIn("por exemplo,", t)

    def test_abreviacoes_es(self):
        t = expandir_abreviacoes("El Dr. Martínez y el Prof. Gómez, p. ej.", idioma="es")
        self.assertIn("Doctor", t)
        self.assertIn("Profesor", t)
        self.assertIn("por ejemplo,", t)


class TestGlossarioCustomizado(unittest.TestCase):
    def test_glossario_txt_e_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            gtxt = p / "custom.txt"
            gtxt.write_text("PostgreSQL = pós-gre\nFastAPI = fást-ápi\n", encoding="utf-8")

            g = carregar_glossario(gtxt)
            self.assertEqual(g["PostgreSQL"], "pós-gre")
            self.assertEqual(g["FastAPI"], "fást-ápi")

            res, _ = normalizar_para_fala("Banco PostgreSQL com FastAPI", idioma="pt", glossario_extra=g)
            self.assertIn("pós-gre", res.lower())
            self.assertIn("fást-ápi", res.lower())

    def test_guia_fonetico_anos(self):
        # Garante que "anos" recebe acento circunflexo guia em português para evitar oxítona no XTTS v2
        res, _ = normalizar_para_fala("dois anos e dez anos", idioma="pt")
        self.assertIn("dois ânos", res)
        self.assertIn("dez ânos", res)

    def test_conjuncao_y_espanhol_nao_vira_ye(self):
        # Garante que a conjunção "Y" em início de frase em espanhol não seja tratada como sigla da letra Y ("ye")
        res, _ = normalizar_para_fala("Y en el versículo tres dice: Y entonces ocurrió.", idioma="es")
        self.assertTrue(res.startswith("Y en el"))
        self.assertNotIn("ye en el", res.lower())


if __name__ == "__main__":
    unittest.main()
