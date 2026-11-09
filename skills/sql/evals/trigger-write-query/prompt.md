---
description: Seam 4 trigger case. A prompt that does not name the skill makes the skill fire, with no database connection and no formatter run.
tags: [trigger, model-invoked]
max_turns: 8
allowed_tools: [Skill, Read, Glob, Grep, Bash]
---

Write a PostgreSQL query that returns the three newest orders of each customer, with the customer name and the order total. The tables are `customers(id, name)` and `orders(id, customer_id, total, created_at)`. Show the query in your reply. Do not create or change any file.
