"""Discover home-network addresses and limit studio access to their subnets."""
import ipaddress
import re
import socket

import psutil


PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def local_interfaces():
    stats = psutil.net_if_stats()
    result = []
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        if re.search(r'vpn|loopback|vethernet|docker|tailscale|zerotier|wsl|tunnel|(?:^|[-_ ])tun(?:$|[-_ ])|^tun\d|^tap\d', name, re.I):
            continue
        for entry in addresses:
            if entry.family != socket.AF_INET or not entry.netmask:
                continue
            address = ipaddress.ip_address(entry.address)
            if any(address in network for network in PRIVATE_V4):
                network = ipaddress.ip_network(f'{address}/{entry.netmask}', strict=False)
                result.append({'address': str(address), 'subnet': str(network), 'interface': name})
    return sorted(result, key=lambda row: (not row['address'].startswith('192.168.'), row['address']))


def permitted_peer(address, interfaces, enabled=True):
    try:
        peer = ipaddress.ip_address(address)
    except ValueError:
        return False
    if peer.is_loopback:
        return True
    return enabled and any(peer in ipaddress.ip_network(row['subnet']) for row in interfaces)
