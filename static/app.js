// Front-end capture logic

// ---- Utilities ----
function pad3(n){
  const x = parseInt(n,10);
  if (isNaN(x) || x<0) return n;
  return x.toString().padStart(3,'0');
}

async function fetchNextForLot(lot){
  try{
    const res = await fetch('/next_no?lot=' + encodeURIComponent(lot||''));
    const j = await res.json();
    if (j.ok){ return j.next; }
  }catch(e){}
  return null;
}

function parseNumber(s){
  if (s == null) return NaN;
  const m = (s+'').match(/(-?\d+(?:[.,]\d+)?)/);
  if (!m) return NaN;
  return parseFloat(m[1].replace(',', '.'));
}

// ---- App ----
(function(){
  const readingsEls = [...document.querySelectorAll('.reading')];
  const wedge = document.getElementById('wedge');
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');
  const clearBtn = document.getElementById('clearBtn');
  const saveBtn = document.getElementById('saveBtn');
  const refreshBtn = document.getElementById('refreshBtn');
  const statusBadge = document.getElementById('statusBadge');
  const pelletNoEl = document.getElementById('pelletNo');
  const autoIncSwitch = document.getElementById('autoIncSwitch');
  const lotNoEl = document.getElementById('lotNo');
  const operatorEl = document.getElementById('operator');
  const unitEl = document.getElementById('unit');
  const notesEl = document.getElementById('notes');
  const saveMsg = document.getElementById('saveMsg');

  const pEls = [1,2,3,4,5].map(i => document.getElementById('p'+i));

  let capturing = false;
  let activeIndex = 0;
  let pelletNoAutoStartArmed = true; // used when Auto-increment is OFF

  // ---- Helpers ----
  function requiredFrontFieldsOk() {
    const lot = lotNoEl.value.trim();
    const operator = operatorEl.value.trim();
    if (!lot){ alert('O/P Product Code is required.'); lotNoEl.focus(); return false; }
    if (!operator){ alert('Operator Name is required.'); operatorEl.focus(); return false; }
    return true;
  }

  function isValidPelletNo(v) {
    // Accept 3+ digits (e.g., 001, 123, 1001). Change to /^\d{3}$/ for exactly 3 digits.
    return /^\d{3,}$/.test((v||'').trim());
  }

  function updateStats(){
    const vals = readingsEls.map(e => parseNumber(e.value)).filter(v => !isNaN(v));
    if (vals.length === 5){
      const avg = vals.reduce((a,b)=>a+b,0) / 5;
      const maxv = Math.max(...vals);
      const minv = Math.min(...vals);
      document.getElementById('avg').value = avg.toFixed(3);
      document.getElementById('maxv').value = maxv.toFixed(3);
      document.getElementById('minv').value = minv.toFixed(3);
      document.getElementById('diff').value = (maxv - minv).toFixed(3);
      saveBtn.disabled = false;
    } else {
      document.getElementById('avg').value = '';
      document.getElementById('maxv').value = '';
      document.getElementById('minv').value = '';
      document.getElementById('diff').value = '';
      saveBtn.disabled = true;
    }
  }
  readingsEls.forEach(e => e.addEventListener('input', updateStats));

  function setActiveField(i){
    pEls.forEach(el => el.classList.remove('active-field'));
    if (i>=0 && i<5){
      pEls[i].classList.add('active-field');
      pEls[i].focus();
    }
  }

  function setCapturing(on){
    capturing = on;
    statusBadge.textContent = on ? 'Capturing' : 'Idle';
    statusBadge.className = 'badge ' + (on ? 'text-bg-success' : 'text-bg-secondary');
    startBtn.disabled = on;
    stopBtn.disabled = !on;
    if (on){
      // prepare P1..P5 for a fresh capture
      readingsEls.forEach(e => e.value='');
      updateStats();
      activeIndex = 0;
      setActiveField(activeIndex);
    } else {
      // disarm UI styles and re-arm pellet auto-start logic
      pEls.forEach(el => el.classList.remove('active-field'));
      pelletNoAutoStartArmed = true;
    }
  }

  // ---- Start/Stop/Clear ----
  startBtn.addEventListener('click', async ()=>{
    if (!requiredFrontFieldsOk()) return;

    if (!autoIncSwitch.checked){
      const val = pelletNoEl.value.trim();
      if (!val){
        alert('Pellet No is required when Auto-increment is OFF.');
        pelletNoEl.focus();
        return;
      }
    } else {
      // Ensure pellet no present when auto-inc ON (fetch if needed)
      if (!pelletNoEl.value.trim()){
        const n = await fetchNextForLot(lotNoEl.value.trim());
        if (n!=null){ pelletNoEl.value = pad3(n); }
      }
    }
    setCapturing(true);
  });

  stopBtn.addEventListener('click', ()=> setCapturing(false));

  clearBtn.addEventListener('click', ()=>{
    readingsEls.forEach(e => e.value='');
    updateStats();
    setActiveField(0);
  });

  // ---- P1 -> P5 advance with Enter ----
  document.addEventListener('keydown', async (ev)=>{
    if (!capturing) return;
    if (ev.key === 'Enter'){
      ev.preventDefault();
      const el = pEls[activeIndex];
      const val = el.value.trim();
      if (!val) return;
      if (activeIndex < 4){
        activeIndex += 1;
        setActiveField(activeIndex);
      } else {
        updateStats();
        await saveCurrentPellet();
      }
    }
  });

  // ---- Save flow ----
  saveBtn.addEventListener('click', saveCurrentPellet);

  async function saveCurrentPellet(){
    const readings = readingsEls.map(e => e.value.trim());
    if (readings.some(v => !v)){
      alert('Please capture 5 readings.');
      return;
    }
    const payload = {
      lot_no: lotNoEl.value,
      pellet_no: pelletNoEl.value,
      operator: operatorEl.value,
      notes: notesEl.value,
      unit: unitEl.value,
      readings
    };
    saveBtn.disabled = true;
    saveMsg.textContent = 'Saving...';
    try {
      const res = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      const j = await res.json();
      if (!j.ok) throw new Error(j.error || 'Save failed');
      saveMsg.textContent = 'Saved ✔';

      // reset readings
      readingsEls.forEach(e => e.value='');
      updateStats();

      if (autoIncSwitch.checked){
        // Auto: increment and keep capturing
        const n = parseInt(pelletNoEl.value || '0', 10);
        const next = (isNaN(n) ? 1 : n+1);
        pelletNoEl.value = pad3(next);
        loadTable();
        setCapturing(true);
      } else {
        // Manual: stop capturing and focus pellet no
        pelletNoEl.value = '';
        alert('Auto-increment is OFF. Enter the next Pellet No to continue.');
        setCapturing(false);
        pelletNoEl.focus();
        loadTable();
      }
    } catch(err){
      alert(err.message);
      saveMsg.textContent = '';
    } finally {
      saveBtn.disabled = false;
    }
  }

  // ---- Table / Delete ----
  async function loadTable(){
    const res = await fetch('/list');
    const j = await res.json();
    if (!j.ok) return;
    const tb = document.querySelector('#tbl tbody');
    tb.innerHTML = '';
    j.rows.forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${r.ts}</td>
        <td>${r.lot_no}</td>
        <td>${pad3(r.pellet_no)}</td>
        <td>${r.operator}</td>
        <td>${r.p1}</td><td>${r.p2}</td><td>${r.p3}</td><td>${r.p4}</td><td>${r.p5}</td>
        <td>${r.avg.toFixed ? r.avg.toFixed(3) : r.avg}</td>
        <td>${r.max.toFixed ? r.max.toFixed(3) : r.max}</td>
        <td>${r.min.toFixed ? r.min.toFixed(3) : r.min}</td>
        <td>${r.diff.toFixed ? r.diff.toFixed(3) : r.diff}</td>
        <td>${r.unit}</td>
        <td>${r.notes}</td>
        <td><button class="btn btn-sm btn-outline-danger" data-id="${r.id}">Delete</button></td>
      `;
      tb.appendChild(tr);
    });
  }
  refreshBtn.addEventListener('click', loadTable);

  document.addEventListener('click', async (e)=>{
    if (e.target.matches('button.btn-outline-danger[data-id]')){
      const id = e.target.getAttribute('data-id');
      if (!confirm('Delete this record?')) return;
      const form = new FormData();
      form.append('pellet_id', id);
      const res = await fetch('/delete', {method:'POST', body: form});
      const j = await res.json();
      if (j.ok) loadTable();
    }
  });

  // ---- Per-lot auto pellet no update (when Auto-inc ON) ----
  lotNoEl.addEventListener('input', async ()=>{
    if (autoIncSwitch.checked){
      const n = await fetchNextForLot(lotNoEl.value.trim());
      if (n!=null){ pelletNoEl.value = pad3(n); }
    }
  });
  autoIncSwitch.addEventListener('change', async ()=>{
    if (autoIncSwitch.checked){
      const n = await fetchNextForLot(lotNoEl.value.trim());
      if (n!=null){ pelletNoEl.value = pad3(n); }
    }
  });

  // ---- Auto-start capture from Pellet No (Auto-inc OFF) ----
  async function autoStartFromPelletNo(){
    if (autoIncSwitch.checked) return;     // only when manual mode
    if (capturing) return;
    if (!pelletNoAutoStartArmed) return;

    const val = pelletNoEl.value.trim();
    if (!isValidPelletNo(val)) return;
    if (!requiredFrontFieldsOk()) return;

    pelletNoAutoStartArmed = false;        // prevent double-fire
    setCapturing(true);                    // focus goes to P1 automatically
  }

  // Start automatically as operator types 3+ digits (e.g., "001")
  pelletNoEl.addEventListener('input', ()=>{
    if (!autoIncSwitch.checked){
      if (pelletNoEl.value.trim().length >= 3 && isValidPelletNo(pelletNoEl.value)){
        autoStartFromPelletNo();
      }
    }
  });

  // Also start when the field loses focus
  pelletNoEl.addEventListener('blur', ()=>{
    if (!autoIncSwitch.checked){
      autoStartFromPelletNo();
    }
  });

  // ---- Export per lot ----
  const btnExcel = document.getElementById('exportExcelLot');
  const btnPdf = document.getElementById('exportPdfLot');
  if (btnExcel) btnExcel.addEventListener('click', ()=>{
    const lot = lotNoEl.value.trim();
    if (!lot){ alert('Enter O/P Product Code to export.'); return; }
    window.location.href = '/export/lot/excel?lot=' + encodeURIComponent(lot);
  });
  if (btnPdf) btnPdf.addEventListener('click', ()=>{
    const lot = lotNoEl.value.trim();
    if (!lot){ alert('Enter O/P Product Code to export.'); return; }
    window.location.href = '/export/lot/pdf?lot=' + encodeURIComponent(lot);
  });

  // ---- Init ----
  loadTable();
})();