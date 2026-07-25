// Vercel excluye cualquier carpeta llamada "node_modules" del deploy,
// sin importar .vercelignore. El export web de Expo mete las fuentes
// de iconos en dist/assets/node_modules/..., asi que nunca llegaban a
// produccion (los iconos se veian como cuadros). Renombra esa carpeta
// y parcha las rutas ya hasheadas dentro del bundle JS exportado.
const fs = require('fs');
const path = require('path');

const DIST = path.join(__dirname, '..', 'dist');
const OLD_DIR = path.join(DIST, 'assets', 'node_modules');
const NEW_DIR = path.join(DIST, 'assets', 'expo-icon-fonts');
const OLD_REF = 'assets/node_modules/';
const NEW_REF = 'assets/expo-icon-fonts/';

if (!fs.existsSync(OLD_DIR)) {
  console.log('[fix-vendor-fonts] nada que renombrar, listo');
  process.exit(0);
}

fs.renameSync(OLD_DIR, NEW_DIR);

const jsDir = path.join(DIST, '_expo', 'static', 'js', 'web');
const files = fs.existsSync(jsDir) ? fs.readdirSync(jsDir).filter(f => f.endsWith('.js')) : [];
let totalReplaced = 0;
for (const file of files) {
  const filePath = path.join(jsDir, file);
  const original = fs.readFileSync(filePath, 'utf8');
  const count = original.split(OLD_REF).length - 1;
  if (count > 0) {
    fs.writeFileSync(filePath, original.split(OLD_REF).join(NEW_REF));
    totalReplaced += count;
  }
}

console.log(`[fix-vendor-fonts] carpeta renombrada, ${totalReplaced} referencias parchadas en ${files.length} archivo(s)`);
