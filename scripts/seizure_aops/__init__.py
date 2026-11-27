"""Standalone seizure-AOP runner (relocated from the aop_wiki_cli CLI, issue #28).

The Behl seizure workbook pipeline processes one specific supplementary input
and is not meant for reuse, so it lives outside the installed library. It still
depends on the reusable library (``aop_wiki_cli.*``), including the shared
harmonization-sheet core in ``aop_wiki_cli.parsers.seizure_harmonization``.

Run the two commands it provides with::

    $ uv run python scripts/seizure_aops/runner.py collect-harmonized-seizure-aops
    $ uv run python scripts/seizure_aops/runner.py manually-review-matches <file.json>
"""
