// Contrato MQTT FSR402: tres canales en orden GPIO34, GPIO35, GPIO32.
const rawOK=value=>Array.isArray(value)&&value.length===3&&value.every(x=>Number.isInteger(x)&&x>=0&&x<=4095);
const presenceOK=value=>Array.isArray(value)&&value.length===3&&value.every(x=>['present','absent','unknown'].includes(x));
const pressureKeys=['pressure_raw','sensor_presence','pressure_calibrated','pressure_stable','before_raw','after_raw','before_presence','after_presence'];
function pressureData(p){
 if(p.kind!=='lectura_presion'&&!pressureKeys.some(k=>Object.hasOwn(p,k)))return {};
 if(!rawOK(p.pressure_raw)||!presenceOK(p.sensor_presence)||typeof p.pressure_calibrated!=='boolean'||typeof p.pressure_stable!=='boolean')throw Error('Lectura FSR402 inválida.');
 if((!p.pressure_calibrated||!p.pressure_stable)&&p.sensor_presence.some(x=>x!=='unknown'))throw Error('Presencia sin calibración o estabilidad.');
 const presence=p.sensor_presence.includes('present')?'present':p.sensor_presence.includes('unknown')?'unknown':'absent';
 if(p.presence!==presence)throw Error('Presencia FSR402 inconsistente.');
 const data={pressure_raw:[...p.pressure_raw],sensor_presence:[...p.sensor_presence],pressure_calibrated:p.pressure_calibrated,pressure_stable:p.pressure_stable,presence};
 if(['before_raw','after_raw','before_presence','after_presence'].some(k=>Object.hasOwn(p,k))){
  if(!rawOK(p.before_raw)||!rawOK(p.after_raw)||!presenceOK(p.before_presence)||!presenceOK(p.after_presence)
    ||!p.pressure_calibrated||!p.pressure_stable||p.before_presence.includes('unknown')||p.after_presence.includes('unknown')
    ||p.after_raw.some((x,i)=>x!==p.pressure_raw[i])||p.after_presence.some((x,i)=>x!==p.sensor_presence[i]))throw Error('Comparación FSR402 inválida.');
  for(const key of ['before_raw','after_raw','before_presence','after_presence'])data[key]=[...p[key]];
 }
 return data;
}
module.exports={pressureData};
