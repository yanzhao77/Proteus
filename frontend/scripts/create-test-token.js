import { readFileSync } from 'node:fs';
import { createSign } from 'node:crypto';

const privateKeyPath = process.env.TEST_PRIVATE_KEY_PATH || '/tmp/test_private_key.pem';

function base64url(value) {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

function createTestToken(privateKey) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', kid: 'test-key-1', typ: 'JWT' };
  const payload = {
    sub: 'e13-e2e-user',
    preferred_username: 'e2etest',
    email: 'e2e@test.com',
    roles: ['user'],
    aud: 'test-audience',
    iss: 'https://test-issuer.example.com',
    iat: now - 60,
    exp: now + 3600,
    nbf: now - 60,
  };
  const signingInput = `${base64url(header)}.${base64url(payload)}`;
  const signer = createSign('RSA-SHA256');
  signer.update(signingInput);
  signer.end();
  return `${signingInput}.${signer.sign(privateKey).toString('base64url')}`;
}

const privateKey = readFileSync(privateKeyPath, 'utf8');
console.log(createTestToken(privateKey));
