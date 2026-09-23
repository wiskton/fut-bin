"""Configuração única de qualidade para todos os cortes intermediários."""

CLIP_QUALITY_VERSION = "max-v1"
CLIP_QUALITY_ARGS = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "14",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "320k",
    "-movflags", "+faststart", "-avoid_negative_ts", "make_zero",
]


def clip_command(video: str, inicio_s: float, duracao_s: float, saida: str) -> list[str]:
    """Corta do original preservando resolução e FPS, sem filtros de escala."""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(inicio_s), "-i", video, "-t", str(duracao_s),
        *CLIP_QUALITY_ARGS, saida,
    ]
