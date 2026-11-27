"""Local report conversion. Source documents are data, never instructions or code."""
import io
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from uuid import uuid4

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from PIL import Image

from .config import soffice_path
from .markdown_export import safe_url

MAX_TEXT = 1_000_000
MAX_PAGES = 100


class ConversionError(ValueError):
    pass


def escape(text):
    return re.sub(r'([\\`*_\[\]<>#|])', r'\\\1', str(text or ''))


class Converter:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.assets = []
        self.warnings = []
        self.counters = {}

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def image(self, image, label):
        if len(self.assets) >= 200 or image.width * image.height > 40_000_000:
            raise ConversionError('报告图片过多或尺寸过大，请拆分报告后导入。')
        image = image.convert('RGBA' if image.mode in ('RGBA', 'LA') else 'RGB')
        image.thumbnail((2400, 3200))
        ident = uuid4().hex
        path = self.folder / (ident + '.png')
        image.save(path, format='PNG')
        if sum((self.folder / item['file']).stat().st_size for item in self.assets) + path.stat().st_size > 100 * 1024 * 1024:
            raise ConversionError('报告图片总量过大，请拆分报告后导入。')
        self.assets.append({'id': ident, 'file': path.name, 'name': label + '.png'})
        return '![' + escape(label) + '](import-asset:' + ident + ')'

    def run(self, run, document):
        text = escape(run.text)
        if text.strip():
            left, right = len(text) - len(text.lstrip()), len(text) - len(text.rstrip())
            core = text.strip()
            if run.bold:
                core = '**' + core + '**'
            if run.italic:
                core = '*' + core + '*'
            if run.font.strike:
                core = '~~' + core + '~~'
            text = text[:left] + core + (text[-right:] if right else '')
        for blip in run._r.xpath('.//a:blip'):
            rid = blip.get(qn('r:embed'))
            part = document.part.related_parts.get(rid)
            if part is None:
                self.warn('文档包含外部图片链接，未读取外部地址；请对照原文件核对。')
                continue
            try:
                with Image.open(io.BytesIO(part.blob)) as picture:
                    text += '\n\n' + self.image(picture, '报告图片' + str(len(self.assets) + 1)) + '\n\n'
            except ConversionError:
                raise
            except (OSError, ValueError):
                self.warn('部分图片格式无法转换，已保留原文件供核对。')
        if run._r.xpath('.//c:chart'):
            self.warn('文档含嵌入图表，正文保留文字；请下载原文件查看原图表。')
        return text

    def inline(self, paragraph, document):
        parts = []
        for element in paragraph._p:
            if element.tag == qn('w:r'):
                parts.append(self.run(Run(element, paragraph), document))
            elif element.tag == qn('w:hyperlink'):
                label = ''.join(self.run(Run(run, paragraph), document) for run in element if run.tag == qn('w:r'))
                rel = document.part.rels.get(element.get(qn('r:id')))
                url = safe_url(rel.target_ref) if rel and rel.is_external else ''
                parts.append('[' + label + '](' + url.replace(' ', '%20').replace(')', '%29') + ')' if url else label)
        return ''.join(parts).strip()

    def list_prefix(self, paragraph, document):
        properties = paragraph._p.pPr
        numbering = properties.numPr if properties is not None else None
        if numbering is None and paragraph.style is not None:
            properties = paragraph.style.element.pPr
            numbering = properties.numPr if properties is not None else None
        style = paragraph.style.name if paragraph.style is not None else ''
        if numbering is None:
            if style.startswith('List Bullet'):
                return '- '
            if style.startswith('List Number'):
                self.counters[style] = self.counters.get(style, 0) + 1
                return str(self.counters[style]) + '. '
            return ''
        num_id = numbering.numId.val if numbering.numId is not None else 0
        level = numbering.ilvl.val if numbering.ilvl is not None else 0
        if num_id == 0:
            return ''
        root = document.part.numbering_part.element
        num = root.find(f'w:num[@w:numId="{num_id}"]', root.nsmap)
        abstract_id = num.find(qn('w:abstractNumId')).get(qn('w:val')) if num is not None else None
        abstract = root.find(f'w:abstractNum[@w:abstractNumId="{abstract_id}"]', root.nsmap)
        lvl = abstract.find(f'w:lvl[@w:ilvl="{level}"]', root.nsmap) if abstract is not None else None
        fmt = lvl.find(qn('w:numFmt')) if lvl is not None else None
        if fmt is not None and fmt.get(qn('w:val')) == 'bullet':
            return '  ' * min(level, 6) + '- '
        start = lvl.find(qn('w:start')) if lvl is not None else None
        key = (num_id, level)
        self.counters[key] = self.counters.get(key, int(start.get(qn('w:val'))) - 1 if start is not None else 0) + 1
        return '  ' * min(level, 6) + str(self.counters[key]) + '. '

    def docx(self, path):
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 3000 or sum(item.file_size for item in entries) > 100 * 1024 * 1024:
                    raise ConversionError('Word 文档展开后过大，请拆分后导入。')
                if 'word/document.xml' not in archive.namelist():
                    raise ConversionError('文件不是有效的 Word 文档。')
            document = Document(path)
        except (zipfile.BadZipFile, KeyError, OSError) as error:
            raise ConversionError('无法读取 Word 文档，文件可能损坏或已加密。') from error
        blocks = []
        for element in document.element.body:
            if element.tag == qn('w:p'):
                paragraph = Paragraph(element, document)
                value = self.inline(paragraph, document)
                if not value:
                    continue
                style = paragraph.style.name if paragraph.style is not None else ''
                heading = re.search(r'(?:Heading|标题)\s*(\d+)', style, re.I)
                prefix = self.list_prefix(paragraph, document)
                if heading or style in ('Title', '标题'):
                    level = min(6, int(heading[1])) if heading else 1
                    value = '#' * level + ' ' + prefix.strip() + (' ' if prefix else '') + value
                else:
                    value = prefix + value
                blocks.append(value)
            elif element.tag == qn('w:tbl'):
                table = Table(element, document)
                seen = set()
                rows = []
                for row in table.rows:
                    values = []
                    for cell in row.cells:
                        if cell._tc in seen:
                            values.append('')
                        else:
                            seen.add(cell._tc)
                            values.append(' / '.join(self.inline(p, document).replace('\n', ' / ') for p in cell.paragraphs))
                    rows.append(values)
                blocks.append(markdown_table(rows, escaped=True))
        return '\n\n'.join(blocks)

    def pdf(self, path):
        import pdfplumber
        import pypdfium2 as pdfium
        blocks = []
        with pdfplumber.open(path) as document, pdfium.PdfDocument(path) as rendered:
            if document.doc.encryption:
                raise ConversionError('PDF 已加密，请先解除密码保护再导入。')
            if len(document.pages) > MAX_PAGES:
                raise ConversionError(f'报告超过 {MAX_PAGES} 页，请拆分后导入。')
            sizes = Counter(round(c.get('size', 12), 1) for page in document.pages[:10] for c in page.chars if c.get('text', '').strip())
            normal_size = sizes.most_common(1)[0][0] if sizes else 12
            for number, page in enumerate(document.pages, 1):
                page_blocks = []
                bitmap = None

                def page_image():
                    nonlocal bitmap
                    if bitmap is None:
                        pdf_page = rendered[number - 1]
                        scale = min(2, 2400 / max(page.width, page.height))
                        raster = pdf_page.render(scale=scale)
                        bitmap = raster.to_pil().copy()
                        raster.close()
                        pdf_page.close()
                    return bitmap

                page_text = ''.join(c.get('text', '') for c in page.chars).strip()
                if not page_text or '(cid:' in page_text or '\ufffd' in page_text:
                    blocks.append(self.image(page_image(), f'原报告第{number}页'))
                    self.warn(f'第 {number} 页没有可靠的可提取文字，已保留页面图片；该页文字不可直接编辑。')
                    continue
                tables = [table for table in page.find_tables() if len(table.rows) >= 2]
                for table in tables:
                    page_blocks.append((table.bbox[1], table.bbox[0], markdown_table(table.extract())))

                def outside_tables(obj):
                    x, y = (obj['x0'] + obj['x1']) / 2, (obj['top'] + obj['bottom']) / 2
                    return not any(a <= x <= c and b <= y <= d for a, b, c, d in (t.bbox for t in tables))

                for line in page.filter(outside_tables).extract_text_lines(x_tolerance=2, y_tolerance=3):
                    text = escape(line['text'])
                    size = max((c.get('size', normal_size) for c in line.get('chars', [])), default=normal_size)
                    if size >= normal_size * 1.2 and len(text) < 150:
                        text = ('# ' if size >= normal_size * 1.6 else '## ') + text
                    page_blocks.append((line['top'], line['x0'], text))
                for picture in page.images:
                    original = page_image()
                    xscale, yscale = original.width / page.width, original.height / page.height
                    box = (max(0, picture['x0'] * xscale), max(0, picture['top'] * yscale),
                           min(original.width, picture['x1'] * xscale), min(original.height, picture['bottom'] * yscale))
                    if box[2] - box[0] > 2 and box[3] - box[1] > 2:
                        page_blocks.append((picture['top'], picture['x0'], self.image(original.crop(box), f'第{number}页图片{len(self.assets) + 1}')))
                if page.curves:
                    self.warn(f'第 {number} 页含图形，已附页面原图供核对。')
                    page_blocks.append((page.height, 0, self.image(page_image(), f'第{number}页图形原图')))
                blocks.extend(value for _, _, value in sorted(page_blocks, key=lambda value: (value[0], value[1])))
                if sum(len(value) for value in blocks) > MAX_TEXT:
                    raise ConversionError('报告正文过长，请拆分后导入。')
        self.warn('PDF 已按页面阅读顺序提取；复杂分栏、合并单元格和分页处请在预览中核对。')
        return '\n\n'.join(blocks)


def markdown_table(rows, escaped=False):
    if not rows:
        return ''
    width = max(len(row) for row in rows)
    if width > 80 or len(rows) > 5000:
        raise ConversionError('报告表格过大，请拆分后导入。')
    lines = []
    for index, row in enumerate(rows):
        values = [(str(value or '') if escaped else escape(value)).replace('\n', ' / ') for value in row]
        lines.append('| ' + ' | '.join(values + [''] * (width - len(values))) + ' |')
        if index == 0:
            lines.append('| ' + ' | '.join(['---'] * width) + ' |')
    return '\n'.join(lines)


def convert_doc(path, folder):
    executable = soffice_path()
    if not executable or not Path(executable).is_file():
        raise ConversionError('导入 .doc 需要 LibreOffice，请在设置与维护中配置，或先另存为 .docx。')
    profile = folder / 'office-profile'
    (profile / 'user').mkdir(parents=True)
    (profile / 'user/registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop><prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
</oor:items>''', encoding='utf-8')
    runner = Path(executable).with_suffix('.com')
    converted = path.with_suffix('.docx')
    try:
        result = subprocess.run([str(runner if runner.is_file() else executable), '-env:UserInstallation=' + profile.as_uri(),
                                 '--headless', '--nologo', '--nodefault', '--norestore', '--convert-to', 'docx', '--outdir', str(folder), str(path)],
                                capture_output=True, timeout=75, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        # A launcher timeout may occur after a complete document has been written.
        # The normal DOCX parser below verifies the ZIP and document before use.
        if not converted.is_file():
            raise ConversionError('DOC 报告转换超时，请重试或另存为 DOCX 后导入。')
    else:
        if result.returncode:
            raise ConversionError('无法读取 DOC 报告，请检查是否损坏或加密，或另存为 DOCX 后导入。')
    if not converted.is_file():
        raise ConversionError('无法读取 DOC 报告，请检查是否损坏或加密，或另存为 DOCX 后导入。')
    return converted


def convert(folder):
    folder = Path(folder)
    info = json.loads((folder / 'manifest.json').read_text('utf-8'))
    source = folder / ('source' + info['extension'])
    converter = Converter(folder)
    if info['extension'] == '.doc':
        source = convert_doc(source, folder)
    markdown = converter.pdf(source) if info['extension'] == '.pdf' else converter.docx(source)
    if not markdown.strip():
        raise ConversionError('报告没有可导入的正文。')
    if len(markdown) > MAX_TEXT:
        raise ConversionError('报告正文过长，请拆分后导入。')
    result = {'markdown': markdown, 'assets': converter.assets, 'warnings': converter.warnings}
    (folder / 'converted.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result


if __name__ == '__main__':
    folder = Path(sys.argv[1])
    try:
        convert(folder)
    except Exception as error:
        message = str(error) if isinstance(error, ConversionError) else '报告转换失败，文件可能损坏、已加密或格式不受支持。'
        (folder / 'error.json').write_text(json.dumps({'detail': message}, ensure_ascii=False), encoding='utf-8')
        raise SystemExit(1)
