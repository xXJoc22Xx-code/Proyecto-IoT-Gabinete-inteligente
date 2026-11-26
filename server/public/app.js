let csrf='',current=null,editingId=null,usersSignature='',eventsSignature='',alertSignature=null,page=0;
const PAGE_SIZE=25;
const $=id=>document.getElementById(id);
const date=s=>s?new Date(s*1000).toLocaleString('es-MX',{timeZone:'America/Mexico_City',dateStyle:'short',timeStyle:'medium'}):'Hora no disponible';
// Todos los avisos desaparecen solos a los 6 s, sin importar quién los escriba.
const NOTICE_MS=6000;
let noticeTimer=null;
const notice=(t,reveal=true)=>{$('notice').textContent=t;if(reveal&&t)$('notice').scrollIntoView({block:'nearest'});};
new MutationObserver(()=>{clearTimeout(noticeTimer);if($('notice').textContent)noticeTimer=setTimeout(()=>{$('notice').textContent='';},NOTICE_MS);})
 .observe($('notice'),{childList:true,characterData:true,subtree:true});
async function api(path,body){
 const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
 if(r.status===401)show(false);
 let p;
 try{p=await r.json();}catch{
  if(r.status===404)throw Error('El servidor no reconoce esta función. Reinicia el servidor desde C:\\IoT_ProyectoFinal\\Iniciar-servidor.cmd y recarga con Ctrl+F5.');
  throw Error(`El servidor devolvió una respuesta inesperada (HTTP ${r.status}). Comprueba que abriste el dashboard del servidor actualizado.`);
 }
 if(!r.ok)throw Error(p?.error||'Error del servidor');
 return p;
}
function show(logged){if(!logged)resetUserForm();$('login').hidden=logged;$('dashboard').hidden=!logged;$('logout').hidden=!logged;$(logged?'dashboardNotice':'loginNotice').append($('notice'));}
function resetUserForm(){
 const f=$('userForm');editingId=null;f.reset();f.elements.id.readOnly=false;
 f.elements.password.required=true;$('saveUser').textContent='Crear usuario';
 $('userFormMode').textContent='Nuevo usuario';$('clearUser').textContent='Limpiar formulario';
}
function cell(row,value,label){const td=document.createElement('td');if(label)td.dataset.label=label;if(value!==null)td.textContent=String(value??'—');row.append(td);return td;}
function button(parent,label,fn){const b=document.createElement('button');b.textContent=label;b.onclick=()=>Promise.resolve().then(fn).catch(e=>notice(e.message));parent.append(b);}
async function deleteUser(user){
 if(!confirm(`¿Eliminar al usuario ${user.name} (ID ${user.id}) y sus tarjetas? El historial de accesos se conservará.`))return;
 await api('users/delete',{id:user.id});
 if(editingId===user.id)resetUserForm();
 notice('Usuario eliminado. Espera la sincronización de permisos con la ESP32 1.');
 await refresh();
}

/* ---------- Insignias: color + icono (CSS ::before) + texto ---------- */
function badge(el,level,text){el.className=el.className.split(' ').filter(c=>c==='badge'||c==='big').join(' ')+' '+level;el.textContent=text;}

/* ---------- Etiquetas legibles de eventos ---------- */
const KINDS={
 usuario_eliminado:['Usuario eliminado','info','system'],
 acceso_denegado:['Acceso denegado','warn','access'],
 acceso_no_disponible:['Acceso no disponible','warn','access'],
 apertura_solicitada:['Apertura solicitada','info','access'],
 apertura_iniciada:['Apertura iniciada','info','door'],
 apertura_no_disponible:['Apertura no disponible','warn','door'],
 apertura_sin_confirmar:['Apertura sin confirmar','crit','door'],
 resultado_apertura:['Resultado de apertura','info','door'],
 servo_abierto:['Servo abierto','ok','door'],
 servo_cerrado:['Servo cerrado','ok','door'],
 cierre_solicitado:['Cierre solicitado','info','door'],
 cierre_sin_confirmar:['Cierre sin confirmar','crit','door'],
 resultado_cierre:['Resultado de cierre','info','door'],
 bascula_no_disponible:['Báscula no disponible','warn','inventory'],
 inventario_indeterminado:['Inventario indeterminado','warn','inventory'],
 lectura_peso:['Lectura de peso (histórico)','info','inventory'],
 lectura_presion:['Lectura de presión','info','inventory'],
 sensores_no_disponibles:['Sensores sin lectura','warn','inventory'],
 cambio_mixto:['Cambio de presencia en varios sensores','info','inventory'],
 sin_cambio:['Sin cambio de presencia','info','inventory'],
 retiro:['Retiro de objeto','ok','inventory'],
 devolucion:['Devolución de objeto','ok','inventory'],
 arranque:['Arranque de placa','info','system'],
 prueba_integracion:['Prueba de integración','info','system']
};
const kindInfo=k=>KINDS[k]||[k.replace(/_/g,' '),'info','system'];
const PRESENCE={present:'objeto presente',absent:'objeto ausente',unknown:'presencia indeterminada'};
function detailItems(d,kind){
 const out=[];
 if(d.actor)out.push(kind==='usuario_eliminado'?d.actor+' eliminó usuario':'Administrador: '+d.actor);
 if(d.simulated)out.push('Simulado');
 if(d.method)out.push('Método: '+({card:'tarjeta',keypad:'teclado',rfid:'tarjeta'}[d.method]||d.method));
 if(d.result)out.push('Resultado: '+String(d.result).replace(/_/g,' '));
 if(d.reason)out.push('Motivo: '+String(d.reason).replace(/_/g,' '));
 if(typeof d.before_g==='number'&&typeof d.after_g==='number')out.push(`Peso: ${d.before_g} g → ${d.after_g} g`);
 else if(typeof d.weight_g==='number')out.push(`Peso: ${d.weight_g} g`);
 if(Array.isArray(d.pressure_raw)){
  d.pressure_raw.forEach((raw,i)=>out.push(`Sensor ${i+1} (GPIO${[34,35,32][i]}): ${raw} ADC · ${PRESENCE[d.sensor_presence?.[i]]||'presencia indeterminada'}`));
  if(d.pressure_calibrated===false)out.push('Falta calibrar presencia');
  else if(d.pressure_stable===false)out.push('Lectura inestable');
 }
 if(Array.isArray(d.before_raw)&&Array.isArray(d.after_raw)){
  d.before_raw.forEach((raw,i)=>out.push(`S${i+1}: ${raw} → ${d.after_raw[i]} ADC; ${PRESENCE[d.before_presence?.[i]]||'indeterminada'} → ${PRESENCE[d.after_presence?.[i]]||'indeterminada'}`));
 }
 if(d.presence)out.push('Presencia: '+(PRESENCE[d.presence]||d.presence));
 return out;
}

/* ---------- Alertas: visual + sonora + táctil ---------- */
let soundOn=false,audio=null;
try{soundOn=localStorage.getItem('gabinete.sound')==='1';}catch{}
function paintSound(){const b=$('soundToggle');b.setAttribute('aria-pressed',String(soundOn));b.textContent=soundOn?'🔔 Alertas sonoras: activadas':'🔕 Alertas sonoras: desactivadas';}
function beep(){
 if(!soundOn)return;
 try{
  audio=audio||new (window.AudioContext||window.webkitAudioContext)();
  const t=audio.currentTime;
  for(const [i,f] of [[0,880],[0.28,660],[0.56,880]]){
   const o=audio.createOscillator(),g=audio.createGain();o.frequency.value=f;o.connect(g);g.connect(audio.destination);
   g.gain.setValueAtTime(0.0001,t+i);g.gain.exponentialRampToValueAtTime(0.25,t+i+0.02);g.gain.exponentialRampToValueAtTime(0.0001,t+i+0.22);
   o.start(t+i);o.stop(t+i+0.25);
  }
 }catch{}
 try{navigator.vibrate&&navigator.vibrate([200,100,200,100,200]);}catch{}
}
$('soundToggle').onclick=()=>{
 soundOn=!soundOn;try{localStorage.setItem('gabinete.sound',soundOn?'1':'0');}catch{}
 paintSound();if(soundOn)beep();
};
paintSound();

function evaluate(s){
 const fresh=d=>d?.online===true&&s.serverTime-d.seen<25;
 const crit=[],warn=[];
 if(!s.broker)crit.push('El servidor perdió conexión con el broker MQTTS.');
 if(!fresh(s.devices.esp32_1))crit.push('El control de acceso (ESP32 1) no reporta datos recientes.');
 if(!fresh(s.devices.esp32_2))warn.push('El gabinete y los sensores de presión (ESP32 2) no reportan datos recientes.');
 if(fresh(s.devices.esp32_2)){
  if(s.devices.esp32_2.pressure_calibrated===false)warn.push('Calibra los tres sensores de presión para detectar presencia.');

 }
 const denied=s.events.filter(e=>e.kind==='acceso_denegado'&&s.serverTime-e.received<300).length;
 if(denied>=3)crit.push(`${denied} accesos denegados en los últimos 5 minutos.`);
 const unconfirmed=s.events.find(e=>/_sin_confirmar$/.test(e.kind)&&s.serverTime-e.received<300);
 if(unconfirmed)crit.push('Una orden de puerta no fue confirmada por la placa.');
 if(!(s.applied===s.revision&&fresh(s.devices.esp32_1)))warn.push(`Permisos pendientes de sincronizar (servidor ${s.revision}, placa ${s.applied}).`);
 return {crit,warn,fresh};
}
function renderBanner(s,ev){
 const level=ev.crit.length?'crit':ev.warn.length?'warn':'ok';
 const items=[...ev.crit,...ev.warn];
 const signature=level+'|'+items.join('|');
 const b=$('banner');
 if(signature===alertSignature)return;
 const previous=alertSignature;alertSignature=signature;
 b.className='banner '+level;
 $('bannerIcon').textContent={ok:'✔',warn:'▲',crit:'✖'}[level];
 $('bannerTitle').textContent={ok:'Sistema operando con normalidad',warn:'Atención: hay avisos',crit:'Estado crítico'}[level];
 $('bannerList').replaceChildren(...items.map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
 document.title=(level==='crit'?'⚠ CRÍTICO · ':level==='warn'?'▲ Aviso · ':'')+'Gabinete inteligente';
 if(level==='crit'&&previous!==null&&!previous.startsWith('crit'))beep();
 else if(level==='crit'&&previous!==null)beep();
}

/* ---------- Lecturas de los tres sensores (ADC de 12 bits) ---------- */
function renderSpark(events){
 const pts=events.filter(e=>e.source==='esp32_2'&&Array.isArray(e.data.pressure_raw))
  .sort((a,b)=>(a.occurred||a.received)-(b.occurred||b.received)).slice(-30);
 const box=$('spark');box.replaceChildren();
 if(pts.length<2){const p=document.createElement('p');p.textContent='Sin historial suficiente de presión.';box.append(p);return;}
 const w=300,h=56,ns='http://www.w3.org/2000/svg';
 for(let sensor=0;sensor<3;sensor++){
  const label=document.createElement('p');label.textContent=`Sensor ${sensor+1} · GPIO${[34,35,32][sensor]} · ADC 0–4095`;box.append(label);
  const vals=pts.map(e=>e.data.pressure_raw[sensor]);
  const xy=vals.map((value,i)=>[Math.round(i*(w-8)/(pts.length-1))+4,Math.round(h-8-(value/4095)*(h-16))]);
  const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('role','img');
  svg.setAttribute('aria-label',`Sensor ${sensor+1}: últimas ${pts.length} lecturas ADC, mínimo ${Math.min(...vals)}, máximo ${Math.max(...vals)}, última ${vals[vals.length-1]}.`);
  const line=document.createElementNS(ns,'polyline');line.setAttribute('points',xy.map(p=>p.join(',')).join(' '));svg.append(line);box.append(svg);
 }
}
function renderPressure(s){
 const p=s.pressure,d=p?.data,raw=d?.pressure_raw;
 const online=s.devices.esp32_2?.online===true&&s.serverTime-s.devices.esp32_2.seen<25;
 $('pressure').textContent=Array.isArray(raw)?'3 sensores FSR402':'Sin lectura';
 $('pressureSensors').replaceChildren();
 if(Array.isArray(raw))raw.forEach((value,i)=>{
  const li=document.createElement('li');li.textContent=`Sensor ${i+1} · GPIO${[34,35,32][i]}: ${value} / 4095 ADC · ${PRESENCE[d.sensor_presence[i]]||'presencia indeterminada'}`;
  $('pressureSensors').append(li);
 });
 $('presence').textContent=!p?'Estado desconocido':p.stale||!online?'Dato desactualizado':!raw?'Sensores sin lectura':!d.pressure_calibrated?'Sin calibrar · presencia indeterminada':!d.pressure_stable||s.devices.esp32_2?.pressure_ready===false?'Presencia sin lectura estable':(PRESENCE[d.presence]||'presencia indeterminada');
 $('pressureTime').textContent=p?`${d.simulated?'SIMULADO · ':''}Última lectura: ${date(p.occurred)} · recibida: ${date(p.received)}`:'';
 renderSpark(s.events);
}

/* ---------- Render principal ---------- */
function render(s){current=s;
 const ev=evaluate(s),fresh=ev.fresh;
 renderBanner(s,ev);
 badge($('stBroker'),s.broker?'ok':'crit',s.broker?'Conectado (TLS)':'Desconectado');
 badge($('stAccess'),fresh(s.devices.esp32_1)?'ok':'crit',fresh(s.devices.esp32_1)?'En línea':'Sin datos recientes');
 badge($('stCabinet'),fresh(s.devices.esp32_2)?'ok':'warn',fresh(s.devices.esp32_2)?'En línea':'Sin datos recientes');
 $('connection').textContent=s.broker?'Broker conectado mediante TLS':'Broker desconectado';
 $('devices').textContent=`Acceso: ${fresh(s.devices.esp32_1)?'conectado':'sin datos recientes'} · Gabinete: ${fresh(s.devices.esp32_2)?'conectado':'sin datos recientes'}`;

 const synced=s.applied===s.revision&&fresh(s.devices.esp32_1);
 badge($('stSync'),synced?'ok':'warn',synced?'Sincronizado':'Pendiente');
 $('sync').textContent=synced?`Aplicada · versión ${s.revision}`:`Servidor ${s.revision}, placa ${s.applied}`;

 const door=s.events.find(e=>e.kind==='servo_abierto'||e.kind==='servo_cerrado');
 if(door){badge($('stDoor'),door.kind==='servo_abierto'?'warn':'ok',door.kind==='servo_abierto'?'Abierto':'Cerrado');$('doorTime').textContent='Desde: '+date(door.occurred||door.received);}
 else{badge($('stDoor'),'off','Sin dato');$('doorTime').textContent='Aún no hay órdenes registradas.';}
 const acc=s.events.find(e=>['acceso_denegado','apertura_iniciada','apertura_solicitada'].includes(e.kind));
 $('lastAccess').textContent=acc?`Último intento: ${kindInfo(acc.kind)[0].toLowerCase()}${acc.user_id?' (usuario '+acc.user_id+')':''} · ${date(acc.occurred||acc.received)}`:'Sin intentos de acceso registrados.';

 renderPressure(s);

 renderEvents(s);

 const signature=JSON.stringify(s.users);
 if(signature!==usersSignature){
  usersSignature=signature;
  $('users').replaceChildren();
  for(const u of s.users){
   const tr=document.createElement('tr');
   cell(tr,u.id,'ID');cell(tr,u.name,'Nombre');
   const st=cell(tr,null,'Estado'),b=document.createElement('b');b.className='badge';badge(b,u.active?'ok':'off',u.active?'Activo':'Deshabilitado');st.append(b);
   const cards=cell(tr,null,'Tarjetas');
   if(!u.cards.length)cards.textContent='Sin tarjetas';
   for(const uid of u.cards){const div=document.createElement('div');div.className='cardRow';const c=document.createElement('code');c.textContent=uid;div.append(c);button(div,'Revocar',async()=>{if(confirm('¿Revocar esta tarjeta?')){await api('cards/revoke',{uid});notice('Revocación guardada; espera sincronización.');await refresh();}});cards.append(div);}
   const actions=cell(tr,null,'Acciones');
   button(actions,'Editar',()=>{const f=$('userForm');editingId=u.id;f.elements.id.readOnly=true;f.elements.password.required=false;$('saveUser').textContent='Guardar cambios';$('userFormMode').textContent='Editando usuario ID '+u.id;$('clearUser').textContent='Cancelar edición';f.elements.id.value=u.id;f.elements.name.value=u.name;f.elements.active.checked=!!u.active;f.elements.password.value='';f.elements.name.focus();});
   button(actions,'Agregar tarjeta',async()=>{await api('cards/start',{id:u.id});notice('Acerca una tarjeta al RC522 en los próximos 30 segundos.');await refresh();});
   button(actions,'Eliminar',()=>deleteUser(u));
   $('users').append(tr);
  }
 }
 const en=s.enrollment;$('enrollment').textContent=en?`Usuario ${en.user_id} · ${en.uid?'Tarjeta detectada: '+en.uid+' · Pulsa Confirmar tarjeta detectada':en.reader_available===false?'El lector RC522 no responde; revisa conexión y reinicia la placa':en.ready?'Lector preparado · Acerca una tarjeta':'Esperando que la ESP32 active el registro'} · vence ${date(en.expires)}`:'Sin registro de tarjeta en curso.';$('confirmCard').disabled=!en?.uid;
 $('audit').replaceChildren();for(const a of s.audit){const li=document.createElement('li');li.textContent=`${date(a.at)} · ${a.actor} · ${a.action.replace(/_/g,' ')} · ${a.target}`;$('audit').append(li);}
}

/* ---------- Eventos: filtro + paginación ---------- */
function filteredEvents(events,cat){
 return events.filter(e=>{
  const [,level,c]=kindInfo(e.kind);
  return cat==='all'||(cat==='warn'?level==='warn'||level==='crit':c===cat);
 });
}
function renderEvents(s){
 const cat=$('filterCat').value;
 const list=filteredEvents(s.events,cat);
 const pages=Math.max(1,Math.ceil(list.length/PAGE_SIZE));
 if(page>=pages)page=pages-1;
 const slice=list.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
 const signature=JSON.stringify([cat,page,slice.map(e=>e.id)]);
 $('eventCount').textContent=`${list.length} de ${s.events.length} eventos`;
 $('pageInfo').textContent=`Página ${page+1} de ${pages}`;
 $('prevPage').disabled=page===0;$('nextPage').disabled=page>=pages-1;
 if(signature===eventsSignature)return;
 eventsSignature=signature;
 $('events').replaceChildren();
 if(!slice.length){const tr=document.createElement('tr'),td=cell(tr,'No hay eventos con este filtro.');td.colSpan=4;$('events').append(tr);return;}
 for(const e of slice){
  const tr=document.createElement('tr');
  const when=cell(tr,null,'Fecha');when.className='when';when.append(date(e.occurred||e.received));
  if(e.occurred&&Math.abs(e.received-e.occurred)>5){const sm=document.createElement('small');sm.textContent='recibido '+date(e.received);when.append(sm);}
  cell(tr,e.user_id?'Usuario '+e.user_id:'Sistema','Usuario');
  const [label,level]=kindInfo(e.kind),k=cell(tr,null,'Evento'),b=document.createElement('b');b.className='badge';badge(b,level,label);k.append(b);
  const d=cell(tr,null,'Detalle'),ul=document.createElement('ul');ul.className='detail';
  const items=detailItems(e.data,e.kind);if(!items.length)items.push('—');
  for(const t of items){const li=document.createElement('li');li.textContent=t;ul.append(li);}
  d.append(ul);$('events').append(tr);
 }
}
$('filterCat').onchange=()=>{page=0;current&&renderEvents(current);};
$('prevPage').onclick=()=>{if(page>0){page--;current&&renderEvents(current);}};
$('nextPage').onclick=()=>{page++;current&&renderEvents(current);};

async function refresh(){render(await api('state'));}
$('loginForm').onsubmit=async e=>{e.preventDefault();const f=e.target;try{const r=await api('login',{user:f.elements.user.value,password:f.elements.password.value});csrf=r.csrf;f.elements.password.value='';show(true);notice('Sesión iniciada.');await refresh();}catch(e){notice(e.message);}};
$('logout').onclick=async()=>{try{await api('logout',{});csrf='';show(false);notice('Sesión cerrada.');}catch(e){notice(e.message);}};
$('userForm').onsubmit=async e=>{e.preventDefault();const f=e.target;try{await api('users',{mode:editingId===null?'create':'edit',edit_id:editingId,id:f.elements.id.value,name:f.elements.name.value,password:f.elements.password.value,active:f.elements.active.checked});resetUserForm();notice('Usuario guardado. Espera confirmación de sincronización antes de probar.');await refresh();}catch(e){notice(e.message);}};
$('clearUser').onclick=resetUserForm;
$('confirmCard').onclick=async()=>{try{await api('cards/confirm',{});notice('Tarjeta asociada. Espera sincronización.');await refresh();}catch(e){notice(e.message);}};
$('export').onclick=()=>{if(!current)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(current.events,null,2)],{type:'application/json'}));a.download='eventos-gabinete.json';a.click();URL.revokeObjectURL(a.href);};
(async()=>{try{csrf=(await api('session')).csrf;show(true);await refresh();}catch{show(false);}})();
setInterval(()=>{if(!$('dashboard').hidden)refresh().catch(e=>notice(e.message,false));},3000);

// Pestanas: un solo panel visible; flechas/Home/End, Tab hacia el contenido.
const panelIds=['status','history','admin','auditPanel'];
function selectTab(id,{focus=false,updateHash=false}={}){
 if(!panelIds.includes(id))id='status';
 for(const panelId of panelIds){
  const selected=panelId===id,tab=$('tab-'+panelId);
  tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
  $(panelId).hidden=!selected;
 }
 if(focus)$('tab-'+id).focus();
 if(updateHash&&location.hash!=='#'+id)history.pushState(null,'','#'+id);
}
for(const [index,id] of panelIds.entries()){
 const tab=$('tab-'+id);
 tab.addEventListener('click',()=>selectTab(id,{updateHash:true}));
 tab.addEventListener('keydown',event=>{
  let next;
  if(event.key==='ArrowRight')next=(index+1)%panelIds.length;
  else if(event.key==='ArrowLeft')next=(index+panelIds.length-1)%panelIds.length;
  else if(event.key==='Home')next=0;
  else if(event.key==='End')next=panelIds.length-1;
  else return;
  event.preventDefault();selectTab(panelIds[next],{focus:true,updateHash:true});
 });
}
window.addEventListener('hashchange',()=>selectTab(location.hash.slice(1)));
window.addEventListener('popstate',()=>selectTab(location.hash.slice(1)));
selectTab(location.hash.slice(1));
