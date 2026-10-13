//! dongyi-knowledge：领域适配 / 术语表 / 翻译记忆 / 知识库（RAG）。
//!
//! 语义从 Python 版 domains.py / tm.py / knowledge.py 逐条移植，
//! 数据文件与 Python 版**共用同一份**（config.domains、tm/*.jsonl、
//! kb_index/index.json v4），可互相接力。
//! 已知裁切：KB 文档解析仅支持 txt/md/csv/json 直读（PDF/docx 需重型
//! 依赖不在本地编译集内；Python 版索引生成后本 crate 直接消费）。

pub mod domains;
pub mod glossary;
pub mod knowledge;
pub mod tm;
pub mod tokenize;
