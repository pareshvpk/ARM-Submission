# Round 3 simulation: alert policy and warning-clause filter

Counts only. base = alert on medium or high; policy = new alert policy; both = policy + warning-clause filter.
PC scoring: PyTorch fp32, URL-indicator fallback (no URL model).

## shipped_v5

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 30.0 % / 13.5 % | 13.9 % / 13.5 % | 13.9 % / 13.5 % | 21.7 % / 13.5 % |
| test|all | 1596 | 54.7 % / 9.0 % | 11.3 % / 9.0 % | 11.3 % / 9.0 % | 23.0 % / 9.0 % |
| test|promotional | 69 | 44.9 % / 10.1 % | 17.4 % / 10.1 % | 17.4 % / 10.1 % | 20.3 % / 10.1 % |
| test|unknown | 1297 | 59.6 % / 8.2 % | 10.6 % / 8.2 % | 10.6 % / 8.2 % | 23.4 % / 8.2 % |
| test|genuine|Tamil | 70 | 55.7 % / 34.3 % | 34.3 % / 34.3 % | 34.3 % / 34.3 % | 45.7 % / 34.3 % |
| dev|genuine | 291 | 15.5 % / 6.5 % | 8.2 % / 6.5 % | 8.2 % / 6.5 % | 12.4 % / 6.5 % |
| dev|all | 1416 | 44.8 % / 14.0 % | 22.5 % / 14.0 % | 22.3 % / 13.9 % | 31.7 % / 14.0 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.935 / 0.5 % | 0.926 / 0.2 % | 0.912 / 0.2 % | 0.930 / 0.4 % |
| Hinglish | 0.932 / 0.0 % | 0.862 / 0.0 % | 0.862 / 0.0 % | 0.914 / 0.0 % |
| Tamil | 0.940 / 31.2 % | 0.896 / 0.0 % | 0.896 / 0.0 % | 0.896 / 0.0 % |
| Hindi | 0.964 / 12.8 % | 0.822 / 4.2 % | 0.822 / 4.2 % | 0.938 / 11.8 % |
| Overall | 0.765 / 11.2 % | 0.585 / 0.4 % | 0.584 / 0.4 % | 0.622 / 1.7 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 56 / 58 | 54 / 57 | 54 / 57 | 55 / 58 |
| RBI advisories alerted | 11 of 12 | 5 of 12 | 4 of 12 | 6 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

## finetuned_run3

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

## finetuned_run4

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 7.4 % / 1.3 % | 1.7 % / 1.3 % | 1.7 % / 1.3 % | 3.0 % / 1.3 % |
| test|all | 1596 | 47.0 % / 1.7 % | 4.5 % / 1.7 % | 4.5 % / 1.7 % | 6.2 % / 1.7 % |
| test|promotional | 69 | 49.3 % / 10.1 % | 20.3 % / 10.1 % | 20.3 % / 10.1 % | 21.7 % / 10.1 % |
| test|unknown | 1297 | 53.9 % / 1.3 % | 4.2 % / 1.3 % | 4.2 % / 1.3 % | 5.9 % / 1.3 % |
| test|genuine|Tamil | 70 | 1.4 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| dev|genuine | 291 | 1.7 % / 0.0 % | 0.7 % / 0.0 % | 0.7 % / 0.0 % | 0.7 % / 0.0 % |
| dev|all | 1416 | 37.9 % / 1.6 % | 11.4 % / 1.6 % | 11.2 % / 1.6 % | 12.2 % / 1.6 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.876 / 0.0 % | 0.854 / 0.0 % | 0.838 / 0.0 % | 0.873 / 0.0 % |
| Hinglish | 0.882 / 0.0 % | 0.694 / 0.0 % | 0.694 / 0.0 % | 0.826 / 0.0 % |
| Tamil | 1.000 / 0.0 % | 0.973 / 0.0 % | 0.973 / 0.0 % | 0.978 / 0.0 % |
| Hindi | 0.824 / 0.0 % | 0.626 / 0.0 % | 0.626 / 0.0 % | 0.788 / 0.0 % |
| Overall | 0.770 / 7.1 % | 0.547 / 0.2 % | 0.546 / 0.2 % | 0.674 / 3.0 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 58 / 59 | 56 / 58 | 56 / 58 | 58 / 59 |
| RBI advisories alerted | 12 of 12 | 5 of 12 | 4 of 12 | 5 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

