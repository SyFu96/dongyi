import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const directory = path.resolve('target/chat-feedback-check');
await fs.mkdir(directory, { recursive: true });
for (const name of ['MarkdownContent', 'App']) {
  let source = await fs.readFile(`src/${name}.tsx`, 'utf8');
  if (name === 'App') source = source.replace('"./MarkdownContent"', '"./MarkdownContent.mjs"') + '\nexport { ChatView };';
  const compiled = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  await fs.writeFile(path.join(directory, `${name}.mjs`), compiled.outputText);
}
const { ChatView } = await import(pathToFileURL(path.join(directory, 'App.mjs')));
const props = {
  chat: [{ role: 'user', text: 'test question' }], draft: '', setDraft() {}, onSubmit() {},
  chatProvider: 'openai', modelNames: { local: 'local', cloud: 'deepseek-chat' }, cloudKeyOk: true, onProvider() {},
};
const render = (state) => renderToStaticMarkup(createElement(ChatView, { ...props, state }));
assert.match(render({ text: '', status: 'pending' }), /role="status"[^]*等待云端模型回复/);
assert.match(render({ text: '', status: 'failed', error: 'HTTP 503' }), /role="alert"[^]*HTTP 503[^]*重试/);
assert.match(render({ text: '', status: 'stopped' }), /重试追问/);
console.log('Chat feedback rendering: pending, HTTP error, and stopped retry passed.');
