module.exports = {
  projects: [
    { displayName: 'unit', testMatch: ['<rootDir>/src/**/*.test.js'] },
    { displayName: 'slow', testMatch: ['<rootDir>/e2e/**/*.test.js'] },
  ],
}
