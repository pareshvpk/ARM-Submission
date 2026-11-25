# Round 3 simulation: alert policy and warning-clause filter

Counts only. base = alert on medium or high; policy = new alert policy; both = policy + warning-clause filter.
PC scoring: PyTorch fp32, URL-indicator fallback (no URL model).

## shipped_v5

| Real SMS slice | n | base: alert / HIGH | policy: alert / HIGH | both: alert / HIGH |
|---|---|---|---|---|
| test|genuine | 230 | 30.0 % / 13.5 % | 13.9 % / 13.5 % | 13.9 % / 13.5 % |
| test|all | 1596 | 54.7 % / 9.0 % | 11.3 % / 9.0 % | 11.3 % / 9.0 % |
| test|promotional | 69 | 44.9 % / 10.1 % | 17.4 % / 10.1 % | 17.4 % / 10.1 % |
| test|unknown | 1297 | 59.6 % / 8.2 % | 10.6 % / 8.2 % | 10.6 % / 8.2 % |
| test|genuine|Tamil | 70 | 55.7 % / 34.3 % | 34.3 % / 34.3 % | 34.3 % / 34.3 % |
| dev|genuine | 291 | 15.5 % / 6.5 % | 8.2 % / 6.5 % | 8.2 % / 6.5 % |
| dev|all | 1416 | 44.8 % / 14.0 % | 22.5 % / 14.0 % | 22.3 % / 13.9 % |

| Held-out slice | base: recall / false alarms | policy | both |
|---|---|---|---|
| English | 0.935 / 0.5 % | 0.926 / 0.2 % | 0.912 / 0.2 % |
| Hinglish | 0.932 / 0.0 % | 0.862 / 0.0 % | 0.862 / 0.0 % |
| Tamil | 0.940 / 31.2 % | 0.896 / 0.0 % | 0.896 / 0.0 % |
| Hindi | 0.964 / 12.8 % | 0.822 / 4.2 % | 0.822 / 4.2 % |
| Overall | 0.765 / 11.2 % | 0.585 / 0.4 % | 0.584 / 0.4 % |

| Check | base | policy | both |
|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 56 / 58 | 54 / 57 | 54 / 57 |
| RBI advisories alerted | 11 of 12 | 5 of 12 | 4 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 |

## finetuned_run1

| Real SMS slice | n | base: alert / HIGH | policy: alert / HIGH | both: alert / HIGH |
|---|---|---|---|---|
| test|genuine | 230 | 23.5 % / 3.0 % | 3.9 % / 3.0 % | 3.9 % / 3.0 % |
| test|all | 1596 | 53.7 % / 3.7 % | 6.4 % / 3.7 % | 6.4 % / 3.7 % |
| test|promotional | 69 | 49.3 % / 10.1 % | 20.3 % / 10.1 % | 20.3 % / 10.1 % |
| test|unknown | 1297 | 59.3 % / 3.5 % | 6.1 % / 3.5 % | 6.1 % / 3.5 % |
| test|genuine|Tamil | 70 | 28.6 % / 0.0 % | 1.4 % / 0.0 % | 1.4 % / 0.0 % |
| dev|genuine | 291 | 18.6 % / 2.4 % | 5.8 % / 2.4 % | 5.8 % / 2.4 % |
| dev|all | 1416 | 51.5 % / 10.0 % | 20.4 % / 10.0 % | 20.3 % / 10.0 % |

| Held-out slice | base: recall / false alarms | policy | both |
|---|---|---|---|
| English | 0.958 / 1.5 % | 0.942 / 0.0 % | 0.927 / 0.0 % |
| Hinglish | 0.942 / 0.0 % | 0.806 / 0.0 % | 0.806 / 0.0 % |
| Tamil | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.0 % |
| Hindi | 0.944 / 1.2 % | 0.696 / 0.0 % | 0.696 / 0.0 % |
| Overall | 0.883 / 16.1 % | 0.601 / 0.8 % | 0.600 / 0.8 % |

| Check | base | policy | both |
|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 59 / 59 | 56 / 58 | 56 / 58 |
| RBI advisories alerted | 11 of 12 | 4 of 12 | 4 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 |

