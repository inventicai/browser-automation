import * as esbuild from 'esbuild';
import { copyFileSync, mkdirSync, existsSync, rmSync } from 'fs';
import { execSync } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcDir  = join(__dirname, 'src');
const distDir = join(__dirname, 'dist');

if (existsSync(distDir)) rmSync(distDir, { recursive: true });
mkdirSync(distDir, { recursive: true });

// Static assets
for (const name of ['sidepanel.html', 'sidepanel.js']) {
  copyFileSync(join(srcDir, name), join(distDir, name));
}
copyFileSync(join(__dirname, 'manifest.json'), join(distDir, 'manifest.json'));

// Brand mark PNGs — single source is src/assets/icon.svg; rsvg-convert
// renders the standard Chrome extension sizes (toolbar, install, store).
// ponytail: requires `rsvg-convert` (librsvg) on the build host. Same
// geometry as the inline mark in sidepanel.html — change once, rebuild.
const iconSvg = join(srcDir, 'assets', 'icon.svg');
const iconsDir = join(distDir, 'icons');
mkdirSync(iconsDir, { recursive: true });
for (const size of [16, 32, 48, 128]) {
  execSync(`rsvg-convert -w ${size} -h ${size} ${iconSvg} -o ${join(iconsDir, `icon-${size}.png`)}`);
}

// Bundle background.ts
console.log('Bundling background.ts...');
await esbuild.build({
  entryPoints: [join(srcDir, 'background.ts')],
  bundle:      true,
  outfile:     join(distDir, 'background.js'),
  platform:    'browser',
  target:      'chrome110',
  format:      'iife',
  minify:      false,
  sourcemap:   false,
});

console.log('Build complete!');
