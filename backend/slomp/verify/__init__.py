"""Live verification: re-check Slomp's output against the sources, through fetch paths independent of the pipeline.

    slomp verify --iteration N [--tests 200] [--seed S]
    python -m slomp.verify.runner --judge N labels.json     # merge blind industry labels for iteration N
    slomp verify --iteration N --plan regulars              # regular deals: see regulars_run.py
"""
