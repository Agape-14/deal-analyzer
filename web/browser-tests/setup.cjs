const { request } = require('@playwright/test');
const fs = require('node:fs/promises');

module.exports = async () => {
  await fs.mkdir('.browser-auth', { recursive: true });
  for (const [role, password] of [['admin', 'synthetic-browser-password'], ['viewer', 'synthetic-viewer-password']]) {
    const client = await request.newContext({ baseURL: 'http://127.0.0.1:3000' });
    const response = await client.post('/api/auth/login', { data: { username: `browser-${role}`, password } });
    if (!response.ok()) throw new Error(`Synthetic ${role} login failed: ${response.status()}`);
    await client.storageState({ path: `.browser-auth/${role}.json` });
    await client.dispose();
  }
};
