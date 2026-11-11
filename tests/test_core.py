import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import Server, State
from storage import Scanner
import system


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.server = Server(0, self.state)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def request(self, path='/api/state', method='GET', body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def headers(self):
        return {'X-Bench-Token': self.server.token, 'Content-Type': 'application/json'}

    def test_requires_token(self):
        self.assertEqual(self.request()[0], 401)

    def test_rejects_foreign_origin(self):
        self.assertEqual(self.request(headers={**self.headers(), 'Origin': 'https://example.com'})[0], 403)

    def test_rejects_rebinding_host(self):
        self.assertEqual(self.request(headers={**self.headers(), 'Host': 'attacker.example'})[0], 403)

    def test_state_hides_uninstall_command(self):
        self.state.apps = [dict(id='1', name='App', _command='secret command')]
        status, body = self.request(headers=self.headers())
        self.assertEqual(status, 200)
        self.assertNotIn(b'secret command', body)

    def test_no_confirmation_no_action(self):
        with patch.object(self.state, 'start_remove') as remove:
            status, _ = self.request('/api/uninstall', 'POST', {'ids': ['1']}, self.headers())
            self.assertEqual(status, 400)
            remove.assert_not_called()

    def test_static_traversal_rejected(self):
        self.assertEqual(self.request('/../system.py')[0], 404)

    def test_network_scan_rejected(self):
        self.assertEqual(self.request('/api/scan', 'POST', {'path': r'\\server\share'}, self.headers())[0], 400)

    def test_unknown_action_rejected(self):
        self.assertEqual(self.request('/api/execute', 'POST', {}, self.headers())[0], 404)

    def test_non_object_json_rejected(self):
        self.assertEqual(self.request('/api/uninstall', 'POST', [], self.headers())[0], 400)


class OperationTests(unittest.TestCase):
    def test_protected_app_rejected(self):
        state = State()
        state.apps = [dict(id='safe', removable=False)]
        with self.assertRaises(ValueError):
            state.start_remove(['safe'])

    def test_unknown_app_rejected(self):
        with self.assertRaises(ValueError):
            State().start_remove(['unknown'])

    def test_concurrent_uninstall_rejected(self):
        state = State()
        state.job = dict(status='running')
        with self.assertRaises(ValueError):
            state.start_remove(['anything'])

    @unittest.skipUnless(os.name == 'nt', 'Windows command parsing')
    def test_msi_install_command_converted_to_uninstall(self):
        guid = '{12345678-1234-1234-1234-123456789012}'
        exe, args = system.uninstall_command({'_command': 'MsiExec.exe /I' + guid})
        self.assertEqual(args, ['/x', guid])
        self.assertTrue(exe.lower().endswith('msiexec.exe'))

    @unittest.skipUnless(os.name == 'nt', 'Windows command parsing')
    def test_shell_command_rejected(self):
        with self.assertRaises(ValueError):
            system.uninstall_command({'_command': 'cmd.exe /c erase C:\\anything'})

    def test_match_uses_directory_boundary_and_longest_path(self):
        root = str(Path.cwd() / 'fixture')
        apps = [dict(id='a', location=root), dict(id='b', location=str(Path(root) / 'child'))]
        self.assertEqual(system.match_app(str(Path(root) / 'child' / 'app.exe'), apps), 'b')
        self.assertIsNone(system.match_app(root + '-other' + os.sep + 'app.exe', apps))

    def test_ambiguous_match_is_not_offered(self):
        root = str(Path.cwd() / 'fixture')
        self.assertIsNone(system.match_app(str(Path(root) / 'app.exe'), [dict(id='a', location=root), dict(id='b', location=root)]))

    def test_scan_counts_and_ranks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'folder').mkdir()
            (root / 'folder' / 'large.bin').write_bytes(b'x' * 4096)
            (root / 'small.bin').write_bytes(b'abc')
            scanner = Scanner()
            scanner.start(root)
            scanner.thread.join(5)
            result = scanner.snapshot()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['bytes'], 4099)
            self.assertEqual(result['files'], 2)
            self.assertEqual(result['largest'][0]['size'], 4096)

    def test_scan_cancellation(self):
        scanner = Scanner()
        scanner.cancel.set()
        scanner._scan(Path.cwd())
        self.assertEqual(scanner.snapshot()['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
