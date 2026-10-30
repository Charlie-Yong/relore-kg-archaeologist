"""P6 evaluation: immutable references, complete judgments and reproducible counts."""

from .metrics import evidence_recall, score_extraction, score_qa


def main(argv=None):
    from .cli import main as entry

    return entry(argv)


__all__ = ["score_extraction", "score_qa", "evidence_recall", "main"]
