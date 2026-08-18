# Brotto Benchmark

Last 3 runs. Tasks run on self-hosted sandboxes. 
No LLM-as-judge — every pass/fail is a Python check.

_No benchmark runs yet. Run `python -m brotto_orchestrator.bench.cli --task=login_form --model=haiku-4-5 --write-card` to populate._


Methodology: deterministic checks, no LLM-as-judge. Sandboxes are static HTML served on a free port.
