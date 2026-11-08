# UmbraEdit Benchmark Results

Machine description: Mac Mini (arm64, Apple Silicon), macOS, Python 3.12.16, PyQt6 6.12.0.

| Date | Words | Scenes | Open (s) | Index (s) | Largest Scene (s) | Peak Mem (MB) |
|------|-------|--------|----------|-----------|-------------------|---------------|
| *(run `python3 utils/umbra_bench.py --project <path>` and paste results here)* | | | | | | |

## How to Run

```bash
# Generate the benchmark project
python3 utils/umbra_gen_project.py --words 400000 --scenes 2000 \
    --characters 40 --places 20 --seed 7 --output /tmp/bench_project

# Run the benchmark
python3 utils/umbra_bench.py --project /tmp/bench_project
```

## Target Budgets

| Metric | Budget |
|--------|--------|
| Project open time | < 5 s |
| Index rebuild time | < 10 s |
| Largest scene open time | < 1 s |
| Peak memory | < 500 MB |
