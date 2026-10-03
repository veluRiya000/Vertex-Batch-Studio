import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { Resvg } from '@resvg/resvg-js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const svg = readFileSync(resolve(root, 'src/assets/logo.svg'), 'utf8');
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const images = sizes.map(size => new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng());
const header = Buffer.alloc(6 + sizes.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(sizes.length, 4);
let offset = header.length;
sizes.forEach((size, index) => {
  const entry = 6 + index * 16;
  header[entry] = header[entry + 1] = size === 256 ? 0 : size;
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(images[index].length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += images[index].length;
});
mkdirSync(resolve(root, 'src-tauri/icons'), { recursive: true });
writeFileSync(resolve(root, 'src-tauri/icons/icon.ico'), Buffer.concat([header, ...images]));
writeFileSync(resolve(root, 'src-tauri/icons/icon.png'), images.at(-1));
mkdirSync(resolve(root, 'public'), { recursive: true });
writeFileSync(resolve(root, 'public/icon.svg'), svg);
console.log('Generated desktop, installer and browser icons from logo.svg');
