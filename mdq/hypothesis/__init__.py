"""
Hypothesis strategies for generating MDQ questions and exams. Requires
the `mdq[hypothesis]` extra.
"""

from .documents import exams, questions

__all__ = [
    "exams",
    "questions",
]
