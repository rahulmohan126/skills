---
type: llm
focus: trace
weight: 1
---

parse_duration returns 5400 for '1h30m', 45 for '45s', 7200 for '2h' and 0 for '0s', and raises ValueError for 'abc'
