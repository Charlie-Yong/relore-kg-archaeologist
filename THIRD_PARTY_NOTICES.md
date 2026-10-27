# Third-party source

## relore 0.3.19

- Original project: Hugging Face, https://github.com/huggingface/relore
- Source commit: `06a1c99c4653e9db899a18e96d8ff0ee6b419815`.
- Original copyright: Copyright 2026 The HuggingFace Team. All rights reserved.
- License: [Apache License 2.0](vendor/relore/LICENSE).
- The fixed source, tests, build configuration and documentation are included in
  [vendor/relore](vendor/relore). Provenance and local changes are recorded in
  [UPSTREAM.json](vendor/relore/UPSTREAM.json).
- Original `AGENTS.md` is preserved as `UPSTREAM_AGENTS.md`, an archival reference.
  The original deployment instructions and example results describe that project.
- No upstream runtime source was changed during initial import. Project-specific
  collection limits, local configuration and interfaces live in `historykg`.

项目历史采集器基于开源relore二次开发。上游实现抓取、索引和检索；P4负责本项目的
源码移植、配置、URL入口、基础接口封装、验证及交接。项目汇报同时说明复用来源和
本组新增工作。
