@echo off
setlocal EnableExtensions

echo [KiwoomServer Builder]

set "MSBUILD_PATH="
set "SDK_TOOLS=C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools"
set "AXIMP_PATH=%SDK_TOOLS%\AxImp.exe"
set "TLBIMP_PATH=%SDK_TOOLS%\TlbImp.exe"
set "INTEROP_DIR=%CD%\lib\interop"

if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_PATH=C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_PATH=C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe"
if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" set "MSBUILD_PATH=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not defined MSBUILD_PATH if exist "C:\Windows\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe" set "MSBUILD_PATH=C:\Windows\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe"

if not defined MSBUILD_PATH (
    echo [Error] MSBuild.exe not found. Install Visual Studio Build Tools with .NET Framework 4.8 tools.
    exit /b 1
)

for %%F in ("%AXIMP_PATH%" "%TLBIMP_PATH%" "C:\OpenAPI\khopenapi.ocx" "C:\Daishin\CYBOSPLUS\cputil.dll" "C:\Daishin\CYBOSPLUS\CpSysDib.dll" "C:\Daishin\CYBOSPLUS\CPDIB.DLL") do (
    if not exist %%F (
        echo [Error] Required file not found: %%~F
        exit /b 1
    )
)

echo 1. Restoring NuGet packages...
if exist "packages\Newtonsoft.Json.13.0.3\lib\net45\Newtonsoft.Json.dll" if exist "packages\WebSocketSharp-NonPreRelease.1.0.0\lib\net35\websocket-sharp.dll" goto packages_ready
"%MSBUILD_PATH%" KiwoomServer.sln /t:Restore /p:RestorePackagesConfig=true
if errorlevel 1 (
    echo [Error] NuGet package restore failed.
    exit /b 1
)
:packages_ready

echo.
echo 2. Generating 32-bit broker interop assemblies...
if not exist "%INTEROP_DIR%" mkdir "%INTEROP_DIR%"

"%AXIMP_PATH%" "C:\OpenAPI\khopenapi.ocx" /out:"%INTEROP_DIR%\AxInterop.KHOpenAPILib.dll"
if errorlevel 1 exit /b 1
"%TLBIMP_PATH%" "C:\Daishin\CYBOSPLUS\cputil.dll" /namespace:CPUTILLib /out:"%INTEROP_DIR%\Interop.CPUTILLib.dll" /machine:x86
if errorlevel 1 exit /b 1
"%TLBIMP_PATH%" "C:\Daishin\CYBOSPLUS\CpSysDib.dll" /namespace:CPSYSDIBLib /out:"%INTEROP_DIR%\Interop.CPSYSDIBLib.dll" /machine:x86
if errorlevel 1 exit /b 1
"%TLBIMP_PATH%" "C:\Daishin\CYBOSPLUS\CPDIB.DLL" /namespace:DSCBO1Lib /out:"%INTEROP_DIR%\Interop.DSCBO1Lib.dll" /machine:x86
if errorlevel 1 exit /b 1

echo.
echo 3. Building x86 project...
"%MSBUILD_PATH%" KiwoomServer.vbproj /p:Configuration=Debug /p:Platform=AnyCPU
if errorlevel 1 (
    echo [Build Failed]
    exit /b 1
)

echo.
echo [Build Success]
echo Run bin\Debug\KiwoomServer.exe to start.
exit /b 0
