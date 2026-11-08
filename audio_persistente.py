"""Cache verificável de segmentos e montagem de áudio com memória limitada."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from qualidade_audio import medir_segmento

SR = 24000
CHUNK = 65536
_CACHE_HASH_ARQUIVO: dict[tuple[str, int, int], str] = {}


def hash_arquivo(caminho):
    p = Path(caminho)
    try:
        st = p.stat()
        chave = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        chave = None
    if chave is not None and chave in _CACHE_HASH_ARQUIVO:
        return _CACHE_HASH_ARQUIVO[chave]
    h = hashlib.sha256()
    with open(p, 'rb') as arquivo:
        for dados in iter(lambda: arquivo.read(CHUNK), b''):
            h.update(dados)
    digest = h.hexdigest()
    if chave is not None:
        if len(_CACHE_HASH_ARQUIVO) > 2048:
            _CACHE_HASH_ARQUIVO.clear()
        _CACHE_HASH_ARQUIVO[chave] = digest
    return digest


def chave_segmento(parametros):
    return hashlib.sha256(json.dumps(parametros, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def salvar_json(caminho, dados, sincronizar=True):
    caminho = Path(caminho)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix='.ttsbr-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as arquivo:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
            arquivo.flush()
            if sincronizar:
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
            digest_wav = hashlib.sha256()
            with open(temporario, 'rb') as f_wav:
                for b_chunk in iter(lambda: f_wav.read(CHUNK), b''):
                    digest_wav.update(b_chunk)
            sha_wav = digest_wav.hexdigest()
            os.replace(temporario, destino)
            try:
                st_dest = destino.stat()
                _CACHE_HASH_ARQUIVO[(str(destino.resolve()), st_dest.st_mtime_ns, st_dest.st_size)] = sha_wav
            except OSError:
                pass
            salvar_json(metadados, {'parametros': parametros, 'frames': frames,
                                    'sha256': sha_wav}, sincronizar=False)
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


def escapar_ffmetadata(texto):
    """Escapa caracteres especiais para o formato FFMETADATA1 do FFmpeg."""
    if not texto:
        return ''
    t = str(texto).replace('\\', '\\\\')
    for c in ('=', ';', '#'):
        t = t.replace(c, f'\\{c}')
    return t.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\\n')


def gerar_ffmetadata(titulo=None, autor=None, capitulos=()):
    """Gera o conteúdo de metadados e capítulos no formato FFMETADATA1 do FFmpeg."""
    linhas = [';FFMETADATA1']
    if titulo and str(titulo).strip():
        t = escapar_ffmetadata(str(titulo).strip())
        linhas.append(f'title={t}')
        linhas.append(f'album={t}')
    if autor and str(autor).strip():
        a = escapar_ffmetadata(str(autor).strip())
        linhas.append(f'artist={a}')
        linhas.append(f'album_artist={a}')
        linhas.append(f'composer={a}')
    for idx, cap in enumerate(capitulos or (), 1):
        ini_ms = max(0, int(round(float(cap.get('inicio_s', 0.0)) * 1000)))
        fim_ms = max(ini_ms, int(round(float(cap.get('fim_s', cap.get('inicio_s', 0.0))) * 1000)))
        if fim_ms <= ini_ms:
            fim_ms = ini_ms + 100
        nome_cap = cap.get('titulo') or f'Capítulo {idx}'
        linhas.append('\n[CHAPTER]')
        linhas.append('TIMEBASE=1/1000')
        linhas.append(f'START={ini_ms}')
        linhas.append(f'END={fim_ms}')
        linhas.append(f'title={escapar_ffmetadata(nome_cap)}')
    return '\n'.join(linhas) + '\n'


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


def medir_loudness_final(caminho, ffmpeg):
    """Mede nível integrado (LUFS), true peak (dBTP), LRA e duração do arquivo final via FFmpeg."""
    caminho = Path(caminho)
    duracao_s = None
    if caminho.suffix.lower() == '.wav':
        try:
            with wave.open(str(caminho), 'rb') as audio:
                duracao_s = audio.getnframes() / audio.getframerate()
        except (OSError, wave.Error, EOFError, ZeroDivisionError):
            pass
    saida = {'arquivo': str(caminho.resolve()), 'formato': caminho.suffix.lstrip('.').lower(),
             'tamanho_bytes': caminho.stat().st_size, 'duracao_s': duracao_s,
             'lufs_integrado': None, 'true_peak_dbtp': None, 'lra_lu': None}
    if caminho.suffix.lower() == '.wav':
        try:
            m = medir_segmento(caminho)
            saida.update(duracao_s=m['duracao_s'], rms_dbfs=m['rms_dbfs'], pico_dbfs=m['pico_dbfs'],
                         avisos_pcm=m['avisos'])
        except (OSError, ValueError, wave.Error):
            pass
    if not ffmpeg:
        return saida
    try:
        processo = subprocess.run(
            [str(ffmpeg), '-nostdin', '-hide_banner', '-i', str(caminho),
             '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=120,
        )
        blocos = re.findall(r'\{\s*"input_i"\s*:.*?\n\}', processo.stderr, flags=re.DOTALL)
        if blocos:
            dados = json.loads(blocos[-1])
            for chave_json, chave_out in (('input_i', 'lufs_integrado'),
                                          ('input_tp', 'true_peak_dbtp'),
                                          ('input_lra', 'lra_lu')):
                try:
                    val = float(dados.get(chave_json, 'nan'))
                    if val == val and abs(val) != float('inf'):
                        saida[chave_out] = round(val, 2)
                except (TypeError, ValueError):
                    pass
        if saida['duracao_s'] is None:
            m_dur = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', processo.stderr)
            if m_dur:
                h, mi, s = int(m_dur[1]), int(m_dur[2]), float(m_dur[3])
                saida['duracao_s'] = round(h * 3600 + mi * 60 + s, 3)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return saida


def exportar(eventos, base, formatos, ffmpeg, segmentos=(), lufs=None, taxa_amostragem=None,
             trilha=None, volume_trilha=-18.0, metadados=None, capitulos=(), capa=None):
    """Monta WAV em disco e substitui cada saída somente após sua conclusão."""
    base = Path(base)
    precisa_audio = any(f in ('wav', 'mp3', 'm4b') for f in formatos)
    sr_alvo = int(taxa_amostragem) if taxa_amostragem is not None else SR
    opcoes_audio = []
    opcoes_meta = []
    for k, v in (metadados or {}).items():
        if v is not None and str(v).strip():
            opcoes_meta.extend(['-metadata', f'{k}={str(v).strip()}'])
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

    capa_valida = Path(capa).resolve() if capa and Path(capa).is_file() else None

    loudness_cache = None
    metricas_finais = {}
    with tempfile.TemporaryDirectory(dir=base.parent, prefix='.ttsbr-montagem-') as pasta:
        wav = Path(pasta) / 'montagem.wav'
        if precisa_audio:
            montar_wav(eventos, wav)
        for formato in formatos:
            destino = base.parent / f'{base.name}.{formato}'
            temporario = Path(pasta) / f'final.{formato}'
            if formato in ('srt', 'vtt'):
                temporario.write_text(gerar_legenda(segmentos, formato), encoding='utf-8')
            elif formato == 'wav' and not opcoes_audio and not opcoes_meta:
                shutil.copyfile(wav, temporario)
            elif formato == 'wav':
                processo = subprocess.run(
                    [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                     '-i', str(wav), *opcoes_audio, *opcoes_meta, '-c:a', 'pcm_s16le', str(temporario)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação WAV: {processo.stderr.strip()}')
            elif formato == 'm4b':
                ffmeta_path = Path(pasta) / 'metadata.txt'
                meta_dict = dict(metadados or {})
                titulo = meta_dict.get('title') or base.name
                autor = meta_dict.get('artist') or meta_dict.get('author')
                ffmeta_path.write_text(gerar_ffmetadata(titulo=titulo, autor=autor, capitulos=capitulos), encoding='utf-8')

                cmd_m4b = [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
                           '-i', str(wav), '-f', 'ffmetadata', '-i', str(ffmeta_path)]
                idx_capa = None
                if capa_valida:
                    cmd_m4b.extend(['-i', str(capa_valida)])
                    idx_capa = 2

                if trilha:
                    cmd_m4b.extend(opcoes_audio)
                else:
                    cmd_m4b.extend(['-map', '0:a'])
                    if lufs is not None:
                        cmd_m4b.extend(['-af', f'loudnorm=I={float(lufs)}:TP=-1.5:LRA=11'])
                    if sr_alvo != SR:
                        cmd_m4b.extend(['-ar', str(sr_alvo)])

                cmd_m4b.extend(['-map_metadata', '1'])
                if idx_capa is not None:
                    cmd_m4b.extend(['-map', f'{idx_capa}:v', '-c:v', 'copy', '-disposition:v:0', 'attached_pic'])

                cmd_m4b.extend(['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(temporario)])
                processo = subprocess.run(
                    cmd_m4b,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação M4B: {processo.stderr.strip()}')
            elif formato == 'mp3':
                cmd_mp3 = [str(ffmpeg), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(wav)]
                if capa_valida:
                    cmd_mp3.extend(['-i', str(capa_valida)])
                cmd_mp3.extend([*opcoes_audio, *opcoes_meta])
                if capa_valida:
                    cmd_mp3.extend(['-map', '0:a', '-map', '1:v', '-c:v', 'copy',
                                    '-id3v2_version', '3', '-metadata:s:v', 'title="Album cover"',
                                    '-metadata:s:v', 'comment="Cover (front)"'])
                cmd_mp3.extend(['-b:a', '192k', str(temporario)])
                processo = subprocess.run(
                    cmd_mp3,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if processo.returncode:
                    raise RuntimeError(f'Falha na exportação MP3: {processo.stderr.strip()}')
            else:
                raise ValueError(f'Formato de exportação não suportado: {formato}')
            os.replace(temporario, destino)
            print(f'Gerado: {destino}')
            if formato in ('wav', 'mp3', 'm4b'):
                if loudness_cache is None:
                    medicao = medir_loudness_final(destino, ffmpeg)
                    loudness_cache = {
                        'duracao_s': medicao.get('duracao_s'),
                        'lufs_integrado': medicao.get('lufs_integrado'),
                        'true_peak_dbtp': medicao.get('true_peak_dbtp'),
                        'lra_lu': medicao.get('lra_lu'),
                    }
                    metricas_finais[formato] = medicao
                else:
                    medicao = medir_loudness_final(destino, None)
                    for k_lufs in ('duracao_s', 'lufs_integrado', 'true_peak_dbtp', 'lra_lu'):
                        if medicao.get(k_lufs) is None:
                            medicao[k_lufs] = loudness_cache.get(k_lufs)
                    metricas_finais[formato] = medicao
    return metricas_finais
