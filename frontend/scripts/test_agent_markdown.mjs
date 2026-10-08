import assert from 'node:assert/strict';
import { mkdtemp, unlink, rmdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';

const directory = await mkdtemp(resolve('.agent-markdown-test-'));
const output = join(directory, 'component.mjs');
try {
  await build({ entryPoints: ['src/components/AgentMessageContent.jsx'], bundle: true,
    platform: 'node', format: 'esm', packages: 'external', outfile: output });
  const { AgentMessageContent } = await import(pathToFileURL(output).href);
  const render = (content, isUser = false) => renderToStaticMarkup(React.createElement(AgentMessageContent, { content, isUser }));
  const markdown = render('Đoạn một.\n\nĐoạn hai.\n\n- Camera **CAM_01**\n- Biển số 30A-12345\n\n> Nguồn: GUIDE.md — mục Camera — trang 2');
  assert.equal((markdown.match(/<p>/g) || []).length, 3);
  assert.match(markdown, /<ul>/);
  assert.match(markdown, /<li>Camera <strong>CAM_01<\/strong>/);
  assert.match(markdown, /30A-12345/);
  assert.match(markdown, /<blockquote>/);
  assert.match(markdown, /GUIDE.md/);
  const code = render('~~~json\n{"total":0}\n~~~');
  assert.match(code, /<pre><code class="language-json">/);
  const malicious = render('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![tracking](https://example.com/pixel.png)');
  assert.doesNotMatch(malicious, /<script|javascript:|<img|pixel.png/);
  const literal = render('**Literal user**\nCAM_01', true);
  assert.doesNotMatch(literal, /<strong>/);
  assert.match(literal, /\*\*Literal user\*\*/);
  assert.match(literal, /CAM_01/);
  console.log('Agent Markdown rendering: paragraphs, lists, citations, explicit JSON, safe HTML/links/images and literal user text PASS');
} finally {
  await unlink(output).catch(() => {});
  await rmdir(directory);
}
