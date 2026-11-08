const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '../web/assistente.js'), 'utf8');
const start = source.indexOf('let _descartandoClipe = false;');
const end = source.indexOf('\nasync function sincronizarGolsComBackend', start);
assert.ok(start >= 0 && end > start, 'descartarClipe function should exist');

const events = [];
function makeVideo(label) {
  return {
    pause() { events.push(`${label}:pause`); },
    removeAttribute(name) { if(name === 'src') events.push(`${label}:remove-src`); },
    load() { events.push(`${label}:load`); },
  };
}
const thumbnail = makeVideo('thumbnail');
const card = {querySelectorAll: selector => selector === 'video' ? [thumbnail] : []};
const grade = {querySelectorAll: selector => {
  assert.equal(selector, '.evcard[data-indice="20"]');
  return [card];
}};
const elements = {
  '#modalClipe': {hidden:true},
  '#modalVideo': makeVideo('modal-video'),
  '#vid': makeVideo('video'),
  '#gradeClipes': grade,
};
const context = {
  $: selector => elements[selector],
  alert: message => { throw new Error(message); },
  fetch: async (url, options) => {
    assert.equal(url, '/api/gols/descartar');
    assert.ok(events.includes('thumbnail:remove-src'), 'thumbnail source must be released before delete request');
    events.push('post');
    return {ok:true};
  },
  salvarPartida: async () => { events.push('save'); },
  carregarClipes: async () => { events.push('reload'); },
  fecharModalClipe() {},
  ESTADO: {gols:[{indice:20},{indice:21}], clipes:{20:'/clip'}, indiceAtual:20},
  clipesAtuais:[{indice:20},{indice:21}],
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

(async () => {
  assert.equal(await context.descartarClipe(20), true);
  assert.ok(events.indexOf('thumbnail:remove-src') < events.indexOf('post'));
  assert.deepEqual(events.slice(-3), ['post','save','reload']);
  assert.deepEqual(context.ESTADO.gols.map(gol => gol.indice), [21]);
  console.log('OK: thumbnail released before delete; partida saved and clip list reloaded.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
