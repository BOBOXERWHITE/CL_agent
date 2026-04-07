FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_API_TOKEN=

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_API_TOKEN=${VITE_API_TOKEN}

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
