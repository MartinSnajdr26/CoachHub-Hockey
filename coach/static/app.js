// Global app JS (CSP-safe)
(function(){
  function onReady(fn){
    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function toggleTeamMode(){
    var mode = (document.querySelector('input[name="team_mode"]:checked')||{}).value || 'create';
    var createBox = document.getElementById('createFields');
    var joinBox = document.getElementById('joinFields');
    if(createBox) createBox.style.display = (mode === 'join') ? 'none' : '';
    if(joinBox) joinBox.style.display = (mode === 'join') ? '' : 'none';
  }

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
    // Auth radios
    document.querySelectorAll('input[name="team_mode"]').forEach(function(r){
      r.addEventListener('change', toggleTeamMode);
    });
    toggleTeamMode();

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

    // Drills select toggles
    function updateCount(){
      var boxes = document.querySelectorAll('input[name="drill_ids"]');
      var n = Array.prototype.slice.call(boxes).filter(function(cb){ return cb.checked; }).length;
      var el = document.getElementById('selCount');
      if(el) el.textContent = n + ' vybráno';
    }
    document.querySelectorAll('.btn-toggle-all').forEach(function(btn){
      btn.addEventListener('click', function(){
        var state = btn.getAttribute('data-state') === 'true';
        document.querySelectorAll('input[name="drill_ids"]').forEach(function(cb){ cb.checked = !!state; });
        updateCount();
      });
    });
    document.querySelectorAll('input[name="drill_ids"]').forEach(function(cb){
      cb.addEventListener('change', updateCount);
    });
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
