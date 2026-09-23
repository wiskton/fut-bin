const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync(process.argv[2] || require('path').join(__dirname, '../web/assistente.html'), 'utf8');
const source = html.slice(html.indexOf('let pedidoPreviaCompleto = 0;'), html.indexOf('function urlClipeDaCamera('));
let camera = 1, nextResponse;
const events = new Map();
const attributes = new Map([['data-carregado', '/original/1']]);
const video = {
  currentTime:123, duration:600, playbackRate:5, paused:false, muted:true, volume:0.3,
  addEventListener(name, fn) { if(!events.has(name)) events.set(name, new Set()); events.get(name).add(fn); },
  removeEventListener(name, fn) { events.get(name)?.delete(fn); },
  getAttribute(key) { return attributes.get(key); },
  setAttribute(key, value) { attributes.set(key, value); },
  load() { this.currentTime = 0; this.paused = true; },
  play() { this.paused = false; return Promise.resolve(); }
};
const elements = {'#videoCompleto':video, '#qualidadeVideoCompleto':{value:'360'}, '#statusPreviaCompleto':{textContent:''}};
const context = {
  $: key => elements[key], localStorage:{setItem(){}},
  cameraVerValida: () => camera, caminhoVideoCompleto: n => '/source/' + n,
  urlVideoCompleto: n => '/original/' + n, offsetCameraS: n => n === 1 ? 0 : 10,
  rotuloCameraVideoCompleto(){},
  fetch: async () => await nextResponse,
  setTimeout, console,
};
vm.createContext(context); vm.runInContext(source, context);
function metadata() { const handlers = [...(events.get('loadedmetadata') || [])]; events.set('loadedmetadata', new Set()); handlers.forEach(fn => fn()); }
async function run(){
  nextResponse = {ok:true, json:async()=>({pronto:true,url:'/preview/360'})};
  await context.aplicarQualidadeVideoCompleto(); metadata();
  assert.equal(video.src,'/preview/360'); assert.equal(video.currentTime,123);
  assert.equal(video.playbackRate,5); assert.equal(video.paused,false);
  assert.equal(video.muted,true); assert.equal(video.volume,0.3);
  video.paused=true; video.currentTime=222;
  elements['#qualidadeVideoCompleto'].value='original';
  await context.aplicarQualidadeVideoCompleto(); metadata();
  assert.equal(video.currentTime,222); assert.equal(video.paused,true); assert.equal(video.playbackRate,5);
  // Uma resposta tardia não pode substituir a escolha mais recente.
  let resolve;
  nextResponse = new Promise(r => {resolve=r;});
  elements['#qualidadeVideoCompleto'].value='480';
  const pending=context.aplicarQualidadeVideoCompleto();
  elements['#qualidadeVideoCompleto'].value='original';
  await context.aplicarQualidadeVideoCompleto();
  resolve({ok:true,json:async()=>({pronto:true,url:'/preview/480'})});
  await pending;
  assert.equal(video.src,'/original/1');
  nextResponse = {ok:false,status:404,json:async()=>({detail:'Not Found'})};
  elements['#qualidadeVideoCompleto'].value='360';
  await context.aplicarQualidadeVideoCompleto();
  assert.match(elements['#statusPreviaCompleto'].textContent,/servidor ainda está na versão antiga/i);
  context.aplicarFonteVideoCompleto('/preview/360',222,false);
  elements['#qualidadeVideoCompleto'].value='original';
  await context.aplicarQualidadeVideoCompleto();
  video.defaultPlaybackRate=3; video.playbackRate=3;
  metadata();
  assert.equal(video.currentTime,222); assert.equal(video.playbackRate,3);
  video.playbackRate=5;
  camera=2; context.trocarVideoCompleto(1); metadata();
  assert.equal(video.currentTime,212); assert.equal(video.playbackRate,5);
  assert.equal(video.src,'/original/2');
  console.log('OK: qualidade preserva posição, 5x, pausa, volume; respostas antigas ignoradas; câmeras mantêm offset.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
