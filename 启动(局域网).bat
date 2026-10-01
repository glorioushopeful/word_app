@echo off
chcp 65001 >nul
cd /d %~dp0

echo   正在清理 5000 端口上的旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo   正在放行 Windows 防火墙 5000 端口（若手机连不上，请右键本文件用管理员身份运行）
netsh advfirewall firewall add rule name="WordApp-5000" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1

echo.
echo   正在启动背单词服务，启动后会显示手机访问地址
echo   保持本窗口开启，关闭即停止服务
echo.
python app.py

pause
