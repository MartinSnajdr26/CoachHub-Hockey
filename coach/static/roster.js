/* Roster page JS: DnD pools + selected (CSP-safe) */
(function(){
  function onReady(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  onReady(function(){
    try { console.debug('[roster] js loaded'); } catch(_) {}
    var selectedId=null, selectedEl=null, dragSourceList=null; // 'pool' or 'selected'
    function $(s,root){ return (root||document).querySelector(s); }
    function $all(s,root){ return Array.prototype.slice.call((root||document).querySelectorAll(s)); }
    var selected = $('#rosterSelected'); var form = $('#rosterForm'); var checksWrap = $('#hiddenChecks');
    if(!selected || !form || !checksWrap){ try { console.error('[roster] missing DOM containers'); } catch(_) {} return; }

    function setCheckbox(id, val){ var cb = checksWrap.querySelector('input[type="checkbox"][name="players"][value="'+id+'"]'); if(cb) cb.checked = !!val; }
    function isChecked(id){ var cb = checksWrap.querySelector('input[type="checkbox"][name="players"][value="'+id+'"]'); return !!(cb && cb.checked); }
    function counters(){ var f=0,d=0,g=0; $all('.sel-item').forEach(function(it){ var pos = it.getAttribute('data-pos'); if(pos==='F') f++; else if(pos==='D') d++; else if(pos==='G') g++; }); $('#cntF').textContent=f; $('#cntD').textContent=d; $('#cntG').textContent=g; }

    function makeSelItem(id, name, pos){ var el=document.createElement('div'); el.className='sel-item'; el.draggable=true; el.setAttribute('data-id', id); el.setAttribute('data-pos', pos); el.innerHTML = '<span class="pl-badge">'+pos+'</span> '+name+' <button type="button" class="btn-x" aria-label="Odebrat">×</button>'; bindSelDrag(el); el.querySelector('.btn-x').addEventListener('click', function(){ removeFromSelected(id); }); return el; }
    function addToSelected(id, name, pos){ if(isChecked(id)) return; setCheckbox(id, true); selected.appendChild(makeSelItem(id,name,pos)); applyHide(); counters(); }
    function removeFromSelected(id){ setCheckbox(id,false); var el = selected.querySelector('.sel-item[data-id="'+id+'"]'); if(el && el.parentNode) el.parentNode.removeChild(el); applyHide(); counters(); }

    function bindPool(el){ el.addEventListener('click', function(){ var id=el.dataset.id, pos=el.dataset.pos, name=(el.textContent||'').replace(/^\s*\S+\s+/,''); if(!isChecked(id)) addToSelected(id,name,pos); else removeFromSelected(id); }); el.addEventListener('dragstart', function(e){ selectedId=el.dataset.id; selectedEl=el; dragSourceList='pool'; try{ e.dataTransfer.setData('text/plain', selectedId); e.dataTransfer.effectAllowed='move'; }catch(_){} }); el.addEventListener('dragend', function(){ selectedId=null; selectedEl=null; dragSourceList=null; }); }
    function bindSelDrag(el){ el.addEventListener('dragstart', function(e){ selectedId=el.getAttribute('data-id'); selectedEl=el; dragSourceList='selected'; try{ e.dataTransfer.setData('text/plain', selectedId); e.dataTransfer.effectAllowed='move'; }catch(_){} }); el.addEventListener('dragend', function(){ selectedId=null; selectedEl=null; dragSourceList=null; }); el.setAttribute('tabindex','0'); el.addEventListener('keydown', function(e){ if(e.key==='Delete' || e.key==='Backspace'){ removeFromSelected(el.getAttribute('data-id')); }}); }

    // Bind pre-rendered selected items from server
    $all('#rosterSelected .sel-item').forEach(function(el){ bindSelDrag(el); el.querySelector('.btn-x')?.addEventListener('click', function(){ removeFromSelected(el.getAttribute('data-id')); }); });

    // Selected drop area
    selected.addEventListener('dragover', function(e){ e.preventDefault(); selected.classList.add('over'); });
    selected.addEventListener('dragleave', function(){ selected.classList.remove('over'); });
    selected.addEventListener('drop', function(e){ e.preventDefault(); selected.classList.remove('over'); var id=(e.dataTransfer && e.dataTransfer.getData('text/plain')) || selectedId; if(!id) return; var pill=document.querySelector('.pl-item[data-id="'+id+'"]'); var name=pill? (pill.textContent||'').replace(/^\s*\S+\s+/,'') : (function(){ var el=selected.querySelector('.sel-item[data-id="'+id+'"]'); return el?el.textContent.replace(/^\s*\S+\s+/,'').replace(/×\s*$/,''):''; })(); var pos=(pill && pill.dataset.pos) || (selected.querySelector('.sel-item[data-id="'+id+'"]') && selected.querySelector('.sel-item[data-id="'+id+'"]').getAttribute('data-pos')) || 'F'; if(dragSourceList==='selected'){ /* reorder to end */ var ex=selected.querySelector('.sel-item[data-id="'+id+'"]'); if(ex){ selected.appendChild(ex); } } else { addToSelected(id,name,pos); } });

    // Pools
    $all('#poolF .pl-item').forEach(bindPool); $all('#poolD .pl-item').forEach(bindPool); $all('#poolG .pl-item').forEach(bindPool);

    // Initial fill from checked boxes (server state)
    $all('#hiddenChecks input[type="checkbox"][name="players"]:checked').forEach(function(cb){ var id=cb.value; var pill=document.querySelector('.pl-item[data-id="'+id+'"]'); if(pill){ var name=pill.textContent.replace(/^\s*\S+\s+/,''); var pos=pill.dataset.pos; addToSelected(id,name,pos); } });

    // Hide selected toggle
    var hideCb = $('#hideAssigned'); function applyHide(){ var hide=!!(hideCb && hideCb.checked); $all('.pl-item').forEach(function(el){ var id=el.dataset.id; el.style.display = (hide && isChecked(id)) ? 'none' : ''; }); }
    if(hideCb) hideCb.addEventListener('change', applyHide);

    // Search
    var search = $('#playerSearch'); if(search){ search.addEventListener('input', function(){ var q=(search.value||'').toLowerCase(); $all('.pl-item').forEach(function(el){ var nm=(el.textContent||'').toLowerCase(); el.style.display = (!q || nm.indexOf(q)>=0) ? '' : 'none'; }); applyHide(); }); }

    // Buttons
    var btnAll = $('.btn-roster-select-all'); var btnNone = $('.btn-roster-deselect-all'); var btnClr = $('.btn-roster-clear');
    function selectAll(val){ $all('.pl-item').forEach(function(el){ var id=el.dataset.id, pos=el.dataset.pos, name=el.textContent.replace(/^\s*\S+\s+/,''); if(val){ if(!isChecked(id)) addToSelected(id,name,pos); } else { if(isChecked(id)) removeFromSelected(id); } }); }
    if(btnAll) btnAll.addEventListener('click', function(){ selectAll(true); });
    if(btnNone) btnNone.addEventListener('click', function(){ selectAll(false); });
    if(btnClr) btnClr.addEventListener('click', function(){ selectAll(false); });

    counters(); applyHide();
    try { console.debug('[roster] init ok', {selected: $all('.sel-item').length}); } catch(_) {}
  });
})();
