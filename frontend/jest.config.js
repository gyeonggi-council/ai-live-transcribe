const nextJest = require('next/jest');

const createJestConfig = nextJest({
  dir: './',
});

/** @type {import('jest').Config} */
const config = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testEnvironment: 'jsdom',
  testPathIgnorePatterns: ['<rootDir>/e2e/', '<rootDir>/node_modules/'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  collectCoverageFrom: [
    'src/components/**/*.{ts,tsx}',
    'src/hooks/**/*.{ts,tsx}',
    'src/lib/**/*.{ts,tsx}',
    '!src/components/**/*.test.{ts,tsx}',
    '!src/components/**/__tests__/**',
    '!src/components/**/index.{ts,tsx}',
    '!src/hooks/**/*.test.{ts,tsx}',
    '!src/hooks/**/__tests__/**',
    '!src/lib/**/*.test.{ts,tsx}',
    '!src/lib/**/__tests__/**',
    '!src/lib/.gitkeep',
    '!src/hooks/.gitkeep',
    '!src/hooks/**/index.{ts,tsx}',
    '!src/lib/**/index.{ts,tsx}',
    '!src/lib/supabase.ts',
  ],
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80,
    },
  },
};

module.exports = createJestConfig(config);
