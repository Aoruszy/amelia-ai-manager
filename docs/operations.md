# Operations notes

## SQLite backup

The runtime database is SQLite in WAL mode. Do not back it up by copying only the main `.sqlite3` file while the process is running: recent data may still be in the `-wal` file and the copy can be inconsistent. Use SQLite's online backup API instead, for example:

```bash
sqlite3 data/amelia_manager.sqlite3 ".backup 'backups/amelia_manager-$(date +%F-%H%M%S).sqlite3'"
```

Run this from the deployment host with the runtime user or another account that can read the database file. Store backups outside the repository, ideally on another disk or remote storage, and keep a daily rotation for at least the retention/business-recovery window you need.
