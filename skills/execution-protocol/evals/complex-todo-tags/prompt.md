---
tags: [skill-creator]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

I want to add tags to my todo cli. when adding a todo you should be able to pass one or more tags (like --tag work --tag urgent), `list` should show the tags, and `list --tag work` should filter to just those. databases created before this change need to keep working. just build it, I'll review at the end

Input files: todo-cli/
