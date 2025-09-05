// Global app JS (CSP-safe)
(function(){
  function onReady(fn){
    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
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
          toast.style.display = 'block';
          clearTimeout(hideTimer);
          hideTimer = setTimeout(function(){ toast.style.display='none'; }, 4000);
          toast.querySelector('.btn-close').onclick = function(){ toast.style.display='none'; };
          // Show explicit "Upravit" for coaches when an event exists
          var isCoach = (calWrap.getAttribute('data-is-coach') === '1');
          var evDet = cell && cell.querySelector('.cal-event details');
          var btnEdit = toast.querySelector('.btn-edit');
          if(isCoach && evDet){ btnEdit.style.display='inline-block'; btnEdit.onclick = function(){ openDetailsInSheet(evDet); toast.style.display='none'; }; }
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
            toast.style.display='none';
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
          if(!sum) return;
          var det = sum.closest('details');
          var td = sum.closest('td');
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
    function updateCount(){
      var boxes = document.querySelectorAll('input[name="drill_ids"]');
      var n = Array.prototype.slice.call(boxes).filter(function(cb){ return cb.checked; }).length;
      var el = document.getElementById('selCount');
      if(el) el.textContent = n + ' vybráno';
    }

    function nextOrderValue(){
      var vals = [];
      document.querySelectorAll('.order-input').forEach(function(inp){
        var v = parseInt(inp.value, 10);
        if(!isNaN(v)) vals.push(v);
      });
      if(vals.length === 0) return 1;
      return Math.max.apply(null, vals) + 1;
    }

    function compactOrders(){
      // Optional: keep stable relative order, just compact to 1..N based on current numeric order
      var pairs = [];
      document.querySelectorAll('.card').forEach(function(card){
        var cb = card.querySelector('input.drill-check');
        var inp = card.querySelector('input.order-input');
        if(cb && cb.checked && inp){
          var v = parseInt(inp.value, 10);
          pairs.push({inp: inp, v: isNaN(v) ? Infinity : v});
        }
      });
      pairs.sort(function(a,b){ return a.v - b.v; });
      for(var i=0;i<pairs.length;i++){
        pairs[i].inp.value = (i+1);
      }
    }

    document.querySelectorAll('.btn-toggle-all').forEach(function(btn){
      btn.addEventListener('click', function(){
        var state = btn.getAttribute('data-state') === 'true';
        document.querySelectorAll('.card').forEach(function(card){
          var cb = card.querySelector('input.drill-check');
          var inp = card.querySelector('input.order-input');
          if(cb){ cb.checked = !!state; }
          if(inp){ inp.value = state ? '' : ''; }
        });
        // Auto-assign sequential order if selecting all
        if(state){
          var i = 1;
          document.querySelectorAll('.card').forEach(function(card){
            var cb = card.querySelector('input.drill-check');
            var inp = card.querySelector('input.order-input');
            if(cb && cb.checked && inp){ inp.value = i++; }
          });
        }
        updateCount();
      });
    });
    document.querySelectorAll('input[name="drill_ids"]').forEach(function(cb){
      cb.addEventListener('change', function(){
        var card = cb.closest('.card');
        var inp = card ? card.querySelector('input.order-input') : null;
        if(cb.checked){
          if(inp && (inp.value === '' || isNaN(parseInt(inp.value,10)))){
            inp.value = nextOrderValue();
          }
        } else {
          if(inp){ inp.value = ''; }
          compactOrders();
        }
        updateCount();
      });
    });

    var exportForm = document.getElementById('exportForm');
    if(exportForm){
      exportForm.addEventListener('submit', function(){
        // Before submit: ensure checked drills have an order; compact orders to 1..N
        document.querySelectorAll('.card').forEach(function(card){
          var cb = card.querySelector('input.drill-check');
          var inp = card.querySelector('input.order-input');
          if(cb && cb.checked && inp){
            if(inp.value === '' || isNaN(parseInt(inp.value,10))){ inp.value = nextOrderValue(); }
          }
        });
        compactOrders();
      });
    }

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
    });
