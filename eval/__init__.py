"""ClaimSense evaluation package (L13, L15). Owner: Eval & Red-Team.

    eval.harness        the scoring harness. `python -m eval.harness.suite` runs everything.
    eval.calibration    the Cohen's kappa workflow for the judge
    eval.tools          supporting tools, not on the scoring path (the report DOCX builder)

The harness observes the product, never the reverse. One exception: the dev-policy seeder
(`claimsense.mcp_servers.seed_dev_policies`, a setup tool) reuses `eval.harness`'s fixture mapping,
so the API image copies `eval/harness` for it. See `eval/README.md` to run it, and
`docs/EVAL_HARNESS_REPORT.md` for the full documentation.
"""
