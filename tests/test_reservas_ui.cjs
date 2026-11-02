const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');

const jsSource = fs.readFileSync(path.join(__dirname, '../web/assistente.js'), 'utf8');

// Extrai o bloco inicial de posições, reservas e renderPosicoesElenco
const endIdx = jsSource.indexOf('function corTextoParaFundo(');
assert.ok(endIdx > 0, 'Não encontrou bloco de elenco em assistente.js');
const snippet = jsSource.slice(0, endIdx);

const dom = {
  '#posElencoA': { innerHTML: '' },
  '#posElencoB': { innerHTML: '' },
};
let salvouCount = 0;

const context = {
  document: {
    querySelector: sel => dom[sel] || null,
    querySelectorAll: () => [],
  },
  agendarSalvar: () => { salvouCount += 1; },
  Date,
  Math,
  Set,
  Object,
  Array,
  String,
  Number,
  console,
};

vm.createContext(context);
vm.runInContext(snippet + '\nthis.__api = { getS: () => S, setS: v => { S = v; }, ehJogadorReserva, listarReservasTime, alternarReservaJogador, definirPosicaoJogador, obterPosicaoJogador, obterSiglaElencoJogador, escalacaoCompleta, autoDefinirPosicoes, renderPosicoesElenco };', context);

const api = context.__api;

// Configura Time A com 1º nome reserva para garantir que o 1º titular vira goleiro
api.setS({
  meta: { pelada: 'Will Cup' },
  times: [
    {
      nome: 'Time Amarelo',
      cor: '#eab308',
      jogadores: ['Pedro', 'Will', 'João', 'Lucas', 'Mateus', 'Caio'],
      posicoes: {},
      reservas: [],
    },
    {
      nome: 'Time Azul',
      cor: '#2563eb',
      jogadores: ['Arthur', 'Marcão'],
      posicoes: {},
      reservas: ['Marcão'],
    },
  ],
});

// Marca Pedro (índice 0) como reserva
api.alternarReservaJogador(0, 'Pedro');
assert.equal(api.ehJogadorReserva(0, 'Pedro'), true);
assert.deepEqual([...api.listarReservasTime(0)], ['Pedro']);
assert.equal(api.obterSiglaElencoJogador(0, 'Pedro'), 'RES');

// Will (1º titular não-reserva) assume posição padrão de goleiro
assert.equal(api.obterPosicaoJogador(0, 'Will'), 'goleiro');
assert.equal(api.obterSiglaElencoJogador(0, 'Will'), 'GOL');

const escA = api.escalacaoCompleta(0);
assert.equal(escA['Will'], 'goleiro');
assert.equal(escA['Pedro'], undefined);

// Verifica HTML renderizado na Etapa 5
assert.match(dom['#posElencoA'].innerHTML, /5 TITULARES · 1 RESERVA/);
assert.match(dom['#posElencoA'].innerHTML, /fut-player-row is-reserva/);
assert.match(dom['#posElencoA'].innerHTML, /pos-reserva[^>]*>RES</);

// Auto-definir posições respeita quem está marcado como reserva
api.autoDefinirPosicoes();
assert.equal(api.ehJogadorReserva(0, 'Pedro'), true);
assert.equal(api.obterPosicaoJogador(0, 'Will'), 'goleiro');
assert.equal(api.obterPosicaoJogador(0, 'João'), 'zagueiro');

// Clicar em uma posição tática (ex.: ATA) tira o jogador da reserva automaticamente
api.definirPosicaoJogador(0, 'Pedro', 'atacante');
assert.equal(api.ehJogadorReserva(0, 'Pedro'), false);
assert.equal(api.obterPosicaoJogador(0, 'Pedro'), 'atacante');

// Time B carregado de partida.json com reservas
api.renderPosicoesElenco(1);
assert.equal(api.ehJogadorReserva(1, 'Marcão'), true);
assert.match(dom['#posElencoB'].innerHTML, /1 TITULAR · 1 RESERVA/);
assert.ok(salvouCount >= 3);

console.log('OK: UI de reservas (toggle RES, promoção automática ao clicar posição, goleiro titular e serialização) validada.');
