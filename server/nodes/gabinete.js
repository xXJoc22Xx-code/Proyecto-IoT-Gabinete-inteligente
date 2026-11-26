module.exports=function(RED){
 RED.nodes.registerType('gabinete-source',function(config){
  RED.nodes.createNode(this,config);
  const service=this.context().global.get('gabinete');
  const incoming=msg=>this.send(msg);
  service.on('incoming',incoming);
  this.on('close',()=>service.off('incoming',incoming));
 });
};
