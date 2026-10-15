from pathlib import Path
import json,hashlib,zipfile
root=Path.cwd();component=root/'harness/component'
files=[p for p in sorted(component.rglob('*')) if p.is_file() and not p.name.endswith('.test.mjs') and p.relative_to(component).as_posix()!='studio.patch.yml']
for p in files:
    if p.is_symlink():raise RuntimeError('Runtime payload contains a symlink')
checksums={p.relative_to(component).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.name!='checksums.json'}
(component/'checksums.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
files=[p for p in sorted(component.rglob('*')) if p.is_file() and not p.name.endswith('.test.mjs') and p.relative_to(component).as_posix()!='studio.patch.yml']
target=root/'.runtime/Harness-Component-0.1.0-preview.zip'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for p in files:archive.write(p,p.relative_to(component).as_posix())
size={'files':len(files),'raw_bytes':sum(p.stat().st_size for p in files),'zip_bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
(root/'.runtime/lean-size.json').write_text(json.dumps(size,indent=2),encoding='utf-8')
print(json.dumps(size))
