/* CareCloud dashboard. Patient data and bearer credentials stay in memory only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { token: '', rows: [], total: 0, offset: 0, limit: 50, query: {}, editId: null,
    selected: null, listVersion: 0, detailVersion: 0, config: null, vapi: null, callState: 'idle', saving: false };
  const icons = {
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/><circle cx="9" cy="7" r="4"/>',
    wave: '<path d="M3 10v4m4-8v12m5-16v20m5-16v12m4-8v4"/>',
    shield: '<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m8 12 3 3 5-6"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>', 'chevron-left': '<path d="m15 18-6-6 6-6"/>', 'chevron-right': '<path d="m9 18 6-6-6-6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', x: '<path d="m6 6 12 12M18 6 6 18"/>',
    sparkles: '<path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7L12 3ZM20 2v4m-2-2h4"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
    'arrow-right': '<path d="M5 12h14m-6-6 6 6-6 6"/>', 'arrow-up': '<path d="M12 19V5m-6 6 6-6 6 6"/>',
    clipboard: '<rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="m9 14 2 2 4-5"/>',
    activity: '<path d="M2 12h4l3-9 6 18 3-9h4"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-2l2 2M4 17l2 2a7 7 0 0 0 12-2"/>',
    search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
    filter: '<path d="M4 6h16M7 12h10m-7 6h4"/>', check: '<path d="m5 12 4 4L19 6"/>',
    lock: '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    edit: '<path d="m16 3 5 5M4 20l5-1L21 7a2 2 0 0 0-4-4L5 15l-1 5Z"/>',
    terminal: '<path d="m4 5 6 7-6 7m9 0h7"/>', stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>'
  };
  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = String(text); return node; }
  function icon(name) { const span = el('span'); span.dataset.icon = name; span.setAttribute('aria-hidden', 'true'); paintIcon(span); return span; }
  function paintIcon(node) { // Only fixed, developer-owned SVG paths enter innerHTML.
    node.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[node.dataset.icon] || icons.users}</svg>`;
  }
  document.querySelectorAll('[data-icon]').forEach(paintIcon);
  function button(label, style, handler, iconName) { const b = el('button', `button ${style}`); b.type = 'button'; if (iconName) b.append(icon(iconName)); b.append(document.createTextNode(label)); if (handler) b.addEventListener('click', handler); return b; }
  function setButton(node, label, iconName) { node.replaceChildren(); if (iconName) node.append(icon(iconName)); node.append(document.createTextNode(label)); }
  function showError(id, message) { const node = $(id); node.textContent = message || ''; node.hidden = !message; }
  function toast(message, isError = false) { const item = el('div', `toast${isError ? ' error' : ''}`); item.append(icon(isError ? 'shield' : 'check'), el('span', '', message)); const close = button('', 'icon-button', () => item.remove(), 'x'); close.setAttribute('aria-label', 'Dismiss notification'); item.append(close); $('toastRegion').append(item); setTimeout(() => item.remove(), 6500); }
  function openDialog(id) { if (!$(id).open) $(id).showModal(); }
  function closeDialog(id) { $(id).close(); }
  function patientName(p) { return `${p.first_name} ${p.last_name}`; }
  function initials(p) { return `${p.first_name?.[0] || ''}${p.last_name?.[0] || ''}`.toUpperCase(); }
  function phoneDisplay(value) { if (!value) return 'Not provided'; const digits = value.replace(/\D/g, ''); return digits.length === 10 ? `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}` : value; }
  async function api(path, options = {}, token = state.token) {
    const headers = { Accept: 'application/json', ...options.headers };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (options.body) headers['Content-Type'] = 'application/json';
    let response;
    try { response = await fetch(path, { ...options, headers, cache: 'no-store', credentials: 'same-origin' }); }
    catch { throw Object.assign(new Error('Unable to reach the service. Check your connection and try again.'), { status: 0 }); }
    let body;
    try { body = await response.json(); } catch { throw new Error('The service returned an unexpected response. Please try again.'); }
    if (!response.ok || body.error) {
      const error = new Error(body.error?.message || `Request failed (${response.status}).`);
      error.status = response.status; error.details = body.error?.details || []; error.code = body.error?.code;
      if (response.status === 401 && token === state.token && token) { clearConnection(); toast('Your API connection expired. Connect again to continue.', true); }
      throw error;
    }
    return body;
  }
  function updateConnection() {
    const connected = Boolean(state.token);
    $('connectionLabel').textContent = connected ? 'Connected' : 'Connect API';
    $('connectionDot').classList.toggle('connected', connected);
    $('connectionDot').style.background = connected ? '#5aaf86' : '#c69e73';
    $('disconnectButton').hidden = !connected;
    $('tokenInput').value = '';
  }
  function statusView(kind, title, description, action) {
    const box = el('div', `${kind}-state`); const mark = el('div', 'empty-icon'); mark.append(icon(kind === 'error' ? 'shield' : 'users'));
    box.append(mark, el('h3', '', title), el('p', '', description)); if (action) box.append(action);
    $('tableRegion').replaceChildren(box); $('tableRegion').setAttribute('aria-busy', 'false');
  }
  function lockedView() {
    $('refreshButton').disabled = false;
    state.rows = []; state.total = 0;
    for (const id of ['totalCount', 'pageCount', 'directoryCount']) $(id).textContent = '—';
    $('resultsSummary').textContent = 'Connect your API to view patient records';
    $('previousPage').disabled = true; $('nextPage').disabled = true; $('pageLabel').textContent = 'Page 1';
    statusView('empty', 'Your directory is ready when you are', 'Connect with your demo API token to securely view and manage synthetic patient records.', button('Connect to API', 'button-primary', openConnection, 'lock'));
  }
  function renderPatients(data) {
    state.rows = data.data; state.total = data.meta.total;
    $('totalLabel').textContent = Object.keys(state.query).length ? 'Matching patients' : 'Active patients';
    $('totalCount').textContent = state.total.toLocaleString(); $('pageCount').textContent = state.rows.length;
    $('directoryCount').textContent = state.total.toLocaleString();
    $('resultsSummary').textContent = state.total ? `Showing ${state.offset + 1}–${state.offset + state.rows.length} of ${state.total} patients` : 'No patient records to display';
    $('pageLabel').textContent = `Page ${Math.floor(state.offset / state.limit) + 1}`;
    $('previousPage').disabled = state.offset === 0; $('nextPage').disabled = state.offset + state.limit >= state.total;
    $('tableRegion').setAttribute('aria-busy', 'false');
    if (!state.rows.length) {
      const filtered = Object.keys(state.query).length > 0;
      statusView('empty', filtered ? 'No matching patients' : 'A fresh start for your directory', filtered ? 'Try another exact last name, date of birth, or phone number.' : 'Register your first synthetic patient to see their details here.', button(filtered ? 'Clear filters' : 'Register patient', 'button-primary', filtered ? clearFilters : () => openPatient(), filtered ? 'refresh' : 'plus'));
      return;
    }
    const table = el('table', 'patient-table');
    const head = el('thead'); const header = el('tr');
    ['PATIENT', 'DATE OF BIRTH', 'PHONE NUMBER', 'LOCATION', 'LANGUAGE', ''].forEach(text => { const th = el('th', '', text); th.scope = 'col'; if (!text) { th.textContent = 'Details'; th.setAttribute('aria-label', 'Patient actions'); } header.append(th); });
    head.append(header); table.append(head); const body = el('tbody');
    state.rows.forEach((p, index) => {
      const row = el('tr'); const nameCell = el('td'); const nameButton = el('button', 'patient-name-button'); nameButton.type = 'button';
      const avatar = el('span', `patient-avatar tint-${index % 5}`, initials(p)); avatar.setAttribute('aria-hidden', 'true');
      const identity = el('span'); identity.append(el('strong', '', patientName(p)), el('small', '', `ID · ${p.patient_id.slice(0, 8)}`));
      nameButton.append(avatar, identity); nameButton.addEventListener('click', () => openDetails(p.patient_id)); nameCell.append(nameButton);
      row.append(nameCell, el('td', '', p.date_of_birth), el('td', '', phoneDisplay(p.phone_number)), el('td', '', `${p.city}, ${p.state}`));
      const language = el('td'); language.append(el('span', 'language-pill', p.preferred_language)); row.append(language);
      const actions = el('td'); const view = el('button', 'icon-button row-open'); view.type = 'button'; view.setAttribute('aria-label', `View ${patientName(p)}`); view.append(icon('chevron-right')); view.addEventListener('click', () => openDetails(p.patient_id)); actions.append(view); row.append(actions); body.append(row);
    });
    table.append(body); $('tableRegion').replaceChildren(table);
  }
  async function loadPatients() {
    const version = ++state.listVersion;
    if (!state.token) { lockedView(); return; }
    $('tableRegion').setAttribute('aria-busy', 'true'); $('refreshButton').disabled = true;
    const loading = el('div', 'loading-state'); loading.append(el('span', 'spinner'), el('p', '', 'Loading your patient directory…')); $('tableRegion').replaceChildren(loading);
    try {
      const query = new URLSearchParams({ ...state.query, limit: state.limit, offset: state.offset });
      const data = await api(`/patients?${query}`);
      if (version !== state.listVersion) return;
      if (state.offset && state.offset >= data.meta.total) { state.offset = Math.max(0, Math.floor((data.meta.total - 1) / state.limit) * state.limit); return loadPatients(); }
      renderPatients(data);
    } catch (error) {
      if (version !== state.listVersion) return;
      if (error.status === 401) { lockedView(); toast('Your API connection expired. Connect again to continue.', true); }
      else { $('resultsSummary').textContent = 'Unable to load patient records'; $('previousPage').disabled = true; $('nextPage').disabled = true; statusView('error', 'We couldn’t load the directory', error.message, button('Try again', 'button-outline', loadPatients, 'refresh')); }
    } finally { if (version === state.listVersion) $('refreshButton').disabled = false; }
  }
  function normalizePhone(value) {
    if (!/^[0-9()+.\s-]+$/.test(value)) return null;
    let digits = value.replace(/\D/g, ''); if (digits.length === 11 && digits.startsWith('1')) digits = digits.slice(1);
    return digits.length === 10 ? digits : null;
  }
  function validDate(value) {
    let match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value); let y, m, d;
    if (match) [, m, d, y] = match.map(Number);
    else { match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value); if (!match) return false; [, y, m, d] = match.map(Number); }
    const date = new Date(0); date.setUTCFullYear(y, m - 1, d); date.setUTCHours(0, 0, 0, 0);
    return y >= 1 && date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d && date <= new Date();
  }
  function applyFilters(event) {
    event?.preventDefault(); const last = $('lastNameSearch').value.trim(), dob = $('dobSearch').value.trim(), phone = $('phoneSearch').value.trim();
    if (dob && !validDate(dob)) { toast('Enter a real date of birth in MM/DD/YYYY format that is not in the future.', true); $('dobSearch').focus(); return; }
    if (phone && !normalizePhone(phone)) { toast('Enter a 10-digit US phone number.', true); $('phoneSearch').focus(); return; }
    state.query = {}; if (last) state.query.last_name = last; if (dob) state.query.date_of_birth = dob; if (phone) state.query.phone_number = normalizePhone(phone);
    state.offset = 0; const count = Number(Boolean(dob)) + Number(Boolean(phone)); $('filterCount').textContent = count; $('filterCount').hidden = !count;
    loadPatients();
  }
  function clearFilters() { $('searchForm').reset(); state.query = {}; state.offset = 0; $('filterCount').hidden = true; loadPatients(); }
  function openConnection() { showError('connectionError', ''); updateConnection(); openDialog('connectionDialog'); }
  let connectionVersion = 0;
  $('connectionDialog').addEventListener('close', () => { ++connectionVersion; $('tokenInput').value = ''; });
  $('connectionForm').addEventListener('submit', async event => {
    event.preventDefault(); const token = $('tokenInput').value.trim(); if (!token) { showError('connectionError', 'Enter the demo bearer token.'); return; }
    const version = ++connectionVersion; $('connectSubmit').disabled = true; showError('connectionError', '');
    try {
      const data = await api('/patients?limit=50&offset=0', {}, token);
      if (version !== connectionVersion || !$('connectionDialog').open) return;
      state.token = token; state.offset = 0; state.query = {}; $('searchForm').reset(); $('filterCount').hidden = true; ++state.listVersion;
      updateConnection(); closeDialog('connectionDialog'); renderPatients(data); toast('API connected. Your patient directory is ready.');
    } catch (error) { showError('connectionError', error.status === 401 ? 'That token was not accepted. Check your API bearer token and try again.' : error.message); }
    finally { $('connectSubmit').disabled = false; }
  });
  function clearConnection() {
    state.token = ''; ++state.listVersion; ++state.detailVersion; ++connectionVersion; state.selected = null; state.editId = null;
    $('patientForm').reset(); $('detailContent').replaceChildren();
    for (const id of ['patientDialog', 'detailDialog', 'deleteDialog', 'connectionDialog']) closeDialog(id);
    updateConnection(); lockedView();
  }
  $('disconnectButton').addEventListener('click', () => { clearConnection(); toast('Disconnected. The token has been cleared.'); });
  const fields = ['first_name', 'last_name', 'date_of_birth', 'sex', 'phone_number', 'email', 'preferred_language', 'address_line_1', 'address_line_2', 'city', 'state', 'zip_code', 'insurance_provider', 'insurance_member_id', 'emergency_contact_name', 'emergency_contact_phone'];
  const optional = new Set(['email', 'address_line_2', 'insurance_provider', 'insurance_member_id', 'emergency_contact_name', 'emergency_contact_phone']);
  const states = 'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split(' ');
  states.forEach(code => { const option = el('option', '', code); option.value = code; $('stateSelect').append(option); });
  const form = $('patientForm');
  function clearFieldErrors() { showError('formError', ''); form.querySelectorAll('[data-error-for]').forEach(node => { node.textContent = ''; }); fields.forEach(name => form.elements[name].removeAttribute('aria-invalid')); }
  function fieldError(name, message) { const input = form.elements[name]; const label = form.querySelector(`[data-error-for="${name}"]`); if (label) label.textContent = message.replace(/^Value error, /, ''); if (input) input.setAttribute('aria-invalid', 'true'); }
  function openPatient(patient = null) {
    if (!state.token) { openConnection(); return; }
    state.editId = patient?.patient_id || null; form.reset(); clearFieldErrors();
    if (patient) fields.forEach(name => { form.elements[name].value = patient[name] ?? ''; });
    $('patientDialogTitle').textContent = patient ? 'Update patient details' : 'A warm welcome starts here';
    $('patientDialogSubtitle').textContent = patient ? 'Keep the patient’s information up to date. Required fields are marked with *.' : 'Enter the patient’s details. Required fields are marked with *.';
    setButton($('savePatientButton'), patient ? 'Save changes' : 'Register patient', 'check');
    openDialog('patientDialog');
  }
  function validatePatient(payload) {
    let invalid = false;
    const fail = (name, message) => { invalid = true; fieldError(name, message); };
    fields.forEach(name => {
      const input = form.elements[name]; const value = payload[name];
      if (!optional.has(name) && !value) fail(name, 'This field is required.');
      else if (value && input.maxLength > 0 && value.length > input.maxLength) fail(name, `Use ${input.maxLength} characters or fewer.`);
    });
    for (const name of ['first_name', 'last_name']) if (payload[name] && (!/\p{L}/u.test(payload[name]) || !/^[\p{L}'-]+$/u.test(payload[name]))) fail(name, 'Use letters, hyphens, or apostrophes only.');
    if (payload.date_of_birth && !validDate(payload.date_of_birth)) fail('date_of_birth', 'Use a real MM/DD/YYYY date that is not in the future.');
    for (const name of ['phone_number', 'emergency_contact_phone']) if (payload[name]) { const phone = normalizePhone(payload[name]); if (!phone) fail(name, 'Enter exactly 10 US digits.'); else payload[name] = phone; }
    if (payload.sex && !['Male', 'Female', 'Other', 'Decline to Answer'].includes(payload.sex)) fail('sex', 'Select an option.');
    if (payload.state && !states.includes(payload.state)) fail('state', 'Select a valid state or DC.');
    if (payload.zip_code && !/^\d{5}(-\d{4})?$/.test(payload.zip_code)) fail('zip_code', 'Use a five-digit ZIP code or ZIP+4.');
    if (payload.email && !form.elements.email.validity.valid) fail('email', 'Enter a valid email address.');
    if (payload.insurance_member_id && !/^[A-Za-z0-9]+$/.test(payload.insurance_member_id)) fail('insurance_member_id', 'Use letters and numbers only.');
    if (payload.emergency_contact_name && (!/\p{L}/u.test(payload.emergency_contact_name) || !/^[\p{L}' -]+$/u.test(payload.emergency_contact_name))) fail('emergency_contact_name', 'Use letters, spaces, hyphens, or apostrophes.');
    return !invalid;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (state.saving) return; clearFieldErrors();
    const payload = {}; fields.forEach(name => { const value = form.elements[name].value.trim(); payload[name] = optional.has(name) && !value ? null : value; });
    if (!validatePatient(payload)) { showError('formError', 'Please correct the highlighted fields before saving.'); form.querySelector('[aria-invalid="true"]')?.focus(); return; }
    state.saving = true; $('savePatientButton').disabled = true; const editing = state.editId;
    try {
      await api(editing ? `/patients/${encodeURIComponent(editing)}` : '/patients', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      closeDialog('patientDialog'); closeDialog('detailDialog'); toast(editing ? 'Patient details updated.' : 'Patient registered successfully.'); await loadPatients();
    } catch (error) {
      showError('formError', error.message); if (Array.isArray(error.details)) error.details.forEach(detail => fieldError(detail.field, detail.message));
      form.querySelector('[aria-invalid="true"]')?.focus();
    } finally { state.saving = false; $('savePatientButton').disabled = false; }
  });
  fields.forEach(name => { const input = form.elements[name]; const label = form.querySelector(`[data-error-for="${name}"]`); if (label) { label.id = `error-${name}`; input.setAttribute('aria-describedby', label.id); } input.addEventListener('input', () => { input.removeAttribute('aria-invalid'); if (label) label.textContent = ''; }); });
  function detailSection(title, pairs) {
    const section = el('section', 'detail-section'); section.append(el('h3', '', title)); const grid = el('dl', 'detail-grid');
    pairs.forEach(([label, value, full]) => { const item = el('div', full ? 'full' : ''); item.append(el('dt', '', label), el('dd', '', value || 'Not provided')); grid.append(item); }); section.append(grid); return section;
  }
  async function openDetails(id) {
    const version = ++state.detailVersion; state.selected = null;
    const loading = el('div', 'loading-state'); loading.append(el('span', 'spinner'), el('p', '', 'Loading patient details…')); $('detailContent').replaceChildren(loading); openDialog('detailDialog');
    try {
      const result = await api(`/patients/${encodeURIComponent(id)}`); if (version !== state.detailVersion || !$('detailDialog').open) return;
      const p = result.data; state.selected = p; const content = $('detailContent'); content.replaceChildren();
      const heading = el('div', 'dialog-heading'); const title = el('div'); title.append(el('span', 'eyebrow', 'PATIENT PROFILE')); const h2 = el('h2', '', 'A closer look'); h2.id = 'detailTitle'; title.append(h2); const close = button('', 'icon-button', () => closeDialog('detailDialog'), 'x'); close.setAttribute('aria-label', 'Close patient details'); heading.append(title, close);
      const identity = el('div', 'detail-identity'); const name = el('div'); name.append(el('h3', '', patientName(p)), el('p', '', `Patient ID · ${p.patient_id}`)); identity.append(el('span', 'patient-avatar', initials(p)), name);
      content.append(heading, identity, detailSection('Personal information', [['Date of birth', p.date_of_birth], ['Sex', p.sex], ['Phone', phoneDisplay(p.phone_number)], ['Preferred language', p.preferred_language], ['Email address', p.email, true]]), detailSection('Home address', [['Street address', [p.address_line_1, p.address_line_2].filter(Boolean).join(', '), true], ['City', p.city], ['State / ZIP', `${p.state} ${p.zip_code}`]]), detailSection('Insurance & emergency contact', [['Insurance provider', p.insurance_provider], ['Member ID', p.insurance_member_id], ['Emergency contact', p.emergency_contact_name], ['Emergency phone', phoneDisplay(p.emergency_contact_phone)]]));
      content.append(detailSection('Record history · UTC', [['Created', p.created_at ? new Date(p.created_at).toISOString() : null, true], ['Last updated', p.updated_at ? new Date(p.updated_at).toISOString() : null, true]]));
      const actions = el('div', 'detail-actions'); actions.append(button('Edit details', 'button-primary', () => { closeDialog('detailDialog'); openPatient(p); }, 'edit'), button('Remove', 'button-outline danger-quiet', () => { state.selected = p; showError('deleteError', ''); $('deleteMessage').textContent = `Remove ${patientName(p)} from the active directory? The record will be soft-deleted, not permanently erased.`; openDialog('deleteDialog'); }, 'trash')); content.append(actions);
    } catch (error) {
      if (version !== state.detailVersion) return; const box = el('div', 'error-state'); box.append(el('h3', '', 'Unable to load patient'), el('p', '', error.message), button('Close', 'button-outline', () => closeDialog('detailDialog'))); $('detailContent').replaceChildren(box);
    }
  }
  $('confirmDelete').addEventListener('click', async () => {
    if (!state.selected) return; $('confirmDelete').disabled = true; showError('deleteError', ''); const id = state.selected.patient_id;
    try { await api(`/patients/${encodeURIComponent(id)}`, { method: 'DELETE' }); closeDialog('deleteDialog'); closeDialog('detailDialog'); state.selected = null; toast('Patient removed from the active directory.'); await loadPatients(); }
    catch (error) { showError('deleteError', error.message); }
    finally { $('confirmDelete').disabled = false; }
  });
  let sdkPromise;
  async function loadVapi() {
    if (window.Vapi) return window.Vapi.default || window.Vapi;
    if (!sdkPromise) sdkPromise = import('https://esm.sh/@vapi-ai/web@2.7.1').then(module => module.default || module.Vapi).catch(() => {
      sdkPromise = null;
      throw new Error('The voice SDK could not be loaded. Check your internet connection and try again.');
    });
    return sdkPromise;
  }
  function voiceUi(status, description) {
    state.callState = status; const active = status === 'active', starting = status === 'starting';
    $('voiceState').textContent = active ? 'You’re connected' : starting ? 'Connecting your conversation…' : state.config?.voice_enabled ? 'Ready when you are' : 'Voice setup needed';
    $('voiceDescription').textContent = description || (active ? 'Speak naturally. Your assistant will review every detail before asking to save.' : state.config?.voice_enabled ? 'Start a conversation to register a synthetic patient, one question at a time.' : 'Configure the Vapi public key, assistant ID, and webhook secret to enable voice registration. You can use the registration form now.');
    setButton($('startVoice'), active || starting ? 'End conversation' : 'Start voice conversation', active || starting ? 'stop' : 'mic');
    $('startVoice').disabled = !state.config?.voice_enabled; document.querySelector('.session-orb').classList.toggle('call-active', active);
  }
  function stopVoice() { ++voiceAttempt; if (state.vapi && state.callState !== 'idle') { try { state.vapi.stop(); } catch { /* stop is best-effort when already disconnected */ } } voiceUi('idle'); }
  let voiceAttempt = 0;
  async function startVoice() {
    if (state.callState !== 'idle') { stopVoice(); return; }
    if (!state.config?.voice_enabled) return; const attempt = ++voiceAttempt; showError('voiceError', ''); voiceUi('starting');
    try {
      if (!window.isSecureContext) throw new Error('Voice calls need HTTPS or localhost to access your microphone.');
      const Vapi = await loadVapi(); if (attempt !== voiceAttempt) return;
      if (!state.vapi) {
        state.vapi = new Vapi(state.config.vapi_public_key);
        state.vapi.on('call-start', () => { if (!$('voiceDialog').open || state.callState !== 'starting') { state.vapi.stop(); return; } voiceUi('active'); });
        state.vapi.on('call-end', () => { voiceUi('idle', 'Conversation ended. Refresh the directory to see any registration saved after confirmation.'); if (state.token) loadPatients(); });
        state.vapi.on('error', error => { voiceUi('idle'); showError('voiceError', error?.message || 'The voice connection encountered a problem. Check microphone permissions and try again.'); });
        state.vapi.on('message', message => {
          if (message.type !== 'transcript' || message.transcriptType !== 'final' || !message.transcript) return;
          const line = el('p'); line.append(el('strong', '', message.role === 'user' ? 'You' : 'Assistant'), document.createTextNode(message.transcript)); $('voiceTranscript').hidden = false; $('voiceTranscript').append(line); $('voiceTranscript').scrollTop = $('voiceTranscript').scrollHeight;
        });
      }
      $('voiceTranscript').replaceChildren(); $('voiceTranscript').hidden = true;
      await state.vapi.start(state.config.vapi_assistant_id);
      if (attempt !== voiceAttempt) state.vapi.stop();
    } catch (error) { if (attempt !== voiceAttempt) return; voiceUi('idle'); showError('voiceError', error.message || 'Unable to start a voice conversation. Please try again.'); }
  }
  function openVoice() { showError('voiceError', ''); if (state.callState === 'idle') voiceUi('idle'); openDialog('voiceDialog'); }
  $('startVoice').addEventListener('click', startVoice);
  $('voiceDialog').addEventListener('close', stopVoice);
  $('detailDialog').addEventListener('close', () => { ++state.detailVersion; });
  $('patientDialog').addEventListener('cancel', event => { if (state.saving) event.preventDefault(); });
  document.addEventListener('click', event => {
    const close = event.target.closest('[data-close]'); if (close) { if (close.dataset.close === 'patientDialog' && state.saving) return; closeDialog(close.dataset.close); return; }
    const control = event.target.closest('[data-action]'); if (!control) return;
    const action = control.dataset.action;
    if (action === 'register') openPatient(); else if (action === 'connect') openConnection(); else if (action === 'voice') openVoice(); else if (action === 'refresh') { loadPatients(); checkHealth(); } else if (action === 'patients') $('directoryTitle').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('filterToggle').addEventListener('click', () => { const open = $('advancedFilters').hidden; $('advancedFilters').hidden = !open; $('filterToggle').setAttribute('aria-expanded', String(open)); if (open) $('dobSearch').focus(); });
  $('clearFilters').addEventListener('click', clearFilters); $('searchForm').addEventListener('submit', applyFilters);
  let searchTimer;
  $('lastNameSearch').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(applyFilters, 350); });
  $('previousPage').addEventListener('click', () => { if (state.offset > 0) { state.offset -= state.limit; loadPatients(); } });
  $('nextPage').addEventListener('click', () => { if (state.offset + state.limit < state.total) { state.offset += state.limit; loadPatients(); } });
  async function checkHealth() {
    try { const response = await fetch('/health', { cache: 'no-store' }); const health = await response.json(); if (!response.ok || health.status !== 'ok') throw new Error(); $('serviceStatus').textContent = 'Online'; $('serviceFootnote').textContent = 'API health check passed'; }
    catch { $('serviceStatus').textContent = 'Unavailable'; $('serviceFootnote').textContent = 'Could not reach the API'; }
  }
  async function init() {
    updateConnection(); lockedView(); checkHealth();
    $('todayLabel').textContent = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).toUpperCase();
    try { const result = await api('/config', {}, ''); state.config = result.data; voiceUi('idle'); }
    catch { voiceUi('idle', 'Unable to check voice configuration. Refresh the page to try again.'); }
  }
  window.addEventListener('pagehide', () => { state.token = ''; if (state.vapi) { try { state.vapi.stop(); } catch {} } });
  init();
})();
