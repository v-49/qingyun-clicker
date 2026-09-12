"""Embed a versioned, hashed runtime in a single Windows launcher executable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parent
runtime=ROOT/'dist'/'QingyunRuntime'
build=ROOT/'build'/'cached-launcher'
build.mkdir(parents=True,exist_ok=True)
files=sorted(p for p in runtime.rglob('*') if p.is_file())
manifest='\n'.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}|{p.stat().st_size}|{p.relative_to(runtime).as_posix()}' for p in files)+'\n'
version=hashlib.sha256(manifest.encode()).hexdigest()
(build/'manifest.txt').write_text(manifest,encoding='utf-8')
with zipfile.ZipFile(build/'payload.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for p in files: archive.write(p,p.relative_to(runtime).as_posix())
(build/'CacheLauncher.cs').write_text((ROOT/'CacheLauncher.cs').read_text(encoding='utf-8').replace('@VERSION_ID@',version),encoding='utf-8')
csc=Path(os.environ['SystemRoot'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
output=ROOT/'dist'/'轻云连点器.exe'
subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+',
                '/r:System.IO.Compression.dll','/r:System.Windows.Forms.dll',
                f'/win32manifest:{ROOT / "launcher.manifest"}',f'/win32icon:{ROOT / "app.ico"}',
                f'/resource:{build / "payload.zip"},payload',f'/resource:{build / "manifest.txt"},manifest',
                f'/out:{output}',str(build/'CacheLauncher.cs')],check=True)
print(json.dumps({'runtime_id':version,'files':len(files),'runtime_bytes':sum(p.stat().st_size for p in files),'exe_bytes':output.stat().st_size}))
