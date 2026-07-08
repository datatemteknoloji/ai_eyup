# Stage 1: Build
# --platform=$BUILDPLATFORM: bu adım sadece platform-bağımsız statik dosyalar
# (JS/CSS/HTML) üretir, hedef mimariye (ör. amd64) ihtiyaç duymaz. Native build
# platformunda (ör. arm64 geliştirme makinesi) çalıştırmak, esbuild'in Go
# runtime'ının QEMU emülasyonu altında zaman zaman çökmesini (lfstack.push
# hatası) önler ve cross-build'i hem hızlandırır hem güvenilir hale getirir.
FROM --platform=$BUILDPLATFORM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev || npm install

COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN chown -R nginx:nginx /usr/share/nginx/html
# nginx master process binds to port 80 (requires root); workers run as nginx user
# via nginx.conf — this is nginx's standard security model.

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
