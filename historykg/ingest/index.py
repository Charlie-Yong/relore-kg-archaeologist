"""Local discussion index for bounded course datasets, with the same ranking on both DBs."""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import (
    BigInteger,
    Column,
    Connection,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url

from .github import ThreadPayload

metadata = MetaData()
documents = Table(
    "hg_discussion_documents",
    metadata,
    Column("repo", String, primary_key=True),
    Column("number", BigInteger, primary_key=True, autoincrement=False),
    Column("source_type", String, primary_key=True),
    Column("source_id", String, primary_key=True),
    Column("thread_type", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("author", String),
    Column("trust", String, nullable=False),
    Column("occurred_at", String),
)


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("采集索引支持 SQLite 或 PostgreSQL。")
    return create_engine(url)


def counts(engine: Engine, repo: str | None = None) -> dict[str, int]:
    query = select(
        func.count().filter(documents.c.source_type == "body"), func.count()
    ).select_from(documents)
    if repo is not None:
        query = query.where(documents.c.repo == repo)
    with engine.connect() as conn:
        threads, total = conn.execute(query).one()
    return {"threads": threads, "documents": total}


def write_thread(conn: Connection, payload: ThreadPayload) -> int:
    """Refresh only this thread; an unread part does not imply deletion."""
    scope = (documents.c.repo == payload.repo, documents.c.number == payload.number)
    old = {
        (r["source_type"], r["source_id"]): dict(r)
        for r in conn.execute(select(documents).where(*scope)).mappings()
    }
    base = (
        payload.thread.get("html_url")
        or f"https://github.com/{payload.repo}/"
        f"{'pull' if payload.thread_type == 'pr' else 'issues'}/{payload.number}"
    )
    changed, seen = [], set()
    for kind, source_id, raw in payload.objects():
        key = kind, source_id
        seen.add(key)
        row = {
            "repo": payload.repo,
            "number": payload.number,
            "source_type": kind,
            "source_id": source_id,
            "thread_type": payload.thread_type,
            "title": payload.thread.get("title") or "",
            "text": (raw.get("body") or "").replace("\r\n", "\n").replace("\r", "\n"),
            "url": raw.get("html_url") or base,
            "author": (raw.get("user") or {}).get("login"),
            "trust": "authoritative"
            if raw.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
            else "reported",
            "occurred_at": raw.get("submitted_at") or raw.get("created_at"),
        }
        if row != old.get(key):
            changed.append(row)
    for kind, source_id in old.keys() - seen:
        if kind not in payload.unread:
            conn.execute(
                delete(documents).where(
                    *scope, documents.c.source_type == kind, documents.c.source_id == source_id
                )
            )
    if changed:
        dialect = postgresql if conn.dialect.name == "postgresql" else sqlite
        statement = dialect.insert(documents)
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=list(documents.primary_key),
                set_={
                    col.name: statement.excluded[col.name]
                    for col in documents.columns
                    if not col.primary_key
                },
            ),
            changed,
        )
    return len(changed)


SEARCH_BACKEND = "historykg.collector.search_history"
SEARCH_METHOD = "discussion_keywords_v1"
_STOPWORDS = set(
    "a an the in of to for and or on at as is was were are be with this that "
    "what why how when where does did which please explain".split()
)


def _words(text: str):
    for word in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.casefold()):
        if "\u3400" <= word[0] <= "\u9fff":
            yield from (word[i : i + 2] for i in range(max(1, len(word) - 1)))
        elif word not in _STOPWORDS:
            yield word


def search(engine: Engine, repo: str, question: str, limit: int) -> list[dict]:
    terms = set(_words(question))
    numbers = {int(value) for value in re.findall(r"#\s*(\d+)\b", question)}
    hits = []
    with engine.connect() as conn:
        for row in conn.execute(select(documents).where(documents.c.repo == repo)).mappings():
            body = row["source_type"] == "body"
            words = Counter(_words(row["text"]))
            title = set(_words(row["title"])) if body else set()
            score = sum(min(words[term], 3) for term in terms) + 4 * len(title & terms)
            if body and row["number"] in numbers:
                score += 12
            if not score:
                continue
            text = row["text"] or row["title"]
            positions = [pos for term in terms if (pos := text.lower().find(term)) >= 0]
            start = max(0, min(positions, default=0) - 60)
            hits.append(
                {
                    **{key: value for key, value in row.items() if key != "text"},
                    "score": score,
                    "snippet": text[start : start + 360],
                }
            )
    return sorted(hits, key=lambda h: (-h["score"], h["number"], h["source_type"], h["source_id"]))[
        :limit
    ]
