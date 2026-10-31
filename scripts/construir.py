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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--saida', type=Path, default=ROOT / 'dist')
    args = ap.parse_args()
    destino = args.saida.resolve()
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ttsbr-build-') as tmp:
        fonte = Path(tmp) / 'fonte'
        copiar_fontes(fonte)
        env = os.environ.copy()
        env['COPYFILE_DISABLE'] = '1'
        subprocess.run([sys.executable, '-m', 'build', '--sdist', '--wheel',
                        '--outdir', str(destino), str(fonte)], check=True, env=env)


if __name__ == '__main__':
    main()
