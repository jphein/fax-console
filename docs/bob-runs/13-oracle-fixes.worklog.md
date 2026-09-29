# Run 13 work log

| # | Item | Files changed | Tests |
|---|------|--------------|-------|
| 1 | Early POST gate: `do_POST` checks token and declared Content-Length before `rfile.read`; 401 on no token, 413 on oversized body | `faxconsole/server.py` (import `_write_authorized`, rewrite `do_POST`) | +2 → 836 total |
