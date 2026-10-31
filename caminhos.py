"""Localização de recursos distribuídos e dados graváveis da aplicação."""
import os
from pathlib import Path
import sys

CODIGO = Path(__file__).resolve().parent


def pasta_dados():
    """No checkout usa a raiz; instalado usa a pasta de dados do usuário."""
    if os.environ.get('TTSBR_HOME'):
        return Path(os.environ['TTSBR_HOME']).expanduser().resolve()
    if (CODIGO / 'pyproject.toml').is_file():
        return CODIGO
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'TTSBR'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'TTSBR'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'ttsbr'


def recurso(relativo):
    local = CODIGO / relativo
    if local.is_file():
        return local
    return Path(sys.prefix) / 'share' / 'ttsbr' / relativo
