"""Thin adapters to P1/P2. No collection, graph or model orchestration lives here."""

from historykg import pipeline
from historykg.contracts import BuildRequest_v1, QueryRequest_v1
from historykg.query import query


def start(repo_url):
    return pipeline.start_build(BuildRequest_v1(repo_url=repo_url), config=pipeline.load_config())


def get(job_id):
    return pipeline.get_build(job_id, config=pipeline.load_config())


def resume(job_id):
    return pipeline.resume_build(job_id, config=pipeline.load_config())


def ask(dataset_id, question, kind="search"):
    result = query(QueryRequest_v1(dataset_id=dataset_id, question=question, kind=kind),
                   config=pipeline.load_config())
    return result.model_dump(mode="json")
