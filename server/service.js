const {DatabaseSync} = require('node:sqlite');
const crypto = require('node:crypto');
const {EventEmitter} = require('node:events');
const dep = require('./deps');
const {pressureData} = require('./pressure-data');
const now=()=>Math.floor(Date.now()/1000);
const uidOK=x=>typeof x==='string' && /^(?:[0-9A-F]{2}:){3}(?:[0-9A-F]{2}|(?:[0-9A-F]{2}:){3}[0-9A-F]{2}|(?:[0-9A-F]{2}:){6}[0-9A-F]{2})$/.test(x);
class Service extends EventEmitter {
 constructor(dbPath) {
  super(); this.db=new DatabaseSync(dbPath); this.connected=false; this.status={}; this.enrollment=null; this.applied=0;
  this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
   CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,active INTEGER NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,rounds INTEGER NOT NULL);
   CREATE TABLE IF NOT EXISTS cards(uid TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id));
   CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
   INSERT OR IGNORE INTO meta VALUES('revision',1);
   CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,source TEXT NOT NULL,occurred INTEGER,received INTEGER NOT NULL,kind TEXT NOT NULL,user_id TEXT,operation_id TEXT,data TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at INTEGER NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL);
  `);
 }
 revision(){return this.db.prepare("SELECT value FROM meta WHERE key='revision'").get().value;}
 audit(actor,action,target){this.db.prepare('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)').run(now(),actor,action,target);}
 mutate(actor,action,target,fn){this.db.exec('BEGIN IMMEDIATE');try{fn();this.db.exec("UPDATE meta SET value=value+1 WHERE key='revision'");this.audit(actor,action,target);this.db.exec('COMMIT');}catch(e){this.db.exec('ROLLBACK');throw e;}}
 users(){return this.db.prepare('SELECT id,name,active FROM users ORDER BY CAST(id AS INTEGER)').all().map(u=>({...u,cards:this.db.prepare('SELECT uid FROM cards WHERE user_id=?').all(u.id).map(c=>c.uid)}));}
 saveUser(body,actor) {
  const id=String(body.id||''); const name=String(body.name||'').trim();
  if(!/^[1-9][0-9]{0,5}$/.test(id)||!name||name.length>80) throw Error('ID de 1 a 6 dígitos sin cero inicial y nombre de 1 a 80 caracteres.');
  const old=this.db.prepare('SELECT * FROM users WHERE id=?').get(id);
  const mode=body.mode??'create';
  if(!['create','edit'].includes(mode))throw Error('Operación de usuario inválida.');
  if(mode==='create'&&old)throw Error('Ese ID ya existe. Usa otro ID o pulsa Editar en el usuario existente.');
  if(mode==='edit'&&(!old||body.edit_id!==id))throw Error('Selecciona el usuario con Editar. Su ID no puede cambiarse.');
  const normalizeName=value=>value.normalize('NFKC').trim().replace(/\s+/g,' ').toLocaleLowerCase('es-MX');
  if(this.db.prepare('SELECT id,name FROM users WHERE id<>?').all(id).some(u=>normalizeName(u.name)===normalizeName(name)))
   throw Error('Ya existe un usuario con ese nombre. Usa un nombre completo que lo distinga.');
  if(!old&&this.users().length>=50) throw Error('Límite de maqueta: 50 usuarios.');
  const pin=body.password;
  if((!old||pin)&& (typeof pin!=='string'||!/^[0-9A-D]{6,12}$/.test(pin))) throw Error('Contraseña de 6 a 12 caracteres: 0–9 y A–D.');
  let salt=old?.salt,hash=old?.hash,rounds=old?.rounds;
  if(pin){salt=crypto.randomBytes(16).toString('hex');rounds=20000;hash=crypto.pbkdf2Sync(pin,Buffer.from(salt,'hex'),rounds,32,'sha256').toString('hex');}
  this.mutate(actor,mode==='edit'?'editar_usuario':'crear_usuario',id,()=>{
   if(mode==='create')this.db.prepare('INSERT INTO users VALUES(?,?,?,?,?,?)').run(id,name,body.active===false?0:1,salt,hash,rounds);
   else this.db.prepare('UPDATE users SET name=?,active=?,salt=?,hash=?,rounds=? WHERE id=?').run(name,body.active===false?0:1,salt,hash,rounds,id);
  });
  return {revision:this.revision()};
 }
 deleteUser(id,actor){
  if(typeof id!=='string'||!/^[1-9][0-9]{0,5}$/.test(id))throw Error('ID de usuario inválido.');
  if(!this.db.prepare('SELECT id FROM users WHERE id=?').get(id))throw Error('Usuario no encontrado.');
  this.mutate(actor,'eliminar_usuario',id,()=>{
   this.db.prepare('DELETE FROM cards WHERE user_id=?').run(id);
   this.db.prepare('DELETE FROM users WHERE id=?').run(id);
  });
  if(this.enrollment?.user_id===id){
   const token=this.enrollment.token;
   this.enrollment=null;
   try{this.publish('acceso/enroll',{token,cancel:true});}catch{}
  }
  return {revision:this.revision()};
 }
 snapshot(){return this.db.prepare('SELECT id,name,active FROM users').all().map(u=>({...u,cards:this.db.prepare('SELECT uid FROM cards WHERE user_id=?').all(u.id).map(c=>c.uid)}));}
 publish(topic,data){if(!this.connected) throw Error('Broker sin conexión.');this.client.publish('gabinete/'+topic,JSON.stringify(data),{qos:1,retain:false});}
 start(options){
  this.client=dep('mqtt').connect(options.url,{...options,clientId:'servidor-'+crypto.randomBytes(4).toString('hex'),clean:true,reconnectPeriod:2000,rejectUnauthorized:true});
  this.client.on('connect',()=>{this.connected=true;this.client.subscribe(['acceso/hello','acceso/eventos','acceso/enrollment','acceso/solicitud','puerta/respuesta','inventario/eventos','estado/esp32_1','estado/esp32_2'].map(x=>'gabinete/'+x),{qos:1});});
  this.client.on('offline',()=>{this.connected=false;});
  this.client.on('error',()=>{this.connected=false;});
  this.client.on('message',(topic,payload,packet)=>{if(payload.length<=65536)this.emit('incoming',{topic,payload:payload.toString(),retained:packet.retain});});
 }
 process(topic,raw,retained=false){
  try {
   const p=typeof raw==='string'?JSON.parse(raw):raw;
   if(!p||typeof p!=='object'||Array.isArray(p))return;
   const t=topic.replace(/^gabinete\//,'');
   if(t==='acceso/hello'){
    if(retained||typeof p.nonce!=='string'||p.nonce.length>80)return;
    this.applied=Number(p.revision)||0;
    this.status.esp32_1={...p,seen:now(),online:true};
    this.publish('acceso/config',{nonce:p.nonce,revision:this.revision(),lease:25,users:this.snapshot()});
    const e=this.enrollment;
    if(e&&e.expires>now())this.publish('acceso/enroll',{token:e.token,expires:e.expires});
    return;
   }
   if(t.startsWith('estado/')){
    const device=t.split('/')[1];
    this.status[device]={...this.status[device],...p,seen:retained?0:now()};return;
   }
   if(t==='acceso/enrollment'){
    const e=this.enrollment;
    if(!retained&&e&&e.expires>now()&&p.token===e.token){
     if(p.ready===true){e.ready=true;e.reader_available=p.reader_available;}
     if(uidOK(p.uid)&&!e.uid){e.uid=p.uid;e.ready=true;}
    }
    return;
   }
   if(t==='acceso/eventos'||t==='inventario/eventos'){
    if(typeof p.id!=='string'||p.id.length>100||typeof p.kind!=='string'||p.kind.length>60)return;
    const source=t==='acceso/eventos'?'esp32_1':'esp32_2';
    // Lista explícita de campos: nunca guardar contraseñas ni verificadores enviados por error.
    const data={};for(const k of ['method','result','weight_g','before_g','after_g','presence','reason','simulated'])if(['string','number','boolean'].includes(typeof p[k]))data[k]=p[k];
    if(source==='esp32_2')Object.assign(data,pressureData(p));
    const occurred=Number.isInteger(p.at)&&p.at>1700000000&&p.at<=now()+60?p.at:null;
    const user=typeof p.user_id==='string'?p.user_id.slice(0,6):null;
    const op=typeof p.operation_id==='string'?p.operation_id.slice(0,100):null;
    this.db.prepare('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?)').run(p.id,source,occurred,now(),p.kind,user,op,JSON.stringify(data));
    this.publish(source==='esp32_1'?'acceso/acuse':'inventario/acuse',{id:p.id});return;
   }
   if(t==='puerta/respuesta'&&!retained){this.status.lastResponse={...p,seen:now()};}
  } catch(e){console.error('Mensaje rechazado o almacenamiento fallido:',e.message);}
 }
 getState(){
  const rows=this.db.prepare('SELECT * FROM events ORDER BY received DESC,rowid DESC LIMIT 200').all().map(e=>({...e,data:JSON.parse(e.data)}));
  // Proyectar la auditoria tambien en Eventos, incluidas eliminaciones anteriores.
  const deletions=this.db.prepare("SELECT id,at,actor,target FROM audit WHERE action='eliminar_usuario' ORDER BY at DESC,id DESC LIMIT 200").all()
   .map(a=>({id:'audit-delete-'+a.id,source:'servidor',occurred:a.at,received:a.at,kind:'usuario_eliminado',user_id:a.target,operation_id:null,data:{actor:a.actor}}));
  const timeline=[...deletions,...rows].sort((a,b)=>b.received-a.received).slice(0,200);
  const pressure=this.db.prepare("SELECT * FROM events WHERE source='esp32_2' AND (json_type(data,'$.pressure_raw')='array' OR kind='sensores_no_disponibles') ORDER BY COALESCE(occurred,received) DESC,received DESC,rowid DESC LIMIT 1").get();
  return {broker:this.connected,revision:this.revision(),applied:this.applied,devices:this.status,
   users:this.users(),events:timeline,pressure:pressure?{...pressure,data:JSON.parse(pressure.data),stale:now()-(pressure.occurred||pressure.received)>20}:null,
   enrollment:this.enrollment&&this.enrollment.expires>now()?{user_id:this.enrollment.user_id,expires:this.enrollment.expires,uid:this.enrollment.uid||null,ready:!!this.enrollment.ready,reader_available:this.enrollment.reader_available}:null,
   audit:this.db.prepare('SELECT * FROM audit ORDER BY id DESC LIMIT 30').all(),serverTime:now()};
 }
 enroll(id,actor){
  if(!this.db.prepare('SELECT id FROM users WHERE id=? AND active=1').get(id))throw Error('Usuario activo no encontrado.');
  if(!this.connected||!this.status.esp32_1?.online||now()-this.status.esp32_1.seen>25)throw Error('ESP32 1 sin conexión reciente.');
  if(this.status.esp32_1.reader_available===false)throw Error('El lector RC522 no responde. Revisa su conexión y reinicia la placa.');
  if(this.enrollment?.expires>now())throw Error('Ya hay un registro de tarjeta en curso.');
  this.enrollment={user_id:id,token:crypto.randomBytes(16).toString('hex'),expires:now()+30};
  this.publish('acceso/enroll',{token:this.enrollment.token,expires:this.enrollment.expires});this.audit(actor,'iniciar_registro_tarjeta',id);
 }
 confirmCard(actor){
  const e=this.enrollment;if(!e||e.expires<=now()||!uidOK(e.uid))throw Error('No hay tarjeta detectada vigente.');
  if(!this.db.prepare('SELECT id FROM users WHERE id=? AND active=1').get(e.user_id))throw Error('Usuario activo no encontrado.');
  if(this.db.prepare('SELECT uid FROM cards WHERE uid=?').get(e.uid))throw Error('Tarjeta ya asociada. Revócala antes de reasignarla.');
  this.mutate(actor,'agregar_tarjeta',e.user_id,()=>this.db.prepare('INSERT INTO cards VALUES(?,?)').run(e.uid,e.user_id));
  this.enrollment=null;
  // El guardado ya se completo; una desconexion no debe presentarlo como fallido.
  try{this.publish('acceso/enroll',{token:e.token,cancel:true});}catch{}
 }
 revoke(uid,actor){if(!uidOK(uid))throw Error('UID inválido.');this.mutate(actor,'revocar_tarjeta',uid,()=>this.db.prepare('DELETE FROM cards WHERE uid=?').run(uid));}
 close(){this.client?.end(true);this.db.close();}
}
module.exports={Service,uidOK};
