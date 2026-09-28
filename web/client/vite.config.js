import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // En développement, le client tourne sur Vite et l'API sur uvicorn :
  // le proxy évite une configuration CORS qui n'existerait qu'ici.
  server: {
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
  build: {
    // Servi tel quel par FastAPI ; aucun CDN, l'app vit derrière Access.
    outDir: 'dist',
    emptyOutDir: true,
  },
  worker: { format: 'es' },
});
