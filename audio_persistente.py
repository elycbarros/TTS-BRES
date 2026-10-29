"""Cache verificável de segmentos e montagem de áudio com memória limitada."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

SR = 24000
CHUNK = 65536


def hash_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, 'rb') as arquivo:
        for dados in iter(lambda: arquivo.read(CHUNK), b''):
            h.update(dados)
    return h.hexdigest()


def chave_segmento(parametros):
    return hashlib.sha256(json.dumps(parametros, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def salvar_json(caminho, dados):
    caminho = Path(caminho)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix='.ttsbr-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    finally:
        Path(temporario).unlink(missing_ok=True)


class CacheSegmentos:
    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)

    def obter(self, parametros, gerar, refazer=False):
        chave = chave_segmento(parametros)
        destino = self.pasta / f'{chave}.wav'
        metadados = destino.with_suffix('.json')
        if not refazer:
            try:
                info = json.loads(metadados.read_text(encoding='utf-8'))
                with wave.open(str(destino), 'rb') as audio:
                    valido = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, SR)
                    frames = audio.getnframes()
                if (valido and frames > 0 and info['frames'] == frames
                        and info['parametros'] == parametros and info['sha256'] == hash_arquivo(destino)):
                    return destino, frames, True
            except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError):
                pass
        segmento = gerar()
        if (segmento.channels, segmento.sample_width, segmento.frame_rate) != (1, 2, SR):
            raise ValueError('Segmento deve ser PCM mono de 16 bits a 24 kHz.')
        frames = len(segmento.raw_data) // 2
        if not frames:
            raise ValueError('A síntese retornou um segmento vazio.')
        fd, temporario = tempfile.mkstemp(dir=self.pasta, prefix='.ttsbr-', suffix='.wav')
        os.close(fd)
        try:
            with segmento.export(temporario, format='wav'):
                pass
            os.replace(temporario, destino)
            salvar_json(metadados, {'parametros': parametros, 'frames': frames,
                                    'sha256': hash_arquivo(destino)})
        finally:
            Path(temporario).unlink(missing_ok=True)
        return destino, frames, False


def escrever_silencio(audio, ms):
    restante = SR * ms // 1000 * 2
    zeros = bytes(CHUNK)
    while restante:
        n = min(CHUNK, restante)
        audio.writeframesraw(zeros[:n])
        restante -= n


def montar_wav(eventos, destino):
    """Copia PCM em blocos; eventos são caminhos WAV ou pausas em ms."""
    total = 0
    for evento in eventos:
        if isinstance(evento, int):
            total += SR * evento // 1000
        else:
            with wave.open(str(evento), 'rb') as entrada:
                total += entrada.getnframes()
    if total * 2 > 0xFFFFFFFF - 36:
        raise ValueError('O áudio excede o limite de 4 GB do WAV RIFF; divida o texto em arquivos menores.')
    with wave.open(str(destino), 'wb') as saida:
        saida.setparams((1, 2, SR, 0, 'NONE', 'not compressed'))
        for evento in eventos:
            if isinstance(evento, int):
                escrever_silencio(saida, evento)
            else:
                with wave.open(str(evento), 'rb') as entrada:
                    if (entrada.getnchannels(), entrada.getsampwidth(), entrada.getframerate()) != (1, 2, SR):
                        raise ValueError(f'Formato de segmento incompatível: {evento}')
                    for dados in iter(lambda: entrada.readframes(CHUNK // 2), b''):
                        saida.writeframesraw(dados)


def exportar(eventos, base, formatos, ffmpeg):
    """Monta WAV em disco e substitui cada saída somente após sua conclusão."""
    base = Path(base)
    with tempfile.TemporaryDirectory(dir=base.parent, prefix='.ttsbr-montagem-') as pasta:
        wav = Path(pasta) / 'montagem.wav'
        montar_wav(eventos, wav)
        for formato in formatos:
            destino = base.parent / f'{base.name}.{formato}'
            temporario = Path(pasta) / f'final.{formato}'
            if formato == 'wav':
                shutil.copyfile(wav, temporario)
            else:
                processo = subprocess.run(
                    [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                     '-i', str(wav), '-b:a', '192k', str(temporario)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação MP3: {processo.stderr.strip()}')
            os.replace(temporario, destino)
            print(f'Gerado: {destino}')
