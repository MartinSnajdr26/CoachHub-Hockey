/* Lines page JS (drag & drop + colors) */
(function(){
  try { console.debug('[lines] lines.js loaded'); } catch(_) {}
  function onReady(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  onReady(function(){
    try { console.debug('[lines] DOM ready; binding handlers'); } catch(_) {}
    var selectedId=null, selectedEl=null, dragSourceSlot=null;
    function $(s,root){ return (root||document).querySelector(s); }
    function $all(s,root){ return Array.prototype.slice.call((root||document).querySelectorAll(s)); }
    function poolFor(pos){ return pos==='F' ? $('#poolF') : pos==='D' ? $('#poolD') : $('#poolG'); }
    function findSlotOf(id){ var f=$all('.slot .fill').find(function(x){ return x.getAttribute('data-id')===String(id); }); return f?f.closest('.slot'):null; }
    function updatePoolBadges(){
      $all('.pl-item').forEach(function(el){
        var id = el.dataset.id; var b = el.querySelector('[data-badge]');
        ['ln1','ln2','ln3','ln4'].forEach(function(c){ el.classList.remove(c); });
        var tag='—'; var slot=findSlotOf(id);
        if(slot){ var sk=slot.getAttribute('data-slot');
          if(sk && (sk[0]==='L' || sk[0]==='D')){ var line=parseInt(sk[1]||'0',10)||0; if(line>=1 && line<=4){ el.classList.add('ln'+line); tag=String(line);} }
          else if(sk==='G1'||sk==='G2'){ tag=sk; }
        }
        if(b) b.textContent=tag;
      });
    }
    function clearSlot(slotEl){
      var hid=slotEl.querySelector('input[type="hidden"]');
      var fill=slotEl.querySelector('.fill'); if(fill) fill.remove();
      if(hid) hid.value='';
      var ph=slotEl.querySelector('.ph'); if(!ph){ var sp=document.createElement('span'); sp.className='ph'; sp.textContent=(slotEl.getAttribute('data-accept')==='F'?'Přetáhni útočníka…':(slotEl.getAttribute('data-accept')==='D'?'Přetáhni obránce…':'Přetáhni brankáře…')); slotEl.appendChild(sp); }
      updatePoolBadges();
    }
    function bindFillDrag(fill, slotEl){
      fill.setAttribute('draggable','true');
      fill.addEventListener('dragstart', function(e){ dragSourceSlot=slotEl; try{ e.dataTransfer.setData('text/plain', fill.getAttribute('data-id')); e.dataTransfer.effectAllowed='move'; }catch(_){} });
      fill.addEventListener('dragend', function(){ dragSourceSlot=null; });
      // keyboard remove
      fill.setAttribute('tabindex','0');
      fill.setAttribute('role','button');
      fill.setAttribute('aria-label','Hráč ve slotu; stiskni Delete pro odebrání');
      fill.addEventListener('keydown', function(e){ if(e.key==='Delete' || e.key==='Backspace'){ clearSlot(slotEl); }});
    }
    function placeInto(slotEl, id, name, pos){
      if(!slotEl) return; var accept=slotEl.getAttribute('data-accept'); if(accept!==pos) return;
      clearSlot(slotEl);
      // odeber stejného hráče z jiných slotů
      $all('.slot .fill').forEach(function(f){ if(f.getAttribute('data-id')===String(id)){ clearSlot(f.closest('.slot')); }});
      var hid=slotEl.querySelector('input[type="hidden"]'); if(hid) hid.value=id;
      var ph=slotEl.querySelector('.ph'); if(ph) ph.remove();
      var fill=document.createElement('div'); fill.className='fill'; fill.setAttribute('data-id', id);
      var span=document.createElement('span'); span.textContent=name;
      var bx=document.createElement('button'); bx.type='button'; bx.className='btn-x'; bx.textContent='×'; bx.setAttribute('aria-label','Odebrat hráče ze slotu');
      bx.addEventListener('click', function(){ clearSlot(slotEl); });
      fill.appendChild(span); fill.appendChild(bx); slotEl.appendChild(fill);
      bindFillDrag(fill, slotEl); updatePoolBadges(); applyHide();
    }
    function bindSelect(el){
      el.addEventListener('click', function(){ if(selectedEl){ selectedEl.classList.remove('is-selected'); if(selectedEl===el){ selectedEl=null; selectedId=null; return; }} selectedEl=el; selectedId=el.dataset.id; el.classList.add('is-selected'); });
      el.setAttribute('tabindex','0'); el.setAttribute('role','button'); el.setAttribute('aria-label','Hráč; Enter vybrat');
      el.addEventListener('keydown', function(e){ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); el.click(); }});
    }
    function bindDrag(el){
      el.addEventListener('dragstart', function(e){ el.classList.add('dragging'); dragSourceSlot=null; selectedId=el.dataset.id; selectedEl=el; try{ e.dataTransfer.setData('text/plain', el.dataset.id); e.dataTransfer.effectAllowed='move'; }catch(_){} });
      el.addEventListener('dragend', function(){ el.classList.remove('dragging'); });
    }
    function dropHandlerFactory(slot){ return function(e){ e.preventDefault(); e.stopPropagation(); slot.classList.remove('over');
      var id=(e.dataTransfer && e.dataTransfer.getData('text/plain')) || selectedId; if(!id) return;
      var item=document.querySelector('.pl-item[data-id="'+id+'"]');
      var name=item? (item.textContent||'').replace(/^\s*\S+\s+/,'') : (function(){ var f=$all('.slot .fill').find(function(el){ return el.getAttribute('data-id')===String(id); }); return f?f.querySelector('span').textContent:''; })();
      var pos = (item && item.dataset.pos) || (dragSourceSlot ? dragSourceSlot.getAttribute('data-accept') : slot.getAttribute('data-accept'));
      if(dragSourceSlot){ // slot -> slot (swap/move)
        if(dragSourceSlot===slot) return;
        var dstFill=slot.querySelector('.fill');
        if(dstFill){ var dstId=dstFill.getAttribute('data-id'); var dstName=dstFill.querySelector('span').textContent; var dstPos=slot.getAttribute('data-accept'); clearSlot(dragSourceSlot); clearSlot(slot); placeInto(dragSourceSlot, dstId, dstName, dstPos); placeInto(slot, id, name, pos); }
        else { clearSlot(dragSourceSlot); placeInto(slot, id, name, pos); }
        dragSourceSlot=null;
      } else { // pool -> slot
        var dstFill2=slot.querySelector('.fill');
        if(dstFill2){ clearSlot(slot); placeInto(slot, id, name, pos); }
        else { placeInto(slot, id, name, pos); }
      }
      selectedId=null; if(selectedEl){ selectedEl.classList.remove('is-selected'); selectedEl=null; }
    }; }

    // Bind slots (mouse + keyboard)
    var slots = $all('.slot');
    try { console.debug('[lines] slots count:', slots.length); } catch(_) {}
    slots.forEach(function(slot){
      slot.addEventListener('dragover', function(e){ e.preventDefault(); slot.classList.add('over'); try{ e.dataTransfer.dropEffect='move'; }catch(_){} });
      slot.addEventListener('dragleave', function(){ slot.classList.remove('over'); });
      slot.addEventListener('drop', dropHandlerFactory(slot));
      slot.setAttribute('tabindex','0'); slot.setAttribute('role','button'); slot.setAttribute('aria-label','Slot; Enter/Space vložit vybraného hráče');
      slot.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); if(!selectedId) return; var item=selectedEl; var id=selectedId; var name=item?item.textContent.replace(/^\s*\S+\s+/,''):''; var pos=item?item.dataset.pos:slot.getAttribute('data-accept'); placeInto(slot, id, name, pos); selectedId=null; if(selectedEl){ selectedEl.classList.remove('is-selected'); selectedEl=null; } }});
      var fill=slot.querySelector('.fill'); if(fill) bindFillDrag(fill, slot);
      var bx=slot.querySelector('.btn-x'); if(bx){ bx.addEventListener('click', function(){ clearSlot(slot); }); }
    });

    // Bind pools
    var poolItems = $all('.pl-item');
    try { console.debug('[lines] pool items count:', poolItems.length); } catch(_) {}
    poolItems.forEach(function(el){ bindDrag(el); bindSelect(el); });

    // Hide assigned toggle
    var hideCb=$('#hideAssigned');
    function applyHide(){ var hide = !!(hideCb && hideCb.checked); $all('.pl-item').forEach(function(el){ var has=findSlotOf(el.dataset.id); el.style.display=(hide && has)?'none':''; }); }
    if(hideCb) hideCb.addEventListener('change', applyHide);

    // Color pickers and reset
    // Helpers to read brand vars
    function brandVar(name, fallback){ try{ var v=getComputedStyle(document.body).getPropertyValue(name).trim(); return v || fallback; }catch(_){ return fallback; } }
    // Color helpers for contrast fallback
    function hexToRgb(h){ var m=(h||'').replace('#',''); if(m.length===3){ m=m.split('').map(x=>x+x).join(''); } return [parseInt(m.slice(0,2),16),parseInt(m.slice(2,4),16),parseInt(m.slice(4,6),16)]; }
    function luminance(c){ const s=c.map(v=>{v/=255; return v<=0.03928? v/12.92: Math.pow((v+0.055)/1.055,2.4)}); return 0.2126*s[0]+0.7152*s[1]+0.0722*s[2]; }
    function contrast(rgb1,rgb2){ const L1=luminance(rgb1),L2=luminance(rgb2); const a=Math.max(L1,L2), b=Math.min(L1,L2); return (a+0.05)/(b+0.05); }
    function ensureContrast(bgHex, fgHex, min){
      min = min || 4.5; try{
        var bg = hexToRgb(bgHex||'#000000'); var fg = hexToRgb((fgHex||'#ffffff'));
        if(contrast(bg, fg) >= min) return fgHex;
        // Try simple fallback: choose black/white whichever has higher contrast
        var blackC = contrast(bg, [0,0,0]); var whiteC = contrast(bg,[255,255,255]);
        return blackC > whiteC ? '#000000' : '#ffffff';
      }catch(_){ return fgHex || '#ffffff'; }
    }
    var defaultBg = brandVar('--brand-secondary', '#000000');
    var defaultFg = brandVar('--brand-primary', '#d4c76f');
    // Persist and restore colors per formation
    $all('.formation').forEach(function(fm){
      var line = fm.getAttribute('data-line') || '1';
      var keyBg = 'lineColor_bg_'+line, keyFg = 'lineColor_fg_'+line;
      var bg=fm.querySelector('input[data-bg]'); var fg=fm.querySelector('input[data-fg]');
      // restore saved
      try {
        var savedBg = localStorage.getItem(keyBg) || (bg && bg.value) || defaultBg;
        var savedFgRaw = localStorage.getItem(keyFg) || (fg && fg.value) || defaultFg;
        var savedFg = ensureContrast(savedBg, savedFgRaw, 4.5);
        fm.style.setProperty('--form-bg', savedBg); fm.style.backgroundColor=savedBg; $all('.slot', fm).forEach(function(s){ s.style.backgroundColor=savedBg; });
        fm.style.setProperty('--form-fg', savedFg); fm.style.color=savedFg;
        if(bg) bg.value = savedBg; if(fg) fg.value = savedFg;
        // Update global line accent for pool badges
        document.documentElement.style.setProperty('--line'+line+'-accent', savedFg);
      } catch(_){}
      if(bg){ bg.addEventListener('input', function(){ var v=bg.value||defaultBg; var f = fg ? (fg.value||defaultFg) : defaultFg; var adjF = ensureContrast(v, f, 4.5); try{ localStorage.setItem(keyBg, v); localStorage.setItem(keyFg, adjF);}catch(_){ } fm.style.setProperty('--form-bg', v); fm.style.backgroundColor=v; $all('.slot', fm).forEach(function(s){ s.style.backgroundColor=v; }); fm.style.setProperty('--form-fg', adjF); fm.style.color=adjF; if(fg) fg.value=adjF; document.documentElement.style.setProperty('--line'+line+'-accent', adjF); }); }
      if(fg){ fg.addEventListener('input', function(){ var v=fg.value||defaultFg; var b = bg ? (bg.value||defaultBg) : defaultBg; var adj = ensureContrast(b, v, 4.5); try{ localStorage.setItem(keyFg, adj); }catch(_){ } fm.style.setProperty('--form-fg', adj); fm.style.color=adj; document.documentElement.style.setProperty('--line'+line+'-accent', adj); fg.value = adj; }); }
    });
    var btnReset=$('#btnResetColors');
    if(btnReset){ btnReset.addEventListener('click', function(){
      var bgDef = defaultBg; // brand secondary
      var fgDef = ensureContrast(bgDef, defaultFg, 4.5); // brand primary with contrast guard
      $all('.formation').forEach(function(fm){
        var line = fm.getAttribute('data-line') || '1';
        var keyBg = 'lineColor_bg_'+line, keyFg = 'lineColor_fg_'+line;
        var bg=fm.querySelector('input[data-bg]'); var fg=fm.querySelector('input[data-fg]');
        // clear persisted
        try{ localStorage.removeItem(keyBg); localStorage.removeItem(keyFg); }catch(_){ }
        // apply defaults
        fm.style.setProperty('--form-bg', bgDef);
        fm.style.setProperty('--form-fg', fgDef);
        fm.style.backgroundColor = bgDef;
        fm.style.color = fgDef;
        if(bg) bg.value = bgDef; if(fg) fg.value = fgDef;
        $all('.slot', fm).forEach(function(s){ s.style.backgroundColor = bgDef; });
        // reset line accent for badges
        try{ document.documentElement.style.setProperty('--line'+line+'-accent', fgDef); }catch(_){ }
      });
    }); }

    // Initialize from server (badges + hide toggle)
    $all('.pl-item').forEach(function(el){
      var sk = el.getAttribute('data-ass-slot') || '';
      if(!sk) return;
      var id = el.dataset.id;
      var slot = $all('.slot').find(function(s){ return s.getAttribute('data-slot') === sk; });
      if(!slot) return;
      var fill = slot.querySelector('.fill');
      if(fill) return;
      var txt = el.textContent || '';
      var name = txt.replace(/^\s*\S+\s+/, '');
      var pos = el.dataset.pos || slot.getAttribute('data-accept');
      var hid = slot.querySelector('input[type="hidden"]');
      if(hid && !hid.value){ placeInto(slot, id, name, pos); }
    });
    updatePoolBadges(); applyHide();
    try { window.__linesBound = { slots: $all('.slot').length, pools: $all('.pl-item').length }; console.debug('[lines] init ok', window.__linesBound); } catch(_) {}
    // Clear all button handler
    var btnClr = document.querySelector('.btn-lines-clear');
    if(btnClr){ btnClr.addEventListener('click', function(){
      $all('.slot').forEach(function(slot){ clearSlot(slot); });
    }); }

    // --- Mobile swiper (CSS scroll-snap) pager ---
    var track = document.getElementById('linesTrack');
    var pager = document.getElementById('linesPager');
    if(track && pager){
      var slides = Array.prototype.slice.call(track.querySelectorAll('.slide'));
      // build dots
      slides.forEach(function(_,i){ var b=document.createElement('button'); b.type='button'; b.setAttribute('aria-label','Přejít na kartu '+(i+1)); if(i===0) b.setAttribute('aria-selected','true'); b.addEventListener('click', function(){ track.scrollTo({left: i * track.clientWidth, behavior:'smooth'}); }); pager.appendChild(b); });
      // observe active slide
      var io = new IntersectionObserver(function(entries){ entries.forEach(function(ent){ if(ent.isIntersecting){ var idx = slides.indexOf(ent.target); if(idx>=0){ Array.prototype.slice.call(pager.children).forEach(function(d,k){ d.setAttribute('aria-selected', k===idx ? 'true':'false'); }); } } }); }, { root: track, threshold: 0.6 });
      slides.forEach(function(s){ io.observe(s); });
    }
  });
})();
