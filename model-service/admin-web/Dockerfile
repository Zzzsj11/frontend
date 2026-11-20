ARG NODE_IMAGE=node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
ARG NGINX_IMAGE=nginx:1.30-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3
FROM ${NODE_IMAGE} AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM ${NGINX_IMAGE}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
