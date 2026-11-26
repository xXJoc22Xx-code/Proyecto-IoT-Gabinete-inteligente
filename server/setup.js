const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const dep = require('./deps');
const root = path.resolve(__dirname, '..');
const runtime = path.join(root, 'runtime');
if (fs.existsSync(path.join(runtime, 'local.json'))) throw Error('Configuración existente. No se sobrescribe.');
fs.mkdirSync(runtime, {recursive:true});
for (const dir of ['certs','broker','red','provision/esp32_1','provision/esp32_2']) fs.mkdirSync(path.join(runtime,dir),{recursive:true});
const openssl = process.env.OPENSSL_PATH || 'openssl';
const brokerExe = process.env.MOSQUITTO_PATH || path.join(root, 'mosquitto/mosquitto.exe');
const ips = Object.values(os.networkInterfaces()).flat().filter(x=>x.family==='IPv4'&&!x.internal).map(x=>x.address);
const host = process.env.GABINETE_IP || ips.find(x=>x.startsWith('192.168.1.')) || ips[0];
if (!host) throw Error('No hay dirección LAN. Define GABINETE_IP.');
const cert = name => path.join(runtime,'certs',name);
function opens(args) {execFileSync(openssl,args,{stdio:'pipe'});}
opens(['req','-x509','-newkey','rsa:2048','-sha256','-days','365','-nodes','-subj','/CN=Gabinete IoT CA','-keyout',cert('ca.key'),'-out',cert('ca.crt'),'-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign']);
opens(['req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',cert('server.key'),'-out',cert('server.csr')]);
fs.writeFileSync(cert('extensions.cnf'),`subjectAltName=DNS:localhost,DNS:${os.hostname()},IP:127.0.0.1,${ips.map(x=>'IP:'+x).join(',')}\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n`);
opens(['x509','-req','-in',cert('server.csr'),'-CA',cert('ca.crt'),'-CAkey',cert('ca.key'),'-CAcreateserial','-out',cert('server.crt'),'-days','365','-sha256','-extfile',cert('extensions.cnf')]);
opens(['x509','-in',cert('ca.crt'),'-outform','DER','-out',cert('ca.der')]);
const token=()=>crypto.randomBytes(24).toString('base64url');
const passwords={esp32_1:token(),esp32_2:token(),servidor:token()};
const adminPassword=token();
const config={host, mqttPort:8883, httpsPort:1881, brokerExe,
  passwords, adminUser:'admin', adminHash:dep('bcryptjs').hashSync(adminPassword,12), credentialSecret:token()};
fs.writeFileSync(path.join(runtime,'local.json'),JSON.stringify(config,null,2));
fs.writeFileSync(path.join(runtime,'ACCESO-LOCAL.txt'),`Dashboard: https://localhost:1881\nEditor Node-RED: https://localhost:1881/editor\nUsuario: admin\nContraseña inicial: ${adminPassword}\n\nArchivo privado: no compartir ni subir a Git.\n`);
const passwdFile=path.join(runtime,'broker','passwords');
fs.writeFileSync(passwdFile,Object.entries(passwords).map(([u,p])=>u+':'+p).join('\n')+'\n');
execFileSync(path.join(path.dirname(brokerExe),'mosquitto_passwd.exe'),['-U',passwdFile],{stdio:'pipe'});
const prefix='gabinete/';
const rights={
 esp32_1:{write:['acceso/hello','acceso/eventos','acceso/solicitud','acceso/enrollment','estado/esp32_1'],read:['acceso/config','acceso/acuse','acceso/enroll','puerta/respuesta','estado/esp32_2']},
 esp32_2:{write:['puerta/respuesta','inventario/eventos','estado/esp32_2'],read:['acceso/solicitud','inventario/acuse']},
 servidor:{write:['acceso/config','acceso/acuse','acceso/enroll','inventario/acuse'],read:['acceso/hello','acceso/eventos','acceso/enrollment','acceso/solicitud','puerta/respuesta','inventario/eventos','estado/esp32_1','estado/esp32_2']}
};
fs.writeFileSync(path.join(runtime,'broker','acl'),Object.entries(rights).map(([u,r])=>'user '+u+'\n'+Object.entries(r).flatMap(([op,ts])=>ts.map(t=>'topic '+op+' '+prefix+t)).join('\n')).join('\n\n')+'\n');
const slash=p=>p.replace(/\\/g,'/');
fs.writeFileSync(path.join(runtime,'broker','mosquitto.conf'),`listener 8883 0.0.0.0\nallow_anonymous false\npassword_file ${slash(passwdFile)}\nacl_file ${slash(path.join(runtime,'broker','acl'))}\ncertfile ${slash(cert('server.crt'))}\nkeyfile ${slash(cert('server.key'))}\ntls_version tlsv1.2\npersistence true\npersistence_location ${slash(path.join(runtime,'broker'))}/\nmax_packet_size 65536\nlog_type error\nlog_type warning\nlog_type notice\n`);
for (const device of ['esp32_1','esp32_2']) {
 const dir=path.join(runtime,'provision',device);
 fs.writeFileSync(path.join(dir,'config.json'),JSON.stringify({device_id:device,ssid:'',wifi_password:'',mqtt_host:host,mqtt_port:8883,mqtt_user:device,mqtt_password:passwords[device],ntp_host:'pool.ntp.org'},null,2));
 fs.copyFileSync(cert('ca.der'),path.join(dir,'ca.der'));
}
console.log('Configuración privada creada en runtime. IP LAN: '+host);
console.log('Credenciales administrativas: runtime/ACCESO-LOCAL.txt (no se imprimen).');

fs.mkdirSync(path.join(root,'ESP32_1'),{recursive:true});
fs.copyFileSync(cert('ca.der'),path.join(root,'ESP32_1','ca.der'));
fs.writeFileSync(path.join(runtime,'ACCESO-MQTT.txt'), 'Datos privados MQTTS. No publicar.\nServidor: '+host+'\nPuerto: 8883\nUsuario ESP32 1: esp32_1\nContraseña ESP32 1: '+passwords.esp32_1+'\nUsuario ESP32 2: esp32_2\nContraseña ESP32 2: '+passwords.esp32_2+'\n');
