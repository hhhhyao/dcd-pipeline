# pipe_performance

Reusable local helpers for profiling and comparing DCD pipe experiments.

These modules are intentionally repo-level tools. Production pipes should stay
self-contained and should not import `tools/pipe_performance` at runtime.

Main modules:

- `profiling.py`: timing profile collection and JSON writing.
- `lance_io.py`: generic stream-once Lance writer and narrow-column scans.
- `fingerprint.py`: logical Lance/JSONL fingerprints for output comparison.
- `workspace.py`: run directory creation and code snapshots.
- `reports.py`: lightweight JSON/CSV/HTML compare reports.
