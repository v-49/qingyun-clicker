from pathlib import Path

root = Path(SPECPATH)
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[],
             datas=[(str(root / 'app.ico'), '.')], hiddenimports=[],
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)

# These plugin families are not used by this raster QWidget application.
# Keep Windows platform/IME support, image codecs, and the normal Qt libraries.
def needed(entry):
    name = entry[0].replace('\\', '/').lower()
    return not (name.endswith('opengl32sw.dll') or 'virtualkeyboard' in name
                or '/qt6qml' in name or '/qt6quick' in name
                or name.endswith('/qt6pdf.dll') or name.endswith('/qpdf.dll'))

a.binaries = [entry for entry in a.binaries if needed(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='QingyunRuntime',
          console=False, upx=False, uac_admin=False, icon=[str(root / 'app.ico')])
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='QingyunRuntime')
