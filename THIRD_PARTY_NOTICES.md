# Third-party source

## ReLore 0.3.19 (historical prototype and experiments)

- Original project: Hugging Face, https://github.com/huggingface/relore
- Source commit: `06a1c99c4653e9db899a18e96d8ff0ee6b419815`.
- Original copyright: Copyright 2026 The HuggingFace Team. All rights reserved.
- License: [Apache License 2.0](repro/licenses/Relore-LICENSE.txt).
- The [original import record](repro/licenses/Relore-UPSTREAM.json) is preserved.
  The full vendored snapshot used for the original experiments is available in the
  project history at `e8b8658`.

早期原型使用 ReLore 的讨论抓取、存储和检索，P4 负责移植、采集范围、回放与数据接口适配。
2026-11-08 起，现行版本通过 HistoryKG 内的 GitHub 读取、快照和讨论索引完成这些工作；
保留原采集格式的读兼容，以便重建历史数据。旧实验的检索方法和结果仍按原版本引用。

## Flask frozen course sources

- Original project: Pallets, https://github.com/pallets/flask .
- Source code is BSD-3-Clause; the unmodified license from commit
  `548994ea0c61465574cbfdd636a894a692f54b94` is included at
  [repro/licenses/Flask-LICENSE.txt](repro/licenses/Flask-LICENSE.txt).
- The frozen course package preserves each source's original URL, author, time and hash.
  Discussion text remains attributable to its original authors; public visibility
  does not transfer ownership. Model-produced Decision records are distinguished
  from original quoted text.
- The package contains a limited historical sample, not the full upstream repository.
