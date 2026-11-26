"""Rebuild the formal project report template; no application data required."""
from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

root = Path(__file__).resolve().parent.parent
document = Document()
section = document.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin, section.bottom_margin = Cm(2.6), Cm(2.4)
section.left_margin, section.right_margin = Cm(2.8), Cm(2.6)
section.footer_distance = Cm(1.2)
document.settings.odd_and_even_pages_header_footer = False

for style in document.styles:
    for border in list(style.element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)


def font(style_name, family, size, bold=False):
    style = document.styles[style_name]
    style.font.name = family
    fonts = style.element.get_or_add_rPr().rFonts
    for attribute in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        fonts.attrib.pop(qn('w:' + attribute), None)
    fonts.set(qn('w:eastAsia'), family)
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.font.italic = False
    return style.paragraph_format


body = font('Normal', 'FangSong', 14)
body.line_spacing = Pt(26)
body.first_line_indent = Pt(28)
body.space_after = Pt(0)
body.widow_control = True

title = font('Title', 'SimSun', 22, True)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
title.first_line_indent = Pt(0)
title.line_spacing = 1.3
title.space_after = Pt(12)
title.keep_with_next = True

subtitle = font('Subtitle', 'FangSong', 12)
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle.first_line_indent = Pt(0)
subtitle.space_after = Pt(18)
subtitle.keep_with_next = True

heading = font('Heading 1', 'SimHei', 14)
heading.first_line_indent = Pt(0)
heading.space_before = Pt(12)
heading.space_after = Pt(4)
heading.line_spacing = Pt(26)
heading.keep_with_next = True
heading.keep_together = True

footer_style = font('Footer', 'SimSun', 10.5)
footer_style.alignment = WD_ALIGN_PARAGRAPH.CENTER
footer_style.first_line_indent = Pt(0)
footer_style.line_spacing = 1
footer = section.footer.paragraphs[0]
footer.style = 'Footer'
footer.add_run('- ')
field = OxmlElement('w:fldSimple')
field.set(qn('w:instr'), 'PAGE')
footer._p.append(field)
footer.add_run(' -')

document.add_paragraph('{{ project }}\n项目简报', 'Title')
document.add_paragraph('{{ start }}至{{ end }}', 'Subtitle')
document.add_paragraph('{%p for section in sections %}')
document.add_heading('{{ section.heading }}', 1)
document.add_paragraph('{%p for paragraph in section.paragraphs %}')
document.add_paragraph('{{ paragraph.text }}')
document.add_paragraph('{%p endfor %}')
document.add_paragraph('{%p endfor %}')

(root / 'templates').mkdir(exist_ok=True)
document.save(root / 'templates' / 'brief.docx')
print('Created templates/brief.docx')
