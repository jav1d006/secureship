FROM node:25-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:25-alpine
WORKDIR /app

ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0

# Runtime image-dən istifadə olunmayan npm alətlərini sil
RUN rm -rf /usr/local/lib/node_modules/npm \
    /usr/local/bin/npm \
    /usr/local/bin/npx

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

USER 10001
EXPOSE 3000
CMD ["node", "server.js"]
