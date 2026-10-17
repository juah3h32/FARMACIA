// Estilos de la pantalla del POS (app/web/index.html) ya compilados, en vez de que Tailwind los
// calcule mientras el programa corre (eso revisaba toda la pantalla en cada cambio, ~20 ms por segundo).
// Se vuelve a generar al publicar (release.yml) y a mano con:  scripts\estilos\construir.cmd
module.exports = {
  content: ['../../app/web/index.html'],
  theme: { extend: { fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] } } },
};
