# -*- mode: python ; coding: utf-8 -*-
a = Analysis(['desktop.py'], pathex=[], binaries=[], datas=[('researcher.toml', '.'), ('static', 'static')],
             hiddenimports=['pypdf', 'webview.platforms.edgechromium'], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='InfraResearcher',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, icon='static/app.ico')
