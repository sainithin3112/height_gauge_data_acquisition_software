async function postJSON(url, data) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data||{})
  });
  return await r.json();
}

function $(sel){ return document.querySelector(sel); }

async function pollStatus(){
  try{
    const s = await fetch('/api/status').then(r=>r.json());
    $('#sessActive').textContent = s.active ? 'Active' : 'Idle';
    $('#sessPid').textContent = s.pellet_id || '—';
    $('#sessNext').textContent = s.next_index || '—';
    $('#lastVal').textContent = (s.last_value!=null) ? s.last_value.toFixed(3) : '—';
    $('#lastTime').textContent = s.last_time || '—';
    $('#unit').textContent = s.unit || '';
  }catch(e){ /* ignore */ }
}

document.addEventListener('DOMContentLoaded', ()=>{
  const startForm = $('#startForm');
  if(startForm){
    startForm.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const fd = new FormData(startForm);
      const data = Object.fromEntries(fd.entries());
      const res = await postJSON('/api/start_pellet', data);
      if(res.ok){
        startForm.reset();
      }else{
        alert('Failed to start pellet');
      }
    });
  }
  const cancelBtn = $('#cancelBtn');
  if(cancelBtn){
    cancelBtn.addEventListener('click', async ()=>{
      await postJSON('/api/cancel_pellet', {});
    });
  }
  setInterval(pollStatus, 500);
});
