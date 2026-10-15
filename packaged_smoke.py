"""Launch the standalone EXE with clean PATH and isolated settings before shipping."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from app_version import APP_VERSION
from models import DEFAULT_PRESS_MS


def main():
    source = Path(sys.argv[1]).resolve()
    report = source.with_suffix('.smoke.json')
    report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='clicker_standalone_') as directory:
        executable = Path(directory) / 'QingyunClicker.exe'
        shutil.copy2(source, executable)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('PYTHON', 'QT_'))}
        env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        env['__COMPAT_LAYER'] = 'RunAsInvoker'
        env['QINGYUN_TEST_CACHE'] = str(Path(directory) / 'cache')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(executable), '--smoke-test', str(report)], cwd=directory, env=env, startupinfo=startup)
        try:
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            raise RuntimeError('Packaged EXE did not start and exit within 30 seconds')
        if code != 0 or not report.exists():
            raise RuntimeError(f'Packaged EXE failed: exit code {code}')
        result = json.loads(report.read_text(encoding='utf-8'))
        assert result['ok'] and result['frozen'] and result['platform'] == 'windows', result
        assert result['version'] == APP_VERSION and result['default_press_ms'] == DEFAULT_PRESS_MS, result
        assert result['mixed_rules_checked'], result
        assert result['recording_delay_checked'], result
        assert result['recording_tail_checked'], result
        assert result['countdown_labels'] == ['3s', '2s', '1s', '停止录制'], result
        print('Standalone EXE startup verified:', json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
