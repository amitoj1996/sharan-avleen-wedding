(function() {
  var CORRECT_HASH = '5585d35fbab6ffdbdb99268e8ffe8aa068e5fda5cc5b7b442f14124225012e28';

  // Already authenticated — skip
  if (localStorage.getItem('sw_auth') === 'granted') return;

  // Hide everything immediately
  document.documentElement.style.visibility = 'hidden';
  document.documentElement.style.overflow = 'hidden';

  window.addEventListener('DOMContentLoaded', function() {
    document.documentElement.style.visibility = 'hidden';

    // Create gate overlay
    var gate = document.createElement('div');
    gate.id = 'authGate';
    gate.innerHTML =
      '<div style="position:fixed;inset:0;z-index:999999;display:flex;align-items:center;justify-content:center;' +
      'background:linear-gradient(135deg,#7B1E3A 0%,#9B1B30 40%,#7B1E3A 100%);' +
      'background-image:url(\'data:image/svg+xml,%3Csvg width=%2260%22 height=%2260%22 viewBox=%220 0 60 60%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cg fill=%22none%22 fill-rule=%22evenodd%22%3E%3Cg fill=%22%23d4a855%22 fill-opacity=%220.06%22%3E%3Cpath d=%22M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z%22/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\');">' +
        '<div style="text-align:center;padding:40px;max-width:400px;width:90%;">' +
          // Ornate top line
          '<div style="display:flex;align-items:center;gap:12px;margin-bottom:32px;">' +
            '<div style="flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(212,168,85,0.4),transparent);"></div>' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" fill="#D4A855"/></svg>' +
            '<div style="flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(212,168,85,0.4),transparent);"></div>' +
          '</div>' +
          // S & A
          '<p style="font-family:Playfair Display,Georgia,serif;font-size:36px;color:#FDF5E6;font-weight:700;margin-bottom:4px;line-height:1;">S <span style="color:#D4A855;font-style:italic;font-size:24px;">&</span> A</p>' +
          '<p style="font-family:Poppins,system-ui,sans-serif;font-size:8px;color:rgba(253,245,230,0.3);letter-spacing:0.4em;text-transform:uppercase;margin-bottom:32px;">January 2026</p>' +
          // Password field
          '<p style="font-family:Cormorant Garamond,Georgia,serif;font-size:18px;color:rgba(253,245,230,0.6);font-style:italic;margin-bottom:20px;">Enter the password to view the gallery</p>' +
          '<input type="password" id="authInput" placeholder="Password" autocomplete="off" style="' +
            'width:100%;padding:14px 20px;font-family:Poppins,system-ui,sans-serif;font-size:13px;' +
            'background:rgba(253,245,230,0.08);color:#FDF5E6;border:1px solid rgba(212,168,85,0.25);' +
            'border-radius:50px;outline:none;text-align:center;letter-spacing:0.15em;' +
            'transition:border-color 0.3s;">' +
          '<br><br>' +
          '<button id="authBtn" style="' +
            'padding:12px 40px;font-family:Poppins,system-ui,sans-serif;font-size:11px;font-weight:600;' +
            'letter-spacing:0.2em;text-transform:uppercase;cursor:pointer;' +
            'background:linear-gradient(135deg,#D4A855,#edce6a);color:#3d0a1a;border:none;' +
            'border-radius:50px;transition:all 0.3s;box-shadow:0 4px 15px rgba(212,168,85,0.3);">' +
            'Enter' +
          '</button>' +
          '<p id="authError" style="font-family:Poppins,system-ui,sans-serif;font-size:11px;color:#ec7696;margin-top:16px;display:none;">Incorrect password</p>' +
          // Ornate bottom line
          '<div style="display:flex;align-items:center;gap:12px;margin-top:32px;">' +
            '<div style="flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(212,168,85,0.4),transparent);"></div>' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" fill="#D4A855"/></svg>' +
            '<div style="flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(212,168,85,0.4),transparent);"></div>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.prepend(gate);
    document.documentElement.style.visibility = 'visible';

    // Focus the input
    var input = document.getElementById('authInput');
    setTimeout(function() { input.focus(); }, 100);

    // Hover effect on button
    var btn = document.getElementById('authBtn');
    btn.addEventListener('mouseenter', function() { btn.style.transform = 'scale(1.05)'; btn.style.boxShadow = '0 6px 20px rgba(212,168,85,0.4)'; });
    btn.addEventListener('mouseleave', function() { btn.style.transform = 'scale(1)'; btn.style.boxShadow = '0 4px 15px rgba(212,168,85,0.3)'; });

    // Focus effect on input
    input.addEventListener('focus', function() { input.style.borderColor = 'rgba(212,168,85,0.6)'; });
    input.addEventListener('blur', function() { input.style.borderColor = 'rgba(212,168,85,0.25)'; });

    // Check password
    async function checkPassword() {
      var pw = input.value;
      var encoded = new TextEncoder().encode(pw);
      var hashBuffer = await crypto.subtle.digest('SHA-256', encoded);
      var hashHex = Array.from(new Uint8Array(hashBuffer)).map(function(b) {
        return b.toString(16).padStart(2, '0');
      }).join('');

      if (hashHex === CORRECT_HASH) {
        localStorage.setItem('sw_auth', 'granted');
        gate.style.transition = 'opacity 0.5s ease';
        gate.style.opacity = '0';
        setTimeout(function() {
          gate.remove();
          document.documentElement.style.overflow = '';
        }, 500);
      } else {
        document.getElementById('authError').style.display = 'block';
        input.style.borderColor = '#ec7696';
        input.value = '';
        setTimeout(function() {
          input.style.borderColor = 'rgba(212,168,85,0.25)';
          document.getElementById('authError').style.display = 'none';
        }, 2000);
      }
    }

    btn.addEventListener('click', checkPassword);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') checkPassword();
    });
  });
})();
