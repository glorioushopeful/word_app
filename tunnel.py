"""
免费外网穿透启动器（Cloudflare Tunnel）
- 自动启动本地背单词服务
- 自动从 cloudflared 输出中抓取 https://xxx.trycloudflare.com
- 把地址写入「手机访问地址.txt」，并在屏幕上生成二维码，手机扫码即可打开
"""
import os
import re
import sys
import time
import signal
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(BASE_DIR, '手机访问地址.txt')
URL_RE = re.compile(r'https://[A-Za-z0-9._-]+\.trycloudflare\.com')

processes = []


def cleanup(*_):
    for p in processes:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def port_in_use(port):
    """端口是否被占用"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    finally:
        s.close()


def pick_port():
    """从 5000 开始找一个空闲端口，避免和别的项目抢端口"""
    env_port = os.environ.get('PORT')
    if env_port:
        return int(env_port)
    for port in range(5000, 5100):
        if not port_in_use(port):
            return port
    return 5000


def print_qr(url):
    """在屏幕上画二维码（纯 ASCII，避免 Windows GBK 控制台报错），同时保存图片"""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)

        print('\n手机扫码即可打开（或直接在手机浏览器输入上面的地址）：\n')
        for row in qr.get_matrix():
            print(''.join('##' if cell else '  ' for cell in row))

        png_path = os.path.join(BASE_DIR, '手机扫码.png')
        img = qrcode.make(url)
        img.save(png_path)
        print(f'\n二维码图片已保存：{png_path}（双击可用手机扫）')
    except Exception as e:
        print('\n（二维码生成失败，不影响使用，直接手动输入地址即可：%s）' % e)


def main():
    cloudflared = os.path.join(BASE_DIR, 'cloudflared.exe')
    if not os.path.exists(cloudflared):
        print('未找到 cloudflared.exe，请先把它放到本文件夹。')
        print('下载地址（免费、无需注册）：')
        print('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe')
        input('\n按回车键退出...')
        return

    port = pick_port()
    print(f'正在启动本地服务（端口 {port}）...')
    env = os.environ.copy()
    env['PORT'] = str(port)
    flask = subprocess.Popen([sys.executable, 'app.py'], cwd=BASE_DIR, env=env)
    processes.append(flask)

    # 等服务真正起来
    for _ in range(30):
        if port_in_use(port):
            break
        time.sleep(0.5)

    print('正在建立免费隧道，请稍候（一般 5~15 秒）...\n')
    tunnel = subprocess.Popen(
        [cloudflared, 'tunnel', '--url', f'http://localhost:{port}'],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='ignore', bufsize=1
    )
    processes.append(tunnel)

    url = None
    deadline = time.time() + 90
    while time.time() < deadline:
        line = tunnel.stdout.readline()
        if not line:
            if tunnel.poll() is not None:
                break
            continue
        line = line.rstrip()
        if line:
            print('   [cloudflared]', line)
        m = URL_RE.search(line)
        if m and not url:
            url = m.group(0)
            break

    if not url:
        print('\n未能获取到隧道地址，可能是网络不通或 cloudflared 启动失败。')
        print('可改用局域网方式：双击「启动(局域网).bat」')
        cleanup()
        return

    with open(URL_FILE, 'w', encoding='utf-8') as f:
        f.write(url)
    print('\n' + '=' * 56)
    print('  手机访问地址：', url)
    print('  已保存到：', URL_FILE)
    print('  电脑保持开机，关闭本窗口后地址失效，下次会换新地址')
    print('=' * 56)
    print_qr(url)

    print('\n按 Ctrl+C 停止服务\n')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == '__main__':
    main()
