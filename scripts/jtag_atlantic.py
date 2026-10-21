"""Binary-safe, timeout-bounded access to Quartus's JTAG Atlantic library."""
import ctypes
import time
from pathlib import Path


# Quartus 25.1 exports the C++ jtagatlantic API rather than C aliases.
_SYMBOLS = {
    "open": "_Z17jtagatlantic_openPKciiS0_",
    "close": "_Z18jtagatlantic_closeP12JTAGATLANTIC",
    "read": "_Z17jtagatlantic_readP12JTAGATLANTICPcj",
    "write": "_Z18jtagatlantic_writeP12JTAGATLANTICPKcj",
}


def bind_api(lib):
    for name, symbol in _SYMBOLS.items():
        alias = "jtag_atlantic_" + name
        try:
            function = getattr(lib, alias)
        except AttributeError:
            try:
                function = getattr(lib, symbol)
            except AttributeError as exc:
                raise RuntimeError(f"Unsupported JTAG Atlantic library: missing {alias} / {symbol}") from exc
        setattr(lib, alias, function)
    return lib


def load_library(library):
    """Load matching Quartus AJI dependencies before JTAG Atlantic."""
    # Both clients export overlapping AJI symbols: JTAG client must win.
    directory = Path(library).resolve().parent
    dependencies = []
    for name in ("libjtag_client.so", "libaji_client.so"):
        dependency = directory / name
        if dependency.is_file():
            dependencies.append(ctypes.CDLL(str(dependency), mode=ctypes.RTLD_GLOBAL))
    return bind_api(ctypes.CDLL(str(library))), dependencies


class JtagAtlantic:
    def __init__(self, library, cable=None, device=1, instance=0, timeout=30.0):
        self.timeout = timeout
        self.lib, self._dependencies = load_library(library)
        self.lib.jtag_atlantic_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                              ctypes.c_int, ctypes.c_char_p]
        self.lib.jtag_atlantic_open.restype = ctypes.c_void_p
        for name in ('read', 'write'):
            fn = getattr(self.lib, 'jtag_atlantic_' + name)
            fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
        self.lib.jtag_atlantic_close.argtypes = [ctypes.c_void_p]
        self.lib.jtag_atlantic_close.restype = None
        self.handle = self.lib.jtag_atlantic_open(
            cable.encode() if cable else None, device, instance, b'dense2sparse')
        if not self.handle:
            detail = ""
            for symbol in ("jtag_atlantic_get_error", "_Z22jtagatlantic_get_errorPPKc"):
                try:
                    error_fn = getattr(self.lib, symbol)
                except AttributeError:
                    continue
                error_fn.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
                error_fn.restype = ctypes.c_int
                message = ctypes.c_char_p()
                code = error_fn(ctypes.byref(message))
                text = message.value.decode(errors="replace") if message.value else ""
                detail = f" Library error {code}: {text}"
                break
            raise RuntimeError('Cannot open JTAG UART. Check cable/device/instance, '
                               'programmed SOF, and close nios2-terminal.' + detail)

    def _transfer(self, data, size, writing):
        buffer = ctypes.create_string_buffer(data, size) if writing else ctypes.create_string_buffer(size)
        fn = self.lib.jtag_atlantic_write if writing else self.lib.jtag_atlantic_read
        deadline = time.monotonic() + self.timeout
        while True:
            count = fn(self.handle, buffer, size)
            if count < 0:
                raise OSError('JTAG Atlantic connection failed; reset and retry the frame.')
            if count:
                return count if writing else buffer.raw[:count]
            if time.monotonic() >= deadline:
                raise TimeoutError('JTAG UART timed out; check programming and press KEY[0].')
            time.sleep(0.001)

    def read(self, size):
        return self._transfer(None, size, False) if size else b''

    def write(self, data):
        data = bytes(data)
        return self._transfer(data, len(data), True) if data else 0

    def close(self):
        if self.handle:
            self.lib.jtag_atlantic_close(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
