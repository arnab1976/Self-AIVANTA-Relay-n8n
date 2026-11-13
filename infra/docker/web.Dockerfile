FROM node:20-alpine AS build
WORKDIR /repo
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_N8N_EDITOR_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_N8N_EDITOR_URL=$NEXT_PUBLIC_N8N_EDITOR_URL NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json* ./
COPY apps/web/package.json apps/web/
COPY packages/graph-schema packages/graph-schema
RUN npm install --no-audit --no-fund
COPY apps/web apps/web
RUN npm run build -w @aivanta/web

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 aivanta
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
USER aivanta
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
