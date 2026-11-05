"""Launch, diagnose, or render Ultron without changing application settings."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def doctor():
    print(f'Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
    missing = []
    for name in ('PyQt6', 'sounddevice', 'numpy', 'google-genai', 'requests', 'pillow', 'psutil'):
        try:
            print(f'{name}: {importlib.metadata.version(name)}')
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    print('Provider configuration:', 'present' if (ROOT/'config/api_keys.json').exists() else 'not configured (setup screen will open)')
    print('Graphical display:', 'available' if sys.platform != 'linux' or os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') else 'not available; use --preview')
    if missing:
        print('Missing packages:', ', '.join(missing))
        print('Install them with: python -m pip install -r requirements.txt')
        return 1
    return subprocess.run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description='Ultron desktop assistant')
    parser.add_argument('--doctor', action='store_true', help='Check dependencies without starting the assistant')
    parser.add_argument('--preview', action='store_true', help='Render a screenshot without any provider session or desktop actions')
    parser.add_argument('--workspace', action='store_true', help='Hide setup in a preview to inspect the workspace')
    parser.add_argument('--output', type=Path, default=ROOT/'screenshots/ultron-preview.png')
    parser.add_argument('--size', default='1280x820', help='Preview window size, for example 1100x720')
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    if sys.version_info < (3, 11):
        parser.error('Use Python 3.11 or newer. Python 3.12 is recommended.')
    if args.doctor:
        return doctor()
    if sys.platform == 'linux' and not Path('/usr/share/pipewire/client.conf').exists():
        os.environ.setdefault('QT_AUDIO_BACKEND', 'pulseaudio')
    if args.preview:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        try:
            width, height = (int(number) for number in args.size.lower().split('x'))
            if width < 1100 or height < 720 or width > 3840 or height > 2160:
                raise ValueError
        except ValueError:
            parser.error('Preview size must be between 1100x720 and 3840x2160.')
        from PyQt6.QtCore import QTimer
        from ui import JarvisUI
        app = JarvisUI('ultron_avatar.png')
        app._win.resize(width, height)
        if args.workspace:
            app._win._dismiss_connection_setup()
        result = {'ok': False}
        def capture():
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                image = app._win.grab()
                result['ok'] = not image.isNull() and image.save(str(args.output))
                if result['ok']:
                    print('Preview saved:', args.output.resolve())
            finally:
                app._app.quit()
        QTimer.singleShot(1200, capture)
        QTimer.singleShot(15000, app._app.quit)
        app.root.mainloop()
        return 0 if result['ok'] else 1
    if sys.platform == 'linux' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') or os.environ.get('QT_QPA_PLATFORM')):
        print('No graphical display is connected. Use python run.py --preview, or run on your desktop.')
        return 2
    try:
        from main import main as start
        start()
    except ImportError as error:
        print(f'A required dependency could not be loaded: {error.name}')
        print('Run python -m pip install -r requirements.txt, then python run.py --doctor.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
