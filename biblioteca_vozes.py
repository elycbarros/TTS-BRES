"""Biblioteca privada de referências. SQLite e arquivos imutáveis; nenhum modelo TTS."""
import argparse
from array import array
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import wave

from caminhos import pasta_dados
from contratos import validar, carregar, identificador, caminho_relativo

MAX_BYTES = 100 * 1024 * 1024
MAX_SEGUNDOS = 75
EXTENSOES = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.aac', '.aiff'}


def hash_arquivo(caminho):
    digest = hashlib.sha256()
    with Path(caminho).open('rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(65536), b''):
            digest.update(bloco)
    return digest.hexdigest()


def ffmpeg_disponivel():
    executavel = shutil.which('ffmpeg')
    if executavel:
        return executavel
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ValueError('Instale FFmpeg ou imageio-ffmpeg no Python selecionado.') from exc


def converter(origem, destino, limpar=False):
    filtros = ['-af', 'highpass=f=80,lowpass=f=10000,afftdn=nf=-25,loudnorm=I=-18:TP=-1.5:LRA=11'] if limpar else []
    comando = [ffmpeg_disponivel(), '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
               '-protocol_whitelist', 'file,pipe', '-i', str(origem),
               '-t', str(MAX_SEGUNDOS + 1), '-vn', *filtros,
               '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(destino)]
    try:
        resultado = subprocess.run(comando, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Não foi possível decodificar a amostra dentro do tempo limite.') from exc
    if resultado.returncode:
        raise ValueError('Áudio inválido ou formato não decodificável pelo FFmpeg disponível.')


def medir(caminho):
    total = saturadas = silenciosas = 0
    energia = pico = 0.0
    with wave.open(str(caminho), 'rb') as arquivo:
        if (arquivo.getnchannels(), arquivo.getsampwidth(), arquivo.getframerate()) != (1, 2, 24000):
            raise ValueError('A prévia deve ser WAV PCM mono, 16 bits, 24 kHz.')
        for bloco in iter(lambda: arquivo.readframes(32768), b''):
            valores = array('h', bloco)
            if sys.byteorder != 'little':
                valores.byteswap()
            for inteiro in valores:
                valor = abs(inteiro) / 32768
                total += 1
                energia += valor * valor
                pico = max(pico, valor)
                saturadas += valor >= 0.999
                silenciosas += valor < 0.001
    if not total:
        raise ValueError('A amostra não contém áudio.')
    duracao = total / 24000
    if duracao > MAX_SEGUNDOS:
        raise ValueError('Recorte a amostra para até 75 segundos; nenhum trecho será truncado ao importar.')
    rms = math.sqrt(energia / total)
    avisos = []
    if duracao < 6: avisos.append('amostra_curta')
    if duracao > 30: avisos.append('amostra_longa')
    if rms < 0.001: avisos.append('silencio_ou_nivel_muito_baixo')
    if silenciosas / total > 0.5: avisos.append('muitas_amostras_em_nivel_muito_baixo')
    if saturadas: avisos.append('amostras_proximas_da_saturacao')
    return {'duracao_s': duracao, 'canais': 1, 'taxa_hz': 24000, 'bits': 16,
            'rms_dbfs': 20 * math.log10(rms) if rms else None,
            'pico_dbfs': 20 * math.log10(pico) if pico else None,
            'fracao_saturada': saturadas / total, 'avisos': avisos}


def formato_original(caminho):
    """Metadados do original quando o leitor instalado suporta o formato."""
    try:
        import soundfile
        info = soundfile.info(str(caminho))
        return {'taxa_hz': info.samplerate, 'canais': info.channels,
                'duracao_s': info.duration, 'formato': info.format, 'subtipo': info.subtype}
    except (ImportError, RuntimeError, OSError):
        return {'estado': 'metadados_originais_indisponiveis'}


class BibliotecaVozes:
    def __init__(self, raiz=None):
        self.raiz = Path(raiz or (pasta_dados() / 'local' / 'vozes')).resolve()
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.banco = self.raiz / 'biblioteca.sqlite3'
        if self.banco.is_symlink():
            raise ValueError('O banco da biblioteca não pode ser link simbólico.')
        with closing(self._conectar()) as banco, banco:
            banco.execute('BEGIN IMMEDIATE')
            versao = banco.execute('PRAGMA user_version').fetchone()[0]
            if versao not in (0, 1):
                raise ValueError('Versão da biblioteca não suportada; preserve o banco e use uma versão compatível.')
            tabelas = banco.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if versao == 0 and tabelas:
                raise ValueError('Banco sem versão reconhecida; importação automática não permitida.')
            banco.execute('CREATE TABLE IF NOT EXISTS vozes (id TEXT PRIMARY KEY, documento TEXT NOT NULL, '
                          'audio TEXT NOT NULL, removida INTEGER NOT NULL DEFAULT 0)')
            banco.execute('CREATE TABLE IF NOT EXISTS usos (voz_id TEXT NOT NULL REFERENCES vozes(id), '
                          'projeto_id TEXT NOT NULL, PRIMARY KEY(voz_id, projeto_id))')
            banco.execute('PRAGMA user_version=1')

    def _conectar(self):
        banco = sqlite3.connect(self.banco, timeout=10)
        banco.execute('PRAGMA foreign_keys=ON')
        return banco

    def _arquivo(self, relativo):
        if not caminho_relativo(relativo):
            raise ValueError('Caminho interno inválido.')
        alvo = self.raiz
        for parte in relativo.split('/'):
            alvo = alvo / parte
            if alvo.is_symlink():
                raise ValueError('Links simbólicos não são aceitos nos arquivos da biblioteca.')
        if not alvo.resolve().is_relative_to(self.raiz):
            raise ValueError('Arquivo fora da biblioteca.')
        return alvo

    def importar(self, origem, nome, idioma='pt', estilo='neutra', transcricao='',
                 autorizacao=False, limpar=False):
        if autorizacao is not True:
            raise ValueError('Confirme que tem autorização para gravar e usar essa voz.')
        origem = Path(origem)
        if origem.suffix.lower() not in EXTENSOES or not origem.is_file():
            raise ValueError('Selecione um arquivo de áudio suportado.')
        if not 0 < origem.stat().st_size <= MAX_BYTES:
            raise ValueError('Amostra vazia ou maior que 100 MiB.')
        identidade = uuid.uuid4().hex
        relativo = f'referencias/{identidade}'
        pasta_final = self._arquivo(relativo)
        pasta_final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.importacao-', dir=self.raiz) as tmp:
            pasta = Path(tmp)
            original = pasta / ('original' + origem.suffix.lower())
            with origem.open('rb') as entrada, original.open('xb') as saida:
                total = 0
                for bloco in iter(lambda: entrada.read(65536), b''):
                    total += len(bloco)
                    if total > MAX_BYTES:
                        raise ValueError('Amostra maior que 100 MiB.')
                    saida.write(bloco)
            previa = pasta / 'previa.wav'
            converter(original, previa)
            metricas = medir(previa)
            # A limpeza é uma derivação, jamais substitui os bytes originais ou a prévia sem filtros.
            escolhido = previa
            if limpar:
                escolhido = pasta / 'limpa.wav'
                converter(original, escolhido, limpar=True)
                medir(escolhido)
            documento = validar({'formato': 'ttsbr.voz', 'versao_esquema': 1, 'id': identidade,
                                 'dados': {'nome': nome, 'idioma': idioma, 'estilo': estilo,
                                           'referencia': f'{relativo}/{original.name}',
                                           'sha256': hash_arquivo(original), 'transcricao': transcricao,
                                           'autorizacao_declarada': True}})
            metadados = {'previa': f'{relativo}/previa.wav', 'selecionada': f'{relativo}/{escolhido.name}',
                         'sha256_previa': hash_arquivo(previa), 'sha256_selecionada': hash_arquivo(escolhido),
                         'metricas': metricas, 'limpeza_aplicada': bool(limpar),
                         'original': formato_original(original)}
            os.replace(pasta, pasta_final)
            try:
                with closing(self._conectar()) as banco, banco:
                    banco.execute('INSERT INTO vozes(id,documento,audio) VALUES(?,?,?)',
                                  (identidade, json.dumps(documento, ensure_ascii=False), json.dumps(metadados)))
            except Exception:
                shutil.rmtree(pasta_final)
                raise
        return self.obter(identidade)

    def obter(self, identidade, incluir_removidas=False):
        if not identificador(identidade):
            raise ValueError('ID de voz inválido.')
        with closing(self._conectar()) as banco:
            linha = banco.execute('SELECT documento,audio FROM vozes WHERE id=? AND (removida=0 OR ?)',
                                  (identidade, bool(incluir_removidas))).fetchone()
        if not linha:
            raise ValueError('Perfil não encontrado ou removido.')
        return {'documento': carregar(linha[0]), 'audio': json.loads(linha[1])}

    def listar(self, removidas=False):
        with closing(self._conectar()) as banco:
            ids = [linha[0] for linha in banco.execute('SELECT id FROM vozes WHERE removida=? ORDER BY rowid',
                                                      (int(removidas),))]
        return [self.obter(identidade, incluir_removidas=removidas) for identidade in ids]

    def resolver(self, identidade, original=False):
        perfil = self.obter(identidade)
        return self._resolver_perfil(perfil, original)

    def _resolver_perfil(self, perfil, original=False):
        dados, audio = perfil['documento']['dados'], perfil['audio']
        if dados['autorizacao_declarada'] is not True:
            raise ValueError('Perfil sem autorização declarada.')
        caminhos = [(dados['referencia'], dados['sha256']),
                    (audio['selecionada'], audio['sha256_selecionada'])]
        for relativo, esperado in caminhos:
            arquivo = self._arquivo(relativo)
            if not arquivo.is_file():
                raise ValueError('Referência ausente. Restaure o backup ou importe uma nova tomada.')
            if hash_arquivo(arquivo) != esperado:
                raise ValueError('Referência alterada. Importe uma nova tomada para usar os novos bytes.')
        return self._arquivo(dados['referencia'] if original else audio['selecionada'])

    def renomear(self, identidade, nome):
        return self.atualizar(identidade, nome=nome)

    def atualizar(self, identidade, **campos):
        if set(campos) - {'nome', 'idioma', 'estilo', 'transcricao'}:
            raise ValueError('Só é possível editar nome, idioma, estilo e transcrição.')
        perfil = self.obter(identidade)
        perfil['documento']['dados'].update(campos)
        documento = validar(perfil['documento'])
        with closing(self._conectar()) as banco, banco:
            banco.execute('UPDATE vozes SET documento=? WHERE id=? AND removida=0',
                          (json.dumps(documento, ensure_ascii=False), identidade))

    def registrar_uso(self, identidade, projeto_id):
        self.obter(identidade)
        if not identificador(projeto_id):
            raise ValueError('ID de projeto inválido.')
        with closing(self._conectar()) as banco, banco:
            banco.execute('BEGIN IMMEDIATE')
            if not banco.execute('SELECT 1 FROM vozes WHERE id=? AND removida=0', (identidade,)).fetchone():
                raise ValueError('Perfil não encontrado ou removido.')
            banco.execute('INSERT OR IGNORE INTO usos VALUES(?,?)', (identidade, projeto_id))

    def liberar_uso(self, identidade, projeto_id):
        with closing(self._conectar()) as banco, banco:
            banco.execute('DELETE FROM usos WHERE voz_id=? AND projeto_id=?', (identidade, projeto_id))

    def listar_usos(self, prefixo):
        with closing(self._conectar()) as banco:
            return [(r[0], r[1]) for r in banco.execute('SELECT voz_id,projeto_id FROM usos') if r[1].startswith(prefixo)]

    def reconciliar_usos(self, projeto_id, identidades):
        identidades = set(identidades)
        with closing(self._conectar()) as banco, banco:
            banco.execute('BEGIN IMMEDIATE')
            for identidade in identidades:
                if not banco.execute('SELECT 1 FROM vozes WHERE id=? AND removida=0', (identidade,)).fetchone():
                    raise ValueError('Perfil vinculado não está disponível.')
                banco.execute('INSERT OR IGNORE INTO usos VALUES(?,?)', (identidade, projeto_id))
            atuais = banco.execute('SELECT voz_id FROM usos WHERE projeto_id=?', (projeto_id,)).fetchall()
            for (identidade,) in atuais:
                if identidade not in identidades:
                    banco.execute('DELETE FROM usos WHERE voz_id=? AND projeto_id=?', (identidade, projeto_id))

    def remover(self, identidade):
        self.obter(identidade)
        with closing(self._conectar()) as banco, banco:
            banco.execute('BEGIN IMMEDIATE')
            if banco.execute('SELECT 1 FROM usos WHERE voz_id=?', (identidade,)).fetchone():
                raise ValueError('Perfil vinculado a um projeto. Remova o vínculo antes de excluir.')
            # Remoção lógica preserva snapshots/saídas e permite backup consistente de arquivos imutáveis.
            banco.execute('UPDATE vozes SET removida=1 WHERE id=?', (identidade,))

    def restaurar(self, identidade):
        with closing(self._conectar()) as banco, banco:
            banco.execute('BEGIN IMMEDIATE')
            perfil = self.obter(identidade, incluir_removidas=True)
            self._resolver_perfil(perfil)
            banco.execute('UPDATE vozes SET removida=0 WHERE id=?', (identidade,))

    def backup(self, destino):
        destino = Path(destino).resolve()
        if destino.exists() or destino.is_relative_to(self.raiz):
            raise ValueError('Escolha um novo diretório fora da biblioteca para o backup.')
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.backup-vozes-', dir=destino.parent) as tmp:
            copia = Path(tmp) / 'biblioteca'
            copia.mkdir()
            with closing(self._conectar()) as origem, closing(sqlite3.connect(copia / self.banco.name)) as alvo:
                origem.backup(alvo)
                registros = alvo.execute('SELECT documento,audio FROM vozes').fetchall()
            for documento, audio in registros:
                doc, meta = carregar(documento), json.loads(audio)
                arquivos = {doc['dados']['referencia']: doc['dados']['sha256'],
                            meta['previa']: meta['sha256_previa'],
                            meta['selecionada']: meta['sha256_selecionada']}
                for relativo, esperado in arquivos.items():
                    fonte = self._arquivo(relativo)
                    target = copia / relativo
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(fonte, target)
                    if hash_arquivo(target) != esperado:
                        raise ValueError('Falha ao verificar os arquivos do backup.')
            os.replace(copia, destino)
        return destino


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raiz', type=Path, help='Pasta privada alternativa.')
    sub = parser.add_subparsers(dest='acao', required=True)
    lista = sub.add_parser('listar'); lista.add_argument('--removidas', action='store_true')
    importar = sub.add_parser('importar')
    importar.add_argument('arquivo', type=Path)
    importar.add_argument('--nome', required=True)
    importar.add_argument('--idioma', choices=('pt', 'es'), default='pt')
    importar.add_argument('--estilo', default='neutra')
    importar.add_argument('--transcricao', default='')
    importar.add_argument('--autorizada', action='store_true')
    importar.add_argument('--limpar', action='store_true')
    for nome in ('resolver', 'remover', 'restaurar', 'renomear'):
        comando = sub.add_parser(nome); comando.add_argument('id')
        if nome == 'renomear': comando.add_argument('nome')
    copia = sub.add_parser('backup'); copia.add_argument('destino', type=Path)
    args = parser.parse_args(argv)
    try:
        biblioteca = BibliotecaVozes(args.raiz)
        if args.acao == 'importar':
            resultado = biblioteca.importar(args.arquivo, args.nome, args.idioma, args.estilo,
                                            args.transcricao, args.autorizada, args.limpar)
        elif args.acao == 'listar': resultado = biblioteca.listar(args.removidas)
        elif args.acao == 'resolver': resultado = str(biblioteca.resolver(args.id))
        elif args.acao == 'remover': resultado = biblioteca.remover(args.id)
        elif args.acao == 'restaurar': resultado = biblioteca.restaurar(args.id)
        elif args.acao == 'renomear': resultado = biblioteca.renomear(args.id, args.nome)
        else: resultado = str(biblioteca.backup(args.destino))
        print(json.dumps({'resultado': resultado}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, wave.Error) as exc:
        print(json.dumps({'erro': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
