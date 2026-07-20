// Global app JS (CSP-safe)
(function(){
  function onReady(fn){
    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  // Contrast helpers (mirrors lines.js logic)
  function hexToRgb(h){ try{ var m=(h||'').trim(); if(!m) return [0,0,0]; m=m.replace('#',''); if(m.length===3){ m=m.split('').map(function(x){return x+x;}).join(''); } return [parseInt(m.slice(0,2),16)||0,parseInt(m.slice(2,4),16)||0,parseInt(m.slice(4,6),16)||0]; }catch(_){ return [0,0,0]; } }
  function luminance(c){ try{ var s=c.map(function(v){ v/=255; return v<=0.03928? v/12.92: Math.pow((v+0.055)/1.055,2.4)}); return 0.2126*s[0]+0.7152*s[1]+0.0722*s[2]; }catch(_){ return 0; } }
  function contrast(rgb1,rgb2){ try{ var L1=luminance(rgb1),L2=luminance(rgb2); var a=Math.max(L1,L2), b=Math.min(L1,L2); return (a+0.05)/(b+0.05); }catch(_){ return 1; } }
  function ensureContrast(bgHex, fgHex, min){
    min = min || 4.5; try{
      var bg = hexToRgb(bgHex||'#000000'); var fg = hexToRgb((fgHex||'#ffffff'));
      if(contrast(bg, fg) >= min) return fgHex;
      var blackC = contrast(bg, [0,0,0]); var whiteC = contrast(bg,[255,255,255]);
      return blackC > whiteC ? '#000000' : '#ffffff';
    }catch(_){ return fgHex || '#ffffff'; }
  }
  function cssVar(el, name, fallback){ try{ var v=getComputedStyle(el||document.body).getPropertyValue(name).trim(); return v || fallback; }catch(_){ return fallback; } }
  function setGlobalOnColors(){
    try{
      var el = document.body || document.documentElement;
      var prim = cssVar(el, '--primary', '#d4c76f');
      var sec  = cssVar(el, '--secondary', '#000000');
      // Text colors designed for primary/secondary backgrounds
      var onPrim = ensureContrast(prim, sec, 4.5);
      var onSec  = ensureContrast(sec, prim, 4.5);
      el.style.setProperty('--on-primary', onPrim);
      el.style.setProperty('--on-secondary', onSec);
    }catch(_){ }
  }

  function initDropdowns(){
    try{
      // NOTE: ':scope >' is required — 'querySelector("> a")' throws SyntaxError.
      // The toggle may be a link (Tým/Tréninky/Nastavení) or a button (bell).
      function trig(dd){ return dd.querySelector(':scope > a, :scope > button'); }
      function setOpen(dd, open){
        dd.classList.toggle('open', open);
        var t = trig(dd);
        if(t){ t.setAttribute('aria-expanded', open ? 'true' : 'false'); }
      }
      function closeAllDropdowns(except){
        document.querySelectorAll('.dropdown.open').forEach(function(dd){
          if(dd !== except){ setOpen(dd, false); }
        });
      }
      var ddSeq = 0;
      document.querySelectorAll('.dropdown').forEach(function(dropdown){
        var trigger = trig(dropdown);
        var menu = dropdown.querySelector('.dropdown-menu');
        if(trigger){
          trigger.setAttribute('aria-haspopup', 'true');
          if(!trigger.hasAttribute('aria-expanded')){ trigger.setAttribute('aria-expanded', 'false'); }
          if(menu){
            if(!menu.id){ menu.id = 'ddmenu-' + (++ddSeq); }
            trigger.setAttribute('aria-controls', menu.id);
          }
          // Click-based toggle: open stays open until explicitly closed.
          trigger.addEventListener('click', function(ev){
            ev.preventDefault();
            ev.stopPropagation();
            var willOpen = !dropdown.classList.contains('open');
            closeAllDropdowns(dropdown);   // clicking another dropdown closes the previous one
            setOpen(dropdown, willOpen);
          });
          // Space activates link toggles too (Enter already fires click on a/button).
          trigger.addEventListener('keydown', function(ev){
            if(ev.key === ' ' || ev.key === 'Spacebar'){ ev.preventDefault(); trigger.click(); }
            else if(ev.key === 'Escape'){ setOpen(dropdown, false); }
          });
        }
        if(menu){
          // Selecting an item closes the dropdown (navigation still proceeds).
          menu.querySelectorAll('a').forEach(function(item){
            item.addEventListener('click', function(){ setOpen(dropdown, false); });
          });
        }
      });
      // Click outside closes any open dropdown.
      document.addEventListener('click', function(ev){
        if(!ev.target.closest('.dropdown')){ closeAllDropdowns(); }
      });
      // Escape closes and returns focus to the toggle of the open dropdown.
      document.addEventListener('keydown', function(ev){
        if(ev.key === 'Escape'){
          var openDd = document.querySelector('.dropdown.open');
          closeAllDropdowns();
          if(openDd){ var t = trig(openDd); if(t && t.focus){ try{ t.focus(); }catch(_){ } } }
        }
      });
    }catch(_){ }
  }

  // (team mode radios removed; using segmented toggle below)

  async function sharePdf(url, filename){
    try {
      const resp = await fetch(url, {credentials:'include'});
      const blob = await resp.blob();
      const name = (filename && filename.endsWith('.pdf')) ? filename : (filename || 'file.pdf');
      const file = new File([blob], name, { type: blob.type || 'application/pdf' });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: name, text: name });
        return;
      }
    } catch (e) {}
    const msg = encodeURIComponent((filename || '') + ' ' + url);
    window.open('https://api.whatsapp.com/send?text=' + msg, '_blank');
  }

  onReady(function(){
    // Compute global readable text colors against brand backgrounds
    setGlobalOnColors();
    initDropdowns();
    // ===== Calendar event popover (add / edit / view) — premium, never clipped =====
    (function initCalendarPopover(){
      var calWrap = document.querySelector('.calendar-wrap');
      if(!calWrap) return;

      // One popover, appended to <body> so it can never be clipped by the table/overflow.
      var pop = document.createElement('div');
      pop.className = 'cal-pop';
      pop.setAttribute('role','dialog');
      pop.setAttribute('aria-modal','false');
      pop.innerHTML = '<div class="cal-pop-card">'
        + '<div class="cal-pop-head"><span class="cal-pop-title"></span>'
        + '<button type="button" class="cal-pop-close" aria-label="Zavřít">✕</button></div>'
        + '<div class="cal-pop-body"></div></div>';
      var backdrop = document.createElement('div');
      backdrop.className = 'cal-pop-backdrop';
      document.body.appendChild(backdrop);
      document.body.appendChild(pop);
      var card = pop.querySelector('.cal-pop-card');
      var body = pop.querySelector('.cal-pop-body');
      var titleEl = pop.querySelector('.cal-pop-title');

      var moved = { node:null, placeholder:null };
      var anchorCell = null, lastFocus = null;

      function isMobile(){ return window.matchMedia && window.matchMedia('(max-width: 768px)').matches; }
      function restoreMoved(){
        if(moved.node && moved.placeholder && moved.placeholder.parentNode){
          try { if((moved.node.tagName||'').toLowerCase()==='details'){ moved.node.open=false; } } catch(_){}
          moved.placeholder.parentNode.insertBefore(moved.node, moved.placeholder);
          moved.placeholder.parentNode.removeChild(moved.placeholder);
        }
        moved = { node:null, placeholder:null };
      }
      function position(){
        if(isMobile()){ pop.style.left=''; pop.style.top=''; return; } // CSS bottom-sheet
        if(!anchorCell) return;
        var r = anchorCell.getBoundingClientRect();
        var pw = card.offsetWidth, ph = card.offsetHeight;
        var m = 10, vw = window.innerWidth, vh = window.innerHeight;
        var left = r.right + m;                       // prefer to the right of the day
        if(left + pw > vw - m){ left = r.left - m - pw; }   // flip to the left
        if(left < m){ left = Math.max(m, Math.min(vw - pw - m, r.left)); } // clamp
        var top = r.top;
        if(top + ph > vh - m){ top = vh - ph - m; }   // shift up if overflowing bottom
        if(top < m){ top = m; }
        pop.style.left = Math.round(left) + 'px';
        pop.style.top = Math.round(top) + 'px';
      }
      function onDocClick(e){
        if(!pop.classList.contains('open')) return;
        if(pop.contains(e.target)) return;            // clicks inside the popover stay
        if(e.target.closest && e.target.closest('.cal-nav-btn')) { close(); return; }
        close();
      }
      function onKey(e){ if(e.key==='Escape' && pop.classList.contains('open')){ close(); } }

      function open(detailsNode, title, cell, readonlyText){
        restoreMoved();
        if(anchorCell){ anchorCell.classList.remove('cal-cell--active'); }
        anchorCell = cell || null;
        titleEl.textContent = title || '';
        body.innerHTML = '';
        if(detailsNode){
          var ph = document.createComment('cal-pop-ph');
          detailsNode.parentNode.insertBefore(ph, detailsNode);
          moved = { node: detailsNode, placeholder: ph };
          try { detailsNode.open = true; } catch(_){}
          body.appendChild(detailsNode);
        } else if(readonlyText){
          var infoEl = document.createElement('div');
          infoEl.className = 'cal-pop-info';
          infoEl.textContent = readonlyText;
          body.appendChild(infoEl);
        }
        if(anchorCell){ anchorCell.classList.add('cal-cell--active'); }
        lastFocus = document.activeElement;
        pop.classList.add('open'); backdrop.classList.add('open');
        position();
        setTimeout(function(){
          var f = body.querySelector('input:not([type=hidden]),select,textarea,button');
          if(f){ try{ f.focus(); }catch(_){ } }
          document.addEventListener('click', onDocClick, true);
        }, 0);
      }
      function close(){
        if(anchorCell){ anchorCell.classList.remove('cal-cell--active'); }
        pop.classList.remove('open'); backdrop.classList.remove('open');
        document.removeEventListener('click', onDocClick, true);
        restoreMoved();
        var f = lastFocus; anchorCell = null;
        if(f){ try{ f.focus(); }catch(_){ } }
      }

      pop.querySelector('.cal-pop-close').addEventListener('click', close);
      document.addEventListener('keydown', onKey);
      window.addEventListener('resize', position);
      window.addEventListener('scroll', function(){ if(pop.classList.contains('open')) position(); }, true);

      calWrap.addEventListener('click', function(ev){
        var td = ev.target.closest('td.cal-cell');
        if(!td) return;
        var isCoach = (calWrap.getAttribute('data-is-coach') === '1');
        var summary = ev.target.closest('summary');
        if(summary){
          ev.preventDefault(); ev.stopPropagation();
          var det = summary.closest('details');
          var isEdit = !!summary.closest('.cal-event');
          if(det){ open(det, isEdit ? 'Upravit událost' : 'Přidat událost', td); }
          return;
        }
        var evBox = ev.target.closest('.cal-event');
        if(evBox){
          ev.preventDefault(); ev.stopPropagation();
          var det2 = evBox.querySelector('details');
          if(det2){ open(det2, 'Upravit událost', td); }
          else {
            var info = evBox.textContent.replace(/\s+/g,' ').replace('Upravit','').trim();
            open(null, 'Detail události', td, info || 'Událost');
          }
          return;
        }
        if(isCoach && !td.classList.contains('out-month')){
          var addDet = td.querySelector('.cal-cell-head details');
          if(addDet){ ev.preventDefault(); ev.stopPropagation(); open(addDet, 'Přidat událost', td); }
        }
      });
    })();


    // Mobile nav: hamburger toggle
    var menuBtn = document.getElementById('mobileMenuBtn');
    var nav = document.querySelector('.header-bottom nav');
    if(menuBtn && nav){
      menuBtn.addEventListener('click', function(){
        nav.classList.toggle('open');
        var expanded = menuBtn.getAttribute('aria-expanded') === 'true';
        menuBtn.setAttribute('aria-expanded', (!expanded).toString());
      });
    }

    // Auth tabs: toggle between login and register
    var tabs = document.querySelectorAll('.auth-tab');
    if(tabs && tabs.length){
      var panels = document.querySelectorAll('.auth-panel');
      tabs.forEach(function(btn){
        btn.addEventListener('click', function(){
          var target = btn.getAttribute('data-auth-tab');
          tabs.forEach(function(b){ b.classList.remove('active'); });
          btn.classList.add('active');
          panels.forEach(function(p){ p.style.display = (p.getAttribute('data-auth-panel') === target) ? 'block' : 'none'; });
        });
      });
    }
    // Team mode segmented toggle
    var segBtns = document.querySelectorAll('.seg-btn');
    var hiddenTeamMode = document.getElementById('teamModeInput');
    function setTeamMode(mode){
      if(hiddenTeamMode) hiddenTeamMode.value = mode;
      var createBox = document.getElementById('createFields');
      var joinBox = document.getElementById('joinFields');
      if(createBox) createBox.style.display = (mode === 'create') ? 'block' : 'none';
      if(joinBox) joinBox.style.display = (mode === 'join') ? 'block' : 'none';
    }
    if(segBtns && segBtns.length){
      segBtns.forEach(function(b){
        b.addEventListener('click', function(){
          segBtns.forEach(function(x){ x.classList.remove('active'); x.setAttribute('aria-pressed','false'); });
          b.classList.add('active'); b.setAttribute('aria-pressed','true');
          setTeamMode(b.getAttribute('data-team-mode') || 'create');
        });
      });
      setTeamMode('create');
    }

    // Password strength meter (registration)
    var pw = document.getElementById('regPassword');
    var meter = document.getElementById('pwStrength');
    function score(s){ if(!s) return 0; var pts=0; if(s.length>=8) pts++; if(/[A-Z]/.test(s)) pts++; if(/[a-z]/.test(s)) pts++; if(/[0-9]/.test(s)) pts++; if(/[^A-Za-z0-9]/.test(s)) pts++; return pts; }
    function label(pts){ return pts<=1?'velmi slabé':pts===2?'slabé':pts===3?'střední':pts===4?'silné':'velmi silné'; }
    if(pw && meter){ pw.addEventListener('input', function(){ meter.textContent = 'Síla hesla: ' + label(score(pw.value)); }); }

    // Brand colors preview
    var prim = document.getElementById('primColReg');
    var sec = document.getElementById('secColReg');
    var prev = document.getElementById('brandPreview');
    var hex = document.getElementById('brandHex');
    function updBrand(){ if(prev && prim && sec){ prev.style.background = 'linear-gradient(90deg,'+prim.value+' 50%,'+sec.value+' 50%)'; } if(hex && prim && sec){ hex.textContent = (prim.value||'#fff')+' / '+(sec.value||'#000'); } }
    if(prim) prim.addEventListener('input', updBrand);
    if(sec) sec.addEventListener('input', updBrand);
    updBrand();

    // Dropzone logo upload with preview/validation
    var dz = document.getElementById('logoDrop');
    var fileInput = document.getElementById('teamLogoInput');
    var thumb = document.getElementById('logoThumb');
    function setLogoError(msg){ var el = document.querySelector('[data-error-for="team_logo"]'); if(el) el.textContent = msg||''; }
    function handleFiles(f){
      if(!f) return; var ok = ['image/png','image/jpeg'].includes(f.type); var max=2*1024*1024;
      if(!ok){ setLogoError('Povolené typy: PNG/JPG.'); if(fileInput) fileInput.value=''; return; }
      if(f.size>max){ setLogoError('Soubor je větší než 2 MB.'); if(fileInput) fileInput.value=''; return; }
      setLogoError(''); var r = new FileReader(); r.onload=function(){ if(thumb){ thumb.src=r.result; thumb.style.display='inline-block'; } }; r.readAsDataURL(f);
    }
    if(dz && fileInput){
      dz.addEventListener('click', function(){ fileInput.click(); });
      dz.addEventListener('dragover', function(e){ e.preventDefault(); dz.classList.add('drag'); });
      dz.addEventListener('dragleave', function(){ dz.classList.remove('drag'); });
      dz.addEventListener('drop', function(e){ e.preventDefault(); dz.classList.remove('drag'); var f=e.dataTransfer.files[0]; if(f){ fileInput.files=e.dataTransfer.files; handleFiles(f);} });
      fileInput.addEventListener('change', function(){ var f=fileInput.files&&fileInput.files[0]; handleFiles(f); });
    }

    // Team search filter.
    // Native <select> pickers on mobile (iOS/Android) IGNORE `option.hidden`, so
    // hiding options did not filter the dropdown on phones (BUG-2). Instead we
    // remove/re-add the option elements in the DOM, which native pickers respect.
    var search = document.getElementById('teamSearch');
    var select = document.getElementById('existingTeam');
    if(search && select){
      // cache all real (non-placeholder) options once, in their original order
      var allOpts = Array.prototype.slice.call(select.options).filter(function(o){ return o.value; });
      search.addEventListener('input', function(){
        var q = (search.value||'').trim().toLowerCase();
        var selected = select.value;
        // remove every real option (keep the placeholder = value-less option)
        Array.prototype.slice.call(select.options).forEach(function(o){ if(o.value) select.removeChild(o); });
        // re-append only matching options, preserving original order
        allOpts.forEach(function(o){
          if(!q || (o.textContent||'').toLowerCase().indexOf(q) !== -1){ select.appendChild(o); }
        });
        // preserve the current selection if still present, else fall back to placeholder
        var stillThere = Array.prototype.slice.call(select.options).some(function(o){ return o.value === selected; });
        if(selected && stillThere){ select.value = selected; } else { select.selectedIndex = 0; }
      });
    }

    // Consent checkbox enables submit
    var cb = document.getElementById('termsAccept');
    var btn = document.getElementById('btnRegister');
    if(cb && btn){ function upd(){ btn.disabled = !cb.checked; } cb.addEventListener('change', upd); upd(); }

    // Register form micro-validation
    var regForm = document.getElementById('registerForm');
    function setErr(name, msg){ var el = document.querySelector('[data-error-for="'+name+'"]'); if(el) el.textContent = msg||''; }
    if(regForm){
      regForm.addEventListener('submit', function(e){
        var ok=true;
        var email = regForm.querySelector('input[name="email"]');
        var pass = regForm.querySelector('input[name="password"]');
        var mode = (document.getElementById('teamModeInput')||{}).value || 'create';
        var teamName = regForm.querySelector('input[name="team_name"]');
        var existing = document.getElementById('existingTeam');
        setErr('email',''); setErr('team_logo',''); setErr('terms','');
        if(!email.value){ setErr('email','Zadej e‑mail.'); ok=false; }
        if((pass.value||'').length<8){ var m=document.getElementById('pwStrength'); if(m) m.textContent='Síla hesla: slabé (min. 8 znaků)'; ok=false; }
        if(mode==='create'){ if(!teamName.value){ ok=false; } } else { if(existing && !existing.value){ ok=false; } }
        var terms = document.getElementById('termsAccept'); if(!terms || !terms.checked){ setErr('terms','Potvrď souhlas s podmínkami.'); ok=false; }
        if(!ok){ e.preventDefault(); }
      });
    }

    // Share buttons
    document.querySelectorAll('.btn-share-pdf').forEach(function(btn){
      btn.addEventListener('click', function(){
        var url = btn.getAttribute('data-url');
        var filename = btn.getAttribute('data-filename');
        if(url) sharePdf(url, filename);
      });
    });

    // Confirm buttons (inside forms)
    document.querySelectorAll('.btn-confirm').forEach(function(btn){
      btn.addEventListener('click', function(ev){
        var msg = btn.getAttribute('data-message') || 'Opravdu provést akci?';
        if(!window.confirm(msg)){
          ev.preventDefault();
          ev.stopPropagation();
        }
      }, {capture: true});
    });

    // Confirm forms (onsubmit)
    document.querySelectorAll('form.form-confirm').forEach(function(form){
      form.addEventListener('submit', function(ev){
        var msg = form.getAttribute('data-message') || 'Opravdu provést akci?';
        if(!window.confirm(msg)){
          ev.preventDefault();
          ev.stopPropagation();
        }
      });
    });

    // Settings: swap colors
    var swapBtn = document.getElementById('btnSwapColors');
    if(swapBtn){
      swapBtn.addEventListener('click', function(){
        var a = document.getElementById('primCol');
        var b = document.getElementById('secCol');
        if(!a || !b) return;
        var tmp = a.value; a.value = b.value; b.value = tmp;
      });
    }

    // Drills select toggles + ordering
    var selectionHidden = document.getElementById('selectionOrder');
    var selectionOrder = [];

    function updateHiddenOrder(){
      if(selectionHidden){ selectionHidden.value = selectionOrder.join(','); }
    }

    function updateCount(){
      var boxes = document.querySelectorAll('input[name="drill_ids"]');
      var n = Array.prototype.slice.call(boxes).filter(function(cb){ return cb.checked; }).length;
      var el = document.getElementById('selCount');
      if(el) el.textContent = n + ' vybráno';
    }

    function cardMetaForCheckbox(cb){
      if(!cb) return null;
      var card = cb.closest('.card');
      if(!card) return null;
      var inp = card.querySelector('.order-input');
      var domIdx = parseInt(card.getAttribute('data-card-index'), 10);
      if(isNaN(domIdx)) domIdx = 0;
      return {card: card, inp: inp, domIndex: domIdx};
    }

    function normalizeFromInputs(){
      var pairs = [];
      document.querySelectorAll('input[name="drill_ids"]:checked').forEach(function(cb){
        var meta = cardMetaForCheckbox(cb);
        if(!meta || !meta.inp) return;
        var orderVal = parseInt(meta.inp.value, 10);
        pairs.push({
          id: cb.value,
          order: isNaN(orderVal) ? null : orderVal,
          domIndex: meta.domIndex,
          inp: meta.inp
        });
      });
      pairs.sort(function(a,b){
        var aHas = a.order !== null;
        var bHas = b.order !== null;
        if(aHas && bHas){
          if(a.order !== b.order) return a.order - b.order;
          return a.domIndex - b.domIndex;
        }
        if(aHas) return -1;
        if(bHas) return 1;
        return a.domIndex - b.domIndex;
      });
      selectionOrder = pairs.map(function(p){ return p.id; });
      selectionOrder.forEach(function(id, idx){
        var input = document.querySelector('.order-input[data-drill-id="'+id+'"]');
        if(input){ input.value = idx + 1; }
      });
      updateHiddenOrder();
    }

    function applySelectionOrder(){
      var checked = Array.prototype.slice.call(document.querySelectorAll('input[name="drill_ids"]:checked'));
      var checkedSet = new Set(checked.map(function(cb){ return cb.value; }));
      selectionOrder = selectionOrder.filter(function(id){ return checkedSet.has(id); });
      checked.forEach(function(cb){
        if(!selectionOrder.includes(cb.value)){
          selectionOrder.push(cb.value);
        }
      });
      selectionOrder.forEach(function(id, idx){
        var input = document.querySelector('.order-input[data-drill-id="'+id+'"]');
        if(input){ input.value = idx + 1; }
      });
      updateHiddenOrder();
    }

    document.querySelectorAll('.btn-toggle-all').forEach(function(btn){
      btn.addEventListener('click', function(){
        var state = btn.getAttribute('data-state') === 'true';
        document.querySelectorAll('.card').forEach(function(card){
          var cb = card.querySelector('input.drill-check');
          var inp = card.querySelector('.order-input');
          if(cb){ cb.checked = !!state; }
          if(inp){ inp.value = ''; }
        });
        if(state){
          selectionOrder = Array.prototype.slice.call(document.querySelectorAll('input[name="drill_ids"]')).map(function(cb){ return cb.value; });
        } else {
          selectionOrder = [];
        }
        applySelectionOrder();
        updateCount();
      });
    });

    document.querySelectorAll('input[name="drill_ids"]').forEach(function(cb){
      cb.addEventListener('change', function(){
        if(cb.checked){
          selectionOrder = selectionOrder.filter(function(id){ return id !== cb.value; });
          selectionOrder.push(cb.value);
        } else {
          selectionOrder = selectionOrder.filter(function(id){ return id !== cb.value; });
        }
        applySelectionOrder();
        updateCount();
      });
    });

    document.querySelectorAll('.order-input').forEach(function(inp){
      inp.addEventListener('change', normalizeFromInputs);
      inp.addEventListener('blur', normalizeFromInputs);
    });

    var exportForm = document.getElementById('exportForm');
    if(exportForm){
      exportForm.addEventListener('submit', function(){
        normalizeFromInputs();
        applySelectionOrder();
      });
    }

    applySelectionOrder();
    updateCount();

    // New drill toolbar bindings
    document.querySelectorAll('.btn-tool').forEach(function(btn){
      btn.addEventListener('click', function(){
        var tool = btn.getAttribute('data-tool');
        if(window.setTool) window.setTool(tool);
      });
    });
    var clearBtn = document.querySelector('.btn-clear');
    if(clearBtn){ clearBtn.addEventListener('click', function(){ if(window.clearCanvas) window.clearCanvas(); }); }
    var undoBtn = document.querySelector('.btn-undo');
    if(undoBtn){ undoBtn.addEventListener('click', function(){ if(window.undo) window.undo(); }); }
    var form = document.getElementById('newDrillForm');
    if(form){
      form.addEventListener('submit', function(){ if(window.saveImage) window.saveImage(); });
    }

    // Drill detail animation buttons
    document.querySelectorAll('.btn-anim').forEach(function(btn){
      btn.addEventListener('click', function(){
        var action = btn.getAttribute('data-action');
        if(action === 'play' && window.playAnimation) window.playAnimation();
        else if(action === 'pause' && window.pauseAnimation) window.pauseAnimation();
        else if(action === 'stop' && window.stopAnimation) window.stopAnimation();
        else if(action === 'restart' && window.restartAndPlay) window.restartAndPlay();
      });
    });

    // Lines: disable already-selected players across selects
    var linesForm = document.querySelector('.lines-form');
    if(linesForm){
      var selects = linesForm.querySelectorAll('select');
      var updateOptions = function(){
        var selectedValues = Array.prototype.slice.call(selects)
          .map(function(s){ return s.value; })
          .filter(function(v){ return v !== ''; });
        selects.forEach(function(select){
          Array.prototype.slice.call(select.options).forEach(function(opt){
            if(opt.value === '') return;
            if(selectedValues.includes(opt.value) && opt.value !== select.value){ opt.disabled = true; }
            else { opt.disabled = false; }
          });
        });
      };
      selects.forEach(function(select){ select.addEventListener('change', updateOptions); });
      updateOptions();
      // Clear all selections button
      var clearBtn = document.querySelector('.btn-lines-clear');
      if(clearBtn){
        clearBtn.addEventListener('click', function(){
          selects.forEach(function(sel){ sel.value = ''; });
          updateOptions();
        });
      }
    }
  });
})();
(function(){
  function onReady(fn){
    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  onReady(function(){
    document.querySelectorAll('.btn-toggle-pw').forEach(function(btn){
      btn.addEventListener('click', function(){
        var id = btn.getAttribute('data-target');
        var inp = id && document.getElementById(id);
        if(!inp) return;
        if(inp.type === 'password'){
          inp.type = 'text';
          btn.textContent = '🙈';
        } else {
          inp.type = 'password';
          btn.textContent = '👁';
        }
      });
    });
  });
})();

/* ---- Reusable double-submit guard (audit Phase 5) ----------------------------
   Stops accidental double POSTs (double-click / impatient re-submit) from
   creating duplicate records and from piling duplicate requests on the single
   PythonAnywhere worker.
   - Document-level, bubble phase, so it runs AFTER form-level handlers: a
     cancelled `form.form-confirm` or any AJAX form that called preventDefault is
     skipped (ev.defaultPrevented is already true).
   - Opt out with `data-no-busy` on a <form> for intentionally repeatable actions.
   - The submit button is disabled on a `setTimeout(…, 0)` so the browser has
     already serialized the form (the clicked button's name/value is still sent).
   - bfcache (Back/Forward) restore via pageshow.persisted so a cached page never
     keeps a permanently-disabled button. Native required-field validation never
     fires `submit`, so there is nothing to restore in that case.
--------------------------------------------------------------------------------*/
(function(){
  var DEFAULT_BUSY = 'Ukládám…';
  function submitButton(form){
    return form.querySelector(
      'button[type="submit"]:not([disabled]), input[type="submit"]:not([disabled]), button:not([type]):not([disabled])'
    );
  }
  function markBusy(form){
    var btn = submitButton(form);
    if(!btn) return;
    var isInput = (btn.tagName === 'INPUT');
    btn.setAttribute('data-prev-label', isInput ? btn.value : btn.innerHTML);
    var busy = btn.getAttribute('data-busy-label') || DEFAULT_BUSY;
    setTimeout(function(){
      try{
        btn.setAttribute('aria-busy', 'true');
        btn.classList.add('is-submitting');
        btn.disabled = true;
        if(isInput){ btn.value = busy; } else { btn.textContent = busy; }
      }catch(e){}
    }, 0);
  }
  function restore(form){
    try{ form.__chSubmitting = false; }catch(e){}
    var btn = form.querySelector('[data-prev-label]');
    if(!btn) return;
    var prev = btn.getAttribute('data-prev-label');
    try{
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.classList.remove('is-submitting');
      if(btn.tagName === 'INPUT'){ btn.value = prev; } else { btn.innerHTML = prev; }
    }catch(e){}
    btn.removeAttribute('data-prev-label');
  }
  document.addEventListener('submit', function(ev){
    var form = ev.target;
    if(!form || form.nodeName !== 'FORM') return;
    if(ev.defaultPrevented) return;                 // AJAX / confirm-cancelled
    if(form.hasAttribute('data-no-busy')) return;   // opt-out: repeatable action
    if(form.__chSubmitting){ ev.preventDefault(); return; }  // block the duplicate
    form.__chSubmitting = true;
    markBusy(form);
  }, false);
  window.addEventListener('pageshow', function(e){
    if(!e.persisted) return;
    Array.prototype.forEach.call(document.querySelectorAll('form'), restore);
  });
})();
