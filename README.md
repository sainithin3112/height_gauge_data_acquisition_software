# Height Gauge Logger (Flask)

A small, industrial-style Flask application to capture thickness readings from a height gauge over a serial (RS‑232/USB) cable. 
User presses the gauge's SEND/PRINT button, the app receives a value, and it auto-fills 5 points per pellet.

## Features
- Serial reader (background thread) using `pyserial`
- Auto-advance through 5 points per pellet (Point 1→5)
- Stores data in SQLite (`data/app.db`)
- Live display of last reading (polling)
- CSV export for any date range
- Simple configuration page to set COM port & baud
- Works offline on Windows/Linux

## Quick start

```bash
# 1) Create and activate a virtual environment
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell
# or
source .venv/bin/activate # Linux/macOS

# 2) Install deps
pip install -r requirements.txt

# 3) Run the app (edit COM port in UI after first run)
python app.py
# open http://127.0.0.1:5000
```

## Notes
- Default COM port is `COM3` on Windows (`/dev/ttyUSB0` on Linux). Adjust in **Settings**.
- The reader accepts typical height-gauge frames like `+00.289 mm` or `0.289` and extracts the numeric part.
- If your gauge needs a newline or handshaking, adjust `SerialReader._open_port()` and parsing in `parse_value()`.
