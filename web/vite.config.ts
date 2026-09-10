import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// dev 模式:前端 5173 端口,代理 /api -> 后端 FastAPI(8001)。
// 生产:FastAPI 直接托管 web/dist 构建产物,不走代理(单服务,D8 决策)。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
});
