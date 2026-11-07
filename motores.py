"""Contrato inicial de motores de síntese. Pesos e dependências são externos."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Capacidades:
    idiomas: tuple[str, ...]
    clonagem: bool
    transcricao_referencia: bool
    semente: bool
    taxa_hz: int


@runtime_checkable
class MotorSintese(Protocol):
    id: str
    modelo_id: str
    capacidades: Capacidades

    def sintetizar(self, texto: str, idioma: str, locutor: str | None,
                   referencia: str | None, velocidade: float): ...


def _garantir_torchaudio_load():
    """Adiciona fallback via soundfile em torchaudio.load quando libtorchcodec falha (Torchaudio >= 2.9)."""
    try:
        import torchaudio
    except ImportError:
        return
    if getattr(torchaudio, '_ttsbr_soundfile_fallback', False):
        return
    original = torchaudio.load

    def _load_com_fallback(uri, frame_offset=0, num_frames=-1, normalize=True,
                           channels_first=True, format=None, buffer_size=4096, backend=None):
        try:
            return original(uri, frame_offset=frame_offset, num_frames=num_frames,
                            normalize=normalize, channels_first=channels_first,
                            format=format, buffer_size=buffer_size, backend=backend)
        except (RuntimeError, OSError, ImportError):
            import soundfile as sf
            import torch
            frames = -1 if num_frames is None or num_frames < 0 else num_frames
            dados, sr = sf.read(uri, start=frame_offset or 0, frames=frames,
                                dtype='float32', always_2d=True)
            tensor = torch.from_numpy(dados.T if channels_first else dados)
            return tensor, int(sr)

    torchaudio.load = _load_com_fallback
    torchaudio._ttsbr_soundfile_fallback = True


class MotorXTTS:
    id = 'xtts_v2'
    modelo_id = 'tts_models/multilingual/multi-dataset/xtts_v2'
    capacidades = Capacidades(('pt', 'es'), True, False, False, 24000)

    def __init__(self, modelo):
        self.modelo = modelo

    def sintetizar(self, texto, idioma, locutor, referencia, velocidade):
        if idioma not in self.capacidades.idiomas:
            raise ValueError('Idioma não suportado pelo XTTS.')
        if referencia:
            _garantir_torchaudio_load()
        voz = {'speaker_wav': referencia} if referencia else {'speaker': locutor}
        return self.modelo.tts(text=texto, **voz, language=idioma,
                               split_sentences=False, speed=velocidade)
