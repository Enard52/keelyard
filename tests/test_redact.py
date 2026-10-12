from keelyard.redact import redact


def test_redacts_common_secrets():
    text = (
        "key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123 and ghp_abcdefghijklmnopqrstuvwxyz0123456789 "
        "AKIAABCDEFGHIJKLMNOP 8928308079:AAGXabcdefghijklmnopqrstuvwxyz012345 "
        "postgres://user:hunter22@db/x\nAPI_KEY=supersecretvalue123"
    )
    out = redact(text)
    for leaked in ["sk-ant-api03", "ghp_abc", "AKIAABCD", "8928308079:AAGX", "hunter22", "supersecretvalue123"]:
        assert leaked not in out
    assert "[REDACTED:anthropic]" in out and "API_KEY=[REDACTED:assignment]" in out


def test_leaves_normal_text():
    s = "def tokenize(text): return text.split()  # tokens are words"
    assert redact(s) == s
