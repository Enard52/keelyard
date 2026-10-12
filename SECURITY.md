# Security

Please report vulnerabilities privately via GitHub Security Advisories on this repository.

Threat model notes:
- keelyard runs with your user's permissions, as part of your agent's hooks. It runs test commands you configure
  (`[proof].test_cmd`) without a shell.
- Memory stores redacted transcript text in `$XDG_DATA_HOME/keelyard/memory.db` (mode 600). Redaction is pattern based
  and cannot catch every secret. Do not paste secrets into agent chats.
- Swarm sends file contents (redacted) to the helper endpoint you configure. Point it at a local model if the code is
  sensitive.
