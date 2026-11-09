---
name: Bug report
about: Report a problem with question-bank
title: ''
labels: bug
assignees: ''
---

**What happened**

A clear description of the problem.

**What you ran**

```
# the exact command and its output
```

**Diagnostics**

Run and paste the redacted bundle (it contains no paths, no file
contents, and no key values):

```
uv run question-bank diagnose
```

**Environment**

- OS and version:
- Python version (`python --version`):
- question-bank version:
- Did this involve the LLM PDF adapter? (yes/no; if yes, the model in
  `QUESTION_EXTRACT_MODEL`)
