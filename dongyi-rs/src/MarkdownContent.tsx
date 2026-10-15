import { memo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";

const plugins = [remarkGfm];
const components: Components = {
  table: ({ children }) => (
    <div className="markdown-table-scroll" role="region" aria-label="表格（可横向滚动）" tabIndex={0}>
      <table>{children}</table>
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
      <Markdown remarkPlugins={plugins} components={components} skipHtml>{text}</Markdown>
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
