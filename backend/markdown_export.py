"""Render Markdown to real Word paragraphs/runs/tables, without evaluating HTML.

The source is never rewritten. Images retain their caption and link in documents;
export deliberately does not fetch remote URLs or arbitrary local files.
"""
import re
from copy import deepcopy
from urllib.parse import urlsplit

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Cm, Pt, RGBColor
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

RENDER_VERSION = 'markdown-1'


def safe_url(value):
    value = value.strip()
    if re.search(r'[\x00-\x20\\]', value):
        return ''
    try:
        return value if urlsplit(value).scheme.lower() in ('', 'http', 'https', 'mailto') else ''
    except ValueError:
        return ''


def parser():
    md = MarkdownIt('gfm-like', {'html': False, 'breaks': True})
    md.validateLink = lambda url: bool(safe_url(url))
    return md.use(tasklists_plugin).use(footnote_plugin, inline=False)


def shade(element, color):
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color)
    element.append(shading)


def inline(paragraph, tokens, header=False, image_resolver=None):
    bold = italic = strike = 0
    link = None
    for token in tokens:
        kind = token.type
        if kind in ('strong_open', 'strong_close'):
            bold += token.nesting
            continue
        if kind in ('em_open', 'em_close'):
            italic += token.nesting
            continue
        if kind in ('s_open', 's_close'):
            strike += token.nesting
            continue
        if kind == 'link_open':
            link = safe_url(token.attrGet('href') or '')
            continue
        if kind == 'link_close':
            link = None
            continue
        if kind in ('softbreak', 'hardbreak'):
            paragraph.add_run().add_break()
            continue
        if kind == 'footnote_ref':
            run = paragraph.add_run('[' + str(token.meta['id'] + 1) + ']')
            run.font.superscript = True
            continue
        if kind == 'image':
            label = token.content or '图片'
            url = safe_url(token.attrGet('src') or '')
            path = image_resolver(url) if image_resolver and url else None
            if path:
                from PIL import Image
                section = paragraph.part.document.sections[-1]
                width = section.page_width - section.left_margin - section.right_margin
                height = section.page_height - section.top_margin - section.bottom_margin - Cm(1)
                with Image.open(path) as picture:
                    width = min(width, int(height * picture.width / picture.height))
                paragraph.add_run().add_picture(str(path), width=width)
                continue
            # Keep the image accessible, without exporting untrusted network/local bytes.
            paragraph.add_run('［图片：' + label + '］')
            if url:
                add_link(paragraph, url, url)
            continue
        if kind == 'html_inline':  # Only generated task-list markers; raw HTML is text.
            if token.content.startswith('<input class="task-list-item-checkbox"'):
                paragraph.add_run('☑' if 'checked=' in token.content else '☐')
            continue
        if kind not in ('text', 'code_inline'):
            continue
        run = paragraph.add_run(token.content)
        run.bold = True if bold or header else None
        run.italic = True if italic else None
        run.font.strike = True if strike else None
        if kind == 'code_inline':
            run.font.name = 'Consolas'
            shade(run._r.get_or_add_rPr(), 'F1F4F2')
        if link:
            attach_link(paragraph, run, link)


def attach_link(paragraph, run, url):
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True))
    run.font.color.rgb = RGBColor.from_string('2464B6')
    run.font.underline = True
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def add_link(paragraph, text, url):
    attach_link(paragraph, paragraph.add_run(text), url)


def append_markdown(document, source, *, anchor=None, image_resolver=None):
    """Append blocks, or replace an existing template paragraph at its location."""
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    tokens = parser().parse(source)
    created = []
    base_style = anchor.style if anchor is not None else None

    def paragraph(style=None):
        p = document.add_paragraph(style=style or base_style)
        if anchor is not None and style is None and anchor._p.pPr is not None:
            p._p.insert(0, deepcopy(anchor._p.pPr))
        created.append(p._p)
        return p

    # Keep old plain text exactly, including blank lines, tabs and leading spaces.
    plain = all(t.type in ('paragraph_open', 'paragraph_close', 'inline') and
                (t.type != 'inline' or (all(c.type in ('text', 'softbreak', 'hardbreak') for c in t.children or [])
                 and [line.strip() for line in t.content.split('\n')] == [line.strip() for line in ''.join('\n' if c.type in ('softbreak', 'hardbreak') else c.content for c in t.children or []).split('\n')]))
                for t in tokens)
    if plain:
        for line in source.split('\n'):
            paragraph().add_run(line)
    else:
        current = None
        lists = []
        quote_depth = 0
        pending_marker = ''
        table = None
        row = cell = None
        column = 0
        header = False
        heading_level = 0
        for token in tokens:
            kind = token.type
            if kind in ('bullet_list_open', 'ordered_list_open'):
                lists.append({'ordered': kind == 'ordered_list_open', 'next': int(token.attrGet('start') or 1)})
            elif kind in ('bullet_list_close', 'ordered_list_close'):
                lists.pop()
            elif kind == 'list_item_open':
                item = lists[-1]
                pending_marker = (str(item['next']) + '. ') if item['ordered'] else '• '
                if 'task-list-item' in (token.attrGet('class') or ''):
                    pending_marker = ''
                item['next'] += 1
            elif kind == 'blockquote_open':
                quote_depth += 1
            elif kind == 'blockquote_close':
                quote_depth -= 1
            elif kind in ('paragraph_open', 'heading_open'):
                level = min(6, int(token.tag[1:])) if kind == 'heading_open' else 0
                heading_level = level
                style = 'Heading ' + str(level) if level and 'Heading ' + str(level) in document.styles else None
                current = paragraph(style)
                current.paragraph_format.first_line_indent = Cm(0)
                if lists or quote_depth:
                    current.paragraph_format.left_indent = Cm(.55 * (len(lists) + quote_depth))
                if quote_depth:
                    shade(current._p.get_or_add_pPr(), 'F3F6F4')
                if pending_marker:
                    current.add_run(pending_marker)
                    pending_marker = ''
            elif kind == 'inline':
                if current is None:
                    current = paragraph()
                inline(current, token.children or [], header=header, image_resolver=image_resolver)
                if heading_level:
                    for run in current.runs:
                        run.bold = True
                        run.font.color.rgb = RGBColor(0, 0, 0)
                        run.font.name = '黑体'
                        run.font.size = Pt(14 if heading_level == 1 else 13 if heading_level == 2 else 12)
                        run._r.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), '黑体')
            elif kind in ('paragraph_close', 'heading_close'):
                current = None
                heading_level = 0
            elif kind in ('fence', 'code_block'):
                p = paragraph()
                p.paragraph_format.first_line_indent = Cm(0)
                p.paragraph_format.left_indent = Cm(.3)
                shade(p._p.get_or_add_pPr(), 'F1F4F2')
                run = p.add_run(token.content.rstrip('\n'))
                run.font.name = 'Consolas'
                run.font.size = Pt(10)
            elif kind == 'hr':
                p = paragraph()
                border = OxmlElement('w:pBdr')
                bottom = OxmlElement('w:bottom')
                bottom.set(qn('w:val'), 'single')
                bottom.set(qn('w:sz'), '4')
                bottom.set(qn('w:color'), 'CCD8D1')
                border.append(bottom)
                p._p.get_or_add_pPr().append(border)
            elif kind == 'table_open':
                # Column count is determined by the header row, not cell contents.
                index = next(i for i, t in enumerate(tokens) if t is token)
                end = next(i for i in range(index + 1, len(tokens)) if tokens[i].type == 'tr_close')
                columns = sum(t.type == 'th_open' for t in tokens[index:end])
                table = document.add_table(rows=0, cols=max(1, columns))
                if 'Table Grid' in document.styles:
                    table.style = 'Table Grid'
                table.autofit = False
                created.append(table._tbl)
            elif kind == 'tr_open':
                row = table.add_row()
                column = 0
            elif kind in ('th_open', 'td_open'):
                header = kind == 'th_open'
                cell = row.cells[column]
                column += 1
                current = cell.paragraphs[0]
                current.paragraph_format.first_line_indent = Cm(0)
                align = token.attrGet('style') or ''
                if 'center' in align:
                    current.alignment = 1
                elif 'right' in align:
                    current.alignment = 2
                if header:
                    shade(cell._tc.get_or_add_tcPr(), 'EAF0EC')
                    if column == 1:
                        row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
            elif kind in ('th_close', 'td_close'):
                current = None
                header = False
            elif kind == 'table_close':
                table = None
            elif kind == 'footnote_block_open':
                paragraph().add_run('注释').bold = True
            elif kind == 'footnote_open':
                pending_marker = '[' + str(token.meta['id'] + 1) + '] '
    if anchor is not None:
        for element in created:
            anchor._p.addprevious(element)
        anchor._p.getparent().remove(anchor._p)
