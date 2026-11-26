const crypto = require('node:crypto');
const {promisify} = require('node:util');
const derive = promisify(crypto.pbkdf2);
const same = (a,b) => {
 const x=Buffer.from(String(a||'')), y=Buffer.from(String(b||''));
 return x.length===y.length && crypto.timingSafeEqual(x,y);
};
module.exports = function deviceAuth(service, deviceSecret) {
 let failures=0, until=0, busy=false;
 return async function(req,res) {
  res.set('Cache-Control','no-store');
  if(!same(req.headers['x-device-key'],deviceSecret))return res.status(401).json({error:'device_unauthorized'});
  const b=req.body||{};
  if(!/^[a-f0-9]{32}$/.test(b.request_id||'') || typeof b.user_id!=='string' || b.user_id.length>6 || typeof b.password!=='string' || b.password.length>12)
   return res.status(400).json({error:'invalid_request'});
  const reply=(result,extra={})=>res.json({request_id:b.request_id,result,revision:service.revision(),...extra});
  if(Date.now()<until)return reply('blocked',{retry_after:Math.ceil((until-Date.now())/1000)});
  if(busy)return res.status(503).json({error:'busy'});
  busy=true;
  try {
   const revision=service.revision();
   const user=service.db.prepare('SELECT * FROM users WHERE id=?').get(b.user_id);
   const candidate=await derive(b.password,Buffer.from(user?user.salt:'00'.repeat(16),'hex'),20000,32,'sha256');
   const valid=!!user && !!user.active && /^[0-9A-D]{6,12}$/.test(b.password) && crypto.timingSafeEqual(candidate,Buffer.from(user.hash,'hex'));
   if(revision!==service.revision())return reply('retry');
   if(valid){failures=0;until=0;return reply('authorized');}
   failures++;
   if(failures>=5){failures=0;until=Date.now()+30000;}
   return reply('denied');
  }catch{return res.status(503).json({error:'unavailable'});}
  finally{busy=false;}
 };
};
