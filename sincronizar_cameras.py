"""Local visual matching of red LED game clocks; never changes match data."""
import cv2, numpy as np, time

def red(f):
 b,g,r=cv2.split(f.astype(np.int16)); return np.clip(r-np.maximum(g,b),0,255).astype(np.uint8)

def locate(cap,duration):
 samples=[]
 for t in [20,40,60,80]:
  cap.set(cv2.CAP_PROP_POS_MSEC,min(t,duration*.2)*1000);ok,f=cap.read()
  if not ok:continue
  ex=red(f);m=(ex>60).astype(np.uint8)*255
  cs,_=cv2.findContours(cv2.dilate(m,np.ones((5,9),np.uint8)),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
  boxes=[]
  for c in cs:
   x,y,w,h=cv2.boundingRect(c)
   if 18<=w<=150 and 18<=h<=110 and .65<w/h<2.8:
    boxes.append((x,y,w,h))
  samples.append(boxes)
 candidates=[]
 if not samples:raise ValueError("Não foi possível ler o vídeo.")
 for box in samples[0]:
  x,y,w,h=box;matches=[box]
  for boxes in samples[1:]:
   near=[a for a in boxes if abs(a[0]-x)<w*.4 and abs(a[1]-y)<h*.4 and abs(a[2]-w)<w*.4]
   if near:matches.append(min(near,key=lambda a:abs(a[0]-x)+abs(a[1]-y)))
  if len(matches)>=3:candidates.append((len(matches),w*h,tuple(np.median(matches,axis=0).astype(int))))
 if not candidates:raise ValueError('Relógio LED vermelho não localizado. O placar precisa estar visível nas câmeras.')
 box=max(candidates)[2]; x,y,w,h=box
 # Tighten to the clock row; adjacent scoreboard may touch lower row.
 cap.set(cv2.CAP_PROP_POS_MSEC,min(60,duration*.2)*1000);ok,f=cap.read()
 top=red(f[y:y+int(h*.48),x:x+w]); m=(top>max(50,float(top.max())*.45)).astype(np.uint8)
 cs,_=cv2.findContours(cv2.dilate(m,np.ones((2,3),np.uint8)),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 if not cs:raise ValueError("Relógio sem contraste suficiente.")
 rx,ry,rw,rh=cv2.boundingRect(max(cs,key=cv2.contourArea))
 yy,xx=np.where(m[ry:ry+rh,rx:rx+rw]); xx+=rx; yy+=ry
 if len(xx)<10:raise ValueError('Relógio sem contraste suficiente.')
 return (x+int(xx.min()),y+int(yy.min()),int(xx.max()-xx.min()+1),int(yy.max()-yy.min()+1))

def sig(cap,t,roi):
 cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,f=cap.read()
 if not ok:return np.zeros(960)
 x,y,w,h=roi
 x0=max(0,x-40);y0=max(0,y-70);reg=f[y0:min(f.shape[0],y+h+90),x0:min(f.shape[1],x+w+40)]
 e=red(reg);m=(e>60).astype(np.uint8)
 cs,_=cv2.findContours(cv2.dilate(m,np.ones((5,9),np.uint8)),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 boxes=[cv2.boundingRect(c) for c in cs]
 boxes=[b for b in boxes if 18<=b[2]<=100 and 18<=b[3]<=90 and .65<b[2]/b[3]<2.8]
 if not boxes:return np.zeros(960)
 bx,by,bw,bh=min(boxes,key=lambda b:abs(x0+b[0]+b[2]/2-(x+w/2))+.2*abs(y0+b[1]-y))
 top=e[by:by+int(bh*.48),bx:bx+bw];m=(top>max(50,float(top.max())*.45)).astype(np.uint8)
 cs,_=cv2.findContours(cv2.dilate(m,np.ones((2,3),np.uint8)),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 if not cs:return np.zeros(960)
 rx,ry,rw,rh=cv2.boundingRect(max(cs,key=cv2.contourArea)); yy,xx=np.where(m[ry:ry+rh,rx:rx+rw])
 if len(xx)<8:return np.zeros(960)
 xx+=rx;yy+=ry;e=top[yy.min():yy.max()+1,xx.min():xx.max()+1]
 e=cv2.resize(e,(48,20)); e=cv2.GaussianBlur(e,(3,3),0).astype(float)
 e=(e-np.mean(e));v=e.ravel(); norm=np.linalg.norm(v)
 return v/norm if norm>50 else np.zeros(960)


def centered(values):
    values = np.asarray(values, dtype=np.float32)
    values = values - values.mean(axis=0)
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-6)


def coarse_offsets(a, b, step):
    a, b = centered(a), centered(b)
    scores = []
    minimum = max(15, int(min(len(a), len(b)) * .55))
    for lag in range(-len(a) + minimum, len(b) - minimum + 1):
        start, end = max(0, -lag), min(len(a), len(b)-lag)
        if end-start < minimum:
            continue
        scores.append((float(np.mean(np.sum(a[start:end]*b[start+lag:end+lag], axis=1))), lag*step))
    return sorted(scores, reverse=True)


def synchronize(cameras, progress, canceled):
    started = time.monotonic()
    captures = []
    def check():
        if canceled():
            raise InterruptedError('Sincronização cancelada. Os tempos anteriores foram mantidos.')
        if time.monotonic()-started > 600:
            raise ValueError('A análise excedeu 10 minutos. Os tempos anteriores foram mantidos.')
    try:
        durations, regions, samples = [], [], []
        for camera in cameras:
            check()
            cap = cv2.VideoCapture(camera['video'], cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 2])
            captures.append(cap)
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration = cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps if fps else 0
            if duration < 120:
                raise ValueError('Use gravações com pelo menos 2 minutos e o relógio visível.')
            durations.append(min(duration, 620))
            progress(f"Localizando o relógio da câmera {camera['indice']+1}…")
            regions.append(locate(cap, duration))
        step = 20
        for index, (cap, duration, roi) in enumerate(zip(captures, durations, regions)):
            times = np.arange(20, duration-20, step)
            values = []
            for k, t in enumerate(times):
                check()
                if k % 10 == 0:
                    progress(f"Lendo relógio da câmera {cameras[index]['indice']+1}: {round(k/len(times)*100)}%")
                values.append(sig(cap, float(t), roi))
            values = np.asarray(values)
            if np.mean(np.linalg.norm(values, axis=1) > .5) < .7:
                raise ValueError('O relógio não ficou legível em trechos suficientes. Os tempos anteriores foram mantidos.')
            if float(np.mean(np.var(values, axis=0))) < 0.000015:
                raise ValueError('O relógio parece parado ou ilegível. Os tempos anteriores foram mantidos.')
            samples.append(values)
        offsets = [0.0]
        qualities = []
        for index in range(1, len(cameras)):
            scores = coarse_offsets(samples[0], samples[index], step)
            if not scores or scores[0][0] < .12:
                raise ValueError('Não encontrei uma sequência de relógio correspondente com segurança. Ajuste manualmente.')
            coarse = scores[0][1]
            lo = max(35, -coarse+35)
            hi = min(durations[0]-35, durations[index]-coarse-35)
            anchors = np.linspace(lo, hi, 13)
            reference = np.array([sig(captures[0], float(t), regions[0]) for t in anchors])
            ref_mean = samples[0].mean(axis=0)
            alt_mean = samples[index].mean(axis=0)
            def norm(v):
                return v/np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)
            reference = norm(reference-ref_mean)
            fine = []
            for k, offset in enumerate(range(coarse-step//2-1, coarse+step//2+2)):
                check()
                progress(f"Conferindo alinhamento da câmera {cameras[index]['indice']+1}: {round(k/(step+3)*100)}%")
                other = np.array([sig(captures[index], float(t+offset), regions[index]) for t in anchors])
                similarities = np.sum(reference*norm(other-alt_mean),axis=1)
                fine.append((float(np.mean(similarities)), offset, similarities))
            fine.sort(key=lambda row:row[0], reverse=True)
            best, offset, similarities = fine[0]
            rival = max((row[0] for row in fine if abs(row[1]-offset)>3), default=-1)
            # A single coincident or frozen clock is not enough to apply offsets.
            if best < .25 or best-rival < .035 or np.count_nonzero(similarities>.15) < 8:
                raise ValueError('O relógio ficou ambíguo entre as câmeras. Não alterei os tempos; use o ajuste manual.')
            offsets.append(float(offset))
            qualities.append(round(best, 3))
        base = max(0.0, -min(offsets))
        return {'cameras':[{'indice':c['indice'],'inicio_jogo_s':round(base+off,3)} for c,off in zip(cameras,offsets)], 'qualidade':qualities, 'precisao_s':1}
    finally:
        for cap in captures:
            cap.release()
