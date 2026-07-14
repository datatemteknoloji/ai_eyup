# AIOps Pipeline

ainew's AIOps pipeline automatically detects metric anomalies, groups them into events, escalates to incidents, and generates AI root cause analysis — all without manual intervention.

---

## How it works

```
Prometheus / Node Exporter
    │  metrics scraped every 1 min
    ▼
Background task (5-min tick)
    │  stores MetricRecord in TimescaleDB
    ▼
Anomaly Detector
    │  Z-score + IQR per metric per server
    │  threshold: |z| > 2.5 OR IQR outlier
    ▼
AnomalyEvent created
    │
    ▼
Event Router
    │  groups related anomalies → Event
    │  severity 1–4 based on metric type + magnitude
    ▼
Incident Auto-Open
    │  severity ≥ 3 → new Incident
    │  LangGraph RCA chain → Ollama
    ▼
Incident with AI-generated Root Cause Analysis
```

The pipeline runs automatically. You don't configure individual rules — the system learns normal baseline per server and flags deviations.

---

## Anomaly detection algorithm

Each metric (CPU%, memory%, disk%, network I/O) is checked using two methods:

**Z-score:** `z = (value - mean) / std_dev` — flags values more than 2.5 standard deviations from the server's historical mean (rolling 2-hour window).

**IQR:** `value < Q1 - 1.5 * IQR` or `value > Q3 + 1.5 * IQR` — catches outliers that don't fit a normal distribution (e.g. sudden spike in a normally flat metric).

If either method flags a reading, an `AnomalyEvent` is created with:
- `severity`: 1 (minor) to 4 (critical)
- `score`: the Z-score or IQR multiplier
- `metric`: which metric triggered it
- `value`: the anomalous reading

---

## Severity levels

| Severity | Meaning | Auto-creates Incident? |
|---|---|---|
| 1 | Minor deviation — informational | No |
| 2 | Moderate — worth monitoring | No |
| 3 | High — requires attention | Yes |
| 4 | Critical — immediate action | Yes |

Severity is calculated from metric type and magnitude:
- `cpu_percent > 90%` → severity 4
- `disk_percent > 95%` → severity 4
- `mem_percent > 85%` → severity 3
- Log anomalies (unusual error patterns) → severity 2–3

---

## Events vs Incidents

**Events** group related anomalies from the same server or time window. One network outage on a server might create 5 AnomalyEvents (CPU spike, connection errors, disk I/O wait) but a single Event.

**Incidents** are actionable items requiring a human decision. They escalate from Events automatically when severity ≥ 3. Each incident gets:
- A title (AI-generated)
- A root cause analysis (AI-generated)
- A status flow: `open` → `investigating` → `resolved`

---

## Root Cause Analysis

When an Incident is created, a LangGraph chain runs:

1. Fetches last 1 hour of metrics for the affected server
2. Fetches recent Events (correlated time window)
3. Searches the RAG store for matching runbooks or historical incidents
4. Calls Ollama with all context: "Given these metrics and events, what is the likely root cause?"
5. Stores the RCA text in `Incident.ai_rca`

The RCA is visible in the Incidents page when you open an incident detail.

---

## How-to: View and triage anomalies

1. Open **Anomaly Detection** in the sidebar
2. The pipeline status shows:
   - Active anomalies (currently detected)
   - Active events (grouped anomalies)
   - Auto-opened incidents
3. Click any anomaly to see the metric graph around the event time
4. Click **Analyze Group** to run AI analysis on a set of related events

---

## How-to: Manage incidents

1. Open **Incidents** in the sidebar
2. Open incidents are shown with severity badge and AI RCA
3. Click an incident to:
   - Read the RCA
   - Change status to **İnceleniyor** (Investigating)
   - Add notes
   - Resolve or escalate
4. Resolved incidents are archived but visible with filter

---

## How-to: Reduce false positives

If a server consistently generates false anomalies (e.g. a batch job that always spikes CPU at 2am):

1. Open the Event in the Events page
2. Click **Bilinen Olay** (Mark as Known)
3. Future events with the same pattern on that server are suppressed

---

## Explanation: Why Z-score + IQR, not static thresholds

Static thresholds (`cpu > 80% = alert`) produce too many false positives on servers that legitimately run hot. A database server might normally run at 75% CPU — an alert at 80% would be noise.

Z-score adapts to each server's baseline. If a server normally runs at 75% CPU, a spike to 90% is flagged. If it normally runs at 20%, even 50% gets flagged.

IQR handles non-normal distributions (common for disk I/O, network) where Z-score would miss sudden step changes.

**Trade-off:** Adaptive methods need a warm-up period (a few hours of data) before they're accurate. Brand-new servers may generate noise in the first hour.

---

## Related

- [Events API reference](../api-reference.md#events-aiops)
- [Incidents API reference](../api-reference.md#incidents)
- [Anomaly Detection API](../api-reference.md#anomaly-detection)
