const { generateKeyPairSync, randomUUID } = require('node:crypto');

const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const key = privateKey.export({ format: 'jwk' });

key.alg = 'RS256';
key.kid = randomUUID();
key.use = 'sig';

process.stdout.write(`${JSON.stringify({ keys: [key] })}\n`);
