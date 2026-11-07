"""Contratos do preview e limites do diagnóstico público, sem inferência."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import contratos
import diagnostico


def projeto():
    return {'formato': 'ttsbr.projeto', 'versao_esquema': 1, 'id': 'projeto-1',
            'dados': {'titulo': 'Narração', 'roteiro': 'Olá!', 'elenco': {'narrador': 'voz-1'},
                      'glossario': {}, 'configuracao': {}}}


def voz():
    return {'formato': 'ttsbr.voz', 'versao_esquema': 1, 'id': 'voz-1',
            'dados': {'nome': 'Referência', 'idioma': 'pt', 'estilo': 'neutra',
                      'referencia': 'referencias/tomada.wav', 'sha256': 'a' * 64,
                      'transcricao': 'Olá!', 'autorizacao_declarada': True}}


class TestContratosPreview(unittest.TestCase):
    def test_roundtrip_independente_sem_alterar_original(self):
        original = projeto()
        resultado = contratos.carregar(json.dumps(original))
        resultado['dados']['roteiro'] = 'Outro'
        self.assertEqual(original['dados']['roteiro'], 'Olá!')
        self.assertEqual(contratos.validar(voz()), voz())

    def test_rejeita_versao_futura_bool_e_envelope_desconhecido(self):
        for versao in (0, 2, True, '1'):
            documento = projeto(); documento['versao_esquema'] = versao
            with self.subTest(versao=versao), self.assertRaises(contratos.DocumentoInvalido):
                contratos.validar(documento)
        documento = projeto(); documento['segredo'] = 'não pode entrar'
        with self.assertRaises(contratos.DocumentoInvalido):
            contratos.validar(documento)

    def test_rejeita_referencias_nao_portaveis(self):
        for caminho in ('/tmp/voz.wav', '../voz.wav', 'C:/voz.wav', '\\\\host\\voz.wav',
                        'a/../voz.wav', 'a//voz.wav', 'a/./voz.wav', ''):
            documento = voz(); documento['dados']['referencia'] = caminho
            with self.subTest(caminho=caminho), self.assertRaises(contratos.DocumentoInvalido):
                contratos.validar(documento)

    def test_rejeita_tipos_nao_finitos_e_chaves_duplicadas(self):
        for valor in (float('nan'), float('inf'), object()):
            documento = projeto(); documento['dados']['configuracao']['velocidade'] = valor
            with self.assertRaises(contratos.DocumentoInvalido):
                contratos.validar(documento)
        with self.assertRaises(contratos.DocumentoInvalido):
            contratos.carregar('{"id":"a","id":"b"}')

    def test_snapshot_e_estado_de_tarefa(self):
        documento = {'formato': 'ttsbr.tarefa', 'versao_esquema': 1, 'id': 'tarefa-1',
                     'dados': {'projeto_id': 'projeto-1', 'estado': 'aguardando',
                               'snapshot': projeto(), 'saida_relativa': 'saida/tarefa-1', 'erro': None}}
        self.assertEqual(contratos.validar(documento), documento)
        for estado in ('desconhecido', 'falha'):
            alterado = deepcopy(documento); alterado['dados']['estado'] = estado
            with self.assertRaises(contratos.DocumentoInvalido):
                contratos.validar(alterado)
        documento['dados']['snapshot']['id'] = 'outro'
        with self.assertRaises(contratos.DocumentoInvalido):
            contratos.validar(documento)

    def test_estrutura_profunda_rejeitada(self):
        documento = projeto(); valor = documento['dados']['configuracao']
        for _ in range(40):
            valor['filho'] = {}; valor = valor['filho']
        with self.assertRaises(contratos.DocumentoInvalido):
            contratos.validar(documento)


class TestDiagnosticoPreview(unittest.TestCase):
    def test_probe_timeout_e_erro_nao_expoem_saida(self):
        for erro in (OSError('/caminho/privado'), subprocess.TimeoutExpired('probe', 1)):
            with patch('diagnostico.subprocess.run', side_effect=erro):
                self.assertEqual(diagnostico.executar_probe(['teste']), (None, ''))

    def test_publico_sem_caminhos_ou_identificadores_e_sem_torch(self):
        with tempfile.TemporaryDirectory(prefix='privado-') as tmp, \
                patch('diagnostico.executar_probe', return_value=(None, '')) as probe, \
                patch('diagnostico.shutil.which', return_value=None), \
                patch('diagnostico.ctypes.util.find_library', return_value=None), \
                patch('diagnostico.versoes_pacotes', return_value={'torch': None}):
            relatorio = diagnostico.coletar(Path(tmp) / 'ainda-nao-existe')
            serializado = json.dumps(relatorio)
            self.assertNotIn(tmp, serializado)
            self.assertNotIn(str(Path.home()), serializado)
            self.assertEqual(relatorio['dispositivos']['estado'], 'nao_sondado')
            self.assertFalse(relatorio['ffmpeg']['executavel_funcional'])
            self.assertEqual(relatorio['ffmpeg']['torchcodec_leitura_referencia'], 'nao_validada')
            self.assertFalse(any('import json, torch' in str(c) for c in probe.call_args_list))

    def test_sonda_opcional_so_aceita_booleanos(self):
        with patch('diagnostico.executar_probe', return_value=(0, '{"cuda":true,"mps":false}')), \
                patch('diagnostico.shutil.which', return_value='ffmpeg'):
            relatorio = diagnostico.coletar(dispositivos=True)
            self.assertEqual(relatorio['dispositivos']['cuda'], True)
            self.assertEqual(relatorio['dispositivos']['estado'], 'sondado_sem_inferencia')

    def test_importar_diagnostico_nao_importa_modelos(self):
        codigo = ('import sys, diagnostico, contratos; '
                  'assert not any(x in sys.modules for x in ("torch", "TTS", "tkinter"))')
        resultado = subprocess.run([sys.executable, '-c', codigo], capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)


if __name__ == '__main__':
    unittest.main()
