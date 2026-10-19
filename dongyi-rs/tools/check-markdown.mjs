// Run after npm run build: node tools/check-markdown.mjs (project TypeScript/React).
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const out = path.resolve("target/markdown-check");
await fs.mkdir(out, { recursive: true });
const source = await fs.readFile("src/MarkdownContent.tsx", "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const modulePath = path.join(out, "MarkdownContent.mjs");
await fs.writeFile(modulePath, compiled);
const { MarkdownContent, repairTableSeparators } = await import(pathToFileURL(modulePath).href);
const render = text => renderToStaticMarkup(createElement(MarkdownContent, { text }));

const text = [
  "## 两类电池的区别", "", "**先看结论：** 应结合应用场景选择。", "",
  "| 类型 | 主要特点 | 常见用途 | 关注指标 | 说明 |",
  "| :--- | :--- | :--- | ---: | :--- |",
  "| LFP | 循环寿命较长 | 储能、部分电动车 | 循环次数 | 具体性能随产品和工况变化 |",
  "| NMC | 能量密度较高 | 部分电动车 | 能量密度 | 需考虑热管理条件 |", "",
  "### 阅读要点", "", "- 比较时保持测试条件一致。", "- 区分**材料特性**与产品表现。", "",
  "> 不应仅凭单一指标下结论。", "", "代码示例：", "", "```python",
  'print("a_long_identifier_for_testing_horizontal_scrolling_without_expanding_the_popup_window")', "```",
  "", "资料：[参考页面](https://example.com/reference)",
].join("\n");
const html = render(text);
assert.match(html, /<table\b/);
assert.match(html, /<thead>/);
assert.match(html, /<strong>先看结论/);
assert.match(html, /<pre><code/);
assert.match(html, /markdown-table-scroll/);
assert.match(html, /text-align:right/);
// Regression: a model omitted the dashes in the final delimiter cell.
const malformed = [
  "## 关键术语解释", "",
  "| 术语 | 全称/定义 | 所属领域 | 一句话定义 | 常见背景或误读 |",
  "| :--- | :--- | :--- | :--- | : |",
  "| **GitHub Mobile app** | GitHub for iOS / GitHub for Android | 软件开发 / 代码托管 | GitHub 的官方手机应用，用于查看代码、管理仓库和接收通知。 | 可用于安全验证，具体可用功能以服务页面为准。 |",
  "| **Sudo mode** | GitHub Sudo Mode | 账户安全 / 权限控制 | 在执行敏感操作之前再次确认用户身份。 | 这里的名称属于 GitHub 术语，不应直接当作操作系统的 sudo 命令。 |",
].join("\n");
const fixed = render(malformed);
assert.match(fixed, /<table data-wide="true">/);
assert.equal((fixed.match(/<td /g) ?? []).length, 10);
assert.match(fixed, /data-label="常见背景或误读"/);
assert.doesNotMatch(fixed, /\| :--- \|/);
for (const untouched of [
  "普通的 a | b 文本\n没有表格",
  "| A | B |\n| :--- | : | :--- |", // Header/delimiter widths disagree.
  "```md\n" + malformed + "\n```",
  "~~~~md\n```\n" + malformed + "\n~~~~",
  "    | A | B |\n    | :--- | : |",
]) assert.equal(repairTableSeparators(untouched), untouched);
const escaped = "| A \\| B | C | D |\n| :--- | : | ---: |\n| one | two | three |";
assert.match(render(escaped), /<table/);
// A partial stream must keep rendering until the table row/code fence is complete.
for (const partial of ["| 类型 | 特点 |\n| --- | --- |\n| LFP |", "```python\nprint("]) {
  assert.ok(render(partial).length > 0);
}
const unsafe = render('<script>alert(1)</script>\n\n[bad](javascript:alert%281%29)\n\n![remote](https://example.com/x.png)');
assert.doesNotMatch(unsafe, /<script|javascript:|<img/);
assert.match(unsafe, /remote/);

const cssFile = (await fs.readdir("dist/assets")).find(name => name.endsWith(".css"));
const css = await fs.readFile(path.join("dist/assets", cssFile), "utf8");
for (const theme of ["light", "dark"]) {
  await fs.writeFile(path.join(out, `${theme}.html`), `<!doctype html>
<html lang="zh-CN" class="${theme === "dark" ? "dark" : ""}"><meta charset="utf-8">
<style>${css}
body { background:var(--bg); padding:16px; width:100%; max-width:544px; box-sizing:border-box; }
  .answer { border:1px solid var(--line); background:var(--surface); padding:12px; font-size:14px; }
</style><body><div class="answer">${fixed}</div><pre id="metrics" hidden></pre>
<script>
const table = document.querySelector('.markdown-table-scroll');
document.querySelector('#metrics').textContent = JSON.stringify({
  pageFits: document.documentElement.scrollWidth <= innerWidth,
  tableScrolls: table.scrollWidth > table.clientWidth,
  tableWidth: table.clientWidth, contentWidth: table.scrollWidth,
  cellDisplay: getComputedStyle(document.querySelector('td')).display,
  firstLabel: getComputedStyle(document.querySelector('td'), '::before').content
});
</script></body></html>`);
}
console.log("PASS: malformed tables, cell labels, code/ordinary text preservation, partial streams, safe rendering.");
console.log(`Preview: ${out}`);
