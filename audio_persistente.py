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


def higienizar_referencia(caminho_voz, pasta_destino, ffmpeg):
    """Higieniza áudio de referência (highpass, lowpass, denoise FFT e loudnorm) via FFmpeg."""
    caminho_voz = Path(caminho_voz).resolve()
    chave = hash_arquivo(caminho_voz)
    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)
    limpo = pasta_destino / f'ref-{chave[:16]}.limpo.wav'
    if limpo.is_file() and limpo.stat().st_size > 44:
        return str(limpo)
    fd, temporario = tempfile.mkstemp(dir=pasta_destino, prefix='.ttsbr-ref-', suffix='.wav')
    os.close(fd)
    try:
        filtros = 'highpass=f=80,lowpass=f=10000,afftdn=nf=-25,loudnorm=I=-18:TP=-1.5:LRA=11'
        processo = subprocess.run(
            [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
             '-i', str(caminho_voz), '-af', filtros, '-ac', '1', '-ar', str(SR),
             '-c:a', 'pcm_s16le', str(temporario)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        if processo.returncode:
            raise RuntimeError(f'Falha ao higienizar áudio de referência: {processo.stderr.strip()}')
        os.replace(temporario, limpo)
    finally:
        Path(temporario).unlink(missing_ok=True)
    return str(limpo)


def formatar_tempo_legenda(segundos, separador=','):
    ms_total = max(0, int(round(float(segundos) * 1000)))
    horas, resto = divmod(ms_total, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, ms = divmod(resto, 1000)
    return f'{horas:02d}:{minutos:02d}:{segs:02d}{separador}{ms:03d}'


def gerar_legenda(segmentos, formato='srt'):
    formato = formato.lower()
    if formato not in ('srt', 'vtt'):
        raise ValueError(f'Formato de legenda inválido: {formato}')
    sep = ',' if formato == 'srt' else '.'
    blocos = []
    for idx, seg in enumerate(segmentos, 1):
        inicio = formatar_tempo_legenda(seg.get('inicio_s', 0.0), sep)
        fim = formatar_tempo_legenda(seg.get('fim_s', seg.get('inicio_s', 0.0)), sep)
        texto = str(seg.get('texto', '')).strip()
        blocos.append(f'{idx}\n{inicio} --> {fim}\n{texto}')
    corpo = '\n\n'.join(blocos) + ('\n' if blocos else '')
    if formato == 'vtt':
        return 'WEBVTT\n\n' + corpo
    return corpo


def exportar(eventos, base, formatos, ffmpeg, segmentos=(), lufs=None, taxa_amostragem=None,
             trilha=None, volume_trilha=-18.0):
    """Monta WAV em disco e substitui cada saída somente após sua conclusão."""
    base = Path(base)
    precisa_audio = any(f in ('wav', 'mp3') for f in formatos)
    sr_alvo = int(taxa_amostragem) if taxa_amostragem is not None else SR
    opcoes_audio = []
    if trilha:
        pos_mix = f',loudnorm=I={float(lufs)}:TP=-1.5:LRA=11' if lufs is not None else ''
        grafo = (
            f'[0:a]aformat=sample_rates={sr_alvo}:channel_layouts=mono,asplit=2[voz_sc][voz_mix];'
            f'[1:a]aformat=sample_rates={sr_alvo}:channel_layouts=mono,volume={float(volume_trilha)}dB[bg];'
            f'[bg][voz_sc]sidechaincompress=threshold=0.015:ratio=4:attack=50:release=600[bg_duck];'
            f'[voz_mix][bg_duck]amix=inputs=2:duration=first:dropout_transition=2:normalize=0{pos_mix}[out]'
        )
        opcoes_audio.extend([
            '-stream_loop', '-1', '-i', str(Path(trilha).resolve()),
            '-filter_complex', grafo, '-map', '[out]', '-ac', '1', '-ar', str(sr_alvo),
        ])
    else:
        if lufs is not None:
            opcoes_audio.extend(['-af', f'loudnorm=I={float(lufs)}:TP=-1.5:LRA=11'])
        if sr_alvo != SR:
            opcoes_audio.extend(['-ar', str(sr_alvo)])

    with tempfile.TemporaryDirectory(dir=base.parent, prefix='.ttsbr-montagem-') as pasta:
        wav = Path(pasta) / 'montagem.wav'
        if precisa_audio:
            montar_wav(eventos, wav)
        for formato in formatos:
            destino = base.parent / f'{base.name}.{formato}'
            temporario = Path(pasta) / f'final.{formato}'
            if formato in ('srt', 'vtt'):
                temporario.write_text(gerar_legenda(segmentos, formato), encoding='utf-8')
            elif formato == 'wav' and not opcoes_audio:
                shutil.copyfile(wav, temporario)
            elif formato == 'wav':
                processo = subprocess.run(
                    [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                     '-i', str(wav), *opcoes_audio, '-c:a', 'pcm_s16le', str(temporario)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação WAV: {processo.stderr.strip()}')
            else:
                processo = subprocess.run(
                    [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                     '-i', str(wav), *opcoes_audio, '-b:a', '192k', str(temporario)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação MP3: {processo.stderr.strip()}')
            os.replace(temporario, destino)
            print(f'Gerado: {destino}')
