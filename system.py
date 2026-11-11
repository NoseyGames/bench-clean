"""Windows inventory and operations. No shell evaluation of registry commands."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import psutil

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
OPTIONAL = {
    'Microsoft.BingNews', 'Microsoft.BingWeather', 'Microsoft.GetHelp',
    'Microsoft.Getstarted', 'Microsoft.MicrosoftSolitaireCollection',
    'Microsoft.People', 'Microsoft.WindowsFeedbackHub', 'Microsoft.YourPhone',
    'Microsoft.ZuneMusic', 'Microsoft.ZuneVideo', 'Clipchamp.Clipchamp',
    'Microsoft.MicrosoftOfficeHub', 'Microsoft.Todos', 'Microsoft.PowerAutomateDesktop',
    'Microsoft.WindowsMaps', 'Microsoft.SkypeApp',
}
# Never offer infrastructure packages, even when Windows labels them removable.
PROTECTED = ('Microsoft.WindowsStore', 'Microsoft.StorePurchaseApp', 'Microsoft.DesktopAppInstaller',
             'Microsoft.SecHealthUI', 'Microsoft.Windows.', 'Microsoft.AAD.', 'Microsoft.AccountsControl',
             'Microsoft.LockApp', 'Microsoft.Win32WebViewHost', 'Microsoft.CredDialogHost',
             'Microsoft.XboxIdentityProvider', 'Microsoft.GamingServices', 'Microsoft.VCLibs',
             'Microsoft.NET.', 'Microsoft.UI.', 'Microsoft.WindowsAppRuntime')


def powershell(script, env=None, timeout=90):
    exe = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'scripts' / script)],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
                            env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:2000] or 'Windows command failed.')
    return result.stdout.strip()


def as_list(value):
    return value if isinstance(value, list) else ([value] if value else [])


def app_id(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def desktop_apps():
    import winreg
    result = []
    base = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive, scope in ((winreg.HKEY_CURRENT_USER, 'user'), (winreg.HKEY_LOCAL_MACHINE, 'machine')):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                parent = winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        key_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, key_name) as key:
                            def get(name, default=''):
                                try:
                                    return winreg.QueryValueEx(key, name)[0]
                                except OSError:
                                    return default
                            name = get('DisplayName')
                            if not name or get('SystemComponent', 0) or get('ParentKeyName'):
                                continue
                            command = get('UninstallString')
                            result.append(dict(id=app_id(f'{scope}:{view}:{key_name}'), name=name,
                                               kind='desktop', location=get('InstallLocation'),
                                               publisher=get('Publisher'), size=int(get('EstimatedSize', 0)) * 1024,
                                               removable=bool(command), optional=False, scope=scope,
                                               _command=command, _key=key_name))
                    except (OSError, ValueError, TypeError):
                        continue
    return result


def inventory():
    apps = desktop_apps()
    warnings = []
    try:
        for p in as_list(json.loads(powershell('apps.ps1') or '[]')):
            name = p['name']
            apps.append(dict(id=app_id(p['package']), name=name, kind='store', location=p['location'],
                             publisher=p['publisher'], size=None, optional=name in OPTIONAL,
                             removable=not p['protected'] and not name.startswith(PROTECTED),
                             scope='user', _package=p['package']))
    except Exception as exc:
        warnings.append('Store app inventory failed: ' + str(exc))
    return sorted(apps, key=lambda a: a['name'].lower()), warnings


def gpu_sample():
    values = as_list(json.loads(powershell('gpu.ps1', timeout=20) or '[]'))
    if not values:
        raise RuntimeError('No GPU engine counters are available.')
    result = {}
    for value in values:
        match = re.match(r'pid_(\d+)_', value['Name'])
        if match:
            pid = int(match[1])
            result[pid] = max(result.get(pid, 0), min(100, float(value['UtilizationPercentage'])))
    return result


def match_app(executable, apps):
    if not executable:
        return None
    executable = os.path.normcase(os.path.abspath(executable))
    matches = []
    for app in apps:
        location = app.get('location')
        if not location or not os.path.isabs(location):
            continue
        location = os.path.normcase(os.path.abspath(location)).rstrip('\\/')
        # Broad roots cannot reliably identify a product.
        if len(Path(location).parts) < 3 or location.lower() in {
            os.environ.get('ProgramFiles', '').lower(), os.environ.get('SystemRoot', '').lower(),
            os.environ.get('ProgramFiles(x86)', '').lower()}:
            continue
        if executable.startswith(location + os.sep):
            matches.append((len(location), app['id']))
    matches.sort(reverse=True)
    if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0]):
        return None
    return matches[0][1]


def split_windows(command):
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    argc = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv:
        raise ValueError('Invalid uninstall command.')
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def uninstall_command(app):
    args = split_windows(os.path.expandvars(app['_command']))
    if not args:
        raise ValueError('No registered uninstaller.')
    if Path(args[0]).name.lower() in ('msiexec', 'msiexec.exe'):
        guid = next((m.group(0) for arg in args[1:] if (m := re.search(
            r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', arg))), None)
        if not guid:
            raise ValueError('No MSI product identifier. Use Windows Installed apps.')
        return str(Path(os.environ['SystemRoot']) / 'System32/msiexec.exe'), ['/x', guid]
    executable = Path(args[0])
    if not executable.is_absolute() or executable.suffix.lower() != '.exe' or not executable.is_file():
        raise ValueError('Uninstaller path is ambiguous or missing. Use Windows Installed apps.')
    if executable.name.lower() in {'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wscript.exe',
                                   'cscript.exe', 'rundll32.exe', 'regsvr32.exe', 'mshta.exe'}:
        raise ValueError('Script-based uninstaller: use Windows Installed apps.')
    return str(executable), args[1:]


def remove_app(app):
    if not app['removable']:
        raise ValueError('This app is protected or has no uninstaller.')
    if app['kind'] == 'store':
        env = dict(os.environ, BENCH_PACKAGE=app['_package'])
        powershell('remove.ps1', env=env, timeout=300)
        return 'Removed for the current Windows user.'
    executable, args = uninstall_command(app)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                   ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    result = shell.ShellExecuteW(None, 'open', executable, subprocess.list2cmdline(args), None, 1)
    if not result or result <= 32:
        raise RuntimeError(f'Windows could not launch the uninstaller ({result}). Use Windows Installed apps.')
    return 'Uninstaller opened. Complete its prompts, then refresh apps to verify removal.'


def drives():
    result = []
    for p in psutil.disk_partitions():
        if 'cdrom' in p.opts or not p.fstype:
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
            result.append(dict(path=p.mountpoint, total=usage.total, used=usage.used, free=usage.free))
        except OSError:
            pass
    return result
