import { defineConfig } from '@playwright/test';

// Start the stack first: `make api` and `make web` (or `docker compose up`).
export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  use: { baseURL: process.env.WEB_URL || 'http://localhost:3000', trace: 'retain-on-failure' },
});
