from PIL import Image
import numpy as np

for name in ['imagem_original.jpg', 'preset_eq_only.jpg', 'preset_eq_gamma.jpg', 'preset_curves_eq.jpg']:
    img = Image.open('C:/Users/willem/.gemini/antigravity/brain/b0525ebb-8393-448d-a191-e679f76852fb/' + name)
    arr = np.array(img.convert('RGB'), dtype=float)
    luma = 0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]
    blown = (luma > 225).sum() / luma.size * 100
    max_c = np.max(arr, axis=2)
    min_c = np.min(arr, axis=2)
    delta = max_c - min_c
    sat = np.where(max_c > 0, delta / max_c, 0).mean() * 100
    print(f'{name}: mean_luma={luma.mean():.1f}, blown(>225)={blown:.2f}%, avg_sat={sat:.1f}%')
