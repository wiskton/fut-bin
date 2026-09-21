"""Regressao real com FFmpeg: cameras diferentes devem manter o tempo em 1x.

Executar: python -m unittest discover -s tests -v
"""
import os
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import montar_video as render


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requer FFmpeg")
class RenderTimingTest(unittest.TestCase):
    def test_vertical_player_clip_without_audio(self):
        with tempfile.TemporaryDirectory(prefix="player_1x_") as tmp, patch.multiple(
            render, VERTICAL=True, LV=180, AV=320, ALTURA_SAIDA=180
        ):
            source = os.path.join(tmp, "source.mp4")
            output = os.path.join(tmp, "player.mp4")
            overlay = os.path.join(tmp, "overlay.png")
            Image.new("RGBA", (180, 320)).save(overlay)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=60", "-t", "2", "-an",
                "-c:v", "libx264", "-preset", "ultrafast", source
            ], check=True)
            render.seg_de_clipe(source, overlay, output, False, preset="ultrafast")
            self.assertAlmostEqual(render.duracao_video(output), 2, delta=1/30)
            streams = render.dados_midia(output)["streams"]
            self.assertEqual((streams[0]["width"], streams[0]["height"]), (180, 320))
            self.assertEqual(streams[1]["sample_rate"], "48000")

    def test_camera_loudness_is_balanced_without_changing_pitch(self):
        with tempfile.TemporaryDirectory(prefix="audio_1x_") as tmp:
            levels = []
            for index, (hz, gain) in enumerate([(44100, 0.15), (48000, 1.0)]):
                source = os.path.join(tmp, f"camera{index}.wav")
                output = os.path.join(tmp, f"normalized{index}.wav")
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:sample_rate={hz}:duration=6", "-af", f"volume={gain}", source
                ], check=True)
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-i", source,
                    "-af", render.filtro_audio_normalizado(source), "-ar", "48000", output
                ], check=True)
                measurement = subprocess.run([
                    "ffmpeg", "-hide_banner", "-nostats", "-i", output,
                    "-af", "loudnorm=print_format=json", "-f", "null", "-"
                ], capture_output=True, text=True, check=True).stderr
                level = json.loads(measurement[measurement.rfind("{"):measurement.rfind("}")+1])
                levels.append(float(level["input_i"]))
                self.assertAlmostEqual(levels[-1], -16, delta=0.5)
                self.assertAlmostEqual(float(render.dados_midia(output)["format"]["duration"]), 6, delta=0.01)
                import array
                raw = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", output, "-ss", "1", "-t", "1",
                    "-ac", "1", "-f", "f32le", "-"
                ], capture_output=True, check=True).stdout
                samples = array.array("f", raw)
                crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
                self.assertAlmostEqual(crossings, 440, delta=2)
            self.assertAlmostEqual(*levels, delta=0.5)
            silent = os.path.join(tmp, "silent.wav")
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "anullsrc=r=44100:cl=mono", "-t", "1", silent
            ], check=True)
            self.assertEqual(render.filtro_audio_normalizado(silent), render.AUDIO_FORMAT)

    def test_mixed_cameras_and_cards_preserve_timing(self):
        with tempfile.TemporaryDirectory(prefix="render_1x_") as tmp, patch.multiple(
            render, L=320, A=180, ALTURA_SAIDA=180, LV=180, AV=320
        ):
            card = os.path.join(tmp, "card.png")
            overlay = os.path.join(tmp, "overlay.png")
            Image.new("RGB", (320, 180), "black").save(card)
            Image.new("RGBA", (320, 180)).save(overlay)
            intro = os.path.join(tmp, "intro.mp4")
            render.seg_de_imagem(card, 1, intro, preset="ultrafast")
            parts = [intro]
            for index, (fps, hz, mute) in enumerate([
                ("30000/1001", 44100, False), ("60", 48000, False), ("25", 44100, True)
            ]):
                with self.subTest(fps=fps, hz=hz, mute=mute):
                    source = os.path.join(tmp, f"source{index}.mp4")
                    segment = os.path.join(tmp, f"segment{index}.mp4")
                    subprocess.run([
                        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=320x180:rate={fps}", "-f", "lavfi", "-i",
                        f"sine=frequency=440:sample_rate={hz}", "-t", "3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", source
                    ], check=True)
                    render.seg_de_clipe(source, overlay, segment, mute, preset="ultrafast")
                    self.assertAlmostEqual(render.duracao_video(source), render.duracao_video(segment), delta=1/30)
                    streams = render.dados_midia(segment)["streams"]
                    self.assertEqual(streams[0]["time_base"], "1/90000")
                    self.assertEqual(streams[1]["sample_rate"], "48000")
                    self.assertEqual(streams[1]["channels"], 2)
                    parts.append(segment)
            output = os.path.join(tmp, "final.mp4")
            render.concatenar_segmentos(parts, os.path.join(tmp, "list.txt"), output)
            self.assertAlmostEqual(render.duracao_video(output), 10, delta=0.15)
            frames = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "frame=best_effort_timestamp_time", "-of", "csv=p=0", output
            ], capture_output=True, text=True, check=True).stdout
            times = [float(line.split(",")[0]) for line in frames.splitlines() if line.strip(", ")]
            # Nenhum intervalo pode encurtar abaixo de um quadro a 30 fps.
            self.assertTrue(all(b-a >= 1/30 - 0.0001 for a, b in zip(times, times[1:])))
            with self.assertRaisesRegex(RuntimeError, "incompativel"):
                render.concatenar_segmentos([intro, source], os.path.join(tmp, "bad.txt"), output)
            with self.assertRaisesRegex(RuntimeError, "Duracao alterada"):
                render.validar_duracao(segment, 6)


if __name__ == "__main__":
    unittest.main()
