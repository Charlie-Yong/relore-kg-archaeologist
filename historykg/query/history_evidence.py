"""Select small, attributable passages for questions about a specific release or change."""

from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import quote

from .retrieval import PATH_PATTERN, decision_terms

NUMBER = re.compile(r"(?:#\s*|\b(?:issue|pr|pull request)\s+)(\d+)(?![0-9])", re.I)
VERSION = re.compile(
    r"(?<![\w.])v?\d+(?:\.\d+)+(?:[-.]?(?:rc|a|b)\d+)?(?![a-zA-Z0-9.])", re.I | re.ASCII
)
SNAPSHOT = re.compile(
    r"(?:冻结默认分支|冻结快照|snapshot(?:\s+(?:sha|commit))?)\s*[:：=]?\s*[a-f0-9]{7,40}\b", re.I
)
RELEASE = re.compile(r"发布|发行|\brelease\b", re.I)
RELEASE_DATE = re.compile(r"(?:哪天|哪一天|什么时候|几号)(?:正式)?(?:出|上线)|哪天出的")
RELEASE_MEMBERSHIP = re.compile(
    r"(?:随|进入?|包含于|纳入|进了|收录于).{0,14}(?:正式)?版|"
    r"(?:哪个|哪一?个?)(?:正式)?版|(?:随|正式版).{0,16}发布|"
    r"(?:included in|first shipped in|released in)", re.I,
)
RELEASE_IDENTITY = re.compile(
    r"(?:是|属于)(?:不是|否(?:为)?|不是)?(?:正式版|候选版|预发布版)|"
    r"(?:is|was).{0,12}(?:pre[- ]?release|release candidate)", re.I,
)
DECISION_INTENT = re.compile(
    r"为什么|为何|决定|决策|权衡|拒绝|弃用|移除|改用|替代|"
    r"\b(?:why|decisions?|rejected?|deprecat\w*|remov\w*|replac\w*)\b", re.I,
)
TRACE = re.compile(
    r"为什么|改[动了]|修改|追溯|落实|合并|重构|变更|改过|源[码文]|测试|why|change|merge|trace|implement|diff",
    re.I,
)
SHA = re.compile(r"[0-9a-f]{40}")
PYTHON_METHOD = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?![\w.])", re.ASCII)
CUTOFF = re.compile(
    r"(?:截止(?:时间)?|截至|as of|cutoff)\s*[:：]?\s*"
    r"(\d{4}-\d\d-\d\d(?:T[\d:.]+(?:Z|[+-]\d\d:\d\d))?)",
    re.I,
)


def search_intent(question):
    if NUMBER.search(question):
        if RELEASE_MEMBERSHIP.search(question):
            return "membership"
        if TRACE.search(question):
            return "change"
        return None
    if VERSION.search(question):
        if (
            RELEASE.search(question)
            or RELEASE_DATE.search(question)
            or RELEASE_IDENTITY.search(question)
        ):
            return "release"
        return None
    if any(p.endswith(".py") for p in PATH_PATTERN.findall(question)):
        return "code"
    if DECISION_INTENT.search(question):
        return "decision"
    return None


def fragment(source, start, end, title=None, detail_url=None):
    item = dict(
        source_id=source["source_id"],
        url=source["url"],
        author=source.get("author"),
        time=source.get("occurred_at"),
        title=title or source.get("title"),
        start=start,
        end=end,
        quote=source["text"][start:end],
    )
    if detail_url:
        item["detail_url"] = detail_url
    return item


def instant(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def release_records(sources, repo, cutoff):
    """Find offsets of individual Release objects, including paginated frozen responses."""
    url = "https://api.github.com/repos/" + repo + "/releases"
    decoder = json.JSONDecoder()
    for source in sources:
        if source["kind"] != "api_response" or source["url"].split("?")[0] != url:
            continue
        text = source["text"]
        if not text.lstrip().startswith("["):
            continue
        pos = text.index("[") + 1
        while pos < len(text):
            while pos < len(text) and (text[pos].isspace() or text[pos] == ","):
                pos += 1
            if pos == len(text) or text[pos] == "]":
                break
            try:
                row, end = decoder.raw_decode(text, pos)
            except ValueError:
                break
            published = instant(row.get("published_at")) if isinstance(row, dict) else None
            if (
                published
                and row.get("tag_name")
                and (cutoff is None or published <= cutoff)
                and not row.get("draft")
            ):
                yield row, source, pos, end
            pos = end


def release_fragment(row, source, start, end, compact):
    text = source["text"]
    obj = text[start:end]
    # Decode only the object's own keys and values, retaining their original offsets.
    decoder = json.JSONDecoder()
    fields = {}
    pos = 1
    while True:
        while pos < len(obj) and (obj[pos].isspace() or obj[pos] == ","):
            pos += 1
        if pos == len(obj) or obj[pos] == "}":
            break
        key, key_end = decoder.raw_decode(obj, pos)
        value_start = obj.index(":", key_end) + 1
        while obj[value_start].isspace():
            value_start += 1
        _, value_end = decoder.raw_decode(obj, value_start)
        fields[key] = (pos, value_end)
        pos = value_end
    selected = [
        fields[k] for k in ("tag_name", "draft", "prerelease", "published_at") if k in fields
    ]
    a, b = min(x[0] for x in selected), max(x[1] for x in selected)
    if compact and b - a > 1000:
        a, b = fields["tag_name"]
    elif b - a > 1800:
        date = fields["published_at"]
        flag = fields.get("prerelease", date)
        a, b = min(date[0], flag[0]), max(date[1], flag[1])
        if b - a > 1800:
            a, b = flag
    detail_url = row.get("html_url") or (
        f"https://github.com/{source['repo']}/releases/tag/{quote(row['tag_name'], safe='')}"
    )
    title = (
        f"{row['tag_name']} · {detail_url} · draft={row.get('draft')}, "
        f"prerelease={row.get('prerelease')}"
    )
    return fragment(source, start + a, start + b, title, detail_url)


def python_method_passages(sources, repo, question):
    paths = {p for p in PATH_PATTERN.findall(question) if p.endswith(".py")}
    methods = set(PYTHON_METHOD.findall(PATH_PATTERN.sub("", question)))
    snapshots = SNAPSHOT.findall(question)
    commits = {found[0] for value in snapshots if (found := SHA.search(value))}
    if not snapshots:
        ref_root = f"https://api.github.com/repos/{repo}/git/ref/heads/"
        for source in sources:
            if source["kind"] == "api_response" and source["url"].startswith(ref_root):
                try:
                    commit = json.loads(source["text"])["object"]["sha"]
                except (ValueError, KeyError, TypeError):
                    continue
                if isinstance(commit, str) and SHA.fullmatch(commit):
                    commits.add(commit)
    if len(commits) != 1:
        return []
    commit = next(iter(commits))
    base = f"https://github.com/{repo}/blob/{commit}/"
    urls = {base + path for path in paths}
    passages = []
    for source in sources:
        if source["kind"] != "code" or source["url"] not in urls:
            continue
        try:
            tree = ast.parse(source["text"])
        except (SyntaxError, ValueError):
            continue
        offsets = [0]
        for line in source["text"].splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if (node.name, member.name) in methods or (
                    not methods and member.name.startswith(("load", "dump"))
                ):
                    line_url = f"{source['url']}#L{member.lineno}-L{member.end_lineno}"
                    passages.append(fragment(
                        source, offsets[member.lineno - 1], offsets[member.end_lineno],
                        f"{node.name}.{member.name} · {line_url}", line_url,
                    ))
    return passages


def targeted_paths(package, identities, intent, depth, limit):
    """Use only recorded relations. Keep the direction and whole Issue→PR→commit paths."""
    entities = {e["id"]: e for e in package["entities"]}
    issues = {i for i in identities if entities[i]["type"] == "Issue"}
    prs = {i: ([i], []) for i in identities if entities[i]["type"] == "PullRequest"}
    paths = []

    def append(nodes, edges):
        if len(edges) <= depth:
            paths.append(dict(entity_ids=nodes, relation_ids=edges))

    for r in package["relations"]:
        if r["type"] in {"Closes", "ClaimsToClose"} and r["to_id"] in issues:
            nodes, edges = [r["to_id"], r["from_id"]], [r["id"]]
            append(nodes, edges)
            prs.setdefault(r["from_id"], (nodes, edges))
        if intent == "release" and r["type"] == "HasRelease" and r["to_id"] in identities:
            append([r["to_id"], r["from_id"]], [r["id"]])
    commits = {}
    for r in package["relations"]:
        if r["type"] == "MergedAs" and r["from_id"] in prs:
            n, e = prs[r["from_id"]]
            nodes, edges = [*n, r["to_id"]], [*e, r["id"]]
            append(nodes, edges)
            commits[r["to_id"]] = (nodes, edges)
    last = "ReachableIn" if intent == "membership" else "Touches"
    for r in package["relations"]:
        if r["type"] == last and r["from_id"] in commits:
            nodes, edges = commits[r["from_id"]]
            append([*nodes, r["to_id"]], [*edges, r["id"]])
    return paths[:limit]


def ancestry_fragments(sources, releases, merge_sha):
    """Check each frozen single-tag walk. Prove negative walks closed with parent records."""
    tips, walks, parents = {}, {}, {}
    for source in sources:
        meta = source.get("git_metadata") or {}
        cmd = meta.get("command", [])
        if source["kind"] != "git_output" or meta.get("returncode") != 0:
            continue
        if cmd[:3] == ["git", "rev-parse", "--verify"] and len(cmd) == 4:
            match = re.fullmatch(r"refs/tags/(.+)\^\{commit\}", cmd[-1])
            if match:
                tips[match[1]] = json.loads(source["text"])["stdout"].strip()
        elif cmd[:2] == ["git", "rev-list"] and len(cmd) == 3 and SHA.fullmatch(cmd[-1]):
            walks[cmd[-1]] = source
        elif cmd[:4] == ["git", "show", "-s", "--format=%H%n%P%n%cI%n%B"] and len(cmd) == 5:
            lines = json.loads(source["text"])["stdout"].splitlines()
            if len(lines) >= 2 and lines[0] == cmd[-1]:
                parents[cmd[-1]] = lines[1].split()
    for row, *_ in releases:
        tag = row["tag_name"]
        tip = tips.get(tag)
        walk = walks.get(tip)
        if walk is None:
            continue
        shas = set(json.loads(walk["text"])["stdout"].splitlines())
        if tip not in shas or not all(SHA.fullmatch(h) for h in shas):
            continue
        if merge_sha in shas:
            verdict = "包含"
            start = walk["text"].index(merge_sha, walk["text"].index('"stdout"'))
            end = start + len(merge_sha)
        else:
            closed = all(h in parents and all(p in shas for p in parents[h]) for h in shas)
            verdict = (
                "冻结历史不包含（已逐项核对所列提交的父记录）"
                if closed
                else "在已存历史中未找到，完整性未确认"
            )
            start = walk["text"].index('"rev-list"')
            end = walk["text"].index("]", start) + 1
        title = f"{tag} → {tip}，单标签 git rev-list 共 {len(shas)} 项；{verdict} {merge_sha}"
        url = f"https://github.com/{walk['repo']}/compare/{merge_sha}...{quote(tag, safe='')}"
        yield fragment(walk, start, end, title, url)


def historical_passages(package, question, intent, paths):
    """A and B share direct lookups. Only recorded graph paths supply additional subjects."""
    sources = package["sources"]
    repo = package["manifest"]["repo"]
    if intent == "code":
        return python_method_passages(sources, repo, question)
    base = "https://api.github.com/repos/" + repo
    numbers = set(NUMBER.findall(question))
    graph_ids = {n for path in paths for n in path["entity_ids"]}
    if intent == "decision" and not graph_ids:
        return []
    graph_prs, commits = set(), set()
    for entity in package["entities"]:
        if entity["id"] in graph_ids and entity["type"] == "PullRequest":
            graph_prs.add(str(entity["properties"].get("number", entity["key"])))
        if entity["id"] in graph_ids and entity["type"] == "Commit":
            commits.add(entity["properties"].get("sha", entity["key"]))
    cutoff_match = CUTOFF.search(question)
    cutoff_value = cutoff_match[1] if cutoff_match else None
    if cutoff_value and len(cutoff_value) == 10:
        cutoff_value += "T23:59:59.999999Z"
    cutoff = instant(cutoff_value)
    tags = {v.lower().removeprefix("v") for v in VERSION.findall(question)}
    releases = []
    fragments = []
    if intent in {"release", "membership"}:
        records = list(release_records(sources, repo, cutoff))
        for rec in records:
            row = rec[0]
            version = row["tag_name"].lower().removeprefix("v")
            if intent == "release" and version not in tags:
                continue
            if row.get("prerelease") and not (
                intent == "release"
                and (re.search(r"预发布|候选|pre.?release", question, re.I)
                     or re.search(r"(?:rc|a|b)\d+$", version))
            ):
                continue
            releases.append(rec)
        releases.sort(key=lambda rec: rec[0]["published_at"])
        if intent == "release":
            if releases:
                return [release_fragment(*r, compact=False) for r in releases]
            official = sorted(
                (r for r in records if not r[0].get("prerelease")),
                key=lambda rec: rec[0]["published_at"], reverse=True,
            )
            excerpts = [release_fragment(*r, compact=True) for r in official[:7]]
            if excerpts:
                versions = ", ".join(r[0]["tag_name"] for r in official[:7])
                list_label = "正式记录" if len(official) <= 7 else "最近七条正式记录"
                excerpts[0]["title"] = (
                    f"已冻结 GitHub Releases 中的{list_label}：{versions}。"
                    f"共 {len(official)} 条，结论限于该清单。"
                    f"所问版本在已冻结记录中未找到。{excerpts[0]['title']}"
                )
            return excerpts
    for source in sources:
        if (
            source["kind"] in {"issue_body", "pr_body"}
            and source["url"].rsplit("/", 1)[-1] in numbers | graph_prs
        ):
            if source["text"] and intent != "decision":
                fragments.append(
                    fragment(source, 0, min(1500, len(source["text"])), source.get("title"))
                )
        if source["kind"] != "api_response" or not source["url"].startswith(base + "/pulls/"):
            continue
        number = source["url"][len(base + "/pulls/") :]
        if number not in numbers | graph_prs:
            continue
        raw = source["text"]
        block = re.search(
            r'(?m)^  "merge_commit_sha": [^\n]+,'
            r'(?:\n  "(?:mergeable|mergeable_state|merged)": [^\n]+,)*\n  "merged_at": [^\n]+',
            raw,
        )
        if block:
            # Include PR number in the GitHub endpoint and both merge fields in one quote.
            fragments.append(
                {**fragment(source, *block.span()), "acquisition_source": "pr_api_lookup"}
            )
    if intent == "membership":
        fragments.extend(release_fragment(*rec, compact=True) for rec in releases)
        for sha in sorted(commits):
            fragments.extend(ancestry_fragments(sources, releases, sha))
    else:
        for source in sources:
            meta = source.get("git_metadata") or {}
            cmd = meta.get("command", [])
            if (
                cmd[:2] == ["git", "diff-tree"]
                and "--name-status" in cmd
                and cmd[-1] in commits
                and meta.get("returncode") == 0
            ):
                url = f"https://github.com/{repo}/commit/{cmd[-1]}"
                title = f"文件变更 A 新增 / M 修改 / D 删除 / R 重命名 · {url}"
                raw = source["text"]
                fragments.append({**fragment(source, 0, min(3200, len(raw)), title, url),
                                  "acquisition_source": "git_diff_lookup"})
                if len(raw) > 3200:
                    for pattern in (r"(?:src/|lib/)[^\s\\]+", r"(?:tests?/|test_)[^\s\\]+"):
                        match = re.search(pattern, raw[3200:])
                        if match:
                            at = 3200 + match.start()
                            fragments.append(
                                fragment(
                                    source, max(0, at - 40), min(len(raw), at + 350), title, url
                                )
                            )
    return fragments


def decision_paths(package, question, limit=12, *, include_change_paths=True):
    """Select decisions by general IDF-weighted topic match, then expand 1-hop."""
    topic = decision_terms(question)
    entities = {e["id"]: e for e in package["entities"]}
    sources = {s["source_id"]: s for s in package["sources"]}
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    all_decisions = [e for e in package["entities"] if e["type"] == "Decision"]
    if not all_decisions:
        return []

    # Corpus-level IDF across all Decision nodes (zero repo-specific keywords).
    df = Counter()
    doc_meta = {}
    for decision in all_decisions:
        props = decision["properties"]
        subject = entities.get(props.get("subject_id"), {})
        title = subject.get("properties", {}).get("title") or ""
        title_terms = decision_terms(title)
        stmt_terms = decision_terms(props.get("statement") or "")
        rat_terms = decision_terms(props.get("rationale") or "")
        all_t = title_terms | stmt_terms | rat_terms
        for t in all_t:
            df[t] += 1
        doc_meta[decision["id"]] = (title_terms, stmt_terms, rat_terms, all_t)

    n_docs = len(all_decisions)
    idf = {t: math.log((n_docs + 1) / (count + 1)) + 1.0 for t, count in df.items()}

    # Pre-index execution links for scoring & 1-hop graph expansion.
    exec_subjects = set()
    thread_links = {}
    for edge in package["relations"]:
        etype = edge["type"]
        if etype in {"ClaimsToClose", "Closes", "MergedAs", "Touches"}:
            exec_subjects.add(edge["from_id"])
            exec_subjects.add(edge["to_id"])
        if etype in {"ClaimsToClose", "Closes"}:
            thread_links.setdefault(edge["from_id"], set()).add(edge["to_id"])
            thread_links.setdefault(edge["to_id"], set()).add(edge["from_id"])

    asks_rejected = bool(re.search(r"拒绝|否定|rejected|declined|not merged", question, re.I))
    asks_accepted = bool(
        re.search(r"最终|采纳|合并|改用|落地|accepted|merged|adopted|instead", question, re.I)
    )
    asks_removed = bool(
        re.search(r"移除|弃用|删除|改用|替换|removed?|deprecated?|replac\w*", question, re.I)
    )

    def score_decision(decision_id, props, matched_terms):
        title_t, stmt_t, rat_t, _ = doc_meta[decision_id]
        s = 0.0
        for term in matched_terms:
            w = idf.get(term, 1.0)
            if term in title_t:
                s += 2.5 * w
            if term in stmt_t:
                s += 2.0 * w
            if term in rat_t:
                s += 1.2 * w
        if props.get("rationale_status") == "stated":
            s += 1.0
        if props.get("subject_id") in exec_subjects:
            s += 1.2
        if asks_accepted and props.get("status") == "accepted":
            s += 1.5
        if asks_rejected and props.get("status") == "rejected":
            s += 1.5
        if asks_removed and props.get("action") in {"remove", "deprecate", "change"}:
            s += 1.0
        return s

    def earliest_time(props):
        times = [sources[evidence[i]["source_id"]].get("occurred_at") or ""
                 for i in props.get("statement_evidence_ids", [])
                 if i in evidence and evidence[i]["source_id"] in sources]
        return min(times, default="")

    seed_rows = []
    for decision in all_decisions:
        props = decision["properties"]
        _, _, _, all_t = doc_meta[decision["id"]]
        if topic:
            if not (topic <= all_t):
                continue
            rel_score = score_decision(decision["id"], props, topic)
        else:
            if asks_rejected and props.get("status") != "rejected":
                continue
            if asks_removed and props.get("action") not in {"remove", "deprecate"}:
                continue
            if props.get("rationale_status") != "stated":
                continue
            rel_score = 1.0 if props.get("subject_id") in exec_subjects else 0.0
        seed_rows.append((-rel_score, earliest_time(props), decision["id"], props))

    # Fallback only when >= 3 topic terms and all rare terms + >= 2 terms match
    # (never on 1-2 term queries).
    if topic and not seed_rows and len(topic) >= 3:
        rarest = max(topic, key=lambda t: idf.get(t, 0.0))
        if df.get(rarest, 0) > 0:
            for decision in all_decisions:
                _, _, _, all_t = doc_meta[decision["id"]]
                matched = topic & all_t
                if rarest in matched and len(matched) >= 2:
                    props = decision["properties"]
                    rel_score = score_decision(decision["id"], props, matched)
                    seed_rows.append((-rel_score, earliest_time(props), decision["id"], props))

    if not seed_rows:
        return []

    distinct = {}
    for row in sorted(seed_rows):
        distinct.setdefault((row[3].get("subject_id"), row[3].get("status")), row)

    effective_limit = min(limit, 8) if topic else limit
    seed_chosen = list(distinct.values())
    if topic and len(seed_chosen) > effective_limit:
        seed_chosen = seed_chosen[:effective_limit]
    else:
        seed_chosen = seed_chosen[:effective_limit]

    # Stage 2: 1-hop graph neighbors + high-IDF co-topic expansion from top seed decisions.
    if topic and seed_chosen:
        top_seeds = seed_chosen[:4]
        linked_subjects = {
            neighbor
            for _, _, _, props in top_seeds
            for neighbor in thread_links.get(props.get("subject_id"), ())
        }
        rare_freq = Counter()
        rare_cutoff = max(5, int(0.03 * n_docs))
        for _, _, _, props in seed_chosen[:4]:
            title_t, stmt_t, _, _ = doc_meta[
                next(d for _, _, d, pr in seed_chosen[:4] if pr is props)
            ]
            for t in (title_t | stmt_t) - topic:
                if 2 <= df.get(t, 0) <= rare_cutoff and idf.get(t, 1.0) >= 3.0:
                    rare_freq[t] += 1
        shared_rare = {t: freq for t, freq in rare_freq.items() if freq >= 2}
        pool_rare = shared_rare or rare_freq
        top_rare = {
            t
            for t, _ in sorted(
                ((t, freq * idf[t]) for t, freq in pool_rare.items()),
                key=lambda x: (-x[1], x[0]),
            )[:6]
        }
        long_topic = {t for t in topic if len(t) >= 4}
        existing_keys = {(row[3].get("subject_id"), row[3].get("status")) for row in seed_chosen}
        expanded = []
        for decision in all_decisions:
            props = decision["properties"]
            key = (props.get("subject_id"), props.get("status"))
            if key in existing_keys:
                continue
            title_t, stmt_t, _, all_t = doc_meta[decision["id"]]
            is_linked = props.get("subject_id") in linked_subjects
            rare_hit = top_rare & all_t
            compound_hit = {
                t for t in long_topic
                if any(t in w and t != w for w in (title_t | stmt_t))
            }
            if not is_linked and not rare_hit and not compound_hit:
                continue
            exp_score = (
                score_decision(decision["id"], props, rare_hit)
                + sum(1.5 * idf.get(t, 1.0) for t in compound_hit)
                + (3.0 if is_linked else 0.0)
            )
            expanded.append((-exp_score, earliest_time(props), decision["id"], props))
        if expanded:
            exp_distinct = {}
            for row in sorted(expanded):
                exp_distinct.setdefault((row[3].get("subject_id"), row[3].get("status")), row)
            # Reserve slots for top seeds and splice in the highest-scoring expanded neighbors.
            keep_seeds = seed_chosen[: max(2, effective_limit - min(4, len(exp_distinct)))]
            chosen = [*keep_seeds, *list(exp_distinct.values())][:effective_limit]
        else:
            chosen = seed_chosen
    else:
        chosen = seed_chosen

    paths, subjects = [], set()
    outgoing = {}
    for edge in package["relations"]:
        if edge["type"] in {"ABOUT", "EVIDENCED_BY"}:
            outgoing.setdefault(edge["from_id"], []).append(edge)
    for _, _, did, props in chosen:
        subjects.add(props["subject_id"])
        for edge in outgoing.get(did, []):
            paths.append(dict(entity_ids=[did, edge["to_id"]], relation_ids=[edge["id"]]))
    if not include_change_paths:
        return paths
    return [*paths, *targeted_paths(package, subjects, "change", 3, 50)]


def decision_passages(package, question, paths):
    """Prioritize exact discussion and execution excerpts; status comes from the original text."""
    ordered_decisions = []
    seen_decisions = set()
    for p in paths:
        did = p["entity_ids"][0]
        if did.startswith("Decision:") and did not in seen_decisions:
            seen_decisions.add(did)
            ordered_decisions.append(did)
    decision_rank = {did: idx for idx, did in enumerate(ordered_decisions)}
    sources = {s["source_id"]: s for s in package["sources"]}
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    windows = {}
    sid_rank = {}
    for entity in package["entities"]:
        if entity["id"] not in decision_rank:
            continue
        rank = decision_rank[entity["id"]]
        props = entity["properties"]
        for id_ in [
            *props.get("statement_evidence_ids", []),
            *props.get("rationale_evidence_ids", []),
        ]:
            if id_ not in evidence:
                continue
            item = evidence[id_]
            sid = item["source_id"]
            if sid not in sources:
                continue
            sid_rank[sid] = min(sid_rank.get(sid, rank), rank)
            size = len(sources[sid]["text"])
            bounds = (0, size) if size <= 1800 else (
                max(0, item["start"] - 250), min(size, item["end"] + 380)
            )
            windows.setdefault(sid, []).append(bounds)

    discussion = []
    for sid, intervals in windows.items():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(end, merged[-1][1])
            else:
                merged.append((start, end))
        discussion.extend({**fragment(sources[sid], a, b), "acquisition_source": "graph_relation"}
                          for a, b in merged)
    discussion.sort(
        key=lambda f: (sid_rank.get(f["source_id"], 999), f["time"] or "", f["url"], f["start"])
    )
    execution = historical_passages(package, question, "decision", paths)
    # Reserve space so official API/diff execution evidence is not crowded out past 12,000 chars.
    lead_discussion, tail_discussion, used = [], [], 0
    for frag in discussion:
        if used + len(frag["quote"]) <= 7500:
            lead_discussion.append(frag)
            used += len(frag["quote"])
        else:
            tail_discussion.append(frag)
    return [*lead_discussion, *execution, *tail_discussion]
