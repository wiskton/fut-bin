import subprocess
import os

img_input = r"C:/Users/willem/.gemini/antigravity/brain/b0525ebb-8393-448d-a191-e679f76852fb/.user_uploaded/media_1794384996340_c172174d.jpg"
out_dir = r"C:/Users/willem/.gemini/antigravity/brain/b0525ebb-8393-448d-a191-e679f76852fb"

# Preset values: b=86 (eq brightness=-0.14), s=165 (saturation=1.65), c=120 (contrast=1.20)
# Option 1: eq only (b=-0.14, c=1.20, s=1.65)
out1 = os.path.join(out_dir, "preset_eq_only.jpg")
subprocess.run([
    "ffmpeg", "-y", "-i", img_input,
    "-vf", "eq=brightness=-0.14:contrast=1.20:saturation=1.65",
    "-q:v", "2", out1
], check=True)

# Option 2: eq with gamma recovery (b=-0.08, c=1.18, s=1.60, gamma=0.88)
out2 = os.path.join(out_dir, "preset_eq_gamma.jpg")
subprocess.run([
    "ffmpeg", "-y", "-i", img_input,
    "-vf", "eq=brightness=-0.08:contrast=1.18:saturation=1.60:gamma=0.88",
    "-q:v", "2", out2
], check=True)

# Option 3: curves highlight compression + eq
out3 = os.path.join(out_dir, "preset_curves_eq.jpg")
subprocess.run([
    "ffmpeg", "-y", "-i", img_input,
    "-vf", "curves=all='0/0 0.35/0.30 0.7/0.65 0.9/0.82 1/0.88',eq=brightness=-0.05:contrast=1.15:saturation=1.55",
    "-q:v", "2", out3
], check=True)

print("Test images generated!")
