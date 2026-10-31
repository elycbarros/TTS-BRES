#!/usr/bin/env python3
"""Mapeamento, resolução e roteamento de locutores e vozes de referência."""
from pathlib import Path

EXTENSOES_AUDIO = (".wav", ".mp3", ".flac", ".m4a", ".ogg")

VOZES_PADRAO: dict[str, str] = {
    "pt": "Luis Moray",
    "es": "Alma María",
}

# Mapeamento de apelidos de personagens para nomes oficiais de locutores do XTTS v2
PERSONAGENS_MAP: dict[str, str] = {
    "narrador": "Luis Moray",
    "luis": "Luis Moray",
    "moray": "Luis Moray",
    "alma": "Alma María",
    "maria": "Alma María",
    "marcos": "Marcos Rudaski",
    "rudaski": "Marcos Rudaski",
    "gilberto": "Gilberto Mathias",
    "mathias": "Gilberto Mathias",
    "ana": "Ana Florence",
    "florence": "Ana Florence",
    "sofia": "Sofia Hellen",
    "hellen": "Sofia Hellen",
    "xavier": "Xavier Hayasaka",
    "hayasaka": "Xavier Hayasaka",
    "iapetus": "Xavier Hayasaka",
    "iapetus (xavier hayasaka)": "Xavier Hayasaka",
    "claribel": "Claribel Dervla",
    "daisy": "Daisy Studious",
    "gracie": "Gracie Wise",
    "ferran": "Ferran Simen",
    "tammie": "Tammie Ema",
    "ema": "Tammie Ema",
}

TONS_PREDEFINIDOS: dict[str, dict] = {
    "enfatico": {"volume_offset_db": 2.5, "velocidade_fator": 1.05},
    "enfase": {"volume_offset_db": 2.5, "velocidade_fator": 1.05},
    "animado": {"volume_offset_db": 2.0, "velocidade_fator": 1.08},
    "calmo": {"volume_offset_db": -2.0, "velocidade_fator": 0.92},
    "suave": {"volume_offset_db": -2.5, "velocidade_fator": 0.94},
    "sussurro": {"volume_offset_db": -4.0, "velocidade_fator": 0.90},
    "serio": {"volume_offset_db": 0.0, "velocidade_fator": 0.95},
}


def eh_caminho_audio(nome: str | None) -> bool:
    """Verifica se uma string possui extensão de arquivo de áudio reconhecida."""
    return bool(nome and nome.strip().lower().endswith(EXTENSOES_AUDIO))


def resolver_caminho_voz(caminho_str: str, base_texto: Path | None = None) -> str:
    """Resolve o caminho absoluto de um áudio de referência, considerando o caminho base do texto."""
    candidato = Path(caminho_str.strip()).expanduser()
    if candidato.is_file():
        return str(candidato.resolve())
    if base_texto is not None and not candidato.is_absolute():
        relativo = (base_texto.parent / candidato).expanduser()
        if relativo.is_file():
            return str(relativo.resolve())
    raise ValueError(f"Áudio de referência não encontrado: {caminho_str}")


def carregar_vozes_personagens(especificacao: str | None, base_texto: Path | None = None) -> dict[str, str]:
    """Interpreta especificações de vozes de personagens (ex.: 'narrador=voz1.wav,ana=voz2.wav')."""
    if not especificacao or not especificacao.strip():
        return {}
    mapa: dict[str, str] = {}
    for item in especificacao.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Mapeamento de voz inválido ({item!r}); use personagem=arquivo.wav.")
        chave, caminho = item.split("=", 1)
        chave = chave.strip().lower()
        caminho = caminho.strip()
        if not chave or not caminho:
            raise ValueError(f"Mapeamento de voz inválido ({item!r}); use personagem=arquivo.wav.")
        resolvido = resolver_caminho_voz(caminho, base_texto)
        mapa[chave] = resolvido
        oficial = PERSONAGENS_MAP.get(chave)
        if oficial:
            mapa[oficial.lower()] = resolvido
    return mapa


def resolver_voz_segmento(
    locutor_char: str | None,
    vozes_personagens: dict[str, str],
    base_texto: Path | None = None,
) -> str | None:
    """Retorna o caminho de áudio associado ao personagem informado, se houver."""
    if not locutor_char:
        return None
    chave = locutor_char.strip().lower()
    if chave in vozes_personagens:
        return vozes_personagens[chave]
    if eh_caminho_audio(locutor_char):
        return resolver_caminho_voz(locutor_char, base_texto)
    return None


def resolver_voz_tom(
    mods: dict,
    vozes_tons: dict[str, str],
    base_texto: Path | None = None,
) -> str | None:
    """Retorna a referência de áudio customizada para o tom/estilo do segmento, se especificada."""
    tom = mods.get("tom")
    if tom:
        chave = tom.strip().lower()
        if chave in vozes_tons:
            return vozes_tons[chave]
        if eh_caminho_audio(tom):
            return resolver_caminho_voz(tom, base_texto)
        if chave not in TONS_PREDEFINIDOS:
            raise ValueError(f"Tom desconhecido ({tom!r}); use {', '.join(sorted(TONS_PREDEFINIDOS))} ou mapeie em --vozes-tons.")
        return None
    offset = mods.get("volume_offset_db")
    if offset == 2.5 and ("enfase" in vozes_tons or "enfatico" in vozes_tons):
        return vozes_tons.get("enfase") or vozes_tons.get("enfatico")
    if offset == -4.0 and "sussurro" in vozes_tons:
        return vozes_tons["sussurro"]
    return None


def resolver_locutor(nome_ou_tag: str | None, idioma_trecho: str, locutor_fallback: str) -> str:
    """Resolve o locutor a partir de um nome de personagem, nome oficial ou idioma."""
    if not nome_ou_tag:
        return VOZES_PADRAO.get(idioma_trecho, locutor_fallback)
    alvo = nome_ou_tag.strip().lower()
    return PERSONAGENS_MAP.get(alvo, nome_ou_tag.strip())
