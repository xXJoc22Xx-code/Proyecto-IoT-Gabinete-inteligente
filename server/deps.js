// Reutiliza instalaciones existentes; npm install ofrece una copia local portable.
const path = require('node:path');
module.exports = name => require(require.resolve(name, {paths: [
  path.join(__dirname, '..'),
  path.join(process.env.APPDATA || '', 'npm/node_modules/node-red')
]}));
