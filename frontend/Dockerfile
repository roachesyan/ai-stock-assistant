# 前端构建 + nginx 提供静态文件并反代 /api
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# 生产构建时 API 走同源 /api（由 nginx 反代到后端）
RUN echo "VITE_API_BASE_URL=/api" > .env.production && npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
