# Height Gauge Data Acquisition System

A Flask-based web application designed to capture, store, and report height gauge measurements for production pellets. It is optimized for use with keyboard-wedge interface gauges.

## Features

### 📊 Data Acquisition
* **5-Point Measurement**: Captures 5 distinct readings (P1–P5) per pellet.
* **Real-time Statistics**: Automatically calculates **Average**, **Max**, **Min**, and **Difference (Max-Min)**.
* **Unit Support**: Toggles between **mm** and **in**.
* **Keyboard Wedge Friendly**: Designed for gauges that input data as plain text followed by an Enter key.

### ⚡ Workflow Efficiency
* **Smart Navigation**:
    * Focus automatically advances from P1 through P5 upon pressing **Enter**.
    * Auto-saves and resets for the next pellet immediately after the 5th reading.
* **Pellet Numbering**:
    * **Auto-increment**: Automatically generates the next sequence number (e.g., 001 → 002) for the specific Lot.
    * **Manual Mode**: Logic to detect manual entry of 3-digit pellet numbers to trigger capture start.
* **Validation**: Enforces mandatory fields (O/P Product Code, Operator Name) to prevent bad data entry.

### 💾 Data Management & Export
* **Storage**: Uses SQLite for reliable, local data persistence.
* **History**: Displays the last 500 records in a responsive table with delete capabilities.
* **Reporting**:
    * **Export All**: Download the complete database as a CSV file.
    * **Lot-Specific Reports**: Generate professional **PDF** reports or **Excel** spreadsheets for a specific Product Code (Lot).

## Tech Stack
* **Backend**: Python (Flask, SQLAlchemy)
* **Frontend**: HTML5, Bootstrap 5, Vanilla JavaScript
* **Data Processing**: Pandas, OpenPyXL (Excel), ReportLab (PDF)

## Installation and Running

1.  **Create a Virtual Environment**
    ```bash
    python -m venv .venv
    
    # Windows
    .venv\Scripts\activate
    
    # Linux/macOS
    source .venv/bin/activate
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the Application**
    ```bash
    python app.py
    ```
    The application will be accessible at `http://127.0.0.1:5000`.
    *(The SQLite database `instance/hg.db` will be created automatically on the first run).*

## Usage Guide

1.  **Initialization**: Enter the **O/P Product Code** (Lot No) and **Operator Name**.
2.  **Capture Mode**:
    * **Auto-Inc ON**: Click "Start Measure". The system assigns the next number (e.g., 001).
    * **Auto-Inc OFF**: Manually type a pellet number (e.g., "005"). The system detects the input and arms the capture mode.
3.  **Measurement**:
    * Cursor focuses on **P1**. Trigger your gauge or type the value.
    * Press **Enter** to move to the next point.
    * After **P5**, the data is saved, and the form resets instantly for the next pellet.
