"""Supervisiona o experimento OmniVoice em Python separado e preserva saídas existentes."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import wave

from supervisor import GrupoWindows, encerrar_grupo, vivo_grupo


def hash_arquivo(caminho):
    h = hashlib.sha256()
    with Path(caminho).open('rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b''):
            h.update(bloco)
    return h.hexdigest()


def _hash_blob_git(caminho):
    """SHA-1 de blob Git, usado pelo Hugging Face como ETag de arquivos fora do LFS."""
    caminho = Path(caminho)
    h = hashlib.sha1(b'blob %d\0' % caminho.stat().st_size)
    with caminho.open('rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b''):
            h.update(bloco)
    return h.hexdigest()


def verificar_pesos(modelo, revisao):
    """Confere cada arquivo local contra os metadados de download do Hugging Face.

    Exige que todos os arquivos pertençam à revisão informada e que o conteúdo
    corresponda ao ETag registrado (SHA-256 no LFS, SHA-1 de blob Git nos demais).
    """
    modelo = Path(modelo)
    base = modelo / '.cache' / 'huggingface' / 'download'
    if not base.is_dir():
        raise ValueError('Pesos sem metadados de download do Hugging Face; não é possível verificar a revisão.')
    arquivos = sorted(p for p in modelo.rglob('*') if p.is_file()
                      and '.cache' not in p.relative_to(modelo).parts and not p.name.startswith('._'))
    metadados = sorted(p for p in base.rglob('*.metadata') if not p.name.startswith('._'))
    relativos = {p.relative_to(modelo).as_posix() for p in arquivos}
    registrados = {p.relative_to(base).as_posix()[:-len('.metadata')] for p in metadados}
    if not relativos:
        raise ValueError('Diretório de pesos vazio.')
    if relativos != registrados:
        faltando = sorted(registrados - relativos)[:3]
        extras = sorted(relativos - registrados)[:3]
        raise ValueError(f'Arquivos de pesos não conferem com o download (ausentes: {faltando}; sem registro: {extras}).')
    agregado = hashlib.sha256()
    for rel in sorted(relativos):
        linhas = (base / (rel + '.metadata')).read_text(encoding='utf-8').splitlines()
        if len(linhas) < 2:
            raise ValueError(f'Metadados inválidos para {rel}.')
        commit, etag = linhas[0].strip(), linhas[1].strip().strip('"').lower()
        if commit != revisao:
            raise ValueError(f'{rel} pertence a outra revisão ({commit[:12]}).')
        if len(etag) == 64:
            obtido = hash_arquivo(modelo / rel)
        elif len(etag) == 40:
            obtido = _hash_blob_git(modelo / rel)
        else:
            raise ValueError(f'ETag não reconhecido para {rel}.')
        if obtido != etag:
            raise ValueError(f'Conteúdo de {rel} não corresponde ao download registrado.')
        agregado.update(f'{rel}\0{etag}\n'.encode('utf-8'))
    return {'pesos_arquivos_verificados': len(relativos), 'pesos_manifesto_sha256': agregado.hexdigest()}


def executar(python, modelo, referencia, transcricao, texto, idioma, destino,
             revisao, dispositivo='cpu', timeout=900, worker=None):
    python = Path(python).expanduser().absolute()  # Não resolver symlink: preserva o ambiente virtual.
    modelo = Path(modelo).expanduser().resolve()
    referencia = Path(referencia).expanduser().resolve()
    destino = Path(destino).expanduser().absolute()
    if not python.is_file() or not modelo.is_dir() or not referencia.is_file():
        raise ValueError('Python, diretório local do modelo ou referência indisponível.')
    if not isinstance(revisao, str) or not revisao.strip():
        raise ValueError('Informe a revisão exata dos pesos do modelo.')
    if not isinstance(texto, str) or not texto.strip() or not isinstance(transcricao, str) or not transcricao.strip():
        raise ValueError('Texto de teste e transcrição da referência são obrigatórios.')
    if idioma not in ('pt', 'es') or dispositivo not in ('cpu', 'mps', 'cuda'):
        raise ValueError('Idioma ou dispositivo não suportado.')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout deve ser um número positivo e finito.')
    if destino.exists():
        raise FileExistsError('O arquivo de saída já existe; escolha outro nome.')
    if not destino.parent.is_dir():
        raise ValueError('A pasta de destino deve existir.')
    worker = Path(worker or Path(__file__).with_name('omnivoice_experimental.py')).absolute()
    if not worker.is_file():
        raise ValueError('Worker experimental não encontrado.')
    pesos = verificar_pesos(modelo, revisao.strip())
    referencia_hash = hash_arquivo(referencia)
    with tempfile.TemporaryDirectory(prefix='.ttsbr-comparacao-', dir=destino.parent) as pasta:
        pasta = Path(pasta)
        wav = pasta / 'saida.wav'
        gate = pasta / 'iniciar.flag'
        pedido = {'modelo': str(modelo), 'referencia': str(referencia), 'transcricao': transcricao,
                  'texto': texto, 'idioma': idioma, 'saida': str(wav), 'dispositivo': dispositivo}
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TTSBR_EXPERIMENTO_GATE=str(gate),
                   PYTHONIOENCODING='utf-8')
        grupo = GrupoWindows()
        processo = None
        opcoes = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        inicio = time.monotonic()
        try:
            with tempfile.TemporaryFile() as logs:
                processo = subprocess.Popen([str(python), '-u', str(worker), '--worker'], stdin=subprocess.PIPE,
                                           stdout=logs, stderr=logs, env=env, **opcoes)
                try:
                    grupo.associar(processo)
                except Exception:
                    processo.kill(); processo.wait(timeout=5)
                    raise
                gate.touch()
                try:
                    processo.communicate(json.dumps(pedido, ensure_ascii=False).encode('utf-8'), timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    while not encerrar_grupo(processo, grupo): time.sleep(.2)
                    processo.wait()
                    raise TimeoutError('O worker excedeu o tempo limite; processos encerrados.') from exc
                if vivo_grupo(processo, grupo):
                    while not encerrar_grupo(processo, grupo): time.sleep(.2)
                if processo.returncode:
                    raise RuntimeError('O worker experimental falhou; confira o ambiente e os pesos locais.')
                tamanho = logs.tell()
                if tamanho > 1024 * 1024:
                    raise ValueError('O worker produziu um registro maior que o limite permitido.')
                logs.seek(0)
                linhas = logs.read().decode('utf-8', errors='replace').splitlines()
                try:
                    resposta = json.loads(linhas[-1])
                    resultado = resposta['resultado']
                except (IndexError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError('Resposta inválida do worker experimental.') from exc
            with wave.open(str(wav), 'rb') as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000) or not audio.getnframes():
                    raise ValueError('O worker produziu WAV incompatível ou vazio.')
                duracao = audio.getnframes() / audio.getframerate()
            if not isinstance(resultado, dict) or resultado.get('motor') != 'omnivoice_experimental':
                raise ValueError('Identidade de motor inválida na resposta.')
            for campo in ('carga_s', 'primeira_sintese_s', 'sintese_quente_s'):
                valor = resultado.get(campo)
                if type(valor) not in (int, float) or not math.isfinite(valor) or valor < 0:
                    raise ValueError('Medição inválida do worker.')
            if hash_arquivo(referencia) != referencia_hash:
                raise ValueError('A referência mudou durante a execução; resultado não publicado.')
            resultado.update(pesos)
            resultado.update(revisao_modelo=revisao.strip(), revisao_verificada=True,
                             referencia_sha256=referencia_hash,
                             texto_sha256=hashlib.sha256(texto.encode()).hexdigest(),
                             transcricao_sha256=hashlib.sha256(transcricao.encode()).hexdigest(),
                             duracao_s=duracao, rtf_quente=resultado['sintese_quente_s'] / duracao,
                             tempo_total_s=time.monotonic() - inicio,
                             saida_sha256=hash_arquivo(wav))
            # Criação exclusiva também funciona em volumes que não suportam hard links.
            criado = False
            try:
                with destino.open('xb') as final:
                    criado = True
                    with wav.open('rb') as fonte:
                        shutil.copyfileobj(fonte, final, 1024 * 1024)
                        final.flush()
                        os.fsync(final.fileno())
            except FileExistsError:
                raise
            except Exception:
                if criado:
                    destino.unlink(missing_ok=True)
                raise
            return resultado
        finally:
            if processo and processo.poll() is None:
                while not encerrar_grupo(processo, grupo): time.sleep(.2)
                processo.wait()
            grupo.fechar()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    for nome in ('python', 'modelo', 'referencia', 'transcricao-arquivo', 'texto-arquivo', 'saida', 'revisao'):
        ap.add_argument('--' + nome, required=True)
    ap.add_argument('--idioma', choices=('pt', 'es'), required=True)
    ap.add_argument('--dispositivo', choices=('cpu', 'mps', 'cuda'), default='cpu')
    ap.add_argument('--timeout', type=float, default=900)
    args = ap.parse_args(argv)
    try:
        transcricao = Path(args.transcricao_arquivo).read_text(encoding='utf-8-sig')
        texto = Path(args.texto_arquivo).read_text(encoding='utf-8-sig')
        resultado = executar(args.python, args.modelo, args.referencia, transcricao, texto,
                             args.idioma, args.saida, args.revisao, args.dispositivo, args.timeout)
        print(json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError, wave.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
