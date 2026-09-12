"""Exercise first release, reuse, repair, stale cleanup and concurrent launch."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


def main():
    source=Path(sys.argv[1]).resolve()
    results=[]
    with tempfile.TemporaryDirectory(prefix='qingyun cache ') as temp:
        folder=Path(temp)
        executable=folder/'Qingyun Clicker.exe'
        shutil.copy2(source,executable)
        cache=folder/'runtime'
        env={k:v for k,v in os.environ.items() if not k.startswith(('QT_','PYTHON'))}
        env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),__COMPAT_LAYER='RunAsInvoker',QINGYUN_TEST_CACHE=str(cache))
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1
        def spawn(name):
            report=folder/(name+'.json');start=time.perf_counter()
            process=subprocess.Popen([str(executable),'--smoke-test',str(report)],cwd=temp,env=env,startupinfo=startup)
            return name,start,process,report
        def finish(item):
            name,start,process,report=item
            try:code=process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                raise
            assert code==0 and report.exists(),(name,code)
            data=json.loads(report.read_text(encoding='utf-8'));assert data['ok']
            result={'case':name,'ready_ms':round((data['ready_perf_counter']-start)*1000,2)}
            results.append(result);print(result,flush=True)
        finish(spawn('first'))
        versions=list(cache.glob('[0-9a-f]'*64));assert len(versions)==1
        version=versions[0];dll=version/'_internal'/'PySide6'/'Qt6Core.dll'
        initial=dll.stat().st_mtime_ns;digest=hashlib.sha256(dll.read_bytes()).digest()
        for i in range(5):finish(spawn('warm-'+str(i)))
        assert dll.stat().st_mtime_ns==initial,'Warm launches unexpectedly extracted the runtime'
        dll.unlink();finish(spawn('missing-file-repair'));assert hashlib.sha256(dll.read_bytes()).digest()==digest
        with dll.open('r+b') as stream:stream.seek(4096);byte=stream.read(1);stream.seek(4096);stream.write(bytes([byte[0]^1]))
        finish(spawn('same-size-corruption-repair'));assert hashlib.sha256(dll.read_bytes()).digest()==digest
        (version/'unexpected.dll').write_bytes(b'not a real DLL')
        finish(spawn('unexpected-file-repair'));assert not (version/'unexpected.dll').exists()
        old=cache/('0'*64);old.mkdir();(old/'.managed').write_text('QingyunClicker managed runtime v1');(old/'old.bin').write_bytes(b'old')
        finish(spawn('old-version-cleanup'));assert not old.exists()
        other=cache/'leave-user-files';other.mkdir();(other/'note.txt').write_text('untouched')
        # Simulate an older running version's lifetime lease using Windows sharing modes.
        old.mkdir();(old/'.managed').write_text('QingyunClicker managed runtime v1');(old/'.inuse').touch()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.CreateFileW(str(old/'.inuse'),0x80000000,1,None,3,0,None)
        assert handle not in (None,ctypes.c_void_p(-1).value)
        try:finish(spawn('active-version-preserved'));assert old.exists()
        finally:kernel.CloseHandle(handle)
        # Force a fresh extraction in an isolated test cache, then launch twice simultaneously.
        shutil.rmtree(version)
        launches=[spawn('concurrent-1'),spawn('concurrent-2')]
        for item in launches:finish(item)
        assert len(list(cache.glob('[0-9a-f]'*64)))==1
        assert (other/'note.txt').read_text()=='untouched'
        assert not list(cache.glob('*.tmp.*'))
        data={'cases':results,'warm_median_ms':statistics.median(r['ready_ms'] for r in results if r['case'].startswith('warm-')),
              'runtime_bytes':sum(p.stat().st_size for p in version.rglob('*') if p.is_file()),'exe_bytes':source.stat().st_size}
        source.with_suffix('.cache-test.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
        print('CACHE TESTS PASSED',data['warm_median_ms'],flush=True)

if __name__=='__main__':main()
