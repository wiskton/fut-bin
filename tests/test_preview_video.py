"""Verifica prévias reais e a preservação dos tempos usados pelos cortes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preview_video as preview
import assistente_web as api
import detectar_gols
import montar_video
import video_quality


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)
    ]))


class PreviewCacheTest(unittest.TestCase):
    def test_selects_only_requested_final_video_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            partida = Path(tmp) / 'partida.json'
            partida.write_text('{"meta": {}}', encoding='utf-8')
            cases = [
                (True, False, False, '/video/final'),
                (False, True, True, '/video/final/gols'),
                (True, True, False, '/video/final'),
            ]
            for melhores, gols, somente_gols, video_url in cases:
                with self.subTest(melhores=melhores, gols=gols), \
                     patch.multiple(api, PARTIDA_JSON=str(partida), PROJECT_DIR=tmp), \
                     patch.object(api, '_iniciar_job', return_value='job') as iniciar:
                    resposta = api.api_iniciar_montagem(api.IniciarMontagem(
                        codec='libx264',
                        renderizar_melhores_momentos=melhores,
                        renderizar_apenas_gols=gols,
                    ))
                    comando = iniciar.call_args.args[0]
                    self.assertEqual(resposta['video_url'], video_url)
                    self.assertEqual('--somente_gols' in comando, somente_gols)
                    self.assertEqual(
                        comando[comando.index('--saida_gols') + 1],
                        'final/apenas_gols.mp4' if melhores and gols else '',
                    )
                    saida = Path(comando[comando.index('--saida') + 1]).as_posix()
                    self.assertEqual(
                        saida,
                        'final/apenas_gols.mp4' if somente_gols else 'final/melhores_momentos.mp4',
                    )

        with self.assertRaises(api.HTTPException):
            api.api_iniciar_montagem(api.IniciarMontagem(
                renderizar_melhores_momentos=False,
                renderizar_apenas_gols=False,
            ))

    def test_goal_only_roteiro_excludes_highlight_clips(self):
        roteiro = [{'i': 1}, {'i': 2}, {'i': 3}]
        por_indice = {1: ('gol', {}), 2: ('lance', {}), 3: ('gol', {})}

        self.assertEqual(
            montar_video._roteiro_apenas_gols(roteiro, por_indice),
            [{'i': 1}, {'i': 3}],
        )

    def test_light_correction_preserves_midtone_brightness(self):
        with patch.object(montar_video, 'duracao_video', return_value=3), \
             patch.object(montar_video, 'roda') as roda:
            montar_video.seg_de_clipe(
                'clip.mp4', 'overlay.png', 'output.mp4', True,
                ajuste_cor={
                    'corrigir_luzes': True,
                    'brilho': 1.0,
                    'contraste': 1.0,
                    'saturacao': 1.0,
                },
            )

        comando = roda.call_args.args[0]
        filtro = comando[comando.index('-filter_complex') + 1]
        self.assertIn(
            "curves=all='0/0 0.25/0.26 0.6/0.62 0.85/0.82 1/0.92'",
            filtro,
        )
        self.assertIn(
            'eq=contrast=1.00:brightness=0.00:saturation=1.40',
            filtro,
        )
        self.assertNotIn('gamma=', filtro)

    def test_short_clip_uses_original_at_maximum_quality(self):
        command = api._comando_corte_qualidade_maxima(
            r"C:\videos\original-4k.mp4", 12.5, 15, r"C:\clips\gol.mp4")
        self.assertEqual(command[command.index("-i") + 1], r"C:\videos\original-4k.mp4")
        self.assertEqual(command[command.index("-crf") + 1], "14")
        self.assertEqual(command[command.index("-preset") + 1], "slow")
        self.assertEqual(command[command.index("-b:a") + 1], "320k")
        self.assertNotIn("-vf", command)
        self.assertNotIn("scale", " ".join(command))

    def test_every_clip_path_uses_the_shared_maximum_quality_command(self):
        self.assertIs(api._comando_corte_qualidade_maxima, video_quality.clip_command)
        self.assertIs(detectar_gols.clip_command, video_quality.clip_command)
        self.assertIs(montar_video.clip_command, video_quality.clip_command)

    def test_cache_tracks_source_and_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mp4'
            source.write_bytes(b'original')
            first = preview.preview_key(source, 360)
            self.assertEqual(first, preview.preview_key(source, 360))
            self.assertNotEqual(first, preview.preview_key(source, 480))
            source.write_bytes(b'original changed')
            self.assertNotEqual(first, preview.preview_key(source, 360))
            with self.assertRaises(ValueError):
                preview.preview_key(source, 1080)

    def test_failed_conversion_does_not_publish_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'preview.mp4'
            partial = output.with_suffix('.partial.mp4')
            def fail(*args, **kwargs):
                partial.write_bytes(b'incomplete')
                raise subprocess.CalledProcessError(1, 'ffmpeg')
            with patch.object(preview.subprocess, 'run', side_effect=fail):
                with self.assertRaises(subprocess.CalledProcessError):
                    preview.generate_preview('source.mp4', 360, output)
            self.assertFalse(output.exists())
            self.assertFalse(partial.exists())
            self.assertFalse(output.with_suffix('.lock').exists())

    def test_api_deduplicates_jobs_and_reuses_completed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mp4'
            source.write_bytes(b'original')
            with patch.multiple(api, PREVIEW_DIR=tmp, PREVIEW_JOBS={},
                                JOBS={'job1': {'status': 'running'}}), \
                 patch.object(api, '_iniciar_job', return_value='job1') as start:
                body = api.PreviewBody(video=str(source), altura=360)
                first = api.api_previa_video(body)
                self.assertEqual(first, api.api_previa_video(body))
                start.assert_called_once()
                key = preview.preview_key(source, 360)
                (Path(tmp) / (key + '.mp4')).write_bytes(b'completed')
                self.assertTrue(api.api_previa_video(body)['pronto'])
                self.assertEqual(api.video_previa(key).media_type, 'video/mp4')
                with self.assertRaises(api.HTTPException):
                    api.video_previa('../source')
                with self.assertRaises(api.HTTPException):
                    api.api_previa_video(api.PreviewBody(video=str(source), altura=1080))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Requer FFmpeg')
class PreviewTimingTest(unittest.TestCase):
    def test_resolution_duration_audio_and_seek(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mp4'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'testsrc2=size=1280x720:rate=30:duration=3',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(source)
            ], check=True, capture_output=True)
            original = source.read_bytes()
            for height in (360, 480):
                output = Path(tmp) / f'preview{height}.mp4'
                with self.subTest(height=height):
                    # Subprocess real, apenas silencia o progresso neste teste.
                    subprocess.run([
                        os.sys.executable, str(Path(preview.__file__)),
                        str(source), str(height), str(output)
                    ], check=True, capture_output=True)
                    info = probe(output)
                    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                    self.assertEqual(video['height'], height)
                    self.assertEqual(video['width'], round(height * 16 / 9 / 2) * 2)
                    self.assertEqual(video['r_frame_rate'], '15/1')
                    self.assertAlmostEqual(float(video['duration']), 3, delta=1/15)
                    self.assertAlmostEqual(float(info['format']['duration']), 3, delta=0.1)
                    self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
                    # Procura um quadro no mesmo instante do original.
                    import cv2
                    import numpy as np
                    images = []
                    for path in (source, output):
                        cap = cv2.VideoCapture(str(path))
                        cap.set(cv2.CAP_PROP_POS_MSEC, 2000)
                        ok, frame = cap.read()
                        cap.release()
                        self.assertTrue(ok)
                        images.append(cv2.resize(frame, (160, 90)).astype(float))
                    self.assertLess(np.mean(np.abs(images[0] - images[1])), 12)
            self.assertEqual(source.read_bytes(), original)

    def test_video_without_audio_and_nonzero_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mp4'
            output = Path(tmp) / 'preview.mp4'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'testsrc2=size=640x360:rate=24:duration=2',
                '-vf', 'setpts=PTS+5/TB', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-fps_mode', 'passthrough', str(source)
            ], check=True, capture_output=True)
            subprocess.run([os.sys.executable, str(Path(preview.__file__)), str(source),
                            '360', str(output)], check=True, capture_output=True)
            streams = probe(output)['streams']
            self.assertEqual(len(streams), 1)
            self.assertAlmostEqual(float(streams[0]['duration']), 2, delta=1/15)
            self.assertAlmostEqual(float(streams[0]['start_time']), 0, delta=1/15)


if __name__ == '__main__':
    unittest.main()
