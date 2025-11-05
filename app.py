import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo 
IST = ZoneInfo("Asia/Kolkata")
from statistics import mean
from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
import pandas as pd
from io import BytesIO

# --- Config ---
def create_app():
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY','dev-secret')
    db_url = os.getenv('DATABASE_URL','sqlite:///hg.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    return app

app = create_app()
db = SQLAlchemy(app)

# --- Models ---
class Pellet(db.Model):
    __tablename__ = 'pellets'
    id = db.Column(db.Integer, primary_key=True)
    lot_no = db.Column(db.String(128), nullable=True)  # O/P Product Code
    pellet_no = db.Column(db.Integer, nullable=False)
    operator = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    measurements = relationship('Measurement', back_populates='pellet', cascade='all, delete-orphan', uselist=False)

class Measurement(db.Model):
    __tablename__ = 'measurements'
    id = db.Column(db.Integer, primary_key=True)
    pellet_id = db.Column(db.Integer, db.ForeignKey('pellets.id'), nullable=False, unique=True)
    p1 = db.Column(db.Float, nullable=False)
    p2 = db.Column(db.Float, nullable=False)
    p3 = db.Column(db.Float, nullable=False)
    p4 = db.Column(db.Float, nullable=False)
    p5 = db.Column(db.Float, nullable=False)
    avg = db.Column(db.Float, nullable=False)
    maxv = db.Column(db.Float, nullable=False)
    minv = db.Column(db.Float, nullable=False)
    diff = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(8), default='mm', nullable=False)
    pellet = relationship('Pellet', back_populates='measurements')

# --- Helpers ---
def parse_number(s: str):
    if s is None:
        return None
    m = re.search(r'(-?\d+(?:[.,]\d+)?)', s)
    if not m:
        return None
    return float(m.group(1).replace(',', '.'))

# --- Routes ---
@app.route('/')
def index():
    # Next pellet number overall for convenience (UI will fetch per lot)
    max_no = db.session.query(db.func.max(Pellet.pellet_no)).scalar() or 0
    next_no = max_no + 1
    return render_template('index.html', next_pellet_no=next_no)

@app.get('/next_no')
def next_no():
    lot = (request.args.get('lot') or '').strip()
    if not lot:
        max_no = db.session.query(db.func.max(Pellet.pellet_no)).scalar() or 0
        return jsonify({'ok': True, 'next': int(max_no)+1})
    max_no = (db.session.query(db.func.max(Pellet.pellet_no))
              .filter(Pellet.lot_no == lot).scalar()) or 0
    return jsonify({'ok': True, 'next': int(max_no)+1})

@app.post('/save')
def save():
    data = request.get_json(force=True)
    lot_no = (data.get('lot_no') or '').strip()
    pellet_no_raw = (data.get('pellet_no') or '').strip()
    pellet_no = int(pellet_no_raw) if pellet_no_raw.isdigit() else int(parse_number(pellet_no_raw) or 0)
    operator = (data.get('operator') or '').strip()
    notes = (data.get('notes') or '').strip()
    unit = (data.get('unit') or 'mm').strip()

    if not lot_no:
        return jsonify({'ok': False, 'error': 'O/P Product Code required'}), 400
    if not operator:
        return jsonify({'ok': False, 'error': 'Operator required'}), 400
    if not pellet_no:
        return jsonify({'ok': False, 'error': 'Pellet No required'}), 400

    readings_raw = data.get('readings', [])
    readings = []
    for r in readings_raw:
        v = parse_number(str(r))
        if v is None:
            return jsonify({'ok': False, 'error': f'Invalid reading: {r}'}), 400
        readings.append(v)

    if len(readings) != 5:
        return jsonify({'ok': False, 'error': 'Need exactly 5 readings'}), 400

    avg = sum(readings)/5.0
    maxv = max(readings)
    minv = min(readings)
    diff = maxv - minv

    pellet = Pellet(lot_no=lot_no, pellet_no=pellet_no, operator=operator, notes=notes)
    db.session.add(pellet)
    db.session.flush()

    m = Measurement(
        pellet_id=pellet.id,
        p1=readings[0], p2=readings[1], p3=readings[2], p4=readings[3], p5=readings[4],
        avg=avg, maxv=maxv, minv=minv, diff=diff, unit=unit
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({'ok': True, 'pellet_id': pellet.id})

@app.get('/list')
def list_measurements():
    pellets = (db.session.query(Pellet)
               .order_by(Pellet.created_at.desc())
               .limit(500).all())
    rows = []
    for p in pellets:
        utc = p.created_at
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        ts_ist = utc.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
        if not p.measurements:
            continue
        m = p.measurements
        rows.append({
            'id': p.id,
            'ts': ts_ist,
            'lot_no': p.lot_no or '',
            'pellet_no': p.pellet_no,
            'operator': p.operator or '',
            'p1': m.p1, 'p2': m.p2, 'p3': m.p3, 'p4': m.p4, 'p5': m.p5,
            'avg': m.avg, 'max': m.maxv, 'min': m.minv, 'diff': m.diff, 'unit': m.unit,
            'notes': p.notes or ''
        })
    return jsonify({'ok': True, 'rows': rows})

@app.get('/export/csv')
def export_csv():
    pellets = db.session.query(Pellet).order_by(Pellet.created_at.asc()).all()
    recs = []
    for p in pellets:
        utc = p.created_at
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        ts_ist = utc.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
        m = p.measurements
        if not m: 
            continue
        recs.append({
            'Timestamp': ts_ist,
            'Lot No': p.lot_no or '',
            'Pellet No': p.pellet_no,
            'Operator': p.operator or '',
            'P1': m.p1, 'P2': m.p2, 'P3': m.p3, 'P4': m.p4, 'P5': m.p5,
            'Avg': m.avg, 'Max': m.maxv, 'Min': m.minv, 'Max-Min': m.diff,
            'Unit': m.unit,
            'Notes': p.notes or ''
        })
    df = pd.DataFrame(recs)
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    fname = f'height_gauge_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return send_file(buf, mimetype='text/csv', as_attachment=True, download_name=fname)

@app.get('/export/lot/excel')
def export_lot_excel():
    lot = (request.args.get('lot') or '').strip()
    if not lot:
        return jsonify({'ok': False, 'error': 'lot required'}), 400
    pellets = (db.session.query(Pellet).join(Measurement)
               .filter(Pellet.lot_no == lot)
               .order_by(Pellet.pellet_no.asc()).all())
    recs = []
    for p in pellets:
        utc = p.created_at
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        ts_ist = utc.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
        m = p.measurements
        if not m: continue
        recs.append({
            'Timestamp': ts_ist,
            'Lot': p.lot_no or '',
            'Pellet No': p.pellet_no,
            'Operator': p.operator or '',
            'P1': m.p1, 'P2': m.p2, 'P3': m.p3, 'P4': m.p4, 'P5': m.p5,
            'Avg': m.avg, 'Max': m.maxv, 'Min': m.minv, 'Max-Min': m.diff,
            'Unit': m.unit, 'Notes': p.notes or ''
        })
    buf = BytesIO()
    df = pd.DataFrame(recs)
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Measurements')
    buf.seek(0)
    fname = f'lot_{re.sub(r"[^A-Za-z0-9_-]","_",lot)}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=fname)

@app.get('/export/lot/pdf')
def export_lot_pdf():
    lot = (request.args.get('lot') or '').strip()
    if not lot:
        return jsonify({'ok': False, 'error': 'lot required'}), 400
    pellets = (db.session.query(Pellet).join(Measurement)
               .filter(Pellet.lot_no == lot)
               .order_by(Pellet.pellet_no.asc()).all())
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20,leftMargin=20,topMargin=20,bottomMargin=20)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Lot Report: {lot}", styles['Title']))
    story.append(Paragraph(datetime.now(tz=IST).strftime("%Y-%m-%d %H:%M:%S IST"), styles['Normal']))
    story.append(Spacer(1, 12))
    data = [["Pellet","Operator","P1","P2","P3","P4","P5","Avg","Max","Min","Max-Min","Unit","Notes","Time"]]
    for p in pellets:
        utc = p.created_at
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        ts_ist = utc.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
        m = p.measurements
        if not m: continue
        data.append([
            f"{p.pellet_no:03d}", p.operator or '',
            f"{m.p1:.3f}", f"{m.p2:.3f}", f"{m.p3:.3f}", f"{m.p4:.3f}", f"{m.p5:.3f}",
            f"{m.avg:.3f}", f"{m.maxv:.3f}", f"{m.minv:.3f}", f"{m.diff:.3f}",
            m.unit, (p.notes or '')[:40], ts_ist
        ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#222222')),
        ('TEXTCOLOR',(0,0),(-1,0), colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('GRID',(0,0),(-1,-1),0.25, colors.gray),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('BACKGROUND',(0,1),(-1,-1), colors.whitesmoke),
    ]))
    story.append(tbl)
    doc.build(story)
    buf.seek(0)
    fname = f'lot_{re.sub(r"[^A-Za-z0-9_-]","_",lot)}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=fname)

@app.post('/delete')
def delete():
    pellet_id = int(request.form.get('pellet_id','0'))
    if not pellet_id:
        return jsonify({'ok': False, 'error': 'pellet_id required'}), 400
    p = db.session.get(Pellet, pellet_id)
    if not p:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})

@app.cli.command('init-db')
def init_db():
    db.create_all()
    print("Database initialized.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
