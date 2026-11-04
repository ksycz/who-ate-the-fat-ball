import subprocess

from fatball.camera import discovery

ARP = """? (192.168.1.1) at 0:11:22:33:44:55 on en0 ifscope [ethernet]
? (127.0.0.1) at a:b:c:d:e:f on en0 ifscope [ethernet]
? (192.168.1.9) at (incomplete) on en0 ifscope [ethernet]
"""


def test_cached_ip_is_tried_first(fake_camera, monkeypatch):
    monkeypatch.setattr(discovery, "arp_table", lambda: (_ for _ in ()).throw(AssertionError("arp used")))
    assert discovery.find_camera("127.0.0.1", fake_camera.port, "0a:0b:0c:0d:0e:0f") == "127.0.0.1"


def test_arp_table_finds_mac_with_dropped_leading_zeros(fake_camera, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, ARP, ""))
    assert discovery.arp_table()["00:11:22:33:44:55"] == "192.168.1.1"
    assert discovery.find_camera("10.255.255.1/32", fake_camera.port, "0A-0B-0C-0D-0E-0F") == "127.0.0.1"


def test_scan_finds_open_port_on_the_subnet(fake_camera, monkeypatch):
    monkeypatch.setattr(discovery, "arp_table", dict)
    assert discovery.find_camera("127.0.0.0/30", fake_camera.port, None) == "127.0.0.1"


def test_scan_with_a_known_mac_skips_a_device_with_another_mac(fake_camera, monkeypatch):
    monkeypatch.setattr(discovery, "arp_table", lambda: {"11:11:11:11:11:11": "127.0.0.1"})
    assert discovery.find_camera("127.0.0.0/30", fake_camera.port, "aa:bb:cc:dd:ee:ff") is None


def test_scan_with_a_known_mac_accepts_the_matching_device(fake_camera, monkeypatch):
    tables = iter([{}, {"aa:bb:cc:dd:ee:ff": "127.0.0.1"}])  # the ARP entry appears once the port answered
    monkeypatch.setattr(discovery, "arp_table", lambda: next(tables))
    assert discovery.find_camera("127.0.0.0/30", fake_camera.port, "AA-BB-CC-DD-EE-FF") == "127.0.0.1"


def test_mac_of_reads_the_arp_table_for_an_ip(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, ARP, ""))
    assert discovery.mac_of("192.168.1.1") == "00:11:22:33:44:55"
    assert discovery.mac_of("192.168.1.9") is None  # (incomplete)
    assert discovery.mac_of("192.168.1.200") is None


def test_same_mac_ignores_case_separators_and_leading_zeros():
    assert discovery.same_mac("0:1B:2c:3:4:5", "00-1b-2C-03-04-05")
    assert not discovery.same_mac("00:1b:2c:03:04:05", "00:1b:2c:03:04:06")
    assert not discovery.same_mac(None, "00:1b:2c:03:04:05")


def test_arp_lookup_normalises_the_mac(monkeypatch):
    monkeypatch.setattr(discovery, "arp_table", lambda: {"0a:0b:0c:0d:0e:0f": "192.168.1.9"})
    assert discovery.arp_lookup("A:B:C:D:E:F") == "192.168.1.9"
    assert discovery.arp_lookup("aa:aa:aa:aa:aa:aa") is None
