"""Public contract 1.4.1; record validation is completed by historykg.io."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import normalize_repo, source_id, text_hash

CONTRACT_VERSION = "1.4.1"
STAGES = ("discover", "collect", "code", "extract", "validate", "index_graph")
ENTITY_TYPES = ("Project", "Release", "Issue", "PullRequest", "Commit", "File", "Decision")
RELATION_ENDPOINTS = {
    "HasRelease": ({"Project"}, {"Release"}),
    "ClaimsToClose": ({"PullRequest"}, {"Issue"}),
    "Closes": ({"PullRequest"}, {"Issue"}),
    "MergedAs": ({"PullRequest"}, {"Commit"}),
    "Touches": ({"Commit"}, {"File"}),
    "ReachableIn": ({"Commit"}, {"Release"}),
    "MentionsPR": ({"Release"}, {"PullRequest"}),
    "ChangesTo": ({"File"}, {"File"}),
    "Imports": ({"File"}, {"File"}),
    "ABOUT": ({"Decision"}, {"Project", "Issue", "PullRequest", "File"}),
    "EVIDENCED_BY": ({"Decision"}, {"SourceDocument"}),
}


class Record(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class VersionedRecord(Record):
    contract_version: Literal["1.4.1"] = CONTRACT_VERSION


class SourceDocument(VersionedRecord):
    dataset_id: str
    source_id: str
    repo: str
    kind: Literal["issue_body", "pr_body", "comment", "review", "review_comment",
                  "release_note", "commit_message", "code", "git_output", "api_response"]
    url: str
    text: str
    text_sha256: str
    retrieved_at: str
    occurred_at: str | None
    author: str | None
    trust_tier: Literal["authoritative", "reported", "machine", "unknown"]
    origin_key: str
    api_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def frozen_text(self):
        if self.repo != normalize_repo(self.repo) or "\r" in self.text:
            raise ValueError("repo须规范化，冻结文本只允许LF换行")
        if self.text_sha256 != text_hash(self.text):
            raise ValueError("text_sha256不匹配")
        if self.source_id != source_id(self.repo, self.origin_key, self.text_sha256):
            raise ValueError("source_id不匹配C5稳定ID")
        if self.kind == "api_response":
            metadata = self.api_metadata or {}
            if not {"method", "endpoint", "params", "response_status"} <= metadata.keys():
                raise ValueError("api_response缺少api_metadata")
            if metadata["method"] != "GET":
                raise ValueError("api_response只能保存官方只读GET元数据")
        return self


class SourceUnit(Record):
    unit_id: str
    dataset_id: str
    topic_group: str
    source_ids: list[str]
    completeness: Literal["complete", "partial", "unread"]
    missing_parts: list[str]
    origin_thread: str

    @model_validator(mode="after")
    def completeness_matches(self):
        if self.completeness == "complete" and self.missing_parts:
            raise ValueError("complete单元不能有missing_parts")
        return self


class Evidence(Record):
    evidence_id: str
    dataset_id: str
    source_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class Entity(VersionedRecord):
    dataset_id: str
    id: str
    repo: str
    type: Literal["Project", "Release", "Issue", "PullRequest", "Commit", "File", "Decision"]
    key: Any
    properties: dict[str, Any]
    evidence_ids: list[str]


class Relation(VersionedRecord):
    dataset_id: str
    id: str
    type: Literal["HasRelease", "ClaimsToClose", "Closes", "MergedAs", "Touches",
                  "ReachableIn", "MentionsPR", "ChangesTo", "Imports", "ABOUT", "EVIDENCED_BY"]
    from_id: str
    to_id: str
    properties: dict[str, Any]
    evidence_ids: list[str]
    method: Literal["github_api", "git", "ast", "text_rule", "llm"]
    extractor_version: str
    occurred_at: str | None


class Subject(Record):
    subject_id: str
    repo: str
    entity_type: Literal["Project", "Issue", "PullRequest", "File"]
    display_name: str
    aliases: list[str]
    source_ids: list[str]


class BuildRequest(Record):
    repo_url: str
    profile: str = "course_small_v1"

    @field_validator("repo_url")
    @classmethod
    def github_url(cls, value):
        return "https://github.com/" + normalize_repo(value, require_url=True)


class BuildJob(VersionedRecord):
    job_id: str
    repo: str
    profile_version: str
    dataset_id: str | None
    status: Literal["queued", "running", "ready", "partial", "failed", "unsupported", "blocked"]
    stage: Literal["discover", "collect", "code", "extract", "validate", "index_graph"]
    created_at: str
    updated_at: str
    counts: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    gaps: list[Any] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    resume_from: str | None = None


class QueryRequest(Record):
    dataset_id: str
    question: str
    kind: Literal["search", "trace", "timeline", "dependencies", "compare"] = "search"
    seed_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class QueryResult(VersionedRecord):
    dataset_id: str
    query: Any
    status: Literal["ok", "empty", "unsupported", "error"]
    claims: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    paths: list[dict[str, Any]]
    gaps: list[Any]
    timings_ms: dict[str, Any]
    error: dict[str, Any] | None


# Contract-labelled aliases are available for external consumers.
SourceDocument_v1 = SourceDocument
SourceUnit_v1 = SourceUnit
Evidence_v1 = Evidence
Entity_v1 = Entity
Relation_v1 = Relation
BuildRequest_v1 = BuildRequest
BuildJob_v1 = BuildJob
QueryRequest_v1 = QueryRequest
QueryResult_v1 = QueryResult
