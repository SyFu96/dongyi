import { memo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import type { Element, Nodes, Root } from "hast";

const plugins = [remarkGfm];
const htmlPlugins = [labelTableCells];

/** 只修复可明确识别的分隔行；原文、普通竖线文本和代码保持不变。 */
export function repairTableSeparators(text: string): string {
  const lines = text.split(/\r?\n/);
  const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "")
    .split(/(?<!\\)\|/).map((cell) => cell.trim());
  let fence: { marker: string; length: number } | undefined;
  for (let i = 0; i < lines.length; i++) {
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(lines[i]);
    if (fence) {
      if (marker && marker[1][0] === fence.marker && marker[1].length >= fence.length && !marker[2].trim()) fence = undefined;
      continue;
    }
    if (marker) { fence = { marker: marker[1][0], length: marker[1].length }; continue; }
    if (i === 0 || !lines[i].includes("|") || /^(?: {4}|\t)/.test(lines[i - 1]) || /^(?: {4}|\t)/.test(lines[i])) continue;
    const row = cells(lines[i]);
    if (row.length < 2 || row.length !== cells(lines[i - 1]).length
      || !row.every((cell) => /^:?-*:?$/.test(cell)) || !row.some((cell) => cell.includes("-"))
      || row.every((cell) => /^:?-+:?$/.test(cell))) continue;
    lines[i] = "| " + row.map((cell) => `${cell.startsWith(":") ? ":" : ""}---${cell.length > 1 && cell.endsWith(":") ? ":" : ""}`).join(" | ") + " |";
  }
  return lines.join("\n");
}

/** 为窄窗的纵向表格提供列名，继续由 Markdown 解析器处理单元格内容。 */
function labelTableCells() {
  const elements = (node: Root | Element, tag: string): Element[] =>
    [...node.children].filter((child): child is Element => child.type === "element" && child.tagName === tag);
  const content = (node: Nodes): string => "value" in node ? node.value : "children" in node ? node.children.map(content).join("") : "";
  return (tree: Root) => {
    const visit = (node: Root | Element) => {
      if (node.type === "element" && node.tagName === "table") {
        const head = elements(node, "thead")[0];
        const row = head && elements(head, "tr")[0];
        const labels = row ? elements(row, "th").map(content) : [];
        node.properties["data-wide"] = labels.length >= 3 ? "true" : "false";
        for (const body of elements(node, "tbody")) for (const row of elements(body, "tr")) {
          elements(row, "td").forEach((cell, index) => { cell.properties["data-label"] = labels[index] ?? ""; });
        }
      }
      for (const child of node.children) if (child.type === "element") visit(child);
    };
    visit(tree);
  };
}

const components: Components = {
  table: ({ children, node }) => (
    <div className="markdown-table-scroll" role="region" aria-label="表格内容" tabIndex={0}>
      <table data-wide={node?.properties["data-wide"]}>{children}</table>
    </div>
  ),
  a: ({ href, children }) => {
    if (href?.startsWith("#")) return <a href={href}>{children}</a>;
    if (!href || !/^https?:\/\//i.test(href)) return <span>{children}</span>;
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" onClick={(e) => {
        if (isTauri()) {
          e.preventDefault();
          // 资料链接交给系统浏览器，避免弹窗跳离应用。
          void openUrl(href).catch(() => {});
        }
      }}>
        {children}
      </a>
    );
  },
  // 回答中的外部图片只显示说明，避免自动发起图片请求。
  img: ({ alt }) => <span className="text-muted">[图片：{alt || "无说明"}]</span>,
};

/** 只渲染回答；原始文本仍用于复制与会话。历史气泡不随新 chunk 重解析。 */
export const MarkdownContent = memo(function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="markdown-content select-text">
      <Markdown remarkPlugins={plugins} rehypePlugins={htmlPlugins} components={components} skipHtml>
        {repairTableSeparators(text)}
      </Markdown>
    </div>
  );
});

export function CopyAnswer({ text }: { text: string }) {
  return (
    <button className="text-[11px] text-muted hover:text-text" title="复制原始 Markdown 文本"
      onClick={() => navigator.clipboard.writeText(text)}>
      复制回答 ↗
    </button>
  );
}
