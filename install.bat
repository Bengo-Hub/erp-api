@echo off
REM Script to deploy Django application on IIS (Windows)

REM Step 1: Install IIS and enable CGI
echo Installing IIS and enabling CGI...
dism /online /enable-feature /featurename:IIS-WebServerRole
dism /online /enable-feature /featurename:IIS-WebServer
dism /online /enable-feature /featurename:IIS-CommonHttpFeatures
dism /online /enable-feature /featurename:IIS-CGI

REM Step 2: Copy project to IIS root directory
echo Copying project to IIS root directory...
xcopy /E /I "C:\path\to\your\django\project" "C:\inetpub\wwwroot\erpapi"

REM Step 3: Install Python and required libraries
echo Installing Python and required libraries...
curl https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe -o python-installer.exe
python-installer.exe /quiet InstallAllUsers=1 PrependPath=1
del python-installer.exe

pip install django openpyxl wfastcgi

REM Step 4: Configure IIS permissions
echo Configuring IIS permissions...
icacls "C:\Python312" /grant "IIS AppPool\DefaultAppPool:(OI)(CI)F"

REM Step 5: Enable wfastcgi
echo Enabling wfastcgi...
wfastcgi-enable

REM Step 6: Configure web.config
echo Configuring web.config...
copy "C:\inetpub\wwwroot\erpapi\web-config-template" "C:\inetpub\wwwroot\web.config"

REM Step 7: Unlock IIS handlers
echo Unlocking IIS handlers...
%windir%\system32\inetsrv\appcmd.exe unlock config -section:system.webServer/handlers

REM Step 8: Add Virtual Directory for static files
echo Adding Virtual Directory for static files...
%windir%\system32\inetsrv\appcmd.exe add vdir /app.name:"Default Web Site/" /path:/static /physicalPath:"C:\inetpub\wwwroot\erpapi\static"

REM Step 9: Restart IIS
echo Restarting IIS...
iisreset

echo Deployment complete! Access your application at http://localhost:8000