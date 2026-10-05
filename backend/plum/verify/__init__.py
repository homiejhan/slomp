"""Live verification: re-check Plum's output against the sources, through fetch paths independent of the pipeline.

    plum verify --iteration N [--tests 200] [--seed S]
    python -m plum.verify.runner --judge N labels.json     # merge blind industry labels for iteration N
"""
