"""Embed a versioned, hashed runtime in a single Windows launcher executable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
from app_version import APP_NAME, APP_VERSION, EXE_NAME, WINDOWS_VERSION

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
launcher_source = (ROOT/'CacheLauncher.cs').read_text(encoding='utf-8').replace('@VERSION_ID@',version)
metadata = (
    f'[assembly: AssemblyTitle("{APP_NAME}")]\n'
    f'[assembly: AssemblyProduct("{APP_NAME}")]\n'
    f'[assembly: AssemblyVersion("{WINDOWS_VERSION}")]\n'
    f'[assembly: AssemblyFileVersion("{WINDOWS_VERSION}")]\n'
    f'[assembly: AssemblyInformationalVersion("{APP_VERSION}")]\n'
)
launcher_source = launcher_source.replace('class CacheLauncher {', metadata + '\nclass CacheLauncher {', 1)
(build/'CacheLauncher.cs').write_text(launcher_source,encoding='utf-8')
csc=Path(os.environ['SystemRoot'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
output=ROOT/'dist'/EXE_NAME
subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+',
                '/r:System.IO.Compression.dll','/r:System.Windows.Forms.dll',
                f'/win32manifest:{ROOT / "launcher.manifest"}',f'/win32icon:{ROOT / "app.ico"}',
                f'/resource:{build / "payload.zip"},payload',f'/resource:{build / "manifest.txt"},manifest',
                f'/out:{output}',str(build/'CacheLauncher.cs')],check=True)
print(json.dumps({'runtime_id':version,'files':len(files),'runtime_bytes':sum(p.stat().st_size for p in files),'exe_bytes':output.stat().st_size}))
