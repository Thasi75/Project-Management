import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const directory=path.dirname(fileURLToPath(import.meta.url));
const output=path.join(directory,'.markdown-test.mjs');
const source=await fs.readFile(path.join(directory,'../src/Markdown.tsx'),'utf8');
await fs.writeFile(output,ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText);
try {
  const {MarkdownContent,MarkdownEditor,safeMarkdownUrl}=await import('./.markdown-test.mjs');
  const render=text=>renderToStaticMarkup(React.createElement(MarkdownContent,{text}));
  const html=render('## 标题\n\n**加粗**、*斜体*、~~删除~~、`代码`\n换行\n\n- [x] 已完成\n- [ ] 未完成\n\n| 字段 | 值 |\n| --- | --- |\n| 版本 | 1 |\n\n```js\nconst x = 1;\n```\n\n[链接](https://example.com)');
  for(const pattern of [/<h2>标题<\/h2>/,/<strong>加粗<\/strong>/,/<em>斜体<\/em>/,/<del>删除<\/del>/,/<code>代码<\/code>/,/<br\/>\n换行/,/type="checkbox"/,/<table>/,/<pre><code class="language-js">/,/rel="noopener noreferrer"/])assert.match(html,pattern);
  const unsafe=render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[危险](javascript:alert%281%29)\n\n[本地](file:///secret)\n\n![危险图片](data:image/svg+xml,bad)');
  assert.doesNotMatch(unsafe,/<script|<img|href="(?:javascript:|file:|data:)/i);
  assert.match(unsafe,/&lt;script&gt;/);
  for(const bad of ['javascript:alert(1)','vbscript:x','file:///secret','data:text/html,test','\\server\\share'])assert.equal(safeMarkdownUrl(bad),'');
  for(const safe of ['https://example.com','http://127.0.0.1:18765/api','mailto:test@example.com','#note','/api/attachments/id/download'])assert.equal(safeMarkdownUrl(safe),safe);
  const editable=renderToStaticMarkup(React.createElement(MarkdownEditor,{label:'必填',name:'required',required:true,value:'**原文**',onChange:()=>{}}));
  assert.match(editable,/<textarea[^>]*required=""[^>]*>\*\*原文\*\*<\/textarea>/);
  assert.match(editable,/aria-label="必填"/);
  const readonly=renderToStaticMarkup(React.createElement(MarkdownEditor,{label:'只读',disabled:true,value:'**只读内容**',onChange:()=>{}}));
  assert.match(readonly,/<textarea[^>]*disabled=""[^>]*hidden=""/);
  assert.match(readonly,/<strong>只读内容<\/strong>/);
  assert.doesNotMatch(readonly,/aria-label="加粗"/);
  console.log('PASS: Markdown rendering, GFM blocks, URL/HTML safety, source preservation, required and readonly editor semantics');
} finally {await fs.unlink(output);}
