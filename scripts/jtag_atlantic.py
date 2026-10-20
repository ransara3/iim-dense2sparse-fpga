"""Binary-safe, timeout-bounded access to Quartus's JTAG Atlantic library."""
import ctypes
import time


class JtagAtlantic:
    def __init__(self, library, cable=None, device=1, instance=0, timeout=30.0):
        self.timeout = timeout
        self.lib = ctypes.CDLL(str(library))
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
            raise RuntimeError('Cannot open JTAG UART. Check cable/device/instance, '
                               'programmed SOF, and close nios2-terminal.')

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
