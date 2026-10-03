import { copyFileSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'

const version = JSON.parse(readFileSync('package.json', 'utf8')).version
const target = resolve(process.env.CARGO_TARGET_DIR || 'src-tauri/target')
const source = resolve(target, 'release/bundle/nsis')
const files = readdirSync(source).filter(name => name.endsWith('.exe') && name.includes(version) && name.includes('x64'))
if (files.length !== 1) throw new Error('Expected exactly one x64 installer for this version')
const output = resolve('../release')
mkdirSync(output, { recursive: true })
const name = `VertexBatchStudio-Setup-${version}-x64.exe`
copyFileSync(resolve(source, files[0]), resolve(output, name))
const checksum = createHash('sha256').update(readFileSync(resolve(output, name))).digest('hex')
writeFileSync(resolve(output, 'SHA256SUMS.txt'), `${checksum}  ${name}\n`)
console.log(`Installer: ${resolve(output, name)}`)
