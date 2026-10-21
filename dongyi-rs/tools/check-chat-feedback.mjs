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
  if (name === 'App') source = source.replace('"./MarkdownContent"', '"./MarkdownContent.mjs"') + '\nexport { ChatView, StatusMeta, ResultView, TranslationActions, PopupCard };';
  const compiled = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  await fs.writeFile(path.join(directory, `${name}.mjs`), compiled.outputText);
}
const { ChatView, StatusMeta, ResultView, TranslationActions } = await import(pathToFileURL(path.join(directory, 'App.mjs')));
const { SearchSources } = await import(pathToFileURL(path.join(directory, 'MarkdownContent.mjs')));
const props = {
  chat: [{ role: 'user', text: 'test question' }], draft: '', setDraft() {}, onSubmit() {},
  chatProvider: 'openai', modelNames: { local: 'local', cloud: 'deepseek-chat' }, cloudKeyOk: true, onProvider() {},
};
const render = (state) => renderToStaticMarkup(createElement(ChatView, { ...props, state }));
assert.match(render({ text: '', status: 'pending' }), /role="status"[^]*等待云端模型回复/);
assert.match(render({ text: '', status: 'failed', error: 'HTTP 503' }), /role="alert"[^]*HTTP 503[^]*重试/);
assert.match(render({ text: '', status: 'stopped' }), /重试追问/);
const sources = [{ title: 'Official <guide>', url: 'https://example.com/guide' }];
const chat = [
  { role: 'user', text: 'First question' },
  { role: 'assistant', text: 'First answer', sources },
  { role: 'user', text: 'Second question' },
  { role: 'assistant', text: 'Second answer', sources: [{ title: 'Research', url: 'https://example.org/paper' }] },
  { role: 'user', text: 'Local question' },
  { role: 'assistant', text: 'Local answer' },
];
const history = renderToStaticMarkup(createElement(ChatView, { ...props, chat, state: { text: 'Local answer', status: 'done' } }));
assert.match(history, /First answer[^]*Official &lt;guide&gt;[^]*Second answer[^]*https:\/\/example.org\/paper[^]*Local answer/);
assert.equal((history.match(/aria-label="搜索来源"/g) ?? []).length, 2);
assert.match(history, /target="_blank" rel="noopener noreferrer"/);
assert.equal(renderToStaticMarkup(createElement(SearchSources, { sources: [] })), '');
assert.equal(renderToStaticMarkup(createElement(SearchSources, { sources: [{ title: 'Unsafe', url: 'javascript:alert(1)' }] })), '');
for (const reason of ['length', 'eof']) {
  const state = { text: 'partial answer', status: 'done', truncated: true, finish_reason: reason };
  const partial = renderToStaticMarkup(createElement(ChatView, { ...props, state, chat: [
    { role: 'user', text: 'question' }, { role: 'assistant', ...state },
  ] }));
  assert.match(partial, /role="alert"[^]*回答未完成[^]*重试/);
  assert.match(partial, reason === 'length' ? /上下文或输出长度上限/ : /连接在输出结束前中断/);
  const footer = renderToStaticMarkup(createElement(StatusMeta, { kind: 'chat', state }));
  assert.match(footer, /回答未完成/);
  assert.doesNotMatch(footer, /已完成/);
}
console.log('Chat feedback rendering: pending, HTTP error, and stopped retry passed.');
console.log('Search sources: per-answer links, safe titles, local-only answer, and unsafe URL filtering passed.');
console.log('Incomplete answers: length/EOF warnings, retry, and truthful footer status passed.');

for (const mode of ['local', 'search', 'cloud']) {
  const html = renderToStaticMarkup(createElement(TranslationActions, { mode, busy: false, enabled: true }));
  assert.match(html, new RegExp(`<option value="${mode}" selected=""`));
  assert.match(html, /本地模型[^]*联网搜索[^]*云端模型[^]*重新翻译/);
}
const busyActions = renderToStaticMarkup(createElement(TranslationActions, { mode: 'search', busy: true, enabled: true }));
assert.match(busyActions, /<button disabled=""/);
assert.doesNotMatch(busyActions, /<select[^>]*\sdisabled=""/); // 生成中仍能换模式，后端取消旧请求。
const noSource = renderToStaticMarkup(createElement(TranslationActions, { mode: 'local', busy: false, enabled: false }));
assert.match(noSource, /<select[^>]*\sdisabled=""/);
assert.match(noSource, /<button disabled=""/);
const untranslated = renderToStaticMarkup(createElement(ResultView, { tab: '译文', state: {
  text: 'The original English text.', status: 'failed', error: '模型原样返回了英文，尚未完成翻译。',
} }));
assert.match(untranslated, /The original English text\.[^]*role="alert"[^]*模型原样返回了英文/);
const searched = renderToStaticMarkup(createElement(ResultView, { tab: '译文', mode: 'search', state: {
  text: '中文译文', status: 'done', sources,
} }));
assert.match(searched, /中文译文[^]*aria-label="搜索来源"/);
console.log('Retranslation controls: three modes, selection, busy switching, empty selection, visible errors, and sources passed.');
