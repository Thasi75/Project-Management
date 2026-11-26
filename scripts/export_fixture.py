"""Generate export QA samples with isolated paths; never reads user business data."""
import os
import sys
import hashlib
from pathlib import Path
from types import SimpleNamespace
root = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
os.environ['PM_DATA_DIR'] = str(root / 'tmp' / 'export-qa')
from backend.config import now, ensure_dirs
from backend.reporting import HEADINGS
from backend.exports import export_brief
ensure_dirs()
long = '完成采购与库存数据的联调验证，逐项核对订单字段和出库批次，保留验收记录并登记后续安排。'
sections = [{'heading': heading, 'paragraphs': ([{'text': long * (12 if i == 1 else 2), 'source_ids': ['T-SAMPLE','L-SAMPLE']}] if i not in (4,5) else [])} for i,heading in enumerate(HEADINGS)]
metrics = {f'验证指标 {i:02d}': str(i) for i in range(1,43)}
snap = {'project_name':'华东制造供应链系统实施与交付管理项目中文长标题排版验证', 'metrics':metrics,
        'warnings':['需求变更和风险栏目为空时显示“未记录”；本文件为导出排版验收样例。']}
brief=SimpleNamespace(start='2026-11-01',end='2026-11-07')
template_hash=hashlib.sha256((root/'templates'/'brief.docx').read_bytes()).hexdigest()[:12]
version=SimpleNamespace(id='export-layout-'+template_hash,snapshot=snap,number=1,created_at=now(),content={'sections':sections})
for ext in ('docx','pdf'):
    output=export_brief(brief,version,ext)
    print(str(output))

