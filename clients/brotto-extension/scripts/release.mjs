// Build a signed CRX3 + Edge ZIP from the existing `dist/`.
// Run after `npm run build` (or `node build.mjs`).
//
// `update.xml` is intentionally not produced — that lives behind a
// hosting layer (CF Pages / GH Pages / similar). For now, GH Releases
// is the distribution channel; testers re-download to update.
import { readFileSync, writeFileSync, statSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';
import Crx from 'crx';

const __dirname = dirname(fileURLToPath(import.meta.url));
const extDir    = join(__dirname, '..');
const distDir   = join(extDir, 'dist');
const keyPath   = join(extDir, 'crx-signing.pem');
const crxPath   = join(distDir, 'brotto.crx');
const edgePath  = join(distDir, 'brotto-edge.zip');

if (!existsSync(distDir)) {
  console.error(`No ${distDir}/ found. Run \`npm run build\` first.`);
  process.exit(1);
}

let pem;
if (process.env.CRX_PEM)         pem = Buffer.from(process.env.CRX_PEM);
else if (existsSync(keyPath))    pem = readFileSync(keyPath);
else {
  console.error(
    'Missing signing key. Run `openssl genrsa -out clients/brotto-extension/crx-signing.pem 2048` ' +
    'and back it up out-of-band (1Password). Never commit this file.'
  );
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(join(extDir, 'manifest.json'), 'utf8'));
const version  = manifest.version;

const crx = new Crx({ privateKey: pem });
await crx.load(distDir);
const crxBuffer = await crx.pack();
writeFileSync(crxPath, crxBuffer);

// Edge Add-ons wants a plain ZIP of the unpacked dist/ (no CRX/XML/ZIP inside it).
execSync(`zip -r brotto-edge.zip . -x "brotto.crx" "update.xml" "brotto-edge.zip"`,
  { cwd: distDir, stdio: 'inherit' });

console.log('--- Release artifacts ---');
console.log(`version : ${version}`);
console.log(`crx     : ${crxPath}  (${statSync(crxPath).size} bytes)`);
console.log(`edge zip: ${edgePath}`);
