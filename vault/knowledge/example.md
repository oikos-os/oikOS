---
tier: reference
tags: [example, getting-started]
---

# Example Knowledge File

This is an example vault file. oikOS indexes markdown files with YAML frontmatter into a hybrid search engine (BM25 + vector).

## How It Works

1. Place `.md` files in `vault/knowledge/`
2. Add YAML frontmatter with `tier` and `tags`
3. Run `oikos index` to rebuild the search index
4. Query with `oikos search "your question"`

## Tiers

| Tier | Purpose |
|------|---------|
| `identity` | Core identity files (who you are, what you believe) |
| `reference` | Knowledge base, documentation, notes |
| `episodic` | Session logs, conversation summaries |

## Tags

Tags enable Room-scoped search. A Room configured with `tag_filter: ["work"]` will only search files tagged `work`.
