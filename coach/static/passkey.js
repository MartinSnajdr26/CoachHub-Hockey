/* CoachHub — passkey (WebAuthn) client.

   Thin transport layer only: it moves options and responses between the browser
   credential API and the server. Every security decision — challenge validity,
   origin, RP ID, signature, credential status, which player_id a session gets —
   is made on the server. Nothing here can be trusted, and nothing here needs to be.

   Used by both the desktop and the mobile layouts; the markup differs, the
   hooks (data-pk-register / data-pk-login) do not. */
'use strict';
(function () {
  function supported() {
    return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create);
  }

  function b64urlToBuf(value) {
    var s = String(value).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) { s += '='; }
    var bin = atob(s);
    var buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { buf[i] = bin.charCodeAt(i); }
    return buf.buffer;
  }

  function bufToB64url(buf) {
    var bytes = new Uint8Array(buf), bin = '';
    for (var i = 0; i < bytes.length; i++) { bin += String.fromCharCode(bytes[i]); }
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function csrf() {
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  function post(url, payload) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(payload || {})
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'bad_response' }; });
    });
  }

  /* Server options arrive as JSON with base64url fields; the credential API
     wants ArrayBuffers. */
  function decodeCreationOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    o.user.id = b64urlToBuf(o.user.id);
    (o.excludeCredentials || []).forEach(function (c) { c.id = b64urlToBuf(c.id); });
    return o;
  }

  function decodeRequestOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = b64urlToBuf(c.id); });
    return o;
  }

  function encodeAttestation(cred) {
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        attestationObject: bufToB64url(cred.response.attestationObject),
        transports: (cred.response.getTransports ? cred.response.getTransports() : []) || []
      }
    };
  }

  function encodeAssertion(cred) {
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        authenticatorData: bufToB64url(cred.response.authenticatorData),
        signature: bufToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null
      }
    };
  }

  var MESSAGES = {
    not_approved: 'Žádost ještě není schválená trenérem.',
    expired: 'Žádost vypršela. Požádej o přístup znovu.',
    not_found: 'Žádost nebyla nalezena.',
    unknown_credential: 'Tento passkey už neplatí. Požádej trenéra o nový přístup.',
    credential_exists: 'Tento passkey už je zaregistrovaný.',
    challenge_missing: 'Relace vypršela, zkus to znovu.',
    challenge_expired: 'Relace vypršela, zkus to znovu.',
    unsupported: 'Tvoje zařízení nebo prohlížeč passkeys nepodporuje.',
    insecure: 'Passkeys vyžadují zabezpečené připojení (HTTPS).',
    cancelled: 'Akce byla zrušena.'
  };

  function say(el, text, kind) {
    if (!el) { return; }
    el.textContent = text;
    el.className = 'pk-msg' + (kind ? ' pk-msg--' + kind : '');
  }

  function describe(err) {
    if (err && err.name === 'NotAllowedError') { return MESSAGES.cancelled; }
    if (err && err.name === 'InvalidStateError') { return MESSAGES.credential_exists; }
    return (err && MESSAGES[err]) || 'Něco se nepovedlo, zkus to prosím znovu.';
  }

  function run(btn, msgEl, optionsUrl, verifyUrl, ceremony) {
    if (!supported()) { say(msgEl, MESSAGES.unsupported, 'err'); return; }
    if (!window.isSecureContext) { say(msgEl, MESSAGES.insecure, 'err'); return; }
    btn.disabled = true;
    say(msgEl, 'Pracuji…');
    post(optionsUrl, {})
      .then(function (data) {
        if (!data.ok) { throw data.error || 'options_failed'; }
        var opts = ceremony === 'create'
          ? decodeCreationOptions(data.options)
          : decodeRequestOptions(data.options);
        return ceremony === 'create'
          ? navigator.credentials.create({ publicKey: opts })
          : navigator.credentials.get({ publicKey: opts });
      })
      .then(function (cred) {
        if (!cred) { throw 'cancelled'; }
        var encoded = ceremony === 'create' ? encodeAttestation(cred) : encodeAssertion(cred);
        return post(verifyUrl, { credential: encoded });
      })
      .then(function (data) {
        if (!data.ok) { throw data.error || 'verify_failed'; }
        say(msgEl, 'Hotovo, přesměrovávám…', 'ok');
        window.location.assign(data.redirect || '/app');
      })
      .catch(function (err) {
        btn.disabled = false;
        say(msgEl, describe(err), 'err');
      });
  }

  function wire() {
    document.querySelectorAll('[data-pk-register]').forEach(function (btn) {
      var msg = document.getElementById(btn.getAttribute('data-pk-msg') || '');
      btn.addEventListener('click', function () {
        run(btn, msg, btn.getAttribute('data-options-url'), btn.getAttribute('data-verify-url'), 'create');
      });
    });
    document.querySelectorAll('[data-pk-login]').forEach(function (btn) {
      var msg = document.getElementById(btn.getAttribute('data-pk-msg') || '');
      if (!supported()) { btn.hidden = true; return; }
      btn.addEventListener('click', function () {
        run(btn, msg, btn.getAttribute('data-options-url'), btn.getAttribute('data-verify-url'), 'get');
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
