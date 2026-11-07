#!/usr/bin/env python3
"""Constrói distribuições a partir de uma cópia pública, sem metadados do volume."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def copiar_fontes(destino):
    cfg = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    arquivos = {'pyproject.toml', 'MANIFEST.in'}
    arquivos.update(n + '.py' for n in cfg['tool']['setuptools']['py-modules'])
    for grupo in cfg['tool']['setuptools']['data-files'].values():
        arquivos.update(grupo)
    arquivos.update(str(p.relative_to(ROOT)) for p in (ROOT / 'tests').glob('test_*.py'))
    arquivos.add('scripts/construir.py')
    for relativo in arquivos:
        alvo = destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        # copyfile não transporta atributos estendidos e metadados AppleDouble.
        shutil.copyfile(ROOT / relativo, alvo)


def construir(destino):
    destino = Path(destino).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ttsbr-build-') as tmp:
        fonte = Path(tmp) / 'fonte'
        saida_tmp = Path(tmp) / 'saida'
        saida_tmp.mkdir(parents=True, exist_ok=True)
        copiar_fontes(fonte)
        env = os.environ.copy()
        env['COPYFILE_DISABLE'] = '1'
        r = subprocess.run([sys.executable, '-c', 'import build.__main__'], capture_output=True)
        if r.returncode == 0:
            subprocess.run([sys.executable, '-m', 'build', '--sdist', '--wheel',
                            '--outdir', str(saida_tmp), str(fonte)], check=True, env=env)
        else:
            for etapa in ('build_sdist', 'build_wheel'):
                subprocess.run(
                    [sys.executable, '-c', f'import sys, setuptools.build_meta as b; b.{etapa}(sys.argv[1])', str(saida_tmp)],
                    cwd=str(fonte), check=True, env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
        for artefato in saida_tmp.iterdir():
            if artefato.is_file() and not artefato.name.startswith('._'):
                shutil.copyfile(artefato, destino / artefato.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--saida', type=Path, default=ROOT / 'dist')
    args = ap.parse_args()
    construir(args.saida)


if __name__ == '__main__':
    main()
