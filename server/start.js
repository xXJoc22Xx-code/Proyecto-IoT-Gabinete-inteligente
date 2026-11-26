const fs=require('node:fs'),path=require('node:path'),https=require('node:https'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const dep=require('./deps');const {Service}=require('./service');
const root=path.resolve(__dirname,'..'),runtime=path.join(root,'runtime');
const config=JSON.parse(fs.readFileSync(path.join(runtime,'local.json')));
const tls={key:fs.readFileSync(path.join(runtime,'certs/server.key')),cert:fs.readFileSync(path.join(runtime,'certs/server.crt')),minVersion:'TLSv1.2'};
const log=fs.openSync(path.join(runtime,'broker.log'),'a');
const broker=spawn(config.brokerExe,['-c',path.join(runtime,'broker/mosquitto.conf')],{windowsHide:true,stdio:['ignore',log,log]});
broker.on('error',e=>console.error('No se pudo iniciar broker:',e.message));
broker.on('exit',code=>{if(code)console.error('Broker terminó. Revisar runtime/broker.log; no usar otro broker sin esta configuración.');});
const service=new Service(path.join(runtime,'gabinete.sqlite'));
const express=dep('express'),app=express(),RED=dep('node-red');
const server=https.createServer(tls,app);
// Puerto exclusivo para la placa; el dashboard sigue limitado a localhost.
const deviceApp=express();
deviceApp.disable('x-powered-by');
deviceApp.use(express.json({limit:'1kb'}));
deviceApp.post('/device/auth',require('./device-auth')(service,config.passwords.esp32_1));
deviceApp.use((err,req,res,next)=>res.status(400).json({error:'invalid_request'}));
const deviceServer=https.createServer(tls,deviceApp);
deviceServer.requestTimeout=6000;
deviceServer.headersTimeout=6000;
deviceServer.on('error',e=>console.error('HTTPS de la placa no disponible:',e.code));
const sessions=new Map(),attempts=new Map();
app.disable('x-powered-by');app.use(express.json({limit:'16kb'}));
app.use((req,res,next)=>{res.set({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'});if(!req.path.startsWith('/editor'))res.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'");next();});
function session(req){const token=(req.headers.cookie||'').split(';').map(s=>s.trim()).find(s=>s.startsWith('gabinete='))?.slice(9);const s=sessions.get(token);if(!s||s.until<Date.now()){sessions.delete(token);return null;}return {...s,token};}
function originOK(req){return req.headers.origin===`https://${req.headers.host}`;}
app.post('/api/login',(req,res)=>{
 if(!originOK(req))return res.status(403).json({error:'Origen no autorizado.'});
 const ip=req.socket.remoteAddress;let a=attempts.get(ip);if(!a||a.until<Date.now())a={count:0,until:Date.now()+60000};
 attempts.set(ip,a);if(a.count>=5)return res.status(429).json({error:'Espera un minuto antes de intentar otra vez.'});a.count++;
 if(req.body.user!==config.adminUser||typeof req.body.password!=='string'||req.body.password.length>200||!dep('bcryptjs').compareSync(req.body.password,config.adminHash))return res.status(401).json({error:'Credenciales inválidas.'});
 const token=crypto.randomBytes(32).toString('hex'),csrf=crypto.randomBytes(24).toString('hex');
 sessions.set(token,{csrf,user:config.adminUser,until:Date.now()+3600000});attempts.delete(ip);
 res.setHeader('Set-Cookie',`gabinete=${token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=3600`);res.json({csrf});
});
app.use('/api',(req,res,next)=>{const s=session(req);if(!s)return res.status(401).json({error:'Inicia sesión.'});req.auth=s;
 if(req.method!=='GET'&&(!originOK(req)||req.headers['x-csrf-token']!==s.csrf))return res.status(403).json({error:'Solicitud no autorizada.'});next();});
app.get('/api/session',(req,res)=>res.json({csrf:req.auth.csrf}));
app.get('/api/state',(req,res)=>res.json(service.getState()));
app.post('/api/logout',(req,res)=>{sessions.delete(req.auth.token);res.setHeader('Set-Cookie','gabinete=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0');res.json({ok:true});});
app.post('/api/users',(req,res)=>{try{res.json(service.saveUser(req.body,req.auth.user));}catch(e){res.status(400).json({error:e.message});}});
app.post('/api/users/delete',(req,res)=>{try{res.json(service.deleteUser(req.body.id,req.auth.user));}catch(e){res.status(400).json({error:e.message});}});
app.post('/api/cards/start',(req,res)=>{try{service.enroll(String(req.body.id),req.auth.user);res.json({ok:true});}catch(e){res.status(400).json({error:e.message});}});
app.post('/api/cards/confirm',(req,res)=>{try{service.confirmCard(req.auth.user);res.json({ok:true});}catch(e){res.status(400).json({error:e.message});}});
app.post('/api/cards/revoke',(req,res)=>{try{service.revoke(req.body.uid,req.auth.user);res.json({ok:true});}catch(e){res.status(400).json({error:e.message});}});
app.use(express.static(path.join(__dirname,'public')));
const flows=[{id:'tab-gabinete',type:'tab',label:'Gabinete · eventos y persistencia'},
 {id:'mqtt-source',type:'gabinete-source',z:'tab-gabinete',name:'MQTTS validado',x:180,y:140,wires:[['persist-events']]},
 {id:'persist-events',type:'function',z:'tab-gabinete',name:'Validar, guardar SQLite y confirmar',func:"global.get('gabinete').process(msg.topic,msg.payload,msg.retained); return null;",outputs:1,x:500,y:140,wires:[[]]},
 {id:'explanation',type:'comment',z:'tab-gabinete',name:'Los eventos pasan por este flujo antes de guardarse y recibir acuse.',x:360,y:60,wires:[]}];
const flowPath=path.join(runtime,'red/flows.json');if(!fs.existsSync(flowPath))fs.writeFileSync(flowPath,JSON.stringify(flows,null,2));
RED.init(server,{userDir:path.join(runtime,'red'),nodesDir:path.join(__dirname,'nodes'),flowFile:'flows.json',httpAdminRoot:'/editor',httpNodeRoot:'/red',credentialSecret:config.credentialSecret,
 adminAuth:{type:'credentials',users:[{username:config.adminUser,password:config.adminHash,permissions:'*'}]},functionGlobalContext:{gabinete:service},
 logging:{console:{level:'warn',metrics:false,audit:false}},editorTheme:{projects:{enabled:false}}});
app.use('/editor',RED.httpAdmin);app.use('/red',RED.httpNode);
RED.start().then(()=>server.listen(config.httpsPort,'127.0.0.1',()=>{
 deviceServer.listen(config.authPort||8443,'0.0.0.0',()=>console.log('Autenticacion de placa HTTPS: puerto '+(config.authPort||8443)));
 console.log(`Dashboard HTTPS: https://localhost:${config.httpsPort}`);
 service.start({url:`mqtts://localhost:${config.mqttPort}`,username:'servidor',password:config.passwords.servidor,ca:fs.readFileSync(path.join(runtime,'certs/ca.crt'))});
})).catch(e=>{console.error(e);broker.kill();process.exitCode=1;});
function stop(){deviceServer.close();server.close();RED.stop().finally(()=>{service.close();broker.kill();process.exit(0);});}
process.on('SIGINT',stop);process.on('SIGTERM',stop);
