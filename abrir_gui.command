#!/bin/sh
# A janela usa Tkinter; o ambiente da síntese é escolhido dentro da GUI.
cd "$(dirname "$0")" || exit 1
python3 gui.py
codigo=$?
if [ "$codigo" -ne 0 ]; then
    printf '\nNão foi possível iniciar a GUI. Consulte docs/GUI.md.\n'
    printf 'Pressione Enter para fechar.'
    read -r resposta
fi
exit "$codigo"
