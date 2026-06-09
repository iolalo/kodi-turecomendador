import sqlite3, os, xml.etree.ElementTree as ET, datetime

DB_PATH = '/storage/.kodi/userdata/Database/Addons33.db'
ADDONS_DIR = '/storage/.kodi/addons'
OUT = open('/storage/register_out.txt', 'w')

def log(msg):
    print(msg)
    OUT.write(msg + '\n')
    OUT.flush()

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# --- Print schema ---
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for name, sql in cur.fetchall():
    log(f'TABLE {name}: {sql}')

cur.execute("PRAGMA table_info(installed)")
log('installed cols: ' + str(cur.fetchall()))

cur.execute("PRAGMA table_info(addons)")
log('addons cols: ' + str(cur.fetchall()))

cur.execute("SELECT addonID, enabled FROM installed")
log('installed rows: ' + str(cur.fetchall()))

db.close()
OUT.close()
