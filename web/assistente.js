const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const PASSOS = [
  ['s-inicio','Início'], ['s-jogadores','⚽ Jogadores'], ['s-video','1 · Vídeo'], ['s-placar','2 · Placar'], ['s-gols','3 · Detectar/Cortar'],
  ['s-revisar','4 · Revisar cortes'], ['s-dados','5 · Dados da partida'], ['s-marcar','6 · Marcação'],
  ['s-resumo','7 · Resumo'], ['s-final','8 · Vídeo final'], ['s-jogador','9 · Jogador'],
];
let passoAtual = 's-video';

let ESTADO = {
  video: null,           // {nome, caminho, duracao_s}
  cameras: [null, null, null], // vídeos sincronizados; a 1 é a referência do placar
  placarRect: null,      // [x,y,w,h] em pixels do frame original
  gols: [],              // gols confirmados (schema gols.json) usados na marcacao
  clipes: {},            // "01" -> url
  atual: 0,
  indiceAtual: null,     // Indice do clipe atualmente selecionado (evita desalinhamento)
};
let S = { meta:{data:'',comp:'',local:'',pelada:'Will Cup'},
  times:[{nome:'Time Amarelo',cor:'#eab308',jogadores:[]},{nome:'Time Azul',cor:'#2563eb',jogadores:[]}] };
let rascunho = {tipo:null,time:null,autor:null,assist:null,lance:null,destaque:null};
const TIPOS_LANCE = ['Defesaça','Chute na trave','Quase gol','Drible','Bola perdida','Confusão','Engraçado'];
const TIPOS_CLIPE = [
  { id: 'gol', rotulo: 'Gol', icon: '⚽', cor: 'var(--accent)', bg: 'rgba(0,255,135,0.18)', border: '#00ff87', isGol: true, hotkey: 'g' },
  { id: 'lance', rotulo: 'Outro lance', icon: '🎬', cor: '#00f0ff', bg: 'rgba(0,240,255,0.18)', border: '#00f0ff', lanceNome: 'Outro lance', isGol: false, hotkey: 'o' },
];

const POSICOES_JOGADORES = [
  { id: 'goleiro', rotulo: 'Goleiro', sigla: 'GOL', icon: '🧤', cor: '#eab308' },
  { id: 'zagueiro', rotulo: 'Zagueiro', sigla: 'ZAG', icon: '🛡️', cor: '#2563eb' },
  { id: 'meio', rotulo: 'Meio', sigla: 'MEI', icon: '⚙️', cor: '#10b981' },
  { id: 'atacante', rotulo: 'Atacante', sigla: 'ATA', icon: '⚽', cor: '#f43f5e' },
];

function obterPosicaoJogador(timeIdx, nome){
  if(!S.times[timeIdx]) return 'meio';
  const posicoes = S.times[timeIdx].posicoes || {};
  if(posicoes[nome]) return posicoes[nome];
  const jgs = S.times[timeIdx].jogadores || [];
  const idx = jgs.indexOf(nome);
  if(idx === 0) return 'goleiro';
  if(idx === 1 || idx === 2) return 'zagueiro';
  if(idx === 3 || idx === 4) return 'meio';
  return 'atacante';
}

// A tela marca o primeiro do elenco como goleiro mesmo sem escolha manual,
// mas `posicoes` só guardava quem foi clicado. Salvar a escalação completa
// evita que o vídeo trate esse goleiro como meio-campo.
function escalacaoCompleta(timeIdx){
  const t = S.times[timeIdx];
  if(!t) return {};
  const out = Object.assign({}, t.posicoes || {});
  (t.jogadores || []).forEach(nome => { out[nome] = obterPosicaoJogador(timeIdx, nome); });
  return out;
}

function definirPosicaoJogador(timeIdx, nome, pos){
  if(!S.times[timeIdx]) return;
  if(!S.times[timeIdx].posicoes) S.times[timeIdx].posicoes = {};
  S.times[timeIdx].posicoes[nome] = pos;
  renderPosicoesElenco(timeIdx);
  agendarSalvar();
}

function autoDefinirPosicoes(){
  [0, 1].forEach(timeIdx => {
    if(!S.times[timeIdx]) return;
    const jgs = S.times[timeIdx].jogadores || [];
    if(!S.times[timeIdx].posicoes) S.times[timeIdx].posicoes = {};
    jgs.forEach((nome, idx) => {
      if(idx === 0) S.times[timeIdx].posicoes[nome] = 'goleiro';
      else if(idx === 1 || idx === 2) S.times[timeIdx].posicoes[nome] = 'zagueiro';
      else if(idx === 3 || idx === 4) S.times[timeIdx].posicoes[nome] = 'meio';
      else S.times[timeIdx].posicoes[nome] = 'atacante';
    });
    renderPosicoesElenco(timeIdx);
  });
  agendarSalvar();
}

let _uploadJogadorAlvo = null;
function acionarUploadFoto(timeIdx, nome){
  _uploadJogadorAlvo = { timeIdx, nome };
  const input = $('#fileFotoJogador');
  if(input){
    input.value = '';
    input.click();
  }
}

async function removerFotoJogador(timeIdx, nome){
  if(!confirm(`Remover foto de "${nome}"?`)) return;
  try {
    const res = await fetch('/api/remover_foto_jogador', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ jogador: nome, time_idx: timeIdx })
    });
    if(S.times[timeIdx] && S.times[timeIdx].fotos){
      delete S.times[timeIdx].fotos[nome];
    }
    renderPosicoesElenco(timeIdx);
    agendarSalvar();
  } catch(e){
    alert('Erro ao remover foto: ' + e.message);
  }
}

function renderPosicoesElenco(timeIdx){
  const el = timeIdx === 0 ? $('#posElencoA') : $('#posElencoB');
  if(!el) return;
  const t = S.times[timeIdx];
  if(!t || !t.jogadores || !t.jogadores.length){
    el.innerHTML = '<div class="hint" style="font-size:12px">Digite os nomes acima para definir as posições e fotos.</div>';
    return;
  }
  let html = '<div class="fut-roster-box">';
  html += `<div class="fut-roster-header"><span class="fut-roster-title">DISPOSIÇÃO TÁTICA & FOTOS · ${(t.nome||'TIME').toUpperCase()}</span><span class="fut-roster-count">${t.jogadores.length} ATLETAS</span></div>`;
  html += '<div class="fut-roster-list">';
  const fotosMap = t.fotos || {};
  t.jogadores.forEach(nome => {
    const posAtual = obterPosicaoJogador(timeIdx, nome);
    const posObj = POSICOES_JOGADORES.find(p => p.id === posAtual) || POSICOES_JOGADORES[2];
    const fotoUrl = fotosMap[nome] || null;
    const nomeEsc = nome.replace(/'/g, "\\'");

    html += `<div class="fut-player-row">`;
    html += `  <div class="fut-player-info">`;
    if(fotoUrl){
      html += `    <div class="fut-avatar-wrap" title="Clique para trocar foto de ${nome}" onclick="acionarUploadFoto(${timeIdx}, '${nomeEsc}')">`;
      html += `      <img src="${fotoUrl}?t=${Date.now()}" class="fut-avatar-img" alt="${nome}">`;
      html += `      <button type="button" class="fut-avatar-del" title="Remover foto" onclick="event.stopPropagation(); removerFotoJogador(${timeIdx}, '${nomeEsc}')">×</button>`;
      html += `    </div>`;
    } else {
      html += `    <div class="fut-avatar-wrap vazio" title="Subir foto de ${nome}" onclick="acionarUploadFoto(${timeIdx}, '${nomeEsc}')">`;
      html += `      <span class="fut-avatar-icon">📷</span>`;
      html += `    </div>`;
    }
    html += `    <div class="fut-player-badge pos-${posAtual}">${posObj.sigla}</div>`;
    html += `    <span class="fut-player-name" title="${nome}">${nome}</span>`;
    html += `  </div>`;
    html += `  <div class="fut-pos-buttons">`;
    POSICOES_JOGADORES.forEach(p => {
      const ativa = (posAtual === p.id);
      const cls = ativa ? `fut-btn-pos sel pos-${p.id}` : 'fut-btn-pos';
      html += `<button type="button" class="${cls}" onclick="definirPosicaoJogador(${timeIdx}, '${nomeEsc}', '${p.id}')" title="${p.rotulo}">${p.sigla}</button>`;
    });
    html += `  </div>`;
    html += `</div>`;
  });
  html += '</div></div>';
  el.innerHTML = html;
}

function corTextoParaFundo(hex){
  if(!hex || !hex.startsWith('#')) return '#ffffff';
  const c = hex.replace('#','');
  const r = parseInt(c.substr(0,2),16)||0;
  const g = parseInt(c.substr(2,2),16)||0;
  const b = parseInt(c.substr(4,2),16)||0;
  const yiq = ((r*299)+(g*587)+(b*114))/1000;
  return (yiq >= 140) ? '#04140a' : '#ffffff';
}

function normalizarTexto(txt){
  return String(txt || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

function obterInfoTipo(status, lance){
  if(!status && !lance) return null;
  const s = normalizarTexto(status);
  const l = normalizarTexto(lance);
  if(s === 'revisar' || s === 'pendente' || s === 'null' || s === 'none' || s === 'undefined') return null;

  if(s === 'gol' || (!s && l === 'gol')) return TIPOS_CLIPE[0];
  if(s === 'confusao' || (s !== 'gol' && l === 'confusao')){
    return { id: 'confusao', rotulo: 'Confusão', icon: '🥊', cor: '#a855f7',
             bg: 'rgba(168,85,247,0.18)', border: '#a855f7', lanceNome: 'Confusão', isGol: false };
  }
  if(s === 'engracado' || (s !== 'gol' && l === 'engracado')){
    return { id: 'engracado', rotulo: 'Engraçado', icon: '🤣', cor: '#f59e0b',
             bg: 'rgba(245,158,11,0.18)', border: '#f59e0b', lanceNome: 'Engraçado', isGol: false };
  }
  if(s || l) return TIPOS_CLIPE[1];
  return null;
}

/* ------------------------------------------------------------ tempo */
function parseTempo(txt){
  if(!txt) return null;
  txt = String(txt).trim();
  if(!txt) return null;
  if(txt.indexOf(':')===-1) return parseFloat(txt);
  return txt.split(':').reduce((acc,p)=>acc*60+parseFloat(p), 0);
}
function fmtTempo(s){
  s = Math.max(0, s|0);
  const m = Math.floor(s/60), r = s%60;
  return String(m).padStart(2,'0')+':'+String(r).padStart(2,'0');
}

function mostrarAlertaClipePronto({ indice, inicio_s, fim_s, dur, tipo, infoTipo, clipe, restantesNaFila = 0 }){
  let container = document.getElementById('hudToastContainer');
  if(!container){
    container = document.createElement('div');
    container.id = 'hudToastContainer';
    container.className = 'hud-toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'hud-toast';

  const ehPendente = !infoTipo && (tipo === 'pendente' || tipo === 'sem_marcar' || !tipo);
  const icon = (infoTipo && infoTipo.icon) ? infoTipo.icon : (tipo === 'gol' ? '⚽' : (tipo === 'lance' ? '🎬' : '⏳'));
  const rotulo = (infoTipo && infoTipo.rotulo) ? infoTipo.rotulo : (tipo === 'gol' ? 'Gol' : (tipo === 'lance' ? 'Lance' : 'Sem marcação'));
  const idxStr = String(indice).padStart(2, '0');
  const durSec = (dur != null && !isNaN(dur)) ? Math.round(dur) : Math.round(fim_s - inicio_s);
  const tempoStr = `${fmtTempo(inicio_s)} ➔ ${fmtTempo(fim_s)}`;
  const badgeFila = (restantesNaFila > 0)
    ? `<span style="background:rgba(0,240,255,0.22); color:var(--cyan); border:1px solid var(--cyan); padding:1px 7px; border-radius:10px; font-size:10px; font-weight:800; margin-left:6px">+${restantesNaFila} na fila</span>`
    : '';

  toast.innerHTML = `
    <div class="hud-toast-icon-wrap" style="${ehPendente ? 'border-color:var(--gold); box-shadow:0 0 16px rgba(255,215,0,0.4); background:radial-gradient(circle, rgba(255,215,0,0.2) 0%, transparent 100%)' : ''}">
      <span>${icon}</span>
      <div class="hud-toast-check" style="${ehPendente ? 'background:var(--gold); color:#04140a' : ''}">✓</div>
    </div>
    <div class="hud-toast-body">
      <div class="hud-toast-tag" style="${ehPendente ? 'color:var(--gold)' : ''}">Corte Salvo · ${rotulo} ${badgeFila}</div>
      <div class="hud-toast-title">Clipe #${idxStr} pronto!</div>
      <div class="hud-toast-time"><span>⏱</span> <b>${tempoStr}</b> (${durSec}s)${ehPendente ? ' · definir depois' : ''}</div>
    </div>
    <div class="hud-toast-actions">
      ${clipe ? `<button type="button" class="hud-toast-btn-ver" title="Abrir clipe para conferir">👁️ Ver</button>` : ''}
      <button type="button" class="hud-toast-btn-close" title="Fechar alerta">✕</button>
    </div>
    <div class="hud-toast-timer-bar" style="${ehPendente ? 'background:linear-gradient(90deg, var(--gold) 0%, var(--cyan) 100%)' : ''}"></div>
  `;

  const btnClose = toast.querySelector('.hud-toast-btn-close');
  const fechar = () => {
    if(toast.classList.contains('saindo')) return;
    toast.classList.add('saindo');
    setTimeout(() => { toast.remove(); }, 350);
  };
  btnClose.onclick = fechar;

  const btnVer = toast.querySelector('.hud-toast-btn-ver');
  if(btnVer && clipe){
    btnVer.onclick = () => {
      fechar();
      abrirModalClipe(clipe);
    };
  }

  container.appendChild(toast);
  setTimeout(fechar, 4500);
}

function mostrarAlertaFilaAdicionada(posicaoFila, job){
  let container = document.getElementById('hudToastContainer');
  if(!container){
    container = document.createElement('div');
    container.id = 'hudToastContainer';
    container.className = 'hud-toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'hud-toast';
  toast.style.borderColor = 'var(--cyan)';
  toast.style.boxShadow = '0 16px 40px rgba(0,0,0,0.85), 0 0 25px rgba(0,240,255,0.35)';

  const ehPendente = !job.infoTipo && (job.tipo === 'pendente' || job.tipo === 'sem_marcar' || !job.tipo);
  const icon = (job.infoTipo && job.infoTipo.icon) ? job.infoTipo.icon : (job.tipo === 'gol' ? '⚽' : (job.tipo === 'lance' ? '🎬' : '⏳'));
  const rotulo = (job.infoTipo && job.infoTipo.rotulo) ? job.infoTipo.rotulo : (job.tipo === 'gol' ? 'Gol' : (job.tipo === 'lance' ? 'Lance' : 'Sem marcação'));
  const tempoStr = `${fmtTempo(job.inicio_s)} ➔ ${fmtTempo(job.fim_s)}`;

  toast.innerHTML = `
    <div class="hud-toast-icon-wrap" style="border-color:var(--cyan); background:radial-gradient(circle, rgba(0,240,255,0.25) 0%, transparent 100%)">
      <span>${ehPendente ? '⏳' : '📥'}</span>
      <div class="hud-toast-check" style="background:var(--cyan); color:#041416">#${posicaoFila}</div>
    </div>
    <div class="hud-toast-body">
      <div class="hud-toast-tag" style="color:var(--cyan)">Na Fila · ${posicaoFila}º corte pendente</div>
      <div class="hud-toast-title">Corte agendado (${rotulo})</div>
      <div class="hud-toast-time"><span>⏱</span> <b>${tempoStr}</b> (${Math.round(job.dur)}s)</div>
    </div>
    <div class="hud-toast-actions">
      <button type="button" class="hud-toast-btn-close" title="Fechar alerta">✕</button>
    </div>
    <div class="hud-toast-timer-bar" style="background:linear-gradient(90deg, var(--cyan) 0%, var(--accent) 100%); animation-duration:3.2s"></div>
  `;

  const btnClose = toast.querySelector('.hud-toast-btn-close');
  const fechar = () => {
    if(toast.classList.contains('saindo')) return;
    toast.classList.add('saindo');
    setTimeout(() => { toast.remove(); }, 350);
  };
  btnClose.onclick = fechar;

  container.appendChild(toast);
  setTimeout(fechar, 3200);
}

/* ================= ALERTA DE RENDERIZAÇÃO CONCLUÍDA ================= */
function tocarSomVitoria(){
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    if(ctx.state === 'suspended') ctx.resume();
    const notas = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6 (Acorde de vitória)
    notas.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, ctx.currentTime + (i * 0.11));
      gain.gain.setValueAtTime(0.18, ctx.currentTime + (i * 0.11));
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + (i * 0.11) + 0.6);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + (i * 0.11));
      osc.stop(ctx.currentTime + (i * 0.11) + 0.65);
    });
  } catch(e){
    console.log('AudioContext indisponível:', e);
  }
}

function dispararConfetes(){
  const wrap = document.getElementById('renderConfettiWrap');
  if(!wrap) return;
  wrap.innerHTML = '';
  const cores = ['#00ff87', '#00f0ff', '#ffd700', '#ff3366', '#ffffff'];
  for(let i = 0; i < 45; i++){
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    piece.style.left = Math.random() * 100 + '%';
    piece.style.top = (Math.random() * 20 - 10) + 'px';
    piece.style.backgroundColor = cores[Math.floor(Math.random() * cores.length)];
    piece.style.width = (Math.random() * 6 + 6) + 'px';
    piece.style.height = (Math.random() * 8 + 6) + 'px';
    piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
    piece.style.animationDelay = (Math.random() * 0.8) + 's';
    piece.style.animationDuration = (Math.random() * 1.5 + 2) + 's';
    wrap.appendChild(piece);
  }
}

function fecharModalRender(){
  const m = document.getElementById('modalRenderConcluido');
  if(m) m.hidden = true;
}

function fecharModalRenderEAssistir(qual){
  fecharModalRender();
  irPara('s-final');
  const resFinal = document.getElementById('resultadoFinal');
  if(resFinal){
    resFinal.scrollIntoView({behavior:'smooth', block:'start'});
    const vidId = (qual === 'gols') ? 'videoPlayerApenasGols' : 'videoPlayerMelhoresMomentos';
    const v = document.getElementById(vidId);
    if(v){
      setTimeout(() => {
        try { v.play(); } catch(e){}
      }, 400);
    }
  }
}

function mostrarAlertaHUDVideoFinal(){
  let container = document.getElementById('hudToastContainer');
  if(!container){
    container = document.createElement('div');
    container.id = 'hudToastContainer';
    container.className = 'hud-toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'hud-toast';
  toast.style.borderColor = 'var(--accent)';
  toast.style.boxShadow = '0 16px 40px rgba(0,0,0,0.85), 0 0 28px rgba(0,255,135,0.45)';

  toast.innerHTML = `
    <div class="hud-toast-icon-wrap" style="border-color:var(--gold); background:radial-gradient(circle, rgba(255,215,0,0.3) 0%, transparent 70%)">
      <span>🏆</span>
      <div class="hud-toast-check" style="background:var(--accent); color:#04140a">⚽</div>
    </div>
    <div class="hud-toast-body">
      <div class="hud-toast-tag" style="color:var(--accent)">Processo Finalizado · Full HD</div>
      <div class="hud-toast-title">Vídeos Finais Prontos!</div>
      <div class="hud-toast-time"><span>🎬</span> Melhores Momentos e Apenas Gols gerados</div>
    </div>
    <div class="hud-toast-actions">
      <button type="button" class="hud-toast-btn-ver" style="background:var(--accent); color:#04140a; border:none; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:800; cursor:pointer" title="Ver vídeos gerados">👁️ Ver</button>
      <button type="button" class="hud-toast-btn-close" title="Fechar alerta">✕</button>
    </div>
    <div class="hud-toast-timer-bar" style="background:linear-gradient(90deg, var(--accent) 0%, var(--gold) 100%); animation-duration:10s"></div>
  `;

  const btnClose = toast.querySelector('.hud-toast-btn-close');
  const fechar = () => {
    if(toast.classList.contains('saindo')) return;
    toast.classList.add('saindo');
    setTimeout(() => { toast.remove(); }, 350);
  };
  btnClose.onclick = fechar;

  const btnVer = toast.querySelector('.hud-toast-btn-ver');
  if(btnVer){
    btnVer.onclick = () => {
      fechar();
      fecharModalRenderEAssistir('melhores');
    };
  }

  container.appendChild(toast);
  setTimeout(fechar, 10000);
}

function mostrarAlertaRenderizacaoConcluida(){
  tocarSomVitoria();

  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('⚽ Vídeos Prontos! — fut-bin', {
        body: 'A renderização dos melhores momentos e dos gols foi concluída com sucesso!',
        icon: '/web/icon.png'
      });
    }
  } catch(e){}

  const modal = document.getElementById('modalRenderConcluido');
  if(modal){
    modal.hidden = false;
    dispararConfetes();
  }

  mostrarAlertaHUDVideoFinal();
}

/* ------------------------------------------------------------ navegacao */
function montarNav(){
  const nav = $('#nav'); nav.innerHTML='';
  PASSOS.forEach(([id,rot])=>{
    const b = document.createElement('button');
    b.textContent = rot; b.dataset.id = id;
    b.onclick = ()=> irPara(id);
    nav.appendChild(b);
  });
  atualizarNav();
}
function atualizarNav(){
  $$('#nav button').forEach(b=>{
    b.classList.toggle('on', b.dataset.id===passoAtual);
  });
}
function inicializarVideoCompleto(){
  const vc = $('#videoCompleto');
  const st = $('#statusVideoCompleto');
  if(!vc) return;
  if(vc.getAttribute('data-carregado') && vc.src) return;
  const urlEsperada = urlVideoCompleto(cameraVerValida());
  rotuloCameraVideoCompleto();
  if(vc.getAttribute('data-carregado') !== urlEsperada){
    vc.setAttribute('data-carregado', urlEsperada);
    if(st) st.innerHTML = '<span class="spinner"></span> Carregando vídeo do jogo...';
    vc.addEventListener('loadedmetadata', () => aplicarQualidadeVideoCompleto(), {once:true});
    vc.src = urlEsperada;
    vc.load();
    if(typeof aplicarFiltroBrilho === 'function') aplicarFiltroBrilho();
  }
}

/* ------------------------------------------------------------ sessoes / multi-video */
let sessoesCache = [];
let sessaoAtivaId = null;

async function carregarSessoes(){
  try {
    const res = await (await fetch('/api/sessoes')).json();
    sessoesCache = res.sessoes || [];
    sessaoAtivaId = res.sessao_ativa_id;

    // Atualiza o pill no header
    const ativa = sessoesCache.find(s => s.id === sessaoAtivaId || s.is_ativa) || sessoesCache[0];
    if(ativa){
      const elNome = $('#sessaoHeaderNome');
      const elBadge = $('#sessaoHeaderBadge');
      if(elNome) elNome.textContent = ativa.nome || 'Sessão Ativa';
      if(elBadge) elBadge.textContent = (ativa.n_gols || 0) + ' gol(s)';
    }

    renderCardsSessoesInicio();
    renderListaSessoesModal();
    return res;
  } catch(err) {
    console.warn('Erro ao carregar sessões:', err);
    return null;
  }
}

function renderCardsSessoesInicio(){
  const container = $('#listaSessoesCards');
  if(!container) return;
  const badgeTotal = $('#badgeTotalSessoes');
  if(badgeTotal) badgeTotal.textContent = `${sessoesCache.length} ${sessoesCache.length === 1 ? 'partida' : 'partidas'}`;

  if(!sessoesCache.length){
    container.innerHTML = `<div class="hint" style="grid-column:1/-1; padding:20px; text-align:center;">Nenhuma partida encontrada. Clique em "+ Nova Sessão" para começar.</div>`;
    return;
  }

  container.innerHTML = sessoesCache.map(s => {
    const isAtiva = (s.id === sessaoAtivaId || s.is_ativa);
    const videoNome = s.video_nome || (s.video ? s.video.split(/[\\/]/).pop() : 'Nenhum vídeo escolhido');
    const dataFmt = s.data || (s.atualizado_em ? s.atualizado_em.split('T')[0] : '');

    return `
      <div class="card-sessao ${isAtiva ? 'ativa' : ''}" id="card-sessao-${s.id}">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
          <div>
            <div style="display:flex; align-items:center; gap:6px;">
              ${isAtiva ? '<span class="sessao-status-dot" style="width:7px; height:7px;"></span><span style="font-size:10px; font-weight:800; color:#00ff87; text-transform:uppercase;">EM EDIÇÃO AGORA</span>' : '<span style="font-size:10px; font-weight:700; color:rgba(255,255,255,0.45); text-transform:uppercase;">SALVA NO HISTÓRICO</span>'}
            </div>
            <h4 style="margin:4px 0 2px 0; font-size:15px; color:#fff; word-break:break-word;">${s.nome || 'Sessão Sem Nome'}</h4>
            <div class="hint" style="font-size:11px; margin:0;" title="${s.video || ''}">📹 ${videoNome}</div>
            ${dataFmt ? `<div class="hint" style="font-size:10px; margin-top:2px;">📅 ${dataFmt}</div>` : ''}
          </div>
          ${isAtiva ? '<span class="card-sessao-badge destaque">ATIVA</span>' : ''}
        </div>

        <div class="card-sessao-badges">
          <span class="card-sessao-badge ${s.n_gols > 0 ? 'destaque' : ''}">⚽ ${s.n_gols || 0} gol(s)</span>
          <span class="card-sessao-badge">🎬 ${s.n_clipes || 0} clipe(s)</span>
          ${s.placar_ok ? '<span class="card-sessao-badge" style="color:#00f0ff;">🎯 Placar OK</span>' : ''}
          ${s.final_ok ? '<span class="card-sessao-badge" style="color:#f59e0b;">🏆 Vídeo Pronto</span>' : ''}
        </div>

        <div style="margin-top:12px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08); display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap;">
          <div>
            ${isAtiva ?
              '<button type="button" class="act" style="font-size:11px; padding:5px 12px;" onclick="irPara(passoParaContinuar())">Continuar →</button>' :
              `<button type="button" class="ghost" style="font-size:11px; padding:5px 12px; border-color:rgba(0,255,135,0.5); color:#00ff87; font-weight:700;" onclick="alternarSessao('${s.id}')">▶ Alternar para esta</button>`
            }
          </div>
          <div style="display:flex; gap:4px;">
            <button type="button" class="btnPequeno ghost" title="Renomear sessão" onclick="promptRenomearSessao('${s.id}', '${encodeURIComponent(s.nome || '')}')">✏</button>
            <button type="button" class="btnPequeno ghost" title="Duplicar sessão" onclick="duplicarSessao('${s.id}')">📋</button>
            ${!isAtiva ? `<button type="button" class="btnPequeno ghost" style="color:#ef4444;" title="Excluir sessão" onclick="excluirSessao('${s.id}', '${encodeURIComponent(s.nome || '')}')">🗑</button>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderListaSessoesModal(){
  const container = $('#modalListaSessoes');
  if(!container) return;

  if(!sessoesCache.length){
    container.innerHTML = `<div class="hint" style="padding:20px; text-align:center;">Nenhuma partida cadastrada.</div>`;
    return;
  }

  container.innerHTML = sessoesCache.map(s => {
    const isAtiva = (s.id === sessaoAtivaId || s.is_ativa);
    const videoNome = s.video_nome || (s.video ? s.video.split(/[\\/]/).pop() : 'Sem vídeo');

    return `
      <div style="background:linear-gradient(160deg, #131c2a 0%, #0c131d 100%); border:1px solid ${isAtiva ? '#00ff87' : 'var(--line)'}; border-radius:10px; padding:12px; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
        <div style="flex:1; min-width:200px;">
          <div style="display:flex; align-items:center; gap:6px;">
            ${isAtiva ? '<span class="sessao-status-dot" style="width:7px; height:7px;"></span><span style="font-size:10px; font-weight:800; color:#00ff87;">ATIVA AGORA</span>' : '<span style="font-size:10px; color:rgba(255,255,255,0.4);">HISTÓRICO</span>'}
            <h4 style="margin:0; font-size:15px; color:#fff;">${s.nome || 'Sessão Sem Nome'}</h4>
          </div>
          <div class="hint" style="font-size:11px; margin-top:2px;">📹 ${videoNome} &bull; ⚽ ${s.n_gols || 0} gols &bull; 🎬 ${s.n_clipes || 0} clipes</div>
        </div>
        <div style="display:flex; align-items:center; gap:6px;">
          ${isAtiva ?
            '<span class="card-sessao-badge destaque" style="font-size:12px; padding:4px 10px;">✔ Em edição</span>' :
            `<button type="button" class="act" style="font-size:12px; padding:6px 14px;" onclick="alternarSessao('${s.id}')">Alternar para esta</button>`
          }
          <button type="button" class="ghost btnPequeno" title="Renomear" onclick="promptRenomearSessao('${s.id}', '${encodeURIComponent(s.nome || '')}')">✏</button>
          <button type="button" class="ghost btnPequeno" title="Duplicar" onclick="duplicarSessao('${s.id}')">📋</button>
          ${!isAtiva ? `<button type="button" class="ghost btnPequeno" style="color:#ef4444;" title="Excluir" onclick="excluirSessao('${s.id}', '${encodeURIComponent(s.nome || '')}')">🗑</button>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function abrirModalSessoes(){
  carregarSessoes().then(() => {
    const m = $('#modalSessoes');
    if(m) m.hidden = false;
  });
}
function fecharModalSessoes(){
  const m = $('#modalSessoes');
  if(m) m.hidden = true;
}

function abrirModalNovaSessao(){
  fecharModalSessoes();
  const inp = $('#inputNovaSessaoNome');
  if(inp){
    const d = new Date();
    inp.value = '';
    inp.placeholder = `Ex: Pelada ${d.toLocaleDateString('pt-BR', {weekday:'short'})} - Câmera 1`;
  }
  const st = $('#statusCriarSessao');
  if(st) st.textContent = '';
  const btn = $('#btnConfirmarCriarSessao');
  if(btn) btn.disabled = false;
  const m = $('#modalNovaSessao');
  if(m) m.hidden = false;
}
function fecharModalNovaSessao(){
  const m = $('#modalNovaSessao');
  if(m) m.hidden = true;
}

async function confirmarCriarSessao(){
  const inp = $('#inputNovaSessaoNome');
  const chk = $('#chkReaproveitarTimes');
  const btn = $('#btnConfirmarCriarSessao');
  const st = $('#statusCriarSessao');

  const nome = (inp ? inp.value.trim() : '');
  const reaproveitar = (chk ? chk.checked : true);

  if(btn) btn.disabled = true;
  if(st) st.innerHTML = '<span class="spinner"></span> Salvando sessão atual e criando nova...';

  try {
    const res = await fetch('/api/sessoes/criar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nome: nome, reaproveitar_times: reaproveitar})
    });
    const dados = await res.json();
    if(!res.ok) throw new Error(dados.detail || 'Não foi possível criar a sessão.');

    ['futbin_partida_cache_v1', 'futbin_ultimo_passo'].forEach(k => { try { localStorage.removeItem(k); } catch(e){} });
    fecharModalNovaSessao();
    location.href = location.pathname + '?passo=s-video';
  } catch(err) {
    if(st) st.textContent = 'Erro: ' + err.message;
    if(btn) btn.disabled = false;
  }
}

async function alternarSessao(sessaoId){
  if(sessaoId === sessaoAtivaId) return;
  const msg = 'Deseja alternar para esta sessão de partida?\n\nA sessão atual será salva no histórico com todo o seu progresso e os dados da sessão selecionada serão carregados.';
  if(!confirm(msg)) return;

  const aviso = document.createElement('div');
  aviso.className = 'modal-overlay';
  aviso.innerHTML = '<div class="modal-box" style="max-width:380px; text-align:center;"><span class="spinner" style="width:24px; height:24px; margin-bottom:10px;"></span><h3>Alternando de sessão...</h3><p class="hint">Salvando arquivos da sessão atual e restaurando a selecionada.</p></div>';
  document.body.appendChild(aviso);

  try {
    const res = await fetch(`/api/sessoes/${sessaoId}/ativar`, {method: 'POST'});
    const dados = await res.json();
    if(!res.ok) throw new Error(dados.detail || 'Não foi possível alternar de sessão.');

    ['futbin_partida_cache_v1', 'futbin_ultimo_passo'].forEach(k => { try { localStorage.removeItem(k); } catch(e){} });
    location.href = location.pathname + '?passo=s-inicio';
  } catch(err) {
    alert('Erro ao alternar de sessão: ' + err.message);
    aviso.remove();
  }
}

async function promptRenomearSessao(sessaoId, nomeAtualEnc){
  const nomeAtual = decodeURIComponent(nomeAtualEnc || '');
  const novoNome = prompt('Digite o novo nome para a sessão:', nomeAtual);
  if(!novoNome || !novoNome.trim() || novoNome.trim() === nomeAtual) return;

  try {
    const res = await fetch(`/api/sessoes/${sessaoId}/renomear`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nome: novoNome.trim()})
    });
    const dados = await res.json();
    if(!res.ok) throw new Error(dados.detail || 'Falha ao renomear.');
    await carregarSessoes();
    if(passoAtual === 's-inicio') renderInicio();
  } catch(err) {
    alert('Erro ao renomear: ' + err.message);
  }
}

async function duplicarSessao(sessaoId){
  if(!confirm('Deseja criar uma cópia desta sessão?')) return;
  try {
    const res = await fetch(`/api/sessoes/${sessaoId}/duplicar`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const dados = await res.json();
    if(!res.ok) throw new Error(dados.detail || 'Falha ao duplicar.');
    await carregarSessoes();
    if(passoAtual === 's-inicio') renderInicio();
  } catch(err) {
    alert('Erro ao duplicar: ' + err.message);
  }
}

async function excluirSessao(sessaoId, nomeEnc){
  const nome = decodeURIComponent(nomeEnc || '');
  if(!confirm(`Tem certeza que deseja excluir permanentemente a sessão "${nome}"?\n\nTodos os clipes e gols salvos nesta sessão serão excluídos.`)) return;

  try {
    const res = await fetch(`/api/sessoes/${sessaoId}`, {method: 'DELETE'});
    const dados = await res.json();
    if(!res.ok) throw new Error(dados.detail || 'Falha ao excluir sessão.');
    await carregarSessoes();
    if(passoAtual === 's-inicio') renderInicio();
  } catch(err) {
    alert('Erro ao excluir: ' + err.message);
  }
}

/* ------------------------------------------------------------ inicio / novo corte */
function passoParaContinuar(){
  let salvo = null;
  try { salvo = localStorage.getItem('futbin_ultimo_passo'); } catch(e) {}
  return (salvo && salvo !== 's-inicio' && $(`#${salvo}`)) ? salvo : 's-video';
}
async function renderInicio(){
  const el = $('#inicioResumo'), btn = $('#btnInicioContinuar');
  const nomeEl = $('#inicioSessaoNome'), subEl = $('#inicioSessaoSub');
  try {
    await carregarSessoes();
    const e = await (await fetch('/api/estado')).json();
    const ativa = e.sessao_ativa || (sessoesCache.find(s => s.id === sessaoAtivaId)) || {};

    if(nomeEl) nomeEl.textContent = ativa.nome || 'Sessão Ativa';
    if(subEl){
      const v = ativa.video_nome || (ativa.video ? ativa.video.split(/[\\/]/).pop() : 'Nenhum vídeo escolhido ainda');
      subEl.innerHTML = `📹 <strong>${v}</strong> &bull; Criada em: ${ativa.criado_em ? ativa.criado_em.split('T')[0] : 'Hoje'}`;
    }

    const itens = [];
    if(e.placar_ok) itens.push('placar marcado');
    if(e.n_gols) itens.push(`${e.n_gols} gol(s) detectado(s)`);
    if(e.n_clipes) itens.push(`${e.n_clipes} clipe(s) cortado(s)`);
    if(e.partida_ok) itens.push('dados da partida');
    if(e.final_ok || e.final_gols_ok) itens.push('vídeo final gerado');
    if(el) el.innerHTML = itens.length ? 'Status da sessão ativa: <strong>' + itens.join(' · ') + '.</strong>' : 'Nenhum vídeo/corte iniciado nesta sessão ainda.';
    if(btn){
      btn.textContent = itens.length ? 'Continuar de onde parei →' : 'Começar → escolher o vídeo';
      btn.dataset.vazio = itens.length ? '' : '1';
    }
  } catch(err) {
    if(el) el.textContent = 'Não consegui verificar o estado atual.';
  }
}

const btnContinuarInicio = $('#btnInicioContinuar');
if(btnContinuarInicio){
  btnContinuarInicio.onclick = () => irPara(btnContinuarInicio.dataset.vazio ? 's-video' : passoParaContinuar());
}

const btnNovoInicio = $('#btnInicioNovo');
if(btnNovoInicio){
  btnNovoInicio.onclick = async () => {
    if(!confirm('Limpar dados da sessão atual?\n\nA sessão atual será arquivada no histórico e limpa.\nSe você quiser manter esta sessão intacta e cortar outro vídeo, recomendamos usar "+ Cortar Outro Vídeo (Nova Sessão)".\n\nDeseja continuar?')) return;
    const st = $('#inicioStatus');
    btnNovoInicio.disabled = true;
    if(st) st.textContent = 'Limpando dados da sessão atual...';
    try {
      const r = await fetch('/api/novo-corte', {method:'POST'});
      const d = await r.json().catch(() => ({}));
      if(!r.ok) throw new Error(d.detail || 'Não foi possível limpar.');
      ['futbin_partida_cache_v1','futbin_ultimo_passo'].forEach(k => { try { localStorage.removeItem(k); } catch(e) {} });
      location.href = location.pathname + '?passo=s-video';
    } catch(err) {
      if(st) st.textContent = err.message;
      btnNovoInicio.disabled = false;
    }
  };
}

function irPara(id){
  passoAtual = id;
  if(id!=='s-inicio'){ try { localStorage.setItem('futbin_ultimo_passo', id); } catch(e) {} }
  $$('section').forEach(s=>s.classList.toggle('on', s.id===id));
  atualizarNav();
  if(id==='s-revisar'){
    inicializarVideoCompleto();
  }
  if(id==='s-marcar'){
    renderMarcacao();
    sincronizarGolsComBackend().then(() => renderMarcacao());
    if(localStorage.getItem('futbin_modo_teatro_marcar') === '1'){
      alternarModoTeatroMarcar(true);
    }
  } else {
    const mainEl = document.querySelector('main');
    if(mainEl) mainEl.classList.remove('teatro-ativo');
  }
  if(id==='s-inicio') renderInicio();
  if(id==='s-placar' || id==='s-gols') renderCameraPlacar();
  if(id==='s-gols') renderOpcoesCamerasCorte();
  if(id==='s-revisar') renderCameraVer();
  if(id==='s-resumo') renderResumo();
  if(id==='s-final'){ renderResumo(); }   // renderResumo inicia o card de fundo e a previsão de duração
  if(id==='s-jogador'){ sincronizarCoresJogadorComFundo(); renderTelaJogador(); setTimeout(desenharRecorteVertical, 0); }
  if(typeof aplicarFiltroBrilho === 'function') aplicarFiltroBrilho();
}

/* ------------------------------------------------------------ autosave partida */
let salvarTimer = null;
function agendarSalvar(){
  clearTimeout(salvarTimer);
  salvarTimer = setTimeout(salvarPartida, 400);
}
const CACHE_PARTIDA_KEY = 'futbin_partida_cache_v1';
function guardarCachePartida(dados){
  try {
    localStorage.setItem(CACHE_PARTIDA_KEY, JSON.stringify({meta: dados.meta, times: dados.times, gols: dados.gols, lances: dados.lances, roteiro: dados.roteiro}));
  } catch(e) {}
}
function lerCachePartida(){
  try { const t = localStorage.getItem(CACHE_PARTIDA_KEY); return t ? JSON.parse(t) : null; } catch(e) { return null; }
}
async function salvarPartida(){
  try{
    const dadosPartida = estadoParaPartida();
    guardarCachePartida(dadosPartida);
    await fetch('/api/partida', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(dadosPartida)});
    $$('.stSalvo').forEach(el=> el.textContent = 'salvo ' + new Date().toLocaleTimeString('pt-BR'));
  }catch(e){ $$('.stSalvo').forEach(el=> el.textContent = 'não consegui salvar'); }
}
function estadoParaPartida(){
  const v = [...validos()].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a), tB = obterTempoSegundosClipe(b);
    return (tA !== -1 && tB !== -1) ? (tA - tB) : ((a.indice||0) - (b.indice||0));
  });
  const l = [...lances()].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a), tB = obterTempoSegundosClipe(b);
    return (tA !== -1 && tB !== -1) ? (tA - tB) : ((a.indice||0) - (b.indice||0));
  });
  const todosRoteiro = [...v, ...l].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a), tB = obterTempoSegundosClipe(b);
    return (tA !== -1 && tB !== -1) ? (tA - tB) : ((a.indice||0) - (b.indice||0));
  });

  return {
    meta: Object.assign({}, S.meta, {video: ESTADO.video ? ESTADO.video.caminho : null,
      cameras: camerasSelecionadas().map(c => c ? ({nome:c.nome, caminho:c.caminho, duracao_s:c.duracao_s, inicio_jogo_s:Number(c.inicio_jogo_s)||0, preset:c.preset||null}) : null),
      camera_placar: ESTADO.cameraPlacar,
      placar:[v.filter(g=>g.time===0).length, v.filter(g=>g.time===1).length]}),
    times: S.times.map((t, idx) => ({
      nome: t.nome,
      cor: t.cor,
      jogadores: t.jogadores || [],
      posicoes: escalacaoCompleta(idx),
      fotos: t.fotos || {},
      camera_ataque: t.camera_ataque || 0,
    })),
    gols: v.map(g=>({indice:g.indice, tempo:g.tempo,
      tempo_s: (g.tempo_s != null) ? g.tempo_s : obterTempoSegundosClipe(g),
      inicio_s:g.inicio_s, fim_s:g.fim_s, camera:g.camera || 1, cameras_clipe:g.cameras_clipe || [g.camera || 1], tipo:'gol', status:'gol', time:g.time,
      time_nome:S.times[g.time]?.nome || '', autor:g.autor, assist:g.assist, fonte:g.fonte||null,
      zoom:g.zoom ?? 1, zoom_x:g.zoom_x ?? 0.5, zoom_y:g.zoom_y ?? 0.5})),
    lances: l.map(g=>{
      const inf = obterInfoTipo(g.status || g.tipo, g.lance);
      return {
        indice: g.indice,
        tempo: g.tempo,
        tempo_s: (g.tempo_s != null) ? g.tempo_s : obterTempoSegundosClipe(g),
        inicio_s: g.inicio_s,
        fim_s: g.fim_s, camera:g.camera || 1, cameras_clipe:g.cameras_clipe || [g.camera || 1],
        tipo: 'lance',
        status: g.status || (inf ? inf.id : 'lance'),
        lance: g.lance || (inf ? inf.lanceNome : 'Lance'),
        time: g.time,
        destaque: g.destaque,
        fonte: g.fonte||null,
        zoom: g.zoom ?? 1, zoom_x: g.zoom_x ?? 0.5, zoom_y: g.zoom_y ?? 0.5
      };
    }),
    roteiro: todosRoteiro.map(g=>({i:g.indice, t:obterTempoSegundosClipe(g), tipo:g.tipo})),
    artilheiros: contar('autor').map(d=>({jogador:d[0],gols:d[1]})),
    garcons: contar('assist').map(d=>({jogador:d[0],assistencias:d[1]})),
    descartados: (ESTADO.gols||[]).filter(g=>g.descartado).map(g=>g.indice),
    _todosGols: ESTADO.gols,   // guarda o estado bruto (com nao marcados) pra retomar depois
  };
}
function validos(){ return (ESTADO.gols||[]).filter(g=>!g.descartado && g.tipo==='gol' && g.autor); }
function golsMarcados(){ return (ESTADO.gols||[]).filter(g=>!g.descartado && g.tipo==='gol'); }
function lances(){
  return (ESTADO.gols||[]).filter(g => {
    if(g.descartado) return false;
    const inf = obterInfoTipo(g.status || g.tipo, g.lance);
    return inf ? !inf.isGol : (g.tipo === 'lance');
  });
}
function contar(campo){
  const m={};
  validos().forEach(g=>{ const v=g[campo]; if(v) m[v]=(m[v]||0)+1; });
  return Object.entries(m).sort((a,b)=>b[1]-a[1]);
}

/* ------------------------------------------------------------ passo 1: video/partida */
let buscaDebounce = null;
async function buscarVideos(query = ''){
  const listaEl = $('#listaResultadosPesquisa');
  if(!listaEl) return;
  listaEl.innerHTML = '<span class="hint"><span class="spinner"></span>Buscando vídeos no computador...</span>';
  try {
    const url = '/api/videos/buscar' + (query ? ('?q=' + encodeURIComponent(query)) : '');
    const r = await fetch(url);
    const videos = await r.json();
    renderResultadosPesquisa(videos);
  } catch(e) {
    listaEl.innerHTML = '<span class="hint bad">Erro ao buscar vídeos.</span>';
  }
}

function renderResultadosPesquisa(videos){
  const listaEl = $('#listaResultadosPesquisa');
  if(!listaEl) return;
  listaEl.innerHTML = '';
  if(!videos || !videos.length){
    listaEl.innerHTML = '<span class="hint">Nenhum vídeo encontrado. Digite outro termo ou use o explorador de pastas abaixo.</span>';
    return;
  }
  videos.forEach(v => {
    const item = document.createElement('div');
    item.className = 'item-video';
    const durStr = v.duracao_s ? fmtTempo(v.duracao_s) : '';
    item.innerHTML = `
      <div style="flex:1; min-width:0; padding-right:10px">
        <b>🎬 ${v.nome}</b>
        <div class="sub" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis">${v.caminho}</div>
      </div>
      <div style="text-align:right; flex:0 0 auto">
        ${durStr ? `<span class="teamtag" style="background:var(--line); color:var(--txt)">${durStr}</span>` : ''}
        <button type="button" class="ghost" style="margin-left:8px; padding:4px 10px; font-size:12px">Selecionar</button>
      </div>
    `;
    item.onclick = () => selecionarVideo(v);
    listaEl.appendChild(item);
  });
}

function camerasSelecionadas(){
  return Array.isArray(ESTADO.cameras) ? ESTADO.cameras : [];
}

function tempoCamera(s){
  const ms = Math.round(Math.max(0, Number(s) || 0) * 1000);
  return fmtTempo(Math.floor(ms / 1000)) + '.' + String(ms % 1000).padStart(3, '0');
}

/* ------------------------------------------------------------------ presets de câmera */
const CAMERA_PRESETS = [
  { id: 'principal',  rotulo: 'Principal',       icon: '🎥', desc: 'Câmera principal do jogo',          cor: '#00ff87' },
  { id: 'lateral',    rotulo: 'Lateral',          icon: '📹', desc: 'Ângulo lateral do campo',           cor: '#00f0ff' },
  { id: 'gol',        rotulo: 'Câmera do Gol',    icon: '🥅', desc: 'Atrás do gol / área',              cor: '#fbbf24' },
  { id: 'drone',      rotulo: 'Drone / Topo',     icon: '🚁', desc: 'Vista aérea ou topo',              cor: '#a78bfa' },
  { id: 'celular',    rotulo: 'Celular',           icon: '📱', desc: 'Filmagem com celular na mão',      cor: '#fb7185' },
  { id: 'fixa',       rotulo: 'Câmera Fixa',      icon: '📌', desc: 'Tripé fixo sem operador',          cor: '#38bdf8' },
];

function renderCamerasSelecionadas(){
  const el = $('#listaCamerasSelecionadas');
  if(!el) return;
  const cameras = camerasSelecionadas();
  el.querySelectorAll("video").forEach(v => { v.pause(); v.removeAttribute("src"); v.load(); });
  el.innerHTML = '';

  [0,1,2].forEach(i => {
    const cam = cameras[i];
    const corLabel = i === 0 ? 'var(--accent)' : '#00f0ff';
    const box = document.createElement('div');
    box.style.cssText = `border:1px solid var(--line); border-radius:9px; padding:10px; background:var(--panel2); display:flex; flex-direction:column; gap:0; min-height:100px;`;

    /* ---- cabeçalho ---- */
    const header = document.createElement('div');
    header.style.cssText = 'display:flex; justify-content:space-between; align-items:center; gap:4px; margin-bottom:6px';
    const titulo = document.createElement('b');
    titulo.style.cssText = `font-size:12px; color:${corLabel}`;
    titulo.textContent = `📹 Câmera ${i+1}${i===0?' · principal':''}`;
    header.appendChild(titulo);
    if(cam){
      const btnRem = document.createElement('button');
      btnRem.type = 'button'; btnRem.className = 'ghost'; btnRem.dataset.removerCamera = i;
      btnRem.style.cssText = 'padding:1px 6px; font-size:11px';
      btnRem.textContent = '×'; btnRem.title = `Remover Câmera ${i+1}`;
      header.appendChild(btnRem);
    }
    box.appendChild(header);

    if(!cam){
      const vazio = document.createElement('div');
      vazio.className = 'hint';
      vazio.style.cssText = 'font-size:11px; margin-top:4px; flex:1';
      vazio.textContent = 'Nenhum vídeo escolhido';
      box.appendChild(vazio);
      el.appendChild(box);
      return;
    }

    /* ---- nome do arquivo ---- */
    const nomeEl = document.createElement('div');
    nomeEl.title = cam.nome;
    nomeEl.style.cssText = 'font-size:11px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--txt); margin-bottom:6px';
    nomeEl.textContent = cam.nome;
    box.appendChild(nomeEl);

    /* ---- PRESETS ---- */
    const presetSec = document.createElement('div');
    presetSec.style.cssText = 'margin-bottom:8px';
    const presetLabel = document.createElement('div');
    presetLabel.style.cssText = 'font-size:10px; color:var(--dim); font-weight:700; text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px';
    presetLabel.textContent = 'Tipo de câmera';
    presetSec.appendChild(presetLabel);

    const presetGrid = document.createElement('div');
    presetGrid.style.cssText = 'display:grid; grid-template-columns:repeat(3,1fr); gap:4px';
    CAMERA_PRESETS.forEach(p => {
      const btn = document.createElement('button');
      btn.type = 'button';
      const ativo = (cam.preset || (i===0?'principal':'lateral')) === p.id;
      btn.style.cssText = `padding:4px 3px; border-radius:6px; font-size:10px; font-weight:700; cursor:pointer; border:1.5px solid ${ativo ? p.cor : 'var(--line)'}; background:${ativo ? `${p.cor}22` : 'var(--panel)'}; color:${ativo ? p.cor : 'var(--dim)'}; display:flex; flex-direction:column; align-items:center; gap:1px; transition:all .15s; white-space:nowrap; overflow:hidden`;
      btn.title = p.desc;
      btn.innerHTML = `<span style="font-size:14px">${p.icon}</span><span>${p.rotulo}</span>`;
      btn.onclick = () => {
        cam.preset = p.id;
        agendarSalvar();
        /* atualiza visual sem rerenderizar tudo */
        presetGrid.querySelectorAll('button').forEach((b, bi) => {
          const pp = CAMERA_PRESETS[bi];
          const isNow = pp.id === p.id;
          b.style.border = `1.5px solid ${isNow ? pp.cor : 'var(--line)'}`;
          b.style.background = isNow ? `${pp.cor}22` : 'var(--panel)';
          b.style.color = isNow ? pp.cor : 'var(--dim)';
        });
      };
      presetGrid.appendChild(btn);
    });
    presetSec.appendChild(presetGrid);
    box.appendChild(presetSec);

    /* ---- tempo de início ---- */
    const inicioLabel = document.createElement('label');
    inicioLabel.style.cssText = 'font-size:10px; color:var(--dim); margin:0 0 6px; display:flex; align-items:center; gap:6px; flex-wrap:wrap';
    inicioLabel.innerHTML = `Jogo começa em`;
    const input = document.createElement('input');
    input.type = 'text'; input.dataset.inicioCamera = i;
    input.value = tempoCamera(cam.inicio_jogo_s || 0);
    input.style.cssText = 'width:105px; padding:3px 6px; font-size:11px';
    input.setAttribute('aria-label', `Início do jogo na câmera ${i+1}`);
    inicioLabel.appendChild(input);
    box.appendChild(inicioLabel);

    /* ---- preview / seek ---- */
    const preview = document.createElement('div');
    preview.innerHTML = `
      <video controls muted playsinline preload="metadata" aria-label="Preview da câmera ${i+1}" style="display:block; width:100%; aspect-ratio:16/9; background:#000; border-radius:6px; margin-bottom:6px"></video>
      <img data-quadro-camera alt="Quadro da câmera ${i+1}" style="display:none; width:100%; border-radius:6px; margin-bottom:6px">
      <div style="display:flex; gap:4px; flex-wrap:wrap; margin-bottom:5px">
        <button type="button" class="ghost" data-passo="-5" style="font-size:11px; padding:3px 7px">−5 s</button>
        <button type="button" class="ghost" data-passo="-0.1" style="font-size:11px; padding:3px 7px">−0,1 s</button>
        <button type="button" class="ghost" data-passo="0.1" style="font-size:11px; padding:3px 7px">+0,1 s</button>
        <button type="button" class="ghost" data-passo="5" style="font-size:11px; padding:3px 7px">+5 s</button>
      </div>
      <div style="display:flex; gap:4px; align-items:center; margin-bottom:5px">
        <input data-busca-camera type="text" placeholder="mm:ss.mmm" aria-label="Tempo do preview da câmera ${i+1}" style="flex:1; min-width:0; font-size:11px">
        <button type="button" class="ghost" data-ir-camera style="font-size:11px; padding:3px 8px; white-space:nowrap">Ir</button>
        <button type="button" class="ghost" data-ver-quadro style="font-size:11px; padding:3px 8px; white-space:nowrap">📷</button>
      </div>
      <div class="hint" data-status-camera style="font-size:10px; margin-bottom:5px" aria-live="polite">Carregando preview…</div>
      <button type="button" class="act" data-marcar-camera style="width:100%; font-size:11px; padding:5px">✓ Usar este momento como início</button>
      <p class="hint" style="font-size:10px; margin-top:5px; margin-bottom:0">Encontre o mesmo início em cada câmera e marque para alinhar os cortes.</p>`;
    box.appendChild(preview);

    const video = preview.querySelector('video');
    const status = preview.querySelector('[data-status-camera]');
    const busca = preview.querySelector('[data-busca-camera]');
    let posicao = Number(cam.inicio_jogo_s) || 0;
    let modoQuadro = false, pedidoQuadro = 0, quadroUrl = null;
    const quadro = preview.querySelector('[data-quadro-camera]');
    const duracao = () => Number.isFinite(video.duration) ? video.duration : Number(cam.duracao_s) || 0;
    const mostrarPosicao = () => status.textContent = `Posição: ${tempoCamera(posicao)} / ${tempoCamera(duracao())}`;
    const carregarQuadro = async () => {
      const pedido = ++pedidoQuadro;
      status.textContent = 'Carregando quadro…';
      try {
        const r = await fetch('/api/frame', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({video:cam.caminho || cam.nome, tempo_s:posicao})});
        if(!r.ok) throw new Error('frame');
        const blob = await r.blob();
        if(pedido !== pedidoQuadro || !preview.isConnected) return;
        if(quadroUrl) URL.revokeObjectURL(quadroUrl);
        quadroUrl = URL.createObjectURL(blob);
        quadro.src = quadroUrl;
        quadro.onload = () => { URL.revokeObjectURL(quadroUrl); quadroUrl = null; };
        quadro.style.display = 'block';
        mostrarPosicao();
      } catch(e){ if(pedido === pedidoQuadro) status.textContent = 'Não foi possível carregar o quadro. Tente outro tempo.'; }
    };
    const seek = t => {
      if(!Number.isFinite(t) || t < 0) return false;
      video.pause();
      posicao = duracao() ? Math.min(t, Math.max(0, duracao() - 0.05)) : t;
      busca.value = tempoCamera(posicao);
      if(video.readyState >= 1) video.currentTime = posicao;
      if(modoQuadro) carregarQuadro(); else mostrarPosicao();
      return true;
    };
    box.buscarTempoCamera = seek;
    busca.value = tempoCamera(posicao);
    preview.querySelector('[data-ver-quadro]').onclick = () => {
      video.pause(); modoQuadro = true;
      const t = parseTempo(busca.value.replace(',', '.'));
      if(!seek(t)) seek(posicao);
    };
    video.onplay = () => { modoQuadro = false; quadro.style.display = 'none'; };
    video.onloadedmetadata = () => {
      seek(posicao);
      busca.value = tempoCamera(video.currentTime);
      status.textContent = `Posição: ${tempoCamera(video.currentTime)} / ${tempoCamera(video.duration)}`;
    };
    video.ontimeupdate = () => { if(!modoQuadro){ posicao = video.currentTime; mostrarPosicao(); } };
    video.onerror = () => { status.textContent = 'Use 📷 para visualizar e alinhar este vídeo.'; };
    preview.querySelectorAll('[data-passo]').forEach(b => b.onclick = () => seek(Math.max(0, posicao + Number(b.dataset.passo))));
    const ir = () => {
      const t = parseTempo(busca.value.replace(',', '.'));
      busca.setCustomValidity(seek(t) ? '' : 'Informe um tempo válido, como 01:23.500.');
      busca.reportValidity();
    };
    busca.oninput = () => busca.setCustomValidity('');
    preview.querySelector('[data-ir-camera]').onclick = ir;
    busca.onkeydown = e => { if(e.key === 'Enter'){ e.preventDefault(); ir(); } };
    preview.querySelector('[data-marcar-camera]').onclick = () => {
      video.pause();
      cam.inicio_jogo_s = Math.round(posicao * 1000) / 1000;
      input.value = tempoCamera(cam.inicio_jogo_s);
      input.setCustomValidity('');
      agendarSalvar();
    };
    video.src = '/video/completo?video=' + encodeURIComponent(cam.caminho || cam.nome);

    el.appendChild(box);
  });

  el.querySelectorAll('[data-remover-camera]').forEach(b => b.onclick = () => {
    const i = Number(b.dataset.removerCamera); camerasSelecionadas()[i] = null;
    if(i === 0) ESTADO.video = null;
    renderCamerasSelecionadas(); $('#btnIrPlacar').disabled = !ESTADO.video; agendarSalvar();
  });
  el.querySelectorAll('[data-inicio-camera]').forEach(inp => inp.onchange = () => {
    const i = Number(inp.dataset.inicioCamera);
    const t = parseTempo(inp.value.replace(',', '.'));
    if(!Number.isFinite(t) || t < 0){
      inp.setCustomValidity('Informe um tempo válido, como 01:23.500.'); inp.reportValidity(); return;
    }
    inp.setCustomValidity('');
    if(camerasSelecionadas()[i]) camerasSelecionadas()[i].inicio_jogo_s = t;
    inp.value = tempoCamera(t);
    inp.closest('div').buscarTempoCamera?.(t);
    agendarSalvar();
  });
}

const btnSincronizar = $('#btnSincronizarCameras');
let sincronizacaoAtiva = null, sincronizacaoAnterior = null;
const identidadeCameras = () => JSON.stringify(camerasSelecionadas().map(c => c ? [c.caminho,c.inicio_jogo_s] : null));
btnSincronizar.onclick = async () => {
  const status = $('#statusSincronizarCameras');
  const cameras = camerasSelecionadas().map((c,indice) => c ? {indice, video:c.caminho || c.nome} : null).filter(Boolean);
  if(cameras.length < 2 || !cameras.some(c => c.indice === 0)){
    status.textContent = 'Selecione a câmera principal e pelo menos mais uma câmera.'; return;
  }
  const identidade = identidadeCameras();
  btnSincronizar.disabled = true;
  $('#btnDesfazerSincronizacao').hidden = true;
  $('#btnCancelarSincronizacao').hidden = false;
  status.textContent = 'Localizando o relógio nas câmeras…';
  try {
    const r = await fetch('/api/cameras/sincronizar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cameras})});
    const data = await r.json();
    if(!r.ok) throw new Error(data.detail || 'Não foi possível iniciar a sincronização.');
    sincronizacaoAtiva = data.id;
    for(;;){
      await new Promise(resolve => setTimeout(resolve,1000));
      const res = await fetch('/api/cameras/sincronizar/' + data.id);
      const job = await res.json();
      if(!res.ok) throw new Error(job.detail || 'Falha ao consultar a sincronização.');
      status.textContent = job.mensagem;
      if(job.status === 'erro' || job.status === 'cancelado') break;
      if(job.status !== 'concluido') continue;
      if(identidadeCameras() !== identidade){status.textContent = 'As câmeras ou tempos foram alterados durante a análise. Execute Sincronizar novamente.';break;}
      sincronizacaoAnterior = camerasSelecionadas().map(c => c ? {caminho:c.caminho,inicio:c.inicio_jogo_s || 0} : null);
      for(const c of job.resultado.cameras) camerasSelecionadas()[c.indice].inicio_jogo_s = c.inicio_jogo_s;
      ESTADO.video = camerasSelecionadas()[0];
      renderCamerasSelecionadas(); agendarSalvar();
      status.textContent = 'Câmeras alinhadas pelo relógio. ' + job.resultado.cameras.map(c => `Câmera ${c.indice+1}: ${tempoCamera(c.inicio_jogo_s)}`).join(' · ') + '. Precisão aproximada de 1 segundo. Confira os previews antes de cortar.';
      $('#btnDesfazerSincronizacao').hidden = false;
      break;
    }
  } catch(e){status.textContent = e.message;}
  finally {sincronizacaoAtiva = null;btnSincronizar.disabled = false;$('#btnCancelarSincronizacao').hidden = true;}
};
$('#btnCancelarSincronizacao').onclick = async () => {
  if(sincronizacaoAtiva) await fetch('/api/cameras/sincronizar/' + sincronizacaoAtiva + '/cancelar',{method:'POST'});
};
$('#btnDesfazerSincronizacao').onclick = () => {
  if(!sincronizacaoAnterior) return;
  camerasSelecionadas().forEach((c,i) => {const anterior=sincronizacaoAnterior[i];if(c && anterior && c.caminho===anterior.caminho)c.inicio_jogo_s=anterior.inicio;});
  renderCamerasSelecionadas();agendarSalvar();
  $('#statusSincronizarCameras').textContent = 'Tempos anteriores restaurados.';
  $('#btnDesfazerSincronizacao').hidden = true;
  sincronizacaoAnterior = null;
};

function selecionarVideo(v, cameraAlvo=null){
  const alvo = cameraAlvo === null ? Number($('#selCameraAlvo')?.value || 0) : cameraAlvo;
  if(!Array.isArray(ESTADO.cameras)) ESTADO.cameras = [null, null, null];
  ESTADO.cameras[alvo] = {...v, inicio_jogo_s: Number(ESTADO.cameras[alvo]?.inicio_jogo_s) || 0};
  if(alvo === 0) ESTADO.video = ESTADO.cameras[0];
  renderCamerasSelecionadas();
  if(alvo !== 0){
    $('#selCameraAlvo').value = String(Math.min(2, alvo + 1));
    agendarSalvar();
    return;
  }
  const card = $('#videoSelecionadoCard');
  if(card){
    const durStr = v.duracao_s ? ` · ${fmtTempo(v.duracao_s)}` : '';
    card.style.display = 'flex';
    card.className = 'video-card-selecionado';
    card.innerHTML = `
      <div style="flex:1; min-width:0">
        <div style="font-size:11px; text-transform:uppercase; font-weight:700; color:var(--accent)">✓ Vídeo selecionado</div>
        <div style="font-size:15px; font-weight:700; color:var(--txt); margin-top:2px; word-break:break-all">🎬 ${v.nome}${durStr}</div>
        <div class="hint" style="margin-top:2px; word-break:break-all">${v.caminho}</div>
      </div>
      <div style="flex:0 0 auto">
        <button type="button" class="ghost" id="btnTrocarVideo" style="font-size:12px">Trocar vídeo</button>
      </div>
    `;
    const btnTr = $('#btnTrocarVideo');
    if(btnTr) {
      btnTr.onclick = () => {
        $('#campoPesquisaVideo').focus();
        $('#campoPesquisaVideo').select();
      };
    }
  }
  $('#btnIrPlacar').disabled = false;
  if(v.duracao_s && !$('#tempoFrame').value) $('#tempoFrame').value = fmtTempo(v.duracao_s * 0.4);

  inicializarVideoCompleto();
  agendarSalvar();
}

$('#campoPesquisaVideo').addEventListener('input', e => {
  clearTimeout(buscaDebounce);
  const q = e.target.value.trim();
  buscaDebounce = setTimeout(() => buscarVideos(q), 250);
});

$('#btnToggleExplorador').onclick = () => {
  const el = $('#wrapExploradorManual');
  const aberto = el.style.display !== 'none';
  el.style.display = aberto ? 'none' : 'block';
  $('#btnToggleExplorador').textContent = aberto ? '📁 Explorar pastas manualmente' : '📁 Fechar explorador manual';
  if(!aberto && (!pastaExplorador || !pastaExplorador.pastas.length)){
    explorar();
  }
};

let pastaExplorador = null;
async function explorar(caminho){
  const url = '/api/explorar' + (caminho ? ('?caminho='+encodeURIComponent(caminho)) : '');
  const r = await fetch(url);
  pastaExplorador = await r.json();
  $('#pastaAtual').textContent = pastaExplorador.atual + (pastaExplorador.erro ? ' — '+pastaExplorador.erro : '');
  $('#btnSubirPasta').disabled = !pastaExplorador.pai;
  const sel = $('#selExplorador'); sel.innerHTML = '';
  pastaExplorador.pastas.forEach(p=>{
    const o = document.createElement('option'); o.value = 'dir:'+p.caminho; o.textContent = '📁 '+p.nome;
    sel.appendChild(o);
  });
  pastaExplorador.videos.forEach(v=>{
    const o = document.createElement('option'); o.value = 'video:'+v.caminho;
    const dur = v.duracao_s ? ` (${fmtTempo(v.duracao_s)})` : '';
    o.textContent = '🎬 '+v.nome+dur; sel.appendChild(o);
  });
  if(!pastaExplorador.pastas.length && !pastaExplorador.videos.length){
    const o = document.createElement('option'); o.disabled = true; o.textContent = '(pasta vazia)';
    sel.appendChild(o);
  }
}
$('#selExplorador').addEventListener('change', e=>{
  const v = e.target.value;
  if(v.startsWith('dir:')) explorar(v.slice(4));
  else if(v.startsWith('video:')){
    const caminho = v.slice(6);
    const info = pastaExplorador.videos.find(x=>x.caminho===caminho);
    selecionarVideo(info || {nome: caminho.split(/[\\/]/).pop(), caminho, duracao_s: null});
  }
});
$('#btnSubirPasta').onclick = ()=>{ if(pastaExplorador && pastaExplorador.pai) explorar(pastaExplorador.pai); };

const btnBaixarYt = $('#btnBaixarYoutube');
if(btnBaixarYt){
  btnBaixarYt.onclick = async () => {
    const url = ($('#campoUrlYoutube').value || '').trim();
    if(!url){
      alert('Cole o link do vídeo do YouTube no campo correspondente.');
      $('#campoUrlYoutube').focus();
      return;
    }
    const btn = $('#btnBaixarYoutube');
    const btnCanc = $('#btnCancelarYoutube');
    const logEl = $('#logYoutube');
    btn.disabled = true;
    btnCanc.style.display = 'inline-block';
    logEl.style.display = 'block';
    logEl.textContent = 'Iniciando download do YouTube...';

    try {
      const r = await fetch('/api/video/youtube', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url})
      });
      const data = await r.json();
      if(!r.ok){
        alert('Erro ao iniciar download: ' + (data.detail || 'falha no servidor'));
        return;
      }
      const ok = await acompanharJob(data.job_id, logEl, btnCanc);
      if(ok){
        const res = await fetch(`/api/video/youtube/resultado/${data.job_id}`);
        if(res.ok){
          const videoInfo = await res.json();
          selecionarVideo(videoInfo);
          logEl.textContent += `\n✓ Vídeo baixado com sucesso e selecionado: ${videoInfo.nome}!`;
        } else {
          await buscarVideos();
        }
      }
    } catch(e) {
      alert('Erro ao baixar vídeo do YouTube: ' + e);
    } finally {
      btn.disabled = false;
      btnCanc.style.display = 'none';
    }
  };
}
const btnCancYt = $('#btnCancelarYoutube');
if(btnCancYt){
  btnCancYt.onclick = cancelarJobAtivo;
}

/* ------------------------------------------------------------ passo 5: dados da partida */
function lerSetup(){
  const placarA = parseInt($('#placarJogoA').value, 10);
  const placarB = parseInt($('#placarJogoB').value, 10);
  S.meta = {
    ...(S.meta || {}),   // mantém fundo_config, roteiro_final etc.: só os campos desta tela são reescritos
    data: $('#mData').value,
    comp: $('#mComp').value,
    local: $('#mLocal').value,
    pelada: $('#mPelada').value,
    placar_jogo: [isNaN(placarA) ? null : placarA, isNaN(placarB) ? null : placarB],
  };
  const lista = t => t.split('\n').map(x=>x.trim()).filter(Boolean);
  const jA = lista($('#pA').value);
  const jB = lista($('#pB').value);
  const filtrarPorElenco = (mapa, elenco) => {
    const nomesNorm = new Set(elenco.map(n => n.trim().toLowerCase()));
    const out = {};
    for(const [k, v] of Object.entries(mapa || {})){
      if(nomesNorm.has(k.trim().toLowerCase())) out[k] = v;
    }
    return out;
  };
  const posA = filtrarPorElenco(S.times[0]?.posicoes, jA);
  const posB = filtrarPorElenco(S.times[1]?.posicoes, jB);
  const fotosA = filtrarPorElenco(S.times[0]?.fotos, jA);
  const fotosB = filtrarPorElenco(S.times[1]?.fotos, jB);

  // Sincroniza fotos e posições de jogadores cadastrados
  sincronizarJogadoresCadastrados(0, jA, posA, fotosA);
  sincronizarJogadoresCadastrados(1, jB, posB, fotosB);

  S.times[0] = {nome:$('#tA').value.trim()||'Time Amarelo', cor:$('#cA').value||'#eab308', jogadores:jA, posicoes:posA, fotos:fotosA, camera_ataque:parseInt($('#camAtaqueA').value,10)||0};
  S.times[1] = {nome:$('#tB').value.trim()||'Time Azul', cor:$('#cB').value||'#2563eb', jogadores:jB, posicoes:posB, fotos:fotosB, camera_ataque:parseInt($('#camAtaqueB').value,10)||0};
  atualizarEstilosTimes();
  renderPosicoesElenco(0);
  renderPosicoesElenco(1);
}

function sincronizarJogadoresCadastrados(timeIdx, jogadores, posicoes, fotos){
  // Para cada jogador no elenco, verifica se há correspondente no cadastro
  jogadores.forEach(nomeElenco => {
    const jogadorCadastrado = jogadoresCadastrados.find(j =>
      (j.apelido && j.apelido === nomeElenco) || j.nome === nomeElenco
    );

    if(jogadorCadastrado){
      // Aplica posição se ainda não definida
      if(!posicoes[nomeElenco] && jogadorCadastrado.posicao){
        const mapaPosicao = {
          'GOL': 'goleiro', 'GOLEIRO': 'goleiro',
          'ZAG': 'zagueiro', 'ZAGUEIRO': 'zagueiro',
          'MEI': 'meio', 'MEIO': 'meio', 'MEIA': 'meio',
          'ATA': 'atacante', 'ATACANTE': 'atacante'
        };
        const posNormalizada = jogadorCadastrado.posicao.toUpperCase().trim();
        const posId = mapaPosicao[posNormalizada] || 'meio';
        posicoes[nomeElenco] = posId;
      }

      // Aplica foto se ainda não definida
      if(!fotos[nomeElenco] && jogadorCadastrado.foto){
        fotos[nomeElenco] = jogadorCadastrado.foto;
      }
    }
  });
}
function atualizarEstilosTimes(){
  const corA = S.times[0]?.cor || '#eab308';
  const corB = S.times[1]?.cor || '#2563eb';
  const txtA = corTextoParaFundo(corA);
  const txtB = corTextoParaFundo(corB);

  const tagA = $('#previewTagA');
  if(tagA){
    tagA.textContent = S.times[0]?.nome || 'Time Amarelo';
    tagA.style.background = corA;
    tagA.style.color = txtA;
  }
  const tagB = $('#previewTagB');
  if(tagB){
    tagB.textContent = S.times[1]?.nome || 'Time Azul';
    tagB.style.background = corB;
    tagB.style.color = txtB;
  }
  atualizarLabelsPlacar();
}
function atualizarLabelsPlacar(){
  const lA = $('#lblPlacarA'), lB = $('#lblPlacarB');
  if(lA && S.times[0]) {
    lA.textContent = S.times[0].nome || 'Time Amarelo';
    lA.style.color = S.times[0].cor || '#eab308';
  }
  if(lB && S.times[1]) {
    lB.textContent = S.times[1].nome || 'Time Azul';
    lB.style.color = S.times[1].cor || '#2563eb';
  }
}
function inverterCoresDosTimes(){
  const corA = S.times[0]?.cor || '#eab308';
  const corB = S.times[1]?.cor || '#2563eb';
  S.times[0].cor = corB;
  S.times[1].cor = corA;
  const cA = $('#cA'), cB = $('#cB');
  if(cA) cA.value = corB;
  if(cB) cB.value = corA;
  atualizarEstilosTimes();
  agendarSalvar();
  if(passoAtual === 's-marcar') renderMarcacao();
  else if(passoAtual === 's-resumo') renderResumo();
}
function definirCorTime(timeIdx, corHex){
  if(!S.times[timeIdx]) return;
  S.times[timeIdx].cor = corHex;
  if(timeIdx === 0 && $('#cA')) $('#cA').value = corHex;
  if(timeIdx === 1 && $('#cB')) $('#cB').value = corHex;
  atualizarEstilosTimes();
  agendarSalvar();
  if(passoAtual === 's-marcar') renderMarcacao();
  else if(passoAtual === 's-resumo') renderResumo();
}
function escreverSetup(){
  $('#mData').value=S.meta.data||''; $('#mComp').value=S.meta.comp||'';
  $('#mLocal').value=S.meta.local||''; $('#mPelada').value=S.meta.pelada||'Will Cup';
  if(S.meta.placar_jogo && Array.isArray(S.meta.placar_jogo)){
    $('#placarJogoA').value = S.meta.placar_jogo[0] != null ? S.meta.placar_jogo[0] : '';
    $('#placarJogoB').value = S.meta.placar_jogo[1] != null ? S.meta.placar_jogo[1] : '';
  }
  $('#tA').value=S.times[0].nome||'Time Amarelo'; $('#cA').value=S.times[0].cor||'#eab308';
  $('#pA').value=(S.times[0].jogadores || []).join('\n');
  $('#tB').value=S.times[1].nome||'Time Azul'; $('#cB').value=S.times[1].cor||'#2563eb';
  $('#pB').value=(S.times[1].jogadores || []).join('\n');
  $('#camAtaqueA').value = String(S.times[0].camera_ataque || 0);
  $('#camAtaqueB').value = String(S.times[1].camera_ataque || 0);
  if(!S.times[0].posicoes) S.times[0].posicoes = {};
  if(!S.times[1].posicoes) S.times[1].posicoes = {};
  if(!S.times[0].fotos) S.times[0].fotos = {};
  if(!S.times[1].fotos) S.times[1].fotos = {};
  if(S.meta && S.meta.logo){
    const logoEl = $('#previewLogoCampeonato');
    if(logoEl) logoEl.src = S.meta.logo + '?t=' + Date.now();
  }
  atualizarEstilosTimes();
  renderPosicoesElenco(0);
  renderPosicoesElenco(1);
}
$$('#s-dados input,#s-dados textarea,#s-dados select').forEach(el=>{
  el.addEventListener('input', ()=>{ lerSetup(); agendarSalvar(); });
  el.addEventListener('change', ()=>{ lerSetup(); agendarSalvar(); });
});
const btnInv = $('#btnInverterCores');
if(btnInv) btnInv.onclick = inverterCoresDosTimes;
const btnInv6 = $('#btnInverterCoresStep6');
if(btnInv6) btnInv6.onclick = inverterCoresDosTimes;
const btnInv6L = $('#btnInverterCoresStep6Lance');
if(btnInv6L) btnInv6L.onclick = inverterCoresDosTimes;
const btnAutoPos = $('#btnAutoPosicoes');
if(btnAutoPos) btnAutoPos.onclick = autoDefinirPosicoes;
const btnCancM = $('#btnCancelarMontar');
if(btnCancM) btnCancM.onclick = cancelarJobAtivo;
$('#btnElenco').onclick = ()=>{
  const t = prompt('Cole a lista de jogadores (um por linha ou separados por vírgula):');
  if(!t) return;
  const nomes = t.split(/[\n,;]+/).map(x=>x.replace(/[⚽🎯🛡️🧤]/g,'').trim()).filter(Boolean);
  const meio = Math.ceil(nomes.length/2);
  $('#pA').value = nomes.slice(0,meio).join('\n');
  $('#pB').value = nomes.slice(meio).join('\n');
  lerSetup(); agendarSalvar();
  alert(nomes.length+' jogadores divididos. Ajuste a divisão entre os times.');
};

// Upload de Logo do Campeonato
const btnUpLogo = $('#btnUploadLogo');
const fileLogo = $('#fileLogoTorneio');
if(btnUpLogo && fileLogo){
  btnUpLogo.onclick = () => {
    fileLogo.value = '';
    fileLogo.click();
  };
  fileLogo.onchange = () => {
    const file = fileLogo.files && fileLogo.files[0];
    if(!file) return;
    const reader = new FileReader();
    reader.onload = async (e) => {
      const b64 = e.target.result;
      try {
        btnUpLogo.disabled = true;
        btnUpLogo.textContent = 'Enviando...';
        const res = await fetch('/api/upload_logo', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ imagem_b64: b64 })
        });
        const d = await res.json();
        if(res.ok && d.ok){
          const bust = '?t=' + Date.now();
          const novaUrl = d.url + bust;
          const prev = $('#previewLogoCampeonato');
          if(prev) prev.src = novaUrl;
          $$('img.fut-logo').forEach(img => { img.src = novaUrl; });
          const imgStep7 = $('#previewLogoStep7');
          if(imgStep7) imgStep7.src = novaUrl;
          if(!S.meta) S.meta = {};
          S.meta.logo = d.url;
          agendarSalvar();
          alert('Logo do campeonato atualizada com sucesso!');
        } else {
          alert('Erro ao salvar logo: ' + (d.detail || 'desconhecido'));
        }
      } catch(err){
        alert('Erro ao enviar logo: ' + err.message);
      } finally {
        btnUpLogo.disabled = false;
        btnUpLogo.innerHTML = '📁 Subir Logo';
      }
    };
    reader.readAsDataURL(file);
  };
}

// Upload de Foto de Jogador
const fileFoto = $('#fileFotoJogador');
if(fileFoto){
  fileFoto.onchange = () => {
    const file = fileFoto.files && fileFoto.files[0];
    if(!file || !_uploadJogadorAlvo) return;
    const reader = new FileReader();
    reader.onload = async (e) => {
      const b64 = e.target.result;
      const { timeIdx, nome } = _uploadJogadorAlvo;
      try {
        const res = await fetch('/api/upload_foto_jogador', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            jogador: nome,
            time_idx: timeIdx,
            imagem_b64: b64
          })
        });
        const d = await res.json();
        if(res.ok && d.ok){
          if(!S.times[timeIdx].fotos) S.times[timeIdx].fotos = {};
          S.times[timeIdx].fotos[nome] = d.url;
          renderPosicoesElenco(timeIdx);
          agendarSalvar();
        } else {
          alert('Erro ao subir foto: ' + (d.detail || 'desconhecido'));
        }
      } catch(err){
        alert('Erro de rede ao subir foto: ' + err.message);
      }
    };
    reader.readAsDataURL(file);
  };
}
$('#btnIrPlacar').onclick = ()=>{
  if(!ESTADO.video){ alert('Escolha um vídeo primeiro.'); return; }
  salvarPartida();
  irPara('s-placar');
};
$('#btnIrDados').onclick = ()=>irPara('s-dados');
$('#btnIrMarcar').onclick = async ()=>{
  lerSetup();
  await sincronizarGolsComBackend();
  await salvarPartida();
  irPara('s-marcar');
};
$('#btnIrResumo').onclick = ()=>{ salvarPartida(); irPara('s-resumo'); };

/* ------------------------------------------------------------ ajuste de brilho e contraste */
let filtroBrilho = { brilho: 100, contraste: 100, saturacao: 100 };

function aplicarFiltroBrilho(b = filtroBrilho.brilho, c = filtroBrilho.contraste, s = filtroBrilho.saturacao){
  filtroBrilho.brilho = b;
  filtroBrilho.contraste = c;
  filtroBrilho.saturacao = s;
  const valFiltro = (b === 100 && c === 100 && s === 100) ? 'none' : `brightness(${b}%) contrast(${c}%) saturate(${s}%)`;

  const elementos = [
    $('#frameImg'),
    $('#videoCompleto'),
    $('#modalVideo'),
    $('#vid'),
    ...$$('#previewPlacar img')
  ];
  elementos.forEach(el => {
    if(el) el.style.filter = valFiltro;
  });

  $$('.slider-brilho-sync').forEach(el => { el.value = b; });
  $$('.slider-contraste-sync').forEach(el => { el.value = c; });
  $$('.slider-saturacao-sync').forEach(el => { el.value = s; });
  $$('.txt-brilho-sync').forEach(el => { el.textContent = `${b}%`; });
  $$('.txt-contraste-sync').forEach(el => { el.textContent = `${c}%`; });
  $$('.txt-saturacao-sync').forEach(el => { el.textContent = `${s}%`; });
}

document.addEventListener('input', e => {
  if(e.target.classList.contains('slider-brilho-sync')){
    aplicarFiltroBrilho(parseInt(e.target.value, 10), filtroBrilho.contraste, filtroBrilho.saturacao);
  } else if(e.target.classList.contains('slider-contraste-sync')){
    aplicarFiltroBrilho(filtroBrilho.brilho, parseInt(e.target.value, 10), filtroBrilho.saturacao);
  } else if(e.target.classList.contains('slider-saturacao-sync')){
    aplicarFiltroBrilho(filtroBrilho.brilho, filtroBrilho.contraste, parseInt(e.target.value, 10));
  }
});
document.addEventListener('click', e => {
  if(e.target.classList.contains('btn-brilho-diminuir')){
    aplicarFiltroBrilho(45, 150, filtroBrilho.saturacao);
  } else if(e.target.classList.contains('btn-brilho-reset')){
    aplicarFiltroBrilho(100, 100, 100);
  }
});

/* ------------------------------------------------------------ passo 2: placar + zonas-gatilho */
/* ------------------------------------------------------------ camera do placar */
ESTADO.cameraPlacar = 0;   // índice (0..2) da câmera onde o placar é localizado e a análise roda
function videoPlacar(){
  return camerasSelecionadas()[ESTADO.cameraPlacar] || ESTADO.video;
}
function offsetPlacarS(){
  // Eventos achados na câmera do placar passam para a linha do tempo da câmera 1.
  const ref = camerasSelecionadas()[0], cam = camerasSelecionadas()[ESTADO.cameraPlacar];
  if(!ref || !cam || ESTADO.cameraPlacar === 0) return 0;
  return (Number(ref.inicio_jogo_s) || 0) - (Number(cam.inicio_jogo_s) || 0);
}
function renderCameraPlacar(){
  const pick = $('#pickCameraPlacar'); if(!pick) return;
  if(!camerasSelecionadas()[ESTADO.cameraPlacar]) ESTADO.cameraPlacar = 0;
  pick.innerHTML = '';
  [0,1,2].forEach(i => {
    const ok = Boolean(camerasSelecionadas()[i]);
    const b = document.createElement('button');
    b.type = 'button'; b.className = i === ESTADO.cameraPlacar ? 'act' : 'ghost';
    b.style.cssText = 'font-size:12px; padding:4px 10px';
    b.disabled = !ok;
    b.textContent = `Câmera ${i+1}${i === 0 ? ' · principal' : ''}`;
    if(!ok) b.title = 'Câmera não enviada no passo 1';
    b.onclick = () => trocarCameraPlacar(i);
    pick.appendChild(b);
  });
  const dica = $('#dicaCameraPlacar');
  if(dica){
    dica.textContent = ESTADO.cameraPlacar === 0 ? '' :
      'Os gols detectados nesta câmera são convertidos para o tempo da câmera 1 pela sincronização do passo 1 (' +
      (offsetPlacarS() === 0 ? 'atenção: as câmeras estão sem diferença de início — sincronize antes' : 'diferença de ' + offsetPlacarS().toFixed(1) + ' s') + ').';
  }
  const info = $('#infoCameraPlacar3');
  if(info) info.textContent = `Analisando o placar na câmera ${ESTADO.cameraPlacar + 1}.`;
}
function trocarCameraPlacar(i){
  if(i === ESTADO.cameraPlacar) return;
  ESTADO.cameraPlacar = i;
  rectSel = null; ESTADO.placarRect = null;
  $('#btnConfirmarPlacar').disabled = true; $('#btnIrGols').disabled = true;
  $('#placarAtual').innerHTML = '<span class="bad">Marque o placar nesta câmera e confirme a região.</span>';
  $('#previewPlacar').innerHTML = '';
  renderCameraPlacar(); agendarSalvar();
  carregarFrame();
}

let frameNatural = {w:0,h:0};
let rectSel = null;      // ultimo retangulo arrastado (rascunho, ainda nao salvo)
let zonasSel = [];       // zonas-gatilho ja adicionadas nesta sessao (lista de [x,y,w,h])
let arrastando = false, inicioArrasto = null;

function prepararCanvas(){
  const img = $('#frameImg'), cv = $('#frameCanvas');
  cv.width = img.clientWidth; cv.height = img.clientHeight;
}
async function carregarFrame(){
  if(!videoPlacar()){ alert('Escolha um vídeo no passo 1.'); return; }
  const tempo_s = parseTempo($('#tempoFrame').value) || 0;
  const r = await fetch('/api/frame', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({video: videoPlacar().caminho, tempo_s})});
  if(!r.ok){ alert('Não consegui ler esse instante do vídeo.'); return; }
  const blob = await r.blob();
  const img = $('#frameImg');
  img.onload = ()=>{
    frameNatural = {w: img.naturalWidth, h: img.naturalHeight};
    prepararCanvas();
    redesenharTudo();
    aplicarFiltroBrilho();
  };
  img.src = URL.createObjectURL(blob);
}
$('#btnCarregarFrame').onclick = carregarFrame;

function coordsCanvas(e){
  const r = $('#frameCanvas').getBoundingClientRect();
  return {x: e.clientX-r.left, y: e.clientY-r.top};
}
function desenharRetangulo(ctx, rect, cor, rotulo){
  const img = $('#frameImg');
  if(!frameNatural.w || !img.clientWidth) return;
  const esc = img.clientWidth / frameNatural.w;
  const x = rect[0]*esc, y = rect[1]*esc, w = rect[2]*esc, h = rect[3]*esc;
  ctx.strokeStyle = cor; ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
  if(rotulo){
    ctx.fillStyle = cor; ctx.font = 'bold 13px system-ui';
    ctx.fillText(rotulo, x+3, y > 14 ? y-4 : y+14);
  }
}
function redesenharTudo(){
  const cv = $('#frameCanvas'), ctx = cv.getContext('2d');
  ctx.clearRect(0,0,cv.width,cv.height);
  if(ESTADO.placarRect) desenharRetangulo(ctx, ESTADO.placarRect, '#22c55e', 'placar');
  zonasSel.forEach((z,i)=> desenharRetangulo(ctx, z, '#f59e0b', 'zona '+(i+1)));
}
function desenharRascunho(p0,p1){
  redesenharTudo();
  const cv = $('#frameCanvas'), ctx = cv.getContext('2d');
  ctx.strokeStyle = '#60a5fa'; ctx.lineWidth = 2;
  ctx.strokeRect(Math.min(p0.x,p1.x), Math.min(p0.y,p1.y), Math.abs(p1.x-p0.x), Math.abs(p1.y-p0.y));
}
function renderListaZonas(){
  const el = $('#listaZonas');
  if(!zonasSel.length){ el.innerHTML = '<span class="hint">Nenhuma zona adicionada ainda.</span>'; return; }
  el.innerHTML = '';
  zonasSel.forEach((z,i)=>{
    const div = document.createElement('div'); div.className = 'row'; div.style.marginBottom = '4px';
    div.innerHTML = `<span class="hint">Zona ${i+1}: [${z.join(', ')}]</span>
      <button class="ghost" data-i="${i}" style="padding:2px 10px">✕</button>`;
    div.querySelector('button').onclick = ()=>{ zonasSel.splice(i,1); renderListaZonas(); redesenharTudo(); };
    el.appendChild(div);
  });
}
$('#frameCanvas').addEventListener('mousedown', e=>{ arrastando = true; inicioArrasto = coordsCanvas(e); });
$('#frameCanvas').addEventListener('mousemove', e=>{ if(arrastando) desenharRascunho(inicioArrasto, coordsCanvas(e)); });
window.addEventListener('mouseup', e=>{
  if(!arrastando) return;
  arrastando = false;
  const fim = coordsCanvas(e);
  const img = $('#frameImg');
  if(!frameNatural.w || !img.clientWidth) return;
  const esc = frameNatural.w / img.clientWidth;
  const x0 = Math.min(inicioArrasto.x, fim.x)*esc, y0 = Math.min(inicioArrasto.y, fim.y)*esc;
  const w = Math.abs(fim.x-inicioArrasto.x)*esc, h = Math.abs(fim.y-inicioArrasto.y)*esc;
  if(w < 4 || h < 4) return;
  rectSel = [Math.round(x0), Math.round(y0), Math.round(w), Math.round(h)];
  $('#btnConfirmarPlacar').disabled = false;
});
$('#btnAddZona').onclick = ()=>{
  if(!rectSel){ alert('Arraste um retângulo no quadro primeiro.'); return; }
  zonasSel.push(rectSel);
  rectSel = null;
  renderListaZonas();
  redesenharTudo();
  $('#cardZonasDet').style.display = 'block';
};
$('#btnSalvarZonas').onclick = async ()=>{
  if(!videoPlacar()){ alert('Escolha um vídeo no passo 1.'); return; }
  const r = await fetch('/api/zonas', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({video: videoPlacar().caminho, zonas: zonasSel})});
  if(!r.ok){ alert('Não consegui salvar as zonas.'); return; }
  $('#btnSalvarZonas').textContent = 'Salvo ✓';
  setTimeout(()=>{ $('#btnSalvarZonas').textContent = 'Salvar zonas'; }, 1500);
  if(zonasSel.length > 0) $('#cardZonasDet').style.display = 'block';
};

async function mostrarBlobEm(el, resp){
  const blob = await resp.blob();
  el.innerHTML = `<img src="${URL.createObjectURL(blob)}" style="max-width:400px;border-radius:7px;border:1px solid var(--line)">`;
  aplicarFiltroBrilho();
}
$('#btnVerRecorte').onclick = async ()=>{
  if(!rectSel || !videoPlacar()) return;
  const tempo_s = parseTempo($('#tempoFrame').value) || 0;
  const r = await fetch('/api/placar/preview', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({video: videoPlacar().caminho, tempo_s, rect: rectSel})});
  if(!r.ok){ alert('Não consegui gerar o recorte.'); return; }
  await mostrarBlobEm($('#previewPlacar'), r);
};
$('#btnConfirmarPlacar').onclick = async ()=>{
  if(!rectSel || !videoPlacar()) return;
  const tempo_s = parseTempo($('#tempoFrame').value) || 0;
  const r = await fetch('/api/placar', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({video: videoPlacar().caminho, rect: rectSel, tempo_s})});
  if(!r.ok){ alert('Não consegui salvar a região.'); return; }
  ESTADO.placarRect = rectSel;
  $('#placarAtual').innerHTML = `<span class="ok">✓ Região salva: [${rectSel.join(', ')}]</span>`;
  $('#btnIrGols').disabled = false;
  redesenharTudo();
};
$('#btnIrGols').onclick = ()=>irPara('s-gols');

/* ------------------------------------------------------------ jobs (polling e cancelamento) */
let jobAtivoId = null;
async function cancelarJobAtivo(){
  if(!jobAtivoId) return;
  try{
    await fetch(`/api/job/${jobAtivoId}/cancelar`, {method: 'POST'});
  }catch(e){
    console.error('Erro ao cancelar job:', e);
  }
}
$('#btnCancelarDetectar').onclick = cancelarJobAtivo;
$('#btnCancelarZonas').onclick = cancelarJobAtivo;

async function acompanharJob(job_id, elLog, btnCancelar = null){
  jobAtivoId = job_id;
  if(btnCancelar) btnCancelar.style.display = 'inline-block';
  elLog.style.display = 'block';
  elLog.textContent = 'iniciando...';
  try{
    while(true){
      const r = await fetch('/api/job/' + job_id);
      if(!r.ok) break;
      const j = await r.json();
      const linhas = j.log.slice(-40).join('\n') + (j.linha_atual ? '\n' + j.linha_atual : '');
      elLog.textContent = linhas || '(sem saída ainda)';
      elLog.scrollTop = elLog.scrollHeight;
      if(j.status === 'done' || j.status === 'error' || j.status === 'canceled'){
        if(j.status === 'done'){
          elLog.textContent += '\n\n✓ concluído';
          return true;
        }else if(j.status === 'canceled'){
          elLog.textContent += '\n\n⚠ Processamento cancelado.';
          return false;
        }else{
          elLog.textContent += '\n\n✗ erro (código ' + j.returncode + ')';
          return false;
        }
      }
      await new Promise(res => setTimeout(res, 1000));
    }
    return false;
  }finally{
    if(btnCancelar) btnCancelar.style.display = 'none';
    jobAtivoId = null;
  }
}

/* ------------------------------------------------------------ cameras dos clipes */
let cameraVer = 1;   // câmera usada para assistir aos clipes (1 = principal)
try { cameraVer = Number(localStorage.getItem('futbin_camera_ver')) || 1; } catch(e) {}
function camerasCarregadas(){ return [1,2,3].filter(n => Boolean(camerasSelecionadas()[n-1])); }
function cameraVerValida(){
  return camerasCarregadas().includes(cameraVer) ? cameraVer : 1;
}
function definirCameraVer(n){
  const antes = cameraVerValida();
  cameraVer = n;
  try { localStorage.setItem('futbin_camera_ver', String(n)); } catch(e) {}
  trocarVideoCompleto(antes);
}
// Tempo do jogo (linha do tempo da câmera 1) = tempo do arquivo da câmera n + offsetCameraS(n).
function offsetCameraS(n){
  const ref = camerasSelecionadas()[0], cam = camerasSelecionadas()[(n || 1) - 1];
  if(!ref || !cam || !n || n === 1) return 0;
  return (Number(ref.inicio_jogo_s) || 0) - (Number(cam.inicio_jogo_s) || 0);
}
function caminhoVideoCompleto(n){
  const cam = camerasSelecionadas()[(n || 1) - 1];
  return (cam && cam.caminho) || (ESTADO.video && ESTADO.video.caminho) || '';
}
function urlVideoCompleto(n){
  const caminho = caminhoVideoCompleto(n);
  return '/video/completo' + (caminho ? ('?video=' + encodeURIComponent(caminho)) : '');
}
function tempoJogoDoVideoCompleto(){
  const vc = $('#videoCompleto');
  return (vc ? (vc.currentTime || 0) : 0) + offsetCameraS(cameraVerValida());
}
function irParaTempoJogo(t){
  const vc = $('#videoCompleto');
  if(!vc) return;
  vc.currentTime = Math.max(0, t - offsetCameraS(cameraVerValida()));
  $('#tempoCompletoTxt').textContent = fmtTempo(tempoJogoDoVideoCompleto());
}
function rotuloCameraVideoCompleto(){
  const el = $('#rotCameraCompleto');
  if(el) el.textContent = camerasCarregadas().length > 1 ? `· câmera ${cameraVerValida()}` : '';
}
// Cada escolha invalida respostas antigas de outra qualidade ou câmera.
let pedidoPreviaCompleto = 0;
let restaurarVideoCompleto = null;
let posicaoPendenteCompleto = null;
function posicaoVideoCompleto(){
  const vc = $('#videoCompleto');
  return posicaoPendenteCompleto || {tempo:vc.currentTime || 0, tocando:!vc.paused};
}
function aplicarFonteVideoCompleto(url, tempoArquivo, tocando){
  const vc = $('#videoCompleto');
  const velocidade = vc.playbackRate;
  // Uma segunda escolha antes dos metadados não deve devolver o vídeo ao zero.
  posicaoPendenteCompleto = {tempo:tempoArquivo, tocando};
  vc.defaultPlaybackRate = velocidade;
  if(restaurarVideoCompleto) vc.removeEventListener('loadedmetadata', restaurarVideoCompleto);
  restaurarVideoCompleto = () => {
    vc.currentTime = Math.max(0, Math.min(tempoArquivo, Number.isFinite(vc.duration) ? vc.duration : tempoArquivo));
    vc.playbackRate = vc.defaultPlaybackRate;
    posicaoPendenteCompleto = null;
    if(tocando) vc.play().catch(() => {});
    restaurarVideoCompleto = null;
  };
  vc.addEventListener('loadedmetadata', restaurarVideoCompleto, {once:true});
  vc.setAttribute('data-carregado', url);
  vc.src = url;
  vc.load();
  vc.playbackRate = velocidade;
  if(typeof aplicarFiltroBrilho === 'function') aplicarFiltroBrilho();
}
async function aplicarQualidadeVideoCompleto(){
  const pedido = ++pedidoPreviaCompleto;
  const qualidade = $('#qualidadeVideoCompleto').value;
  const vc = $('#videoCompleto'), status = $('#statusPreviaCompleto');
  const camera = cameraVerValida(), caminho = caminhoVideoCompleto(camera);
  try { localStorage.setItem('futbin_qualidade_revisao', qualidade); } catch(e) {}
  const atual = () => pedido === pedidoPreviaCompleto && camera === cameraVerValida() && caminho === caminhoVideoCompleto(camera);
  if(qualidade === 'original'){
    const url = urlVideoCompleto(camera);
    if(vc.getAttribute('data-carregado') !== url) aplicarFonteVideoCompleto(url, posicaoVideoCompleto().tempo, posicaoVideoCompleto().tocando);
    status.textContent = 'Qualidade original.';
    return;
  }
  if(!caminho){ status.textContent = 'Escolha o vídeo no passo 1 antes de preparar a versão leve.'; return; }
  status.textContent = `Preparando ${qualidade}p… Você pode continuar usando o vídeo enquanto aguarda.`;
  try {
    const response = await fetch('/api/video/previa', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({video:caminho, altura:Number(qualidade)})});
    const data = await response.json().catch(() => ({}));
    if(response.status === 404){
      throw new Error('O servidor ainda está na versão antiga. Feche o fut-bin, abra novamente e então clique em Preparar / aplicar.');
    }
    if(!response.ok) throw new Error(data.detail || `Não foi possível iniciar a preparação (erro ${response.status}).`);
    while(!data.pronto){
      if(!atual()) return;
      await new Promise(resolve => setTimeout(resolve, 1200));
      if(!atual()) return;
      const r = await fetch('/api/job/' + data.job_id);
      if(!r.ok) throw new Error('Não foi possível consultar a preparação. Tente novamente.');
      const job = await r.json();
      if(!atual()) return;
      if(job.status === 'error' || job.status === 'canceled') throw new Error('A preparação não terminou. Confira se o FFmpeg está instalado e se há espaço em disco; clique em Preparar / aplicar para tentar novamente.');
      if(job.status === 'done') break;
      const progress = [...(job.log || []), job.linha_atual || ''].reverse().find(line => line.startsWith('out_time='));
      status.textContent = `Preparando ${qualidade}p…` + (progress ? ' Processado: ' + progress.slice(9, 17) + '.' : '') + ' Você pode continuar usando o vídeo.';
    }
    if(!atual()) return;
    if(vc.getAttribute('data-carregado') !== data.url) aplicarFonteVideoCompleto(data.url, posicaoVideoCompleto().tempo, posicaoVideoCompleto().tocando);
    status.textContent = `${qualidade}p pronto. Cortes e exportações continuam na qualidade original.`;
  } catch(error){
    if(atual()) status.textContent = 'Não foi possível aplicar a versão leve. ' + error.message;
  }
}
function trocarVideoCompleto(anterior){
  const vc = $('#videoCompleto');
  rotuloCameraVideoCompleto();
  if(!vc || !vc.getAttribute('data-carregado')) return;
  const nova = cameraVerValida();
  if(nova === anterior) return;
  ++pedidoPreviaCompleto;
  const posicao = posicaoVideoCompleto();
  const tempo = posicao.tempo + offsetCameraS(anterior) - offsetCameraS(nova);
  aplicarFonteVideoCompleto(urlVideoCompleto(nova), tempo, posicao.tocando);
  vc.addEventListener('loadedmetadata', () => aplicarQualidadeVideoCompleto(), {once:true});
}
function urlClipeDaCamera(indice, cam){
  const chave = String(indice).padStart(2,'0');
  if(cam <= 1) return ESTADO.clipes[chave] || null;
  return `/video/clipes/${indice}/camera/${cam}`;
}
function renderCameraVer(){
  const pick = $('#pickCameraVer'); if(!pick) return;
  const atual = cameraVerValida();
  pick.innerHTML = '';
  [1,2,3].forEach(n => {
    const ok = camerasCarregadas().includes(n);
    const b = document.createElement('button');
    b.type = 'button'; b.className = n === atual ? 'act' : 'ghost';
    b.style.cssText = 'font-size:12px; padding:4px 10px';
    b.disabled = !ok;
    b.textContent = `Câmera ${n}${n === 1 ? ' · principal' : ''}`;
    if(!ok) b.title = 'Câmera não enviada no passo 1';
    b.onclick = () => { definirCameraVer(n); renderCameraVer(); renderGradeClipes(clipesAtuais); };
    pick.appendChild(b);
  });
  const dica = $('#dicaCameraVer');
  if(dica) dica.textContent = atual > 1 ? 'Clipes ainda não cortados nessa câmera são gerados ao abrir; para gerar todos de uma vez use o passo 3 › Câmeras dos clipes.' : '';
}
function renderOpcoesCamerasCorte(){
  const box = $('#opcoesCamerasCorte'); if(!box) return;
  const marcadas = new Set([...box.querySelectorAll('input:checked')].map(i => Number(i.value)));
  const primeira = !box.dataset.pronto;
  box.innerHTML = '';
  box.dataset.pronto = '1';
  [2,3].forEach(n => {
    const ok = camerasCarregadas().includes(n);
    const lab = document.createElement('label');
    lab.style.cssText = 'display:inline-flex; align-items:center; gap:6px; margin:0; font-size:13px; cursor:' + (ok ? 'pointer' : 'not-allowed') + (ok ? '' : '; opacity:.5');
    const chk = document.createElement('input');
    chk.type = 'checkbox'; chk.value = String(n); chk.style.width = 'auto'; chk.disabled = !ok;
    chk.checked = ok && (primeira || marcadas.has(n));
    lab.appendChild(chk);
    lab.appendChild(document.createTextNode(`Câmera ${n}${ok ? '' : ' · não enviada'}`));
    box.appendChild(lab);
  });
  $('#btnCortarCameras').disabled = !camerasCarregadas().some(n => n > 1);
}
function camerasParaCortar(){
  return [...$('#opcoesCamerasCorte').querySelectorAll('input:checked')].map(i => Number(i.value));
}
async function cortarCamerasExtras(logEl, btnCanc){
  const cams = camerasParaCortar();
  if(!cams.length) return true;
  const r = await fetch('/api/cameras/cortar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({cameras: cams})});
  if(!r.ok){
    const d = await r.json().catch(() => ({}));
    logEl.style.display = 'block';
    logEl.textContent = '❌ ' + (d.detail || 'Não consegui cortar as outras câmeras.');
    return false;
  }
  const {job_id} = await r.json();
  return await acompanharJob(job_id, logEl, btnCanc);
}
$('#btnCortarCameras').onclick = async () => {
  $('#btnCortarCameras').disabled = true;
  try { await cortarCamerasExtras($('#cortarCamerasLog'), $('#btnCancelarCortarCameras')); }
  finally { renderOpcoesCamerasCorte(); }
};
$('#btnCancelarCortarCameras').onclick = async () => {
  if(jobAtivoId) await fetch('/api/job/' + jobAtivoId + '/cancelar', {method:'POST'});
};

/* ------------------------------------------------------------ passo 3: detectar e cortar */
$('#btnDetectar').onclick = async ()=>{
  const logEl = $('#detLog');
  const btnCanc = $('#btnCancelarDetectar');

  if(!ESTADO.video){
    try {
      const rg = await fetch('/api/gols');
      const dg = await rg.json();
      if(dg && dg.video){
        selecionarVideo({nome: dg.video.split(/[\\/]/).pop(), caminho: dg.video, duracao_s: null});
      }
    } catch(e){}
  }
  if(!ESTADO.video){
    logEl.style.display = 'block';
    logEl.textContent = '⚠ Escolha um vídeo no passo 1 antes de detectar.';
    return;
  }

  const body = {
    video: videoPlacar().caminho,
    offset_s: offsetPlacarS(),
    video_ref: ESTADO.video.caminho,
    gols_totais: $('#golsTotais').value ? parseInt($('#golsTotais').value,10) : null,
    fixo: $('#fixoSel').value === '1',
    inicio: $('#inicioJogo').value || null,
    fim: $('#fimJogo').value || null,
  };
  $('#btnDetectar').disabled = true;
  try{
    let r = await fetch('/api/detectar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if(!r.ok){
      logEl.style.display = 'block';
      logEl.textContent = '❌ Não consegui iniciar a detecção.';
      return;
    }
    let {job_id} = await r.json();
    if(!await acompanharJob(job_id, logEl, btnCanc)) return;

    const rg = await fetch('/api/gols?video='+encodeURIComponent(ESTADO.video.caminho));
    const {eventos} = await rg.json();
    if(!eventos.length){
      logEl.textContent += '\n\n⚠ nenhum gol detectado. Ajuste os parâmetros acima e tente de novo, ou adicione manualmente no próximo passo.';
    }
    await fetch('/api/gols', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({video: ESTADO.video.caminho, eventos: eventos.map(e=>({tempo_s:e.tempo_s}))})});

    r = await fetch('/api/cortar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({video: ESTADO.video.caminho})});
    if(!r.ok){
      logEl.style.display = 'block';
      logEl.textContent = '❌ Não consegui iniciar o corte.';
      return;
    }
    ({job_id} = await r.json());
    if(!await acompanharJob(job_id, logEl, btnCanc)) return;
    await carregarClipes();
    $('#btnIrRevisar').disabled = ESTADO.gols.length===0;
    if(camerasParaCortar().length){
      logEl.textContent += '\n\nCortando as outras câmeras...';
      await cortarCamerasExtras(logEl, btnCanc);
    }
  }catch(e){
    logEl.style.display = 'block';
    logEl.textContent = '❌ Erro: ' + e;
  }
  finally{ $('#btnDetectar').disabled = false; btnCanc.style.display = 'none'; }
};

$('#btnDetectarZonas').onclick = async ()=>{
  const logEl = $('#zonasDetLog');
  const btnCanc = $('#btnCancelarZonas');

  if(!ESTADO.video){
    try {
      const rg = await fetch('/api/gols');
      const dg = await rg.json();
      if(dg && dg.video){
        selecionarVideo({nome: dg.video.split(/[\\/]/).pop(), caminho: dg.video, duracao_s: null});
      }
    } catch(e){}
  }
  if(!ESTADO.video){
    logEl.style.display = 'block';
    logEl.textContent = '⚠ Escolha um vídeo no passo 1 antes de detectar.';
    return;
  }

  const body = {
    video: videoPlacar().caminho,
    offset_s: offsetPlacarS(),
    video_ref: ESTADO.video.caminho,
    eventos_esperados: $('#zonasEventos').value ? parseInt($('#zonasEventos').value, 10) : null,
    inicio: $('#inicioJogo').value || null,
    fim: $('#fimJogo').value || null,
  };
  $('#btnDetectarZonas').disabled = true;
  try{
    let r = await fetch('/api/zonas/detectar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if(!r.ok){
      logEl.style.display = 'block';
      logEl.textContent = '❌ Não consegui iniciar a detecção pelas zonas.';
      return;
    }
    let {job_id} = await r.json();
    if(!await acompanharJob(job_id, logEl, btnCanc)) return;

    r = await fetch('/api/cortar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({video: ESTADO.video.caminho})});
    if(!r.ok){
      logEl.style.display = 'block';
      logEl.textContent = '❌ Não consegui iniciar o corte.';
      return;
    }
    ({job_id} = await r.json());
    if(!await acompanharJob(job_id, logEl, btnCanc)) return;
    await carregarClipes();
    $('#btnIrRevisar').disabled = ESTADO.gols.length===0;
  }catch(e){
    logEl.style.display = 'block';
    logEl.textContent = '❌ Erro: ' + e;
  }
  finally{ $('#btnDetectarZonas').disabled = false; btnCanc.style.display = 'none'; }
};
$('#btnIrRevisar').onclick = ()=>irPara('s-revisar');

/* ------------------------------------------------------------ passo 4: revisar os cortes */
try {
  const qualidade = localStorage.getItem('futbin_qualidade_revisao');
  if(['original','360','480'].includes(qualidade)) $('#qualidadeVideoCompleto').value = qualidade;
} catch(e) {}
$('#qualidadeVideoCompleto').onchange = aplicarQualidadeVideoCompleto;
$('#btnPrepararPrevia').onclick = aplicarQualidadeVideoCompleto;

$$('.btnVel').forEach(btn => {
  btn.onclick = () => {
    const vel = parseFloat(btn.dataset.vel);
    const vc = $('#videoCompleto');
    if(vc) { vc.defaultPlaybackRate = vel; vc.playbackRate = vel; }
    $$('.btnVel').forEach(b => b.classList.remove('sel'));
    btn.classList.add('sel');
  };
});

$('#videoCompleto').addEventListener('timeupdate', () => {
  $('#tempoCompletoTxt').textContent = fmtTempo(tempoJogoDoVideoCompleto());
});

$('#videoCompleto').addEventListener('loadedmetadata', () => {
  const st = $('#statusVideoCompleto');
  const vc = $('#videoCompleto');
  if(st && vc) st.innerHTML = `<span class="ok">✓ Vídeo pronto (${fmtTempo(vc.duration)})</span>`;
});

$('#videoCompleto').addEventListener('error', () => {
  const st = $('#statusVideoCompleto');
  if(st) st.innerHTML = `<span class="bad">⚠ Não foi possível carregar o vídeo. Verifique se o arquivo existe ou escolha outro vídeo no <a href="javascript:void(0)" onclick="irPara('s-video')" style="color:var(--accent); font-weight:600">Passo 1</a>.</span>`;
});

function pularParaTempoVideo(){
  const input = $('#tempoPularVideo');
  if(!input) return;
  const txt = input.value.trim();
  if(!txt){
    input.focus();
    return;
  }
  const t = parseTempo(txt);
  if(t == null || isNaN(t) || t < 0){
    alert('Digite um tempo válido (ex: 14:30 ou 8:40 ou segundos).');
    input.focus();
    input.select();
    return;
  }
  const vc = $('#videoCompleto');
  if(vc){
    irParaTempoJogo(t);
    vc.play().catch(()=>{});
  }
}

$('#btnPularVideo').onclick = pularParaTempoVideo;
$('#tempoPularVideo').addEventListener('keydown', e => {
  if(e.key === 'Enter'){
    e.preventDefault();
    pularParaTempoVideo();
  }
});
const btnMenos15 = $('#btnPularMenos15s');
if(btnMenos15){
  btnMenos15.onclick = () => {
    const vc = $('#videoCompleto');
    if(vc){
      vc.currentTime = Math.max(0, (vc.currentTime || 0) - 15);
      $('#tempoCompletoTxt').textContent = fmtTempo(tempoJogoDoVideoCompleto());
    }
  };
}
const btnMais15 = $('#btnPularMais15s');
if(btnMais15){
  btnMais15.onclick = () => {
    const vc = $('#videoCompleto');
    if(vc){
      vc.currentTime = Math.min(vc.duration || 999999, (vc.currentTime || 0) + 15);
      $('#tempoCompletoTxt').textContent = fmtTempo(tempoJogoDoVideoCompleto());
    }
  };
}
const btnMaisTrasCompleto = $('#btnGerarClipeCompletoMaisTras');
if(btnMaisTrasCompleto){
  btnMaisTrasCompleto.onclick = () => {
    $('#posicaoCorteCompleto').value = 'antes';
    $('#duracaoCorteCompleto').value = '15';
    $('#btnGerarClipeCompleto').click();
  };
}

/* Tela cheia inclui o player e as ações, para o corte continuar acessível. */
function informarCorteSobreVideo(mensagem){
  const status = $('#statusCorteSobreVideo');
  status.textContent = mensagem;
  status.hidden = !mensagem;
}
async function alternarTelaCheiaCompleto(){
  const player = $('#playerVideoCompleto');
  try {
    if(document.fullscreenElement === player) await document.exitFullscreen();
    else if(player.requestFullscreen) await player.requestFullscreen();
    else informarCorteSobreVideo('Tela cheia indisponível neste navegador.');
  } catch(e) {
    informarCorteSobreVideo('Não foi possível abrir a tela cheia. Tente novamente.');
  }
}
$('#btnTelaCheiaCompleto').onclick = alternarTelaCheiaCompleto;
function alternarPlayPauseVideoCompleto(){
  const vc = $('#videoCompleto');
  if(!vc || vc.readyState < 1) return;
  if(vc.paused) vc.play().catch(() => {});
  else vc.pause();
}
const areaCliqueVideoCompleto = $('#cliquePlayVideoCompleto');
if(areaCliqueVideoCompleto){
  areaCliqueVideoCompleto.addEventListener('click', alternarPlayPauseVideoCompleto);
  areaCliqueVideoCompleto.addEventListener('dblclick', event => {
    event.preventDefault();
    alternarTelaCheiaCompleto();
  });
}
document.addEventListener('fullscreenchange', () => {
  const cheia = document.fullscreenElement === $('#playerVideoCompleto');
  const btn = $('#btnTelaCheiaCompleto');
  btn.textContent = cheia ? '⛶ Sair da tela cheia' : '⛶ Tela cheia';
  btn.setAttribute('aria-label', cheia ? 'Sair da tela cheia' : 'Entrar em tela cheia');
  btn.setAttribute('aria-pressed', String(cheia));
});
$('#btnVoltar10sSobreVideo').onclick = () => {
  const vc = $('#videoCompleto');
  if(!vc) return;
  vc.currentTime = Math.max(0, (vc.currentTime || 0) - 10);
  const tempoTxt = $('#tempoCompletoTxt');
  if(tempoTxt) tempoTxt.textContent = fmtTempo(tempoJogoDoVideoCompleto());
};
$('#btnCortar15sSobreVideo').onclick = () => {
  const vc = $('#videoCompleto');
  if(!ESTADO.video || !vc.readyState || vc.currentTime <= 0 || tempoJogoDoVideoCompleto() <= 0){
    informarCorteSobreVideo('Reproduza o vídeo até o fim do lance para cortar os segundos anteriores.');
    return;
  }
  $('#btnGerarClipeCompletoMaisTras').click();
};

/* Fila de processamento de cortes do vídeo completo */
const filaCortes = [];
let processandoFilaCortes = false;
let _ultimoCliqueCorte = null;

function atualizarIndicadorFila(){
  const badge = $('#badgeFilaCortes');
  const total = (processandoFilaCortes ? 1 : 0) + filaCortes.length;
  if(badge){
    if(total > 0){
      badge.style.display = 'inline-flex';
      if(filaCortes.length > 0){
        badge.innerHTML = `⚡ Processando (+${filaCortes.length} na fila)`;
      } else {
        badge.innerHTML = `⚡ Cortando clipe...`;
      }
    } else {
      badge.style.display = 'none';
    }
  }
}

async function processarFilaCortes(){
  if(processandoFilaCortes) return;
  processandoFilaCortes = true;

  const logEl = $('#logCorteCompleto');

  while(filaCortes.length > 0){
    const job = filaCortes.shift();
    atualizarIndicadorFila();
    informarCorteSobreVideo(`Cortando ${fmtTempo(job.inicio_s)} a ${fmtTempo(job.fim_s)}…`);

    if(logEl){
      logEl.style.display = 'block';
      const filaMsg = filaCortes.length > 0 ? ` (+${filaCortes.length} na fila)` : '';
      logEl.innerHTML = `<span class="spinner"></span> <b>Cortando do original em qualidade máxima (${job.rotuloClipe})</b> de ${fmtTempo(job.inicio_s)} até ${fmtTempo(job.fim_s)} (${job.dur}s)${filaMsg}...`;
    }

    try {
      const r = await fetch('/api/gols/adicionar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          video: job.videoCaminho,
          inicio_s: job.inicio_s,
          fim_s: job.fim_s,
          tempo_s: job.tempo_s,
          status: job.status,
          lance: job.lanceNome,
        })
      });
      const res = await r.json();
      if(!r.ok){
        informarCorteSobreVideo('Erro ao gerar o corte. Confira o registro de cortes.');
        if(logEl) logEl.innerHTML = `<span class="bad">❌ Erro ao cortar (${fmtTempo(job.inicio_s)}): ${res.detail || 'falha no servidor'}</span>`;
        continue;
      }

      await carregarClipes();

      informarCorteSobreVideo(`✓ Clipe #${res.indice} pronto: ${fmtTempo(job.inicio_s)} a ${fmtTempo(job.fim_s)}.`);
      const novoClipe = clipesAtuais.find(c => c.indice === res.indice);
      mostrarAlertaClipePronto({
        indice: res.indice,
        inicio_s: job.inicio_s,
        fim_s: job.fim_s,
        dur: job.dur,
        tipo: job.tipo,
        infoTipo: job.infoTipo,
        clipe: novoClipe,
        restantesNaFila: filaCortes.length
      });

      if(logEl){
        const resto = filaCortes.length > 0 ? ` · restam ${filaCortes.length} na fila` : '';
        logEl.innerHTML = `<span class="ok">✓ Clipe #${String(res.indice).padStart(2,'0')} inserido com sucesso (${fmtTempo(job.inicio_s)} a ${fmtTempo(job.fim_s)})${resto}!</span>`;
      }
    } catch(e) {
      informarCorteSobreVideo('Erro ao comunicar com o servidor para gerar o corte.');
      if(logEl) logEl.innerHTML = `<span class="bad">❌ Erro ao comunicar com o servidor: ${e}</span>`;
    }
  }

  processandoFilaCortes = false;
  atualizarIndicadorFila();

  if(logEl){
    setTimeout(() => {
      if(!processandoFilaCortes && filaCortes.length === 0){
        logEl.style.display = 'none';
      }
    }, 4500);
  }
}

$('#btnGerarClipeCompleto').onclick = () => {
  if(!ESTADO.video){ alert('Selecione um vídeo primeiro no passo 1.'); return; }
  const t = tempoJogoDoVideoCompleto();

  // Evita duplo-clique acidental exato no mesmo segundo dentro de 350ms
  const agora = Date.now();
  if(_ultimoCliqueCorte && (agora - _ultimoCliqueCorte.ts < 350) && Math.abs(_ultimoCliqueCorte.t - t) < 0.2){
    return;
  }
  _ultimoCliqueCorte = { ts: agora, t: t };

  const dur = Math.max(2, parseFloat($('#duracaoCorteCompleto').value) || 15);
  const pos = $('#posicaoCorteCompleto').value;
  const tipo = $('#tipoCorteCompleto').value || 'pendente';
  const ehPendente = (tipo === 'pendente' || tipo === 'sem_marcar');
  const infoTipo = ehPendente ? null : obterInfoTipo(tipo);
  const status = ehPendente ? 'pendente' : tipo;
  const lanceNome = (infoTipo && !infoTipo.isGol) ? infoTipo.lanceNome : null;
  const rotuloClipe = ehPendente ? '⏳ Sem marcação' : (infoTipo ? `${infoTipo.icon} ${infoTipo.rotulo}` : tipo);

  let inicio_s = 0, fim_s = 0;
  if(pos === 'antes'){
    fim_s = t;
    inicio_s = Math.max(0, t - dur);
  } else if(pos === 'depois'){
    inicio_s = t;
    fim_s = t + dur;
  } else {
    inicio_s = Math.max(0, t - dur / 2);
    fim_s = t + dur / 2;
  }
  inicio_s = Math.round(inicio_s * 100) / 100;
  fim_s = Math.round(fim_s * 100) / 100;
  if(fim_s <= inicio_s) fim_s = inicio_s + 2;

  const job = {
    id: agora + '_' + Math.random().toString(36).substr(2, 5),
    videoCaminho: ESTADO.video.caminho,
    inicio_s,
    fim_s,
    tempo_s: t,
    dur,
    pos,
    tipo,
    status,
    lanceNome,
    rotuloClipe,
    infoTipo,
    criadoEm: agora
  };

  const jaEstaProcessando = processandoFilaCortes;
  filaCortes.push(job);
  informarCorteSobreVideo(`Corte adicionado: ${fmtTempo(inicio_s)} a ${fmtTempo(fim_s)}${jaEstaProcessando ? " · aguardando na fila" : ""}.`);
  atualizarIndicadorFila();

  // Feedback visual no botão
  const btn = $('#btnGerarClipeCompleto');
  if(btn){
    btn.style.transform = 'scale(0.95)';
    setTimeout(() => { btn.style.transform = ''; }, 120);
  }

  if(jaEstaProcessando){
    mostrarAlertaFilaAdicionada(filaCortes.length, job);
  }

  processarFilaCortes();
};

let _descartandoClipe = false;
async function descartarClipe(indice, avancarModal = true){
  if(_descartandoClipe) return false;
  _descartandoClipe = true;
  const modalAberto = !$('#modalClipe').hidden;
  const idxAtual = clipesAtuais.findIndex(x => x.indice === indice);
  try {
    const v = $('#modalVideo');
    if(v && modalAberto) v.pause();

    const r = await fetch('/api/gols/descartar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({indice})
    });
    if(!r.ok){
      alert('Não consegui descartar o clipe #' + indice);
      return false;
    }

    await carregarClipes();

    if(modalAberto && avancarModal){
      if(!clipesAtuais.length){
        fecharModalClipe();
      } else {
        // Vai para o próximo clipe da lista (que agora ocupa a posição idxAtual)
        const proxIdx = (idxAtual >= 0 && idxAtual < clipesAtuais.length) ? idxAtual : (clipesAtuais.length - 1);
        abrirModalClipe(clipesAtuais[proxIdx]);
      }
    } else {
      fecharModalClipe();
    }
    return true;
  } catch(e) {
    alert('Erro ao descartar clipe: ' + e);
    return false;
  } finally {
    _descartandoClipe = false;
  }
}

async function sincronizarGolsComBackend(){
  try {
    const rc = await fetch('/api/clipes');
    if(!rc.ok) return;
    const {clipes} = await rc.json();
    if(!clipes || !clipes.length) return;

    let mapaMeta = {};
    try {
      const rg = await fetch('/api/gols');
      if(rg.ok){
        const dg = await rg.json();
        (dg.eventos || []).forEach(ev => { mapaMeta[ev.indice] = ev; });
      }
    } catch(e){}

    const antigos = {};
    (ESTADO.gols || []).forEach(g => { antigos[g.indice] = g; });

    ESTADO.gols = clipes.map(c => {
      const meta = mapaMeta[c.indice] || {};
      const prev = antigos[c.indice] || {};
      const rawStatus = c.status || meta.status || prev.status || null;
      const statusFinal = (rawStatus && rawStatus !== 'pendente' && rawStatus !== 'revisar') ? rawStatus : null;
      const lanceFinal = c.lance || meta.lance || prev.lance || null;
      const info = obterInfoTipo(statusFinal, lanceFinal);
      const ehGol = info ? info.isGol : (statusFinal === 'gol');
      const tipo = info ? (info.isGol ? 'gol' : 'lance') : (statusFinal === 'gol' ? 'gol' : (statusFinal ? 'lance' : null));

      let timeEscolhido = (c.time !== undefined && c.time !== null) ? c.time : (prev.time !== undefined ? prev.time : null);
      const temTime = (timeEscolhido !== null && timeEscolhido !== undefined && S.times[timeEscolhido]);
      if(!temTime) timeEscolhido = null;

      const autorFinal = temTime ? (c.autor || prev.autor || null) : null;
      const assistFinal = temTime ? (c.assist || prev.assist || null) : null;
      const destaqueFinal = temTime ? (c.destaque || prev.destaque || null) : null;

      return {
        indice: c.indice,
        tempo: c.tempo || meta.tempo || '',
        tempo_s: c.tempo_s != null ? c.tempo_s : meta.tempo_s,
        inicio_s: meta.inicio_s,
        fim_s: meta.fim_s,
        duracao_s: c.duracao_s != null ? c.duracao_s : prev.duracao_s,
        fonte: meta.fonte || 'revisado',
        status: info ? info.id : (statusFinal || null),
        tipo: tipo,
        lance: ehGol ? null : (lanceFinal || (info ? info.lanceNome : null)),
        placar: c.placar || meta.placar || null,
        time_provavel: meta.time_provavel,
        time: timeEscolhido,
        autor: (ehGol && temTime) ? autorFinal : null,
        assist: (ehGol && temTime) ? assistFinal : null,
        destaque: (!ehGol && temTime) ? destaqueFinal : null,
        camera: Number(c.camera || meta.camera || prev.camera || 1),
        cameras_clipe: (Array.isArray(prev.cameras_clipe) && prev.cameras_clipe.length) ? prev.cameras_clipe : (Array.isArray(c.cameras_clipe) && c.cameras_clipe.length ? c.cameras_clipe : [Number(c.camera || meta.camera || 1)]),
        descartado: Boolean(prev.descartado),
      };
    });

    if(ESTADO.indiceAtual != null && !ESTADO.gols.some(g => g.indice === ESTADO.indiceAtual)){
      ESTADO.indiceAtual = ESTADO.gols.length ? ESTADO.gols[0].indice : null;
    }
  } catch(e){}
}

let _recarregandoClipes = false;
async function carregarClipes(){
  const r = await fetch('/api/clipes');
  const {clipes} = await r.json();
  ESTADO.clipes = {};
  clipes.forEach(c=> ESTADO.clipes[String(c.indice).padStart(2,'0')] = c.url);
  await sincronizarGolsComBackend();
  renderGradeClipes(clipes);

  const vc = $('#videoCompleto');
  if(vc && (!vc.src || !vc.getAttribute('data-carregado'))){
    inicializarVideoCompleto();
  }
  $('#btnIrDados').disabled = (ESTADO.gols||[]).length===0;
}

function obterTempoSegundosClipe(c){
  if(c.tempo_s != null && !isNaN(c.tempo_s) && c.tempo_s !== '') return Number(c.tempo_s);
  if(c.inicio_s != null && !isNaN(c.inicio_s) && c.inicio_s !== '') return Number(c.inicio_s);
  if(c.tempo) {
    const p = parseTempo(c.tempo);
    if(p != null && !isNaN(p)) return Number(p);
  }
  const g = (ESTADO.gols || []).find(x => x.indice === c.indice);
  if(g){
    if(g.tempo_s != null && !isNaN(g.tempo_s) && g.tempo_s !== '') return Number(g.tempo_s);
    if(g.inicio_s != null && !isNaN(g.inicio_s) && g.inicio_s !== '') return Number(g.inicio_s);
    if(g.tempo) {
      const p = parseTempo(g.tempo);
      if(p != null && !isNaN(p)) return Number(p);
    }
  }
  return -1;
}

let clipesAtuais = [];
function renderGradeClipes(clipes){
  // Ordena os clipes da tela 4 por horário crescente (do início para o final do jogo)
  clipesAtuais = [...(clipes || [])].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a);
    const tB = obterTempoSegundosClipe(b);
    if(tA === -1 && tB !== -1) return 1;
    if(tB === -1 && tA !== -1) return -1;
    if(tA !== tB) return tA - tB;
    return (a.indice || 0) - (b.indice || 0);
  });

  const grade = $('#gradeClipes'); grade.innerHTML='';
  if(!clipesAtuais.length){
    grade.innerHTML = '<span class="hint">Nenhum clipe ainda - volte ao passo 3 e rode a detecção ou gere clipes no player do vídeo completo abaixo.</span>';
  }
  clipesAtuais.forEach(c=>{
    const gItem = (ESTADO.gols || []).find(x => x.indice === c.indice);
    const autorAtual = c.autor || (gItem && gItem.autor);
    const timeAtual = (c.time !== undefined && c.time !== null) ? c.time : (gItem && gItem.time);
    const assistAtual = c.assist || (gItem && gItem.assist);
    const destaqueAtual = c.destaque || (gItem && gItem.destaque);
    const statusAtual = c.status || (gItem && gItem.status);
    const lanceAtual = c.lance || (gItem && gItem.lance);

    const info = obterInfoTipo(statusAtual, lanceAtual);
    const div = document.createElement('div');
    div.className = 'evcard' + (info ? ' status-' + info.id : '');
    if(info) div.style.borderColor = info.border;

    const ehGol = info ? info.isGol : (statusAtual === 'gol');
    const temTime = (timeAtual !== null && timeAtual !== undefined && S.times[timeAtual]);
    let autorBadge = '';
    if(ehGol && temTime && autorAtual){
      const timeCor = S.times[timeAtual].cor || 'var(--accent)';
      const txtCor = corTextoParaFundo(timeCor);
      const assistStr = (assistAtual && assistAtual !== '—') ? ` (${assistAtual})` : '';
      autorBadge = `<span style="background:${timeCor}; color:${txtCor}; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:700; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="Autor: ${autorAtual}${assistAtual ? ' (assistência: ' + assistAtual + ')' : ''}">⚽ ${autorAtual}${assistStr}</span>`;
    } else if(!ehGol && temTime && destaqueAtual){
      autorBadge = `<span style="background:rgba(56,189,248,0.18); border:1px solid #38bdf8; color:#38bdf8; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="Destaque: ${destaqueAtual}">⭐ ${destaqueAtual}</span>`;
    }

    const rotuloBadge = info
      ? `<span class="badge-ok" style="background:${info.bg};border:1px solid ${info.border};color:${info.cor};padding:2px 6px;border-radius:4px;font-size:11px">${info.icon} ${info.rotulo}</span>`
      : `<span class="badge-ok" style="background:var(--panel2);border:1px solid var(--line);color:var(--dim);padding:2px 6px;border-radius:4px;font-size:11px">⏳ sem marcação</span>`;
    const rotuloCheck = (ehGol && temTime && autorAtual) ? '⚽' : (info ? info.icon : '⏳');
    const placarBadge = c.placar ? `<span class="placar-badge">${c.placar}</span>` : '';

    div.innerHTML = `
      <div class="topo" style="display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap">
        <div class="row" style="gap:5px; align-items:center; flex-wrap:wrap">
          <b style="font-size:13px">#${String(c.indice).padStart(2,'0')}</b>
          <span class="hint" style="margin:0">${c.tempo||''}</span>
          ${autorBadge}
        </div>
        <div class="row" style="gap:4px; align-items:center">
          ${placarBadge}
          ${rotuloBadge}
          <button type="button" class="btnDescartarCard" title="Excluir este clipe permanentemente do computador" style="position:static; margin-left:4px; background:#dc2626; color:#fff; border:0; border-radius:5px; padding:2px 7px; font-size:11px; cursor:pointer; font-weight:700">🗑 Excluir</button>
        </div>
      </div>
      <div class="thumb-wrap" style="position:relative">
        <video src="${urlClipeDaCamera(c.indice, cameraVerValida()) || c.url}" muted preload="${cameraVerValida() > 1 ? 'none' : 'metadata'}" playsinline></video>
        <div class="play"></div>
        <div class="check" style="${info ? `display:flex;background:${info.bg};border:1px solid ${info.border};color:${info.cor}` : ''}">${rotuloCheck}</div>
      </div>
    `;

    const vid = div.querySelector('video');
    vid.onerror = () => {
      const wrap = div.querySelector('.thumb-wrap');
      wrap.innerHTML = `
        <div style="background:#200d0d; border:1px solid #7f1d1d; border-radius:6px; padding:16px 8px; text-align:center">
          <div style="color:#f87171; font-size:12px; font-weight:600">⚠ Vídeo corrompido / preto</div>
          <button type="button" class="warnb btnRemoverCorrompido" style="margin-top:8px">🗑 Excluir clipe</button>
        </div>
      `;
      const btnRem = wrap.querySelector('.btnRemoverCorrompido');
      if(btnRem){
        btnRem.onclick = async (e) => {
          e.stopPropagation();
          if(confirm(`ATENÇÃO: Excluir definitivamente o clipe corrompido #${c.indice} do computador?`)){
            await descartarClipe(c.indice);
          }
        };
      }
    };

    const btnDesc = div.querySelector('.btnDescartarCard');
    if(btnDesc){
      btnDesc.onclick = async (e) => {
        e.stopPropagation();
        if(confirm(`ATENÇÃO: Deseja EXCLUIR DEFINITIVAMENTE o clipe #${String(c.indice).padStart(2,'0')} (${c.tempo||''}) do computador?\n\nO arquivo de vídeo será apagado e o lance será removido.`)){
          await descartarClipe(c.indice);
        }
      };
    }

    div.style.cursor = 'pointer';
    div.onclick = (e) => {
      if(e.target.closest('.btnDescartarCard')) return;
      abrirModalClipe(c);
    };
    grade.appendChild(div);
  });
  const contagemGols = clipesAtuais.filter(c => {
    const inf = obterInfoTipo(c.status, c.lance);
    return inf && inf.isGol;
  }).length;
  const contagemLances = clipesAtuais.filter(c => {
    const inf = obterInfoTipo(c.status, c.lance);
    return inf && !inf.isGol;
  }).length;
  const faltam = clipesAtuais.filter(c => !obterInfoTipo(c.status, c.lance)).length;
  $('#contagemClipes').textContent = `(${contagemGols} gols · ${contagemLances} lances · ${faltam} sem marcação · ordem cronológica ⏱️)`;
}

// Cada câmera filma o jogo de um ângulo/distância diferente, então o zoom marcado
// numa câmera não serve pra outra: fica guardado por câmera (câmera 1 usa os campos
// legados zoom/zoom_x/zoom_y; 2 e 3 ficam em zoom_por_camera). Espelha
// obter_zoom_camera/definir_zoom_camera do montar_video.py.
function zoomDaCamera(ev, cam){
  const numCam = Number(cam) || 1;
  const fonte = numCam <= 1 ? ev : ((ev.zoom_por_camera || {})[numCam] || (ev.zoom_por_camera || {})[String(numCam)] || {});
  return {
    zoom: Number.isFinite(Number(fonte.zoom)) ? Number(fonte.zoom) : 1,
    zoom_x: Number.isFinite(Number(fonte.zoom_x)) ? Number(fonte.zoom_x) : 0.5,
    zoom_y: Number.isFinite(Number(fonte.zoom_y)) ? Number(fonte.zoom_y) : 0.5,
  };
}
function definirZoomDaCamera(ev, cam, zoom, zoom_x, zoom_y){
  const numCam = Number(cam) || 1;
  if(numCam <= 1){ ev.zoom = zoom; ev.zoom_x = zoom_x; ev.zoom_y = zoom_y; return; }
  ev.zoom_por_camera = ev.zoom_por_camera || {};
  ev.zoom_por_camera[numCam] = { zoom, zoom_x, zoom_y };
}

function renderModalCameras(c){
  const box = $('#modalCameraBotoes'), st = $('#modalCameraStatus'), v = $('#modalVideo');
  if(!box) return;
  const atual = cameraVerValida();
  box.innerHTML = '';
  st.textContent = '';
  [1,2,3].forEach(n => {
    const ok = camerasCarregadas().includes(n);
    const b = document.createElement('button');
    b.type = 'button'; b.className = n === atual ? 'act' : 'ghost';
    b.style.cssText = 'font-size:12px; padding:4px 10px';
    b.disabled = !ok;
    b.textContent = `Câmera ${n}${n === 1 ? ' · principal' : ''}`;
    if(!ok) b.title = 'Câmera não enviada no passo 1';
    b.onclick = () => {
      if(n === cameraVerValida()) return;
      const tempo = v.currentTime || 0, tocando = !v.paused;
      definirCameraVer(n);
      renderCameraVer();
      const url = urlClipeDaCamera(c.indice, n) || c.url;
      st.textContent = n > 1 ? `carregando a câmera ${n}…` : '';
      v.onloadedmetadata = () => { try { v.currentTime = Math.min(tempo, v.duration || tempo); } catch(e) {} };
      v.onloadeddata = () => { st.textContent = ''; if(tocando) v.play().catch(()=>{}); };
      v.onerror = () => { st.textContent = `não consegui carregar a câmera ${n} neste clipe`; };
      v.src = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
      v.load();
      box.querySelectorAll('button').forEach((x, i) => x.className = (i + 1) === n ? 'act' : 'ghost');
      configurarZoomModal(c, n);
    };
    box.appendChild(b);
  });
}

function configurarZoomModal(c, cam){
  const v = $('#modalVideo');
  const zoomInput = $('#modalZoomClipe');
  const zoomValor = $('#modalZoomClipeValor');
  const zoomReset = $('#btnModalZoomReset');
  const zoomArea = $('#modalZoomArea');
  const zoomViewport = $('#modalVideoViewport');
  const estado = zoomDaCamera(c, cam);
  const aplicarZoomClipe = (valor) => {
    const zoom = Math.max(1, Math.min(2.2, Number(valor) || 1));
    const focoX = Math.max(0, Math.min(1, Number(estado.zoom_x)));
    const focoY = Math.max(0, Math.min(1, Number(estado.zoom_y)));
    const tamanho = 100 / zoom;
    // O vídeo fica sem transformação para o quadro indicar a área de origem com precisão.
    if(v) v.style.transform = 'scale(1)';
    estado.zoom = zoom;
    if(zoomValor) zoomValor.textContent = `${Math.round(zoom * 100)}%`;
    if(zoomArea){
      zoomArea.style.display = zoom > 1.01 ? 'block' : 'none';
      zoomArea.style.width = `${tamanho}%`;
      zoomArea.style.height = `${tamanho}%`;
      zoomArea.style.left = `${focoX * (100 - tamanho)}%`;
      zoomArea.style.top = `${focoY * (100 - tamanho)}%`;
    }
    return zoom;
  };
  const salvarZoomClipe = async (valor, focoX = estado.zoom_x, focoY = estado.zoom_y) => {
    const zoom = aplicarZoomClipe(valor);
    estado.zoom_x = Math.max(0, Math.min(1, Number.isFinite(Number(focoX)) ? Number(focoX) : 0.5));
    estado.zoom_y = Math.max(0, Math.min(1, Number.isFinite(Number(focoY)) ? Number(focoY) : 0.5));
    definirZoomDaCamera(c, cam, zoom, estado.zoom_x, estado.zoom_y);
    const estadoClipe = (ESTADO.gols || []).find(item => item.indice === c.indice);
    if(estadoClipe) definirZoomDaCamera(estadoClipe, cam, zoom, estado.zoom_x, estado.zoom_y);
    try {
      await fetch('/api/gols/zoom', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ indice: c.indice, zoom, zoom_x: estado.zoom_x, zoom_y: estado.zoom_y, camera: cam })
      });
    } catch(err) {
      console.warn('Não foi possível salvar o zoom do clipe', err);
    }
  };
  if(zoomInput){
    zoomInput.value = String(Math.round(estado.zoom * 100));
    aplicarZoomClipe(estado.zoom);
    zoomInput.oninput = () => aplicarZoomClipe(Number(zoomInput.value) / 100);
    zoomInput.onchange = () => salvarZoomClipe(Number(zoomInput.value) / 100);
  }
  if(zoomReset){
    zoomReset.onclick = () => {
      if(zoomInput) zoomInput.value = '100';
      salvarZoomClipe(1);
    };
  }
  if(zoomArea && zoomViewport){
    zoomArea.onpointerdown = (event) => {
      if(estado.zoom <= 1.01) return;
      event.preventDefault();
      zoomArea.setPointerCapture(event.pointerId);
      zoomArea.style.cursor = 'grabbing';
      const mover = (moveEvent) => {
        const rect = zoomViewport.getBoundingClientRect();
        const zoom = estado.zoom;
        const largura = rect.width / zoom;
        const altura = rect.height / zoom;
        const limiteX = Math.max(1, rect.width - largura);
        const limiteY = Math.max(1, rect.height - altura);
        estado.zoom_x = Math.max(0, Math.min(1, (moveEvent.clientX - rect.left - largura / 2) / limiteX));
        estado.zoom_y = Math.max(0, Math.min(1, (moveEvent.clientY - rect.top - altura / 2) / limiteY));
        aplicarZoomClipe(zoom);
      };
      const soltar = () => {
        zoomArea.style.cursor = 'grab';
        salvarZoomClipe(estado.zoom);
        window.removeEventListener('pointermove', mover);
        window.removeEventListener('pointerup', soltar);
      };
      window.addEventListener('pointermove', mover);
      window.addEventListener('pointerup', soltar, {once:true});
    };
  }
}

function abrirModalClipe(c){
  const vc = $('#videoCompleto');
  if(vc && !vc.paused) vc.pause();
  $('#modalTitulo').textContent = `Clipe #${String(c.indice).padStart(2,'0')}` + (c.tempo?` · ${c.tempo}`:'');
  const v = $('#modalVideo');
  const urlModal = urlClipeDaCamera(c.indice, cameraVerValida()) || c.url;
  v.src = urlModal + (urlModal.includes('?') ? '&' : '?') + 't=' + Date.now();
  v.onloadedmetadata = v.onloadeddata = v.onerror = null;
  renderModalCameras(c);
  $('#modalClipe').hidden = false;
  aplicarFiltroBrilho();
  v.play().catch(()=>{});

  // O quadro marca o recorte que será ampliado no vídeo final; cada câmera tem o seu.
  configurarZoomModal(c, cameraVerValida());

  const idx = clipesAtuais.findIndex(x => x.indice === c.indice);
  const temAnterior = idx > 0;
  const temProximo = idx >= 0 && idx < clipesAtuais.length - 1;
  const btnAnt = $('#modalBtnAnterior'), btnProx = $('#modalBtnProximo');
  const setaEsq = $('#modalSetaEsq'), setaDir = $('#modalSetaDir');
  if(btnAnt) btnAnt.disabled = !temAnterior;
  if(btnProx) btnProx.disabled = !temProximo;
  if(setaEsq) setaEsq.disabled = !temAnterior;
  if(setaDir) setaDir.disabled = !temProximo;

  const navegarAnt = () => {
    irAnteriorClipe(c.indice);
  };
  const navegarProx = () => {
    irProximoClipe(c.indice);
  };
  if(btnAnt) btnAnt.onclick = navegarAnt;
  if(setaEsq) setaEsq.onclick = navegarAnt;
  if(btnProx) btnProx.onclick = navegarProx;
  if(setaDir) setaDir.onclick = navegarProx;

  const badge = $('#modalStatusBadge');
  const infoAtual = obterInfoTipo(c.status, c.lance);
  if(badge){
    if(infoAtual){
      badge.style.background = infoAtual.bg;
      badge.style.border = '1px solid ' + infoAtual.border;
      badge.style.color = infoAtual.cor;
      badge.innerHTML = `${infoAtual.icon} Marcado como ${infoAtual.rotulo.toUpperCase()}`;
    } else {
      badge.style.background = 'var(--panel2)';
      badge.style.border = '1px solid var(--line)';
      badge.style.color = 'var(--dim)';
      badge.innerHTML = '⏳ Sem marcação';
    }
  }

  // Configuração do Painel de Ajuste de Corte (-15s / +15s / gerar novo clipe)
  const tempoClipeS = (c.tempo_s != null) ? Number(c.tempo_s) : (c.inicio_s != null ? Number(c.inicio_s) + 20 : 0);
  const inicioOriginal = (c.inicio_s != null) ? Number(c.inicio_s) : Math.max(0, tempoClipeS - 20);
  let fimOriginal = (c.fim_s != null) ? Number(c.fim_s) : (tempoClipeS + 4);
  if(fimOriginal <= inicioOriginal) fimOriginal = inicioOriginal + 24;
  const durOrig = Math.round(fimOriginal - inicioOriginal);

  let modalOffsetSec = 0;
  let modoPreviewVideo = false;

  const infoTrechoEl = $('#modalInfoTrechoJogo');
  if(infoTrechoEl){
    infoTrechoEl.textContent = `${fmtTempo(inicioOriginal)} até ${fmtTempo(fimOriginal)} (${durOrig}s)`;
  }

  const logAjuste = $('#modalAjusteLog');
  if(logAjuste){
    logAjuste.style.display = 'none';
    logAjuste.innerHTML = '';
  }

  const btnPreview = $('#btnModalPreviewVideo');
  const btnVoltarClipe = $('#btnModalVoltarClipe');
  if(btnPreview) btnPreview.style.display = 'inline-block';
  if(btnVoltarClipe) btnVoltarClipe.style.display = 'none';

  function atualizarAjusteCorte(){
    const novoInicio = Math.max(0, Math.round((inicioOriginal + modalOffsetSec) * 100) / 100);
    const novoFim = Math.max(novoInicio + 3, Math.round((fimOriginal + modalOffsetSec) * 100) / 100);
    const dur = Math.round(novoFim - novoInicio);

    const inpIni = $('#modalInpInicio');
    const inpFim = $('#modalInpFim');
    const durEl = $('#modalDuracaoAjustada');
    const badge = $('#modalBadgeOffset');

    if(inpIni) inpIni.value = fmtTempo(novoInicio);
    if(inpFim) inpFim.value = fmtTempo(novoFim);
    if(durEl) durEl.textContent = `(${dur}s)`;

    if(badge){
      if(modalOffsetSec === 0){
        badge.textContent = 'Sem deslocamento (0s)';
        badge.style.background = 'var(--line)';
        badge.style.color = 'var(--txt)';
      } else if(modalOffsetSec < 0){
        badge.textContent = `Deslocamento: ${modalOffsetSec}s (mais pra trás)`;
        badge.style.background = '#0369a1';
        badge.style.color = '#e0f2fe';
      } else {
        badge.textContent = `Deslocamento: +${modalOffsetSec}s (pra frente)`;
        badge.style.background = '#b45309';
        badge.style.color = '#fef3c7';
      }
    }

    if(modoPreviewVideo){
      const v = $('#modalVideo');
      v.currentTime = Math.max(0, novoInicio - offsetCameraS(cameraVerValida()));
      v.play().catch(()=>{});
    }
  }

  atualizarAjusteCorte();

  const bVoltar15 = $('#btnModalVoltar15s');
  if(bVoltar15) bVoltar15.onclick = () => { modalOffsetSec -= 15; atualizarAjusteCorte(); };
  const bVoltar5 = $('#btnModalVoltar5s');
  if(bVoltar5) bVoltar5.onclick = () => { modalOffsetSec -= 5; atualizarAjusteCorte(); };
  const bRest = $('#btnModalRestaurar');
  if(bRest) bRest.onclick = () => { modalOffsetSec = 0; atualizarAjusteCorte(); };
  const bAvancar5 = $('#btnModalAvancar5s');
  if(bAvancar5) bAvancar5.onclick = () => { modalOffsetSec += 5; atualizarAjusteCorte(); };
  const bAvancar15 = $('#btnModalAvancar15s');
  if(bAvancar15) bAvancar15.onclick = () => { modalOffsetSec += 15; atualizarAjusteCorte(); };

  const inpIniEl = $('#modalInpInicio');
  if(inpIniEl){
    inpIniEl.onchange = () => {
      const t = parseTempo(inpIniEl.value);
      if(t != null && !isNaN(t) && t >= 0){
        modalOffsetSec = Math.round(t - inicioOriginal);
        atualizarAjusteCorte();
      }
    };
  }

  const inpFimEl = $('#modalInpFim');
  if(inpFimEl){
    inpFimEl.onchange = () => {
      const t = parseTempo(inpFimEl.value);
      if(t != null && !isNaN(t) && t > 0){
        const novoIni = Math.max(0, inicioOriginal + modalOffsetSec);
        if(t > novoIni){
          fimOriginal = t - modalOffsetSec;
          atualizarAjusteCorte();
        }
      }
    };
  }

  async function dispararCorteModal(novoIni, novoFim, motivoDesc){
    const logEl = $('#modalAjusteLog');
    const btnCorte = $('#btnModalCortarNovo');
    const btnMaisTras = $('#btnModalGerarClipeMaisTras');
    if(btnCorte) btnCorte.disabled = true;
    if(btnMaisTras) btnMaisTras.disabled = true;

    logEl.style.display = 'block';
    logEl.innerHTML = `<span class="spinner"></span> Cortando clipe ${motivoDesc} (${fmtTempo(novoIni)} até ${fmtTempo(novoFim)})...`;

    try {
      const infoTipo = obterInfoTipo(c.status, c.lance);
      const status = c.status || 'gol';
      const lanceNome = (infoTipo && !infoTipo.isGol) ? infoTipo.lanceNome : (c.lance || null);
      const videoCaminho = (ESTADO.video && ESTADO.video.caminho) ? ESTADO.video.caminho : null;

      const r = await fetch('/api/gols/adicionar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          video: videoCaminho,
          inicio_s: novoIni,
          fim_s: novoFim,
          tempo_s: Math.max(0, novoIni + 20),
          status: status,
          lance: lanceNome
        })
      });
      const res = await r.json();
      if(!r.ok){
        logEl.innerHTML = `<span class="bad">Erro ao cortar: ${res.detail || 'falha no servidor'}</span>`;
        return;
      }
      logEl.innerHTML = `<span class="ok">✓ Clipe #${String(res.indice).padStart(2,'0')} gerado com sucesso! Abrindo...</span>`;
      await carregarClipes();
      const novoClipe = clipesAtuais.find(x => x.indice === res.indice);
      mostrarAlertaClipePronto({
        indice: res.indice,
        inicio_s: novoIni,
        fim_s: novoFim,
        dur: (novoFim - novoIni),
        tipo: status,
        infoTipo: infoTipo,
        clipe: novoClipe
      });
      if(novoClipe){
        setTimeout(() => {
          abrirModalClipe(novoClipe);
        }, 600);
      }
    } catch(err) {
      logEl.innerHTML = `<span class="bad">Erro ao comunicar: ${err}</span>`;
    } finally {
      if(btnCorte) btnCorte.disabled = false;
      if(btnMaisTras) btnMaisTras.disabled = false;
    }
  }

  const btnGerarMaisTras = $('#btnModalGerarClipeMaisTras');
  if(btnGerarMaisTras){
    btnGerarMaisTras.onclick = async () => {
      // Se ainda não estava deslocado para trás, usa -15s
      const offset = modalOffsetSec < 0 ? modalOffsetSec : -15;
      const novoInicio = Math.max(0, Math.round((inicioOriginal + offset) * 100) / 100);
      const novoFim = Math.max(novoInicio + 5, Math.round((fimOriginal + offset) * 100) / 100);
      await dispararCorteModal(novoInicio, novoFim, '15s mais pra trás');
    };
  }

  const btnCortarNovo = $('#btnModalCortarNovo');
  if(btnCortarNovo){
    btnCortarNovo.onclick = async () => {
      const tIni = parseTempo($('#modalInpInicio').value);
      const tFim = parseTempo($('#modalInpFim').value);
      if(tIni == null || tFim == null || tFim <= tIni){
        alert('Informe um trecho válido (início menor que o fim).');
        return;
      }
      const motivo = modalOffsetSec !== 0 ? `(${modalOffsetSec > 0 ? '+' : ''}${modalOffsetSec}s)` : 'ajustado';
      await dispararCorteModal(tIni, tFim, motivo);
    };
  }

  if(btnPreview){
    btnPreview.onclick = () => {
      modoPreviewVideo = true;
      const camPrev = cameraVerValida();
      const novoInicio = Math.max(0, Math.round((inicioOriginal + modalOffsetSec) * 100) / 100);

      const v = $('#modalVideo');
      v.src = urlVideoCompleto(camPrev);
      v.currentTime = Math.max(0, novoInicio - offsetCameraS(camPrev));
      v.play().catch(()=>{});

      btnPreview.style.display = 'none';
      if(btnVoltarClipe) btnVoltarClipe.style.display = 'inline-block';
      $('#modalTitulo').textContent = `Vídeo do Jogo · a partir de ${fmtTempo(novoInicio)} (conferindo jogada)`;
    };
  }

  if(btnVoltarClipe){
    btnVoltarClipe.onclick = () => {
      modoPreviewVideo = false;
      const v = $('#modalVideo');
      const urlVolta = urlClipeDaCamera(c.indice, cameraVerValida()) || c.url;
      v.src = urlVolta + (urlVolta.includes('?') ? '&' : '?') + 't=' + Date.now();
      v.play().catch(()=>{});

      if(btnPreview) btnPreview.style.display = 'inline-block';
      btnVoltarClipe.style.display = 'none';
      $('#modalTitulo').textContent = `Clipe #${String(c.indice).padStart(2,'0')}` + (c.tempo ? ` · ${c.tempo}` : '');
    };
  }

  // ------------------------- Lógica de Classificação rápida no Modal (Tela de Revisão)
  let gItem = (ESTADO.gols || []).find(x => x.indice === c.indice);
  const statusAtual = c.status || (gItem && (gItem.status || gItem.tipo)) || null;
  const lanceAtual = c.lance || (gItem && gItem.lance) || null;

  function modalAtualizarBadge(status, lance){
    const badge = $('#modalStatusBadge');
    if(!badge) return;
    const inf = obterInfoTipo(status, lance);
    if(inf){
      badge.style.background = inf.bg;
      badge.style.border = '1px solid ' + inf.border;
      badge.style.color = inf.cor;
      badge.innerHTML = `${inf.icon} Marcado como ${inf.rotulo.toUpperCase()}`;
    } else {
      badge.style.background = 'var(--panel2)';
      badge.style.border = '1px solid var(--line)';
      badge.style.color = 'var(--dim)';
      badge.innerHTML = '⏳ Sem marcação';
    }
  }

  async function classificarEAvancar(tipo){
    const isGol = tipo.isGol;
    const statusFinal = tipo.id;
    const lanceFinal = isGol ? null : tipo.lanceNome;

    c.status = statusFinal;
    c.lance = lanceFinal;

    let g = (ESTADO.gols || []).find(x => x.indice === c.indice);
    if(!g){
      g = {
        indice: c.indice,
        tempo: c.tempo || '',
        tempo_s: c.tempo_s,
        inicio_s: c.inicio_s,
        fim_s: c.fim_s,
        fonte: 'revisado',
        descartado: false
      };
      if(!ESTADO.gols) ESTADO.gols = [];
      ESTADO.gols.push(g);
      ESTADO.gols.sort((a,b) => a.indice - b.indice);
    }
    g.tipo = isGol ? 'gol' : 'lance';
    g.status = statusFinal;
    g.lance = lanceFinal;
    g.descartado = false;

    try {
      await fetch('/api/gols/confirmar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          indice: c.indice,
          status: statusFinal,
          lance: lanceFinal
        })
      });
    } catch(err){}

    agendarSalvar();
    renderGradeClipes(clipesAtuais);

    // Ao clicar em gol ou outro lance, já vai para o próximo clipe
    irProximoClipe(c.indice);
  }

  function modalRenderBotoesTipo(){
    const container = $('#modalBotoesTipo');
    if(!container) return;
    container.innerHTML = '';

    const infoSel = obterInfoTipo(c.status, c.lance);
    const idSel = infoSel ? infoSel.id : (c.status === 'gol' ? 'gol' : null);

    TIPOS_CLIPE.forEach(tipo => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btnTipoClipe';
      btn.dataset.tipoId = tipo.id;
      const isSel = Boolean(idSel && ((idSel === tipo.id) || (tipo.isGol && c.status === 'gol') || (!tipo.isGol && c.status !== 'gol' && (c.status || c.lance))));
      if(isSel){
        btn.classList.add('sel');
        btn.style.background = tipo.bg;
        btn.style.borderColor = tipo.border;
        btn.style.color = tipo.cor;
      }
      btn.style.padding = '6px 14px';
      btn.style.fontSize = '12px';
      btn.style.fontWeight = isSel ? '700' : '600';
      btn.innerHTML = `<span style="font-size:14px">${tipo.icon}</span> <span>${tipo.rotulo}</span>`;
      btn.title = `Classificar como ${tipo.rotulo} e avançar para o próximo (tecla ${tipo.hotkey.toUpperCase()})`;
      btn.onclick = () => {
        classificarEAvancar(tipo);
      };
      container.appendChild(btn);
    });
  }

  modalAtualizarBadge(statusAtual, lanceAtual);
  modalRenderBotoesTipo();

  const btnLimpar = $('#modalLimparStatus');
  if(btnLimpar){
    btnLimpar.onclick = async () => {
      c.status = null;
      c.lance = null;

      let g = (ESTADO.gols || []).find(x => x.indice === c.indice);
      if(g){
        g.status = null;
        g.tipo = 'gol';
        g.lance = null;
      }

      try {
        await fetch('/api/gols/confirmar', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            indice: c.indice,
            status: null
          })
        });
      } catch(err){}

      agendarSalvar();
      renderGradeClipes(clipesAtuais);
      modalAtualizarBadge(null, null);
      modalRenderBotoesTipo();
    };
  }

  $('#modalDescartar').onclick = async ()=>{
    if(_descartandoClipe) return;
    if(!confirm(`ATENÇÃO: Deseja EXCLUIR DEFINITIVAMENTE o clipe selecionado #${String(c.indice).padStart(2,'0')} (${c.tempo||''}) do computador?\n\nO arquivo de vídeo será apagado e o lance será removido.`)) return;
    await descartarClipe(c.indice);
  };
}
function irAnteriorClipe(indiceAtual){
  const idx = clipesAtuais.findIndex(x => x.indice === indiceAtual);
  if(idx > 0) abrirModalClipe(clipesAtuais[idx - 1]);
}
function irProximoClipe(indiceAtual){
  const idx = clipesAtuais.findIndex(x => x.indice === indiceAtual);
  if(idx >= 0 && idx < clipesAtuais.length - 1){
    abrirModalClipe(clipesAtuais[idx + 1]);
  } else if(idx === -1 && clipesAtuais.length > 0){
    abrirModalClipe(clipesAtuais[0]);
  } else {
    fecharModalClipe();
  }
}
function fecharModalClipe(){
  const v = $('#modalVideo');
  v.pause(); v.removeAttribute('src'); v.load();
  $('#modalClipe').hidden = true;
  const btnPrev = $('#btnModalPreviewVideo');
  const btnVolt = $('#btnModalVoltarClipe');
  if(btnPrev) btnPrev.style.display = 'inline-block';
  if(btnVolt) btnVolt.style.display = 'none';
}
$('#modalFechar').onclick = fecharModalClipe;
$('#modalClipe').addEventListener('click', (e)=>{ if(e.target.id==='modalClipe') fecharModalClipe(); });
const modalRenderEl = document.getElementById('modalRenderConcluido');
if(modalRenderEl) modalRenderEl.addEventListener('click', (e)=>{ if(e.target.id==='modalRenderConcluido') fecharModalRender(); });

document.addEventListener('keydown', (e)=>{
  const mRender = document.getElementById('modalRenderConcluido');
  if(mRender && !mRender.hidden){
    if(e.key === 'Escape'){ fecharModalRender(); return; }
  }
  if(!$('#modalClipe').hidden){
    if(e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'){
      if(e.key === 'Escape') fecharModalClipe();
      return;
    }
    const k = e.key.toLowerCase();
    if(e.key==='Escape') fecharModalClipe();
    else if(e.key==='ArrowLeft'){ e.preventDefault(); $('#modalBtnAnterior').click(); }
    else if(e.key==='ArrowRight' || e.key==='Enter'){ e.preventDefault(); $('#modalBtnProximo').click(); }
    else if(e.key==='Delete' || (e.ctrlKey && e.key==='Backspace')){ e.preventDefault(); $('#modalDescartar').click(); }
    else {
      let match = TIPOS_CLIPE.find(t => t.hotkey === k);
      if(!match && (k === 'l' || k === 'o')){
        match = TIPOS_CLIPE.find(t => t.id === 'lance');
      }
      if(match){
        const btn = [...$('#modalBotoesTipo').children].find(b => b.dataset.tipoId === match.id || b.textContent.includes(match.rotulo));
        if(btn) btn.click();
      }
    }
  }
});

/* ------------------------------------------------------------ passo 6: marcacao */
function configurarZoomMarcacao(g, cam = 1){
  const v = $('#vid');
  const viewport = $('#videoMarcacaoViewport');
  const area = $('#marcacaoZoomArea');
  const input = $('#marcacaoZoomClipe');
  const valorEl = $('#marcacaoZoomValor');
  const reset = $('#btnMarcacaoZoomReset');
  const clipe = clipesAtuais.find(item => item.indice === g.indice);
  // Sem marcação própria pra esta câmera ainda: herda uma vez o que já foi
  // marcado na listagem de clipes (c), pra não perder ajuste feito no passo 4.
  const jaTem = cam <= 1 ? (g.zoom != null) : Boolean((g.zoom_por_camera || {})[cam]);
  if(!jaTem && clipe){
    const doClipe = zoomDaCamera(clipe, cam);
    definirZoomDaCamera(g, cam, doClipe.zoom, doClipe.zoom_x, doClipe.zoom_y);
  }
  const estado = zoomDaCamera(g, cam);

  const desenhar = () => {
    const zoom = Math.max(1, Math.min(2.2, Number(estado.zoom) || 1));
    const x = Math.max(0, Math.min(1, Number(estado.zoom_x)));
    const y = Math.max(0, Math.min(1, Number(estado.zoom_y)));
    const tamanho = 100 / zoom;
    estado.zoom = zoom;
    if(input) input.value = String(Math.round(zoom * 100));
    if(valorEl) valorEl.textContent = `${Math.round(zoom * 100)}%`;
    if(area){
      area.style.display = zoom > 1.01 ? 'block' : 'none';
      area.style.width = `${tamanho}%`;
      area.style.height = `${tamanho}%`;
      area.style.left = `${x * (100 - tamanho)}%`;
      area.style.top = `${y * (100 - tamanho)}%`;
    }
  };
  const salvar = async () => {
    definirZoomDaCamera(g, cam, estado.zoom, estado.zoom_x, estado.zoom_y);
    if(clipe) definirZoomDaCamera(clipe, cam, estado.zoom, estado.zoom_x, estado.zoom_y);
    try {
      await fetch('/api/gols/zoom', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({indice:g.indice, zoom:estado.zoom, zoom_x:estado.zoom_x, zoom_y:estado.zoom_y, camera:cam})
      });
    } catch(err) { console.warn('Não foi possível salvar o zoom', err); }
  };
  desenhar();
  if(input){
    input.oninput = () => { estado.zoom = Number(input.value) / 100; desenhar(); };
    input.onchange = () => salvar();
  }
  if(reset) reset.onclick = () => { estado.zoom = 1; estado.zoom_x = 0.5; estado.zoom_y = 0.5; desenhar(); salvar(); };
  if(area && viewport){
    area.onpointerdown = (event) => {
      if(estado.zoom <= 1.01) return;
      event.preventDefault();
      area.setPointerCapture(event.pointerId);
      area.style.cursor = 'grabbing';
      const mover = (moveEvent) => {
        const rect = viewport.getBoundingClientRect();
        const largura = rect.width / estado.zoom, altura = rect.height / estado.zoom;
        estado.zoom_x = Math.max(0, Math.min(1, (moveEvent.clientX - rect.left - largura / 2) / Math.max(1, rect.width - largura)));
        estado.zoom_y = Math.max(0, Math.min(1, (moveEvent.clientY - rect.top - altura / 2) / Math.max(1, rect.height - altura)));
        desenhar();
      };
      const soltar = () => {
        area.style.cursor = 'grab'; salvar();
        window.removeEventListener('pointermove', mover);
        window.removeEventListener('pointerup', soltar);
      };
      window.addEventListener('pointermove', mover);
      window.addEventListener('pointerup', soltar, {once:true});
    };
  }
}

function renderMarcacao(){
  if(!ESTADO.gols.length){ $('#golnav').innerHTML='<span class="hint">Detecte e corte os gols nos passos 3/4 primeiro.</span>'; return; }
  $('#golnav').innerHTML='';

  if(ESTADO.indiceAtual == null && ESTADO.gols.length > 0){
    ESTADO.indiceAtual = ESTADO.gols[0].indice;
  }
  let g = ESTADO.gols.find(x => x.indice === ESTADO.indiceAtual);
  if(!g && ESTADO.gols.length > 0){
    g = ESTADO.gols[0];
    ESTADO.indiceAtual = g.indice;
  }
  if(!g) return;
  ESTADO.atual = ESTADO.gols.findIndex(x => x.indice === ESTADO.indiceAtual);

  ESTADO.gols.forEach((item, i)=>{
    const b = document.createElement('button');
    const inf = obterInfoTipo(item.status || item.tipo, item.lance);
    const temTipo = Boolean(inf || item.status || (item.tipo && item.tipo !== 'revisar'));
    const ehGol = inf ? inf.isGol : (item.tipo === 'gol');
    const ehDone = item.descartado ? false : (ehGol ? Boolean(item.autor && item.time !== null) : Boolean(temTipo));

    let classe = 'chip';
    if(item.descartado) classe += ' skip';
    else if(!temTipo) classe += ' pending-revisar';
    else if(ehDone) classe += (ehGol ? ' done' : ' lance');
    else if(ehGol) classe += ' pending-gol';
    else classe += ' pending-lance';
    if(item.indice === ESTADO.indiceAtual) classe += ' cur';

    b.className = classe;
    if(inf && inf.id === 'confusao' && !item.descartado){
      b.style.borderColor = inf.border;
      b.style.color = inf.cor;
      b.style.background = inf.bg;
    }
    const icone = item.descartado ? '🗑' : (inf ? inf.icon : (temTipo ? (ehGol ? '⚽' : '🎬') : '⏳'));
    const rotulo = String(item.indice).padStart(2,'0');
    let autorTexto = '';
    if(item.autor){
      const timeCor = (item.time !== null && S.times[item.time]) ? S.times[item.time].cor : 'var(--accent)';
      autorTexto = `<span style="font-size:10px; font-weight:700; color:${timeCor}; margin-left:3px">(${item.autor})</span>`;
    } else if(item.tipo === 'lance' && item.destaque){
      autorTexto = `<span style="font-size:10px; opacity:0.85; margin-left:3px">(${item.destaque})</span>`;
    }
    const segundosChip = obterTempoSegundosClipe(item);
    const tempoChip = item.tempo || (segundosChip !== -1 ? fmtTempo(segundosChip) : '');
    b.innerHTML = `<span>${icone} #${rotulo}</span>${autorTexto}<span class="chip-tempo">${tempoChip}</span>`;
    b.title = `Clipe #${item.indice} · ${inf ? inf.rotulo : (temTipo ? (ehGol ? 'Gol' : 'Lance') : 'Sem marcação')}` + (item.autor ? ` (${item.autor})` : '');
    b.onclick = ()=>{ ESTADO.indiceAtual = item.indice; renderMarcacao(); };
    $('#golnav').appendChild(b);
  });
  const infoAtual = obterInfoTipo(g.status || g.tipo, g.lance);
  const temTipoAtual = Boolean(infoAtual || g.status || (g.tipo && g.tipo !== 'revisar'));
  const ehGol = infoAtual ? infoAtual.isGol : (g.tipo === 'gol');

  const temTime = (g.time !== null && g.time !== undefined && S.times[g.time]);
  rascunho = {
    tipo: infoAtual ? (infoAtual.isGol ? 'gol' : 'lance') : (g.tipo || null),
    status: infoAtual ? infoAtual.id : (g.status || null),
    lance: ehGol ? null : (g.lance || (infoAtual ? infoAtual.lanceNome : null)),
    time: temTime ? g.time : null,
    autor: temTime ? g.autor : null,
    assist: temTime ? g.assist : null,
    destaque: temTime ? g.destaque : null
  };
  const camerasDisponiveis = [0,1,2].filter(i => Boolean(camerasSelecionadas()[i])).map(i => i + 1);
  // Câmeras marcadas para este clipe (só as que existem); sempre pelo menos a 1.
  let marcadas = (Array.isArray(g.cameras_clipe) && g.cameras_clipe.length ? g.cameras_clipe : [Number(g.camera) || 1])
    .map(Number).filter((c, k, a) => camerasDisponiveis.includes(c) && a.indexOf(c) === k);
  if(!marcadas.length) marcadas = [1];
  g.cameras_clipe = marcadas;
  g.camera = marcadas[0];
  let cameraVendo = camerasDisponiveis.includes(cameraVerValida()) ? cameraVerValida() : marcadas[0];
  const urlClipeCamera = (cam) => cam <= 1 ? null : `/video/clipes/${g.indice}/camera/${cam}`;
  const blocoCam = $('#blocoCameraClipe');
  const desenharCameras = () => {
    const pick = $('#pickCameraClipe');
    pick.innerHTML = '';
    [1, 2, 3].forEach(cam => {
      const enviada = camerasDisponiveis.includes(cam);
      const wrap = document.createElement('span');
      wrap.style.cssText = 'display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:8px; border:1px solid ' + (cam === cameraVendo ? 'var(--accent)' : 'var(--line)') + '; background:var(--panel2)' + (enviada ? '' : '; opacity:.55');
      if(!enviada) wrap.title = 'Câmera ' + cam + ' não enviada. Envie o vídeo dela no passo 1 (Vídeo) para poder usar aqui.';
      const lab = document.createElement('label');
      lab.style.cssText = 'display:inline-flex; align-items:center; gap:5px; margin:0; font-size:12px; font-weight:700; cursor:pointer';
      const chk = document.createElement('input');
      chk.type = 'checkbox'; chk.checked = enviada && marcadas.includes(cam); chk.style.width = 'auto'; chk.disabled = !enviada;
      chk.onchange = () => {
        if(chk.checked) marcadas = [...marcadas, cam];
        else if(marcadas.length > 1) marcadas = marcadas.filter(c => c !== cam);
        else { chk.checked = true; return; }   // ao menos uma câmera
        g.camera_manual = true;   // escolha do usuário vale mais que a câmera de ataque do time
        marcadas.sort((x, y) => x - y);
        g.cameras_clipe = marcadas; g.camera = marcadas[0];
        agendarSalvar();
        desenharCameras();
      };
      lab.appendChild(chk);
      lab.appendChild(document.createTextNode(`Câmera ${cam}${cam === 1 ? ' · principal' : ''}${enviada ? '' : ' · não enviada'}`));
      const ver = document.createElement('button');
      ver.type = 'button'; ver.className = cam === cameraVendo ? 'act' : 'ghost';
      ver.style.cssText = 'font-size:11px; padding:3px 9px';
      ver.disabled = !enviada;
      ver.textContent = cam === cameraVendo ? '▶ Vendo' : 'Ver';
      ver.onclick = () => { cameraVendo = cam; definirCameraVer(cam); trocarVideoCamera(cam); desenharCameras(); configurarZoomMarcacao(g, cameraVendo); };
      wrap.appendChild(lab); wrap.appendChild(ver);
      pick.appendChild(wrap);
    });
  };
  function trocarVideoCamera(cam){
    const vv = $('#vid'); const st = $('#statusCameraClipe');
    const alvo = urlClipeCamera(cam) || ESTADO.clipes[String(g.indice).padStart(2,'0')];
    if(!alvo) return;
    if(st) st.textContent = cam > 1 ? 'carregando a câmera ' + cam + '…' : '';
    vv.onloadeddata = () => { if(st) st.textContent = ''; vv.play().catch(()=>{}); };
    vv.onerror = () => { if(st) st.textContent = 'não consegui carregar a câmera ' + cam; };
    vv.src = alvo; vv.load();
  }
  if(blocoCam){
    // Sempre visível: as câmeras ainda não enviadas aparecem desabilitadas.
    blocoCam.style.display = 'flex';
    desenharCameras();
  }
  _aplicarCameraMarcacao = () => {
    if(g.camera_manual) return;   // escolha manual do usuário vale mais
    const cam = cameraAutomaticaDoRascunho();
    if(!cam || !camerasDisponiveis.includes(cam)) return;
    if(g.cameras_clipe.length === 1 && g.cameras_clipe[0] === cam && cameraVendo === cam) return;
    marcadas = [cam]; g.cameras_clipe = [cam]; g.camera = cam;
    cameraVendo = cam;
    agendarSalvar();
    desenharCameras();
    trocarVideoCamera(cam);
    const st = $('#statusCameraClipe');
    if(st) st.textContent = `câmera ${cam} escolhida pelo time (câmera de ataque da tela 5)`;
  };

  const url = ESTADO.clipes[String(g.indice).padStart(2,'0')];
  // Lista de clipes ausente/desatualizada (página aberta antes do servidor responder ou
  // reiniciar): recarrega uma vez e redesenha em vez de afirmar que o clipe não existe.
  if(!url && !_recarregandoClipes){
    _recarregandoClipes = true;
    carregarClipes().catch(()=>{}).finally(()=>{
      _recarregandoClipes = false;
      if(ESTADO.clipes[String(g.indice).padStart(2,'0')] && typeof renderMarcacao === 'function') renderMarcacao();
    });
  }
  const v = $('#vid');
  if(url){
    if(cameraVendo > 1) trocarVideoCamera(cameraVendo);
    else { v.onloadeddata = null; v.onerror = null; v.src=url; v.load(); }
  } else { v.removeAttribute('src'); v.load(); }
  if(typeof aplicarFiltroBrilho === 'function') aplicarFiltroBrilho();
  configurarZoomMarcacao(g, cameraVendo);

  const placarBadgeHtml = g.placar
    ? `<span style="background:var(--panel2); border:1px solid var(--line); font-family:ui-monospace,monospace; font-weight:700; font-size:12px; padding:3px 8px; border-radius:5px; margin-left:8px">Placar: ${g.placar}</span>`
    : '';

  const badgeHtml = infoAtual
    ? `<span style="background:${infoAtual.bg}; border:1px solid ${infoAtual.border}; color:${infoAtual.cor}; font-weight:700; font-size:12px; padding:3px 8px; border-radius:5px; margin-left:8px">${infoAtual.icon} Marcado como ${infoAtual.rotulo.toUpperCase()}</span>`
    : `<span style="background:var(--panel2); border:1px solid var(--line); color:var(--dim); font-size:12px; padding:3px 8px; border-radius:5px; margin-left:8px">⏳ Sem marcação</span>`;

  $('#lblGol').innerHTML = `Clipe #${String(g.indice).padStart(2,'0')} · <b>${g.tempo}</b> ${placarBadgeHtml} ${badgeHtml}` + (url?'':(_recarregandoClipes?' — <span class="hint">carregando clipes…</span>':' — <span class="bad">clipe não encontrado</span>'));

  pickTipos();
  pickTimes();
  pickJogadores();
  pickLances();
  pickTimesLance();
  pickDestaqueLance();
  andamento();
}

function pickTipos(){
  const el = $('#pickTipo');
  if(!el) return;
  el.innerHTML = '';

  const infoAtual = obterInfoTipo(rascunho.status || rascunho.tipo, rascunho.lance);
  const idAtual = infoAtual ? infoAtual.id : (rascunho.tipo === 'gol' ? 'gol' : (rascunho.tipo === 'lance' ? 'lance' : null));

  TIPOS_CLIPE.forEach(tipo => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btnTipoClipe';
    const isSel = Boolean(idAtual && ((idAtual === tipo.id) || (tipo.isGol && rascunho.tipo === 'gol') || (!tipo.isGol && rascunho.status === tipo.id)));
    if(isSel){
      b.classList.add('sel');
      b.style.background = tipo.bg;
      b.style.borderColor = tipo.border;
      b.style.color = tipo.cor;
    }
    b.innerHTML = `<span>${tipo.icon}</span> <span>${tipo.rotulo}</span>`;
    b.title = `Classificar como ${tipo.rotulo} (tecla ${tipo.hotkey.toUpperCase()})`;
    b.onclick = () => {
      selecionarTipoMarcacao(tipo);
    };
    el.appendChild(b);
  });

  alternarCampos();
}

/* ------------------------------------------------------------ câmera automática pelo time (tela 6) */
// Câmera que o time ataca (configurada na tela 5). Gol, quase gol e chute na trave usam a do time
// marcado; defesaça usa a do time adversário (a jogada acontece no campo de defesa).
function cameraAutomaticaDoRascunho(){
  const t = rascunho.time;
  if(t === null || t === undefined || !S.times[t]) return 0;
  const outro = S.times[1 - t];
  const nome = String(rascunho.lance || '').toLowerCase();
  const status = String(rascunho.status || '').toLowerCase();
  const ehTipo = (...chaves) => chaves.some(c => nome.includes(c) || status.includes(c));
  if(rascunho.tipo === 'gol') return Number(S.times[t].camera_ataque) || 0;
  if(rascunho.tipo !== 'lance') return 0;
  if(ehTipo('quase', 'trave')) return Number(S.times[t].camera_ataque) || 0;
  if(ehTipo('defesa')) return outro ? Number(outro.camera_ataque) || 0 : 0;
  return 0;
}
let _aplicarCameraMarcacao = null;   // definido por renderMarcacao para o clipe aberto
function aplicarCameraAutomatica(){ if(_aplicarCameraMarcacao) _aplicarCameraMarcacao(); }

function selecionarTipoMarcacao(tipo){
  if(tipo.isGol){
    rascunho.tipo = 'gol';
    rascunho.status = 'gol';
    rascunho.lance = null;
  } else {
    rascunho.tipo = 'lance';
    rascunho.status = tipo.id;
    rascunho.lance = tipo.lanceNome;
  }
  pickTipos();
  alternarCampos();
  pickTimes();
  pickJogadores();
  pickLances();
  pickTimesLance();
  pickDestaqueLance();
  andamento();
  aplicarCameraAutomatica();
}

function alternarCampos(){
  const ehGol = rascunho.tipo === 'gol';
  const ehLance = rascunho.tipo === 'lance';
  $('#camposGol').style.display = ehGol ? '' : 'none';
  $('#camposLance').style.display = ehLance ? '' : 'none';
}

function pickLances(){
  const el = $('#pickLance');
  if(!el) return;
  el.innerHTML = '';
  TIPOS_LANCE.forEach(n => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = n;
    b.className = rascunho.lance === n ? 'sel' : '';
    b.onclick = () => {
      rascunho.lance = rascunho.lance === n ? null : n;
      const inf = obterInfoTipo(null, rascunho.lance);
      if(inf){
        rascunho.status = inf.id;
      }
      pickTipos();
      pickLances();
      aplicarCameraAutomatica();
    };
    el.appendChild(b);
  });
}
function pickTimesLance(){
  const el=$('#pickTimeLance');
  if(!el) return;
  el.innerHTML='';
  S.times.forEach((t,i)=>{
    const b=document.createElement('button'); b.type='button'; b.textContent=t.nome;
    const isSel = rascunho.time===i;
    b.className = isSel ? 'sel' : '';
    const txtCor = corTextoParaFundo(t.cor);
    b.style.borderLeft = '6px solid ' + t.cor;
    if(isSel){
      b.style.background = t.cor;
      b.style.borderColor = t.cor;
      b.style.color = txtCor;
      b.style.fontWeight = '700';
    } else {
      b.style.background = 'var(--panel2)';
      b.style.color = 'var(--txt)';
    }
    b.onclick=()=>{
      rascunho.time = (rascunho.time===i) ? null : i;
      pickTimesLance();
      pickDestaqueLance();
      aplicarCameraAutomatica();
    };
    el.appendChild(b);
  });
  const bNenhum = document.createElement('button'); bNenhum.type='button';
  bNenhum.textContent = 'Sem time / neutro';
  const isNeutro = (rascunho.time===null || rascunho.time===undefined);
  bNenhum.className = isNeutro ? 'sel' : '';
  bNenhum.onclick = ()=>{
    rascunho.time = null;
    pickTimesLance();
    pickDestaqueLance();
  };
  el.appendChild(bNenhum);
}

function pickDestaqueLance(){
  const ed=$('#pickDestaque');
  if(!ed) return;
  ed.innerHTML='';

  if(rascunho.time===null || rascunho.time===undefined || !S.times[rascunho.time]){
    rascunho.destaque = null;
    ed.innerHTML='<span class="hint" style="margin:0; padding:4px 0; color:var(--dim)">Selecione o time da jogada acima para ver o elenco.</span>';
    return;
  }
  let jogadores = S.times[rascunho.time].jogadores || [];

  if(jogadores.length > 0){
    const wrapBotoes = document.createElement('div');
    wrapBotoes.className = 'pick';
    wrapBotoes.style.marginBottom = '6px';
    jogadores.forEach(nome => {
      const b = document.createElement('button');
      b.type = 'button';
      const pos = obterPosicaoJogador(rascunho.time, nome);
      const pInfo = POSICOES_JOGADORES.find(p => p.id === pos) || { sigla: 'MEI' };
      b.innerHTML = `${nome} <span style="font-size:10px; opacity:0.75; font-weight:700; margin-left:3px">[${pInfo.sigla}]</span>`;
      const isSel = rascunho.destaque === nome;
      b.className = isSel ? 'sel' : '';
      b.onclick = () => {
        if(isSel){
          rascunho.destaque = null;
        } else {
          rascunho.destaque = nome;
          if(rascunho.time === null || rascunho.time === undefined){
            if(S.times[0]?.jogadores?.includes(nome)) rascunho.time = 0;
            else if(S.times[1]?.jogadores?.includes(nome)) rascunho.time = 1;
            pickTimesLance();
            aplicarCameraAutomatica();
          }
        }
        pickDestaqueLance();
      };
      wrapBotoes.appendChild(b);
    });
    ed.appendChild(wrapBotoes);
  }

  const outroSel = rascunho.destaque && !jogadores.includes(rascunho.destaque);
  const inD = document.createElement('input');
  inD.type = 'text';
  inD.id = 'inDestaque';
  inD.style.width = '100%';
  inD.placeholder = jogadores.length ? 'outro nome (fora do elenco)' : 'Nome do jogador em destaque (opcional)';
  inD.value = outroSel ? rascunho.destaque : (rascunho.destaque || '');
  inD.oninput = e => {
    rascunho.destaque = e.target.value.trim() || null;
    if(rascunho.destaque && (rascunho.time === null || rascunho.time === undefined)){
      if(S.times[0]?.jogadores?.includes(rascunho.destaque)){
        rascunho.time = 0;
        pickTimesLance();
      } else if(S.times[1]?.jogadores?.includes(rascunho.destaque)){
        rascunho.time = 1;
        pickTimesLance();
      }
      aplicarCameraAutomatica();
    }
  };
  ed.appendChild(inD);
}

function pickTimes(){
  const el=$('#pickTime');
  if(!el) return;
  el.innerHTML='';
  S.times.forEach((t,i)=>{
    const b=document.createElement('button');
    b.type='button';
    b.textContent=t.nome;
    const isSel = rascunho.time===i;
    b.className = isSel ? 'sel' : '';
    const txtCor = corTextoParaFundo(t.cor);
    b.style.borderLeft = '6px solid ' + t.cor;
    if(isSel){
      b.style.background = t.cor;
      b.style.borderColor = t.cor;
      b.style.color = txtCor;
      b.style.fontWeight = '700';
    } else {
      b.style.background = 'var(--panel2)';
      b.style.color = 'var(--txt)';
    }
    b.onclick=()=>{
      rascunho.time = (rascunho.time === i) ? null : i;
      rascunho.autor=null;
      rascunho.assist=null;
      pickTimes();
      pickJogadores();
      andamento();
      aplicarCameraAutomatica();
    };
    el.appendChild(b);
  });
}
function pickJogadores(){
  const ea=$('#pickAutor'), es=$('#pickAssist');
  if(rascunho.time===null || rascunho.time===undefined || !S.times[rascunho.time]){
    rascunho.autor = null;
    rascunho.assist = null;
    ea.innerHTML='<span class="hint" style="margin:0; padding:4px 0; color:var(--dim)">Selecione o time do gol primeiro.</span>';
    es.innerHTML='<span class="hint" style="margin:0; padding:4px 0; color:var(--dim)">Selecione o time do gol primeiro.</span>';
    return;
  }
  const jogadores = S.times[rascunho.time].jogadores;
  const semElenco = jogadores.length===0;

  ea.innerHTML='';
  jogadores.forEach(nome=>{
    const pos = obterPosicaoJogador(rascunho.time, nome);
    const pInfo = POSICOES_JOGADORES.find(p => p.id === pos) || { sigla: 'MEI' };
    const b=document.createElement('button'); b.type='button';
    b.innerHTML = `${nome} <span style="font-size:10px; opacity:0.75; font-weight:700; margin-left:3px">[${pInfo.sigla}]</span>`;
    b.className = rascunho.autor===nome ? 'sel' : '';
    b.onclick=()=>{ rascunho.autor = nome; pickJogadores(); };
    ea.appendChild(b);
  });
  const outroAutorSel = rascunho.autor!=null && !jogadores.includes(rascunho.autor);

  // Autocomplete com jogadores cadastrados
  if(jogadoresCadastrados.length > 0){
    const divAuto = document.createElement('div');
    divAuto.style.cssText = 'position:relative;flex:1 1 100%;margin-top:6px';
    const inA = document.createElement('input');
    inA.type='text'; inA.id='inAutor'; inA.style.width='100%';
    inA.placeholder = semElenco ? 'Digite ou escolha jogador cadastrado' : 'outro nome ou jogador cadastrado';
    inA.value = outroAutorSel ? rascunho.autor : '';
    inA.oninput = e=>{
      rascunho.autor = e.target.value.trim() || null;
      mostrarSugestoesJogador(inA, 'autor');
    };
    inA.onfocus = () => mostrarSugestoesJogador(inA, 'autor');
    divAuto.appendChild(inA);

    const listaSug = document.createElement('div');
    listaSug.id = 'sugestoesAutor';
    listaSug.style.cssText = 'display:none;position:absolute;top:100%;left:0;right:0;background:var(--panel);border:1px solid var(--accent);border-radius:6px;max-height:200px;overflow-y:auto;z-index:1000;margin-top:2px';
    divAuto.appendChild(listaSug);
    ea.appendChild(divAuto);
  } else {
    const inA = document.createElement('input');
    inA.type='text'; inA.id='inAutor'; inA.style.flex='1 1 100%';
    if(!semElenco) inA.style.marginTop='6px';
    inA.placeholder = semElenco ? 'Nome de quem fez o gol' : 'outro nome (fora do elenco)';
    inA.value = outroAutorSel ? rascunho.autor : '';
    inA.oninput = e=>{ rascunho.autor = e.target.value.trim() || null; };
    ea.appendChild(inA);
  }

  es.innerHTML='';
  const semAssist = rascunho.assist === '—';
  jogadores.forEach(nome=>{
    const pos = obterPosicaoJogador(rascunho.time, nome);
    const pInfo = POSICOES_JOGADORES.find(p => p.id === pos) || { sigla: 'MEI' };
    const b=document.createElement('button'); b.type='button';
    b.innerHTML = `${nome} <span style="font-size:10px; opacity:0.75; font-weight:700; margin-left:3px">[${pInfo.sigla}]</span>`;
    b.className = (!semAssist && rascunho.assist===nome) ? 'sel' : '';
    b.onclick=()=>{ rascunho.assist = nome; pickJogadores(); };
    es.appendChild(b);
  });
  const outroAssistSel = !semAssist && rascunho.assist!=null && !jogadores.includes(rascunho.assist);

  // Autocomplete com jogadores cadastrados
  if(jogadoresCadastrados.length > 0){
    const divAuto = document.createElement('div');
    divAuto.style.cssText = 'position:relative;flex:1 1 100%;margin-top:6px';
    const inS = document.createElement('input');
    inS.type='text'; inS.id='inAssist'; inS.style.width='100%';
    inS.placeholder = semElenco ? 'Digite ou escolha jogador cadastrado' : 'outro nome ou jogador cadastrado';
    inS.disabled = semAssist;
    inS.value = outroAssistSel ? rascunho.assist : '';
    inS.oninput = e=>{
      rascunho.assist = e.target.value.trim() || null;
      mostrarSugestoesJogador(inS, 'assist');
    };
    inS.onfocus = () => mostrarSugestoesJogador(inS, 'assist');
    divAuto.appendChild(inS);

    const listaSug = document.createElement('div');
    listaSug.id = 'sugestoesAssist';
    listaSug.style.cssText = 'display:none;position:absolute;top:100%;left:0;right:0;background:var(--panel);border:1px solid var(--accent);border-radius:6px;max-height:200px;overflow-y:auto;z-index:1000;margin-top:2px';
    divAuto.appendChild(listaSug);
    es.appendChild(divAuto);
  } else {
    const inS = document.createElement('input');
    inS.type='text'; inS.id='inAssist'; inS.style.flex='1 1 100%';
    if(!semElenco) inS.style.marginTop='6px';
    inS.placeholder = semElenco ? 'Nome de quem deu a assistência' : 'outro nome (fora do elenco)';
    inS.disabled = semAssist;
    inS.value = outroAssistSel ? rascunho.assist : '';
    inS.oninput = e=>{ rascunho.assist = e.target.value.trim() || null; };
    es.appendChild(inS);
  }

  const lbl = document.createElement('label'); lbl.className='row'; lbl.style.marginTop='6px'; lbl.style.flex='1 1 100%';
  const chk = document.createElement('input'); chk.type='checkbox'; chk.id='chkSemAssist'; chk.style.width='auto';
  chk.checked = semAssist;
  chk.onchange = e=>{
    rascunho.assist = e.target.checked ? '—' : ($('#inAssist').value.trim() || null);
    pickJogadores();
  };
  lbl.appendChild(chk); lbl.appendChild(document.createTextNode(' sem assistência'));
  es.appendChild(lbl);
}
function andamento(){
  const t=ESTADO.gols.length;
  const gols=ESTADO.gols.filter(g=>g.tipo==='gol'&&!g.descartado).length;
  const lc=ESTADO.gols.filter(g=>g.tipo==='lance'&&!g.descartado).length;
  const desc=ESTADO.gols.filter(g=>g.descartado).length;
  $('#andamento').innerHTML = `<b>${gols}</b> gols · <b>${lc}</b> lances · ${desc} descartados · ${t-gols-lc-desc} a revisar`;
  atualizarAnaliseGolsMarcacao();
}

function atualizarAnaliseGolsMarcacao(){
  const topoEl = $('#placarMarcacaoTopo');
  const detalheEl = $('#analiseGolsDetalhada');
  if(!topoEl && !detalheEl) return;

  const timeA = S.times[0] || {nome: 'Time Amarelo', cor: '#eab308'};
  const timeB = S.times[1] || {nome: 'Time Azul', cor: '#2563eb'};

  const v = validos();
  const golsA = v.filter(g => g.time === 0).length;
  const golsB = v.filter(g => g.time === 1).length;
  const totalMarcados = golsA + golsB;

  const pJogo = S.meta.placar_jogo;
  const temPlacar = pJogo && (pJogo[0] != null || pJogo[1] != null);

  if(!temPlacar){
    if(topoEl){
      topoEl.innerHTML = `
        <div style="background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:8px 14px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px">
          <div class="row" style="gap:10px; align-items:center">
            <span style="font-size:11px; text-transform:uppercase; font-weight:700; color:var(--dim)">Gols marcados:</span>
            <span style="font-weight:700; color:${timeA.cor}">${timeA.nome}: ${golsA}</span>
            <span style="color:var(--line)">×</span>
            <span style="font-weight:700; color:${timeB.cor}">${timeB.nome}: ${golsB}</span>
          </div>
          <div style="font-size:12px; color:var(--dim)">
            💡 <a href="javascript:void(0)" onclick="irPara('s-dados')" style="color:var(--accent); font-weight:600">Informe o placar final no Passo 5</a> para conferir quantos gols faltam.
          </div>
        </div>
      `;
    }
    if(detalheEl){
      detalheEl.innerHTML = `
        <div style="padding:10px; background:var(--panel2); border:1px dashed var(--line); border-radius:6px; font-size:12px; color:var(--dim); line-height:1.5">
          💡 Para o assistente analisar <b>quantos gols faltam</b> e de <b>qual time falta marcar</b>, informe o placar final do jogo no <a href="javascript:void(0)" onclick="irPara('s-dados')" style="color:var(--accent); font-weight:600">Passo 5 (Dados da partida)</a>.
        </div>
      `;
    }
    return;
  }

  const espA = pJogo[0] != null ? pJogo[0] : 0;
  const espB = pJogo[1] != null ? pJogo[1] : 0;
  const totalEsp = espA + espB;
  const faltamA = espA - golsA;
  const faltamB = espB - golsB;
  const faltamTotal = totalEsp - totalMarcados;

  let badgeTextoA = '', badgeStyleA = '';
  if(faltamA > 0){
    badgeTextoA = `Faltam ${faltamA}`;
    badgeStyleA = `background:rgba(245,158,11,0.18); border:1px solid var(--b); color:var(--b)`;
  } else if(faltamA === 0){
    badgeTextoA = `✓ Completo (${espA})`;
    badgeStyleA = `background:rgba(34,197,94,0.18); border:1px solid var(--accent); color:var(--accent)`;
  } else {
    badgeTextoA = `⚠ +${-faltamA} a mais`;
    badgeStyleA = `background:rgba(239,68,68,0.18); border:1px solid #ef4444; color:#f87171`;
  }

  let badgeTextoB = '', badgeStyleB = '';
  if(faltamB > 0){
    badgeTextoB = `Faltam ${faltamB}`;
    badgeStyleB = `background:rgba(245,158,11,0.18); border:1px solid var(--b); color:var(--b)`;
  } else if(faltamB === 0){
    badgeTextoB = `✓ Completo (${espB})`;
    badgeStyleB = `background:rgba(34,197,94,0.18); border:1px solid var(--accent); color:var(--accent)`;
  } else {
    badgeTextoB = `⚠ +${-faltamB} a mais`;
    badgeStyleB = `background:rgba(239,68,68,0.18); border:1px solid #ef4444; color:#f87171`;
  }

  let badgeTextoTotal = '', badgeStyleTotal = '';
  if(faltamTotal > 0){
    badgeTextoTotal = `⏳ Faltam ${faltamTotal} gols no total`;
    badgeStyleTotal = `background:rgba(245,158,11,0.22); border:1px solid var(--b); color:var(--b)`;
  } else if(faltamTotal === 0 && faltamA === 0 && faltamB === 0){
    badgeTextoTotal = `✓ Todos os ${totalEsp} gols marcados!`;
    badgeStyleTotal = `background:rgba(34,197,94,0.22); border:1px solid var(--accent); color:var(--accent)`;
  } else {
    badgeTextoTotal = `⚠ Atenção ao placar`;
    badgeStyleTotal = `background:rgba(239,68,68,0.22); border:1px solid #ef4444; color:#f87171`;
  }

  if(topoEl){
    topoEl.innerHTML = `
      <div style="background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:10px 14px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px">
        <div class="row" style="gap:14px; align-items:center; flex-wrap:wrap">
          <div style="display:flex; align-items:center; gap:8px">
            <span style="font-size:11px; text-transform:uppercase; letter-spacing:.7px; color:var(--dim); font-weight:700">Placar do Jogo:</span>
            <b style="font-family:ui-monospace,monospace; font-size:15px; color:var(--txt)">${espA} × ${espB}</b>
          </div>
          <div style="display:flex; align-items:center; gap:10px; border-left:1px solid var(--line); padding-left:14px; flex-wrap:wrap">
            <span style="font-size:11px; text-transform:uppercase; letter-spacing:.7px; color:var(--dim); font-weight:700">Gols Marcados:</span>
            <span style="font-weight:700; color:${timeA.cor}">${timeA.nome}: ${golsA}/${espA}</span>
            <span style="font-size:11px; font-weight:700; padding:2px 7px; border-radius:4px; ${badgeStyleA}">${badgeTextoA}</span>
            <span style="color:var(--line)">|</span>
            <span style="font-weight:700; color:${timeB.cor}">${timeB.nome}: ${golsB}/${espB}</span>
            <span style="font-size:11px; font-weight:700; padding:2px 7px; border-radius:4px; ${badgeStyleB}">${badgeTextoB}</span>
          </div>
        </div>
        <div class="row" style="align-items:center">
          <span style="font-size:12px; font-weight:700; padding:4px 10px; border-radius:6px; ${badgeStyleTotal}">${badgeTextoTotal}</span>
        </div>
      </div>
    `;
  }

  if(detalheEl){
    const pctA = Math.min(100, Math.round((golsA / Math.max(1, espA)) * 100));
    const pctB = Math.min(100, Math.round((golsB / Math.max(1, espB)) * 100));

    let itensAnalise = [];
    if(faltamA > 0) itensAnalise.push(`Faltam <b style="color:${timeA.cor}">${faltamA} gol(s) do ${timeA.nome}</b>`);
    else if(faltamA === 0) itensAnalise.push(`<span style="color:var(--accent); font-weight:700">✓ ${timeA.nome} completo (${espA}/${espA})</span>`);
    else itensAnalise.push(`<span style="color:#f87171; font-weight:700">⚠ ${timeA.nome} com ${-faltamA} a mais</span>`);

    if(faltamB > 0) itensAnalise.push(`Faltam <b style="color:${timeB.cor}">${faltamB} gol(s) do ${timeB.nome}</b>`);
    else if(faltamB === 0) itensAnalise.push(`<span style="color:var(--accent); font-weight:700">✓ ${timeB.nome} completo (${espB}/${espB})</span>`);
    else itensAnalise.push(`<span style="color:#f87171; font-weight:700">⚠ ${timeB.nome} com ${-faltamB} a mais</span>`);

    const faltamRevisar = (ESTADO.gols || []).filter(g => !g.descartado && !g.tipo).length;

    let avisoSemClipes = '';
    if(faltamTotal > 0 && faltamRevisar === 0){
      avisoSemClipes = `
        <div style="margin-top:10px; padding:10px; background:rgba(245,158,11,0.12); border:1px solid var(--b); border-radius:6px; font-size:12px">
          <b style="color:var(--b)">⚠ Faltam ${faltamTotal} gol(s) no vídeo!</b>
          <div style="margin-top:4px; line-height:1.4">Todos os clipes atuais já foram classificados, mas ainda faltam marcar ${faltamA > 0 ? `${faltamA} gol(s) do ${timeA.nome}` : ''}${(faltamA > 0 && faltamB > 0) ? ' e ' : ''}${faltamB > 0 ? `${faltamB} gol(s) do ${timeB.nome}` : ''}.</div>
          <button type="button" class="amberb" onclick="irPara('s-revisar')" style="margin-top:8px; width:100%; font-size:12px; padding:6px 10px">🎬 Voltar à Tela 4 para cortar mais gols no vídeo completo</button>
        </div>
      `;
    }

    detalheEl.innerHTML = `
      <div style="background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:10px">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px">
          <!-- Card Time A -->
          <div style="background:var(--panel); border:1px solid ${faltamA === 0 ? 'var(--accent)' : 'var(--line)'}; border-radius:6px; padding:8px 10px">
            <div class="row" style="justify-content:space-between; align-items:center">
              <b style="color:${timeA.cor}; font-size:12px">${timeA.nome}</b>
              <span style="font-size:10px; font-weight:700; padding:1px 5px; border-radius:3px; ${badgeStyleA}">${badgeTextoA}</span>
            </div>
            <div style="font-size:18px; font-weight:800; color:${timeA.cor}; margin:4px 0 3px; font-family:ui-monospace,monospace">
              ${golsA} <span style="font-size:12px; font-weight:500; color:var(--dim)">/ ${espA} gols</span>
            </div>
            <div style="background:rgba(255,255,255,0.08); border-radius:3px; height:5px; overflow:hidden">
              <div style="background:${timeA.cor}; width:${pctA}%; height:100%; border-radius:3px"></div>
            </div>
          </div>

          <!-- Card Time B -->
          <div style="background:var(--panel); border:1px solid ${faltamB === 0 ? 'var(--accent)' : 'var(--line)'}; border-radius:6px; padding:8px 10px">
            <div class="row" style="justify-content:space-between; align-items:center">
              <b style="color:${timeB.cor}; font-size:12px">${timeB.nome}</b>
              <span style="font-size:10px; font-weight:700; padding:1px 5px; border-radius:3px; ${badgeStyleB}">${badgeTextoB}</span>
            </div>
            <div style="font-size:18px; font-weight:800; color:${timeB.cor}; margin:4px 0 3px; font-family:ui-monospace,monospace">
              ${golsB} <span style="font-size:12px; font-weight:500; color:var(--dim)">/ ${espB} gols</span>
            </div>
            <div style="background:rgba(255,255,255,0.08); border-radius:3px; height:5px; overflow:hidden">
              <div style="background:${timeB.cor}; width:${pctB}%; height:100%; border-radius:3px"></div>
            </div>
          </div>
        </div>

        <div style="font-size:12px; line-height:1.5; color:var(--txt)">
          ${itensAnalise.join(' · ')}
        </div>
        ${avisoSemClipes}
      </div>
    `;
  }
}
$('#btnSalvar').onclick = ()=>{
  const g = ESTADO.gols.find(x => x.indice === ESTADO.indiceAtual) || ESTADO.gols[0];
  if(!g) return;
  if(!rascunho.tipo){ alert('Escolha o tipo do clipe (Gol, Defesaça, etc).'); return; }
  const temTime = (rascunho.time !== null && rascunho.time !== undefined && S.times[rascunho.time]);
  const ehGol = rascunho.tipo === 'gol';
  if(ehGol && (!temTime || !rascunho.autor)){ alert('Escolha o time e o autor do gol.'); return; }
  g.tipo = rascunho.tipo;
  g.status = rascunho.status || (ehGol ? 'gol' : 'lance');
  g.lance = !ehGol ? (rascunho.lance || 'Lance') : null;
  g.time = temTime ? rascunho.time : null;
  g.autor = (ehGol && temTime) ? rascunho.autor : null;
  g.assist = (ehGol && temTime && rascunho.assist !== '—') ? rascunho.assist : null;
  g.destaque = (!ehGol && temTime) ? rascunho.destaque : null;
  g.cameras_clipe = (Array.isArray(g.cameras_clipe) && g.cameras_clipe.length) ? g.cameras_clipe : [Number(g.camera) || 1];
  // Câmera que o time ataca: só entra se ninguém escolheu outra para este clipe.
  const camAtaque = cameraAutomaticaDoRascunho();
  const padrao = g.cameras_clipe.length === 1 && g.cameras_clipe[0] === 1;
  if(camAtaque && !g.camera_manual && padrao && camerasSelecionadas()[camAtaque - 1]) g.cameras_clipe = [camAtaque];
  g.camera = g.cameras_clipe[0];
  g.descartado = false;

  fetch('/api/gols/confirmar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      indice: g.indice,
      status: g.status,
      lance: g.lance,
      time: g.time,
      autor: g.autor,
      assist: g.assist,
      destaque: g.destaque,
      camera: g.camera,
      cameras: g.cameras_clipe
    })
  }).catch(()=>{});

  agendarSalvar();
  const currIdx = ESTADO.gols.findIndex(x => x.indice === g.indice);
  if(currIdx >= 0 && currIdx < ESTADO.gols.length - 1){
    ESTADO.indiceAtual = ESTADO.gols[currIdx + 1].indice;
  }
  renderMarcacao();
};

const btnMaisTrasStep6 = $('#btnClipeMaisTrasStep6');
if(btnMaisTrasStep6){
  btnMaisTrasStep6.onclick = async () => {
    const st = $('#statusClipeMaisTrasStep6');
    const g = ESTADO.gols.find(x => x.indice === ESTADO.indiceAtual) || ESTADO.gols[0];
    if(!g || !ESTADO.video) return;
    const ini = Number(g.inicio_s), fim = Number(g.fim_s);
    if(!Number.isFinite(ini) || !Number.isFinite(fim)){ st.textContent = 'Este clipe não tem início/fim registrados.'; return; }
    // Volta 10 s antes do início do clipe atual e grava 20 s a partir daí.
    const novoIni = Math.max(0, Math.round((ini - 10) * 100) / 100);
    const novoFim = Math.round((novoIni + 20) * 100) / 100;
    btnMaisTrasStep6.disabled = true;
    st.innerHTML = `<span class="spinner"></span> Cortando ${fmtTempo(novoIni)} até ${fmtTempo(novoFim)}...`;
    try {
      // Sem marcação de propósito: é outro momento do jogo e não pode contar como gol em dobro.
      const r = await fetch('/api/gols/adicionar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
        video: ESTADO.video.caminho, inicio_s: novoIni, fim_s: novoFim,
        tempo_s: Math.round(ini * 100) / 100, status: 'pendente', lance: null
      })});
      const res = await r.json().catch(() => ({}));
      if(!r.ok){ st.textContent = 'Erro ao cortar: ' + (res.detail || 'falha no servidor'); return; }
      await carregarClipes();
      ESTADO.indiceAtual = res.indice;
      await sincronizarGolsComBackend();
      renderMarcacao();
      $('#statusClipeMaisTrasStep6').textContent = `✓ Clipe #${String(res.indice).padStart(2,'0')} gerado (começa 10 s antes do clipe, 20 s de duração). Marque o que aconteceu nele.`;
    } catch(err) {
      st.textContent = 'Erro ao comunicar com o servidor: ' + err;
    } finally {
      btnMaisTrasStep6.disabled = false;
    }
  };
}

const btnExcluirStep6 = $('#btnExcluirClipeStep6');
if(btnExcluirStep6){
  btnExcluirStep6.onclick = async ()=>{
    const g = ESTADO.gols.find(x => x.indice === ESTADO.indiceAtual) || ESTADO.gols[0];
    if(!g) return;
    if(!confirm(`ATENÇÃO: Deseja EXCLUIR DEFINITIVAMENTE o clipe selecionado #${String(g.indice).padStart(2,'0')} (${g.tempo || ''}) do computador?\n\nO arquivo de vídeo será apagado e o lance será removido da lista.`)) return;

    const currIdx = ESTADO.gols.findIndex(x => x.indice === g.indice);
    const proximoIndice = (currIdx >= 0 && currIdx < ESTADO.gols.length - 1)
      ? ESTADO.gols[currIdx + 1].indice
      : (currIdx > 0 ? ESTADO.gols[currIdx - 1].indice : null);

    const ok = await descartarClipe(g.indice);
    if(ok){
      ESTADO.indiceAtual = proximoIndice;
      await sincronizarGolsComBackend();
      renderMarcacao();
    }
  };
}

$('#btnDescartar').onclick = ()=>{
  const g = ESTADO.gols.find(x => x.indice === ESTADO.indiceAtual) || ESTADO.gols[0];
  if(!g) return;
  if(!g.descartado){
    if(!confirm(`Pular o clipe #${String(g.indice).padStart(2,'0')} (${g.tempo || ''}) da súmula sem apagar o arquivo de vídeo?\n\nEle não entrará no vídeo final.`)) return;
    g._backup = { tipo: g.tipo, status: g.status, autor: g.autor, assist: g.assist, time: g.time, lance: g.lance, destaque: g.destaque };
    g.descartado = true;
    g.tipo = null; g.status = null; g.autor = null; g.assist = null; g.time = null; g.lance = null; g.destaque = null;
    const currIdx = ESTADO.gols.findIndex(x => x.indice === g.indice);
    if(currIdx >= 0 && currIdx < ESTADO.gols.length - 1){
      ESTADO.indiceAtual = ESTADO.gols[currIdx + 1].indice;
    }
  } else {
    g.descartado = false;
    if(g._backup){
      Object.assign(g, g._backup);
      delete g._backup;
    }
  }
  agendarSalvar();
  renderMarcacao();
};
$('#btnPrev').onclick = ()=>{
  const currIdx = ESTADO.gols.findIndex(x => x.indice === ESTADO.indiceAtual);
  if(currIdx > 0){
    ESTADO.indiceAtual = ESTADO.gols[currIdx - 1].indice;
    renderMarcacao();
  }
};
$('#btnNext').onclick = ()=>{
  const currIdx = ESTADO.gols.findIndex(x => x.indice === ESTADO.indiceAtual);
  if(currIdx >= 0 && currIdx < ESTADO.gols.length - 1){
    ESTADO.indiceAtual = ESTADO.gols[currIdx + 1].indice;
    renderMarcacao();
  }
};
function alternarModoTeatroMarcar(forcar = null){
  const sec = document.getElementById('s-marcar');
  const btn = document.getElementById('btnTeatroMarcar');
  const mainEl = document.querySelector('main');
  if(!sec) return;

  const ativar = (forcar !== null) ? forcar : !sec.classList.contains('modo-teatro');

  if(ativar){
    sec.classList.add('modo-teatro');
    if(mainEl) mainEl.classList.add('teatro-ativo');
    if(btn){
      btn.classList.add('ativo');
      const ic = btn.querySelector('.icone-teatro');
      const tx = btn.querySelector('.texto-teatro');
      if(ic) ic.textContent = '🗗';
      if(tx) tx.textContent = 'Reduzir (Lado a Lado)';
      btn.title = 'Voltar para visualização lado a lado · Atalho: T';
    }
    localStorage.setItem('futbin_modo_teatro_marcar', '1');
  } else {
    sec.classList.remove('modo-teatro');
    if(mainEl) mainEl.classList.remove('teatro-ativo');
    if(btn){
      btn.classList.remove('ativo');
      const ic = btn.querySelector('.icone-teatro');
      const tx = btn.querySelector('.texto-teatro');
      if(ic) ic.textContent = '🗖';
      if(tx) tx.textContent = 'Expandir Vídeo (Modo Teatro)';
      btn.title = 'Modo Teatro (expandir vídeo e mover marcação para baixo) · Atalho: T';
    }
    localStorage.setItem('futbin_modo_teatro_marcar', '0');
  }
}

$('#btnRep').onclick = ()=>{ const v=$('#vid'); v.currentTime=0; v.play(); };
document.addEventListener('keydown', e=>{
  if(passoAtual!=='s-marcar') return;
  if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)) return;
  const k = e.key.toLowerCase();
  if(e.key==='ArrowLeft') $('#btnPrev').click();
  else if(e.key==='ArrowRight') $('#btnNext').click();
  else if(e.key==='Enter') $('#btnSalvar').click();
  else if(k==='r') $('#btnRep').click();
  else if(k==='t') alternarModoTeatroMarcar();
  else {
    let match = TIPOS_CLIPE.find(t => t.hotkey === k);
    if(!match && (k === 'l' || k === 'o')){
      match = TIPOS_CLIPE.find(t => t.id === 'lance');
    }
    if(match){
      selecionarTipoMarcacao(match);
    }
  }
});

/* ------------------------------------------------------------ passo 7: resumo e montagem */
function obterFotoJogador(nome, timeIdx = null){
  if(!nome) return null;
  const nNorm = nome.trim().toLowerCase();
  if(timeIdx !== null && S.times[timeIdx] && S.times[timeIdx].fotos){
    for(const [k, v] of Object.entries(S.times[timeIdx].fotos)){
      if(k.trim().toLowerCase() === nNorm && v) return v;
    }
  }
  for(let i = 0; i < S.times.length; i++){
    const t = S.times[i];
    if(t && t.fotos){
      for(const [k, v] of Object.entries(t.fotos)){
        if(k.trim().toLowerCase() === nNorm && v) return v;
      }
    }
  }
  return null;
}

function obterTimeJogador(nome){
  if(!nome) return null;
  const nNorm = nome.trim().toLowerCase();
  for(let i = 0; i < S.times.length; i++){
    const t = S.times[i];
    if(t && t.jogadores){
      if(t.jogadores.some(j => j.trim().toLowerCase() === nNorm)) return { timeIdx: i, ...t };
    }
  }
  return null;
}

function obterAvatarJogadorHtml(nome, tamanho = 32, timeIdx = null){
  if(!nome) return '';
  const foto = obterFotoJogador(nome, timeIdx);
  const timeInfo = obterTimeJogador(nome);
  const tCor = timeInfo ? timeInfo.cor : (timeIdx !== null && S.times[timeIdx] ? S.times[timeIdx].cor : '#eab308');
  const nomeEsc = nome.replace(/"/g, '&quot;');

  if(foto){
    return `<div class="resumo-avatar-wrap" style="width:${tamanho}px; height:${tamanho}px; border:2px solid ${tCor}" title="${nomeEsc}">
      <img src="${foto}" class="resumo-avatar-img" alt="${nomeEsc}">
    </div>`;
  }

  const partes = nome.trim().split(/\s+/);
  const iniciais = (partes.length >= 2 ? (partes[0][0] + partes[partes.length - 1][0]) : nome.slice(0, 2)).toUpperCase();
  const fontSize = Math.max(10, Math.round(tamanho * 0.38));
  return `<div class="resumo-avatar-wrap" style="width:${tamanho}px; height:${tamanho}px; border:2px solid ${tCor}; background:linear-gradient(135deg, #182233, #0b101a); font-weight:800; font-size:${fontSize}px; color:#ffffff; text-shadow:0 1px 2px rgba(0,0,0,0.8)" title="${nomeEsc}">
    ${iniciais}
  </div>`;
}

let abaPreviewAtual = 'frame';
let tempoFundoSegundos = 150;

/* ===== CONFIG POR CÂMERA (tela final) ============================= */
const _camPresetValues = {
  claro_vivido:{b:125,s:145,c:112,d:0,v:0},
  super_claro: {b:145,s:135,c:115,d:0,v:0},
  fifa:        {b:118,s:165,c:120,d:0,v:0},
  tv:          {b:110,s:130,c:108,d:0,v:5},
  cinema:      {b:105,s:90, c:125,d:0,v:15},
  original:    {b:100,s:100,c:100,d:0,v:0},
};
const _camPresetNomes = {claro_vivido:'🌟 Claro & Vívido',super_claro:'☀️ Super Iluminado',fifa:'🎮 FIFA/Game',tv:'📺 Transmissão TV',cinema:'🎥 Cinema',original:'🔄 Original'};
const _camPresetCores = {claro_vivido:'var(--accent)',super_claro:'#fde047',fifa:'#38bdf8',tv:'#4ade80',cinema:'#a78bfa',original:'var(--dim)'};
const _camCorLabel    = ['var(--accent)','#00f0ff','#a78bfa'];

function _cfgCamDef(){ return {brilho:125,saturacao:145,contraste:112,desfoque:0,vinheta:0,tempo_s:150,aplicar_clipes:true,_preset:null}; }
function _cfgCam(i){
  if(!Array.isArray(ESTADO.configCameras)) ESTADO.configCameras = [null,null,null];
  if(!ESTADO.configCameras[i] || typeof ESTADO.configCameras[i]!=='object') ESTADO.configCameras[i] = _cfgCamDef();
  return ESTADO.configCameras[i];
}

function _atualizarFiltroPreviewCam(ci){
  const cfg=_cfgCam(ci), img=$(`#fundoPreviewCam${ci}`), vin=$(`#fundoVinhetaCam${ci}`);
  if(!img){
    console.warn(`[!] Elemento fundoPreviewCam${ci} não encontrado para aplicar filtros`);
    return;
  }
  const filtro = `brightness(${(cfg.brilho||100)/100}) saturate(${(cfg.saturacao||100)/100}) contrast(${(cfg.contraste||100)/100}) blur(${cfg.desfoque||0}px)`;
  img.style.filter = filtro;
  // Força reflow para garantir que o filtro seja aplicado
  void img.offsetHeight;
  // Log para debug
  console.log(`[>] Filtros aplicados cam${ci}:`, filtro);
  if(vin) vin.style.background=(cfg.vinheta&&cfg.vinheta>0)?`radial-gradient(circle, transparent 20%, rgba(11,15,23,${cfg.vinheta/100}) 80%)`:'transparent';
}

function _sincHidden(ci){
  const cfg=_cfgCam(ci), m=(id,v)=>{const e=$('#'+id);if(e)e.value=String(v);};
  m('fundoBrilho',cfg.brilho??125); m('fundoSaturacao',cfg.saturacao??145);
  m('fundoContraste',cfg.contraste??112); m('fundoDesfoque',cfg.desfoque??0);
  m('fundoVinheta',cfg.vinheta??0);
}

async function aplicarPresetCam(ci, pid){
  console.log(`[>] Aplicando preset ${pid} na câmera ${ci}`);
  const vals=_camPresetValues[pid]; if(!vals) return;
  const cfg=_cfgCam(ci);
  cfg._preset=pid; cfg.brilho=vals.b; cfg.saturacao=vals.s; cfg.contraste=vals.c; cfg.desfoque=vals.d; cfg.vinheta=vals.v;
  const pfxs={camBrilho:'brilho',camSat:'saturacao',camContraste:'contraste',camDesfoque:'desfoque',camVinheta:'vinheta'};
  Object.entries(pfxs).forEach(([pfx,key])=>{
    const v=cfg[key], el=$(`#${pfx}${ci}`); if(el) el.value=v;
    const lb=$(`#lbl_${pfx}${ci}`); if(lb) lb.textContent=key==='desfoque'?(v===0?'0 px':`${v} px`):`${v}%`;
  });
  const pg=$(`#presetsGridCam${ci}`);
  if(pg) pg.querySelectorAll('button').forEach(b=>{
    const ok=b.dataset.preset===pid, cp=_camPresetCores[pid]||'var(--accent)';
    b.style.borderColor=ok?cp:'var(--line)'; b.style.background=ok?`${cp}22`:'';
  });
  _atualizarFiltroPreviewCam(ci);
  if(ci===0){ _sincHidden(0); }
  await salvarFundoCartelaCam(ci,true);
  // Reaplica os filtros após salvar (garante que não foram perdidos)
  setTimeout(() => {
    console.log(`[>] Reaplicando filtros após preset na câmera ${ci}`);
    _atualizarFiltroPreviewCam(ci);
  }, 100);
}

async function capturarFrameCam(ci, tempo_s){
  const ld=$(`#fundoLoadingCam${ci}`), pi=$(`#fundoPreviewCam${ci}`);
  if(ld) ld.style.display='flex';
  try{
    const cams=camerasSelecionadas(), cam=cams[ci];
    const video=cam?(cam.caminho||cam.nome):(S.meta?.video||null);
    const r=await fetch('/api/cartelas/fundo/capturar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({video,tempo_s:parseFloat(tempo_s)||0})});
    if(!r.ok) return;
    const d=await r.json();
    if(d.ok&&(d.raw_url||d.preview)){
      const url=(d.raw_url||d.preview)+'?t='+Date.now();
      if(pi){
        pi.src=url;
        // Aguarda carregar e aplica filtros
        pi.onload = () => {
          _atualizarFiltroPreviewCam(ci);
          if(ld) ld.style.display='none';
        };
      }
      _cfgCam(ci).tempo_s=d.tempo_s;
      const ti=$(`#tempoFundoCam${ci}`); if(ti) ti.value=fmtTempo(Math.round(d.tempo_s));
      if(ci===0){
        tempoFundoSegundos=d.tempo_s;
        const gi=$('#imgFundoPreview'); if(gi) gi.src=url;
        const fi=$('#frameTimestampInfo'); if(fi) fi.textContent=`Instante: ${fmtTempo(Math.round(d.tempo_s))}`;
        _sincHidden(0);
        if(abaPreviewAtual!=='frame') await salvarFundoCartela(true);
      }
    }
  }catch(e){console.error(e);}finally{if(ld) ld.style.display='none';}
}

async function salvarFundoCartelaCam(ci, silencioso=false){
  ESTADO.configCameras[ci]={..._cfgCam(ci)};
  if(ci===0){ _sincHidden(0); await salvarFundoCartela(silencioso); }
  else{
    agendarSalvar();
    if(!silencioso){
      const st=$('#statusSalvoFundo');
      if(st){st.textContent=`✓ Câmera ${ci+1} salva!`;st.style.display='inline-block';setTimeout(()=>{st.style.display='none';st.textContent='✓ Aplicado!';},2500);}
    }
  }
}

function renderGridCamerasFundo(){
  const grid=$('#gridCamerasFundo'); if(!grid) return;
  grid.querySelectorAll('video').forEach(v=>{v.pause();v.removeAttribute('src');v.load();});
  grid.innerHTML='';
  const cameras=camerasSelecionadas();
  const PIDS=['claro_vivido','super_claro','fifa','tv','cinema','original'];

  [0,1,2].forEach(ci=>{
    const cam=cameras[ci], cfg=_cfgCam(ci), cor=_camCorLabel[ci];
    const col=document.createElement('div');
    col.style.cssText=`background:var(--panel2);border:1px solid ${ci===0?'rgba(0,255,135,.35)':'var(--line)'};border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:8px`;

    /* cabeçalho */
    const cab=document.createElement('div'); cab.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:4px';
    cab.innerHTML=`<b style="font-size:13px;color:${cor}">📹 Câmera ${ci+1}${ci===0?' · principal':''}</b>${cam?`<span style="font-size:10px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:110px" title="${cam.nome}">${cam.nome}</span>`:'<span class="hint" style="font-size:10px">sem vídeo</span>'}`;
    col.appendChild(cab);

    if(!cam){
      const msg=document.createElement('div'); msg.className='hint'; msg.style.cssText='font-size:11px;text-align:center;padding:18px 0';
      msg.textContent='Adicione um vídeo no Passo 1 para configurar esta câmera.';
      col.appendChild(msg); grid.appendChild(col); return;
    }

    /* preview */
    const pw=document.createElement('div'); pw.style.cssText='position:relative;aspect-ratio:16/9;background:#000;border-radius:7px;overflow:hidden;border:1px solid var(--line)';
    const pi=document.createElement('img'); pi.id=`fundoPreviewCam${ci}`; pi.style.cssText='width:100%;height:100%;object-fit:cover;display:block'; pi.src='/web/fundo_raw.png'; pi.onerror=()=>{pi.src='/web/fundo_cartela.png';};
    pi.onload = () => _atualizarFiltroPreviewCam(ci);
    const pv=document.createElement('div'); pv.id=`fundoVinhetaCam${ci}`; pv.style.cssText='position:absolute;inset:0;background:transparent;pointer-events:none';
    const pl=document.createElement('div'); pl.id=`fundoLoadingCam${ci}`; pl.style.cssText='position:absolute;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff'; pl.textContent='⏳ Capturando…';
    pw.appendChild(pi); pw.appendChild(pv); pw.appendChild(pl); col.appendChild(pw);

    /* tempo + capturar */
    const tr=document.createElement('div'); tr.style.cssText='display:flex;gap:6px;align-items:center';
    const ti=document.createElement('input'); ti.type='text'; ti.id=`tempoFundoCam${ci}`; ti.value=fmtTempo(cfg.tempo_s||150); ti.style.cssText='width:70px;font-family:monospace;font-size:12px;font-weight:700;text-align:center;padding:4px';
    const cb=document.createElement('button'); cb.type='button'; cb.className='ghost'; cb.style.cssText='flex:1;font-size:11px;padding:4px 8px'; cb.textContent='📷 Capturar Frame';
    cb.onclick=()=>capturarFrameCam(ci,parseTempo(ti.value)||cfg.tempo_s||150);
    ti.onchange=()=>{const t=parseTempo(ti.value);if(t!=null&&!isNaN(t)){cfg.tempo_s=t;capturarFrameCam(ci,t);}};
    tr.appendChild(ti); tr.appendChild(cb); col.appendChild(tr);

    const rng=document.createElement('input'); rng.type='range'; rng.min=0; rng.max=Math.max(10,Math.round(cam.duracao_s||3600)); rng.step=1; rng.value=cfg.tempo_s||150; rng.style.width='100%';
    rng.oninput=()=>ti.value=fmtTempo(Math.round(rng.value));
    rng.onchange=()=>{cfg.tempo_s=parseFloat(rng.value);capturarFrameCam(ci,cfg.tempo_s);};
    col.appendChild(rng);

    /* presets */
    const plbl=document.createElement('div'); plbl.style.cssText='font-size:10px;color:var(--dim);font-weight:700;text-transform:uppercase;letter-spacing:.5px'; plbl.textContent='Preset de cor e iluminação'; col.appendChild(plbl);
    const pg=document.createElement('div'); pg.id=`presetsGridCam${ci}`; pg.style.cssText='display:grid;grid-template-columns:repeat(2,1fr);gap:4px';
    PIDS.forEach(pid=>{
      const isAt=cfg._preset===pid, cp=_camPresetCores[pid]||'var(--dim)';
      const btn=document.createElement('button'); btn.type='button'; btn.dataset.preset=pid; btn.className='ghost';
      btn.style.cssText=`text-align:left;padding:5px 8px;font-size:10px;display:flex;flex-direction:column;gap:1px;border-color:${isAt?cp:'var(--line)'};${isAt?`background:${cp}22`:''}`;
      btn.innerHTML=`<span style="font-weight:700;color:${cp}">${_camPresetNomes[pid]}</span>`;
      btn.onclick=()=>aplicarPresetCam(ci,pid);
      pg.appendChild(btn);
    });
    col.appendChild(pg);

    /* sliders */
    [{pfx:'camBrilho',label:'Brilho',key:'brilho',min:20,max:250,step:5,def:125},
     {pfx:'camSat',label:'Saturação',key:'saturacao',min:0,max:250,step:5,def:145},
     {pfx:'camContraste',label:'Contraste',key:'contraste',min:50,max:200,step:2,def:112},
     {pfx:'camDesfoque',label:'Desfoque',key:'desfoque',min:0,max:25,step:1,def:0},
     {pfx:'camVinheta',label:'Vinheta',key:'vinheta',min:0,max:90,step:5,def:0},
    ].forEach(({pfx,label,key,min,max,step,def})=>{
      const val=cfg[key]!=null?cfg[key]:def;
      const ww=document.createElement('div');
      const rr=document.createElement('div'); rr.style.cssText='display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px';
      const ln=document.createElement('span'); ln.textContent=label;
      const lv=document.createElement('span'); lv.id=`lbl_${pfx}${ci}`; lv.style.cssText='font-weight:700;color:var(--accent)';
      lv.textContent=key==='desfoque'?(val===0?'0 px':`${val} px`):`${val}%`;
      rr.appendChild(ln); rr.appendChild(lv);
      const sl=document.createElement('input'); sl.type='range'; sl.id=`${pfx}${ci}`; sl.min=min; sl.max=max; sl.step=step; sl.value=val; sl.style.width='100%';
      sl.oninput=()=>{
        const v=parseFloat(sl.value);
        console.log(`[>] Slider ${pfx}${ci} alterado para ${v}`);
        cfg[key]=v;
        cfg._preset=null;
        lv.textContent=key==='desfoque'?(v===0?'0 px':`${v} px`):`${v}%`;
        _atualizarFiltroPreviewCam(ci);
      };
      sl.onchange=()=>{if(ci===0)_sincHidden(0);agendarSalvar();};
      ww.appendChild(rr); ww.appendChild(sl); col.appendChild(ww);
    });

    /* checkbox + botão */
    const ck=document.createElement('label'); ck.style.cssText='display:flex;align-items:center;gap:6px;font-size:11px;cursor:pointer';
    const chk=document.createElement('input'); chk.type='checkbox'; chk.id=`camAplicarClipes${ci}`; chk.style.width='auto'; chk.checked=cfg.aplicar_clipes!==false;
    chk.onchange=()=>{cfg.aplicar_clipes=chk.checked;if(ci===0)_sincHidden(0);agendarSalvar();};
    const cl=document.createElement('span'); cl.textContent='Aplicar nos clipes desta câmera';
    ck.appendChild(chk); ck.appendChild(cl); col.appendChild(ck);

    const ab=document.createElement('button'); ab.type='button'; ab.className='act'; ab.style.cssText='width:100%;font-size:12px;padding:6px;margin-top:2px';
    ab.textContent=ci===0?'✓ Aplicar como Fundo das Cartelas':'✓ Salvar Configuração';
    ab.onclick=()=>salvarFundoCartelaCam(ci,false);
    col.appendChild(ab);

    _atualizarFiltroPreviewCam(ci);
    grid.appendChild(col);
  });
}
/* ================================================================== */

function atualizarFiltrosCssFundo(){
  // Lê da config da câmera 0 (inputs hidden são backup, mas cfg é a fonte de verdade)
  const cfg = _cfgCam(0);
  const b = cfg.brilho    ?? 125;
  const s = cfg.saturacao ?? 145;
  const c = cfg.contraste ?? 112;
  const d = cfg.desfoque  ?? 0;
  const v = cfg.vinheta   ?? 0;

  const img = $('#imgFundoPreview');
  if(img) img.style.filter = `brightness(${b/100}) saturate(${s/100}) contrast(${c/100}) blur(${d}px)`;
  const ov = $('#overlayFundoPreview');
  if(ov) ov.style.background = v > 0 ? `rgba(11,15,23,${v/100})` : 'transparent';
  _atualizarFiltroPreviewCam(0);
}

async function capturarFrameFundo(tempo_s){
  // legado: delega para a câmera 1 (índice 0)
  await capturarFrameCam(0, tempo_s);
}

function carregarFramePredefinido(tempo_s){
  capturarFrameCam(0, tempo_s);
}

async function salvarFundoCartela(silencioso = false){
  const loadEl = $('#loadingFundoPreview');
  if(loadEl) loadEl.style.display = 'flex';
  try {
    // Lê sempre da config da câmera 0 (câmera principal)
    const cfg = _cfgCam(0);
    const video = S.meta && S.meta.video ? S.meta.video : null;
    const payload = {
      video,
      tempo_s: cfg.tempo_s || tempoFundoSegundos,
      brilho:    (cfg.brilho    ?? 125) / 100,
      saturacao: (cfg.saturacao ?? 145) / 100,
      contraste: (cfg.contraste ?? 112) / 100,
      desfoque:   cfg.desfoque  ?? 0,
      vinheta:    cfg.vinheta   ?? 0,
      aplicar_video_clipes: cfg.aplicar_clipes !== false,
    };
    const r = await fetch('/api/cartelas/fundo/salvar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if(!r.ok){
      if(!silencioso) alert('Erro ao salvar fundo das cartelas.');
      return;
    }
    const data = await r.json();
    if(data.ok){
      S.meta = S.meta || {};
      S.meta.fundo_config = {...payload};
      S.meta.fundo_cartela = 'fundo_cartela.png';
      const st = $('#statusSalvoFundo');
      if(st){
        st.style.display = 'inline-block';
        setTimeout(() => { st.style.display = 'none'; }, 3000);
      }
      if(abaPreviewAtual !== 'frame'){
        await renderizarPreviewCartela(abaPreviewAtual);
      }
    }
  } catch(e) {
    console.error('Erro ao salvar fundo:', e);
  } finally {
    if(loadEl) loadEl.style.display = 'none';
  }
}

async function restaurarFundoPadrao(){
  if(!confirm('Restaurar imagem de fundo padrão das cartelas?')) return;
  const loadEl = $('#loadingFundoPreview');
  if(loadEl) loadEl.style.display = 'flex';
  try {
    await fetch('/api/cartelas/fundo/restaurar', {method: 'POST'});
    aplicarPresetFundo('original');
    $('#imgFundoPreview').src = '/web/icon.png';
    $('#imgCartelaRenderPreview').style.display = 'none';
    $('#imgFundoPreview').style.display = 'block';
    $('#overlayFundoPreview').style.display = 'block';
    alert('Fundo restaurado para o padrão original de transmissão.');
  } catch(e) {
    console.error(e);
  } finally {
    if(loadEl) loadEl.style.display = 'none';
  }
}

async function aplicarPresetFundo(tipo){
  // delega ao sistema por câmera (câmera 0 = câmera 1 = principal)
  const pid = tipo in _camPresetValues ? tipo
    : (tipo==='vivido'?'claro_vivido':tipo==='noturno'?'super_claro':tipo==='sportv'?'tv':tipo==='padrao'?'original':'claro_vivido');
  await aplicarPresetCam(0, pid);
}

function carregarFramePredefinido(tempo_s){
  capturarFrameFundo(tempo_s);
}

async function renderizarPreviewCartela(tipo){
  const loadEl = $('#loadingFundoPreview');
  if(loadEl) loadEl.style.display = 'flex';
  try {
    const temaSel = document.querySelector('.tema-card.sel');
    const tema = temaSel ? (temaSel.dataset.tema || 'atual') : 'atual';
    const prevImg = $('#imgCartelaRenderPreview');
    prevImg.src = `/api/cartelas/preview/${tipo}?tema=${tema}&t=${Date.now()}`;
    prevImg.onload = () => {
      prevImg.style.display = 'block';
      $('#imgFundoPreview').style.display = 'none';
      $('#overlayFundoPreview').style.display = 'none';
      if(loadEl) loadEl.style.display = 'none';
    };
    prevImg.onerror = () => {
      if(loadEl) loadEl.style.display = 'none';
      alert('Não foi possível renderizar a prévia desta cartela.');
    };
  } catch(e) {
    if(loadEl) loadEl.style.display = 'none';
  }
}

async function trocarAbaPreviewFundo(aba){
  abaPreviewAtual = aba;
  ['tabPrevFundo', 'tabPrevPlacar', 'tabPrevAbertura', 'tabPrevFim', 'tabPrevDestaques', 'tabPrevRecomendados'].forEach(id => {
    const btn = $('#' + id);
    if(btn) btn.classList.remove('active');
  });
  if(aba === 'frame'){
    $('#tabPrevFundo').classList.add('active');
    $('#imgCartelaRenderPreview').style.display = 'none';
    $('#imgFundoPreview').style.display = 'block';
    $('#overlayFundoPreview').style.display = 'block';
  } else {
    if(aba === 'placar') $('#tabPrevPlacar').classList.add('active');
    else if(aba === 'abertura') $('#tabPrevAbertura').classList.add('active');
    else if(aba === 'fim_de_jogo') $('#tabPrevFim').classList.add('active');
    else if(aba === 'destaques') $('#tabPrevDestaques').classList.add('active');
    else if(aba === 'assista_outros_videos') $('#tabPrevRecomendados').classList.add('active');
    await salvarFundoCartela(true);
    await renderizarPreviewCartela(aba);
  }
}

function renderResumo(){
  const v = validos();
  const gm = golsMarcados();
  const a = v.filter(g=>g.time===0).length, b = v.filter(g=>g.time===1).length;
  $('#placar').innerHTML = `<span style="color:${S.times[0].cor}">${a}</span> × <span style="color:${S.times[1].cor}">${b}</span>`;
  const l = lances();
  $('#subPlacar').textContent = `${S.times[0].nome} × ${S.times[1].nome} · ${v.length} gols marcados (${gm.length} identificados)`
    + (l.length?` · ${l.length} melhores momentos`:'') + ` · ${v.length+l.length} clipes no vídeo final`;

  const cardComp = $('#cardComparacaoPlacar');
  const pJogo = S.meta.placar_jogo;
  if(pJogo && (pJogo[0] != null || pJogo[1] != null)){
    const espA = pJogo[0] != null ? pJogo[0] : 0;
    const espB = pJogo[1] != null ? pJogo[1] : 0;
    const totalEsp = espA + espB;
    const diffA = espA - a;
    const diffB = espB - b;
    const totalAchados = a + b;
    const diffTotal = totalEsp - totalAchados;

    let msgStatus = '';
    let corBorda = 'var(--accent)';
    if(diffTotal === 0 && diffA === 0 && diffB === 0){
      msgStatus = '<span class="ok" style="font-size:14px; font-weight:700">✓ Todos os gols do placar foram encontrados e marcados!</span>';
    } else {
      corBorda = 'var(--b)';
      const faltamMsg = [];
      if(diffA > 0) faltamMsg.push(`faltam <b>${diffA} gol(s)</b> do ${S.times[0].nome}`);
      else if(diffA < 0) faltamMsg.push(`há <b>${-diffA} gol(s) a mais</b> do ${S.times[0].nome}`);
      if(diffB > 0) faltamMsg.push(`faltam <b>${diffB} gol(s)</b> do ${S.times[1].nome}`);
      else if(diffB < 0) faltamMsg.push(`há <b>${-diffB} gol(s) a mais</b> do ${S.times[1].nome}`);

      msgStatus = `<span style="color:var(--b); font-size:14px; font-weight:700">⚠ Placar informado: ${espA} × ${espB} (${totalEsp} gols). Marcados nos clipes: ${a} × ${b} (${totalAchados} gols).</span>
        <div style="margin-top:6px; font-size:13px; color:var(--txt)">${faltamMsg.join(' e ')}.</div>
        <div class="hint" style="margin-top:4px">Dica: Volte ao <a href="javascript:void(0)" onclick="irPara('s-revisar')" style="color:var(--accent); font-weight:600">Passo 4 (Revisar cortes)</a> para assistir ao vídeo completo na velocidade que desejar e gerar os clipes faltantes.</div>`;
    }

    cardComp.innerHTML = `
      <div class="card" style="border-left: 5px solid ${corBorda}; padding:14px">
        <div style="font-size:11px; text-transform:uppercase; letter-spacing:.8px; color:var(--dim); font-weight:700">Conferência do Placar da Partida</div>
        <div style="margin-top:8px">${msgStatus}</div>
      </div>
    `;
    cardComp.style.display = 'block';
  } else {
    cardComp.innerHTML = `
      <div class="card" style="border-left: 4px solid var(--line); padding:12px">
        <div class="hint">💡 Você não informou o placar final do jogo no <a href="javascript:void(0)" onclick="irPara('s-dados')" style="color:var(--accent)">Passo 5 (Dados da partida)</a>. Se preencher lá, o assistente confere quantos gols faltam encontrar no vídeo.</div>
      </div>
    `;
    cardComp.style.display = 'block';
  }

  const medalhas=['🥇','🥈','🥉'];
  const pod=(el,dados,rot)=>{
    $(el).innerHTML = dados.slice(0,3).map((d, i)=>{
      const nm = d[0], qtd = d[1];
      const avHtml = obterAvatarJogadorHtml(nm, 54);
      return `
        <div class="pod">
          <div class="p">${medalhas[i]}</div>
          <div style="margin:8px auto 6px; display:flex; justify-content:center">${avHtml}</div>
          <div class="nm">${nm}</div>
          <div class="v">${qtd} ${rot}</div>
        </div>
      `;
    }).join('') || `<div class="pod" style="grid-column:1/-1"><div class="hint">sem dados</div></div>`;
  };
  pod('#podGols', contar('autor'), 'gols');
  pod('#podAssist', contar('assist'), 'assist.');

  const tabela=(el,dados,rot)=>{
    $(el).innerHTML = '<tr><th>Jogador</th><th style="text-align:right">'+rot+'</th></tr>' +
      (dados.map(d=>{
        const nm = d[0], qtd = d[1];
        const avHtml = obterAvatarJogadorHtml(nm, 28);
        return `<tr>
          <td><div class="resumo-player-cell">${avHtml} <span style="font-weight:600">${nm}</span></div></td>
          <td class="n" style="font-weight:800">${qtd}</td>
        </tr>`;
      }).join('') || '<tr><td colspan="2" class="hint">sem dados</td></tr>');
  };
  tabela('#tbGols', contar('autor'), 'Gols');
  tabela('#tbAssist', contar('assist'), 'Assist.');

  const todosCrono = [
    ...v.map(g => ({...g, tipoEvento: 'gol'})),
    ...l.map(g => ({...g, tipoEvento: 'lance'}))
  ].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a), tB = obterTempoSegundosClipe(b);
    return (tA !== -1 && tB !== -1) ? (tA - tB) : ((a.indice||0) - (b.indice||0));
  });

  $('#tbCrono').innerHTML = '<tr><th>#</th><th>Tempo</th><th>Time</th><th>Lance / Gol</th><th>Assistência / Detalhes</th></tr>' +
    (todosCrono.map((g, idx)=>{
      if(g.tipoEvento === 'gol'){
        const t = S.times[g.time];
        const cor = t ? t.cor : 'var(--accent)';
        const nomeTime = t ? t.nome : 'Time';
        const avAutor = g.autor ? obterAvatarJogadorHtml(g.autor, 28, g.time) : '';
        const avAssist = g.assist ? obterAvatarJogadorHtml(g.assist, 24, g.time) : '';
        return `<tr>
          <td><b>${idx + 1}</b></td>
          <td><b>${g.tempo}</b></td>
          <td><span class="teamtag" style="background:${cor};color:${corTextoParaFundo(cor)}">${nomeTime}</span></td>
          <td>
            <div style="display:flex; align-items:center; gap:8px">
              ${avAutor}
              <span>⚽ <b>GOL: ${g.autor}</b></span>
            </div>
          </td>
          <td>
            ${g.assist ? `<div style="display:flex; align-items:center; gap:6px">${avAssist} <span>assistência: <b>${g.assist}</b></span></div>` : '—'}
          </td>
        </tr>`;
      } else {
        const t = (g.time !== null && g.time !== undefined && S.times[g.time]) ? S.times[g.time] : null;
        const timeTag = t ? `<span class="teamtag" style="background:${t.cor};color:${corTextoParaFundo(t.cor)}">${t.nome}</span>` : '<span class="hint">lance</span>';
        const autorOuLance = g.autor || g.destaque;
        const avDestaque = autorOuLance ? obterAvatarJogadorHtml(autorOuLance, 26, g.time) : '';
        return `<tr>
          <td><b>${idx + 1}</b></td>
          <td><b>${g.tempo}</b></td>
          <td>${timeTag}</td>
          <td colspan="2">
            <div style="display:flex; align-items:center; gap:8px">
              ${avDestaque}
              <span>${g.lance || 'Melhor momento'}${g.destaque ? ' — <b>' + g.destaque + '</b>' : ''}</span>
            </div>
          </td>
        </tr>`;
      }
    }).join('') || '<tr><td colspan="5" class="hint">nenhum gol ou lance marcado ainda</td></tr>');

  // Inicialização do controle de fundo das cartelas
  if(!window._fundoCartelasInitDone){
    window._fundoCartelasInitDone = true;

    $('#btnSalvarFundoCartela').onclick = () => salvarFundoCartelaCam(0, false);
    $('#btnRestaurarFundoPadrao').onclick = restaurarFundoPadrao;

    // Carrega configs salvas por câmera
    if(!Array.isArray(ESTADO.configCameras)) ESTADO.configCameras = [null,null,null];
    if(S.meta && S.meta.config_cameras && Array.isArray(S.meta.config_cameras)){
      S.meta.config_cameras.slice(0,3).forEach((cfg,i)=>{
        if(cfg && typeof cfg==='object') ESTADO.configCameras[i]={..._cfgCamDef(),...cfg};
      });
    } else if(S.meta && S.meta.fundo_config){
      // migra config legada para câmera 0
      const fc=S.meta.fundo_config, cfg=_cfgCam(0);
      if(fc.brilho    !=null) cfg.brilho    =Math.round(fc.brilho*100);
      if(fc.saturacao !=null) cfg.saturacao =Math.round(fc.saturacao*100);
      if(fc.contraste !=null) cfg.contraste =Math.round(fc.contraste*100);
      if(fc.desfoque  !=null) cfg.desfoque  =fc.desfoque;
      if(fc.vinheta   !=null) cfg.vinheta   =fc.vinheta;
      if(fc.aplicar_video_clipes!=null) cfg.aplicar_clipes=fc.aplicar_video_clipes;
      if(fc.tempo_s   !=null){ cfg.tempo_s=fc.tempo_s; tempoFundoSegundos=fc.tempo_s; }
    }
  }

  // Renderiza (ou re-renderiza) os 3 painéis de câmera lado a lado
  renderGridCamerasFundo();

  // Atalho para o 1º gol marcado
  const pGol = validos()[0];
  if(pGol){
    const tGol = obterTempoSegundosClipe(pGol);
    if(tGol > 0){
      const btnGol = $('#btnFrameGolDestaque');
      if(btnGol){
        btnGol.textContent = `⚽ Gol 1 (${fmtTempo(tGol)})`;
        btnGol.onclick = () => capturarFrameCam(0, tGol);
      }
    }
  }

  atualizarFiltrosCssFundo();
  atualizarPrevisaoDuracao();
}

function atualizarPrevisaoDuracao(){
  const elMelhores = $('#durEstMelhores');
  const elGols = $('#durEstGols');
  const detMelhores = $('#detEstMelhores');
  const detGols = $('#detEstGols');
  if(!elMelhores || !elGols) return;

  const ab = ($('#semAbertura') && $('#semAbertura').checked) ? 0 : (parseFloat($('#abertura').value) || 7);
  const fech = ($('#semFechamento') && $('#semFechamento').checked) ? 0 : ((parseFloat($('#fechamento').value) || 8) * 3);

  const todosGols = validos();
  const todosLances = lances();
  const totalClipes = [...todosGols, ...todosLances];

  // Inclui a tela final fixa de 30s que convida a assistir os outros vídeos.
  let durTotalMelhores = ab + fech + 30;
  totalClipes.forEach(c => {
    let d = (c.fim_s != null && c.inicio_s != null && c.fim_s > c.inicio_s) ? (c.fim_s - c.inicio_s) : 24;
    durTotalMelhores += d;
  });

  let durTotalGols = ab + fech + 30;
  todosGols.forEach(c => {
    let d = (c.fim_s != null && c.inicio_s != null && c.fim_s > c.inicio_s) ? (c.fim_s - c.inicio_s) : 24;
    durTotalGols += d;
  });

  const mMelhores = Math.floor(durTotalMelhores / 60);
  const sMelhores = Math.round(durTotalMelhores % 60);
  elMelhores.textContent = `${mMelhores}min ${String(sMelhores).padStart(2,'0')}s`;
  if(detMelhores) detMelhores.textContent = `${totalClipes.length} clipes (${todosGols.length} gols + ${todosLances.length} lances)`;

  const mGols = Math.floor(durTotalGols / 60);
  const sGols = Math.round(durTotalGols % 60);
  elGols.textContent = `${mGols}min ${String(sGols).padStart(2,'0')}s`;
  if(detGols) detGols.textContent = `${todosGols.length} gols com cartelas oficiais`;
}

function fmtTempoYoutube(segundos){
  const total = Math.max(0, Math.round(Number(segundos) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h
    ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function duracaoDoClipeFinal(clipe){
  if(clipe && clipe.duracao_s != null && Number(clipe.duracao_s) > 0){
    return Number(clipe.duracao_s);
  }
  if(clipe && clipe.fim_s != null && clipe.inicio_s != null && clipe.fim_s > clipe.inicio_s){
    return clipe.fim_s - clipe.inicio_s;
  }
  return 24;
}

function gerarComentarioYoutube(apenasGols=false, jogador=null){
  const todos = [...validos(), ...lances()];
  const porIndice = new Map(todos.map(c => [Number(c.indice), c]));
  const idsSalvos = ESTADO.roteiroFinal || (S.meta && S.meta.roteiro_final);
  let ordem = Array.isArray(idsSalvos) && idsSalvos.length
    ? idsSalvos.map(i => porIndice.get(Number(i))).filter(Boolean)
    : todos.sort((a, b) => {
        const ta = obterTempoSegundosClipe(a), tb = obterTempoSegundosClipe(b);
        return (ta !== -1 && tb !== -1) ? ta - tb : (a.indice || 0) - (b.indice || 0);
      });
  if(apenasGols) ordem = ordem.filter(c => c.tipo === 'gol' || c.status === 'gol');
  if(jogador) ordem = ordem.filter(c => c.autor === jogador || c.assist === jogador || c.destaque === jogador);
  const opcoes = ESTADO.opcoesMontagemFinal || (S.meta && S.meta.opcoes_montagem_final) || {};
  const temAbertura = opcoes.sem_abertura !== undefined ? !opcoes.sem_abertura : !$('#semAbertura').checked;
  const durAbertura = temAbertura ? (Number(opcoes.abertura ?? $('#abertura').value) || 7) : 0;
  const nomeJogo = `${S.times[0].nome} × ${S.times[1].nome}`;
  const titulo = jogador ? `Melhores Momentos · ${jogador}` : (apenasGols ? 'Apenas Gols' : 'Melhores Momentos');
  const linhas = [`${nomeJogo} — ${titulo}`, '', '⏱️ CAPÍTULOS DO VÍDEO'];
  let tempoVideo = 0;
  if(temAbertura){
    linhas.push(`${fmtTempoYoutube(tempoVideo)} Abertura`);
    tempoVideo += durAbertura;
  }
  ordem.forEach(c => {
    const ehGol = c.tipo === 'gol' || c.status === 'gol';
    const time = (c.time !== null && c.time !== undefined && S.times[c.time]) ? S.times[c.time].nome : '';
    let descricao = '';
    if(ehGol){
      descricao = `⚽ GOL${time ? ` — ${time}` : ''}${c.autor ? ` · ${c.autor}` : ''}${c.assist ? ` (assistência: ${c.assist})` : ''}`;
    } else {
      descricao = `🎬 ${c.lance || 'Melhor momento'}${time ? ` — ${time}` : ''}${c.destaque ? ` · ${c.destaque}` : ''}`;
    }
    linhas.push(`${fmtTempoYoutube(tempoVideo)} ${descricao}`);
    tempoVideo += duracaoDoClipeFinal(c) * ((Array.isArray(c.cameras_clipe) && c.cameras_clipe.length) || 1);
  });
  return linhas.join('\n');
}

async function copiarComentarioYoutube(campoId, botaoId){
  const campo = $('#' + campoId);
  const botao = $('#' + botaoId);
  if(!campo || !botao) return;
  try {
    await navigator.clipboard.writeText(campo.value);
  } catch(e){
    campo.select();
    document.execCommand('copy');
  }
  const original = botao.textContent;
  botao.textContent = '✓ Copiado para o YouTube';
  setTimeout(() => { botao.textContent = original; }, 2500);
}

function ajustarAlturaDescricaoYoutube(campo){
  if(!campo) return;
  campo.style.height = 'auto';
  campo.style.height = `${Math.max(220, campo.scrollHeight + 2)}px`;
}

function atualizarDescricoesYoutube(){
  const textoMelhoresYoutube = $('#textoMelhoresYoutube');
  if(textoMelhoresYoutube){
    textoMelhoresYoutube.value = gerarComentarioYoutube(false);
    ajustarAlturaDescricaoYoutube(textoMelhoresYoutube);
  }
  const textoGolsYoutube = $('#textoGolsYoutube');
  if(textoGolsYoutube){
    textoGolsYoutube.value = gerarComentarioYoutube(true);
    ajustarAlturaDescricaoYoutube(textoGolsYoutube);
  }
}

function renderResultadosVideosFinais(){
  $('#resultadoFinal').innerHTML = `
    <div style="background:linear-gradient(135deg, rgba(0,255,135,0.12) 0%, rgba(14,23,36,0.95) 100%); border:1.5px solid var(--accent); border-radius:12px; padding:16px 20px; margin-top:14px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; box-shadow:0 0 25px rgba(0,255,135,0.2)">
      <div style="display:flex; align-items:center; gap:14px">
        <span style="font-size:32px; filter:drop-shadow(0 2px 8px rgba(0,255,135,0.5))">🏆</span>
        <div>
          <div style="display:flex; align-items:center; gap:8px">
            <span style="font-size:16px; font-weight:800; color:var(--accent)">Vídeos Finais Prontos em Full HD!</span>
            <span style="background:var(--accent); color:#04140a; font-size:10px; font-weight:900; padding:2px 8px; border-radius:10px">1080p Broadcast</span>
          </div>
          <div style="font-size:12px; color:var(--dim); margin-top:2px">Melhores Momentos e Apenas Gols gerados com sucesso. Assista ou baixe abaixo:</div>
        </div>
      </div>
      <button type="button" class="act" onclick="mostrarAlertaRenderizacaoConcluida()" style="font-size:12px; padding:8px 16px; border-radius:8px; display:flex; align-items:center; gap:6px; font-weight:800" title="Reabrir alerta de comemoração e opções de download">
        <span>🎉</span> Ver Notificação Completa
      </button>
    </div>

    <div style="display:flex; justify-content:flex-end; margin-top:14px">
      <button type="button" id="btnAtualizarDescricoesYoutube" class="ghost" style="font-size:12px; padding:8px 12px">↻ Atualizar textos do YouTube</button>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:8px">
      <div class="card" style="margin:0; background:var(--panel2); border:1px solid var(--line-bright)">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
          <h3 style="margin:0; font-size:14px; color:var(--accent); display:flex; align-items:center; gap:6px">
            <span>🎬</span> Melhores Momentos (Gols + Lances)
          </h3>
          <span id="durRealMelhores" style="font-size:12px; font-weight:800; color:var(--accent); background:rgba(0,255,135,0.12); padding:2px 8px; border-radius:6px; border:1px solid rgba(0,255,135,0.3)">⏱ 17min 45s</span>
        </div>
        <video id="videoPlayerMelhoresMomentos" src="/video/final" poster="/video/final/capa/melhores_momentos.mp4?t=${Date.now()}" controls style="border-radius:8px; width:100%; max-height:280px; background:#000"></video>
        <div class="row" style="margin-top:10px">
          <a class="act" style="text-decoration:none; display:inline-flex; align-items:center; justify-content:center; gap:6px; width:100%; text-align:center; font-size:13px; padding:10px 14px; border-radius:8px" href="/video/final" download>⬇ Baixar melhores_momentos.mp4</a>
        </div>
      </div>
      <div class="card" style="margin:0; background:var(--panel2); border:1px solid var(--line-bright)">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
          <h3 style="margin:0; font-size:14px; color:var(--accent); display:flex; align-items:center; gap:6px">
            <span>⚽</span> Apenas Gols
          </h3>
          <span id="durRealGols" style="font-size:12px; font-weight:800; color:var(--gold-light); background:rgba(255,215,0,0.12); padding:2px 8px; border-radius:6px; border:1px solid rgba(255,215,0,0.3)">⏱ 7min 46s</span>
        </div>
        <video id="videoPlayerApenasGols" src="/video/final/gols" poster="/video/final/capa/apenas_gols.mp4?t=${Date.now()}" controls style="border-radius:8px; width:100%; max-height:280px; background:#000"></video>
        <div class="row" style="margin-top:10px">
          <a class="act" style="text-decoration:none; display:inline-flex; align-items:center; justify-content:center; gap:6px; width:100%; text-align:center; font-size:13px; padding:10px 14px; border-radius:8px" href="/video/final/gols" download>⬇ Baixar apenas_gols.mp4</a>
        </div>
      </div>
    </div>

    <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px">
      <div class="card" style="margin:0; border:1px solid rgba(0,255,135,0.45); background:linear-gradient(135deg, rgba(0,255,135,0.08), var(--panel2))">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-bottom:8px">
          <div>
            <h3 style="margin:0; font-size:15px; color:var(--accent)">🎬 Descrição · Melhores Momentos</h3>
            <div style="font-size:12px; color:var(--dim); margin-top:3px">Todos os gols e lances, com o início de cada clipe.</div>
          </div>
          <button type="button" id="btnCopiarMelhoresYoutube" class="act" style="font-size:12px; padding:9px 12px">📋 Copiar</button>
        </div>
        <textarea id="textoMelhoresYoutube" readonly aria-label="Descrição dos melhores momentos para YouTube" style="width:100%; min-height:220px; resize:vertical; box-sizing:border-box; background:#070d16; color:#edf7ff; border:1px solid var(--line-bright); border-radius:8px; padding:11px; font:13px/1.55 monospace"></textarea>
      </div>
      <div class="card" style="margin:0; border:1px solid rgba(255,215,0,0.45); background:linear-gradient(135deg, rgba(255,215,0,0.08), var(--panel2))">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-bottom:8px">
          <div>
            <h3 style="margin:0; font-size:15px; color:var(--gold-light)">⚽ Descrição · Apenas Gols</h3>
            <div style="font-size:12px; color:var(--dim); margin-top:3px">Somente gols, no horário em que começam neste vídeo.</div>
          </div>
          <button type="button" id="btnCopiarGolsYoutube" class="act" style="font-size:12px; padding:9px 12px">📋 Copiar</button>
        </div>
        <textarea id="textoGolsYoutube" readonly aria-label="Descrição dos gols para YouTube" style="width:100%; min-height:220px; resize:vertical; box-sizing:border-box; background:#070d16; color:#edf7ff; border:1px solid var(--line-bright); border-radius:8px; padding:11px; font:13px/1.55 monospace"></textarea>
      </div>
    </div>
    <div id="arquivosFinaisExtras" style="margin-top:14px"></div>
  `;

  atualizarDescricoesYoutube();
  const btnAtualizarDescricoes = $('#btnAtualizarDescricoesYoutube');
  if(btnAtualizarDescricoes) btnAtualizarDescricoes.onclick = () => {
    atualizarDescricoesYoutube();
    btnAtualizarDescricoes.textContent = '✓ Textos atualizados';
    setTimeout(() => { btnAtualizarDescricoes.textContent = '↻ Atualizar textos do YouTube'; }, 1800);
  };
  const btnCopiarMelhores = $('#btnCopiarMelhoresYoutube');
  if(btnCopiarMelhores) btnCopiarMelhores.onclick = () => copiarComentarioYoutube('textoMelhoresYoutube', 'btnCopiarMelhoresYoutube');
  const btnCopiarGols = $('#btnCopiarGolsYoutube');
  if(btnCopiarGols) btnCopiarGols.onclick = () => copiarComentarioYoutube('textoGolsYoutube', 'btnCopiarGolsYoutube');
  carregarVideosFinaisSalvos();

  const vm = $('#videoPlayerMelhoresMomentos');
  if(vm){
    vm.onloadedmetadata = () => {
      if(vm.duration && !isNaN(vm.duration)){
        const m = Math.floor(vm.duration / 60);
        const s = Math.round(vm.duration % 60);
        const el = $('#durRealMelhores');
        if(el) el.textContent = `⏱ ${m}min ${String(s).padStart(2,'0')}s`;
      }
    };
  }
  const vg = $('#videoPlayerApenasGols');
  if(vg){
    vg.onloadedmetadata = () => {
      if(vg.duration && !isNaN(vg.duration)){
        const m = Math.floor(vg.duration / 60);
        const s = Math.round(vg.duration % 60);
        const el = $('#durRealGols');
        if(el) el.textContent = `⏱ ${m}min ${String(s).padStart(2,'0')}s`;
      }
    };
  }
}

function inicializarSeletorQualidade(){
  const savedCrf = localStorage.getItem('futbin_perfil_qualidade') || '24';
  const cards = document.querySelectorAll('.perfil-qualidade-card');
  const badge = document.getElementById('badgeTamanhoEstimado');

  cards.forEach(card => {
    if(card.dataset.crf === savedCrf){
      cards.forEach(c => {
        c.classList.remove('sel');
        c.style.borderColor = 'var(--line)';
        c.style.background = 'var(--panel)';
      });
      card.classList.add('sel');
      card.style.borderColor = 'var(--accent)';
      card.style.background = 'rgba(0,255,135,0.08)';
      if(badge) badge.textContent = card.dataset.estimativa;
    }

    card.onclick = () => {
      cards.forEach(c => {
        c.classList.remove('sel');
        c.style.borderColor = 'var(--line)';
        c.style.background = 'var(--panel)';
      });
      card.classList.add('sel');
      card.style.borderColor = 'var(--accent)';
      card.style.background = 'rgba(0,255,135,0.08)';
      if(badge) badge.textContent = card.dataset.estimativa;
      localStorage.setItem('futbin_perfil_qualidade', card.dataset.crf);
    };
  });

  // Inicializa seletor de temas
  const savedTema = localStorage.getItem('futbin_tema') || 'atual';
  const temaCards = document.querySelectorAll('.tema-card');
  const temaColors = { atual:'var(--accent)', fifa:'#ffd700', iss:'#ffff00', pes:'#38bdf8', tv:'#a78bfa' };
  const temaTextColors = { atual:'var(--accent)', fifa:'#ffd700', iss:'#cccc00', pes:'#38bdf8', tv:'#a78bfa' };
  temaCards.forEach(tc => {
    const cor = temaColors[tc.dataset.tema] || 'var(--accent)';
    const txtCor = temaTextColors[tc.dataset.tema] || 'var(--accent)';
    // Aplica estado salvo
    if(tc.dataset.tema === savedTema){
      temaCards.forEach(x => {
        x.classList.remove('sel');
        x.style.borderColor = 'var(--line)';
        x.style.background = 'var(--panel)';
        x.style.color = 'var(--dim)';
      });
      tc.classList.add('sel');
      tc.style.borderColor = cor;
      tc.style.background = `${cor}18`;
      tc.style.color = txtCor;
    }
    tc.onclick = () => {
      temaCards.forEach(x => {
        x.classList.remove('sel');
        x.style.borderColor = 'var(--line)';
        x.style.background = 'var(--panel)';
        x.style.color = 'var(--dim)';
      });
      tc.classList.add('sel');
      tc.style.borderColor = cor;
      tc.style.background = `${cor}18`;
      tc.style.color = txtCor;
      localStorage.setItem('futbin_tema', tc.dataset.tema);
      // Re-renderiza a aba atual se não for o frame
      if(abaPreviewAtual && abaPreviewAtual !== 'frame'){
        renderizarPreviewCartela(abaPreviewAtual);
      }
    };
  });
}

async function carregarVideosFinaisSalvos(){
  const el = $('#arquivosFinaisExtras');
  if(!el) return;
  try {
    const r = await fetch('/api/videos/finais');
    const dados = await r.json();
    const extras = (dados.videos || []).filter(v => !['melhores_momentos.mp4', 'apenas_gols.mp4'].includes(v.nome));
    if(!extras.length){ el.innerHTML = ''; return; }
    el.innerHTML = `<div class="card" style="margin:0"><h3 style="margin:0 0 9px; font-size:14px">📁 Vídeos já gerados e salvos</h3>${extras.map(v => `<div class="row" style="justify-content:space-between; gap:10px; border-top:1px solid var(--line); padding:8px 0"><span style="font-size:12px; overflow:hidden; text-overflow:ellipsis">${v.nome}</span><a class="ghost" href="${v.url}" download style="text-decoration:none; white-space:nowrap">⬇ Baixar</a></div>`).join('')}</div>`;
  } catch(e) { el.innerHTML = ''; }
}

function atualizarJogadoresDestaques(){
  const sel = $('#selJogadorDestaques');
  if(!sel) return;
  const atual = sel.value;
  const nomes = new Set();
  // Também mostra quem esteve escalado, mesmo que ainda não tenha uma jogada
  // marcada. Assim a tela de estatísticas representa todos os jogadores.
  (S.times || []).forEach(time => (time.jogadores || []).forEach(j => {
    const nome = typeof j === 'string' ? j : j.nome;
    if(nome) nomes.add(nome);
  }));
  [...validos(), ...lances()].forEach(c => [c.autor, c.assist, c.destaque].forEach(n => { if(n) nomes.add(n); }));
  sel.innerHTML = '<option value="">Escolha um jogador</option>';
  [...nomes].sort((a,b) => a.localeCompare(b, 'pt-BR')).forEach(nome => {
    const op = document.createElement('option'); op.value = nome; op.textContent = nome; sel.appendChild(op);
  });
  if(nomes.has(atual)) sel.value = atual;
}
$('#selJogadorDestaques').onfocus = atualizarJogadoresDestaques;

function renderTelaJogador(){
  atualizarJogadoresDestaques();
  carregarVideosJogadoresSalvos();
  const sel = $('#selJogadorDestaques');
  atualizarPreviaJogador(sel ? sel.value : '');
  if(sel && sel.value) renderEstatisticasJogador(sel.value);
  else $('#estatisticasJogador').innerHTML = '<div class="card"><div class="hint">Escolha um jogador acima para ver as estatísticas dele nesta partida.</div></div>';
}

function renderEstatisticasJogador(jogador){
  const destino = $('#estatisticasJogador');
  if(!destino) return;
  const eventos = [...validos(), ...lances()]
    .filter(c => c.autor === jogador || c.assist === jogador || c.destaque === jogador)
    .sort((a,b) => obterTempoSegundosClipe(a) - obterTempoSegundosClipe(b));
  const gols = validos().filter(c => c.autor === jogador);
  const assistencias = validos().filter(c => c.assist === jogador);
  const lancesDestaque = lances().filter(c => c.autor === jogador || c.assist === jogador || c.destaque === jogador);
  const timeIndice = S.times.findIndex(time => (time.jogadores || []).some(j => (typeof j === 'string' ? j : j.nome) === jogador));
  const avatar = obterAvatarJogadorHtml(jogador, 58, timeIndice >= 0 ? timeIndice : null);
  const linhaEvento = c => {
    const eGol = c.tipo === 'gol' || c.status === 'gol';
    const descricao = eGol ? `⚽ Gol${c.assist ? ` · assistência: ${c.assist}` : ''}` : `🎬 ${c.lance || 'Melhor momento'}`;
    const papel = c.autor === jogador ? (eGol ? 'Autor' : 'Em destaque') : (c.assist === jogador ? 'Assistência' : 'Em destaque');
    return `<tr><td><b>${c.tempo || fmtTempo(obterTempoSegundosClipe(c))}</b></td><td>${descricao}</td><td><span class="hint">${papel}</span></td></tr>`;
  };
  destino.innerHTML = `
    <div class="card" style="margin:0; border-color:rgba(0,240,255,.45)">
      <div class="row" style="gap:12px; align-items:center; margin-bottom:13px">${avatar}<div><b style="font-size:18px; color:#00f0ff">${jogador}</b><div class="hint">Resumo individual da partida</div></div></div>
      <div style="display:grid; grid-template-columns:repeat(4,minmax(105px,1fr)); gap:9px">
        <div class="card" style="margin:0; padding:10px; text-align:center"><b style="font-size:23px; color:var(--accent)">${gols.length}</b><div class="hint">gols</div></div>
        <div class="card" style="margin:0; padding:10px; text-align:center"><b style="font-size:23px; color:var(--gold-light)">${assistencias.length}</b><div class="hint">assistências</div></div>
        <div class="card" style="margin:0; padding:10px; text-align:center"><b style="font-size:23px; color:#00f0ff">${lancesDestaque.length}</b><div class="hint">lances</div></div>
        <div class="card" style="margin:0; padding:10px; text-align:center"><b style="font-size:23px">${eventos.length}</b><div class="hint">clipes no vídeo</div></div>
      </div>
      <div style="margin-top:14px; font-weight:700; font-size:13px">Todos os lances do jogador</div>
      <table style="margin-top:7px"><tr><th>Tempo</th><th>Lance</th><th>Participação</th></tr>${eventos.map(linhaEvento).join('') || '<tr><td colspan="3" class="hint">Nenhum lance marcado para este jogador.</td></tr>'}</table>
    </div>`;
}

$('#selJogadorDestaques').onchange = function(){ renderEstatisticasJogador(this.value); atualizarPreviaJogador(this.value); };

$('#btnTextoJogador').onclick = ()=>{
  const jogador = $('#selJogadorDestaques').value;
  const resultado = $('#resultadoJogador');
  if(!jogador){ alert('Escolha o jogador primeiro.'); return; }
  const texto = gerarComentarioYoutube(false, jogador);
  const linhas = texto.split('\n').filter(Boolean);
  if(linhas.length <= 2){ resultado.textContent = 'Não há lances marcados para este jogador.'; return; }
  resultado.innerHTML = `<div style="display:flex; justify-content:space-between; gap:8px; margin:8px 0"><b>📝 Texto de ${jogador}</b><button type="button" class="act" id="btnCopiarTextoJogador" style="font-size:11px; padding:5px 9px">📋 Copiar</button></div><textarea id="textoJogadorYoutube" readonly style="width:100%; min-height:180px; box-sizing:border-box; background:#070d16; color:#edf7ff; border:1px solid var(--line-bright); border-radius:8px; padding:9px; font:12px/1.5 monospace"></textarea>`;
  const campo = $('#textoJogadorYoutube'); campo.value = texto; ajustarAlturaDescricaoYoutube(campo);
  $('#btnCopiarTextoJogador').onclick = () => copiarComentarioYoutube('textoJogadorYoutube', 'btnCopiarTextoJogador');
};

async function carregarMarcacoesSalvasParaTextos(){
  const r = await fetch('/api/partida');
  if(!r.ok) return;
  const partida = await r.json();
  if(!partida) return;
  S.meta = partida.meta || S.meta;
  S.times = partida.times || S.times;
  // A cópia salva no momento da geração é a fonte dos capítulos, mesmo após recarregar a página.
  ESTADO.gols = partida._todosGols || [...(partida.gols || []), ...(partida.lances || [])];
}

$('#btnGerarTextosYoutube').onclick = async ()=>{
  try { await carregarMarcacoesSalvasParaTextos(); } catch(e) {}
  renderResultadosVideosFinais();
  const destino = $('#textoMelhoresYoutube');
  if(destino) destino.scrollIntoView({behavior:'smooth', block:'start'});
};

async function carregarVideosJogadoresSalvos(){
  const el = $('#videosJogadoresSalvos');
  if(!el) return;
  try {
    const r = await fetch('/api/videos/jogadores');
    const dados = await r.json();
    const videos = dados.videos || [];
    if(!videos.length){ el.innerHTML = ''; return; }
    el.innerHTML = `<div style="border-top:1px solid var(--line); padding-top:9px"><b style="font-size:12px; color:var(--dim)">📁 VÍDEOS INDIVIDUAIS JÁ GERADOS</b>${videos.map(v => `<div class="row" style="justify-content:space-between; align-items:center; gap:8px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,.06)"><span style="font-size:13px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${v.nome}">⭐ ${v.nome.replace(/\.mp4$/i,'')}</span><span style="display:flex; gap:6px; flex-shrink:0"><button type="button" class="ghost" data-player-video="${encodeURI(decodeURI(v.url))}" style="font-size:12px; padding:6px 12px">▶ Ver</button><a class="ghost" href="${encodeURI(decodeURI(v.url))}" download style="font-size:12px; padding:6px 12px">⬇ Baixar</a></span></div>`).join('')}</div>`;
    el.querySelectorAll('[data-player-video]').forEach(btn => btn.onclick = () => {
      const url = btn.dataset.playerVideo;
      $('#resultadoJogador').innerHTML = `<video controls autoplay src="${url}" style="display:block; width:100%; max-width:960px; aspect-ratio:16/9; height:auto; margin:0 auto; border-radius:8px; background:#000"></video>`;
      $('#resultadoJogador').scrollIntoView({behavior:'smooth', block:'center'});
    });
  } catch(e) { el.innerHTML = ''; }
}

function mostrarAlertaVideoJogadorGerado(jogador, url){
  let container = document.getElementById('hudToastContainer');
  if(!container){
    container = document.createElement('div');
    container.id = 'hudToastContainer';
    container.className = 'hud-toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'hud-toast';
  toast.style.borderColor = '#00f0ff';
  toast.style.boxShadow = '0 16px 40px rgba(0,0,0,.85), 0 0 28px rgba(0,240,255,.45)';
  toast.innerHTML = `<div class="hud-toast-icon-wrap" style="border-color:#00f0ff; background:radial-gradient(circle, rgba(0,240,255,.25) 0%, transparent 70%)"><span>⭐</span><div class="hud-toast-check" style="background:#00f0ff;color:#041416">✓</div></div><div class="hud-toast-body"><div class="hud-toast-tag" style="color:#00f0ff">Vídeo individual pronto</div><div class="hud-toast-title">Melhores momentos de ${jogador}</div><div class="hud-toast-time">🎬 Prévia e descrição já estão disponíveis</div></div><div class="hud-toast-actions"><button type="button" class="hud-toast-btn-ver">👁️ Ver</button><button type="button" class="hud-toast-btn-close">✕</button></div><div class="hud-toast-timer-bar" style="background:linear-gradient(90deg,#00f0ff,var(--accent));animation-duration:10s"></div>`;
  const fechar = () => { if(!toast.classList.contains('saindo')){ toast.classList.add('saindo'); setTimeout(()=>toast.remove(),350); } };
  toast.querySelector('.hud-toast-btn-close').onclick = fechar;
  toast.querySelector('.hud-toast-btn-ver').onclick = () => { fechar(); $('#resultadoJogador').scrollIntoView({behavior:'smooth', block:'start'}); };
  container.appendChild(toast);
  setTimeout(fechar, 10000);
  try {
    if('Notification' in window && Notification.permission === 'granted'){
      new Notification(`⭐ Vídeo de ${jogador} pronto!`, {body:'A prévia, o download e os capítulos já estão na etapa 8.', icon:'/web/icon.png'});
    }
  } catch(e) {}
}

function mostrarResultadoVideoJogador(jogador, url){
  const resultado = $('#resultadoJogador');
  const texto = gerarComentarioYoutube(false, jogador);
  resultado.innerHTML = `
    <div class="card" style="margin:10px 0 0; padding:12px; border-color:rgba(0,240,255,.6); background:rgba(0,240,255,.035)">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap"><div><b style="color:#00f0ff">⭐ Melhores momentos · ${jogador}</b><div class="hint" style="font-size:12px">Vídeo individual com todos os gols e lances marcados dele.</div></div><a class="act" style="padding:8px 14px; font-size:12px" href="${encodeURI(decodeURI(url))}" download>⬇ Baixar vídeo</a></div>
      <video controls preload="metadata" poster="/video/jogador/capa/${encodeURIComponent(decodeURI(url).split('/').pop())}?t=${Date.now()}" src="${encodeURI(decodeURI(url))}" style="display:block; width:100%; max-width:960px; aspect-ratio:16/9; height:auto; max-height:none; margin:0 auto; border-radius:8px; background:#000"></video>
    </div>
    <div class="card" style="margin:10px 0 0; padding:10px; border-color:rgba(0,255,135,.45)">
      <div style="display:flex; justify-content:space-between; gap:8px; margin-bottom:7px"><div><b style="color:var(--accent)">📝 Descrição · ${jogador}</b><div class="hint" style="font-size:11px">Capítulos no tempo do vídeo, como nos vídeos de gols e melhores momentos.</div></div><button type="button" class="act" id="btnCopiarTextoJogador" style="font-size:11px; padding:5px 9px">📋 Copiar</button></div>
      <textarea id="textoJogadorYoutube" readonly style="width:100%; min-height:180px; box-sizing:border-box; background:#070d16; color:#edf7ff; border:1px solid var(--line-bright); border-radius:8px; padding:9px; font:12px/1.5 monospace"></textarea>
    </div>`;
  const campo = $('#textoJogadorYoutube'); campo.value = texto; ajustarAlturaDescricaoYoutube(campo);
  $('#btnCopiarTextoJogador').onclick = () => copiarComentarioYoutube('textoJogadorYoutube', 'btnCopiarTextoJogador');
}

/* ------------------------------------------------------------ render do jogador: resolução, qualidade e cores */
/* ------------------------------------------------------------ formato vertical (9:16) do vídeo do jogador */
const LARG_RECORTE = 81/256;
let recorteV = {x: (1 - LARG_RECORTE) / 2, y: 0, h: 1};
function formatoJogadorVertical(){ return $('#formatoJogador') && $('#formatoJogador').value === '9:16'; }
function limitarRecorte(){
  recorteV.h = Math.min(1, Math.max(0.35, recorteV.h));
  recorteV.x = Math.min(1 - recorteV.h * LARG_RECORTE, Math.max(0, recorteV.x));
  recorteV.y = Math.min(1 - recorteV.h, Math.max(0, recorteV.y));
}
function desenharRecorteVertical(){
  const el = $('#recorteVertical'), wrap = $('#wrapPreviaJogador');
  if(!el || !wrap) return;
  const ativo = formatoJogadorVertical();
  el.style.display = ativo ? 'block' : 'none';
  $('#blocoRecorteVertical').style.display = ativo ? 'block' : 'none';
  if(!ativo) return;
  limitarRecorte();
  const W = wrap.clientWidth, H = wrap.clientHeight;
  el.style.left = (recorteV.x * W) + 'px'; el.style.top = (recorteV.y * H) + 'px';
  el.style.width = (recorteV.h * LARG_RECORTE * W) + 'px'; el.style.height = (recorteV.h * H) + 'px';
  $('#recorteTamanho').value = Math.round(recorteV.h * 100);
  $('#lblRecorteTamanho').textContent = Math.round(recorteV.h * 100) + '%';
}
function salvarRecorteVertical(){
  try { localStorage.setItem('futbin_jogador_recorte', JSON.stringify(recorteV)); } catch(e) {}
}
function rotulosResolucaoJogador(){
  const vertical = formatoJogadorVertical();
  const nomes = {720: 'HD', 1080: 'Full HD', 1440: '2K', 2160: '4K'};
  [...$('#resolucaoJogador').options].forEach(o => {
    const r = parseInt(o.value, 10);
    const dim = vertical ? `${r}×${Math.round(r * 16 / 9 / 2) * 2}` : `${r}p`;
    o.textContent = `${nomes[r] || r} ${dim}` + (r === 1080 ? ' (recomendado)' : '');
  });
}
function inicializarRecorteVertical(){
  let salvoFmt = null;
  try {
    salvoFmt = localStorage.getItem('futbin_jogador_formato');
    const r = JSON.parse(localStorage.getItem('futbin_jogador_recorte') || 'null');
    if(r && [r.x, r.y, r.h].every(Number.isFinite)) recorteV = r;
  } catch(e) {}
  if(salvoFmt === '9:16' || salvoFmt === '16:9') $('#formatoJogador').value = salvoFmt;
  const atualizarFormato = () => {
    try { localStorage.setItem('futbin_jogador_formato', $('#formatoJogador').value); } catch(e) {}
    rotulosResolucaoJogador(); desenharRecorteVertical();
  };
  $('#formatoJogador').onchange = atualizarFormato;
  $('#recorteTamanho').oninput = e => {
    // O tamanho muda em torno do centro do retângulo.
    const cx = recorteV.x + recorteV.h * LARG_RECORTE / 2, cy = recorteV.y + recorteV.h / 2;
    recorteV.h = parseInt(e.target.value, 10) / 100;
    recorteV.x = cx - recorteV.h * LARG_RECORTE / 2; recorteV.y = cy - recorteV.h / 2;
    desenharRecorteVertical(); salvarRecorteVertical();
  };
  $('#btnRecorteCentralizar').onclick = () => {
    recorteV.x = (1 - recorteV.h * LARG_RECORTE) / 2; recorteV.y = (1 - recorteV.h) / 2;
    desenharRecorteVertical(); salvarRecorteVertical();
  };
  const el = $('#recorteVertical'), wrap = $('#wrapPreviaJogador');
  let arrasto = null;
  el.addEventListener('pointerdown', e => {
    arrasto = {px: e.clientX, py: e.clientY, x: recorteV.x, y: recorteV.y};
    el.setPointerCapture(e.pointerId); e.preventDefault();
  });
  el.addEventListener('pointermove', e => {
    if(!arrasto) return;
    recorteV.x = arrasto.x + (e.clientX - arrasto.px) / wrap.clientWidth;
    recorteV.y = arrasto.y + (e.clientY - arrasto.py) / wrap.clientHeight;
    desenharRecorteVertical();
  });
  const fim = () => { if(arrasto){ arrasto = null; salvarRecorteVertical(); } };
  el.addEventListener('pointerup', fim); el.addEventListener('pointercancel', fim);
  window.addEventListener('resize', desenharRecorteVertical);
  atualizarFormato();
}

let _coresJogadorManual = false;   // true depois que o usuário mexe nos controles de cor do jogador
function sincronizarCoresJogadorComFundo(){
  const cfg = _cfgCam(0);
  const fc = S.meta?.fundo_config;
  const aplicar = cfg.aplicar_clipes !== false || (fc && fc.aplicar_video_clipes);
  if(_coresJogadorManual || !aplicar) return;
  const b = cfg.brilho ?? (fc?.brilho != null ? Math.round(fc.brilho * 100) : null);
  const c = cfg.contraste ?? (fc?.contraste != null ? Math.round(fc.contraste * 100) : null);
  const s = cfg.saturacao ?? (fc?.saturacao != null ? Math.round(fc.saturacao * 100) : null);
  if(b != null){ const el=$('#jgBrilho');    if(el) el.value=b; }
  if(c != null){ const el=$('#jgContraste'); if(el) el.value=c; }
  if(s != null){ const el=$('#jgSaturacao'); if(el) el.value=s; }
  ['jgBrilho', 'jgContraste', 'jgSaturacao'].forEach(id => { const l = $('#lbl_' + id); if(l) l.textContent = `${$('#' + id).value}%`; });
  if(typeof aplicarFiltroPreviaJogador === 'function') aplicarFiltroPreviaJogador();
}
function paramsRenderJogador(){
  const card = document.querySelector('.perfil-jogador-card.sel');
  const v = id => { const n = parseFloat($(id).value); return (Number.isFinite(n) ? n : 100) / 100; };
  return {
    crf: card ? parseInt(card.dataset.crf, 10) : 24,
    codec: card?.dataset.codec || 'libx264',
    resolucao: parseInt($('#resolucaoJogador').value, 10) || 1080,
    ...(formatoJogadorVertical() ? {formato: '9:16', recorte: [recorteV.x, recorteV.y, recorteV.h]} : {}),
    brilho: v('#jgBrilho'), contraste: v('#jgContraste'), saturacao: v('#jgSaturacao'),
  };
}
function inicializarRenderJogador(){
  const cards = document.querySelectorAll('.perfil-jogador-card');
  const badge = $('#badgeTamanhoJogador');
  const marcar = card => {
    cards.forEach(c => { c.classList.remove('sel'); c.style.borderColor = 'var(--line)'; c.style.background = 'var(--panel)'; });
    card.classList.add('sel'); card.style.borderColor = 'var(--accent)'; card.style.background = 'rgba(0,255,135,0.08)';
    if(badge) badge.textContent = card.dataset.estimativa;
  };
  let salvo = null, resSalva = null;
  try { salvo = localStorage.getItem('futbin_jogador_crf'); resSalva = localStorage.getItem('futbin_jogador_res'); } catch(e) {}
  cards.forEach(card => {
    if(card.dataset.crf === salvo) marcar(card);
    card.onclick = () => { marcar(card); try { localStorage.setItem('futbin_jogador_crf', card.dataset.crf); } catch(e) {} };
  });
  if(resSalva) $('#resolucaoJogador').value = resSalva;
  $('#resolucaoJogador').onchange = e => { try { localStorage.setItem('futbin_jogador_res', e.target.value); } catch(err) {} };
  // Parte dos ajustes de cor definidos na tela dos vídeos, se estiverem ativos.
  const cfg0 = _cfgCam(0);
  const fc = S.meta?.fundo_config;
  const aplicar = cfg0.aplicar_clipes !== false || (fc && fc.aplicar_video_clipes);
  if(aplicar){
    const b = cfg0.brilho ?? (fc?.brilho != null ? Math.round(fc.brilho * 100) : null);
    const c = cfg0.contraste ?? (fc?.contraste != null ? Math.round(fc.contraste * 100) : null);
    const s = cfg0.saturacao ?? (fc?.saturacao != null ? Math.round(fc.saturacao * 100) : null);
    if(b != null){ const el=$('#jgBrilho');    if(el) el.value=b; }
    if(c != null){ const el=$('#jgContraste'); if(el) el.value=c; }
    if(s != null){ const el=$('#jgSaturacao'); if(el) el.value=s; }
  }
  const atualizar = () => {
    ['jgBrilho', 'jgContraste', 'jgSaturacao'].forEach(id => { $('#lbl_' + id).textContent = `${$('#' + id).value}%`; });
    aplicarFiltroPreviaJogador();
  };
  document.querySelectorAll('.sl-cor-jogador').forEach(el => el.oninput = () => { _coresJogadorManual = true; atualizar(); });
  $('#btnJgResetCores').onclick = () => { _coresJogadorManual = true; ['jgBrilho', 'jgContraste', 'jgSaturacao'].forEach(id => $('#' + id).value = 100); atualizar(); };
  const comparar = ligado => { $('#videoPreviaJogador').style.filter = ligado ? 'none' : filtroCssJogador(); };
  const bc = $('#btnPreviaComparar');
  ['mousedown', 'touchstart'].forEach(ev => bc.addEventListener(ev, () => comparar(true)));
  ['mouseup', 'mouseleave', 'touchend'].forEach(ev => bc.addEventListener(ev, () => comparar(false)));
  $('#selClipePreviaJogador').onchange = carregarClipePreviaJogador;
  $('#tempoFramePrevia').oninput = buscarFramePrevia;
  atualizar();
}

// Aproxima o filtro eq do ffmpeg: brilho é somado (b-1), o CSS multiplica — próximo o bastante para prévia.
function filtroCssJogador(){
  const p = paramsRenderJogador();
  return `brightness(${p.brilho}) contrast(${p.contraste}) saturate(${p.saturacao})`;
}
function aplicarFiltroPreviaJogador(){
  const v = $('#videoPreviaJogador');
  if(v) v.style.filter = filtroCssJogador();
}
function carregarClipePreviaJogador(){
  const sel = $('#selClipePreviaJogador'), v = $('#videoPreviaJogador'), msg = $('#msgPreviaJogador');
  if(!sel || !v) return;
  const url = sel.value;
  const fonte = $('#fonteFramePrevia');
  if(!url){
    fonte.removeAttribute('src'); fonte.load();
    v.getContext('2d').clearRect(0, 0, v.width, v.height);
    msg.style.display = 'flex'; return;
  }
  msg.style.display = 'none';
  fonte.onloadedmetadata = () => { $('#tempoFramePrevia').value = 50; buscarFramePrevia(); };
  fonte.onseeked = desenharFramePrevia;
  fonte.src = url;
  aplicarFiltroPreviaJogador();
}
function buscarFramePrevia(){
  const fonte = $('#fonteFramePrevia');
  if(!fonte.duration || !isFinite(fonte.duration)) return;
  const t = fonte.duration * (parseFloat($('#tempoFramePrevia').value) / 100);
  $('#lblTempoFramePrevia').textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  try { fonte.currentTime = t; } catch(e) {}
}
function desenharFramePrevia(){
  const fonte = $('#fonteFramePrevia'), cv = $('#videoPreviaJogador');
  if(!fonte.videoWidth) return;
  // Mesmo enquadramento do vídeo final: cabe inteiro em 16:9, com barras se preciso.
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cv.width, cv.height);
  const esc = Math.min(cv.width / fonte.videoWidth, cv.height / fonte.videoHeight);
  const w = fonte.videoWidth * esc, h = fonte.videoHeight * esc;
  ctx.drawImage(fonte, (cv.width - w) / 2, (cv.height - h) / 2, w, h);
}
async function atualizarPreviaJogador(jogador){
  const sel = $('#selClipePreviaJogador');
  if(!sel) return;
  // As URLs dos clipes só existiam depois de abrir a tela de marcação; busca aqui se faltar.
  if(!ESTADO.clipes || !Object.keys(ESTADO.clipes).length){
    try {
      const r = await fetch('/api/clipes');
      const {clipes} = await r.json();
      ESTADO.clipes = {};
      clipes.forEach(c => ESTADO.clipes[String(c.indice).padStart(2,'0')] = c.url);
    } catch(e) {}
  }
  // Sem jogador escolhido, a prévia usa os clipes da partida para as cores já poderem ser ajustadas.
  const itens = [...validos(), ...lances()]
    .filter(c => !jogador || c.autor === jogador || c.assist === jogador || c.destaque === jogador)
    .sort((a,b) => obterTempoSegundosClipe(a) - obterTempoSegundosClipe(b));
  const opcoes = itens.map(c => ({url: ESTADO.clipes?.[String(c.indice).padStart(2,'0')], c})).filter(o => o.url);
  sel.innerHTML = opcoes.length
    ? opcoes.map(o => `<option value="${o.url}">#${o.c.indice} · ${o.c.tempo || ''} ${o.c.autor === jogador ? '(gol/lance)' : ''}</option>`).join('')
    : '<option value="">Sem clipes deste jogador</option>';
  $('#msgPreviaJogador').textContent = 'Sem clipe disponível para a prévia.';
  carregarClipePreviaJogador();
}
inicializarRenderJogador();
inicializarRecorteVertical();

$('#btnMontarJogador').onclick = async ()=>{
  const jogador = $('#selJogadorDestaques').value;
  const resultado = $('#resultadoJogador');
  if(!jogador){ alert('Escolha o jogador primeiro.'); return; }
  const itens = [...validos(), ...lances()].filter(c => c.autor === jogador || c.assist === jogador || c.destaque === jogador)
    .sort((a,b) => obterTempoSegundosClipe(a) - obterTempoSegundosClipe(b));
  if(!itens.length){ resultado.textContent = 'Não há lances marcados para este jogador.'; return; }
  const btn = $('#btnMontarJogador'); btn.disabled = true;
  resultado.textContent = `Gerando ${itens.length} clipes de ${jogador}...`;
  try {
    // Garante que a montagem use as marcações mais recentes da tela 6.
    await salvarPartida();
    if('Notification' in window && Notification.permission === 'default'){
      try { await Notification.requestPermission(); } catch(e) {}
    }
    const r = await fetch('/api/montar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      abertura: parseFloat($('#abertura').value)||7, fechamento: parseFloat($('#fechamento').value)||8,
      sem_audio: $('#semAudio').checked, sem_abertura: $('#semAbertura').checked, sem_fechamento: $('#semFechamento').checked,
      roteiro: itens.map(c=>c.indice), ...paramsRenderJogador(), video_jogador: true,
      nome_saida: `${jogador} - Gols e Melhores Momentos.mp4`
    })});
    if(!r.ok){
      const erro = await r.json().catch(()=>({}));
      throw new Error(erro.detail || 'não consegui iniciar a geração');
    }
    const data = await r.json();
    if(await acompanharJob(data.job_id, $('#montarLogJogador'), $('#btnCancelarMontarJogador'))){
      const arquivoPronto = await fetch(data.video_url, {method:'HEAD'});
      if(!arquivoPronto.ok) throw new Error('a renderização terminou, mas o arquivo do jogador não foi encontrado');
      mostrarResultadoVideoJogador(jogador, data.video_url);
      carregarVideosJogadoresSalvos();
      mostrarAlertaVideoJogadorGerado(jogador, data.video_url);
    } else resultado.textContent = 'A geração foi interrompida.';
  } catch(e) { resultado.textContent = `Não consegui gerar o vídeo do jogador: ${e.message || 'erro desconhecido'}.`; }
  finally { btn.disabled = false; }
};
$('#btnCancelarMontarJogador').onclick = cancelarJobAtivo;

$('#btnMontar').onclick = async ()=>{
  if ('Notification' in window && Notification.permission === 'default') {
    try { await Notification.requestPermission(); } catch(e){}
  }
  await salvarPartida();
  try { await salvarFundoCartela(true); } catch(e){}
  $('#btnMontar').disabled = true;

  const todosOrdenados = [...validos(), ...lances()].sort((a, b) => {
    const tA = obterTempoSegundosClipe(a), tB = obterTempoSegundosClipe(b);
    return (tA !== -1 && tB !== -1) ? (tA - tB) : ((a.indice||0) - (b.indice||0));
  });
  const todos = todosOrdenados.map(g => g.indice);

  const promptText = todos.length
    ? `Clipes ordenados por tempo cronológico (${todos.length} clipes). Edite os índices se desejar ou deixe como está para montar na ordem cronológica:`
    : 'Nenhum clipe válido para montar. Verifique a marcação.';

  const resposta = window.prompt(promptText, todos.join(', '));
  if (resposta === null) {
    $('#btnMontar').disabled = false;
    return;
  }

  const roteiro = resposta.trim()
    ? resposta.split(/[\s,]+/).map(v => parseInt(v, 10)).filter(n => Number.isInteger(n) && n >= 0)
    : todos;

  if (resposta.trim() && !roteiro.length) {
    $('#btnMontar').disabled = false;
    alert('Digite índices válidos para os clipes, separados por vírgula.');
    return;
  }

  const cardSel = document.querySelector('.perfil-qualidade-card.sel');
  const crf = cardSel ? parseInt(cardSel.dataset.crf, 10) : 24;
  const codec = cardSel ? (cardSel.dataset.codec || 'libx264') : 'libx264';
  const temaSel = document.querySelector('.tema-card.sel');
  const tema = temaSel ? (temaSel.dataset.tema || 'atual') : 'atual';

  const body = {
    abertura: parseFloat($('#abertura').value)||7,
    fechamento: parseFloat($('#fechamento').value)||8,
    sem_audio: $('#semAudio').checked,
    sem_abertura: $('#semAbertura').checked,
    sem_fechamento: $('#semFechamento').checked,
    roteiro: roteiro.length ? roteiro : todos,
    crf: crf,
    codec: codec,
    resolucao: parseInt($('#resolucaoFinal').value, 10) || 1080,
    tema: tema,
  };
  // Ajustes de cor configurados no card do fundo valem para os clipes quando "aplicar aos clipes" está marcado.
  if($('#chkAplicarClipes').checked){
    const pct = (id, padrao) => { const v = parseFloat($(id).value); return (Number.isFinite(v) ? v : padrao) / 100; };
    body.brilho = pct('#fundoBrilho', 100);
    body.saturacao = pct('#fundoSaturacao', 100);
    body.contraste = pct('#fundoContraste', 100);
  }

  // Mantém a ordem e a abertura usadas nesta renderização para os capítulos do YouTube.
  ESTADO.roteiroFinal = [...body.roteiro];
  ESTADO.opcoesMontagemFinal = { abertura: body.abertura, sem_abertura: body.sem_abertura };
  S.meta = S.meta || {};
  S.meta.roteiro_final = [...body.roteiro];
  S.meta.opcoes_montagem_final = { abertura: body.abertura, sem_abertura: body.sem_abertura };
  await salvarPartida();

  const btnCanc = $('#btnCancelarMontar');
  const r = await fetch('/api/montar/iniciar', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if(!r.ok){ $('#btnMontar').disabled=false; alert('Não consegui iniciar a montagem.'); return; }
  const {job_id} = await r.json();
  const ok = await acompanharJob(job_id, $('#montarLog'), btnCanc);
  $('#btnMontar').disabled = false;
  if(ok){
    renderResultadosVideosFinais();
    mostrarAlertaRenderizacaoConcluida();
  }
};

/* ------------------------------------------------------------ boot */
(async ()=>{
  const urlParams = new URLSearchParams(window.location.search);
  const pPasso = urlParams.get('passo') || (window.location.hash ? window.location.hash.substring(1) : null);
  let passoSalvo = null;
  try { passoSalvo = localStorage.getItem('futbin_ultimo_passo'); } catch(e) {}
  const passoInicial = (pPasso && $(`#${pPasso}`)) ? pPasso : 's-inicio';
  montarNav();
  // Não renderiza a etapa escolhida ainda: primeiro recuperamos partida.json.
  // Isso evita que o resumo seja aberto vazio ao recarregar a página.
  buscarVideos();
  explorar();
  // Cada etapa do boot é isolada: um erro em uma delas não pode impedir a recuperação
  // dos dados da partida, do vídeo e dos clipes (que aparecem como "sumidos" se o boot parar).
  try {
    const rp = await fetch('/api/placar'); const {rect} = await rp.json();
    if(rect){ ESTADO.placarRect = rect; $('#btnConfirmarPlacar').disabled=false; $('#btnIrGols').disabled=false;
      $('#placarAtual').innerHTML = `<span class="ok">✓ Região já salva: [${rect.join(', ')}]</span>`; }
    const rz = await fetch('/api/zonas'); const {zonas} = await rz.json();
    zonasSel = zonas || [];
    renderListaZonas();
    redesenharTudo();
    if(zonasSel.length > 0) $('#cardZonasDet').style.display = 'block';
  } catch(e) { console.warn('boot: placar/zonas', e); }

  let partida = null;
  try {
    const rpart = await fetch('/api/partida');
    partida = rpart.status===200 ? await rpart.json() : null;
  } catch(e) { console.warn('não consegui ler /api/partida', e); }
  // Sem dados no servidor (arquivo apagado/vazio): recupera a última cópia guardada neste navegador.
  if(!partida || !partida.times || !partida.times.length){
    const guardado = lerCachePartida();
    if(guardado) partida = guardado;
  }
  if(partida){
    S.meta = partida.meta || S.meta; S.times = partida.times || S.times;
    if(partida.meta && [0,1,2].includes(partida.meta.camera_placar)) ESTADO.cameraPlacar = partida.meta.camera_placar;
    if(partida.meta && Array.isArray(partida.meta.cameras) && partida.meta.cameras.length){
      ESTADO.cameras = [null, null, null];
      partida.meta.cameras.slice(0,3).forEach((cam, i) => {
        if(!cam) return; // as câmeras 2 e 3 vêm como null quando não foram enviadas
        ESTADO.cameras[i] = {...cam, nome: cam.nome || String(cam.caminho || '').split(/[\\/]/).pop()};
      });
      ESTADO.video = ESTADO.cameras[0];
      renderCamerasSelecionadas();
      if(ESTADO.video) selecionarVideo(ESTADO.video, 0);
    } else if(partida.meta && partida.meta.video){
      selecionarVideo({nome: partida.meta.video.split(/[\\/]/).pop(), caminho: partida.meta.video, duracao_s: null}, 0);
    }
    if(partida._todosGols) ESTADO.gols = partida._todosGols;
  }
  if(!ESTADO.video){
    try {
      const rg = await fetch('/api/gols');
      const dg = await rg.json();
      if(dg && dg.video){
        selecionarVideo({nome: dg.video.split(/[\\/]/).pop(), caminho: dg.video, duracao_s: null});
      }
    } catch(e){}
  }
  try { escreverSetup(); } catch(e) { console.warn('boot: escreverSetup', e); }
  try { inicializarVideoCompleto(); } catch(e) { console.warn('boot: video completo', e); }

  try {
    const re = await fetch('/api/estado'); const estado = await re.json();
    if(estado.clipes_ok){
      await carregarClipes();
      $('#btnIrRevisar').disabled = false;
    }
    if(estado.final_ok || estado.final_gols_ok){
      renderResultadosVideosFinais();
    }
  } catch(e) { console.warn('boot: clipes/finais', e); }
  try { carregarVideosJogadoresSalvos(); inicializarSeletorQualidade(); } catch(e) { console.warn('boot: listas', e); }
  try { await carregarSessoes(); } catch(e) { console.warn('boot: sessoes', e); }
  try { await carregarJogadoresCadastrados(); } catch(e) { console.warn('boot: jogadores', e); }
  // Agora cada etapa (em especial Resumo e Jogador) recebe os dados salvos.
  irPara(passoInicial);
})();

/* ============================================================
   GERENCIAMENTO DE JOGADORES
   ============================================================ */

let jogadoresCadastrados = [];
let jogadorEmEdicao = null;

async function carregarJogadoresCadastrados(){
  try{
    const r = await fetch('/api/jogadores');
    if(!r.ok) return;
    const data = await r.json();
    jogadoresCadastrados = data.jogadores || [];
    renderGridJogadores();
  }catch(e){
    console.error('Erro ao carregar jogadores:', e);
  }
}

function renderGridJogadores(){
  const grid = $('#gridJogadores');
  const msg = $('#msgSemJogadores');
  const badge = $('#badgeTotalJogadores');

  if(badge) badge.textContent = `${jogadoresCadastrados.length} jogador${jogadoresCadastrados.length !== 1 ? 'es' : ''}`;

  if(!jogadoresCadastrados.length){
    if(grid) grid.innerHTML = '';
    if(msg) msg.style.display = 'block';
    return;
  }

  if(msg) msg.style.display = 'none';
  if(!grid) return;

  grid.innerHTML = jogadoresCadastrados.map(j => {
    const foto = j.foto || '/web/icon.png';
    const apelido = j.apelido ? `<span style="font-size:11px;color:var(--dim)">\"${j.apelido}\"</span>` : '';
    const numero = j.numero ? `<span style="position:absolute;top:6px;right:6px;background:var(--accent);color:#000;font-weight:700;font-size:11px;padding:2px 6px;border-radius:4px">#${j.numero}</span>` : '';
    const posicao = j.posicao ? `<span style="font-size:10px;color:var(--dim);font-weight:700">${j.posicao}</span>` : '';

    return `<div class="jogador-card" style="position:relative">
      ${numero}
      <img src="${foto}" class="jogador-foto" alt="${j.nome}" onerror="this.src='/web/icon.png'">
      <div style="text-align:center">
        <div style="font-weight:700;font-size:13px;margin-bottom:2px">${j.nome}</div>
        ${apelido}
        ${posicao}
      </div>
      <div class="row" style="gap:4px;margin-top:4px">
        <button type="button" class="ghost btnPequeno" style="flex:1" onclick="editarJogador('${j.id}')">✏️ Editar</button>
        <button type="button" class="ghost btnPequeno" style="flex:1" onclick="removerJogador('${j.id}')">🗑️ Remover</button>
      </div>
    </div>`;
  }).join('');
}

function abrirFormJogador(jogadorId = null){
  jogadorEmEdicao = jogadorId;
  const form = $('#formJogadorCard');
  const titulo = $('#formJogadorTitulo');

  if(jogadorId){
    const j = jogadoresCadastrados.find(jog => jog.id === jogadorId);
    if(!j) return;

    if(titulo) titulo.textContent = 'Editar Jogador';
    $('#inputNomeJogador').value = j.nome || '';
    $('#inputApelidoJogador').value = j.apelido || '';
    $('#inputPosicaoJogador').value = j.posicao || '';
    $('#inputNumeroJogador').value = j.numero || '';
    $('#previewFotoJogador').src = j.foto || '/web/icon.png';
  }else{
    if(titulo) titulo.textContent = 'Adicionar Novo Jogador';
    $('#inputNomeJogador').value = '';
    $('#inputApelidoJogador').value = '';
    $('#inputPosicaoJogador').value = '';
    $('#inputNumeroJogador').value = '';
    $('#previewFotoJogador').src = '/web/icon.png';
  }

  if(form){
    form.style.display = 'block';
    form.scrollIntoView({behavior:'smooth', block:'nearest'});
  }
}

function cancelarFormJogador(){
  const form = $('#formJogadorCard');
  if(form) form.style.display = 'none';
  jogadorEmEdicao = null;
}

function carregarPreviewFoto(input){
  if(!input.files || !input.files[0]) return;
  const reader = new FileReader();
  reader.onload = e => {
    $('#previewFotoJogador').src = e.target.result;
  };
  reader.readAsDataURL(input.files[0]);
}

async function salvarJogador(){
  const nome = $('#inputNomeJogador').value.trim();
  if(!nome){ alert('Digite o nome do jogador.'); return; }

  const dados = {
    nome,
    apelido: $('#inputApelidoJogador').value.trim() || null,
    posicao: $('#inputPosicaoJogador').value || null,
    numero: parseInt($('#inputNumeroJogador').value) || null,
  };

  try{
    let jogadorId = jogadorEmEdicao;

    if(jogadorId){
      // Editar
      const r = await fetch(`/api/jogadores/${jogadorId}`, {
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(dados)
      });
      if(!r.ok) throw new Error('Erro ao atualizar');
    }else{
      // Adicionar
      const r = await fetch('/api/jogadores', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(dados)
      });
      if(!r.ok) throw new Error('Erro ao adicionar');
      const resultado = await r.json();
      jogadorId = resultado.jogador.id;
    }

    // Upload de foto se houver
    const inputFoto = $('#inputFotoJogador');
    if(inputFoto.files && inputFoto.files[0]){
      const formData = new FormData();
      formData.append('foto', inputFoto.files[0]);

      const r2 = await fetch(`/api/jogadores/${jogadorId}/foto`, {
        method:'POST',
        body: await inputFoto.files[0].arrayBuffer()
      });
      if(!r2.ok) console.warn('Erro ao fazer upload da foto');
    }

    await carregarJogadoresCadastrados();
    cancelarFormJogador();
    alert(jogadorEmEdicao ? 'Jogador atualizado!' : 'Jogador adicionado!');
  }catch(e){
    alert('Erro ao salvar jogador: ' + e.message);
  }
}

function editarJogador(id){
  abrirFormJogador(id);
}

async function removerJogador(id){
  const j = jogadoresCadastrados.find(jog => jog.id === id);
  if(!j) return;

  if(!confirm(`Remover ${j.nome}?`)) return;

  try{
    const r = await fetch(`/api/jogadores/${id}`, {method:'DELETE'});
    if(!r.ok) throw new Error('Erro ao remover');

    await carregarJogadoresCadastrados();
    alert('Jogador removido!');
  }catch(e){
    alert('Erro ao remover jogador: ' + e.message);
  }
}

function mostrarSugestoesJogador(input, tipo){
  const termo = input.value.trim().toLowerCase();
  const listaSug = $(`#sugestoes${tipo === 'autor' ? 'Autor' : 'Assist'}`);
  if(!listaSug) return;

  if(!termo){
    listaSug.style.display = 'none';
    return;
  }

  const filtrados = jogadoresCadastrados.filter(j =>
    j.nome.toLowerCase().includes(termo) ||
    (j.apelido && j.apelido.toLowerCase().includes(termo))
  );

  if(!filtrados.length){
    listaSug.style.display = 'none';
    return;
  }

  listaSug.innerHTML = filtrados.map(j => {
    const foto = j.foto || '/web/icon.png';
    const apelidoExibir = j.apelido ? ` "${j.apelido}"` : '';
    // Usa apelido se existir, senão usa nome
    const nomeUsar = j.apelido || j.nome;
    return `<div onclick="selecionarJogador('${tipo}', '${nomeUsar.replace(/'/g, "\\'")}')" style="padding:8px;cursor:pointer;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--line);transition:all .15s" onmouseover="this.style.background='var(--panel2)'" onmouseout="this.style.background='transparent'">
      <img src="${foto}" style="width:32px;height:32px;border-radius:50%;object-fit:cover" onerror="this.src='/web/icon.png'">
      <div style="flex:1">
        <div style="font-weight:700;font-size:12px">${j.nome}${apelidoExibir}</div>
        ${j.posicao ? `<div style="font-size:10px;color:var(--dim)">${j.posicao}${j.numero ? ` · #${j.numero}` : ''}</div>` : ''}
      </div>
    </div>`;
  }).join('');
  listaSug.style.display = 'block';
}

function selecionarJogador(tipo, nomeUsado){
  // Busca o jogador cadastrado para puxar informações
  const jogadorCadastrado = jogadoresCadastrados.find(j =>
    (j.apelido && j.apelido === nomeUsado) || j.nome === nomeUsado
  );

  if(tipo === 'autor'){
    rascunho.autor = nomeUsado;
    const inp = $('#inAutor');
    if(inp) inp.value = nomeUsado;
    const lista = $('#sugestoesAutor');
    if(lista) lista.style.display = 'none';

    // Se encontrou jogador cadastrado, define posição automaticamente
    if(jogadorCadastrado && jogadorCadastrado.posicao && rascunho.time !== null){
      // Mapeia posição do cadastro (GOL/ZAG/MEI/ATA) para o sistema
      const mapaPosicao = {
        'GOL': 'goleiro', 'GOLEIRO': 'goleiro',
        'ZAG': 'zagueiro', 'ZAGUEIRO': 'zagueiro',
        'MEI': 'meio', 'MEIO': 'meio', 'MEIA': 'meio',
        'ATA': 'atacante', 'ATACANTE': 'atacante'
      };
      const posNormalizada = jogadorCadastrado.posicao.toUpperCase().trim();
      const posId = mapaPosicao[posNormalizada] || 'meio';
      definirPosicaoJogador(rascunho.time, nomeUsado, posId);
      console.log(`[>] Posição ${posId} definida automaticamente para ${nomeUsado}`);
    }
  } else {
    rascunho.assist = nomeUsado;
    const inp = $('#inAssist');
    if(inp) inp.value = nomeUsado;
    const lista = $('#sugestoesAssist');
    if(lista) lista.style.display = 'none';

    // Também define posição para assistência se aplicável
    if(jogadorCadastrado && jogadorCadastrado.posicao && rascunho.time !== null){
      const mapaPosicao = {
        'GOL': 'goleiro', 'GOLEIRO': 'goleiro',
        'ZAG': 'zagueiro', 'ZAGUEIRO': 'zagueiro',
        'MEI': 'meio', 'MEIO': 'meio', 'MEIA': 'meio',
        'ATA': 'atacante', 'ATACANTE': 'atacante'
      };
      const posNormalizada = jogadorCadastrado.posicao.toUpperCase().trim();
      const posId = mapaPosicao[posNormalizada] || 'meio';
      definirPosicaoJogador(rascunho.time, nomeUsado, posId);
      console.log(`[>] Posição ${posId} definida automaticamente para ${nomeUsado} (assistência)`);
    }
  }
}

/* ============================================================
   SELETOR DE JOGADORES PARA ELENCO (DADOS DA PARTIDA)
   ============================================================ */

let timeParaAdicionar = null;
let jogadoresSelecionados = [];

function abrirSeletorJogadores(timeIdx){
  timeParaAdicionar = timeIdx;
  jogadoresSelecionados = [];

  const modal = $('#modalSeletorJogadores');
  const titulo = $('#tituloSeletorJogadores');
  const grid = $('#gridSeletorJogadores');
  const msg = $('#msgSemJogadoresModal');

  if(titulo){
    const nomeTime = timeIdx === 0 ? ($('#tA').value || 'Time 1') : ($('#tB').value || 'Time 2');
    titulo.textContent = `Adicionar Jogadores ao ${nomeTime}`;
  }

  if(!jogadoresCadastrados.length){
    if(grid) grid.innerHTML = '';
    if(msg) msg.style.display = 'block';
  }else{
    if(msg) msg.style.display = 'none';
    if(grid){
      grid.innerHTML = jogadoresCadastrados.map(j => {
        const foto = j.foto || '/web/icon.png';
        const apelido = j.apelido ? `<span style="font-size:11px;color:var(--dim)">"${j.apelido}"</span>` : '';
        const numero = j.numero ? `<span style="position:absolute;top:6px;right:6px;background:var(--accent);color:#000;font-weight:700;font-size:11px;padding:2px 6px;border-radius:4px">#${j.numero}</span>` : '';
        const posicao = j.posicao ? `<span style="font-size:10px;color:var(--dim);font-weight:700">${j.posicao}</span>` : '';

        return `<div class="jogador-card" style="position:relative;cursor:pointer" onclick="toggleSelecionarJogadorElenco('${j.id}')" data-jogador-id="${j.id}">
          ${numero}
          <img src="${foto}" class="jogador-foto" alt="${j.nome}" onerror="this.src='/web/icon.png'">
          <div style="text-align:center">
            <div style="font-weight:700;font-size:13px;margin-bottom:2px">${j.nome}</div>
            ${apelido}
            ${posicao}
          </div>
          <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,0.75);display:none;align-items:center;justify-content:center" class="check-overlay">
            <span style="font-size:20px;color:var(--accent)">✓</span>
          </div>
        </div>`;
      }).join('');
    }
  }

  if(modal) modal.style.display = 'flex';
}

function toggleSelecionarJogadorElenco(jogadorId){
  const card = document.querySelector(`[data-jogador-id="${jogadorId}"]`);
  if(!card) return;

  const overlay = card.querySelector('.check-overlay');

  if(jogadoresSelecionados.includes(jogadorId)){
    jogadoresSelecionados = jogadoresSelecionados.filter(id => id !== jogadorId);
    card.style.borderColor = 'var(--line)';
    card.style.background = 'var(--panel2)';
    if(overlay) overlay.style.display = 'none';
  }else{
    jogadoresSelecionados.push(jogadorId);
    card.style.borderColor = 'var(--accent)';
    card.style.background = 'rgba(0,255,135,0.1)';
    if(overlay) overlay.style.display = 'flex';
  }
}

function confirmarSelecaoJogadores(){
  if(!jogadoresSelecionados.length){
    alert('Selecione pelo menos um jogador.');
    return;
  }

  const textarea = timeParaAdicionar === 0 ? $('#pA') : $('#pB');
  if(!textarea) return;

  const jogadoresTexto = textarea.value.trim();
  const linhasAtuais = jogadoresTexto ? jogadoresTexto.split('\n').map(l => l.trim()).filter(Boolean) : [];

  // 1. Primeiro coleta tudo que vai ser adicionado
  const posParaAplicar = {};
  const fotosParaAplicar = {};

  jogadoresSelecionados.forEach(id => {
    const jogador = jogadoresCadastrados.find(j => j.id === id);
    if(!jogador) return;
    const nomeExibir = jogador.apelido || jogador.nome;
    if(!linhasAtuais.includes(nomeExibir)){
      linhasAtuais.push(nomeExibir);
    }
    // Coleta posição
    if(jogador.posicao){
      const mapaPosicao = {
        'GOL': 'goleiro', 'GOLEIRO': 'goleiro',
        'ZAG': 'zagueiro', 'ZAGUEIRO': 'zagueiro',
        'MEI': 'meio', 'MEIO': 'meio', 'MEIA': 'meio',
        'ATA': 'atacante', 'ATACANTE': 'atacante'
      };
      const posId = mapaPosicao[jogador.posicao.toUpperCase().trim()] || 'meio';
      posParaAplicar[nomeExibir] = posId;
    }
    // Coleta foto
    if(jogador.foto){
      fotosParaAplicar[nomeExibir] = jogador.foto;
    }
  });

  // 2. Atualiza o textarea (sem disparar evento - evita lerSetup prematuro)
  textarea.value = linhasAtuais.join('\n');

  // 3. Garante estrutura do time antes de definir posições/fotos
  if(!S.times[timeParaAdicionar].posicoes) S.times[timeParaAdicionar].posicoes = {};
  if(!S.times[timeParaAdicionar].fotos)    S.times[timeParaAdicionar].fotos    = {};

  // 4. Aplica posições e fotos direto no estado
  Object.entries(posParaAplicar).forEach(([nome, pos]) => {
    S.times[timeParaAdicionar].posicoes[nome] = pos;
  });
  Object.entries(fotosParaAplicar).forEach(([nome, foto]) => {
    S.times[timeParaAdicionar].fotos[nome] = foto;
  });

  // 5. Agora sim chama lerSetup (vai ler o textarea já atualizado e preservar posições/fotos)
  lerSetup();
  agendarSalvar();

  fecharSeletorJogadores();
}

function fecharSeletorJogadores(){
  const modal = $('#modalSeletorJogadores');
  if(modal) modal.style.display = 'none';
  timeParaAdicionar = null;
  jogadoresSelecionados = [];
}

/* ============================================================
   FIM GERENCIAMENTO DE JOGADORES
   ============================================================ */
