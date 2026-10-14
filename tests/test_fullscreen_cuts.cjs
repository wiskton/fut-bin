const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync(require('path').join(__dirname, '../web/assistente.html'), 'utf8');
// Compile every inline script, in addition to exercising the actual player handlers.
for(const [,script] of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script);
const elements = new Map();
const events = new Map();
function $(id){
  if(!elements.has(id)) elements.set(id, {value:'', style:{}, textContent:'', hidden:true,
    addEventListener(name, fn){events.set(id+':'+name, fn);},
    setAttribute(name,value){this[name]=value;}, click(){this.onclick?.();}});
  return elements.get(id);
}
const video = $('#videoCompleto');
Object.assign(video, {currentTime:120, readyState:1, paused:false, playbackRate:5});
const document = {fullscreenElement:null, addEventListener(name,fn){events.set(name,fn);}, async exitFullscreen(){this.fullscreenElement=null; events.get('fullscreenchange')();}};
$('#playerVideoCompleto').requestFullscreen = async () => {document.fullscreenElement=$('#playerVideoCompleto');events.get('fullscreenchange')();};
let offset=0, captured;
const context = {$, document, console, Date, Math, setTimeout:()=>{}, ESTADO:{video:{caminho:'/original/4k.mp4'}},
  tempoJogoDoVideoCompleto:()=>video.currentTime+offset, fmtTempo:String,
  alert:message=>{throw Error(message);}, obterInfoTipo:()=>null,
  fetch:async(url, options)=>{captured=JSON.parse(options.body);return {ok:true,json:async()=>({indice:7})};},
  carregarClipes:async()=>{}, clipesAtuais:[], mostrarAlertaClipePronto(){}, mostrarAlertaFilaAdicionada(){}};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf("const btnMaisTrasCompleto ="), html.indexOf('let _descartandoClipe =')), context);
async function cut(time, cameraOffset=0){
  video.currentTime=time;offset=cameraOffset;captured=null;
  $('#duracaoCorteCompleto').value='90';$('#posicaoCorteCompleto').value='depois';
  $('#btnCortar15sSobreVideo').click();
  // Wait for the asynchronous queue to finish without contacting the real backend.
  for(let i=0;i<10;i++) await Promise.resolve();
}
(async()=>{
  await $('#btnTelaCheiaCompleto').onclick();
  assert.equal(document.fullscreenElement,$('#playerVideoCompleto'));
  assert.equal($('#btnTelaCheiaCompleto')['aria-pressed'],'true');
  await cut(120);
  assert.equal(captured.inicio_s,105);assert.equal(captured.fim_s,120);
  assert.equal(captured.video,'/original/4k.mp4');assert.equal(captured.status,'pendente');
  assert.equal(video.paused,false);assert.equal(video.playbackRate,5);
  assert.equal(document.fullscreenElement,$('#playerVideoCompleto'));
  assert.match($('#statusCorteSobreVideo').textContent,/pronto/);
  await cut(7);assert.equal(captured.inicio_s,0);assert.equal(captured.fim_s,7);
  await cut(200,10);assert.equal(captured.inicio_s,195);assert.equal(captured.fim_s,210);
  await cut(0);assert.equal(captured,null);
  await $('#btnTelaCheiaCompleto').onclick();
  assert.equal(document.fullscreenElement,null);
  assert.equal($('#btnTelaCheiaCompleto')['aria-pressed'],'false');
  assert.ok(html.indexOf('id="duracaoCorteCompleto"') < html.indexOf('id="playerVideoCompleto"'));
  console.log('OK: fullscreen mantém ações; corte retroativo, início do vídeo, offset, original e reprodução em 5x preservados.');
})().catch(error=>{console.error(error);process.exitCode=1;});
