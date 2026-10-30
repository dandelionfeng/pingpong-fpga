"""RK J3 console with Windows VT output and a matching remote terminal size."""
from pathlib import Path
import argparse
import codecs
import ctypes
from datetime import datetime
import json
import msvcrt
import os
import re
import shutil
import sys
import threading
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'tools/python'))
import serial
from serial.tools import list_ports

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
SHELL_PROMPT = re.compile(r'(?:^|[\r\n])(?:root|linaro)@[^\r\n]*[#$] $')
EXTENDED_KEYS = {
    b'H': b'\x1b[A', b'P': b'\x1b[B', b'K': b'\x1b[D', b'M': b'\x1b[C',
    b'G': b'\x1b[H', b'O': b'\x1b[F', b'S': b'\x1b[3~',
}


class DriverProgressFilter:
    """Hide only the known DMA progress chatter; raw bytes still go to the log."""
    progress = re.compile(r'^\[\s*\d+\.\d+\]\s+(?:codex partial completion\b[^\r\n]*|engine_service_final_transfer: \d+ callbacks suppressed)\r?\n$')

    def __init__(self):
        self.pending = None
        self.hidden_lines = 0

    def feed(self, text):
        output = []
        for char in text:
            if self.pending is not None:
                self.pending += char
                if char == '\n' or len(self.pending) > 512:
                    if self.progress.fullmatch(self.pending):
                        self.hidden_lines += 1
                    else:
                        output.append(self.pending)
                    self.pending = None
                elif ']' not in self.pending:
                    if not re.fullmatch(r'\[[\d .]*', self.pending):
                        output.append(self.pending)
                        self.pending = None
                else:
                    stamp, body = self.pending.split(']', 1)
                    prefixes = ('codex partial completion ', 'engine_service_final_transfer: ')
                    body = body.lstrip()
                    if (not re.fullmatch(r'\[\s*\d+\.\d+', stamp)
                            or not any(p.startswith(body) or body.startswith(p) for p in prefixes)):
                        output.append(self.pending)
                        self.pending = None
            elif char == '[':
                self.pending = char
            else:
                output.append(char)
        return ''.join(output)


def terminal_size():
    size = shutil.get_terminal_size((120, 30))
    return max(20, size.columns), max(5, size.lines)


def configure_console():
    """Use VT output and raw input so Ctrl+C goes to RK, not the parent CMD."""
    if os.name != 'nt' or not sys.stdout.isatty():
        return lambda: None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = kernel.GetStdHandle(-11 & 0xffffffff)
    input_handle = kernel.GetStdHandle(-10 & 0xffffffff)
    mode = wintypes.DWORD()
    saved = []
    if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        previous = mode.value
        if kernel.SetConsoleMode(handle, previous | 0x0004):
            saved.append((handle, previous))
    if kernel.GetConsoleMode(input_handle, ctypes.byref(mode)):
        previous = mode.value
        # Disable processed/line/echo/mouse/QuickEdit input; preserve other flags.
        if kernel.SetConsoleMode(input_handle, (previous | 0x0080) & ~0x0057):
            saved.append((input_handle, previous))
    def restore():
        for target, previous in reversed(saved):
            kernel.SetConsoleMode(target, previous)
    return restore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port')
    args = parser.parse_args()
    ports = [x for x in list_ports.comports() if x.vid == 0x1a86]
    for port in ports:
        print(port.device, port.description)
    port = args.port or (ports[0].device if len(ports) == 1 else input('RK J3 COM port (for example COM8): ').strip())
    restore_console = configure_console()
    folder = BASE / 'results/terminal'
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f_') + port + '.log')
    stop = threading.Event()
    prompt_ready = threading.Event()
    errors = []
    sizes = []
    progress_filter = DriverProgressFilter()
    try:
        channel = serial.Serial(port=None, baudrate=1500000, timeout=.1, rtscts=False, dsrdtr=False)
        # Set line-control levels before opening so connecting does not pulse reset.
        channel.dtr = False
        channel.rts = False
        channel.port = port
        with channel, log_path.open('wb') as log:
            print('RK SERIAL: 1500000 / 8N1. Ctrl+] returns to PC menu; Ctrl+C interrupts RK.')
            print('Session log:', log_path.name, flush=True)

            def reader():
                decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
                tail = ''
                try:
                    while not stop.is_set():
                        data = channel.read(max(1, channel.in_waiting))
                        if not data:
                            continue
                        log.write(data)
                        log.flush()
                        text = decoder.decode(data)
                        sys.stdout.write(progress_filter.feed(text))
                        sys.stdout.flush()
                        tail = (tail + text)[-2048:]
                        if SHELL_PROMPT.search(ANSI.sub('', tail)):
                            prompt_ready.set()
                except Exception as exc:
                    errors.append(str(exc))
                    stop.set()

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            channel.write(b'\r')
            synced_size = None
            editing = False
            try:
                while not stop.is_set():
                    # Never inject shell commands while a foreground program is running
                    # or while the user is editing a command. Recheck at a fresh prompt.
                    size = terminal_size()
                    if prompt_ready.is_set() and not editing and size != synced_size:
                        prompt_ready.clear()
                        columns, rows = size
                        channel.write(f'stty cols {columns} rows {rows}\r'.encode('ascii'))
                        sizes.append({'columns': columns, 'rows': rows})
                        synced_size = size
                    try:
                        if msvcrt.kbhit():
                            key = msvcrt.getch()
                            if key == b'\x1d':
                                break
                            if key in (b'\x00', b'\xe0'):
                                key = EXTENDED_KEYS.get(msvcrt.getch(), b'')
                            if key == b'\x08':
                                key = b'\x7f'
                            if key:
                                prompt_ready.clear()
                                editing = key not in (b'\r', b'\n', b'\x03')
                                channel.write(key)
                        else:
                            time.sleep(.01)
                    except KeyboardInterrupt:
                        prompt_ready.clear()
                        editing = False
                        channel.write(b'\x03')
            finally:
                stop.set()
                thread.join(1)
                if progress_filter.pending:
                    sys.stdout.write(progress_filter.pending)
                    sys.stdout.flush()
    finally:
        restore_console()
        log_path.with_suffix('.json').write_text(json.dumps({
            'port': port, 'terminal_sizes': sizes, 'read_errors': errors,
            'hidden_driver_progress_lines': progress_filter.hidden_lines,
            'output_log': str(log_path),
        }, indent=2), encoding='utf-8')
    if errors:
        raise RuntimeError('RK serial connection ended: ' + errors[0])


if __name__ == '__main__':
    main()
