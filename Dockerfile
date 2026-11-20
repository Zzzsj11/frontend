ARG NODE_BASE_IMAGE=node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
ARG NGINX_BASE_IMAGE=nginx:1.30-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3
FROM ${NODE_BASE_IMAGE} AS build

WORKDIR /app
ARG RELEASE_VERSION=development
ENV VITE_RELEASE_VERSION=${RELEASE_VERSION}
COPY package.json package-lock.json ./
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "$NPM_REGISTRY" \
    && npm config set replace-registry-host always \
    && npm ci --fetch-retries=3 --fetch-timeout=120000
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build

FROM ${NGINX_BASE_IMAGE}
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD wget -qO- http://127.0.0.1/healthz || exit 1
