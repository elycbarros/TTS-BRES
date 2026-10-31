#!/usr/bin/env python3
"""Converte um texto pronto (.txt) em áudio MP3 (e WAV opcional) usando XTTS v2.

Suporta Português Brasileiro ('pt') e Espanhol ('es') com detecção automática de idioma
e seleção da voz ideal para cada idioma.

Fluxo:
  1. Detecta o idioma automaticamente ('pt' ou 'es') e seleciona o locutor padrão ideal
     ('Luis Moray' para PT-BR, 'Alma María' para Espanhol).
  2. Análise prévia: estima palavras e duração (>450 palavras ~ 3 min = longo).
  3. Se longo, divide em blocos independentes de até 150 palavras, sempre
     terminando em fim de frase.
  4. Normaliza o texto adaptado ao idioma (termos técnicos, siglas e abreviações).
  5. Gera cada trecho, remove o silêncio residual do XTTS nas pontas, normaliza
     o volume (dBFS) e aplica a pausa exata da pontuação.

Uso:
    python tts.py texto.txt                       # detecta idioma e voz automaticamente
    python tts.py texto.txt --saida audio         # gera audio.mp3 e audio.blocos.json
    python tts.py texto.txt --idioma es           # força espanhol
    python tts.py texto.txt --locutor "Xavier Hayasaka" # especifica outro locutor
"""
import argparse
import math
import os
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # aceita a licença do XTTS v2
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Mac: cai para CPU em ops não suportadas

with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    from pydub import AudioSegment

from audio_persistente import (
    CacheSegmentos,
    exportar,
    hash_arquivo,
    higienizar_referencia,
    salvar_json,
)
from normalizador import (
    carregar_glossario,
    detectar_idioma,
    normalizar_para_fala,
)
from processamento_audio import (
    DURACAO_MIN_ALUCINACAO_S,
    LIMIAR_ALUCINACAO_S_POR_CHAR,
    SAMPLE_RATE,
    avaliar_anomalia_sintese,
    compactar_silencios_internos,
    configurar_ffmpeg,
    cortar_silencio_pontas,
    escolher_dispositivo,
    para_segmento,
)
from segmentador import (
    LIMITE_LONGO,
    MAX_CHARS,
    MAX_PALAVRAS_BLOCO,
    PALAVRAS_POR_MIN,
    analise_previa,
    contar_palavras,
    dividir_em_blocos,
    dividir_frases,
    extrair_tags_expressividade,
    limpar_para_voz,
    montar_itens,
    pausa_ms,
    preparar_segmentos,
)
from vozes import (
    EXTENSOES_AUDIO,
    PERSONAGENS_MAP,
    TONS_PREDEFINIDOS,
    VOZES_PADRAO,
    carregar_vozes_personagens,
    eh_caminho_audio,
    resolver_caminho_voz,
    resolver_locutor,
    resolver_voz_segmento,
    resolver_voz_tom,
)

# Evita UnicodeEncodeError no console do Windows (acentos, reticências).
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


class SinteseInterrompida(Exception):
    """Interrupção solicitada entre segmentos, com cache preservado."""


def main(argv=None, on_event=None, should_stop=None, modelo_precarregado=None):
    def emitir(tipo, **dados):
        if on_event is not None:
            on_event({"tipo": tipo, **dados})

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("texto", help="arquivo .txt com o texto pronto")
    ap.add_argument("--voz", default=None, help="áudio de referência (wav, 6-30 s) para clonar a voz")
    ap.add_argument(
        "--locutor", default=None,
        help="voz embutida do XTTS (padrão: automático pelo idioma: 'Luis Moray' para PT, 'Alma María' para ES)",
    )
    ap.add_argument("--saida", default="audio", help="nome base (sem extensão)")
    ap.add_argument(
        "--idioma", default="auto", choices=["auto", "pt", "es"],
        help="idioma (auto, pt ou es; padrão: auto com detecção no texto)",
    )
    ap.add_argument("--pausa-frase", type=int, default=600, help="ms após ponto/!/? (padrão: 600)")
    ap.add_argument("--pausa-reticencias", type=int, default=850, help="ms após reticências (padrão: 850)")
    ap.add_argument("--pausa-ponto-virgula", type=int, default=420, help="ms após ; ou : (padrão: 420)")
    ap.add_argument("--pausa-virgula", type=int, default=250, help="ms em corte de frase longa (padrão: 250)")
    ap.add_argument("--pausa-paragrafo", type=int, default=1150, help="ms entre parágrafos (padrão: 1150)")
    ap.add_argument("--pausa-bloco", type=int, default=500, help="ms extra entre blocos (padrão: 500)")
    ap.add_argument("--velocidade", type=float, default=1.1, help="velocidade da fala (1.0 = original; padrão: 1.1; faixa útil 0.8 a 1.3)")
    ap.add_argument("--volume-alvo", type=float, default=-20.0, help="volume alvo em dBFS (padrão: -20.0; deixa folga para [enfase])")
    ap.add_argument("--glossario", default=None, help="arquivo .json opcional com pronúncias extras")
    ap.add_argument("--sem-normalizar", action="store_true", help="desativa a normalização fonética")
    ap.add_argument("--sem-corte-silencio", action="store_true", help="não remove silêncio residual do XTTS")
    ap.add_argument("--refazer", action="store_true", help="regenera os segmentos, ignorando o cache existente")
    ap.add_argument(
        "--refazer-segmentos", default=None,
        help="regenera apenas os IDs de segmentos informados, preservando os demais do cache (ex.: '2' ou '1,4')",
    )
    ap.add_argument("--wav", action="store_true", help="gera também o arquivo .wav além do .mp3")
    ap.add_argument("--srt", action="store_true", help="gera também o arquivo de legendas .srt")
    ap.add_argument("--vtt", action="store_true", help="gera também o arquivo de legendas .vtt (WebVTT)")
    ap.add_argument("--formatos", default="mp3", help="formatos de saída (padrão: mp3; aceita mp3,wav,srt,vtt)")
    ap.add_argument(
        "--lufs", type=float, default=None,
        help="normaliza o loudness final integrado em LUFS via FFmpeg (ex.: -16 para podcasts, -14 para web)",
    )
    ap.add_argument(
        "--taxa-amostragem", type=int, default=SAMPLE_RATE, choices=[24000, 44100, 48000],
        help="taxa de amostragem de saída em Hz (padrão: 24000; opções: 24000, 44100, 48000)",
    )
    ap.add_argument(
        "--trilha", default=None,
        help="arquivo de áudio para trilha sonora de fundo (BGM) com auto-ducking automático na fala",
    )
    ap.add_argument(
        "--volume-trilha", type=float, default=-18.0,
        help="volume base da trilha de fundo em dB antes do auto-ducking (padrão: -18.0; faixa: -60 a 0)",
    )
    ap.add_argument(
        "--vozes-personagens", default=None,
        help="mapeia personagens do roteiro para arquivos WAV de referência (ex.: 'narrador=luis.wav,alma=alma.wav')",
    )
    ap.add_argument(
        "--vozes-tons", default=None,
        help="mapeia tons de expressão ([tom:X]) para arquivos WAV de referência (ex.: 'enfatico=enfase.wav,calmo=calmo.wav')",
    )
    ap.add_argument(
        "--limpar-referencia", action="store_true",
        help="higieniza áudios de referência (remove ruído e padroniza volume via FFmpeg antes da clonagem)",
    )
    ap.add_argument(
        "--max-tentativas", type=int, default=2,
        help="máximo de tentativas por segmento caso seja detectada alucinação/silêncio (padrão: 2)",
    )
    ap.add_argument(
        "--dispositivo", default="auto", choices=["auto", "cpu", "cuda", "mps"],
        help="auto = CUDA se houver, senão CPU (mps é experimental no Mac)",
    )
    ap.add_argument("--analisar", action="store_true", help="confere e mostra o plano sem carregar o XTTS ou gravar saídas")
    args = ap.parse_args(argv)

    for nome in ("pausa_frase", "pausa_reticencias", "pausa_ponto_virgula",
                 "pausa_virgula", "pausa_paragrafo", "pausa_bloco"):
        if getattr(args, nome) < 0:
            ap.error(f"--{nome.replace('_', '-')} deve ser maior ou igual a zero.")
    if not math.isfinite(args.velocidade) or args.velocidade <= 0:
        ap.error("--velocidade deve ser um número finito maior que zero.")
    if not math.isfinite(args.volume_alvo) or args.volume_alvo > 0:
        ap.error("--volume-alvo deve ser um número finito menor ou igual a zero dBFS.")
    if args.lufs is not None and (not math.isfinite(args.lufs) or not (-70.0 <= args.lufs <= -5.0)):
        ap.error("--lufs deve ser um número entre -70 e -5 LUFS (ex.: -16).")
    if not math.isfinite(args.volume_trilha) or not (-60.0 <= args.volume_trilha <= 0.0):
        ap.error("--volume-trilha deve estar entre -60 e 0 dB.")
    if args.max_tentativas < 1:
        ap.error("--max-tentativas deve ser maior ou igual a 1.")
    refazer_ids: set[int] = set()
    if args.refazer_segmentos is not None:
        partes_ids = [p.strip() for p in args.refazer_segmentos.split(",") if p.strip()]
        if not partes_ids or any(not p.isdigit() or int(p) < 1 for p in partes_ids):
            ap.error("--refazer-segmentos deve conter IDs inteiros positivos separados por vírgula (ex.: 2 ou 1,4).")
        refazer_ids = {int(p) for p in partes_ids}
    formatos = list(dict.fromkeys(f.strip().lower() for f in args.formatos.split(",")))
    if not formatos or any(f not in ("mp3", "wav", "srt", "vtt") for f in formatos):
        ap.error("--formatos aceita mp3, wav, srt, vtt ou combinações separadas por vírgula.")
    for flag, fmt in ((args.wav, "wav"), (args.srt, "srt"), (args.vtt, "vtt")):
        if flag and fmt not in formatos:
            formatos.append(fmt)
    if not args.saida.strip() or Path(args.saida).is_dir():
        ap.error("--saida deve indicar um nome base de arquivo.")
    if args.locutor is not None:
        args.locutor = args.locutor.strip()
        if not args.locutor:
            ap.error("--locutor não pode ser vazio.")
        args.locutor = resolver_locutor(args.locutor, "pt", args.locutor)
    if args.voz and not Path(args.voz).is_file():
        ap.error(f"Áudio de referência não encontrado: {args.voz}")
    if args.trilha and not Path(args.trilha).is_file():
        ap.error(f"Arquivo de trilha sonora não encontrado: {args.trilha}")
    normalizar = not args.sem_normalizar
    caminho_texto = Path(args.texto)
    try:
        texto = caminho_texto.read_text(encoding="utf-8-sig")
        glossario_extra = carregar_glossario(args.glossario, texto_path=args.texto)
        vozes_personagens = carregar_vozes_personagens(args.vozes_personagens, base_texto=caminho_texto)
        vozes_tons = carregar_vozes_personagens(args.vozes_tons, base_texto=caminho_texto)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    if not texto.strip():
        ap.error("O arquivo de texto está vazio.")

    # 1) Detecção de idioma e seleção de locutor
    modo_auto = args.idioma == "auto"
    idioma_global = detectar_idioma(texto) if modo_auto else args.idioma
    locutor_global = args.locutor or VOZES_PADRAO.get(idioma_global, "Luis Moray")
    nome_idioma = "Espanhol (es)" if idioma_global == "es" else "Português Brasileiro (pt)"
    origem_idioma = " [detecção automática]" if modo_auto else ""
    origem_locutor = " [seleção automática ideal]" if not args.locutor else ""
    print(f"Idioma dominante: {nome_idioma}{origem_idioma}")
    print(f"Locutor padrão: {locutor_global}{origem_locutor}")

    # 2) Análise prévia
    analise = analise_previa(texto)
    analise["idioma"] = idioma_global
    analise["locutor"] = locutor_global
    print(
        f"Análise prévia: {analise['palavras_estimadas']} palavras, "
        f"~{analise['duracao_estimada_min']} min -> "
        + ("LONGO (divide em blocos de até 150 palavras)" if analise["precisa_dividir"] else "curto (bloco único)")
    )

    # 3) Divisão em blocos (com detecção por parágrafo quando idioma='auto')
    try:
        blocos = dividir_em_blocos(
            montar_itens(texto, normalizar=normalizar, idioma_padrao=idioma_global,
                         detectar_por_paragrafo=modo_auto),
            analise["precisa_dividir"],
        )
        plano = [
            [(preparar_segmentos(t, lang, normalizar, glossario_extra), fim, lang, locutor)
             for t, fim, lang, locutor in bloco]
            for bloco in blocos
        ]
        for bloco in plano:
            for segmentos_tags, _, _, locutor in bloco:
                resolver_voz_segmento(locutor, vozes_personagens, base_texto=caminho_texto)
                for _, mods in segmentos_tags:
                    resolver_voz_tom(mods, vozes_tons, base_texto=caminho_texto)
    except ValueError as exc:
        ap.error(str(exc))
    if not any(limpar_para_voz(t) for bloco in plano for segmentos, _, _, _ in bloco
               for t, _ in segmentos):
        ap.error("O arquivo não contém texto para sintetizar.")

    manifesto = {
        "analise_previa": analise,
        "blocos": [
            {
                "id": i,
                "palavras": sum(contar_palavras(t) for t, _, _, _ in b),
                "texto": " ".join(t for t, _, _, _ in b),
                "texto_falado": " ".join(
                    limpar_para_voz(sub)
                    for segmentos, _, _, _ in plano[i - 1]
                    for sub, _ in segmentos
                    if limpar_para_voz(sub)
                ),
            }
            for i, b in enumerate(blocos, 1)
        ],
    }
    resumo_segmentos = [
        {"id": n, "bloco": bloco, "texto": limpar_para_voz(sub), "idioma": lang,
         "locutor": locutor or args.locutor or VOZES_PADRAO[lang]}
        for n, (bloco, sub, lang, locutor) in enumerate(
            ((i, sub, lang, locutor)
             for i, b in enumerate(plano, 1)
             for segmentos, _, lang, locutor in b
             for sub, _ in segmentos if limpar_para_voz(sub)), 1)
    ]
    if refazer_ids and any(idx > len(resumo_segmentos) for idx in refazer_ids):
        ap.error(f"--refazer-segmentos contém ID fora do total de segmentos ({len(resumo_segmentos)}).")
    emitir("plano", total=len(resumo_segmentos), segmentos=resumo_segmentos)
    if args.analisar:
        for seg in resumo_segmentos:
            print(f"  #{seg['id']} [{seg['idioma']}|{seg['locutor']}] {seg['texto']}")
        return

    base = Path(args.saida)
    json_path = base.parent / f"{base.name}.blocos.json"
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        salvar_json(json_path, manifesto)
    except OSError as exc:
        ap.error(f"Não foi possível gravar o manifesto: {exc}")
    print(f"{len(blocos)} bloco(s). Lista salva em {json_path}")

    # O modelo só é carregado quando algum segmento precisa de síntese.
    configurar_ffmpeg()
    cache = CacheSegmentos(base.parent / f"{base.name}.segmentos")
    eventos = [200]
    cursor_frames = SAMPLE_RATE // 5
    manifesto["segmentos"] = []
    manifesto["estado"] = "sintetizando"
    salvar_json(json_path, manifesto)
    modelo = modelo_precarregado
    versoes = {}
    for pacote in ("coqui-tts", "torch", "numpy", "pydub"):
        try:
            versoes[pacote] = version(pacote)
        except PackageNotFoundError:
            versoes[pacote] = "indisponível"
    hashes_ref: dict[str, str] = {}
    refs_limpas: dict[str, str] = {}

    def obter_hash_ref(caminho_ref: str | None) -> str | None:
        if not caminho_ref:
            return None
        chave = str(Path(caminho_ref).resolve())
        if chave not in hashes_ref:
            hashes_ref[chave] = hash_arquivo(chave)
        return hashes_ref[chave]

    def obter_voz_condicionada(caminho_ref: str | None) -> str | None:
        if not caminho_ref:
            return None
        if not args.limpar_referencia:
            return caminho_ref
        chave = str(Path(caminho_ref).resolve())
        if chave not in refs_limpas:
            refs_limpas[chave] = higienizar_referencia(chave, cache.pasta, AudioSegment.converter)
        return refs_limpas[chave]

    referencia = obter_hash_ref(args.voz)
    manifesto["configuracao"] = {
        "python": sys.version.split()[0], "versoes": versoes,
        "dispositivo_solicitado": args.dispositivo, "velocidade": args.velocidade,
        "volume_alvo": args.volume_alvo, "cortar_silencio": not args.sem_corte_silencio,
        "lufs": args.lufs, "taxa_amostragem": args.taxa_amostragem,
        "limpar_referencia": args.limpar_referencia, "max_tentativas": args.max_tentativas,
        "referencia_sha256": referencia,
        "fontes_sha256": {nome: hash_arquivo(Path(__file__).parent / nome)
                          for nome in ("tts.py", "normalizador.py", "audio_persistente.py")},
    }
    salvar_json(json_path, manifesto)

    def verificar_interrupcao():
        if should_stop is not None and should_stop():
            manifesto["estado"] = "interrompido"
            salvar_json(json_path, manifesto)
            emitir("interrompido", concluidos=len(manifesto["segmentos"]),
                   total=len(resumo_segmentos))
            raise SinteseInterrompida("Interrompido entre segmentos; repita a geração para retomar.")

    def sintetizar(texto_voz, locutor, lang, volume, voz_ref=None, velocidade=None):
        nonlocal modelo
        if modelo is None:
            emitir("etapa", etapa="modelo", mensagem="Carregando o modelo de voz…")
            from TTS.api import TTS
            dispositivo = escolher_dispositivo(args.dispositivo)
            print(f"Dispositivo: {dispositivo}")
            modelo = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dispositivo)
        voz_preparada = obter_voz_condicionada(voz_ref)
        voz = {"speaker_wav": voz_preparada} if voz_preparada else {"speaker": locutor}
        vel = args.velocidade if velocidade is None else velocidade
        melhor_seg = None
        for tentativa in range(1, args.max_tentativas + 1):
            wav = modelo.tts(text=texto_voz, **voz, language=lang,
                             split_sentences=False, speed=vel)
            seg = para_segmento(wav, cortar_silencio=not args.sem_corte_silencio,
                                volume_alvo_dbfs=volume)
            anomalia = avaliar_anomalia_sintese(seg, texto_voz, vel)
            if anomalia is None:
                return seg
            if melhor_seg is None or (seg.dBFS != float("-inf") and len(seg) < len(melhor_seg)):
                melhor_seg = seg
            if tentativa < args.max_tentativas:
                print(f"    Aviso: anomalia na síntese ({anomalia}); repetindo ({tentativa + 1}/{args.max_tentativas})…")
            else:
                print(f"    Aviso: anomalia persistiu após {args.max_tentativas} tentativa(s) ({anomalia}).")
        return melhor_seg

    for i, bloco in enumerate(plano, 1):
        print(f"--- Bloco {i}/{len(plano)} ---")
        for segmentos_tags, fim_par, lang_trecho, locutor_char in bloco:
            locutor_trecho = locutor_char or args.locutor or VOZES_PADRAO.get(lang_trecho, locutor_global)
            voz_personagem = resolver_voz_segmento(locutor_char, vozes_personagens, base_texto=caminho_texto)
            for idx_seg, (sub_trecho, mods) in enumerate(segmentos_tags):
                ultimo_sub = idx_seg == len(segmentos_tags) - 1
                texto_voz = limpar_para_voz(sub_trecho)
                if sub_trecho:
                    # Texto sem pontuação final seguido de tag de pausa: a tag já define a pausa.
                    seguido_de_pausa = (
                        idx_seg + 1 < len(segmentos_tags)
                        and "pausa_extra_ms" in segmentos_tags[idx_seg + 1][1]
                        and not ultimo_sub
                    )
                    sem_pontuacao = not sub_trecho.rstrip().endswith((".", "!", "?", "…", ";", ":", ","))
                    if seguido_de_pausa and sem_pontuacao:
                        pausa_base = 0
                    else:
                        pausa_base = pausa_ms(sub_trecho, fim_par and ultimo_sub, args)
                else:
                    # Item de tag pura: só carrega a pausa pedida (+ pausa de parágrafo se for o último).
                    pausa_base = args.pausa_paragrafo if (fim_par and ultimo_sub) else 0
                pausa_total = pausa_base + mods.get("pausa_extra_ms", 0)

                if texto_voz:
                    voz_tom = resolver_voz_tom(mods, vozes_tons, base_texto=caminho_texto)
                    voz_efetiva = voz_tom or voz_personagem or args.voz
                    ref_efetiva = obter_hash_ref(voz_efetiva)
                    vel_efetiva = (
                        round(args.velocidade * mods["velocidade_fator"], 4)
                        if "velocidade_fator" in mods
                        else args.velocidade
                    )
                    tag_info = ""
                    if "tom" in mods:
                        tag_info += f"|tom:{mods['tom']}"
                    if "volume_offset_db" in mods:
                        tag_info += f"|vol:{mods['volume_offset_db']:+.1f}dB"
                    if "pausa_extra_ms" in mods:
                        tag_info += f"|pausa:{mods['pausa_extra_ms']}ms"

                    print(f"  [{lang_trecho}|{locutor_trecho}{tag_info}] {texto_voz[:55]}")
                    vol_alvo = args.volume_alvo + mods.get("volume_offset_db", 0.0)
                    parametros = {
                        "pipeline": 1, "modelo": "tts_models/multilingual/multi-dataset/xtts_v2",
                        "versoes": versoes, "texto": texto_voz, "idioma": lang_trecho,
                        "locutor": None if voz_efetiva else locutor_trecho,
                        "referencia_sha256": ref_efetiva, "velocidade": vel_efetiva,
                        "volume_alvo": vol_alvo, "cortar_silencio": not args.sem_corte_silencio,
                        "dispositivo_solicitado": args.dispositivo,
                    }
                    if args.limpar_referencia and voz_efetiva:
                        parametros["limpar_referencia"] = True
                    verificar_interrupcao()
                    seg_id = len(manifesto["segmentos"]) + 1
                    emitir("etapa", etapa="sintese", mensagem=f"Processando segmento {seg_id}…")
                    caminho, frames, reutilizado = cache.obter(
                        parametros,
                        lambda v=voz_efetiva, vel=vel_efetiva: sintetizar(
                            texto_voz, locutor_trecho, lang_trecho, vol_alvo, v, vel
                        ),
                        refazer=args.refazer or (seg_id in refazer_ids),
                    )
                    eventos.append(caminho)
                    manifesto["segmentos"].append({
                        "id": seg_id, "bloco": i,
                        "texto": texto_voz, "idioma": lang_trecho, "locutor": parametros["locutor"],
                        "arquivo": str(caminho.resolve()), "chave": caminho.stem,
                        "inicio_s": cursor_frames / SAMPLE_RATE,
                        "fim_s": (cursor_frames + frames) / SAMPLE_RATE,
                        "duracao_s": frames / SAMPLE_RATE, "reutilizado": reutilizado,
                    })
                    emitir("segmento", segmento=manifesto["segmentos"][-1],
                           concluidos=len(manifesto["segmentos"]), total=len(resumo_segmentos))
                    cursor_frames += frames
                    salvar_json(json_path, manifesto)
                    if reutilizado:
                        print("    Segmento recuperado do cache.")

                if pausa_total > 0:
                    eventos.append(pausa_total)
                    cursor_frames += SAMPLE_RATE * pausa_total // 1000
        if i < len(blocos):
            eventos.append(args.pausa_bloco)
            cursor_frames += SAMPLE_RATE * args.pausa_bloco // 1000

    verificar_interrupcao()
    emitir("etapa", etapa="montagem", mensagem="Montando e exportando o áudio…")
    manifesto["estado"] = "montando"
    salvar_json(json_path, manifesto)
    exportar(eventos, base, formatos, AudioSegment.converter,
             segmentos=manifesto["segmentos"], lufs=args.lufs, taxa_amostragem=args.taxa_amostragem,
             trilha=args.trilha, volume_trilha=args.volume_trilha)
    manifesto["estado"] = "concluido"
    salvar_json(json_path, manifesto)
    emitir("resultado", manifesto=str(json_path.resolve()),
           arquivos=[str((base.parent / f"{base.name}.{fmt}").resolve()) for fmt in formatos])


if __name__ == "__main__":
    main()
