//! 中英混合分词（Python knowledge.tokenize 同款）：
//! 英文/数字按词（[a-z0-9]+），连续中文段做 bigram，单字中文保留单字。
//! 检索（BM25/KM）与相似度（TM Jaccard）共用。

pub fn tokenize(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut out: Vec<String> = Vec::new();
    // ASCII 词/数字
    let bytes = lowered.as_bytes();
    let n = bytes.len();
    let mut i = 0usize;
    while i < n {
        if bytes[i].is_ascii_lowercase() || bytes[i].is_ascii_digit() {
            let start = i;
            while i < n && (bytes[i].is_ascii_lowercase() || bytes[i].is_ascii_digit()) {
                i += 1;
            }
            out.push(lowered[start..i].to_owned());
        } else {
            i += 1;
        }
    }
    // 中文段 → bigram（单字保留）
    let mut run = String::new();
    for ch in lowered.chars() {
        if ('\u{4e00}'..='\u{9fff}').contains(&ch) {
            run.push(ch);
        } else if !run.is_empty() {
            flush_cjk(&mut out, &run);
            run.clear();
        }
    }
    if !run.is_empty() {
        flush_cjk(&mut out, &run);
    }
    out
}

fn flush_cjk(out: &mut Vec<String>, run: &str) {
    let chars: Vec<char> = run.chars().collect();
    if chars.len() == 1 {
        out.push(chars[0].to_string());
    } else {
        for w in chars.windows(2) {
            out.push(w.iter().collect());
        }
    }
}
