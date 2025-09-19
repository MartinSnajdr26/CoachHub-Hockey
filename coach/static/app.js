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
      var prim = cssVar(el, '--brand-primary', '#d4c76f');
      var sec  = cssVar(el, '--brand-secondary', '#000000');
      // Text colors designed for primary/secondary backgrounds
      var onPrim = ensureContrast(prim, sec, 4.5);
      var onSec  = ensureContrast(sec, prim, 4.5);
      el.style.setProperty('--on-primary', onPrim);
      el.style.setProperty('--on-secondary', onSec);
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
    // Calendar: mobile tap-to-toast detail
    try {
      var mqMobile = window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
      var calWrap = document.querySelector('.calendar-wrap');
      if (mqMobile && calWrap) {
        // Helper: move-not-clone handling (mobile)
        var movedNode = { node: null, placeholder: null };
        function restoreMovedNode(){
          try {
            if(movedNode && movedNode.node && movedNode.placeholder && movedNode.placeholder.parentNode){
              try { if(movedNode.node.tagName && movedNode.node.tagName.toLowerCase()==='details'){ movedNode.node.open = false; } } catch(_){}
              movedNode.placeholder.parentNode.insertBefore(movedNode.node, movedNode.placeholder);
              movedNode.placeholder.parentNode.removeChild(movedNode.placeholder);
            }
          } catch(_){}
          movedNode = { node:null, placeholder:null };
        }
        var toast = document.createElement('div');
        toast.className = 'cal-toast';
        toast.innerHTML = '<div class="text"></div><div class="actions"><button class="btn btn-edit" style="display:none;">Upravit</button><button class="btn btn-open">Otevřít</button><button class="btn btn-close">Zavřít</button></div>';
        document.body.appendChild(toast);
        var hideTimer;
        function openDetailsInSheet(det){
          var sheet = document.getElementById('calFormSheet');
          var content = sheet && sheet.querySelector('.cal-form-sheet__content');
          var btnClose = sheet && sheet.querySelector('.cal-form-sheet__close');
          if(!(det && sheet && content)) return;
          restoreMovedNode();
          var ph = document.createComment('details-placeholder');
          det.parentNode.insertBefore(ph, det);
          movedNode = { node: det, placeholder: ph };
          content.innerHTML = '';
          content.appendChild(det);
          sheet.classList.add('open');
          sheet.setAttribute('aria-hidden','false');
          if(btnClose){ btnClose.onclick = function(){ sheet.classList.remove('open'); sheet.setAttribute('aria-hidden','true'); restoreMovedNode(); }; }
          // Fallback reload after any submit
          content.querySelectorAll('form').forEach(function(f){
            f.addEventListener('submit', function(){
              setTimeout(function(){ try{ sheet.classList.remove('open'); sheet.setAttribute('aria-hidden','true'); }catch(_){}; window.location.reload(); }, 200);
            });
          });
          try { var firstInput = det.querySelector('input,select,textarea'); if(firstInput){ firstInput.focus(); } } catch(_){ }
        }
        function showToast(msg, cell){
          toast.querySelector('.text').textContent = msg;
          function closeToast(){
            try{ toast.classList.remove('open'); }catch(_){ }
            try{ document.removeEventListener('click', outsideHandler, true); }catch(_){ }
            clearTimeout(hideTimer);
          }
          function outsideHandler(ev){
            try {
              if(!toast.classList.contains('open')) return;
              if(!toast.contains(ev.target)) { closeToast(); }
            } catch(_){ }
          }
          // open with slide-up
          toast.classList.add('open');
          // enable outside-to-close a tick later to avoid closing from the triggering tap
          setTimeout(function(){ document.addEventListener('click', outsideHandler, true); }, 50);
          clearTimeout(hideTimer);
          hideTimer = setTimeout(closeToast, 4000);
          toast.querySelector('.btn-close').onclick = closeToast;
          // Show explicit "Upravit" for coaches when an event exists
          var isCoach = (calWrap.getAttribute('data-is-coach') === '1');
          var evDet = cell && cell.querySelector('.cal-event details');
          var btnEdit = toast.querySelector('.btn-edit');
          if(isCoach && evDet){ btnEdit.style.display='inline-block'; btnEdit.onclick = function(){ openDetailsInSheet(evDet); try{ toast.classList.remove('open'); }catch(_){ } }; }
          else { btnEdit.style.display='none'; btnEdit.onclick = null; }
          toast.querySelector('.btn-open').onclick = function(){
            try {
              if(!cell) return;
              // Prefer editing existing event if any; else open add form
              var evDet2 = cell.querySelector('.cal-event details');
              var addDet = cell.querySelector('.cal-cell-head details');
              var targetDet = evDet2 || addDet;
              if(targetDet){ openDetailsInSheet(targetDet); }
            } catch(_){ }
            closeToast();
          };
        }
        calWrap.addEventListener('click', function(ev){
          var td = ev.target.closest('td[data-kind]');
          if(!td) return;
          // Intercept click on the calendar add/edit summary: open bottom sheet overlay (no cell resize)
          var sum = ev.target.closest('summary');
          if(sum){
            ev.preventDefault(); ev.stopPropagation();
            var det = sum.closest('details');
            if(det){
              var sheet = document.getElementById('calFormSheet');
              var content = sheet && sheet.querySelector('.cal-form-sheet__content');
              var btnClose = sheet && sheet.querySelector('.cal-form-sheet__close');
              if(det && sheet && content){
                // Restore any previous moved node first
                restoreMovedNode();
                // Move entire details block (contains update+delete forms)
                var ph = document.createComment('details-placeholder');
                det.parentNode.insertBefore(ph, det);
                movedNode = { node: det, placeholder: ph };
                content.innerHTML = '';
                content.appendChild(det);
                sheet.classList.add('open');
                sheet.setAttribute('aria-hidden','false');
          if(btnClose){ btnClose.onclick = function(){ sheet.classList.remove('open'); sheet.setAttribute('aria-hidden','true'); restoreMovedNode(); }; }
                // Post fallback for any form inside moved details
                content.querySelectorAll('form').forEach(function(f){
                  f.addEventListener('submit', function(){
                    setTimeout(function(){ try{ sheet.classList.remove('open'); sheet.setAttribute('aria-hidden','true'); }catch(_){}; window.location.reload(); }, 200);
                  });
                });
                try { var firstInput = det.querySelector('input,select,textarea'); if(firstInput){ firstInput.focus(); } } catch(_){ }
                return; // handled
              }
            }
          }
          // Tap on existing event opens its form as overlay too
          var evBox = ev.target.closest('.cal-event');
          if(evBox){
            ev.preventDefault(); ev.stopPropagation();
            var det2 = evBox.querySelector('details');
            var sheet2 = document.getElementById('calFormSheet');
            var content2 = sheet2 && sheet2.querySelector('.cal-form-sheet__content');
            var btnClose2 = sheet2 && sheet2.querySelector('.cal-form-sheet__close');
            if(det2 && sheet2 && content2){
              // Restore any previous moved node first
              restoreMovedNode();
              var ph2 = document.createComment('details-placeholder');
              det2.parentNode.insertBefore(ph2, det2);
              movedNode = { node: det2, placeholder: ph2 };
              content2.innerHTML = '';
              content2.appendChild(det2);
              sheet2.classList.add('open');
              sheet2.setAttribute('aria-hidden','false');
              if(btnClose2){ btnClose2.onclick = function(){ sheet2.classList.remove('open'); sheet2.setAttribute('aria-hidden','true'); restoreMovedNode(); }; }
              // Fallback reload after submit (any form inside details)
              content2.querySelectorAll('form').forEach(function(f){
                f.addEventListener('submit', function(){
                  setTimeout(function(){ try{ sheet2.classList.remove('open'); sheet2.setAttribute('aria-hidden','true'); }catch(_){}; window.location.reload(); }, 200);
                });
              });
              try { var firstInput2 = det2.querySelector('input,select,textarea'); if(firstInput2){ firstInput2.focus(); } } catch(_){ }
              return; // handled
            }
          }
          var kind = td.getAttribute('data-kind');
          if(!kind) return;
          var title = td.getAttribute('data-title') || '';
          var time = td.getAttribute('data-time') || '';
          var kindLabel = kind === 'match' ? 'Zápas' : 'Trénink';
          var msg = (time ? (time + ' – ') : '') + (title || kindLabel);
          showToast(msg, td);
        }, {passive:false});
      }
    } catch(e) {}

    // Desktop calendar overlay form on "+"
    try {
      var mqDesktop = !(window.matchMedia && window.matchMedia('(max-width: 768px)').matches);
      var calWrapDesk = document.querySelector('.calendar-wrap');
      if(mqDesktop && calWrapDesk){
        var movedDesk = { node:null, placeholder:null };
        function restoreDesk(){
          try{
            if(movedDesk.node && movedDesk.placeholder && movedDesk.placeholder.parentNode){
              try { if(movedDesk.node.tagName && movedDesk.node.tagName.toLowerCase()==='details'){ movedDesk.node.open = false; } } catch(_){}
              movedDesk.placeholder.parentNode.insertBefore(movedDesk.node, movedDesk.placeholder);
              movedDesk.placeholder.parentNode.removeChild(movedDesk.placeholder);
            }
          }catch(_){}
          movedDesk={node:null, placeholder:null};
        }
        calWrapDesk.addEventListener('click', function(ev){
          var sum = ev.target.closest('summary');
          var det, td;
          if(sum){
            det = sum.closest('details');
            td = sum.closest('td');
          } else {
            // Allow opening overlay by clicking anywhere in empty in-month cell (coach only)
            td = ev.target.closest('td');
            if(!td || td.classList.contains('out-month')) return;
            // Ignore clicks on existing events
            if(ev.target.closest('.cal-event')) return;
            var cell = td.querySelector('.cal-cell');
            det = cell && cell.querySelector('details');
            if(!det) return;
          }
          if(!det || !td){ return; }
          ev.preventDefault(); ev.stopPropagation();
          // We'll move the entire <details> block so both update and delete are available
          // Remove existing overlay if any
          var exist = calWrapDesk.querySelector('.cal-overlay');
          if(exist && exist.parentElement){ exist.parentElement.removeChild(exist); }
          // Measure target cell and next cell to span ~2 days
          var rectCell = td.getBoundingClientRect();
          var rectWrap = calWrapDesk.getBoundingClientRect();
          var nextTd = td.nextElementSibling;
          var width = rectCell.width * 2 - 8; // minus small gap
          if(nextTd){
            var rectNext = nextTd.getBoundingClientRect();
            width = (rectNext.right - rectCell.left) - 8;
          }
          var left = rectCell.left - rectWrap.left + calWrapDesk.scrollLeft;
          var top = rectCell.top - rectWrap.top + calWrapDesk.scrollTop + 4;
          // Build overlay
          var overlay = document.createElement('div');
          overlay.className = 'cal-overlay';
          var wrapWidth = calWrapDesk.clientWidth;
          var overlayWidth = Math.max(200, width);
          if(left + overlayWidth > wrapWidth){ left = Math.max(0, wrapWidth - overlayWidth - 8); }
          overlay.style.left = Math.max(0,left) + 'px';
          overlay.style.top = Math.max(0,top) + 'px';
          overlay.style.width = overlayWidth + 'px';
          var inner = document.createElement('div'); inner.className = 'cal-overlay-inner';
          var close = document.createElement('button'); close.type='button'; close.className='cal-overlay-close'; close.textContent='✖ Zavřít';
          var content = document.createElement('div'); content.className='cal-overlay-content';
          // Move original details (not clone) to overlay
          restoreDesk();
          var ph = document.createComment('desk-details-placeholder');
          det.parentNode.insertBefore(ph, det);
          movedDesk = { node: det, placeholder: ph };
          try { det.open = true; } catch(_){ }
          content.appendChild(det);
          inner.appendChild(close);
          inner.appendChild(content);
          overlay.appendChild(inner);
          calWrapDesk.appendChild(overlay);
          // Close handlers
          function closeOverlay(){ if(overlay && overlay.parentElement){ overlay.parentElement.removeChild(overlay); } restoreDesk(); }
          close.onclick = closeOverlay;
          // Close overlay after any submit inside details (redirect will refresh)
          content.querySelectorAll('form').forEach(function(f){ f.addEventListener('submit', function(){ setTimeout(closeOverlay, 200); }); });
        });
      }
    } catch(e) {}

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

    // Mobile dropdown open on tap
    function isMobile(){ return window.matchMedia && window.matchMedia('(max-width: 768px)').matches; }
    document.querySelectorAll('.dropdown > a').forEach(function(anchor){
      anchor.addEventListener('click', function(ev){
        if(!isMobile()) return;
        ev.preventDefault();
        var li = anchor.parentElement;
        if(li){ li.classList.toggle('open'); }
      });
    });

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

    // Team search filter
    var search = document.getElementById('teamSearch');
    var select = document.getElementById('existingTeam');
    if(search && select){
      search.addEventListener('input', function(){ var q=(search.value||'').toLowerCase(); Array.prototype.slice.call(select.options).forEach(function(opt){ opt.hidden = q && (opt.textContent||'').toLowerCase().indexOf(q)===-1; }); });
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
    // Toggle password visibility (auth)
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
  // Roster select all / deselect all
  var rosterSelectAll = document.querySelector('.btn-roster-select-all');
  var rosterDeselectAll = document.querySelector('.btn-roster-deselect-all');
  var rosterGrid = document.querySelector('.players-grid');
  function setRosterChecked(val){
    if(!rosterGrid) return;
    Array.prototype.slice.call(rosterGrid.querySelectorAll('input[type="checkbox"][name="players"]')).forEach(function(cb){ cb.checked = !!val; });
  }
  if(rosterSelectAll){ rosterSelectAll.addEventListener('click', function(){ setRosterChecked(true); }); }
  if(rosterDeselectAll){ rosterDeselectAll.addEventListener('click', function(){ setRosterChecked(false); }); }
    });

// --- Fallback binding for Roster page (in case previous block didn't run) ---
(function(){
  function ready(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  ready(function(){
    var selectAll = document.querySelector('.btn-roster-select-all');
    var deselectAll = document.querySelector('.btn-roster-deselect-all');
    var grid = document.querySelector('.players-grid');
    function setAll(val){ if(!grid) return; Array.prototype.slice.call(grid.querySelectorAll('input[type="checkbox"][name="players"]')).forEach(function(cb){ cb.checked = !!val; }); }
    if(selectAll && !selectAll.__bound){ selectAll.__bound=true; selectAll.addEventListener('click', function(){ setAll(true); }); }
    if(deselectAll && !deselectAll.__bound){ deselectAll.__bound=true; deselectAll.addEventListener('click', function(){ setAll(false); }); }
  });
})();
