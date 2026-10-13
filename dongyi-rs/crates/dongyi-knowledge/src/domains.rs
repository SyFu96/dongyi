//! 领域（domains.py 移植）：config.domains 解析、启用去重、激活校验。
//! 领域 id 规则 `^[A-Za-z0-9_-]{1,64}$`（id 会拼进文件路径）。

use serde_json::Value;

/// 领域 id 合法性（DOMAIN_ID_RE 同款：1~64 个 [A-Za-z0-9_-]）
pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.chars().count() <= 64
        && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// 单条领域配置（弱类型 Value 的字段读取封装）
#[derive(Clone)]
pub struct Dom {
    pub id: String,
    pub name: String,
    pub note: String,
    pub enabled: bool,
    pub glossary_file: String,
    pub kb_dirs: Vec<String>,
    pub kb_enabled: bool,
    /// 翻译标签是否也检索知识库（Python kb_for_translate）
    pub kb_for_translate: bool,
}

impl Dom {
    /// 从 domains[k] 的 Value 解析（缺字段按 Python 默认）
    pub fn from_cfg(id: &str, v: &Value) -> Dom {
        let s = |k: &str| v[k].as_str().unwrap_or("").to_owned();
        Dom {
            id: id.to_owned(),
            name: s("name"),
            note: s("note"),
            enabled: v["enabled"].as_bool().unwrap_or(true),
            glossary_file: s("glossary_file"),
            kb_dirs: v["kb_dirs"]
                .as_array()
                .map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_owned)).collect())
                .unwrap_or_default(),
            kb_enabled: v["kb_enabled"].as_bool().unwrap_or(false),
            kb_for_translate: v["kb_for_translate"].as_bool().unwrap_or(false),
        }
    }
}

/// dom.note 截断（MAX_NOTE_CHARS=2000，Python domain_note_text 同款）
pub fn note_text(dom: &Dom) -> String {
    dom.note.trim().chars().take(2000).collect()
}

/// 大小写去重后的 [(id, Dom)]，按 id 排序（参数 = 整个 cfg，内部取 ["domains"]——
/// Python dedupe_domains(cfg) 同款）。
/// 保留规则（Gate P5-m2：与前端 computeDomains 共用的确定性规则，避免前后端
/// keeper 不一致）：同组内**按 id 字节序**取第一个启用的；全停用取排序第一。
pub fn dedupe(cfg: &Value) -> Vec<(String, Dom)> {
    let Some(map) = cfg.get("domains").and_then(|v| v.as_object()) else {
        return vec![];
    };
    let mut groups: std::collections::HashMap<String, Vec<(String, Dom)>> = Default::default();
    for (id, v) in map {
        if !valid_id(id) || !v.is_object() {
            continue;
        }
        groups
            .entry(id.to_lowercase())
            .or_default()
            .push((id.clone(), Dom::from_cfg(id, v)));
    }
    let mut out: Vec<(String, Dom)> = Vec::new();
    for members in groups.into_values() {
        let mut sorted = members;
        sorted.sort_by(|a, b| a.0.cmp(&b.0)); // 确定性：id 字节序
        let keeper = sorted
            .iter()
            .find(|(_, d)| d.enabled)
            .cloned()
            .unwrap_or_else(|| sorted[0].clone());
        out.push(keeper);
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

/// 只保留 id 合法且 enabled 的领域（参数 = 整个 cfg）
pub fn enabled(cfg: &Value) -> Vec<(String, Dom)> {
    dedupe(cfg)
        .into_iter()
        .filter(|(_, d)| d.enabled)
        .collect()
}

/// 当前激活领域 id；无效（不存在/未启用）回退通用空串（Python resolve_active）
pub fn resolve_active(cfg: &Value) -> String {
    let active = cfg["active_domain"].as_str().unwrap_or("").to_owned();
    if !active.is_empty() && enabled(cfg).iter().any(|(id, _)| *id == active) {
        return active;
    }
    String::new()
}

/// 激活领域的 Dom（None = 通用模式）
pub fn active(cfg: &Value) -> Option<(String, Dom)> {
    let id = resolve_active(cfg);
    if id.is_empty() {
        return None;
    }
    dedupe(cfg)
        .into_iter()
        .find(|(d, _)| *d == id)
        .map(|(_, dom)| (id, dom))
}
