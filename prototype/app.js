/* UI-only prototype. No native hooks, synthetic input, or desktop actions. */
(() => {
  'use strict';
  const M = window.QingyunModel;
  const $ = s => document.querySelector(s);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const disabled = value => value ? ' disabled' : '';
  let state = M.defaults(), selected = null, player = null, recording = null, capture = null, clockTimer = null;
  let toastTimer = null, captureTimer = null, dragSource = null, undoState = null, storageError = false;
  const storageKey = 'qingyun-prototype-v3';
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) state = M.validate(JSON.parse(saved));
    else {
      // Keep the previous draft recoverable. Only carry over 1.0 settings;
      // its demo canvas recordings are not desktop recordings.
      const previous = localStorage.getItem('qingyun-prototype-v2');
      if (previous) {
        const old = M.validate(JSON.parse(previous));
        state.groups = old.groups; state.activeClicker = old.activeClicker;
        state.engine = old.engine; state.hotkey = old.hotkey;
      }
    }
  } catch { storageError = true; }
  const groups = () => state.mode === 'clicker' ? state.groups : state.macros;
  const activeIndex = () => state.mode === 'clicker' ? state.activeClicker : state.activeMacro;
  const active = () => groups()[activeIndex()];
  const activeMacro = () => state.macros[state.activeMacro];
  const busy = () => !!player || !!recording;
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify(state)); }
    catch { if (!storageError) toast('无法保存，请导出配置。'); storageError = true; }
  }
  function snapshot() { undoState = JSON.stringify(state); }
  function status(message) { $('#status-message').textContent = message; }
  function toast(message, undo = false) {
    clearTimeout(toastTimer);
    $('#toast').innerHTML = escape(message) + (undo ? ' <button class="text-button" data-action="undo">撤销</button>' : '');
    $('#toast').hidden = false;
    toastTimer = setTimeout(() => { $('#toast').hidden = true; }, undo ? 8000 : 4000);
  }
  function time(ms) { return (ms / 1000).toFixed(2) + ' s'; }
  function interval(value, attrs = '', isDisabled = false, maximum = 600000, prefix = '') {
    return `<label class="interval ${prefix ? 'duration' : ''}">${prefix ? `<span class="duration-label">${prefix}</span>` : ''}<input type="number" min="0" max="${maximum}" step="1" value="${Math.round(value)}" ${attrs}${disabled(isDisabled)}><span>ms</span></label>`;
  }
  function renderTopline() {
    const columns = state.mode === 'clicker' ? '<div class="time-columns"><span class="column-label">间隔</span><span class="duration-space" aria-hidden="true"></span></div>' : '<span class="column-label">前置等待</span>';
    $('#topline').innerHTML = `<div class="topline"><span class="engine-label">输入方式</span><div class="segmented engines" role="group" aria-label="输入方式">${['原生', 'AHK', 'AHK窗口'].map(v => `<button data-action="engine" data-value="${v}" class="${state.engine === v ? 'active' : ''}" aria-pressed="${state.engine === v}"${disabled(busy())}>${v}</button>`).join('')}</div>${state.engine === 'AHK窗口' ? `<button data-action="select-window"${disabled(busy())}>选择窗口</button>` : ''}<div class="segmented mode-switch" role="group" aria-label="功能模式">${[['clicker', '连点模式'], ['macro', '操作录制']].map(([value, label]) => `<button data-action="mode" data-value="${value}" class="${state.mode === value ? 'active' : ''}" aria-pressed="${state.mode === value}"${disabled(busy())}>${label}</button>`).join('')}</div><span class="spacer"></span>${columns}</div>`;
  }
  function render() {
    $('.window').classList.toggle('busy', busy());
    renderTopline();
    if (state.mode === 'clicker') renderClicker(); else renderMacro();
    persist();
  }
  function revealActive() {
    const workspace = $('#workspace'), group = workspace.querySelector('.group.active');
    if (!group) return;
    const box = workspace.getBoundingClientRect(), top = group.getBoundingClientRect().top;
    if (top < box.top || top > box.bottom - 80) workspace.scrollTop += top - box.top;
  }
  function revealSelected() {
    const workspace = $('#workspace'), row = workspace.querySelector(`.macro-row[data-step-id="${selected}"]`);
    if (!row) return;
    const box = workspace.getBoundingClientRect(), r = row.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom) workspace.scrollTop += r.top - box.top - 80;
  }
  function groupHeader(group, index, count) {
    return `<div class="group-header"><button data-action="collapse" data-index="${index}" aria-label="${group.collapsed ? '展开' : '收起'}${escape(group.name)}" aria-expanded="${!group.collapsed}"${disabled(busy())}>${group.collapsed ? '▸' : '▾'}</button><button class="group-name" data-action="activate" data-index="${index}"${disabled(busy())}>${escape(group.name)}</button><button class="name-edit" data-action="rename" data-index="${index}" aria-label="重命名${escape(group.name)}" title="重命名"${disabled(busy())}>✎</button>${index === activeIndex() ? runtimeLabel() : ''}<span class="group-count">${count} ${state.mode === 'macro' ? '步' : '项'}</span><button class="icon-button delete" data-action="delete-group" data-index="${index}" aria-label="删除${escape(group.name)}"${disabled(busy())}>×</button><span class="active-dot" title="${index === activeIndex() ? '当前组' : '点击名称激活'}">●</span></div>`;
  }
  function renderClicker() {
    $('#workspace').innerHTML = state.groups.map((group, index) => `<section class="group ${index === state.activeClicker ? 'active' : ''}" data-group="${index}">${groupHeader(group, index, group.actions.length)}${group.collapsed ? '' : group.actions.length ? group.actions.map((action, row) => `<div class="row" draggable="${!busy()}" data-group="${index}" data-row="${row}"><span class="drag-handle" title="拖动排序">⋮⋮</span><button class="icon-button delete" data-action="delete-row" data-group="${index}" data-row="${row}" aria-label="删除动作 ${row + 1}"${disabled(busy())}>×</button><div class="row-control"><button class="${!action.hold ? 'selected' : ''}" data-action="action-mode" data-group="${index}" data-row="${row}" data-value="repeat" aria-pressed="${!action.hold}"${disabled(busy())}>间隔</button><button class="${action.enabled ? 'enabled' : 'disabled-state'}" data-action="toggle-action" data-group="${index}" data-row="${row}" aria-label="${action.enabled ? '停用' : '启用'}动作 ${row + 1}"${disabled(busy())}>${action.enabled ? '启' : '停'}</button><button class="${action.hold ? 'selected' : ''}" data-action="action-mode" data-group="${index}" data-row="${row}" data-value="hold" aria-pressed="${action.hold}"${disabled(busy())}>按住</button></div><button class="binding" data-action="capture-action" data-group="${index}" data-row="${row}"${disabled(busy())}>${escape(action.binding || '未设置按键')}</button>${interval(action.interval, `aria-label="动作 ${row + 1} 间隔" data-field="interval" data-group="${index}" data-row="${row}"`, busy() || action.hold)}${interval(action.pressMs, `aria-label="动作 ${row + 1} 按下时长" data-field="press" data-group="${index}" data-row="${row}" title="一次点按保持多久；0 ms 为立即松开"`, busy() || action.hold || !action.enabled, 99999, '持续')}</div>`).join('') : '<div class="empty"></div>'}</section>`).join('');
    $('#footer').innerHTML = `<div class="footer"><button class="add" data-action="add-action" aria-label="添加动作"${disabled(busy())}>＋</button><button class="quiet" data-action="add-group"${disabled(busy())}>新分组</button><button class="quiet" data-action="import"${disabled(busy())}>导入</button><button class="quiet" data-action="export"${disabled(busy())}>导出</button><span class="spacer"></span><button class="shutdown" data-action="shutdown">定时关机</button><span class="spacer"></span><span class="muted">快捷键</span><button class="hotkey" data-action="capture-hotkey"${disabled(busy())}>${escape(state.hotkey)}</button><button class="launch" data-action="play">${player ? '停止' : '启动'}</button></div>`;
  }
  function positionText(step) {
    if (step.x === null) return '—';
    const start = `${Math.round(step.x)}, ${Math.round(step.y)}`;
    return ['drag', 'move'].includes(step.type) ? `${start} → ${Math.round(step.endX)}, ${Math.round(step.endY)}` : start;
  }
  function stepMeta(step) {
    if (step.type === 'wheel') return `滚动 ${Math.abs(Math.round(step.delta))} · ${step.events.length} 个事件`;
    if (['drag', 'move'].includes(step.type)) return `轨迹 ${step.events.filter(e => Number.isFinite(e.x)).length} 点 · ${Math.round(step.duration)} ms`;
    return `持续 ${Math.round(step.duration)} ms · ${step.events.length} 个事件`;
  }
  function runtimeLabel() {
    if (recording) return `<span class="group-runtime ${recording.paused ? 'paused' : 'recording'}" role="status"><span class="record-dot"></span><span id="record-state">${recording.paused ? '已暂停' : '录制中'}</span><span id="record-clock" class="mono">${recordClock()}</span></span>`;
    if (player) return '<span class="group-runtime">运行中</span>';
    return '';
  }
  function renderMacro() {
    const selectedStep = activeMacro().steps.find(s => s.id === selected);
    const list = state.macros.map((macro, index) => `<section class="group ${index === state.activeMacro ? 'active' : ''}" data-group="${index}">${groupHeader(macro, index, macro.steps.length)}${macro.collapsed ? '' : macro.steps.length ? macro.steps.map((step, row) => `<div class="macro-row ${step.id === selected ? 'selected' : ''}" draggable="${!busy()}" data-step-id="${step.id}" data-group="${index}" data-row="${row}"><span class="drag-handle" title="拖动排序">⋮⋮</span><button class="icon-button delete" data-action="delete-row" data-group="${index}" data-row="${row}" aria-label="删除步骤 ${row + 1}"${disabled(busy())}>×</button><button class="step-button" data-action="select-step" data-group="${index}" data-row="${row}" aria-label="步骤 ${row + 1} ${escape(step.title)}"${disabled(busy())}><span class="step-number">${String(row + 1).padStart(2, '0')}</span><span><span class="step-title">${escape(step.title)}</span><span class="step-meta">${stepMeta(step)}</span></span></button><span class="step-position mono">${positionText(step)}</span>${interval(step.wait, `aria-label="步骤 ${row + 1} 前置等待" data-field="wait" data-group="${index}" data-row="${row}"`, busy())}</div>`).join('') : '<div class="empty"></div>'}</section>`).join('');
    $('#workspace').innerHTML = `<div class="macro-layout ${selectedStep ? 'with-detail' : ''}"><div>${list}</div>${selectedStep ? inspector(selectedStep) : ''}</div>`;
    $('#footer').innerHTML = `<div class="footer"><button class="add" data-action="add-group" aria-label="添加录制组"${disabled(busy())}>＋</button><button class="quiet" data-action="add-group"${disabled(busy())}>新分组</button><button class="quiet" data-action="import"${disabled(busy())}>导入</button><button class="quiet" data-action="export"${disabled(busy())}>导出</button><span class="spacer"></span><label>速度<select aria-label="回放速度" data-setting="speed"${disabled(busy())}>${[0.25, 0.5, 1, 1.5, 2, 4].map(n => `<option value="${n}"${state.speed === n ? ' selected' : ''}>${n}×</option>`).join('')}</select></label><label>循环<input type="number" min="1" max="99" data-setting="loops" value="${state.loops}" aria-label="循环次数"${disabled(busy())}>次</label><span class="spacer"></span><span class="muted">快捷键</span><button class="hotkey" data-action="capture-hotkey"${disabled(busy())}>${escape(state.recordHotkey)}</button>${recording ? `<button data-action="pause-record">${recording.paused ? '继续' : '暂停'}</button>` : `<button data-action="play"${disabled(!activeMacro().steps.length && !player)}>${player ? '停止回放' : '回放'}</button>`}<button class="launch ${recording ? 'record-stop' : ''}" data-action="record"${disabled(!!player)}>${recording ? '停止' : '启动'}</button></div>`;
  }
  function inspector(step) {
    const points = step.events.filter(e => Number.isFinite(e.x));
    const c = activeMacro().canvas;
    const path = points.map(p => `${p.x},${p.y}`).join(' ');
    return `<aside class="inspector" aria-label="步骤详情"><div class="inspector-header"><h3>步骤详情</h3><button class="icon-button" data-action="close-detail" aria-label="关闭步骤详情">×</button></div><div class="step-full-title">${escape(step.title)}</div>${points.length ? `<div class="preview-mini"><svg viewBox="0 0 ${c.width} ${c.height}" preserveAspectRatio="none" aria-label="鼠标路径"><polyline points="${path}" fill="none" stroke="var(--border-hover)" stroke-width="3"/><circle cx="${step.x}" cy="${step.y}" r="5" fill="var(--ink)"/></svg><span class="preview-cursor" hidden></span></div><div class="fields"><div><label for="step-x">起点 X</label><input id="step-x" type="number" min="-10000" max="10000" value="${Math.round(step.x)}" data-edit="x"${disabled(busy())}></div><div><label for="step-y">起点 Y</label><input id="step-y" type="number" min="-10000" max="10000" value="${Math.round(step.y)}" data-edit="y"${disabled(busy())}></div></div>` : ''}<label for="step-wait">前置等待（ms）</label><input id="step-wait" type="number" min="0" max="600000" value="${step.wait}" data-edit="wait"${disabled(busy())}>${step.duration ? `<label for="step-duration">持续时间（ms）</label><input id="step-duration" type="number" min="1" max="600000" value="${step.duration}" data-edit="duration"${disabled(busy())}>` : ''}<details><summary>原始事件 · ${step.events.length} 条</summary><div class="event-list">${step.events.map(e => `<div>${Math.round(e.t)}ms ${escape(eventLabel(e))}</div>`).join('')}</div></details></aside>`;
  }
  function eventLabel(e) {
    const action = {key_down: '↓', key_up: '↑', mouse_down: '↓', mouse_up: '↑', move: '移动', wheel: '滚动'}[e.type];
    const name = e.key ? `${e.key} [${e.code}]` : e.button !== undefined ? [...(e.modifiers || []), M.buttonName[e.button]].join(' + ') : e.type === 'wheel' ? `${e.dy >= 0 ? '+' : ''}${Math.round(e.dy)}px` : '';
    return `${name} ${action}${Number.isFinite(e.x) ? ` (${Math.round(e.x)}, ${Math.round(e.y)})` : ''}`;
  }
  function openForm(title, content, submit) {
    const dialog = $('#editor-dialog');
    dialog.innerHTML = `<form id="edit-form"><h2>${escape(title)}</h2>${content}<div class="dialog-actions"><button type="button" data-action="close-editor">取消</button><button type="submit" class="launch">确定</button></div></form>`;
    $('#edit-form').onsubmit = e => { e.preventDefault(); submit(new FormData(e.currentTarget)); dialog.close(); render(); };
    dialog.showModal();
    const field = dialog.querySelector('input'); if (field) { field.focus(); field.select(); }
  }
  function editName(index) {
    const group = groups()[index];
    openForm('重命名', `<label for="group-name">名称</label><input id="group-name" name="name" required maxlength="60" value="${escape(group.name)}">`, data => { const name = String(data.get('name')).trim(); if (name) group.name = name; });
  }
  function addGroup() {
    const items = groups();
    if (items.length >= 50) return toast('最多保留 50 个分组。');
    if (state.mode === 'clicker') { items.push({id: M.uid(), name: `动作组 ${items.length + 1}`, actions: [], collapsed: false}); state.activeClicker = items.length - 1; }
    else { items.push({id: M.uid(), name: `录制 ${items.length + 1}`, steps: [], collapsed: false, sample: false, coordinateSpace: 'prototype_canvas_css_px', canvas: {width: 460, height: 260}}); state.activeMacro = items.length - 1; }
    if (state.mode === 'macro') items.forEach((item, index) => { item.collapsed = index !== state.activeMacro; });
    selected = null; render(); revealActive(); status('已新建');
  }
  function deleteGroup(index) {
    if (groups().length <= 1) return toast('至少保留一个分组。');
    snapshot(); groups().splice(index, 1);
    const key = state.mode === 'clicker' ? 'activeClicker' : 'activeMacro';
    state[key] = Math.max(0, Math.min(state[key] > index ? state[key] - 1 : state[key], groups().length - 1));
    selected = null; render(); toast('已删除分组', true);
  }
  function captureBinding(group, row, hotkey = false) {
    capture = {group, row, hotkey: hotkey ? (state.mode === 'macro' ? 'recordHotkey' : 'hotkey') : null, keys: new Set()};
    $('#editor-dialog').innerHTML = `<h2>${hotkey ? '录入快捷键' : '录入动作'}</h2><div class="capture-prompt" tabindex="0"><span id="capture-label">请按下${hotkey ? '键盘按键' : '按键或鼠标按钮'}</span><small>支持组合键 · 最后一次输入 1 秒后完成</small></div><div class="dialog-actions"><button data-action="close-editor">取消</button></div>`;
    $('#editor-dialog').showModal(); $('.capture-prompt').focus();
  }
  function finishCapture() {
    if (!capture || !capture.keys.size) return;
    const binding = [...capture.keys].join(' + ');
    if (capture.hotkey) {
      if (binding === state[capture.hotkey === 'hotkey' ? 'recordHotkey' : 'hotkey'] || binding === 'F10') { toast('快捷键冲突，请重新设置。'); capture.keys.clear(); $('#capture-label').textContent = '请重新按键'; return; }
      state[capture.hotkey] = binding;
    } else state.groups[capture.group].actions[capture.row].binding = binding;
    capture = null; $('#editor-dialog').close(); render(); toast('已录入：' + binding);
  }
  function addCaptured(name) {
    if (!capture) return;
    capture.keys.add(name); $('#capture-label').textContent = '已录入：' + [...capture.keys].join(' + ');
    clearTimeout(captureTimer); captureTimer = setTimeout(finishCapture, 1000);
  }
  function exportFile() {
    const blob = new Blob([JSON.stringify(state, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = '轻云配置.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast('已导出');
  }
  // This shell expresses the desktop recorder's state. Event acquisition
  // belongs to the Windows engine; do not substitute page-local capture.
  function startRecord() {
    if (busy()) return;
    if (activeMacro().steps.length) {
      if (state.macros.length >= 50) return toast('录制分组已满。');
      addGroup();
    }
    activeMacro().collapsed = false;
    selected = null;
    recording = {started: performance.now(), paused: false, pausedTotal: 0, pausedAt: 0};
    render(); revealActive(); status('录制中');
    clockTimer = setInterval(updateRecordClock, 100);
  }
  function recordClock() {
    if (!recording) return '00:00.0';
    const now = recording.paused ? recording.pausedAt : performance.now();
    const ms = Math.max(0, now - recording.started - recording.pausedTotal);
    return `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${(ms / 1000 % 60).toFixed(1).padStart(4, '0')}`;
  }
  function updateRecordClock() {
    const clock = $('#record-clock'); if (clock) clock.textContent = recordClock();
  }
  function pauseRecord() {
    if (!recording) return;
    if (recording.paused) recording.pausedTotal += performance.now() - recording.pausedAt;
    else recording.pausedAt = performance.now();
    recording.paused = !recording.paused;
    render(); status(recording.paused ? '已暂停' : '录制中');
  }
  function stopRecord() {
    if (!recording) return;
    clearInterval(clockTimer); clockTimer = null;
    recording = null; render(); status('已停止');
    // No engine is attached yet: never manufacture a recording or steps.
  }
  function shortcut(event) {
    const keys = []; if (event.ctrlKey) keys.push('Ctrl'); if (event.shiftKey) keys.push('Shift'); if (event.altKey) keys.push('Alt'); if (event.metaKey) keys.push('Win');
    const key = M.keyName(event); if (!['Ctrl', 'Shift', 'Alt', 'Win'].includes(key)) keys.push(key); return keys.join(' + ');
  }
  document.addEventListener('keydown', event => {
    if (capture) { event.preventDefault(); if (!event.repeat) addCaptured(M.keyName(event)); return; }
    if (event.repeat || $('#editor-dialog').open) return;
    if (event.key === 'F10') {
      if (player || recording) { event.preventDefault(); player ? stopPlayer() : stopRecord(); }
      return;
    }
    if (recording) {
      if (shortcut(event) === state.recordHotkey) { event.preventDefault(); stopRecord(); }
      return;
    }
    if (event.target.matches('input,select,textarea')) return;
    if (shortcut(event) === state.hotkey) { event.preventDefault(); togglePlayer(); }
    else if (shortcut(event) === state.recordHotkey && state.mode === 'macro') { event.preventDefault(); startRecord(); }
  });
  document.addEventListener('mousedown', event => {
    if (capture && !capture.hotkey && event.target.closest('.capture-prompt')) {
      event.preventDefault(); addCaptured(M.buttonName[event.button] || '鼠标');
    }
  });
  $('#editor-dialog').addEventListener('cancel', () => { clearTimeout(captureTimer); capture = null; });
  function stopPlayer(message = '已停止。') {
    if (!player) return;
    clearInterval(player.timer); player = null; render(); status(message);
  }
  function togglePlayer() {
    if (player) return stopPlayer();
    if (recording) return;
    if (state.mode === 'clicker') {
      const actions = active().actions.filter(a => a.enabled && a.binding);
      if (!actions.length) return toast('请先添加并录入一个启用的动作。');
      player = {kind: 'clicker', started: performance.now(), timer: null}; render(); status('运行中');

      return;
    }
    const macro = activeMacro(); if (!macro.steps.length) return toast('当前组没有步骤。');
    const list = [], speed = state.speed;
    for (let loop = 0, cursor = 0; loop < state.loops; loop++) {
      for (const step of macro.steps) {
        cursor += step.wait / speed;
        list.push({start: cursor, end: cursor + Math.max(step.duration / speed, 1), step, loop: loop + 1}); cursor += step.duration / speed;
      }
      if (loop < state.loops - 1) cursor += state.loopGap;
    }
    player = {kind: 'macro', started: performance.now(), timeline: list, timer: null, current: null, macro};
    state.macros.forEach(item => { item.collapsed = item !== macro; });
    selected = macro.steps[0].id; render(); revealActive(); status('回放中');
    player.timer = setInterval(tickPlayer, 16);
  }
  function tickPlayer() {
    if (!player || player.kind !== 'macro') return;
    const elapsed = performance.now() - player.started, last = player.timeline.at(-1);
    if (elapsed > last.end + 250) return stopPlayer(`回放完成`);
    const item = player.timeline.findLast(p => elapsed >= p.start);
    const next = player.timeline.find(p => p.start > elapsed);
    if (!item) { status(next ? `等待 ${Math.ceil(next.start - elapsed)} ms · 第 ${next.loop}/${state.loops} 次` : '回放完成'); return; }
    if (player.current !== item) {
      player.current = item;
      document.querySelectorAll('.macro-row').forEach(row => row.classList.toggle('playing', row.dataset.stepId === item.step.id));
      const row = document.querySelector(`.macro-row[data-step-id="${item.step.id}"]`), workspace = $('#workspace');
      if (row) { const r = row.getBoundingClientRect(), box = workspace.getBoundingClientRect(); if (r.bottom > box.bottom || r.top < box.top) workspace.scrollTop += r.top - box.top - 60; }
      selected = item.step.id;
      const inspectorHost = $('.inspector'); if (inspectorHost) inspectorHost.outerHTML = inspector(item.step);
    }
    status(elapsed > item.end && next ? `已完成 ${item.step.title} · 等待 ${Math.ceil(next.start - elapsed)} ms · 第 ${next.loop}/${state.loops} 次` : `回放中 · 第 ${item.loop}/${state.loops} 次 · ${item.step.title} · ${time(elapsed)}`);
    const t = (elapsed - item.start) * state.speed;
    const positions = item.step.events.filter(e => Number.isFinite(e.x) && e.t <= t);
    const p = positions.at(-1), cursor = $('.preview-cursor');
    if (p && cursor) { cursor.hidden = false; cursor.style.left = p.x / player.macro.canvas.width * 100 + '%'; cursor.style.top = p.y / player.macro.canvas.height * 100 + '%'; }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-action]'); if (!button || button.disabled) return;
    const action = button.dataset.action, index = Number(button.dataset.index), g = Number(button.dataset.group), row = Number(button.dataset.row);
    if (action === 'close-editor') { clearTimeout(captureTimer); capture = null; $('#editor-dialog').close(); return; }
    if (action === 'record') return recording ? stopRecord() : startRecord();
    if (action === 'pause-record') return pauseRecord();
    if (action === 'play') return togglePlayer();
    if (action === 'shutdown') return openForm('定时关机', '<label for="hours">小时</label><input id="hours" name="hours" type="number" min="0" max="168" value="0"><label for="minutes">分钟</label><input id="minutes" name="minutes" type="number" min="0" max="59" value="30">', () => toast('已关闭设置'));
    if (busy()) return;
    switch (action) {
      case 'mode': state.mode = button.dataset.value; selected = null; render(); status('就绪'); break;
      case 'engine': state.engine = button.dataset.value; render(); status('已切换输入方式'); break;
      case 'select-window': toast('尚未连接窗口列表。'); break;
      case 'collapse': groups()[index].collapsed = !groups()[index].collapsed; render(); break;
      case 'activate': state[state.mode === 'clicker' ? 'activeClicker' : 'activeMacro'] = index; groups()[index].collapsed = false; selected = null; render(); revealActive(); break;
      case 'rename': editName(index); break;
      case 'delete-group': deleteGroup(index); break;
      case 'add-group': addGroup(); break;
      case 'add-action': if (active().actions.length >= 500) return toast('当前动作组已满。'); active().actions.push({id: M.uid(), binding: '', enabled: true, hold: false, interval: 1000, pressMs: M.DEFAULT_PRESS_MS}); active().collapsed = false; render(); break;
      case 'delete-row': snapshot(); (state.mode === 'clicker' ? state.groups[g].actions : state.macros[g].steps).splice(row, 1); render(); toast('已删除', true); break;
      case 'action-mode': state.groups[g].actions[row].hold = button.dataset.value === 'hold'; render(); break;
      case 'toggle-action': state.groups[g].actions[row].enabled = !state.groups[g].actions[row].enabled; render(); break;
      case 'capture-action': captureBinding(g, row); break;
      case 'capture-hotkey': captureBinding(0, 0, true); break;
      case 'select-step': state.activeMacro = g; selected = state.macros[g].steps[row].id; render(); revealSelected(); break;
      case 'close-detail': selected = null; render(); break;

      case 'import': $('#import-file').click(); break;
      case 'export': exportFile(); break;
      case 'undo': if (undoState) { state = JSON.parse(undoState); undoState = null; selected = null; render(); toast('已撤销'); } break;
    }
  });
  // Save typed values on input as well as change. Keep focus and incomplete
  // numeric text intact; the change handler redraws derived labels on blur.
  document.addEventListener('input', event => {
    const el = event.target;
    if (busy() || !el.matches('input[type=number]') || el.value === '' || !Number.isFinite(Number(el.value))) return;
    if (el.dataset.setting) {
      const key = el.dataset.setting;
      state[key] = key === 'speed' ? M.clamp(el.value, 0.25, 4) : Math.round(M.clamp(el.value, key === 'loops' ? 1 : 0, key === 'loops' ? 99 : 60000));
    }
    if (el.dataset.field) {
      const g = Number(el.dataset.group), r = Number(el.dataset.row);
      if (el.dataset.field === 'interval') state.groups[g].actions[r].interval = Math.round(M.clamp(el.value, 1, 99999));
      else if (el.dataset.field === 'press') state.groups[g].actions[r].pressMs = Math.round(M.clamp(el.value, 0, 99999));
      else state.macros[g].steps[r].wait = Math.round(M.clamp(el.value, 0, 600000));
    }
    if (el.dataset.edit) {
      const step = activeMacro().steps.find(s => s.id === selected); if (!step) return;
      if (el.dataset.edit === 'wait') {
        step.wait = Math.round(M.clamp(el.value, 0, 600000));
        const rowInput = document.querySelector(`.macro-row[data-step-id="${selected}"] input`); if (rowInput) rowInput.value = step.wait;
      }
      if (el.dataset.edit === 'duration') M.resizeStep(step, el.value);
      if (el.dataset.edit === 'x') M.moveStep(step, M.clamp(el.value, -10000, 10000), step.y);
      if (el.dataset.edit === 'y') M.moveStep(step, step.x, M.clamp(el.value, -10000, 10000));
    }
    persist();
  });
  document.addEventListener('change', event => {
    const el = event.target; if (busy()) return;
    if (el.dataset.setting) {
      const key = el.dataset.setting;
      state[key] = key === 'speed' ? M.clamp(el.value, 0.25, 4) : Math.round(M.clamp(el.value, key === 'loops' ? 1 : 0, key === 'loops' ? 99 : 60000));
      el.value = state[key]; persist();
    }
    if (el.dataset.field) {
      const g = Number(el.dataset.group), r = Number(el.dataset.row);
      if (el.dataset.field === 'interval') state.groups[g].actions[r].interval = Math.round(M.clamp(el.value, 1, 99999));
      else if (el.dataset.field === 'press') state.groups[g].actions[r].pressMs = Math.round(M.clamp(el.value, 0, 99999));
      else state.macros[g].steps[r].wait = Math.round(M.clamp(el.value, 0, 600000));
      render();
    }
    if (el.dataset.edit) {
      const step = activeMacro().steps.find(s => s.id === selected); if (!step) return;
      const value = Number(el.value);
      if (!Number.isFinite(value)) return;
      if (el.dataset.edit === 'wait') step.wait = Math.round(M.clamp(value, 0, 600000));
      if (el.dataset.edit === 'duration') M.resizeStep(step, value);
      if (el.dataset.edit === 'x') M.moveStep(step, M.clamp(value, -10000, 10000), step.y);
      if (el.dataset.edit === 'y') M.moveStep(step, step.x, M.clamp(value, -10000, 10000));
      render(); status('已修改');
    }
  });
  $('#import-file').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('文件超过 5 MB，请缩小后导入。');
      const imported = M.validate(JSON.parse(await file.text()));
      snapshot(); state = imported; selected = null; render(); toast('已导入', true); status('已导入');
    } catch (error) { toast(error.message || '文件无法读取。'); }
    event.target.value = '';
  });
  document.addEventListener('dragstart', event => {
    const row = event.target.closest('.row,.macro-row');
    if (!row || busy() || event.target.matches('input')) { event.preventDefault(); return; }
    dragSource = {group: Number(row.dataset.group), row: Number(row.dataset.row)};
    event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(dragSource.row));
  });
  document.addEventListener('dragover', event => { if (dragSource && event.target.closest('.row,.macro-row')) event.preventDefault(); });
  document.addEventListener('drop', event => {
    const row = event.target.closest('.row,.macro-row'); if (!row || !dragSource || busy()) return;
    event.preventDefault(); const targetGroup = Number(row.dataset.group), targetRow = Number(row.dataset.row);
    if (targetGroup === dragSource.group) {
      snapshot(); const items = state.mode === 'clicker' ? state.groups[targetGroup].actions : state.macros[targetGroup].steps;
      items.splice(targetRow, 0, items.splice(dragSource.row, 1)[0]); render(); status('顺序已调整。');
    }
    dragSource = null;
  });
  document.addEventListener('dragend', () => { dragSource = null; });
  window.addEventListener('beforeunload', () => { clearInterval(clockTimer); if (player) clearInterval(player.timer); });
  render();
  if (state.mode === 'macro') revealActive();
  if (storageError) toast('配置读取失败，已载入默认设置。');
})();
