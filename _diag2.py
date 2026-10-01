import os
import sys
import socket
import subprocess
import urllib.request
sys.stdout.reconfigure(encoding='utf-8')

BASE = r'c:\Users\Administrator\Desktop\word_app'

# 1. 隧道日志尾部
p = os.path.join(BASE, '_tunnel_out.txt')
if os.path.exists(p):
    lines = open(p, encoding='utf-8', errors='ignore').read().splitlines()
    print('--- 隧道日志尾部 ---')
    for l in lines[-6:]:
        print('  ', l[:150])

# 2. cloudflared 进程
out = subprocess.run(['tasklist'], capture_output=True, text=True).stdout
print('\ncloudflared 运行中:', 'cloudflared.exe' in out)

# 3. 本机局域网 IP
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('223.5.5.5', 80))
    ip = s.getsockname()[0]
finally:
    s.close()
print('本机局域网 IP:', ip)

# 4. 本地端口
for port in (5000, 5001, 5002):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/stats', timeout=3) as r:
            print(f'  端口 {port}: 服务在跑 HTTP {r.status}')
    except Exception as e:
        print(f'  端口 {port}: {type(e).__name__}')

# 5. 监听地址
out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True).stdout
print('\n--- 5002 端口监听 ---')
for line in out.splitlines():
    if ':5002' in line and 'LISTENING' in line:
        print('  ', line.strip())
