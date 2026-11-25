# Round 3 simulation: alert policy and warning-clause filter

Counts only. base = alert on medium or high; policy = new alert policy; both = policy + warning-clause filter.
PC scoring: PyTorch fp32, URL-indicator fallback (no URL model).

## run3_full

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 10.0 % / 1.7 % | 1.7 % / 1.7 % | 1.7 % / 1.7 % | 1.7 % / 1.7 % |
| test|all | 1596 | 49.4 % / 2.5 % | 5.1 % / 2.5 % | 5.1 % / 2.5 % | 8.3 % / 2.5 % |
| test|promotional | 69 | 50.7 % / 10.1 % | 20.3 % / 10.1 % | 20.3 % / 10.1 % | 21.7 % / 10.1 % |
| test|unknown | 1297 | 56.3 % / 2.2 % | 4.9 % / 2.2 % | 4.9 % / 2.2 % | 8.7 % / 2.2 % |
| test|genuine|Tamil | 70 | 11.4 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| dev|genuine | 291 | 1.0 % / 0.0 % | 0.3 % / 0.0 % | 0.3 % / 0.0 % | 0.3 % / 0.0 % |
| dev|all | 1416 | 43.9 % / 1.4 % | 11.9 % / 1.4 % | 11.7 % / 1.4 % | 12.2 % / 1.4 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.904 / 0.7 % | 0.897 / 0.0 % | 0.882 / 0.0 % | 0.900 / 0.2 % |
| Hinglish | 0.886 / 0.6 % | 0.790 / 0.0 % | 0.790 / 0.0 % | 0.854 / 0.2 % |
| Tamil | 1.000 / 1.1 % | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.4 % |
| Hindi | 0.912 / 2.8 % | 0.750 / 0.0 % | 0.750 / 0.0 % | 0.890 / 1.4 % |
| Overall | 0.869 / 19.9 % | 0.639 / 1.9 % | 0.637 / 1.9 % | 0.796 / 11.4 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 57 / 59 | 58 / 58 | 58 / 58 | 58 / 59 |
| RBI advisories alerted | 11 of 12 | 6 of 12 | 5 of 12 | 8 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

## run3_pruned

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 10.0 % / 1.7 % | 1.7 % / 1.7 % | 1.7 % / 1.7 % | 1.7 % / 1.7 % |
| test|all | 1596 | 49.4 % / 2.5 % | 5.1 % / 2.5 % | 5.1 % / 2.5 % | 8.3 % / 2.5 % |
| test|promotional | 69 | 50.7 % / 10.1 % | 20.3 % / 10.1 % | 20.3 % / 10.1 % | 21.7 % / 10.1 % |
| test|unknown | 1297 | 56.4 % / 2.2 % | 4.9 % / 2.2 % | 4.9 % / 2.2 % | 8.7 % / 2.2 % |
| test|genuine|Tamil | 70 | 11.4 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| dev|genuine | 291 | 1.0 % / 0.0 % | 0.3 % / 0.0 % | 0.3 % / 0.0 % | 0.3 % / 0.0 % |
| dev|all | 1416 | 43.9 % / 1.4 % | 11.9 % / 1.4 % | 11.7 % / 1.4 % | 12.2 % / 1.4 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.904 / 0.7 % | 0.897 / 0.0 % | 0.882 / 0.0 % | 0.900 / 0.2 % |
| Hinglish | 0.886 / 0.6 % | 0.790 / 0.0 % | 0.790 / 0.0 % | 0.854 / 0.2 % |
| Tamil | 1.000 / 1.1 % | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.4 % |
| Hindi | 0.912 / 2.8 % | 0.750 / 0.0 % | 0.750 / 0.0 % | 0.890 / 1.4 % |
| Overall | 0.768 / 8.9 % | 0.578 / 0.3 % | 0.577 / 0.3 % | 0.665 / 3.3 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 57 / 59 | 58 / 58 | 58 / 58 | 58 / 59 |
| RBI advisories alerted | 11 of 12 | 6 of 12 | 5 of 12 | 8 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

