
CREATE TABLE IF NOT EXISTS memories (
 user_id TEXT NOT NULL, memory_key TEXT NOT NULL, candidate_id TEXT NOT NULL,
 kind TEXT NOT NULL, content TEXT NOT NULL, importance REAL NOT NULL,
 confidence REAL NOT NULL, sensitivity INTEGER NOT NULL,
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(user_id, memory_key)
);
CREATE TABLE IF NOT EXISTS blocked_memory (
 user_id TEXT NOT NULL, memory_key TEXT NOT NULL,
 PRIMARY KEY(user_id, memory_key)
);
