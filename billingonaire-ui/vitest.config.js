import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.js',
    include: ['src/__tests__/**/*.{js,jsx,ts,tsx}'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/*.spec.js'],
    clearMocks: true,
    css: false,
    pool: 'forks',
    poolOptions: {
      forks: {
        minForks: 1,
        maxForks: process.env.CI ? 2 : undefined,
      }
    },
    coverage: {
      provider: 'v8',
      reportsDirectory: './coverage',
      reporter: process.env.CI ? ['text', 'json'] : ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/setupTests.js',
        'dist/',
        '.eslintrc.cjs',
        'vite.config.js',
        'playwright.config.js',
        'eslint.config.js',
      ],
      threshold: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  }
});
