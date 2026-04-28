# DuckDB + Iceberg Quick Start

Welcome to DataPond! This notebook demonstrates how to query Iceberg tables using DuckDB.

**Why DuckDB?**
- 🚀 **10x faster** than Spark for small-medium queries
- 💻 **No cluster needed** - runs locally in your notebook
- 🔌 **Zero setup** - works out of the box
- 🐼 **Pandas compatible** - seamless integration

## Quick Start (30 seconds)

```python
# Already imported for you!
from iceberg_helper import q, sql

# Query Iceberg table (sub-second!)
df = q('analytics/events', where="country = 'KR'", limit=1000)
print(f"Rows: {len(df):,}")
df.head()
```

## Method 1: Ultra-Short Query (Recommended)

```python
# Simple filter
df = q('analytics/events', where="date >= '2026-04-01'", limit=1000)

# Multiple conditions
df = q('analytics/events', 
       where="country = 'KR' AND event_type = 'page_view'",
       limit=5000)

# No limit (careful!)
df = q('analytics/events', where="date = '2026-04-28'")
```

## Method 2: Full SQL Query

```python
# Complex aggregation
result = sql("""
    SELECT 
        country,
        COUNT(DISTINCT user_id) as unique_users,
        COUNT(*) as total_events,
        AVG(session_duration) as avg_duration
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
    WHERE date >= '2026-04-01'
    GROUP BY country
    ORDER BY total_events DESC
""")

result
```

## Method 3: Pandas Integration

```python
import pandas as pd

# Small lookup table (Pandas)
lookup = pd.DataFrame({
    'country_code': ['KR', 'US', 'JP'],
    'country_name': ['Korea', 'United States', 'Japan'],
    'region': ['APAC', 'Americas', 'APAC']
})

# DuckDB can query Pandas DataFrames directly!
result = sql("""
    SELECT 
        e.user_id,
        e.event_type,
        l.country_name,
        l.region
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events') e
    JOIN lookup l ON e.country = l.country_code
    WHERE e.date >= '2026-04-01'
    LIMIT 1000
""")

result
```

## Visualization

```python
import matplotlib.pyplot as plt

# Query
df = sql("""
    SELECT country, COUNT(*) as events
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
    WHERE date >= '2026-04-01'
    GROUP BY country
    ORDER BY events DESC
    LIMIT 10
""")

# Plot
df.plot(kind='bar', x='country', y='events', figsize=(12, 6))
plt.title('Events by Country')
plt.ylabel('Event Count')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

## Performance Tips

### When to use DuckDB vs Spark

```python
# DuckDB (< 10GB data): Sub-second
df = q('analytics/events', where="date = '2026-04-28'")  # ~100MB

# DuckDB (10-100GB data): Minute-scale
df = q('analytics/events', where="date >= '2026-04-01'")  # ~10GB

# Spark (> 100GB data): Use for very large datasets
# spark.sql("SELECT * FROM iceberg.analytics.events WHERE date >= '2026-01-01'")
```

### Optimization: Partition Filtering

```python
# ✅ GOOD: Uses partition pruning (fast!)
df = q('analytics/events', where="date = '2026-04-28' AND country = 'KR'")

# ❌ BAD: Full table scan (slow!)
df = q('analytics/events', where="user_id = 12345")

# 💡 Always filter on partition columns first (date, country, etc.)
```

## Table Statistics

```python
from iceberg_helper import table_stats

# Get row count
stats = table_stats('analytics/events')
print(f"Total rows: {stats['row_count']:,}")
```

## Common Patterns

### Time Series Analysis

```python
daily_stats = sql("""
    SELECT 
        date,
        COUNT(DISTINCT user_id) as dau,
        COUNT(*) as events,
        COUNT(*) / COUNT(DISTINCT user_id) as events_per_user
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
    WHERE date >= '2026-04-01' AND date < '2026-05-01'
    GROUP BY date
    ORDER BY date
""")

daily_stats.plot(x='date', y='dau', figsize=(14, 6))
plt.title('Daily Active Users')
plt.show()
```

### Funnel Analysis

```python
funnel = sql("""
    SELECT 
        event_type,
        COUNT(DISTINCT user_id) as users
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
    WHERE date = '2026-04-28'
        AND event_type IN ('page_view', 'add_to_cart', 'checkout', 'purchase')
    GROUP BY event_type
""")

funnel
```

### Cohort Analysis

```python
cohorts = sql("""
    SELECT 
        DATE_TRUNC('week', first_seen) as cohort_week,
        COUNT(DISTINCT user_id) as cohort_size
    FROM (
        SELECT 
            user_id,
            MIN(timestamp) as first_seen
        FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
        GROUP BY user_id
    )
    WHERE first_seen >= '2026-04-01'
    GROUP BY cohort_week
    ORDER BY cohort_week
""")

cohorts
```

## Next Steps

1. **Explore your data**: Try `q('your_table')` on different tables
2. **Write complex queries**: Use `sql()` for advanced analytics
3. **Visualize results**: matplotlib, seaborn, plotly
4. **Switch to Spark**: For > 100GB datasets, use Spark instead

## Need Help?

- **DuckDB Docs**: https://duckdb.org/docs/
- **Iceberg Docs**: https://iceberg.apache.org/docs/latest/
- **DataPond Docs**: Check `/home/jovyan/work/examples/`

Happy analyzing! 🦆📊
