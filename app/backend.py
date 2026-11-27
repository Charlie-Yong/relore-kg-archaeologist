"""Thin adapters to P1/P2. No collection, graph or model orchestration lives here."""

from historykg import pipeline
from historykg.contracts import BuildRequest_v1, QueryRequest_v1
from historykg.ingest.github import FULL_HISTORY
from historykg.query import query


def start(repo_url):
    config = pipeline.load_config()
    if config.get("budget", {}).get("mode") == "provider_balance":
        request = BuildRequest_v1(repo_url=repo_url, profile=FULL_HISTORY)
    else:
        request = BuildRequest_v1(repo_url=repo_url)
    return pipeline.start_build(request, config=config)


def get(job_id):
    return pipeline.get_build(job_id, config=pipeline.load_config())


def resume(job_id):
    return pipeline.resume_build(job_id, config=pipeline.load_config())


def ask(dataset_id, question, kind="search", *, answer_mode=None):
    filters = {"answer_mode": answer_mode} if answer_mode else {}
    result = query(
        QueryRequest_v1(dataset_id=dataset_id, question=question, kind=kind, filters=filters),
        config=pipeline.query_config(pipeline.load_config()),
    )
    return result.model_dump(mode="json")
