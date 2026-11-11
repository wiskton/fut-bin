from PIL import Image, ImageDraw, ImageFont
import subprocess
import os

img_in = r"C:/Users/willem/.gemini/antigravity/brain/b0525ebb-8393-448d-a191-e679f76852fb/.user_uploaded/media_1794384996340_c172174d.jpg"
out_dir = r"C:/Users/willem/.gemini/antigravity/brain/b0525ebb-8393-448d-a191-e679f76852fb"

# Render corrected frame with the preset
out_corrected = os.path.join(out_dir, "preset_anti_estouro_resultado.jpg")
subprocess.run([
    "ffmpeg", "-y", "-i", img_in,
    "-vf", "curves=all='0/0 0.35/0.30 0.7/0.65 0.9/0.82 1/0.88',eq=brightness=-0.14:contrast=1.20:saturation=1.65",
    "-q:v", "2", out_corrected
], check=True)

# Build a side-by-side comparison image
im_orig = Image.open(img_in).convert("RGB")
im_corr = Image.open(out_corrected).convert("RGB")

w, h = im_orig.size
comp_w = w * 2 + 20
comp_h = h + 60
comp = Image.new("RGB", (comp_w, comp_h), (11, 15, 23))

comp.paste(im_orig, (0, 60))
comp.paste(im_corr, (w + 20, 60))

draw = ImageDraw.Draw(comp)
try:
    font = ImageFont.truetype("arial.ttf", 26)
    font_sub = ImageFont.truetype("arial.ttf", 16)
except Exception:
    font = ImageFont.load_default()
    font_sub = font

# Headers
draw.text((20, 16), "ANTES: Imagem Original (Refletores estourados / Jogadores brancos)", font=font, fill=(248, 113, 113))
draw.text((w + 40, 16), "DEPOIS: Novo Preset '✨ Anti-Estouro' (Cores recuperadas / Gramado vivo)", font=font, fill=(0, 240, 255))

comp_path = os.path.join(out_dir, "comparacao_preset_anti_estouro.jpg")
comp.save(comp_path, "JPEG", quality=92)
print("Comparison saved at:", comp_path)
