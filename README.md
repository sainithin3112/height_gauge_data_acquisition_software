# Height Gauge Flask App (v3)

- Keyboard-wedge height gauge (plain number like `0.193`)
- Start/Stop capture
- Mandatory fields: O/P Product Code, Operator; Pellet No required when Auto-increment OFF
- Per-lot pellet numbering (starts at 001), auto-increment optional
- P1→P5 flow with **Enter** to advance; auto-save after P5, then clears for next pellet
- SQLite storage; list last 500; delete rows
- Export **All CSV**, and **Per-Lot Excel/PDF**

## Run
```bash
python -m venv .venv
# Windows: . .venv/Scripts/activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
# http://127.0.0.1:5000
```
