import re

# 1. Update assistente_web.py
with open("C:/Users/willem/Documents/GitHub/fut-bin/assistente_web.py", "r", encoding="utf-8") as f:
    aw_content = f.read()

# Add corrigir_luzes to AjustarFundoPayload
if "class AjustarFundoPayload(BaseModel):" in aw_content and "corrigir_luzes: bool = False" not in aw_content[aw_content.find("class AjustarFundoPayload"):aw_content.find("class AjustarFundoPayload")+300]:
    aw_content = aw_content.replace(
        "    aplicar_video_clipes: bool = False\n",
        "    aplicar_video_clipes: bool = False\n    corrigir_luzes: bool = False\n"
    )
    with open("C:/Users/willem/Documents/GitHub/fut-bin/assistente_web.py", "w", encoding="utf-8") as f:
        f.write(aw_content)
    print("Updated assistente_web.py with AjustarFundoPayload.corrigir_luzes")
else:
    print("assistente_web.py already has AjustarFundoPayload.corrigir_luzes or pattern not matched")

# 2. Update web/assistente.js
with open("C:/Users/willem/Documents/GitHub/fut-bin/web/assistente.js", "r", encoding="utf-8") as f:
    js_content = f.read()

# Update _camPresetValues, _camPresetNomes, _camPresetCores
old_presets_block = """const _camPresetValues = {
  claro_vivido:{b:125,s:145,c:112,d:0,v:0},
  super_claro: {b:145,s:135,c:115,d:0,v:0},
  fifa:        {b:118,s:165,c:120,d:0,v:0},
  tv:          {b:110,s:130,c:108,d:0,v:5},
  cinema:      {b:105,s:90, c:125,d:0,v:15},
  original:    {b:100,s:100,c:100,d:0,v:0},
};"""

new_presets_block = """const _camPresetValues = {
  anti_estouro:{b:86, s:165,c:120,d:0,v:0},
  claro_vivido:{b:125,s:145,c:112,d:0,v:0},
  super_claro: {b:145,s:135,c:115,d:0,v:0},
  fifa:        {b:118,s:165,c:120,d:0,v:0},
  tv:          {b:110,s:130,c:108,d:0,v:5},
  cinema:      {b:105,s:90, c:125,d:0,v:15},
  original:    {b:100,s:100,c:100,d:0,v:0},
};"""

if old_presets_block in js_content:
    js_content = js_content.replace(old_presets_block, new_presets_block)
    print("Replaced _camPresetValues")

# Replace _camPresetNomes and _camPresetCores
old_nomes_re = re.compile(r"const _camPresetNomes = \{[^;]+\};")
new_nomes = "const _camPresetNomes = {anti_estouro:'✨ Anti-Estouro (Refletores)',claro_vivido:'🌟 Claro & Vívido',super_claro:'☀️ Super Iluminado',fifa:'🎮 FIFA/Game',tv:'📺 Transmissão TV',cinema:'🎥 Cinema',original:'🔄 Original'};"
js_content = old_nomes_re.sub(new_nomes, js_content)

old_cores_re = re.compile(r"const _camPresetCores = \{[^;]+\};")
new_cores = "const _camPresetCores = {anti_estouro:'#00f0ff',claro_vivido:'var(--accent)',super_claro:'#fde047',fifa:'#38bdf8',tv:'#4ade80',cinema:'#a78bfa',original:'var(--dim)'};"
js_content = old_cores_re.sub(new_cores, js_content)

# Update PIDS in renderCamerasFundo
old_pids = "const PIDS=['claro_vivido','super_claro','fifa','tv','cinema','original'];"
new_pids = "const PIDS=['anti_estouro','claro_vivido','super_claro','fifa','tv','cinema','original'];"
if old_pids in js_content:
    js_content = js_content.replace(old_pids, new_pids)
    print("Replaced PIDS")

# Update button rendering inside PIDS.forEach
old_btn_loop = """    PIDS.forEach(pid=>{
      const isAt=cfg._preset===pid, cp=_camPresetCores[pid]||'var(--dim)';
      const btn=document.createElement('button'); btn.type='button'; btn.dataset.preset=pid; btn.className='ghost';
      btn.style.cssText=`text-align:left;padding:5px 8px;font-size:10px;display:flex;flex-direction:column;gap:1px;border-color:${isAt?cp:'var(--line)'};${isAt?`background:${cp}22`:''}`;
      btn.innerHTML=`<span style="font-weight:700;color:${cp}">${_camPresetNomes[pid]}</span>`;
      btn.onclick=()=>aplicarPresetCam(ci,pid);
      pg.appendChild(btn);
    });"""

new_btn_loop = """    PIDS.forEach(pid=>{
      const isAt=cfg._preset===pid, cp=_camPresetCores[pid]||'var(--dim)';
      const isDestaque = pid === 'anti_estouro';
      const btn=document.createElement('button'); btn.type='button'; btn.dataset.preset=pid; btn.className='ghost';
      btn.style.cssText=`text-align:left;padding:6px 8px;font-size:10px;display:flex;flex-direction:column;gap:2px;border-color:${isAt?cp:(isDestaque?'rgba(0,240,255,0.45)':'var(--line)')};${isAt?`background:${cp}22`:''};${isDestaque?'grid-column:span 2;background:rgba(0,240,255,0.06);':''}`;
      btn.innerHTML=`<span style="font-weight:700;color:${cp}">${_camPresetNomes[pid]}</span>${isDestaque?'<span style="font-size:9px;color:var(--dim)">Corrige brilho estourado de refletores e dá vida às cores</span>':''}`;
      btn.onclick=()=>aplicarPresetCam(ci,pid);
      pg.appendChild(btn);
    });"""

if old_btn_loop in js_content:
    js_content = js_content.replace(old_btn_loop, new_btn_loop)
    print("Replaced btn loop")
else:
    print("Warning: old_btn_loop pattern not exact match, let's check")

# Update aplicarPresetCam to also set corrigir_luzes when anti_estouro
old_aplicar = """  cfg._preset=pid; cfg.brilho=vals.b; cfg.saturacao=vals.s; cfg.contraste=vals.c; cfg.desfoque=vals.d; cfg.vinheta=vals.v;"""
new_aplicar = """  cfg._preset=pid; cfg.brilho=vals.b; cfg.saturacao=vals.s; cfg.contraste=vals.c; cfg.desfoque=vals.d; cfg.vinheta=vals.v;
  cfg.corrigir_luzes=(pid==='anti_estouro');
  if(pid==='anti_estouro'){
    const c1=$('#chkCorrigirLuzesFinal'); if(c1) c1.checked=true;
    const c2=$('#chkCorrigirLuzesJogador'); if(c2) c2.checked=true;
  }"""
if old_aplicar in js_content:
    js_content = js_content.replace(old_aplicar, new_aplicar)
    print("Replaced aplicarPresetCam logic")

# Update salvarFundoCartela payload
old_payload = """      aplicar_video_clipes: cfg.aplicar_clipes !== false,"""
new_payload = """      aplicar_video_clipes: cfg.aplicar_clipes !== false,
      corrigir_luzes: !!cfg.corrigir_luzes,"""
if old_payload in js_content:
    js_content = js_content.replace(old_payload, new_payload)
    print("Replaced salvarFundoCartela payload")

with open("C:/Users/willem/Documents/GitHub/fut-bin/web/assistente.js", "w", encoding="utf-8") as f:
    f.write(js_content)
print("Saved web/assistente.js successfully")
