---
name: nl2sql
description: Convert natural-language analytics questions into MySQL SELECT queries, execute them, and return results as markdown tables with short insights. Use when the user provides a MySQL connection (.db.yaml/database.yaml) and asks to query data.
metadata:
  openclaw:
    emoji: "🧮"
    requires:
      bins: ["mysql"]
    install:
      - id: brew
        kind: brew
        formula: mysql-client
        bins: ["mysql"]
        label: Install mysql client (brew)
---

# NL2SQL (MySQL)

Convert natural-language questions into safe, read-only MySQL queries, run them, and summarize results.

## Workflow

## Invocation in chat

- Use `/nl2sql ...` or `/skill nl2sql ...` to invoke this skill.
- `@nl2sql` mentions are not supported; if a user tries that, instruct them to use `/nl2sql` instead.
- If the user invokes `/skill nl2sql ...`, **do not** respond with “skill not available.” Treat it as an explicit request to run this workflow.

### 1) Load connection info

The user provides `.db.yaml` (preferred) or `database.yaml` in the workspace. Scripts auto-discover config in this order: `./.db.yaml`, `./database.yaml`, `~/.openclaw/workspace/.db.yaml`, `~/.openclaw/workspace/database.yaml`. `--config` is optional and overrides auto-discovery.

```yaml
databases:
  mysql:
    type: "mysql"
    host: "db-host"
    port: 3306
    database: "app_db"
    username: "app_user"
    password: "app_password"
    charset: "utf8mb4"
```

If `mysql` CLI is missing, fall back to a Python query runner (see "Python fallback").

### 2) Pull a focused schema (with cache)

If the schema is large, **always** pre-filter by keywords from the user query.
`schema.sh` now caches schema locally (default: `./.nl2sql/schema_cache.tsv`):
- Normal query: read cache first; if cache is missing, fetch from DB and save.
- Force refresh: use `--refresh` to fetch latest schema and overwrite cache.

```bash
./skills/scripts/schema.sh --keywords "order customer refund" --format markdown
```

```bash
./skills/scripts/schema.sh --refresh --keywords "order customer refund" --format markdown
```

If results are still too large, refine keywords or ask the user to clarify the target tables.

### 3) Generate SQL (read-only)

- Only `SELECT`/`WITH` queries are allowed.
- Avoid `SELECT *` unless the user explicitly wants full rows.
- The query runner adds a default `LIMIT 200` if none is present (use `--limit 0` to disable).
- Prefer explicit joins and use aliases.

### 4) Execute SQL and summarize (step-by-step output)

```bash
./skills/scripts/query.sh --sql "SELECT ..." --format markdown
```

**Step-by-step rule (mandatory):**

When executing this workflow, run it in clearly separated steps. **After each step produces an output, immediately post that output to the chat before continuing to the next step.**

Recommended step sequence:
1) **Schema (focused):** show the filtered schema excerpt you used.
2) **SQL draft:** show the final read-only SQL that will be executed.
3) **Query result:** show the result table(s).
4) **Insights:** provide 2–5 short bullets.

Return:
- A markdown table of results.
- 2–5 bullets of brief insights (trends, outliers, ratios). If the result is empty, explain that clearly.
- At the end, **always** add a follow-up suggestions block (mandatory, no exceptions):
  `你还可以这样问：`
  then provide 2-4 concrete, related next questions the user can ask.
- Follow-up questions must:
  - stay within the same dataset/topic and be directly actionable as SQL analysis requests;
  - be specific (include metric, dimension, or time range), not generic placeholders;
  - avoid repeating the exact original user question.
- If data is empty or query fails, still provide 2-4 useful follow-up questions based on available schema/context.
- **Do not** show raw command execution logs in chat. Only report the reasoning steps and the results (tables + insights).
- If the user requests a chart, emit an Infographic block (see below) so the Web UI can render it inline.

### Final response template (mandatory)

Use this exact section order in the final answer:
1) Query result (markdown table)
2) Insights (2-5 bullets)
3) `你还可以这样问：` (2-4 bullets, each a concrete question)

Example ending:

```markdown
你还可以这样问：
- 最近90天各渠道退款率的环比变化是多少？
- 订单金额前10%的用户贡献了多少销售额？
- 按地区拆分后，哪个地区的客单价下降最明显？
```

### Plan/Run/Reflect compatibility (mandatory)

If the runtime uses staged outputs like `[plan] / [run] / [reflect] / [final]` with `SUMMARY`, then:
- In both `[reflect]` when `DECISION: done` and `[final]`, `SUMMARY` **must** include:
  - result table
  - insights bullets
  - the follow-up block headed exactly by `你还可以这样问：`
- Never end with only table + insights. Missing `你还可以这样问：` is considered an invalid final answer and must be regenerated before returning.

Pre-submit self-check (required):
1) Does final output contain the exact header `你还可以这样问：`?
2) Are there 2-4 follow-up questions under that header?
3) Are they concrete and related to the current query result?
If any answer is "no", regenerate final output until all are "yes".

## Insights template (use 2-5 bullets)

- **Top/bottom**: highest and lowest values (name + value).
- **Concentration**: top-1/top-3 share of total if there is a numeric metric.
- **Outliers**: values that are notably larger/smaller than the rest.
- **Trends**: if time series, mention direction (up/down/flat) and any spikes.
- **Data quality**: missing/zero rows, unexpected nulls, or very small sample sizes.

## Chart output (Infographic)

When a chart is requested, emit an Infographic block. The Web UI renders it inline. Both forms are supported:

```
infographic chart-column-simple
data
  title 配变停运次数（按月）
  values
    - label 2024-01
      value 282
    - label 2024-02
      value 239
theme light
  palette antv
```

```infographic
infographic chart-column-simple
data
  title 配变停运次数（按月）
  values
    - label 2024-01
      value 282
    - label 2024-02
      value 239
theme light
  palette antv
```

## Chart selection (Infographic gallery)

Choose a template based on data shape (from the Infographic gallery):

- **Category comparison**: `chart-bar`, `chart-column`.
- **Time series**: `chart-line`.
- **Composition**: `chart-pie`, `chart-wordcloud`.
- **Comparisons**: `compare-binary`, `compare-hierarchy`, `compare-quadrant`, `compare-swot`.
- **Hierarchy**: `Mind Map`, `hierarchy-structure`, `Hierarchy Tree`.
- **Lists**: `list-column`, `list-grid`, `list-pyramid`, `list-row`, `list-sector`, `list-zigzag`.
- **Quadrants**: `quadrant-quarter`, `quadrant-simple`.
- **Relations**: `relation-circle`, `relation-dagre`.
- **Sequences/process**: `sequence-ascending`, `sequence-circle`, `sequence-circular`, `sequence-color`, `sequence-cylinders`, `sequence-filter`, `sequence-funnel`, `sequence-horizontal`, `sequence-mountain`, `sequence-pyramid`, `sequence-roadmap`, `sequence-snake`, `sequence-stairs`, `sequence-steps`, `sequence-timeline`, `sequence-zigzag`.

## Insights cheat sheet (example)

Result table:

| channel | order_count | refund_rate_pct |
| --- | --- | --- |
| web | 1240 | 2.1 |
| app | 980 | 3.4 |
| partner | 310 | 1.2 |
| retail | 85 | 5.9 |

Example insights:

- **Top/bottom**: Web has the most orders (1,240); retail has the fewest (85).
- **Concentration**: Web + app account for ~86% of orders (2,220 / 2,615).
- **Outliers**: Retail’s refund rate (5.9%) is notably higher than other channels.

## Example (end-to-end)

User question: “最近30天每个渠道的订单数和退款率是多少？”

1) Schema filter:

```bash
./skills/scripts/schema.sh --keywords "order refund channel created_at" --format markdown
```

2) SQL draft (read-only, with limit if needed):

```sql
SELECT\n  o.channel,\n  COUNT(*) AS order_count,\n  ROUND(SUM(CASE WHEN r.id IS NULL THEN 0 ELSE 1 END) / COUNT(*) * 100, 2) AS refund_rate_pct\nFROM orders o\nLEFT JOIN refunds r ON r.order_id = o.id\nWHERE o.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)\nGROUP BY o.channel\nORDER BY order_count DESC\nLIMIT 100;\n```

3) Execute:

```bash
./skills/scripts/query.sh --sql \"SELECT ...\" --format markdown
```

## Safety rules

- Never run INSERT/UPDATE/DELETE/DDL.
- If the user asks to modify data, refuse and offer a read-only alternative.
- If the request is ambiguous, ask a clarification question before executing.

## Notes

- `schema.sh` and `query.sh` use the local `mysql` CLI.
- `schema.sh` cache options: `--cache-file /path/to/schema.tsv`, `--refresh`, `--no-cache`.
- If `.db.yaml`/`database.yaml` has multiple entries, only the `mysql` block is used.
