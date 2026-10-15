import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atelier.app import create_app
from atelier.network import local_interfaces, permitted_peer
from test_studio import FakeRuntime


INTERFACES = [{'address': '192.168.50.10', 'subnet': '192.168.50.0/24', 'interface': 'Ethernet'}]


class NetworkTests(unittest.TestCase):
    def test_discovery_ignores_vpn_and_inactive_adapters(self):
        addresses = {
            name: [SimpleNamespace(family=socket.AF_INET, address=address, netmask='255.255.255.0')]
            for name, address in [('Ethernet', '192.168.50.10'), ('throne-tun', '172.19.0.1'),
                                  ('Radmin VPN', '172.20.0.10'), ('Wi-Fi', '192.168.51.10')]
        }
        stats = {name: SimpleNamespace(isup=name != 'Wi-Fi') for name in addresses}
        with patch('atelier.network.psutil.net_if_addrs', return_value=addresses), patch('atelier.network.psutil.net_if_stats', return_value=stats):
            self.assertEqual(local_interfaces(), INTERFACES)

    def test_peer_scope_and_local_only(self):
        self.assertTrue(permitted_peer('127.0.0.1', INTERFACES, False))
        self.assertTrue(permitted_peer('192.168.50.52', INTERFACES))
        for peer in ['192.168.51.52', '8.8.8.8', '172.20.0.11', None]:
            self.assertFalse(permitted_peer(peer, INTERFACES))
        self.assertFalse(permitted_peer('192.168.50.52', INTERFACES, False))

    def test_phone_requests_preserve_host_and_origin_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch('atelier.app.local_interfaces', return_value=INTERFACES), patch.dict('os.environ', {'ATELIER_LOCAL_ONLY': '0'}):
            app = create_app(project_root=Path(directory), runtime_factory=FakeRuntime)
            client = app.test_client()
            phone = {'base_url': 'http://192.168.50.10:7870', 'environ_overrides': {'REMOTE_ADDR': '192.168.50.52'}}
            self.assertEqual(client.get('/api/projects', **phone).status_code, 200)
            self.assertEqual(client.post('/api/projects', json={'name': 'Phone test'}, headers={'Origin': 'http://192.168.50.10:7870'}, **phone).status_code, 201)
            self.assertEqual(client.post('/api/projects', json={'name': 'Blocked'}, headers={'Origin': 'http://untrusted.example'}, **phone).status_code, 403)
            self.assertEqual(client.get('/api/projects', base_url='http://untrusted.example', environ_overrides={'REMOTE_ADDR': '192.168.50.52'}).status_code, 400)
            self.assertEqual(client.get('/api/projects', base_url=phone['base_url'], environ_overrides={'REMOTE_ADDR': '8.8.8.8'}).status_code, 403)
            with patch('atelier.app.subprocess.run', side_effect=OSError):
                self.assertEqual(client.get('/api/status', **phone).json['network_urls'], ['http://192.168.50.10:7870/'])
