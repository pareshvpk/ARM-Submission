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

## finetuned_run1

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 23.5 % / 3.0 % | 3.9 % / 3.0 % | 3.9 % / 3.0 % | 13.0 % / 3.0 % |
| test|all | 1596 | 53.7 % / 3.7 % | 6.4 % / 3.7 % | 6.4 % / 3.7 % | 20.9 % / 3.7 % |
| test|promotional | 69 | 49.3 % / 10.1 % | 20.3 % / 10.1 % | 20.3 % / 10.1 % | 26.1 % / 10.1 % |
| test|unknown | 1297 | 59.3 % / 3.5 % | 6.1 % / 3.5 % | 6.1 % / 3.5 % | 22.1 % / 3.5 % |
| test|genuine|Tamil | 70 | 28.6 % / 0.0 % | 1.4 % / 0.0 % | 1.4 % / 0.0 % | 11.4 % / 0.0 % |
| dev|genuine | 291 | 18.6 % / 2.4 % | 5.8 % / 2.4 % | 5.8 % / 2.4 % | 12.7 % / 2.4 % |
| dev|all | 1416 | 51.5 % / 10.0 % | 20.4 % / 10.0 % | 20.3 % / 10.0 % | 34.8 % / 10.0 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.958 / 1.5 % | 0.942 / 0.0 % | 0.927 / 0.0 % | 0.953 / 0.7 % |
| Hinglish | 0.942 / 0.0 % | 0.806 / 0.0 % | 0.806 / 0.0 % | 0.910 / 0.0 % |
| Tamil | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.0 % |
| Hindi | 0.944 / 1.2 % | 0.696 / 0.0 % | 0.696 / 0.0 % | 0.918 / 0.6 % |
| Overall | 0.883 / 16.1 % | 0.601 / 0.8 % | 0.600 / 0.8 % | 0.770 / 7.0 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 59 / 59 | 56 / 58 | 56 / 58 | 59 / 59 |
| RBI advisories alerted | 11 of 12 | 4 of 12 | 4 of 12 | 5 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

## finetuned_run2

| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |
|---|---|---|---|---|---|
| test|genuine | 230 | 23.9 % / 2.6 % | 3.9 % / 2.6 % | 3.9 % / 2.6 % | 11.3 % / 2.6 % |
| test|all | 1596 | 58.5 % / 3.7 % | 7.3 % / 3.7 % | 7.3 % / 3.7 % | 17.9 % / 3.7 % |
| test|promotional | 69 | 68.1 % / 10.1 % | 26.1 % / 10.1 % | 26.1 % / 10.1 % | 29.0 % / 10.1 % |
| test|unknown | 1297 | 64.1 % / 3.5 % | 6.9 % / 3.5 % | 6.9 % / 3.5 % | 18.4 % / 3.5 % |
| test|genuine|Tamil | 70 | 27.1 % / 0.0 % | 1.4 % / 0.0 % | 1.4 % / 0.0 % | 10.0 % / 0.0 % |
| dev|genuine | 291 | 16.8 % / 2.1 % | 3.8 % / 2.1 % | 3.8 % / 2.1 % | 12.0 % / 2.1 % |
| dev|all | 1416 | 57.8 % / 10.9 % | 21.3 % / 10.9 % | 21.2 % / 10.8 % | 32.9 % / 10.9 % |

| Held-out slice | base: recall / false alarms | policy | both | policy2 |
|---|---|---|---|---|
| English | 0.959 / 0.7 % | 0.945 / 0.2 % | 0.932 / 0.2 % | 0.958 / 0.2 % |
| Hinglish | 0.924 / 0.0 % | 0.828 / 0.0 % | 0.828 / 0.0 % | 0.906 / 0.0 % |
| Tamil | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.0 % | 1.000 / 0.0 % |
| Hindi | 0.962 / 2.4 % | 0.770 / 0.0 % | 0.770 / 0.0 % | 0.932 / 0.6 % |
| Overall | 0.890 / 19.6 % | 0.635 / 0.8 % | 0.633 / 0.8 % | 0.796 / 8.2 % |

| Check | base | policy | both | policy2 |
|---|---|---|---|---|
| Golden Tamil / Hindi correct of 60 | 59 / 57 | 57 / 58 | 57 / 58 | 58 / 59 |
| RBI advisories alerted | 12 of 12 | 5 of 12 | 4 of 12 | 5 of 12 |
| Phone test messages right | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 |

