---
type: regex
pattern: '^- \S+:\d+: \S'
flags: m
---
Passes when the reply has at least one style point bullet of the form `- <path>:<line>: <style point>`.
