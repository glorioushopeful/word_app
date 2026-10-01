"""
Tailscale 固定地址启动器：地址永久不变，手机装 App 登录同一账号即可访问
用法：双击「启动(Tailscale固定地址).bat」
"""
import os
import re
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', '5000'))
URL_FILE = os.path.join(BASE_DIR, '手机访问地址.txt')


def tailscale_exe():
    """找到 tailscale.exe（默认安装路径，或已在 PATH 里）"""
    from shutil import which
    p = which('tailscale')
    if p:
        return p
    for base in (r'C:\Program Files', r'C:\Program Files (x86)'):
        cand = os.path.join(base, 'Tailscale', 'tailscale.exe')
        if os.path.exists(cand):
            return cand
    return None


def tailscale_ip():
    """从 tailscale 状态里取本机 IP（100.x.y.z）"""
    exe = tailscale_exe()
    if not exe:
        return None
    for args in (['ip', '-4'], ['status'], ['status', '--json']):
        try:
            out = subprocess.run([exe] + args, capture_output=True, text=True,
                                 timeout=25).stdout
        except Exception:
            continue
        m = re.search(r'\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', out)
        if m:
            return m.group(0)
    return None


def port_in_use(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    finally:
        s.close()


def print_qr(url):
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        print('\n手机扫码即可打开：\n')
        for row in qr.get_matrix():
            print(''.join('##' if c else '  ' for c in row))
    except Exception as e:
        print('\n（二维码生成失败，直接输入地址即可：%s）' % e)


def main():
    print('正在检查 Tailscale 状态...')
    ip = tailscale_ip()

    if not ip:
        exe = tailscale_exe() or 'tailscale'
        print('\n还没登录 Tailscale，请先完成这几步：')
        print('  1. 双击开始菜单里的 Tailscale（托盘区会出现图标）')
        print('     或在命令行执行：  "%s" up' % exe)
        print('  2. 弹出的网页里用 Google / Microsoft / GitHub 账号登录（免费）')
        print('  3. 手机应用商店搜「Tailscale」安装，登录同一个账号')
        print('  4. 完成后重新双击本脚本')
        try:
            input('\n按回车键退出...')
        except EOFError:
            pass
        return

    # 自动挑一个空闲端口
    port = PORT
    while port_in_use(port) and port < PORT + 20:
        port += 1

    print(f'正在启动背单词服务（端口 {port}）...')
    env = os.environ.copy()
    env['PORT'] = str(port)
    flask = subprocess.Popen([sys.executable, 'app.py'], cwd=BASE_DIR, env=env)
    time.sleep(4)

    url = f'http://{ip}:{port}'
    with open(URL_FILE, 'w', encoding='utf-8') as f:
        f.write(url + '\n')

    print('\n' + '=' * 56)
    print('  固定地址（永久不变）：', url)
    print('  已保存到：', URL_FILE)
    print('  手机需装 Tailscale App 并登录同一账号（无需开 WiFi 同一网络）')
    print('=' * 56)
    print_qr(url)
    print('\n按 Ctrl+C 停止服务\n')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        flask.terminate()


if __name__ == '__main__':
    main()
