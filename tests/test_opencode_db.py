"""OpenCode keeps sessions in opencode.db (SQLite) since 1.x; memory and usage must read it.
Schema copied from a real OpenCode 1.19 opencode.db (only the columns keelyard uses)."""

import json
import sqlite3

from keelyard.memory import Memory
from keelyard.usage import collect

SCHEMA = """
CREATE TABLE session(id text PRIMARY KEY, project_id text NOT NULL, slug text NOT NULL, directory text NOT NULL,
  title text NOT NULL, version text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL);
CREATE TABLE message(id text PRIMARY KEY, session_id text NOT NULL, time_created integer NOT NULL,
  time_updated integer NOT NULL, data text NOT NULL);
CREATE TABLE part(id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL, time_created integer NOT NULL,
  time_updated integer NOT NULL, data text NOT NULL);
CREATE TABLE credential(id text PRIMARY KEY, value text NOT NULL);
"""


def _db(tmp_path, proj):
    root = tmp_path / "opencode"
    (root / "storage").mkdir(parents=True)  # may exist (old data) or not
    con = sqlite3.connect(root / "opencode.db")
    con.executescript(SCHEMA)
    con.execute("INSERT INTO credential VALUES ('c', 'sk-or-v1-SECRETSECRETSECRET')")
    con.execute("INSERT INTO session VALUES ('ses1','p','s',?,'t','1.19',1,1)", (str(proj),))
    user = {"role": "user", "time": {"created": 1792150000000}}
    asst = {"role": "assistant", "time": {"created": 1792150001000}, "modelID": "big-pickle", "cost": 0,
            "tokens": {"input": 7000, "output": 300, "reasoning": 20, "cache": {"read": 900, "write": 0}}}
    con.execute("INSERT INTO message VALUES ('m1','ses1',1792150000000,1,?)", (json.dumps(user),))
    con.execute("INSERT INTO message VALUES ('m2','ses1',1792150001000,1,?)", (json.dumps(asst),))
    con.execute("INSERT INTO part VALUES ('p1','m1','ses1',1,1,?)", (json.dumps({"type": "text", "text": "why is the discount ignored"}),))
    con.execute("INSERT INTO part VALUES ('p2','m2','ses1',2,1,?)", (json.dumps(
        {"type": "text", "text": "total() never applies the discount argument; round money after it"}),))
    con.execute("INSERT INTO part VALUES ('p3','m2','ses1',3,1,?)", (json.dumps(
        {"type": "tool", "tool": "read", "state": {"input": {"filePath": "cart.py"}, "output": "def total(p, d=0)"}}),))
    con.commit()
    con.close()
    return root / "storage"


def test_memory_indexes_opencode_db(tmp_path):
    storage = _db(tmp_path, tmp_path / "shop")
    m = Memory(tmp_path / "mem.db")
    assert m.ingest([("opencode", storage)])["opencode"] >= 2
    hits = m.search("discount argument")
    assert hits and hits[0]["agent"] == "opencode"
    blob = json.dumps(m.search("SECRETSECRET sk"))
    assert "SECRETSECRET" not in blob  # credentials table is never read
    assert m.ingest([("opencode", storage)])["opencode"] == 0  # idempotent


def test_usage_reads_opencode_db_without_storage_dir(tmp_path):
    storage = _db(tmp_path, tmp_path / "shop")
    storage.rmdir()
    rows = collect(sources=[("opencode", storage)], by="model")
    r = rows["opencode big-pickle"]
    assert (r.input, r.output, r.cache_read, r.messages) == (7000, 320, 900, 1)


def test_usage_counts_migrated_messages_once(tmp_path):
    storage = _db(tmp_path, tmp_path / "shop")
    (storage / "message" / "ses1").mkdir(parents=True)
    (storage / "message" / "ses1" / "m2.json").write_text(json.dumps(
        {"id": "m2", "role": "assistant", "modelID": "big-pickle", "tokens": {"input": 7000, "output": 300}}), encoding="utf-8")
    assert collect(sources=[("opencode", storage)], by="model")["opencode big-pickle"].messages == 1
