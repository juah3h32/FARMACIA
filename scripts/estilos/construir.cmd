@echo off
rem Genera app\web\static\tailwind.css con las clases que usa app\web\index.html
cd /d "%~dp0"
npx -y tailwindcss@3.4.17 -c tailwind.config.js -i entrada.css -o ..\..\app\web\static\tailwind.css --minify
