"""Configuração única de qualidade para todos os cortes intermediários."""
import os
import json
import subprocess

CONFIG_RENDER_FILE = os.path.join(os.path.dirname(__file__), "render_config.json")
PARTIDA_JSON = os.path.join(os.path.dirname(__file__), "partida.json")

_GPU_DETECCAO = None


def detectar_hardware_corte():
    global _GPU_DETECCAO
    if _GPU_DETECCAO is not None:
        return _GPU_DETECCAO

    def _testar(c_name):
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                 "-c:v", c_name, "-f", "null", "-"],
                capture_output=True, text=True, timeout=3
            )
            return r.returncode == 0
        except Exception:
            return False

    if _testar("h264_nvenc"): _GPU_DETECCAO = "h264_nvenc"
    elif _testar("h264_amf"): _GPU_DETECCAO = "h264_amf"
    elif _testar("h264_qsv"): _GPU_DETECCAO = "h264_qsv"
    else: _GPU_DETECCAO = "libx264"
    return _GPU_DETECCAO


def obter_encoder_configurado():
    if os.path.exists(CONFIG_RENDER_FILE):
        try:
            with open(CONFIG_RENDER_FILE, encoding="utf-8-sig") as f:
                d = json.load(f)
                if d.get("encoder"):
                    return d["encoder"]
        except Exception:
            pass
    if os.path.exists(PARTIDA_JSON):
        try:
            with open(PARTIDA_JSON, encoding="utf-8-sig") as f:
                d = json.load(f)
                enc = d.get("meta", {}).get("render_encoder")
                if enc: return enc
        except Exception:
            pass
    return detectar_hardware_corte()


def obter_args_corte(encoder=None):
    enc = str(encoder or obter_encoder_configurado()).lower().strip()
    if any(k in enc for k in ("nvenc", "gpu", "amf", "qsv", "auto")):
        gpu_codec = detectar_hardware_corte()
        if "amf" in enc: gpu_codec = "h264_amf"
        elif "qsv" in enc: gpu_codec = "h264_qsv"
        elif "nvenc" in enc: gpu_codec = "h264_nvenc"

        if gpu_codec == "h264_nvenc":
            return [
                "-c:v", "h264_nvenc", "-preset", "p4", "-rc:v", "vbr", "-cq:v", "18", "-b:v", "0",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
                "-movflags", "+faststart", "-avoid_negative_ts", "make_zero"
            ]
        elif gpu_codec == "h264_amf":
            return [
                "-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_p", "18", "-qp_i", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
                "-movflags", "+faststart", "-avoid_negative_ts", "make_zero"
            ]
        elif gpu_codec == "h264_qsv":
            return [
                "-c:v", "h264_qsv", "-preset", "faster", "-global_quality", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
                "-movflags", "+faststart", "-avoid_negative_ts", "make_zero"
            ]

    return [
        "-c:v", "libx264", "-preset", "faster", "-crf", "16", "-threads", "0",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
        "-movflags", "+faststart", "-avoid_negative_ts", "make_zero"
    ]


CLIP_QUALITY_VERSION = "max-v3"
CLIP_QUALITY_ARGS = obter_args_corte()


def clip_command(video: str, inicio_s: float, duracao_s: float, saida: str, encoder: str = None) -> list[str]:
    """Corta do original com aceleração por GPU (se ativa) ou CPU multi-threads."""
    args = obter_args_corte(encoder)
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(inicio_s), "-i", video, "-t", str(duracao_s),
        *args, saida,
    ]
