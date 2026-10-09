@echo off
cd /d "%~dp0"
if exist "dist-ui\InfraResearcher.exe" (
    start "" "dist-ui\InfraResearcher.exe"
) else if exist "dist-models\InfraResearcher.exe" (
    start "" "dist-models\InfraResearcher.exe"
) else if exist "dist-tasks\InfraResearcher.exe" (
    start "" "dist-tasks\InfraResearcher.exe"
) else if exist "dist-review\InfraResearcher.exe" (
    start "" "dist-review\InfraResearcher.exe"
) else if exist "dist-notes\InfraResearcher.exe" (
    start "" "dist-notes\InfraResearcher.exe"
) else if exist "dist-materials\InfraResearcher.exe" (
    start "" "dist-materials\InfraResearcher.exe"
) else if exist "dist-drawing\InfraResearcher.exe" (
    start "" "dist-drawing\InfraResearcher.exe"
) else if exist "dist-face\InfraResearcher.exe" (
    start "" "dist-face\InfraResearcher.exe"
) else if exist "dist-flex\InfraResearcher.exe" (
    start "" "dist-flex\InfraResearcher.exe"
) else if exist "dist-eyes\InfraResearcher.exe" (
    start "" "dist-eyes\InfraResearcher.exe"
) else if exist "dist-natural\InfraResearcher.exe" (
    start "" "dist-natural\InfraResearcher.exe"
) else if exist "dist-detail\InfraResearcher.exe" (
    start "" "dist-detail\InfraResearcher.exe"
) else if exist "dist-rig\InfraResearcher.exe" (
    start "" "dist-rig\InfraResearcher.exe"
) else if exist "dist-flow\InfraResearcher.exe" (
    start "" "dist-flow\InfraResearcher.exe"
) else if exist "dist-music\InfraResearcher.exe" (
    start "" "dist-music\InfraResearcher.exe"
) else if exist "dist-companion\InfraResearcher.exe" (
    start "" "dist-companion\InfraResearcher.exe"
) else if exist "dist-blended\InfraResearcher.exe" (
    start "" "dist-blended\InfraResearcher.exe"
) else if exist "dist-actions\InfraResearcher.exe" (
    start "" "dist-actions\InfraResearcher.exe"
) else if exist "dist-scene\InfraResearcher.exe" (
    start "" "dist-scene\InfraResearcher.exe"
) else if exist "dist-chat\InfraResearcher.exe" (
    start "" "dist-chat\InfraResearcher.exe"
) else if exist "dist-motion\InfraResearcher.exe" (
    start "" "dist-motion\InfraResearcher.exe"
) else if exist "dist-wallpaper\InfraResearcher.exe" (
    start "" "dist-wallpaper\InfraResearcher.exe"
) else if exist "dist-infra\InfraResearcher.exe" (
    start "" "dist-infra\InfraResearcher.exe"
) else if exist "dist\InfraResearcher.exe" (
    start "" "dist\InfraResearcher.exe"
) else (
    python desktop.py
    if errorlevel 1 pause
)
