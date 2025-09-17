// Lightweight contextual help: info button + modal; persists 'seen' per page via localStorage
(function(){
  function onReady(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  onReady(function(){
    try { console.debug('[help] loaded'); } catch(_){}
    var MODAL_ID = 'globalHelpModal';
    function ensureModal(){
      var m = document.getElementById(MODAL_ID); if(m) return m;
      m = document.createElement('div'); m.className='help-modal'; m.id=MODAL_ID; m.setAttribute('role','dialog'); m.setAttribute('aria-modal','true');
      m.innerHTML = '<div class="help-backdrop" data-help-close></div>'+
        '<div class="help-dialog" tabindex="-1">'+
        '<button class="help-close" data-help-close aria-label="Zavřít">✖</button>'+
        '<div class="help-content"></div>'+
        '<div class="help-foot"><label><input type="checkbox" id="helpDontShow"> Nezobrazovat znovu</label><span style="opacity:.7;">Tipy pro rychlý start</span></div>'+
        '</div>';
      document.body.appendChild(m);
      m.addEventListener('click', function(ev){ if(ev.target && ev.target.hasAttribute('data-help-close')) close(); });
      return m;
    }
    function open(html, pageKey){
      var m = ensureModal();
      m.querySelector('.help-content').innerHTML = html;
      var chk = m.querySelector('#helpDontShow');
      chk.checked = false;
      chk.onchange = function(){ try { localStorage.setItem('help_hide_'+pageKey, chk.checked? '1':'0'); }catch(_){} };
      m.classList.add('open');
      try { m.querySelector('.help-dialog').focus(); } catch(_){}
    }
    function close(){ var m=document.getElementById(MODAL_ID); if(m) m.classList.remove('open'); }
    // Bind buttons
    document.querySelectorAll('.help-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        var key = btn.getAttribute('data-help');
        var srcId = btn.getAttribute('data-help-src');
        var html = '';
        if(srcId){ var src=document.getElementById(srcId); if(src) html = src.innerHTML; }
        open(html, key || 'global');
      });
    });
    // Auto-open on first visit per page key
    document.querySelectorAll('[data-help-auto]').forEach(function(el){
      var key = el.getAttribute('data-help-auto');
      try { if(localStorage.getItem('help_hide_'+key) === '1') return; } catch(_){}
      var srcId = el.getAttribute('data-help-src'); var html='';
      if(srcId){ var src=document.getElementById(srcId); if(src) html = src.innerHTML; }
      if(html) open(html, key);
    });
    // ESC close
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  });
})();

