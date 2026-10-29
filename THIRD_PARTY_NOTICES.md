# Licenças e componentes de terceiros

[README](README.md#licenca) · [Licença MIT do código original](LICENSE)

A licença MIT deste repositório cobre o código e a documentação originais do TTSBR. Ela não relicencia dependências, modelos, pesos, gravações de referência ou saídas de modelos de terceiros. Os avisos e condições aplicáveis a esses componentes devem ser preservados.

## Modelo XTTS v2 e áudio gerado

O XTTS v2 é disponibilizado sob a **Coqui Public Model License 1.0.0 (CPML)**. O texto publicado permite uso não comercial do modelo e de suas saídas, nos termos e definições da própria licença. A MIT do TTSBR não concede permissão de uso comercial do XTTS v2 nem dos áudios gerados por ele.

- [Página do modelo](https://huggingface.co/coqui/XTTS-v2)
- [Texto da licença CPML](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt)

A CPML também exige que quem recebe cópias do modelo, modificações ou suas saídas receba os termos ou o endereço indicado na licença. Ao compartilhar um áudio gerado pelo XTTS v2, inclua a referência à licença aplicável. As saídas em `saida/` e os áudios da avaliação não devem ser apresentados como licenciados sob MIT apenas por terem sido produzidos com este projeto.

Os scripts de síntese definem `COQUI_TOS_AGREED=1`. Essa configuração sinaliza aceite dos termos, não modifica a licença nem amplia suas permissões. Consulte os termos antes de executar o modelo.

## Biblioteca Coqui TTS

A biblioteca `coqui-tts`, responsável pela integração de síntese, tem licença própria. A versão 0.28.0 usada na avaliação inicial declara **MPL-2.0** em seus metadados. Essa licença da biblioteca é distinta da CPML dos pesos do XTTS v2 e da MIT do código original do TTSBR.

- [Repositório da biblioteca](https://github.com/idiap/coqui-ai-TTS)

## Interface gráfica

A GUI utiliza Tkinter e Tcl/Tk fornecidos pela instalação de Python. Esses componentes mantêm seus próprios termos de licença; o projeto não os redistribui nesta versão. Consulte as licenças da distribuição de Python utilizada.

## Outras dependências e modelos

O projeto utiliza bibliotecas como Torch, Torchaudio, NumPy, Pydub e ImageIO-FFmpeg. As ferramentas auxiliares também utilizam Transformers, Librosa e SoundFile. Cada pacote e suas dependências transitivas mantêm suas próprias licenças e avisos.

O FFmpeg pode vir do sistema ou do pacote ImageIO-FFmpeg. As condições de redistribuição dependem da compilação e dos componentes incluídos. A licença MIT do TTSBR não substitui essas condições.

A validação usa por padrão o modelo [openai/whisper-small](https://huggingface.co/openai/whisper-small). Modelos alternativos selecionados com `--modelo` podem ter condições diferentes. Consulte a licença da versão efetivamente utilizada.

As dependências não estão fixadas por versão. Este documento destaca componentes relevantes e não constitui um inventário completo de licenças transitivas. Ao redistribuir um ambiente, executável, contêiner ou pacote que incorpore componentes de terceiros, confira as licenças e avisos das versões incluídas.

## Gravações de referência e conteúdos de entrada

Os arquivos fornecidos pelo usuário não passam a ser licenciados sob MIT por serem processados pelo TTSBR. O projeto não concede direitos sobre vozes, gravações ou textos de terceiros.
