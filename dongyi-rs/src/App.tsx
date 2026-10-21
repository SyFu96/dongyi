/**
 * 懂译前端入口：按 ?view= 分发视图（弹窗 / 设置 / 浮标）。
 * UI 按需求方提供的 ArtCraft Launcher 截图语言：纸白底 + 1px 细线栅格 +
 * 全直角 + 黑底白字激活 chip + 彩色编号块 + 等宽大写 micro-label + 无投影。
 * P3：流式渲染（rAF 批量 flush，等价 Python 版 30ms 批量 append）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { CopyAnswer, MarkdownContent, SearchSources, type SearchSource } from "./MarkdownContent";

type View = "popup" | "settings" | "icon";

function currentView(): View {
  const loc = window.location;
  if ((loc.hash + loc.search).includes("icon")) return "icon";
  return (loc.hash + loc.search).includes("settings") ? "settings" : "popup";
}

export interface OpenPayload {
  text: string;
  truncated: boolean;
  source: "uia" | "clipboard" | "input";
  kind: "translate" | "explain" | "chat" | "input";
  error?: string;
}

type LlmMsg =
  | { type: "pending"; kind: string; req_id: number }
  | { type: "chunk"; kind: string; delta: string; req_id: number }
  | { type: "finished"; kind: string; full_text: string; secs: number; truncated: boolean; finish_reason?: string; req_id: number; sources?: SearchSource[] }
  | { type: "failed"; kind: string; error: string; req_id: number; full_text?: string };

type TranslationMode = "local" | "search" | "cloud";

type Status = "idle" | "searching" | "pending" | "done" | "failed" | "stopped";
interface ResultState {
  text: string;
  sources?: SearchSource[];
  status: Status;
  error?: string;
  secs?: number;
  retryable?: boolean;
  truncated?: boolean;
  finish_reason?: string;
}

interface ChatMessage { role: string; text: string; sources?: SearchSource[]; truncated?: boolean; finish_reason?: string }

const TABS = [
  { key: "translate", label: "译文", num: "01", color: "var(--color-accent)" },
  { key: "explain", label: "解释", num: "02", color: "var(--color-c02)" },
  { key: "chat", label: "追问", num: "03", color: "var(--color-c03)" },
  { key: "input", label: "输入翻译", num: "04", color: "var(--color-c04)" },
] as const;

type TabKey = (typeof TABS)[number]["key"];
const EMPTY: ResultState = { text: "", status: "idle" };

/** P5：领域（学科）下拉数据——与后端 domains::dedupe **共用确定性规则**
 *  （Gate P5-m2）：id 形态 [A-Za-z0-9_-]{1,64}、enabled 默认 true、
 *  同 lowercase 组按 id 字节序取第一个启用的；组输出按 id 排序。 */
function computeDomains(map: Record<string, { name?: string; enabled?: boolean }> | undefined) {
  if (!map) return [] as { id: string; label: string }[];
  const idOk = (id: string) =>
    id.length >= 1 && id.length <= 64 && /^[A-Za-z0-9_-]+$/.test(id);
  const groups = new Map<string, { id: string; label: string; enabled: boolean }[]>();
  for (const [id, dom] of Object.entries(map)) {
    if (!idOk(id) || !dom || typeof dom !== "object" || (dom as any) === null) continue;
    const entry = { id, label: dom.name?.trim() ? dom.name.trim() : id, enabled: dom.enabled !== false };
    const key = id.toLowerCase();
    const list = groups.get(key) ?? [];
    list.push(entry);
    groups.set(key, list);
  }
  const out: { id: string; label: string }[] = [];
  const idCmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0); // 合法 id 全 ASCII：与后端字节序一致
  for (const list of groups.values()) {
    list.sort((a, b) => idCmp(a.id, b.id));
    const keeper = list.find((d) => d.enabled) ?? list[0];
    if (keeper.enabled) out.push({ id: keeper.id, label: keeper.label });
  }
  out.sort((a, b) => idCmp(a.id, b.id));
  return out;
}

/** 目标语向清单（Python popup.TARGET_LANGUAGES 原值集） */const TARGET_LANGUAGES: [string, string][] = [
  ["自动（中→英 / 其他→中）", "auto"],
  ["中文", "中文"],
  ["英文", "英文"],
  ["繁体中文", "繁体中文"],
  ["日文", "日文"],
  ["韩文", "韩文"],
  ["法文", "法语"],
  ["德文", "德语"],
  ["西班牙文", "西班牙语"],
  ["俄文", "俄语"],
  ["意大利文", "意大利语"],
  ["葡萄牙文", "葡萄牙语"],
  ["阿拉伯文", "阿拉伯语"],
];

// --------------------------------------------------------------- 主题

type ThemeMode = "auto" | "light" | "dark";

/**
 * 主题跟随系统（P4）：class "dark" 由三处驱动——
 * 1) config.theme（auto/light/dark，Python 遗留字段，旧值 "dark" 直接可用）
 * 2) auto = matchMedia(prefers-color-scheme)（WebView2 随 Windows 应用主题）
 * 3) 设置窗保存后后端广播 config:updated{theme}，三个窗口即时切换。
 */
function useThemeSync() {
  useEffect(() => {
    // N7：统一 apply 入口 + mql 句柄集中管理（切换 light/dark 前先摘旧监听）；
    // 初始 get_config 与广播事件并行 → 广播已处理过主题时丢弃迟到的初始读取
    let disposed = false;
    let mql: MediaQueryList | null = null;
    let onMediaChange: (() => void) | null = null;
    let sawBroadcast = false;
    const normalize = (t: unknown): ThemeMode =>
      (typeof t === "string" && ["auto", "light", "dark"].includes(t)
        ? t
        : "auto") as ThemeMode;
    const apply = (mode: ThemeMode) => {
      const addDark =
        mode === "dark" ||
        (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
      document.documentElement.classList.toggle("dark", addDark);
    };
    const clearAutoListener = () => {
      if (mql && onMediaChange) mql.removeEventListener("change", onMediaChange);
      mql = null;
      onMediaChange = null;
    };
    const setMode = (mode: ThemeMode) => {
      clearAutoListener();
      apply(mode);
      if (mode === "auto") {
        mql = window.matchMedia("(prefers-color-scheme: dark)");
        onMediaChange = () => apply("auto");
        mql.addEventListener("change", onMediaChange);
      }
    };
    invoke<{ theme: string }>("get_config")
      .then((cfg) => {
        if (disposed || sawBroadcast) return; // 迟到的初始读取不覆盖广播新值
        setMode(normalize(cfg.theme));
      })
      .catch(() => {});
    let unlisten: (() => void) | null = null;
    listen<{ theme?: string }>("config:updated", (e) => {
      if (typeof e.payload.theme !== "string") return;
      sawBroadcast = true;
      setMode(normalize(e.payload.theme)); // 清旧监听→应用→按需重挂 auto
    }).then((off) => {
      if (disposed) off();
      else unlisten = off;
    });
    return () => {
      disposed = true;
      clearAutoListener();
      unlisten?.();
    };
  }, []);
}

export default function App() {
  const view = currentView();
  useThemeSync();
  return view === "settings" ? <SettingsView /> : view === "icon" ? <IconView /> : <PopupView />;
}

// --------------------------------------------------------------- 浮标

function IconView() {
  return (
    <button
      onClick={() => invoke("icon_clicked")}
      className="h-screen w-screen flex items-center justify-center !outline-none"
    >
      <span className="w-5 h-5 bg-[#17181a] text-white text-[11px] font-bold flex items-center justify-center border border-black/20 hover:bg-white hover:text-black transition-colors select-none">
        译
      </span>
    </button>
  );
}

// --------------------------------------------------------------- 弹窗

function PopupView() {
  const [source, setSource] = useState("");
  const [kind, setKind] = useState<TabKey>("translate");
  const [truncated, setTruncated] = useState(false);
  const [provider, setProvider] = useState("…");
  const [results, setResults] = useState<Partial<Record<TabKey, ResultState>>>({});
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [pinned, setPinned] = useState(false);
  // 输入翻译的后端选择与模型名（用户需求：本地默认，可在输入处随时切换）
  const [inputProvider, setInputProvider] = useState<"ollama" | "openai">("ollama");
  const [chatProvider, setChatProvider] = useState<"ollama" | "openai">("ollama");
  const [modelNames, setModelNames] = useState<{ local: string; cloud: string }>({ local: "", cloud: "" });
  const [cloudKeyOk, setCloudKeyOk] = useState(false);
  // P5：领域（学科）下拉与切换反馈
  const [domains, setDomains] = useState<{ id: string; label: string }[]>([]);
  const [activeDomain, setActiveDomain] = useState("");
  const [translationMode, setTranslationMode] = useState<TranslationMode>("local");
  const [tmMsg, setTmMsg] = useState("");

  // chunk 缓冲 + rAF 批刷（30ms 语义等价 Python 版批量 append）
  const buffers = useRef<Partial<Record<TabKey, string>>>({});
  // req_id 门控（Gate P3-B3）：只接受当前绑定请求的 chunk/终态，旧会话迟到流直接丢
  const activeReq = useRef<Partial<Record<TabKey, number>>>({});
  const rafRef = useRef<number | null>(null);
  const chatStreaming = useRef(false);

  // N1：配置加载统一入口（mount / popup:open / 整份保存广播 共用）
  // Gate P5：加请求票据——快速连续更新时迟到的 get_config 响应不回退显示
  const cfgPullId = useRef(0);
  const loadCfg = useCallback(() => {
    const id = ++cfgPullId.current;
    type CfgT = {
      provider: string;
      model: string;
      cloud: { base_url?: string; model?: string; api_key: string };
      kind_providers: Record<string, string>;
      offline?: boolean;
      domains?: Record<string, { name?: string; enabled?: boolean }>;
      active_domain?: string;
    };
    invoke<CfgT>("get_config")
      .then((cfg) => {
        if (cfgPullId.current !== id) return; // 迟到响应丢弃
        setProvider(cfg.provider);
        setModelNames({
          local: cfg.model || "",
          cloud: cfg.cloud?.model || "",
        });
        setCloudKeyOk((cfg.cloud?.api_key ?? "").trim().length > 0);
        const ov = (cfg.kind_providers?.input ?? "") as string;
        setInputProvider(ov === "openai" || (ov === "" && cfg.provider === "openai") ? "openai" : "ollama");
        const cv = (cfg.kind_providers?.chat ?? "") as string;
        setChatProvider(cv === "openai" || (cv === "" && cfg.provider === "openai") ? "openai" : "ollama");
        setDomains(computeDomains(cfg.domains));
        setActiveDomain(String(cfg.active_domain ?? ""));
      })
      .catch(() => setProvider("IPC 失败"));
  }, []);
  useEffect(loadCfg, [loadCfg]);
  // 监听器 useEffect（依赖 []）内要调最新 loadCfg → 闭包外的稳定引用
  const loadCfgRef = useRef(loadCfg);
  loadCfgRef.current = loadCfg;

  // 监听器生命周期（React StrictMode 双挂载下 async listen 会泄漏——
  // 用户实测"解释结巴"根因）：disposed 标志 + 已解析句柄统一注销
    // 监听器生命周期（React StrictMode 双挂载下 async listen 会泄漏——
  // 用户实测"解释结巴"根因）：disposed 标志 + 已解析句柄统一注销。
  // 事件按 req_id 门控（Gate P3-B3）：旧会话迟到流直接丢弃。
  useEffect(() => {
    const offs: Array<() => void> = [];
    let disposed = false;
    const reg = <T,>(ev: string, h: (p: T) => void) =>
      listen<T>(ev, (e) => h(e.payload)).then((off) => {
        if (disposed) off();
        else offs.push(off);
      });

    const at = (k: TabKey) => activeReq.current[k];

    const scheduleFlush = () => {
      if (rafRef.current == null) {
        rafRef.current = requestAnimationFrame(() => {
          rafRef.current = null;
          const bs = buffers.current;
          buffers.current = {};
          // flush 逐 kind 复核：终态已先落地则丢弃遗留缓冲（防"甲甲"重复）
          setResults((prev) => {
            const next = { ...prev };
            for (const [kind, buf] of Object.entries(bs) as [TabKey, string][]) {
              if (activeReq.current[kind] == null) continue;
              const base = next[kind] ?? EMPTY;
              if (base.status !== "pending") continue;
              next[kind] = { ...base, text: base.text + buf, status: "pending" };
            }
            return next;
          });
        });
      }
    };

    reg<OpenPayload>("popup:open", (p) => {
      setTranslationMode("local");
      setSource(p.text);
      setKind(p.kind);
      setTruncated(p.truncated);
      setResults(p.error ? { [p.kind]: { text: "", status: "failed", error: p.error, retryable: false } } : {});
      setChat([]);
      chatStreaming.current = false;
      buffers.current = {};
      activeReq.current = {};
      // pinned 不在此清：置顶跨会话保持（Python open_at 语义），
      // 后端 open_popup 会 emit popup:pin 回放真实状态
      // 会话开启时重拉配置（实测反馈：用户改 config.json 后不再需要重启）
      loadCfgRef.current();
    });

    // LLM 事件流（req_id 绑定后 chunk/终态只认当前请求；
    // req_id=0 为系统级广播如 key 未配置提示，免检直达）
    reg<LlmMsg>("llm:event", (m) => {
      const k = m.kind as TabKey;
      if (m.type === "pending") {
        if (k === "chat") chatStreaming.current = false;
        activeReq.current[k] = m.req_id;
        buffers.current[k] = "";
        setResults((p) => ({ ...p, [k]: { text: "", status: "pending" } }));
      } else if (m.type === "chunk") {
        if (m.req_id !== 0 && at(k) !== m.req_id) return; // 迟到/旧会话 chunk 丢弃
        if (k === "chat") {
          // 追问：assistant 气泡流式增长
          if (!chatStreaming.current) {
            chatStreaming.current = true;
            setChat((c) => [...c, { role: "assistant", text: m.delta }]);
          } else {
            setChat((c) => {
              const copy = [...c];
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant") {
                copy[copy.length - 1] = { ...last, text: last.text + m.delta };
              }
              return copy;
            });
          }
        } else {
          buffers.current[k] = (buffers.current[k] ?? "") + m.delta;
          scheduleFlush();
        }
      } else if (m.type === "finished") {
        if (at(k) !== m.req_id) return; // 终态只认当前请求
        chatStreaming.current = false;
        activeReq.current[k] = undefined;
        buffers.current[k] = ""; // 终态先于 rAF：清缓冲防重复
        if (k === "chat") {
          setChat((c) => {
            const copy = [...c];
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant") {
              copy[copy.length - 1] = { ...last, text: m.full_text, sources: m.sources ?? [], truncated: m.truncated, finish_reason: m.finish_reason };
            }
            return copy;
          });
          // 追问完成也回填 results.chat（原缺陷：完成后仍显示请求中）
          setResults((p) => ({ ...p, [k]: { text: m.full_text, sources: m.sources ?? [], status: "done", secs: m.secs, truncated: m.truncated, finish_reason: m.finish_reason } }));
        } else {
          setResults((p) => ({ ...p, [k]: { text: m.full_text, sources: m.sources ?? [], status: "done", secs: m.secs, truncated: m.truncated, finish_reason: m.finish_reason } }));
        }
      } else if (m.type === "failed") {
        // req_id=0 = 系统级提示（如 key 未配置）免检；active 未绑定（闸门拒绝，
        // 没有经过 pending）也放行；两者都不拦，只有旧流 late failed 才丢
        const bound = at(k);
        if (m.req_id !== 0 && bound != null && bound !== m.req_id) return;
        chatStreaming.current = false;
        if (m.req_id !== 0) activeReq.current[k] = undefined;
        buffers.current[k] = "";
        setResults((p) => ({
          ...p,
          [k]: { ...(p[k] ?? EMPTY), ...(m.full_text === undefined ? {} : { text: m.full_text }), status: "failed", error: m.error },
        }));
      }
    });

    reg<{ kind: string }>("llm:stopped", (p) => {
      const k = p.kind as TabKey;
      if (k === "chat") chatStreaming.current = false;
      activeReq.current[k] = undefined;
      buffers.current[k] = "";
      setResults((prev) => ({
        ...prev,
        [k]: { ...(prev[k] ?? EMPTY), status: "stopped" },
      }));
    });

    reg<{ kind: string; idle?: boolean }>("llm:reset", (p) => {
      const k = p.kind as TabKey;
      if (k === "chat") {
        chatStreaming.current = false;
        // 重试替换上一段未完成回答，保留原问题与更早的对话。
        setChat((c) => c[c.length - 1]?.role === "assistant" ? c.slice(0, -1) : c);
      }
      buffers.current[k] = "";
      activeReq.current[k] = undefined; // Gate 复审 RR4：reset 清绑定
      setResults((prev) => ({ ...prev, [k]: { text: "", status: p.idle ? "idle" : "pending" } }));
    });

    reg<{ mode: TranslationMode }>("translation:mode", (p) => setTranslationMode(p.mode));

    // popup:tab：RR4 轻量切标签（输入热键在弹窗已开时），不清会话/结果
    reg<{ kind: string }>("popup:tab", (p) => {
      const k = p.kind as TabKey;
      setKind(k);
      invoke("activate_tab", { kind: k });
    });

    reg<{ on: boolean }>("popup:pin", (p) => {
      setPinned(p.on);
    });

    reg<{ kind: string }>("llm:searching", (p) => {
      const k = p.kind as TabKey;
      setResults((prev) => ({ ...prev, [k]: { text: "", status: "searching" } }));
    });

    // P5：存为记忆反馈（footer 短提示）
    reg<{ ok: boolean; msg: string }>("tm:saved", (p) => {
      setTmMsg(p.msg);
      window.setTimeout(() => setTmMsg(""), 3000);
    });

    reg<{ kind: string; provider: string }>("config:updated", (p) => {
      if (p.kind === "chat" || p.kind === "input") {
        // N1：后端恒发「生效」provider（ollama|openai）——发布与回滚都由
        // 后端 provider_for 计算，前端不再解析 ""=跟随全局（闭包捕获旧值会误判）
        const next: "ollama" | "openai" = p.provider === "openai" ? "openai" : "ollama";
        if (p.kind === "chat") setChatProvider(next);
        if (p.kind === "input") setInputProvider(next);
      } else {
        // kind="" = 设置窗整份/差异保存广播：重拉全量配置，
        // 同步全局 provider / 模型名 / key 状态 / kind chips（N1 缺口）
        loadCfgRef.current();
      }
    });
    return () => {
      disposed = true;
      for (const off of offs) off();
    };
  }, []);

  const active = TABS.find((t) => t.key === kind)?.label ?? "译文";
  const [activeLabel, setActiveLabel] = useState(active);
  useEffect(() => setActiveLabel(active), [active]);

  const switchTab = useCallback((tab: (typeof TABS)[number]) => {
    setActiveLabel(tab.label);
    invoke("activate_tab", { kind: tab.key }); // 后端惰性分发（解释等）
  }, []);

  const askChat = useCallback(() => {
    const q = chatDraft.trim();
    if (!q) return;
    setChatDraft("");
    setChat((c) => [...c, { role: "user", text: q }]);
    chatStreaming.current = false;
    invoke("chat_question", {
      question: q,
      translation: results["translate"]?.text ?? "",
      explanation: results["explain"]?.text ?? "",
    });
  }, [chatDraft, results]);

  const askInput = useCallback(
    (text: string, target: string) => {
      chatStreaming.current = false;
      // target="auto" 传 null → 后端走自动中英互译 prompt
      invoke("input_translate", { text, target: target === "auto" ? null : target });
    },
    [],
  );

  const metaKind = ((): TabKey => {
    switch (activeLabel) {
      case "解释": return "explain";
      case "追问": return "chat";
      case "输入翻译": return "input";
      default: return "translate";
    }
  })();

  return (
    <PopupCard
      source={source}
      truncated={truncated}
      provider={provider}
      results={results}
      chat={chat}
      activeTab={activeLabel}
      onSwitchTab={switchTab}
      onAskChat={askChat}
      chatDraft={chatDraft}
      onChatDraft={setChatDraft}
      metaKind={metaKind}
      onAskInput={askInput}
      pinned={pinned}
      onTogglePin={() => invoke("set_popup_pinned", { on: !pinned })}
      inputProvider={inputProvider}
      chatProvider={chatProvider}
      modelNames={modelNames}
      cloudKeyOk={cloudKeyOk}
      onKindProvider={(kind, p) => invoke("set_kind_provider", { kind, provider: p })}
      domains={domains}
      activeDomain={activeDomain}
      translationMode={translationMode}
      onSetDomain={(id) => invoke("set_domain", { id })}
      onTmSave={(kind, translation) => invoke("tm_save", { kind, translation })}
      tmMsg={tmMsg}
    />
  );
}

/** ArtCraft Launcher 风：纸白底、1px 栅格分割、全直角、无投影。 */
function PopupCard({
  source,
  truncated,
  provider,
  results,
  chat,
  activeTab,
  onSwitchTab,
  onAskChat,
  chatDraft,
  onChatDraft,
  metaKind,
  onAskInput,
  pinned,
  onTogglePin,
  inputProvider,
  chatProvider,
  modelNames,
  cloudKeyOk,
  onKindProvider,
  domains,
  activeDomain,
  translationMode,
  onSetDomain,
  onTmSave,
  tmMsg,
}: {
  source: string;
  truncated: boolean;
  provider: string;
  results: Partial<Record<TabKey, ResultState>>;
  chat: ChatMessage[];
  activeTab: string;
  onSwitchTab: (tab: (typeof TABS)[number]) => void;
  onAskChat: () => void;
  chatDraft: string;
  onChatDraft: (v: string) => void;
  metaKind: TabKey;
  onAskInput: (text: string, target: string) => void;
  pinned: boolean;
  onTogglePin: () => void;
  inputProvider: "ollama" | "openai";
  chatProvider: "ollama" | "openai";
  modelNames: { local: string; cloud: string };
  cloudKeyOk: boolean;
  onKindProvider: (kind: string, p: "ollama" | "openai") => void;
  domains: { id: string; label: string }[];
  activeDomain: string;
  translationMode: TranslationMode;
  onSetDomain: (id: string) => void;
  onTmSave: (kind: string, translation: string) => void;
  tmMsg: string;
}) {
  // footer 按当前 kind 显示 provider/模型（Gate 实测反馈：此前恒显全局 ollama）
  const kindMeta = (k: TabKey): { whom: string; name: string } => {
    const p =
      k === "translate" ? (translationMode === "cloud" ? "openai" : "ollama") : k === "input" ? inputProvider : k === "chat" ? chatProvider : (provider === "openai" ? "openai" : "ollama");
    return {
      whom: p === "ollama" ? "本地" : "云端",
      name: p === "ollama" ? modelNames.local : modelNames.cloud,
    };
  };
  const meta = results[metaKind] ?? EMPTY;
  // P5：存记忆校对框（原文只读取自配对快照，译文可编辑——Python TmEditDialog 同款流程）
  const [tmEdit, setTmEdit] = useState<string | null>(null);
  return (
    <div className="h-screen flex flex-col bg-bg text-text overflow-hidden relative">
      {/* 标题栏（Launcher 顶栏语言） */}
      <header data-tauri-drag-region className="flex items-stretch h-10 shrink-0 border-b border-line">
        <div data-tauri-drag-region className="flex items-center gap-2 px-3 cursor-default">
          <span className="text-[13px] font-extrabold tracking-wide">懂译</span>
          <span className="micro-label text-muted">Translator</span>
        </div>
        <div className="flex-1" data-tauri-drag-region />
        <div className="flex items-stretch border-l border-line">
          <PinAction pinned={pinned} onToggle={onTogglePin} />
          <TopAction label="关闭 ✕" onClick={() => invoke("hide_popup")} />
        </div>
      </header>

      {/* 标签行：编号色块 + 黑底白字激活 chip；点击通知后端（惰性分发） */}
      <nav className="flex items-stretch shrink-0 border-b border-line">
        {TABS.map((t) => {
          const isActive = activeTab === t.label;
          return (
            <button
              key={t.key}
              onClick={() => onSwitchTab(t)}
              className={`flex items-center gap-2 px-3 h-9 text-[12px] font-medium border-r border-line transition-colors ${
                isActive ? "bg-chip-bg text-chip-text" : "text-muted hover:bg-surface"
              }`}
            >
              <span
                className="num-chip w-4 h-4 flex items-center justify-center"
                style={{ background: t.color, color: "#fff" }}
              >
                {t.num}
              </span>
              {t.label}
            </button>
          );
        })}
        {/* 切领域后，当前译文/解释自动重算；隐藏页签下次打开时重算。 */}
        <div className="flex-1 flex items-center justify-end gap-1 px-2">
          {tmMsg && <span className="text-[11px] text-ok normal-case tracking-normal mr-2">{tmMsg}</span>}
          <span className="micro-label text-muted hidden sm:block">学科</span>
          <select
            value={activeDomain || "通用"}
            onChange={(e) => onSetDomain(e.target.value === "通用" ? "" : e.target.value)}
            className="textSel normal-case tracking-normal"
          >
            <option value="通用">通用</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </div>
      </nav>

      {/* SOURCE */}
      <section className="shrink-0 border-b border-line">
        <div className="flex items-center justify-between px-3 pt-2 pb-1">
          <span className="micro-label text-muted">Source / 原文</span>
          <button
            className="micro-label text-muted hover:text-text transition-colors"
            onClick={() => navigator.clipboard.writeText(source)}
          >
            复制原文 ↗
          </button>
        </div>
        <p className="px-3 pb-2 text-[13px] leading-relaxed whitespace-pre-wrap select-text max-h-[25vh] overflow-y-auto">
          {source}
        </p>
        {truncated && <div className="px-3 pb-2 text-[11px] text-muted">原文过长，已截断</div>}
      </section>

      {/* RESULT（按 tab 分视图；流式文本实时增长） */}
      <main className="flex-1 overflow-y-auto min-h-0">
        {activeTab === "输入翻译" ? (
          <InputView
            state={results["input"] ?? EMPTY}
            onSubmit={onAskInput}
            inputProvider={inputProvider}
            modelNames={modelNames}
            cloudKeyOk={cloudKeyOk}
            onProvider={(p) => onKindProvider("input", p)}
          />
        ) : activeTab === "追问" ? (
          <ChatView
            chat={chat}
            state={results.chat ?? EMPTY}
            draft={chatDraft}
            setDraft={onChatDraft}
            onSubmit={onAskChat}
            chatProvider={chatProvider}
            modelNames={modelNames}
            cloudKeyOk={cloudKeyOk}
            onProvider={(p) => onKindProvider("chat", p)}
          />
        ) : (
          <ResultView
            tab={activeTab}
            state={results[activeTab === "解释" ? "explain" : "translate"] ?? EMPTY}
            mode={translationMode}
            canTranslate={!!source.trim()}
          />
        )}
      </main>

      {/* footer 状态行：学科 + provider/模型（当前激活 kind）+ 状态 + 存记忆 */}
      <footer className="micro-label text-muted flex items-center gap-2 h-8 px-3 shrink-0 border-t border-line overflow-hidden whitespace-nowrap">
        <span className="normal-case tracking-normal shrink-0">
          {domains.find((d) => d.id === activeDomain)?.label ?? "通用"}
        </span>
        <span className="opacity-50">·</span>
        <span className="normal-case tracking-normal truncate min-w-0">
          {kindMeta(metaKind).whom} · {kindMeta(metaKind).name}
        </span>
        <span className="shrink-0">
          <StatusMeta kind={metaKind} state={meta} />
        </span>
        {(metaKind === "translate" || metaKind === "input") && meta.text && (
          <button
            onClick={() => setTmEdit(meta.text)}
            className="px-1.5 h-5 text-[11px] border border-line text-muted hover:text-text hover:border-border-strong transition-colors normal-case tracking-normal whitespace-nowrap shrink-0"
          >
            存记忆
          </button>
        )}
        {tmMsg && (
          <span className="text-ok normal-case tracking-normal shrink-0">{tmMsg}</span>
        )}
      </footer>

      {/* P5：存记忆校对层（原文只读 + 译文可编辑；无投影/直角/细线，同 Launcher 语言） */}
      {tmEdit !== null && (
        <div className="absolute inset-0 bg-bg/85 flex items-center justify-center p-3 z-10">
          <div className="w-full max-h-full border border-border-strong bg-bg-elevated flex flex-col">
            <div className="micro-label text-muted px-3 py-2 border-b border-line flex items-center justify-between">
              <span>存为记忆 · 校对译文</span>
              <span className="normal-case tracking-normal text-muted">
                {domains.find((d) => d.id === activeDomain)?.label ?? "通用"}
              </span>
            </div>
            <div className="px-3 py-2 text-[11px] text-muted border-b border-line max-h-24 overflow-y-auto select-text whitespace-pre-wrap">
              {source}
            </div>
            <textarea
              className="ti m-3 h-28 resize-none"
              value={tmEdit}
              onChange={(e) => setTmEdit(e.target.value)}
              autoFocus
            />
            <div className="flex justify-end gap-2 px-3 pb-3">
              <button
                onClick={() => setTmEdit(null)}
                className="px-2.5 h-7 text-[12px] border border-line text-muted hover:text-text hover:border-border-strong"
              >
                取消
              </button>
              <button
                onClick={() => {
                  if (tmEdit.trim()) onTmSave(metaKind, tmEdit);
                  setTmEdit(null);
                }}
                className="px-2.5 h-7 text-[12px] font-semibold bg-chip-bg text-chip-text"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 结果区（译文/解释主体） */
function ResultView({ tab, state, mode = "local", canTranslate = true }: { tab: string; state: ResultState; mode?: TranslationMode; canTranslate?: boolean }) {
  return (
    <div className="px-3 pt-2 pb-3">
      {tab === "译文" && <TranslationActions mode={mode} busy={state.status === "pending" || state.status === "searching"} enabled={canTranslate} />}
      {tab === "解释" && state.text && (
        <div className="flex justify-end mb-2"><CopyAnswer text={state.text} /></div>
      )}
      <div className="text-sm leading-relaxed select-text min-h-[3rem]">
        {state.status === "searching" ? <span className="text-muted">正在搜索术语与背景资料…</span> : state.status === "idle" || state.status === "pending" && state.text === "" ? (
          <span className="text-muted">{tab === "译文" ? "翻译请求中…" : "解释请求中…"}</span>
        ) : (
          state.text ? (
            tab === "解释" ? <MarkdownContent text={state.text} /> : <div className="whitespace-pre-wrap">{state.text}</div>
          ) : <span className="text-muted">…</span>
        )}
      </div>
      {state.status === "failed" && <div role="alert" className="mt-2 border border-line p-2 text-[12px] text-error leading-relaxed">{state.error ?? "翻译失败，请重试。"}</div>}
      {state.text && <SearchSources sources={state.sources} />}
      {state.truncated && <IncompleteAnswer kind={tab === "解释" ? "explain" : "translate"} reason={state.finish_reason} />}
    </div>
  );
}

/** 切换方式立即重译；领域变化由后端沿用本次方式，避免另起一份原文。 */
function TranslationActions({ mode, busy, enabled }: { mode: TranslationMode; busy: boolean; enabled: boolean }) {
  return (
    <div className="sticky top-0 z-[1] bg-bg flex flex-wrap items-center justify-end gap-2 pb-2 mb-2 border-b border-line">
      <select aria-label="翻译方式" value={mode} disabled={!enabled}
        title="切换方式会立即重译当前原文；云端模型可能计费"
        className="bg-bg-elevated border border-line px-2 h-7 text-[12px] min-w-0 disabled:opacity-40"
        onChange={(e) => invoke("translate_again", { mode: e.target.value })}>
        <option value="local">本地模型</option>
        <option value="search">联网搜索 · 本地模型</option>
        <option value="cloud">联网翻译 · 云端模型</option>
      </select>
      <button disabled={!enabled || busy} onClick={() => invoke("translate_again", { mode })}
        className="border border-line px-2 h-7 text-[12px] hover:border-border-strong disabled:opacity-40">
        重新翻译
      </button>
    </div>
  );
}

/** 状态 meta：请求中…/完成 3.3s/失败+重试/已停止（Python mark_pending 等） */
function StatusMeta({ kind, state }: { kind: TabKey; state: ResultState }) {
  if (state.status === "idle") return null;
  if (state.status === "searching") {
    // F1：检索也应可停止（停止令 on_stop 作废在途检索与绑定）
    return (
      <span className="flex items-center gap-2">
        <span>联网检索中…</span>
        <button
          className="underline underline-offset-2"
          onClick={() => invoke("llm_stop", { kind })}
        >
          停止
        </button>
      </span>
    );
  }
  if (state.status === "pending") {
    return (
      <span className="flex items-center gap-2">
        <span>请求中…</span>
        <button className="underline underline-offset-2" onClick={() => invoke("llm_stop", { kind })}>
          停止
        </button>
      </span>
    );
  }
  if (state.status === "done") {
    if (state.truncated) return <span className="text-error">回答未完成</span>;
    return (
      <span className="text-ok">
        已完成 {state.secs?.toFixed(1)}s
      </span>
    );
  }
  if (state.status === "stopped") {
    return <span>已停止</span>;
  }
  return (
    <span className="flex items-center gap-2 text-error">
      <span className="normal-case tracking-normal">{kind === "translate" ? "翻译失败" : state.error ?? "失败"}</span>
      {state.retryable !== false && (
        <button className="underline underline-offset-2" onClick={() => invoke("llm_retry", { kind })}>
          重试
        </button>
      )}
    </span>
  );
}

function IncompleteAnswer({ kind, reason, retryable = true }: { kind: TabKey; reason?: string; retryable?: boolean }) {
  return (
    <div role="alert" className="mt-2 border border-line p-2 text-[12px] text-error leading-relaxed">
      {reason === "length" ? "回答未完成：已达到模型的上下文或输出长度上限。" : "回答未完成：连接在输出结束前中断。"}
      {retryable && <button className="ml-2 underline underline-offset-2" onClick={() => invoke("llm_retry", { kind })}>重试</button>}
    </div>
  );
}

/** 追问视图：模型选择与联网检索独立。 */
function ChatView({
  chat,
  state,
  draft,
  setDraft,
  onSubmit,
  chatProvider,
  modelNames,
  cloudKeyOk,
  onProvider,
}: {
  chat: ChatMessage[];
  state: ResultState;
  draft: string;
  setDraft: (v: string) => void;
  onSubmit: () => void;
  chatProvider: "ollama" | "openai";
  modelNames: { local: string; cloud: string };
  cloudKeyOk: boolean;
  onProvider: (p: "ollama" | "openai") => void;
}) {
  const curName = chatProvider === "ollama" ? modelNames.local : modelNames.cloud;
  return (
    <div className="h-full flex flex-col">
      <div className="micro-label text-muted px-3 pt-2 flex items-center gap-2">
        <span>Chat / 追问</span>
        <ProviderChip
          provider={chatProvider}
          modelNames={modelNames}
          cloudKeyOk={cloudKeyOk}
          onProvider={onProvider}
        />
        <span className="normal-case tracking-normal opacity-70 truncate max-w-[9rem]">
          {curName}
        </span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-2">
        {chat.length === 0 && (
          <div className="text-muted text-sm">
            可以继续问：为什么这样翻译？能举个例子吗？追问会结合原文、译文和解释。
          </div>
        )}
        {chat.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] bg-chip-bg text-chip-text text-[13px] leading-relaxed px-3 py-2 whitespace-pre-wrap select-text">
                {m.text}
              </div>
            </div>
          ) : (
            <div
              key={i}
              className="w-full min-w-0 bg-surface border border-line px-3 py-2 text-[13px] leading-relaxed select-text"
            >
              <MarkdownContent text={m.text} />
              <SearchSources sources={m.sources} />
              {m.truncated && <IncompleteAnswer kind="chat" reason={m.finish_reason} retryable={i === chat.length - 1} />}
              <div className="flex justify-end mt-2"><CopyAnswer text={m.text} /></div>
            </div>
          ),
        )}
        {state.status === "pending" && chat[chat.length - 1]?.role === "user" && (
          <div role="status" className="text-sm text-muted border border-line p-3">
            等待{chatProvider === "openai" ? "云端" : "本地"}模型回复…
            {chatProvider === "openai" && "若服务繁忙，可停止后切换「本地」重试。"}
          </div>
        )}
        {state.status === "failed" && (
          <div role="alert" className="text-sm border border-line p-3">
            <StatusMeta kind="chat" state={state} />
          </div>
        )}
        {state.status === "stopped" && (
          <div className="text-sm text-muted p-2">
            已停止。
            <button className="underline underline-offset-2" onClick={() => invoke("llm_retry", { kind: "chat" })}>
              重试追问
            </button>
          </div>
        )}
      </div>
      <div className="shrink-0 border-t border-line p-2">
        <textarea
          className="w-full h-16 bg-field border border-line p-2 text-[13px] text-text resize-none outline-none focus:border-border-strong select-text"
          placeholder="接着问…Enter 发送；Shift+Enter 换行"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
        />
        <div className="flex justify-end gap-1">
          <MainBtn label="发送" onClick={onSubmit} />
        </div>
      </div>
    </div>
  );
}

/** 后端选择 chip（本地/云端）：Launcher tab 语言；key 未配置时仍可点击——
 *  点击触发后端拒绝并给出明确原因（footer 显示），永远不"点了两下没反应"。 */
function ProviderChip({
  provider,
  modelNames,
  cloudKeyOk,
  onProvider,
}: {
  provider: "ollama" | "openai";
  modelNames: { local: string; cloud: string };
  cloudKeyOk: boolean;
  onProvider: (p: "ollama" | "openai") => void;
}) {
  return (
    <span className="flex items-stretch border border-line ml-1">
      {(["ollama", "openai"] as const).map((p) => {
        const activeChip = provider === p;
        return (
          <button
            key={p}
            title={
              p === "ollama"
                ? `本地模型：${modelNames.local}（无需模型 API key；搜索独立配置）`
                : cloudKeyOk
                  ? `云端模型：${modelNames.cloud}`
                  : `云端模型：${modelNames.cloud}（未配置 api_key，点击查看提示）`
            }
            onClick={() => onProvider(p)}
            className={`px-2 h-6 micro-label transition-colors ${
              activeChip ? "bg-chip-bg text-chip-text" : "text-muted hover:bg-surface"
            }`}
          >
            {p === "ollama" ? "本地" : "云端"}
          </button>
        );
      })}
    </span>
  );
}

/** 输入翻译：本地/云端模型选择 + Enter 提交 + 流式结果。 */
function InputView({
  state,
  onSubmit,
  inputProvider,
  modelNames,
  cloudKeyOk,
  onProvider,
}: {
  state: ResultState;
  onSubmit: (text: string, target: string) => void;
  inputProvider: "ollama" | "openai";
  modelNames: { local: string; cloud: string };
  cloudKeyOk: boolean;
  onProvider: (p: "ollama" | "openai") => void;
}) {
  const [draft, setDraft] = useState("");
  // 目标语向（Python TARGET_LANGUAGES；state 与输入框同生命周期跨会话保留）
  const [target, setTarget] = useState("auto");
  const curName = inputProvider === "ollama" ? modelNames.local : modelNames.cloud;
  return (
    <div className="h-full flex flex-col">
      <div className="micro-label text-muted px-3 pt-2 flex items-center gap-2">
        <span>Input / 输入翻译</span>
        <ProviderChip
          provider={inputProvider}
          modelNames={modelNames}
          cloudKeyOk={cloudKeyOk}
          onProvider={onProvider}
        />
        <span className="normal-case tracking-normal opacity-70 truncate max-w-[9rem]">
          {curName}
        </span>
        {/* 目标语向下拉（P4：Python input_combo 同款语向清单） */}
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="ml-auto normal-case tracking-normal text-[12px] bg-field border border-line px-1.5 py-0.5 text-text outline-none focus:border-border-strong"
        >
          {TARGET_LANGUAGES.map(([label, value]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <textarea
        className="shrink-0 mx-3 mt-2 h-20 bg-field border border-line p-2 text-[13px] text-text resize-none outline-none focus:border-border-strong select-text"
        placeholder="输入要翻译的内容…（Enter 发送；Shift+Enter 换行）"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (draft.trim()) {
              // 提交后保留原文（Python _submit_input 不清 input_editor：
              // 用户需基于原文改译；追问框才清空）
              onSubmit(draft.trim(), target === "auto" ? "" : target);
            }
          }
        }}
      />
      <div className="px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap select-text">
        {state.status === "failed" ? (
          <span className="text-error">{state.error}</span>
        ) : (
          state.text || <span className="text-muted">译文将在此显示</span>
        )}
        {state.text && <SearchSources sources={state.sources} />}
        {state.truncated && <IncompleteAnswer kind="input" reason={state.finish_reason} />}
      </div>
    </div>
  );
}

/** Launcher 主按钮：白底黑边方角，hover 反色 */
function MainBtn({ label, onClick }: { label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="px-3 h-7 text-[12px] font-semibold bg-bg-elevated text-text border border-border-strong hover:bg-chip-bg hover:text-chip-text hover:border-transparent transition-colors"
    >
      {label}
    </button>
  );
}

/** 置顶 chip：激活态黑底白字（"已置顶"），未激活 muted ghost——状态一眼可见 */
function PinAction({ pinned, onToggle }: { pinned: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      title={pinned ? "已置顶：Esc / 点外不关闭；点击取消" : "置顶：Esc / 点外不关闭"}
      className={`micro-label px-3 transition-colors ${
        pinned ? "bg-chip-bg text-chip-text" : "text-muted hover:text-text hover:bg-surface"
      }`}
    >
      {pinned ? "已置顶 · A" : "置顶 · A"}
    </button>
  );
}

/** 顶栏动作：1px 左边分割的 ghost 文本钮 */
function TopAction({ label, onClick, title }: { label: string; onClick?: () => void; title?: string }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="micro-label px-3 text-muted hover:text-text hover:bg-surface transition-colors"
    >
      {label}
    </button>
  );
}

// --------------------------------------------------------------- 设置

type Cfg = Record<string, any>; // 弱类型（Python dict 语义：未知字段整体写回保留）

/** 只读路径取值；缺省给前端兜底（后端 get_config 已深合并默认值，一般不会缺） */
function getIn(o: Cfg, keys: string[]): any {
  let cur: any = o;
  for (const k of keys) {
    cur = cur?.[k];
    if (cur === undefined) return undefined;
  }
  return cur;
}
/** 不可变路径写值（分支克隆，不触碰未知兄弟字段） */
function setIn(o: Cfg, keys: string[], v: any): Cfg {
  const out = (o && typeof o === "object" && !Array.isArray(o) ? { ...o } : {}) as Cfg;
  const head = keys[0];
  if (keys.length === 1) {
    out[head] = v;
  } else {
    out[head] = setIn((out[head] as Cfg) ?? {}, keys.slice(1), v);
  }
  return out;
}

const SETTING_GROUPS = [
  { key: "model", num: "01", color: "var(--color-accent)", label: "模型" },
  { key: "selection", num: "02", color: "var(--color-c02)", label: "划词" },
  { key: "hotkeys", num: "03", color: "var(--color-c03)", label: "热键" },
  { key: "search", num: "04", color: "var(--color-c04)", label: "检索" },
  { key: "appearance", num: "05", color: "var(--color-accent)", label: "外观" },
  { key: "domain", num: "06", color: "var(--color-ok)", label: "领域" },
] as const;
type GroupKey = (typeof SETTING_GROUPS)[number]["key"];

/** 设置窗（ArtCraft 风）：无边框自绘标题栏 + 左导航 + 右表单卡片。
 *  N2/R2：所有「覆盖类异步」（初始读/广播重拉/放弃统一 pullLatest）带 ticket——
 *  响应回来时 pull id 已过期或期间有编辑（patchSeq 变化）就丢弃，绝不覆盖新草稿。
 *  N3/R1：补丁带编辑代次 seq，保存成功只删除「提交且之后未被改动」的补丁。 */
function SettingsView() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [group, setGroup] = useState<GroupKey>("model");
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const patches = useRef(new Map<string, { path: string[]; value: any; seq: number }>());
  const patchSeq = useRef(0);
  const pullId = useRef(0);
  const savingRef = useRef(false);
  const dirtyRef = useRef(false);
  const recompute = () => {
    dirtyRef.current = patches.current.size > 0;
    setDirty(dirtyRef.current);
  };
  // 覆盖类重拉统一入口（ticket：pullId 变了 / 期间有编辑 → 响应作废）
  const pullLatest = (reset: boolean) => {
    const id = ++pullId.current;
    const editAt = patchSeq.current;
    invoke<Cfg>("get_config")
      .then((v) => {
        if (pullId.current !== id || patchSeq.current !== editAt) return; // 过期响应：保留草稿
        setCfg(v);
        if (reset) {
          patches.current.clear();
          patchSeq.current += 1;
          recompute();
          setMsg(null);
        }
      })
      .catch(() => setMsg({ ok: false, text: "读取配置失败（未动磁盘，草稿保留）" }));
  };
  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;
    pullLatest(false); // 初始读取（同样 ticket 化）
    // N2：其他窗口改了配置 → clean 时跟随最新；dirty 时不动草稿只提示；
    // 保存进行中跳过广播（保存完成后的 recompute + 后续广播会收敛状态）
    listen<{ kind?: string }>("config:updated", () => {
      if (disposed || savingRef.current) return;
      if (dirtyRef.current) {
        setMsg({ ok: false, text: "配置已在其他窗口更新，你的草稿可能与磁盘不一致（保存仅提交本页编辑项）" });
      } else {
        pullLatest(false);
      }
    }).then((off) => { if (disposed) off(); else unlisten = off; });
    return () => {
      disposed = true;
      unlisten?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!cfg) {
    return <div className="h-screen flex items-center justify-center bg-bg text-muted text-sm">加载配置…</div>;
  }
  const set = (keys: string[], v: any) => {
    setCfg((prev) => setIn(prev ?? {}, keys, v));
    patches.current.set(keys.join("\u0001"), { path: keys, value: v, seq: ++patchSeq.current });
    recompute();
    setMsg(null);
  };
  const save = async () => {
    if (savingRef.current || patches.current.size === 0) return; // 单飞 + 空保存不出手
    const committed = new Map(patches.current); // key → {path,value,seq}
    savingRef.current = true;
    try {
      await invoke("save_config_paths", {
        entries: [...committed.values()].map((p) => ({ path: p.path, value: p.value })),
      });
      patchSeq.current += 1; // 提交完成即代次推进
      // R1：只删「本轮提交且之后未被改动」的补丁；保存期间的新编辑原样保留
      for (const [key, entry] of committed) {
        const cur = patches.current.get(key);
        if (cur && cur.seq === entry.seq) patches.current.delete(key);
      }
      recompute();
      if (patches.current.size > 0) {
        setMsg({ ok: true, text: "已保存提交的修改；保存期间的新改动尚未保存，可再次保存" });
      } else {
        setMsg({ ok: true, text: "已保存（主题即时生效；热键改动重启应用后生效）" });
      }
    } catch (e) {
      setMsg({ ok: false, text: `保存失败：${e}` });
    } finally {
      savingRef.current = false;
    }
  };
  return (
    <div className="h-screen flex flex-col bg-bg text-text select-text">
      {/* 自绘标题栏（无原生边框）：可拖动 + 关闭 */}
      <header
        data-tauri-drag-region
        className="h-9 shrink-0 flex items-center justify-between px-3 bg-bg-elevated border-b border-line cursor-default"
      >
        <span className="micro-label text-muted">Dongyi / 设置</span>
        <button
          onClick={() => invoke("hide_settings")}
          className="w-6 h-6 flex items-center justify-center text-muted hover:text-text border border-line hover:border-border-strong"
        >
          ×
        </button>
      </header>
      <div className="flex-1 flex min-h-0">
        {/* 左导航：彩色编号块 + micro-label（Launcher 风语言） */}
        <nav className="w-40 shrink-0 border-r border-line py-3 flex flex-col gap-0.5">
          {SETTING_GROUPS.map((g) => (
            <button
              key={g.key}
              onClick={() => setGroup(g.key)}
              className={
                group === g.key
                  ? "flex items-center gap-2 px-3 h-8 text-left bg-chip-bg text-chip-text"
                  : "flex items-center gap-2 px-3 h-8 text-left text-muted hover:text-text hover:bg-surface-hover transition-colors"
              }
            >
              <span
                className="w-4 text-[10px] font-bold flex items-center justify-center text-white"
                style={{ background: g.color }}
              >
                {g.num}
              </span>
              <span className="text-[12px] font-semibold">{g.label}</span>
            </button>
          ))}
        </nav>
        {/* 右卡片区 */}
        <main className="flex-1 overflow-y-auto min-h-0 px-5 py-4">
          {group === "model" && (
            <div className="border border-line bg-bg-elevated">
              <div className="micro-label text-muted px-4 py-2 border-b border-line">Model / 模型</div>
              <div className="px-4 py-2">
                <Row label="默认后端">
                  <select
                    value={String(getIn(cfg, ["provider"]) ?? "ollama")}
                    onChange={(e) => set(["provider"], e.target.value === "openai" ? "openai" : "ollama")}
                    className="textSel"
                  >
                    <option value="ollama">本地 Ollama</option>
                    <option value="openai">云端模型（需 API key）</option>
                  </select>
                </Row>
                {([["chat", "追问模型"], ["input", "输入翻译模型"]] as const).map(([kind, label]) => (
                  <Row key={kind} label={label}>
                    <select
                      value={String(getIn(cfg, ["kind_providers", kind]) ?? "")}
                      onChange={(e) => set(["kind_providers", kind], e.target.value)}
                      className="textSel"
                    >
                      <option value="">跟随默认后端</option>
                      <option value="ollama">本地模型（无需模型 key）</option>
                      <option value="openai">云端模型（需模型 key）</option>
                    </select>
                  </Row>
                ))}
                <p className="py-2 text-[11px] text-muted leading-relaxed">
                  本地模型在本机运行，不调用云端模型接口。联网检索在「联网搜索」中独立设置，搜索服务可能仍需要搜索 key。
                </p>
                <Row label="本地模型名">
                  <ModelSelect value={String(getIn(cfg, ["model"]) ?? "")} onChange={(v) => set(["model"], v)} />
                </Row>
                <Row label="keep_alive">
                  <input className="ti w-36" value={String(getIn(cfg, ["keep_alive"]) ?? "")} onChange={(e) => set(["keep_alive"], e.target.value)} />
                  <span className="text-[11px] text-muted">何时 unload 本地模型（如 30m）</span>
                </Row>
                <Row label="云端 base_url">
                  <input className="ti" value={String(getIn(cfg, ["cloud", "base_url"]) ?? "")} onChange={(e) => set(["cloud", "base_url"], e.target.value)} />
                </Row>
                <Row label="云端模型名">
                  <input className="ti" value={String(getIn(cfg, ["cloud", "model"]) ?? "")} onChange={(e) => set(["cloud", "model"], e.target.value)} />
                </Row>
                <Row label="云端 api_key">
                  <ApiKeyInput value={String(getIn(cfg, ["cloud", "api_key"]) ?? "")} onChange={(v) => set(["cloud", "api_key"], v)} />
                </Row>
                <p className="px-0 py-2 text-[11px] text-muted leading-relaxed">
                  key 留空时可回退环境变量（api_key_env 指定变量名）。保存后下次请求即时生效。
                </p>
              </div>
            </div>
          )}
          {group === "selection" && (
            <div className="border border-line bg-bg-elevated">
              <div className="micro-label text-muted px-4 py-2 border-b border-line">Selection / 划词</div>
              <div className="px-4 py-2">
                <NumRow cfg={cfg} set={set} keys={["debounce_ms"]} label="防抖（毫秒）" />
                <NumRow cfg={cfg} set={set} keys={["icon_timeout_s"]} label="浮标自动隐藏（秒）" />
                <NumRow cfg={cfg} set={set} keys={["max_text_len"]} label="原文截断长度（字符）" />
                <CheckRow cfg={cfg} set={set} keys={["offline"]} label="严格离线（不外发云端，本地仅 loopback）" />
                <CheckRow cfg={cfg} set={set} keys={["clipboard_fallback"]} label="剪贴板兜底取词（UIA 取不到时 Ctrl+C 复制）" />
                <Row label="剪贴板兜底进程">
                  <ProcessListInput
                    value={Array.isArray(getIn(cfg, ["clipboard_fallback_processes"])) ? getIn(cfg, ["clipboard_fallback_processes"]) : []}
                    onChange={(arr) => set(["clipboard_fallback_processes"], arr)}
                  />
                </Row>
              </div>
            </div>
          )}
          {group === "hotkeys" && (
            <div className="border border-line bg-bg-elevated">
              <div className="micro-label text-muted px-4 py-2 border-b border-line">Hotkeys / 热键（重启应用生效）</div>
              <div className="px-4 py-2">
                {[["translate", "翻译弹窗"], ["explain", "解释"], ["input", "输入翻译"]].map(([k, note]) => (
                  <Row key={k} label={note ?? ""}>
                    <input
                      className="ti"
                      value={String(getIn(cfg, ["hotkeys", k]) ?? "")}
                      onChange={(e) => set(["hotkeys", k], e.target.value)}
                    />
                    <span className="text-[11px] text-muted">kdl 格式：&lt;ctrl&gt;+&lt;alt&gt;+&lt;shift&gt;+t</span>
                  </Row>
                ))}
              </div>
            </div>
          )}
          {group === "search" && (
            <div className="border border-line bg-bg-elevated">
              <div className="micro-label text-muted px-4 py-2 border-b border-line">Web Search / 联网检索</div>
              <div className="px-4 py-2">
                <CheckRow cfg={cfg} set={set} keys={["web_search", "enabled"]} label="启用联网检索" />
                {([["explain", "解释时搜索"], ["chat", "追问时搜索"], ["input", "输入翻译时搜索（术语查证）"]] as const).map(([kind, label]) => (
                  <CheckRow key={kind} cfg={cfg} set={set} keys={["web_search", "kinds", kind]} label={label} />
                ))}
                <p className="py-2 text-[11px] text-muted leading-relaxed">
                  搜索与回答模型独立：选本地模型也可搜索，无需云端模型 key。搜索使用下方 Ollama 搜索 key；输入翻译默认不搜索，开启后只辅助核对术语与背景。
                </p>
                <Row label="检索 api_key">
                  <ApiKeyInput value={String(getIn(cfg, ["web_search", "api_key"]) ?? "")} onChange={(v) => set(["web_search", "api_key"], v)} />
                  <span className="text-[11px] text-muted">留空回退 OLLAMA_API_KEY 环境变量</span>
                </Row>
                <NumRow cfg={cfg} set={set} keys={["web_search", "max_results"]} label="最多取结果条数" />
              </div>
            </div>
          )}
          {group === "appearance" && (
            <div className="border border-line bg-bg-elevated">
              <div className="micro-label text-muted px-4 py-2 border-b border-line">Appearance / 外观</div>
              <div className="px-4 py-3">
                <Row label="主题">
                  <ThemePicker cfg={cfg} set={set} />
                </Row>
              </div>
            </div>
          )}
          {group === "domain" && (
            <DomainEditor
              cfg={cfg}
              set={set}
              dropPatches={(prefix) => {
                for (const k of [...patches.current.keys()]) {
                  if (k === prefix || k.startsWith(prefix + "\u0001")) patches.current.delete(k);
                }
              }}
            />
          )}
        </main>
      </div>
      {/* 底部保存条 */}
      <footer className="shrink-0 border-t border-line px-4 py-2.5 flex items-center gap-3 bg-bg-elevated">
        <span className={`text-[12px] ${msg ? (msg.ok ? "text-ok" : "text-error") : ""} normal-case tracking-normal`}>
          {msg ? msg.text : dirty ? "有未保存修改" : "配置与磁盘一致"}
        </span>
        <span className="flex-1" />
        {dirty && (
          <button
            onClick={() => {
              if (savingRef.current) return; // R2：保存中禁放弃，交叉状态立界
              // R3：不清补丁、不预推进代次——pullLatest(true) 在「响应成功且
              // 票据有效」时才原子替换 cfg+清补丁+recompute；失败/过期时草稿原样保留
              pullLatest(true);
            }}
            className="px-3 h-7 text-[12px] text-muted hover:text-text border border-line hover:border-border-strong transition-colors"
          >
            放弃修改
          </button>
        )}
        <MainBtn label={dirty ? "保存" : "已保存"} onClick={dirty ? save : undefined} />
      </footer>
    </div>
  );
}

/** numVal：容错取数值 */
function NumRow({ cfg, set, keys, label }: { cfg: Cfg; set: (k: string[], v: any) => void; keys: string[]; label: string }) {
  const v = getIn(cfg, keys);
  const value = typeof v === "number" ? v : Number(v ?? 0);
  return (
    <Row label={label}>
      <input
        type="number"
        className="ti w-28"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) set(keys, n);
        }}
      />
    </Row>
  );
}

function CheckRow({ cfg, set, keys, label }: { cfg: Cfg; set: (k: string[], v: any) => void; keys: string[]; label: string }) {
  const checked = !!getIn(cfg, keys);
  return (
    <Row label={label}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => set(keys, e.target.checked)}
        className="w-3.5 h-3.5 accent-black"
      />
    </Row>
  );
}

/** 本地模型下拉：数据来自 Ollama /api/tags（后端 local_models 命令）。
 *  连不上 Ollama / 列表为空时退化手输 + 提示（保证设置页始终可用）。 */
function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [models, setModels] = useState<string[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    invoke<string[]>("local_models")
      .then((ls) => {
        if (alive) setModels(ls.filter(Boolean));
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => { alive = false; };
  }, []);
  if (failed || (models !== null && models.length === 0)) {
    // N5：两种退化（不可达 / 列表为空）都给提示，不再只有 failed 分支
    return (
      <>
        <input className="ti" value={value} onChange={(e) => onChange(e.target.value)} />
        <span className="text-[11px] text-error normal-case tracking-normal shrink-0">
          {failed ? "Ollama 未连接，请手填模型名" : "未取到模型（Ollama 无模型或不可达），请手填"}
        </span>
      </>
    );
  }
  if (models === null) {
    return <span className="text-[11px] text-muted normal-case tracking-normal">正在获取模型列表…</span>;
  }
  const hasCur = models.includes(value);
  return (
    <select className="textSel flex-1" value={hasCur ? value : ""} onChange={(e) => onChange(e.target.value)}>
      {!hasCur && <option value="">{value || "选择模型…"}</option>}
      {models.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </select>
  );
}

/** P4-N6：进程列表草稿式编辑——本地 draft 保留逐字输入（不合规不回弹），
 *  合法时才提交 cfg；外部 value 变化（放弃修改）时重同步。 */
function ProcessListInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState(JSON.stringify(value ?? []));
  const [err, setErr] = useState(false);
  useEffect(() => {
    setDraft(JSON.stringify(value ?? []));
    setErr(false);
  }, [value]);
  return (
    <>
      <input
        className="ti font-mono"
        value={draft}
        onChange={(e) => {
          const text = e.target.value;
          setDraft(text);
          try {
            const arr = JSON.parse(text);
            if (Array.isArray(arr) && arr.every((x) => typeof x === "string")) {
              setErr(false);
              onChange(arr);
            } else {
              setErr(true);
            }
          } catch {
            setErr(true); // 输入中允许暂时非法，blur 时以最后合法值提交
          }
        }}
      />
      <span className={`text-[11px] shrink-0 normal-case tracking-normal ${err ? "text-error" : "text-muted"}`}>
        {err ? "JSON 数组格式待修正（保存用最后合法值）" : 'JSON 数组，如 ["sioyek.exe"]'}
      </span>
    </>
  );
}

/** api_key 输入：password + 显示切换（粘贴用） */
function ApiKeyInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [show, setShow] = useState(false);
  return (
    <>
      <input
        type={show ? "text" : "password"}
        className="ti font-mono"
        placeholder="sk-…（可留空回退环境变量）"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
      />
      <button
        onClick={() => setShow(!show)}
        className="text-[11px] text-muted hover:text-text border border-line px-1.5 py-0.5 normal-case tracking-normal"
      >
        {show ? "隐藏" : "显示"}
      </button>
    </>
  );
}

/** 主题三选（auto/light/dark），保存后由 save_config 广播跨窗口切换 */
function ThemePicker({ cfg, set }: { cfg: Cfg; set: (k: string[], v: any) => void }) {
  const cur = ["auto", "light", "dark"].includes(String(getIn(cfg, ["theme"]))) ? String(getIn(cfg, ["theme"])) : "auto";
  return (
    <div className="flex gap-1">
      {(["auto", "light", "dark"] as const).map((t) => (
        <button
          key={t}
          onClick={() => set(["theme"], t)}
          className={
            cur === t
              ? "px-2.5 h-7 text-[12px] font-semibold bg-chip-bg text-chip-text"
              : "px-2.5 h-7 text-[12px] font-semibold bg-bg text-text border border-line hover:border-border-strong transition-colors"
          }
        >
          {t === "auto" ? "跟随系统" : t === "light" ? "浅色" : "深色"}
        </button>
      ))}
    </div>
  );
}

/** P5：领域（学科）编辑（Python settings.py 领域区同款字段）：
 *  name/note/enabled/glossary_file/kb_dirs/kb_enabled/kb_for_translate。
 *  新建 id 自动 d1/d2…；删除走 ConfigPatch null 删除语义 + 后代补丁归一化（M7）。 */
function DomainEditor({
  cfg,
  set,
  dropPatches,
}: {
  cfg: Cfg;
  set: (k: string[], v: any) => void;
  dropPatches: (prefix: string) => void;
}) {
  const domainsMap = (cfg["domains"] && typeof cfg["domains"] === "object"
    ? (cfg["domains"] as Record<string, any>)
    : {}) as Record<string, Record<string, any>>;
  const idOk = (id: string) => {
    return id.length >= 1 && id.length <= 64 && /^[A-Za-z0-9_-]+$/.test(id);
  };
  const ids = Object.keys(domainsMap)
    .filter((id) => idOk(id) && domainsMap[id] !== null) // null = 草稿删除态，不显示
    .sort();
  const [cur, setCur] = useState("");
  const [newName, setNewName] = useState("");
  const selected = ids.includes(cur) ? cur : (ids[0] ?? "");
  const dom = (domainsMap[selected] ?? {}) as Record<string, any>;
  const setField = (field: string, v: any) => set(["domains", selected, field], v);
  const newDomain = () => {
    const name = newName.trim().slice(0, 30);
    if (!name) return;
    let n = 1;
    while (domainsMap[`d${n}`]) n += 1; // Python _new_domain 同款 id 编号
    const id = `d${n}`;
    set(["domains", id], {
      name, note: "", enabled: true, glossary_file: "",
      kb_dirs: [], kb_enabled: false, kb_for_translate: false,
    });
    setCur(id);
    setNewName("");
  };
  const removeDomain = () => {
    if (!selected) return;
    // Gate P5-M7：先清该领域的全部后代补丁（防子补丁在后端自动建父级"复活"），
    // 再把父路径 null 重插到补丁尾部（同键重设即移到末尾——提交顺序保证删除在后）
    dropPatches(["domains", selected].join("\u0001"));
    set(["domains", selected], null); // null = 删除键（后端 diff 事务支持）
    setCur("");
  };
  const kbDirs: string[] = Array.isArray(dom.kb_dirs) ? dom.kb_dirs : [];
  return (
    <div className="border border-line bg-bg-elevated">
      <div className="micro-label text-muted px-4 py-2 border-b border-line">Domains / 领域（学科适配：术语表 + 知识库）</div>
      <div className="px-4 py-2">
        <Row label="领域">
          <select
            className="textSel flex-1"
            value={selected}
            onChange={(e) => setCur(e.target.value)}
          >
            {ids.length === 0 && <option value="">（尚无领域）</option>}
            {ids.map((id) => (
              <option key={id} value={id}>
                {String(domainsMap[id]?.name || id)}（{id}）
              </option>
            ))}
          </select>
          <input
            className="ti w-28"
            placeholder="新领域名"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") newDomain(); }}
          />
          <button
            onClick={newDomain}
            className="px-2 h-7 text-[12px] border border-line hover:border-border-strong text-muted hover:text-text"
          >
            新建
          </button>
          {selected && (
            <button
              onClick={removeDomain}
              className="px-2 h-7 text-[12px] border border-line text-error hover:border-error"
            >
              删除
            </button>
          )}
        </Row>
        {selected && (
          <>
            <Row label="显示名">
              <input className="ti" value={String(dom.name ?? "")} onChange={(e) => setField("name", e.target.value)} />
            </Row>
            <Row label="启用">
              <input
                type="checkbox"
                checked={dom.enabled !== false}
                onChange={(e) => setField("enabled", e.target.checked)}
                className="w-3.5 h-3.5 accent-black"
              />
              <span className="text-[11px] text-muted">出现于弹窗学科下拉</span>
            </Row>
            <div className="py-2 border-b border-line flex gap-3">
              <span className="w-44 shrink-0 text-[12px] text-muted pt-1">领域说明（注入 prompt）</span>
              <textarea
                className="ti h-20 resize-none"
                value={String(dom.note ?? "")}
                onChange={(e) => setField("note", e.target.value)}
              />
            </div>
            <Row label="术语表 CSV 路径">
              <input
                className="ti"
                placeholder="留空 = glossaries/&lt;id&gt;.csv（相对=数据目录）"
                value={String(dom.glossary_file ?? "")}
                onChange={(e) => setField("glossary_file", e.target.value)}
              />
            </Row>
            <Row label="术语表上限">
              <span className="text-[11px] text-muted normal-case tracking-normal">
                CSV 每行「原文,译文[,备注]」；请求时按命中注入（≤60 条 / 4000 字）；改表无需重启
              </span>
            </Row>
            <div className="py-2 border-b border-line flex gap-3">
              <span className="w-44 shrink-0 text-[12px] text-muted pt-1">知识库目录（每行一条）</span>
              <textarea
                className="ti h-16 resize-none"
                value={kbDirs.join("\n")}
                onChange={(e) => {
                  setField(
                    "kb_dirs",
                    e.target.value.split("\n").map((l) => l.trim()).filter(Boolean),
                  );
                }}
              />
            </div>
            <Row label="知识库检索注入">
              <input
                type="checkbox"
                checked={!!dom.kb_enabled}
                onChange={(e) => setField("kb_enabled", e.target.checked)}
                className="w-3.5 h-3.5 accent-black"
              />
            </Row>
            <Row label="翻译时也检索知识库">
              <input
                type="checkbox"
                checked={!!dom.kb_for_translate}
                onChange={(e) => setField("kb_for_translate", e.target.checked)}
                className="w-3.5 h-3.5 accent-black"
              />
              <span className="text-[11px] text-muted">默认仅解释启用；追问/输入默认不注入</span>
            </Row>
            <p className="py-2 text-[11px] text-muted leading-relaxed">
              术语表/翻译记忆/知识库与 Python 版共用同一数据目录：%APPDATA%\dongyi\（glossaries\、tm\、kb_index\index.json）。
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/** 设置页通用行：左侧 12px label，右侧控件 */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex items-center gap-3 py-2 border-b border-line last:border-b-0">
      <span className="w-44 shrink-0 text-[12px] text-muted">{label}</span>
      <div className="flex-1 flex items-center gap-2 min-w-0">{children}</div>
    </label>
  );
}
