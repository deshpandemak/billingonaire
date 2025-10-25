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
    // CI optimizations
    pool: process.env.CI ? 'threads' : 'forks',
    poolOptions: {
      threads: {
        minThreads: 1,
        maxThreads: process.env.CI ? 2 : undefined,
      }
    },
    // Reduce startup time in CI
    deps: {
      optimizer: {
        web: {
          include: ['vitest > @vitest/utils > pretty-format'],
        },
      },
    },
    coverage: {
      provider: 'v8',
      reporter: process.env.CI ? ['text', 'json'] : ['text', 'json', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/setupTests.js',
        'dist/',
        '.eslintrc.cjs',
        'vite.config.js'
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
