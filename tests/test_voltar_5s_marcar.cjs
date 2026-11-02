const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');

const html = fs.readFileSync(path.join(__dirname, '../web/assistente.html'), 'utf8');
assert.match(html, /id="btnVoltar5sManter15sMarcar"/);
assert.match(html, /id="btnAvancar5sManter15sMarcar"/);

const js = fs.readFileSync(path.join(__dirname, '../web/assistente.js'), 'utf8');
const startIdx = js.indexOf('/* ---- Botões Voltar 5s (15s)');
const endIdx = js.indexOf("$('#btnRep').onclick");
assert.ok(startIdx > 0 && endIdx > startIdx, 'Bloco dos botões 5s (15s) não encontrado');
const snippet = js.slice(startIdx, endIdx);

const btnVoltar = { disabled: false, innerHTML: '<span>⏪</span> <span>Voltar 5s (15s)</span>', onclick: null };
const btnAvancar = { disabled: false, innerHTML: '<span>⏩</span> <span>Avançar 5s (15s)</span>', onclick: null };
const calls = [];
let nextIndice = 12;

const context = {
  ESTADO: {
    video: { caminho: '/videos/jogo.mp4' },
    indiceAtual: 5,
    gols: [
      { indice: 5, inicio_s: 100, fim_s: 115, tempo_s: 115, status: 'gol', tipo: 'gol', time: 0, autor: 'Will', assist: 'João', camera: 2, cameras_clipe: [2] },
      { indice: 6, inicio_s: 3, fim_s: 27, tempo_s: 23, status: null, tipo: 'revisar', time: null },
    ],
  },
  document: {
    getElementById: id => {
      if (id === 'btnVoltar5sManter15sMarcar') return btnVoltar;
      if (id === 'btnAvancar5sManter15sMarcar') return btnAvancar;
      return null;
    },
  },
  obterInfoTipo: status => (status === 'gol' ? { id: 'gol', isGol: true } : null),
  carregarClipes: async () => {},
  renderMarcacao: () => {},
  mostrarAlertaClipePronto: info => calls.push({ alerta: info }),
  fetch: async (url, opts) => {
    const body = JSON.parse(opts.body);
    calls.push({ url, body });
    if (url === '/api/gols/adicionar') {
      return { ok: true, json: async () => ({ ok: true, indice: nextIndice++ }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
  },
  alert: msg => { throw new Error('Alert inesperado: ' + msg); },
  Math,
  Number,
  isNaN,
};

vm.createContext(context);
vm.runInContext(snippet, context);
assert.equal(typeof btnVoltar.onclick, 'function');
assert.equal(typeof btnAvancar.onclick, 'function');

(async () => {
  // Caso 1: Voltar 5s em clipe [100, 115] -> inicio=95, fim=110 (15s)
  await btnVoltar.onclick();
  assert.equal(calls[0].url, '/api/gols/adicionar');
  assert.equal(calls[0].body.inicio_s, 95);
  assert.equal(calls[0].body.fim_s, 110);
  assert.equal(calls[0].body.fim_s - calls[0].body.inicio_s, 15);
  assert.equal(calls[1].url, '/api/gols/confirmar');
  assert.equal(calls[1].body.autor, 'Will');
  assert.equal(calls[1].body.camera, 2);
  assert.equal(context.ESTADO.indiceAtual, 12);
  assert.equal(btnVoltar.disabled, false);

  // Caso 2: Avançar 5s em clipe [100, 115] -> inicio=105, fim=120 (15s)
  calls.length = 0;
  context.ESTADO.indiceAtual = 5;
  await btnAvancar.onclick();
  assert.equal(calls[0].url, '/api/gols/adicionar');
  assert.equal(calls[0].body.inicio_s, 105);
  assert.equal(calls[0].body.fim_s, 120);
  assert.equal(calls[0].body.fim_s - calls[0].body.inicio_s, 15);
  assert.equal(calls[1].url, '/api/gols/confirmar');
  assert.equal(calls[1].body.autor, 'Will');
  assert.equal(context.ESTADO.indiceAtual, 13);
  assert.equal(btnAvancar.disabled, false);

  // Caso 3: Voltar 5s no começo do vídeo (inicio=3) e pendente -> inicio=0, fim=15 (15s)
  calls.length = 0;
  context.ESTADO.indiceAtual = 6;
  await btnVoltar.onclick();
  assert.equal(calls[0].url, '/api/gols/adicionar');
  assert.equal(calls[0].body.inicio_s, 0);
  assert.equal(calls[0].body.fim_s, 15);
  assert.equal(calls[0].body.status, 'pendente');

  console.log('OK: botões Voltar 5s (15s) e Avançar 5s (15s) deslocam ±5s mantendo 15s de jogada.');
})().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
