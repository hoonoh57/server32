@echo off
echo [KiwoomServer Builder]

echo 1. Restoring NuGet packages...
if exist "nuget.exe" (
    nuget install packages.config -OutputDirectory packages
) else (
    echo [Info] nuget.exe not found in current dir. Assuming packages are ready or restored manually.
)

echo.
echo 2. Building Project...
set MSBUILD_PATH=""

if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe" (
    set MSBUILD_PATH="C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe"
)
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" (
    set MSBUILD_PATH="C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe"
)
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\Msbuild\Current\Bin\MSBuild.exe" (
    set MSBUILD_PATH="C:\Program Files\Microsoft Visual Studio\2022\Community\Msbuild\Current\Bin\MSBuild.exe"
)
if exist "C:\Windows\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe" (
    if %MSBUILD_PATH% == "" set MSBUILD_PATH="C:\Windows\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe"
)

if %MSBUILD_PATH% == "" (
    echo [Error] MSBuild.exe not found! Please check your Visual Studio installation.
    pause
    exit /b
)

echo Using MSBuild: %MSBUILD_PATH%
%MSBUILD_PATH% KiwoomServer.vbproj /p:Configuration=Debug /p:Platform=AnyCPU

if %errorlevel% neq 0 (
    echo.
    echo [Build Failed]
    pause
    exit /b
)

echo.
echo [Build Success]
echo Run 'bin\Debug\KiwoomServer.exe' to start.
pause
