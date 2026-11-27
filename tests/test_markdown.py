import io
from types import SimpleNamespace

from docx import Document
from docx.oxml.ns import qn

from backend import exports
from backend.markdown_export import append_markdown, safe_url
from .conftest import create_record
from .test_communications import data as communication_data
from .test_research import data as research_data
from .test_log_export import read_export


SAMPLE = '''## 本期进展

完成 **接口联调**，*待确认*，~~旧方案~~，`status=200`。
保留普通换行。

- [x] 字段核对
- [ ] 验收确认
  - 子项

3. 联调
4. 上线

> 需客户确认

```json
{"状态": "正常"}
```

| 项目 | 结果 |
| --- | ---: |
| **接口** | 通过 |

[查看说明](https://example.com/readme)

正文注释[^1]

[^1]: 保留注释
'''


def assert_formatted(document):
    text = '\n'.join(p.text for p in document.paragraphs)
    assert '接口联调' in text and '**接口联调**' not in text
    assert any(p.text == '本期进展' and p.style.name.startswith('Heading') for p in document.paragraphs)
    assert all(str(r.font.color.rgb) == '000000' for p in document.paragraphs if p.text == '本期进展' for r in p.runs)
    runs = [r for p in document.paragraphs for r in p.runs]
    assert any(r.text == '接口联调' and r.bold for r in runs)
    assert any(r.text == '待确认' and r.italic for r in runs)
    assert any(r.text == '旧方案' and r.font.strike for r in runs)
    assert any(r.text == 'status=200' and r.font.name == 'Consolas' for r in runs)
    assert '☑ 字段核对' in text and '☐ 验收确认' in text
    assert '3. 联调' in text and '4. 上线' in text and '• 子项' in text
    assert '正常' in text and '```' not in text
    assert len(document.tables) == 1
    assert [[c.text for c in row.cells] for row in document.tables[0].rows] == [['项目','结果'],['接口','通过']]
    assert any(rel.target_ref == 'https://example.com/readme' for rel in document.part.rels.values())
    assert '[1]' in text and '保留注释' in text


def test_markdown_word_formatting_and_plain_text_compatibility(tmp_path):
    doc = Document()
    append_markdown(doc, SAMPLE)
    target = tmp_path / 'markdown.docx'
    doc.save(target)
    assert_formatted(Document(target))
    plain = '首行\n  保留前导空格\n\n含 <XML> & 内容\t制表符\n最后一行'
    doc = Document()
    append_markdown(doc, plain)
    assert '\n'.join(p.text for p in doc.paragraphs) == plain
    doc = Document()
    append_markdown(doc, r'\*按原字显示\* &amp; 保留')
    assert doc.paragraphs[0].text == '*按原字显示* & 保留'


def test_export_html_and_links_are_not_executable():
    doc = Document()
    append_markdown(doc, '<script>alert(1)</script>\n\n[危险](javascript:alert%281%29)\n\n![图片](https://example.com/image.png)\n\n[本地](file:///secret)')
    assert '<script>alert(1)</script>' in '\n'.join(p.text for p in doc.paragraphs)
    targets = [r.target_ref for r in doc.part.rels.values() if r.is_external]
    assert targets == ['https://example.com/image.png']
    assert not doc.inline_shapes
    assert '图片：图片' in '\n'.join(p.text for p in doc.paragraphs)
    for bad in ['javascript:alert(1)', 'data:text/html,a', 'vbscript:x', 'file:///secret', '\\server\\share', 'java\nscript:x']:
        assert not safe_url(bad)


def test_brief_markdown_replaces_template_paragraph_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(exports, 'DATA', tmp_path)
    version = SimpleNamespace(id='markdown-version', number=1, snapshot={'project_name':'排版测试'}, content={
        'sections':[{'heading':'工作进展','paragraphs':[{'text':SAMPLE},{'text':'后一段'}]},
                    {'heading':'后续计划','paragraphs':[{'text':'下一节'}]}]})
    brief = SimpleNamespace(start='2026-11-01', end='2026-11-27')
    path = exports.export_brief(brief, version, 'docx')
    doc = Document(path)
    assert_formatted(doc)
    texts = [p.text for p in doc.paragraphs]
    assert texts.index('一、工作进展') < texts.index('本期进展') < texts.index('后一段') < texts.index('二、后续计划') < texts.index('下一节')
    assert 'PMMARKDOWN' not in doc.element.xml
    assert exports.export_brief(brief, version, 'docx').read_bytes() == path.read_bytes()


def test_saved_source_sync_and_excel_stay_markdown(client, setup_project):
    project, person, module = setup_project('Markdown全流程')
    response = create_record(client, project, 'communications', communication_data(person, summary='**沟通概况**', details=SAMPLE))
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['details'] == SAMPLE
    logs = client.get('/api/records/logs', params={'project_id':project['id']}).json()['items']
    assert logs[0]['content'] == '**沟通概况**' and logs[0]['details'] == SAMPLE
    word = client.get(f'/api/projects/{project["id"]}/communications/{record["id"]}/export/docx')
    assert word.status_code == 200, word.text[:200] if word.status_code != 200 else ''
    assert_formatted(Document(io.BytesIO(word.content)))
    _, _, rows = read_export(client.get(f'/api/projects/{project["id"]}/logs/export'))
    assert any(SAMPLE in values for values in rows.values())
    research = create_record(client, project, 'research', research_data(person, module, requirement=SAMPLE, solution='**处理思路**', notes='=HYPERLINK("https://example.com")'))
    assert research.status_code == 200, research.text
    _, _, rows = read_export(client.get(f'/api/projects/{project["id"]}/research/export'))
    assert any(SAMPLE in values and '**处理思路**' in values for values in rows.values())
    saved = client.get(f'/api/projects/{project["id"]}/records/communications/{record["id"]}').json()
    assert saved == record


def test_multiline_schema_preserves_markdown_whitespace_and_rejects_blank_required():
    import pytest
    from pydantic import ValidationError
    from backend.schemas import PersonInput, ProjectInput, ResearchInput, TaskInput, ExternalInterfaceInput, RemoveInput, AttachmentInput
    source = '    缩进代码\n\n**加粗**  \n下一行\n'
    assert PersonInput(name=' 姓名 ', notes=source).notes == source
    assert PersonInput(name=' 姓名 ', notes=source).name == '姓名'
    assert ProjectInput(name='项目', scope=source).scope == source
    assert TaskInput(name='任务', owner_id='person', plan_start='2026-11-01', plan_end='2026-11-02', planned_deliverable=source).planned_deliverable == source
    assert ExternalInterfaceInput(version=1, status='开发', development_notes=source).development_notes == source
    assert RemoveInput(version=1, reason=source).reason == source
    assert AttachmentInput(version=1, description=source).description == source
    with pytest.raises(ValidationError):
        ProjectInput(name='项目', scope='  \n  ')
    with pytest.raises(ValidationError):
        RemoveInput(version=1, reason='  ')
