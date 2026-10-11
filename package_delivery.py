# 交付打包脚本：收集源码与文档，排除虚拟环境、运行数据及辅助脚本，再校验压缩包。
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parent
target=root.parent/'MOMO_AI_系统设计与代码骨架.zip'
excluded={'.venv','__pycache__','data','.git','.streamlit'}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        if not path.is_file() or excluded.intersection(path.relative_to(root).parts) or any(part.startswith('.venv') for part in path.relative_to(root).parts):
            continue
        if path.name in {'render-check.cjs','package_delivery.py'} or path.suffix=='.pyc':
            continue
        # .gitignore 不影响 ZIP 收集，必须显式排除潜在本地密钥文件。
        if path.name.startswith(('.env','config.local.')) or path.name=='secrets.toml':
            continue
        archive.write(path,Path(root.name)/path.relative_to(root))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert 'MOMO_AI_System/app.py' in archive.namelist()
    assert not any('/.venv/' in name or '/data/' in name for name in archive.namelist())
print(f'{target.name}: {target.stat().st_size} bytes, archive verified')
