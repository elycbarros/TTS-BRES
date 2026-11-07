"""Diagnóstico público por lista permitida; não carrega modelos nem acessa a rede."""
import argparse
import ctypes.util
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

PACOTES = ('coqui-tts', 'torch', 'torchaudio', 'torchcodec', 'pydub',
           'numpy', 'imageio-ffmpeg', 'soundfile', 'transformers')


def executar_probe(comando, timeout=15):
    """Erros crus podem conter caminhos e ficam fora do relatório público."""
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True,
                                   timeout=timeout, check=False)
        return resultado.returncode, resultado.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, ''


def versoes_pacotes():
    resultado = {}
    for nome in PACOTES:
        try:
            resultado[nome] = importlib.metadata.version(nome)
        except importlib.metadata.PackageNotFoundError:
            resultado[nome] = None
    return resultado


def coletar(destino_dados=None, dispositivos=False):
    # O caminho serve apenas para medir o volume; nunca entra no relatório.
    pasta = Path(destino_dados or Path.cwd()).resolve()
    while not pasta.exists() and pasta != pasta.parent:
        pasta = pasta.parent
    try:
        livre = round(shutil.disk_usage(pasta).free / (1024 ** 3), 1)
    except OSError:
        livre = None
    codigo, _ = executar_probe([sys.executable, '-c',
                               'import tkinter; t = tkinter.Tcl(); t.eval("info patchlevel")'])
    tkinter = 'importavel_sem_validacao_visual' if codigo == 0 else 'indisponivel_ou_probe_falhou'
    ffmpeg = shutil.which('ffmpeg')
    origem = 'sistema' if ffmpeg else 'ausente'
    if not ffmpeg:
        codigo, texto = executar_probe([sys.executable, '-c',
                                       'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'])
        if codigo == 0 and texto.strip():
            ffmpeg, origem = texto.strip(), 'imageio-ffmpeg'
    # find_library só localiza candidatos: não comprova carregamento pelo TorchCodec.
    nativas = {}
    for nome in ('avcodec', 'avformat', 'avutil'):
        try:
            nativas[nome] = bool(ctypes.util.find_library(nome))
        except OSError:
            nativas[nome] = False
    device = {'estado': 'nao_sondado', 'cpu': True, 'cuda': None, 'mps': None}
    if dispositivos:
        codigo, texto = executar_probe([sys.executable, '-c',
            'import json, torch; print(json.dumps({"cuda": bool(torch.cuda.is_available()), '
            '"mps": bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())}))'], 30)
        try:
            dados = json.loads(texto) if codigo == 0 else {}
            if type(dados.get('cuda')) is bool and type(dados.get('mps')) is bool:
                device.update(estado='sondado_sem_inferencia', cuda=dados['cuda'], mps=dados['mps'])
            else:
                device['estado'] = 'probe_falhou'
        except (ValueError, TypeError):
            device['estado'] = 'probe_falhou'
    return {
        'formato': 'ttsbr.diagnostico', 'versao_esquema': 1,
        'gerado_em': datetime.now(timezone.utc).isoformat(),
        'ambiente': {'sistema': platform.system(), 'arquitetura': platform.machine(),
                     'python': platform.python_version()},
        'pacotes': versoes_pacotes(), 'tkinter': tkinter,
        'ffmpeg': {'origem': origem, 'executavel_funcional': codigo_ffmpeg(ffmpeg),
                   'bibliotecas_localizaveis': nativas,
                   'torchcodec_leitura_referencia': 'nao_validada'},
        'dispositivos': device, 'espaco_livre_gib': livre,
        'limites': ['Sem inferência ou teste de qualidade de voz.',
                    'Tkinter importável não aprova a janela ou o player.',
                    'FFmpeg executável não comprova bibliotecas compartilhadas compatíveis.',
                    'Detecção de dispositivo não comprova síntese nesse dispositivo.'],
    }


def codigo_ffmpeg(executavel):
    return bool(executavel and executar_probe([executavel, '-version'])[0] == 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dados', type=Path, help='Volume a medir; caminho omitido do relatório.')
    parser.add_argument('--dispositivos', action='store_true', help='Sonda Torch em subprocesso isolado.')
    args = parser.parse_args(argv)
    print(json.dumps(coletar(args.dados, args.dispositivos), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
