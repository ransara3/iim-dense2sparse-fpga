import ctypes
import unittest
from unittest.mock import Mock, patch

from scripts.jtag_atlantic import JtagAtlantic


class JtagAtlanticTests(unittest.TestCase):
    def library(self):
        lib = Mock()
        lib.jtag_atlantic_open.return_value = 123
        lib.jtag_atlantic_write.return_value = 3
        def read(handle, buffer, size):
            ctypes.memmove(buffer, b'\x00\xac\xff', 3)
            return 3
        lib.jtag_atlantic_read.side_effect = read
        return lib

    def test_binary_read_write_and_close(self):
        lib = self.library()
        with patch('scripts.jtag_atlantic.ctypes.CDLL', return_value=lib):
            with JtagAtlantic('fake', cable='USB-Blaster') as port:
                self.assertEqual(port.read(8), b'\x00\xac\xff')
                self.assertEqual(port.write(b'\x00\xac\xff'), 3)
                buf = lib.jtag_atlantic_write.call_args.args[1]
                self.assertEqual(buf.raw, b'\x00\xac\xff')
        lib.jtag_atlantic_close.assert_called_once_with(123)

    def test_open_failure(self):
        lib = self.library()
        lib.jtag_atlantic_open.return_value = None
        with patch('scripts.jtag_atlantic.ctypes.CDLL', return_value=lib):
            with self.assertRaises(RuntimeError):
                JtagAtlantic('fake')

    def test_timeout_and_disconnect(self):
        lib = self.library()
        with patch('scripts.jtag_atlantic.ctypes.CDLL', return_value=lib):
            with JtagAtlantic('fake', timeout=0) as port:
                lib.jtag_atlantic_read.side_effect = None
                lib.jtag_atlantic_read.return_value = 0
                with self.assertRaises(TimeoutError):
                    port.read(1)
                lib.jtag_atlantic_write.return_value = -1
                with self.assertRaises(OSError):
                    port.write(b'X')


if __name__ == '__main__':
    unittest.main()
