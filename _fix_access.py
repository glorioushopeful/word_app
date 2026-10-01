import os
import re
import sys
import time
import socket
import subprocess
import urllib.request

BASE = r'c:\Users\Administrator\Desktop\word_app'
LOG = os.path.join(BASE, '_tunnel_out.txt')
DETACHED = 0x00000008

# 1. 放行防火墙（局域网用）
for port in (5001, 5002, 5003, 5004):
    subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                    f'name=WordApp-{port}', 'dir=in', 'action=allow',
                    'protocol=TCP', f'localport={port}'],
                   capture_output=True)
print('防火墙规则已尝试添加（5001-5004）')

# 2. 确认局域网地址
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('223.5.5.5', 80))
    lan_ip = s.getsockname()[0]
finally:
    s.close()

# 找当前在跑的背单词服务端口
lan_port = None
for port in (5000, 5001, 5002, 5003, 5004):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/stats', timeout=3) as r:
            body = r.read().decode('utf-8')
            if 'no_syn' in body:          # 背单词服务的标志字段
                lan_port = port
                break
    except Exception:
        pass
print(f'局域网地址: http://{lan_ip}:{lan_port}')

# 3. 重启隧道
subprocess.run(['taskkill', '/F', '/IM', 'cloudflared.exe'], capture_output=True)
ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tunnel.py*' } | "
      "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
subprocess.run(['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps], capture_output=True)
time.sleep(2)

p = subprocess.Popen([sys.executable, 'tunnel.py'], cwd=BASE,
                     stdout=open(LOG, 'w', encoding='utf-8'),
                     stderr=subprocess.STDOUT, creationflags=DETACHED)

url = None
for _ in range(30):
    time.sleep(2)
    try:
        text = open(LOG, encoding='utf-8', errors='ignore').read()
    except Exception:
        continue
    m = re.search(r'https://[A-Za-z0-9._-]+\.trycloudflare\.com', text)
    if m:
        url = m.group(0)
        break
print('隧道地址:', url)
