(function (root) {
  'use strict';
  const uid = () => Math.random().toString(36).slice(2, 10);
  const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, finite(value, min)));
  const modifiers = ['Ctrl', 'Shift', 'Alt', 'Win'];
  const DEFAULT_PRESS_MS = 50;
  const buttonName = {0: '鼠标左键', 1: '鼠标中键', 2: '鼠标右键', 3: '鼠标侧键 1', 4: '鼠标侧键 2'};
  function keyName(event) {
    return ({Control: 'Ctrl', Meta: 'Win', ' ': 'Space', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Escape: 'Esc'})[event.key] || (event.key.length === 1 ? event.key.toUpperCase() : event.key);
  }
  function describe(events) {
    const keys = [...new Set([...events.filter(e => e.type === 'key_down').map(e => e.key), ...events.flatMap(e => e.modifiers || [])])];
    keys.sort((a, b) => (modifiers.indexOf(a) < 0 ? 10 : modifiers.indexOf(a)) - (modifiers.indexOf(b) < 0 ? 10 : modifiers.indexOf(b)));
    const pressed = new Map(), chords = [];
    for (const event of events) {
      if (event.type === 'key_down') {
        pressed.set(event.code, event.key);
        if (!modifiers.includes(event.key)) {
          const names = [...new Set(pressed.values())];
          names.sort((a, b) => (modifiers.indexOf(a) < 0 ? 10 : modifiers.indexOf(a)) - (modifiers.indexOf(b) < 0 ? 10 : modifiers.indexOf(b)));
          const previous = chords.at(-1);
          if (previous && previous.codes.every(code => pressed.has(code))) chords.pop();
          chords.push({names, codes: [...pressed.keys()]});
        }
      } else if (event.type === 'key_up') pressed.delete(event.code);
    }
    const keyboardTitle = chords.length ? chords.map(chord => chord.names.join(' + ')).join(' → ') : keys.join(' + ');
    const mouse = events.find(e => e.type === 'mouse_down');
    const points = events.filter(e => Number.isFinite(e.x));
    const duration = events.at(-1).t;
    const first = points[0], last = points.at(-1);
    const travel = first ? Math.max(...points.map(p => Math.hypot(p.x - first.x, p.y - first.y))) : 0;
    const wheel = events.filter(e => e.type === 'wheel');
    let type, title;
    if (mouse) {
      type = travel > 4 ? 'drag' : duration >= 500 ? 'hold' : 'click';
      title = [keyboardTitle, buttonName[mouse.button] || '鼠标'].filter(Boolean).join(' + ') + (type === 'drag' ? ' · 拖动' : type === 'hold' ? ' · 长按' : ' · 点击');
    } else if (wheel.length) {
      type = 'wheel';
      const total = wheel.reduce((sum, e) => sum + e.dy, 0);
      title = (keys.length ? keys.join(' + ') + ' + ' : '') + (total >= 0 ? '向下滚动' : '向上滚动');
    } else if (keys.length) {
      type = keys.length > 1 ? 'combo' : duration >= 500 ? 'hold' : 'key';
      title = keyboardTitle + (type === 'hold' ? ' · 长按' : '');
    } else {
      type = 'move'; title = '移动鼠标';
    }
    return {type, title, keys, x: first?.x ?? null, y: first?.y ?? null, endX: last?.x ?? null, endY: last?.y ?? null, delta: wheel.reduce((sum, e) => sum + e.dy, 0)};
  }
  // Merge overlapping input into one executable segment. Preserve every down/up
  // and its relative time, even when the display summarizes it as a chord.
  function toSteps(raw) {
    const sorted = raw.map((e, i) => ({...e, at: Math.max(0, finite(e.at)), order: i})).sort((a, b) => a.at - b.at || a.order - b.order);
    const steps = [], held = new Set();
    let pending = [], end = 0;
    const flush = () => {
      if (!pending.length) return;
      const start = pending[0].at;
      const events = pending.map(({at, order, ...e}) => ({...e, t: at - start}));
      steps.push({id: uid(), ...describe(events), wait: Math.max(0, Math.round(start - end)), duration: Math.round(events.at(-1).t), events});
      end = pending.at(-1).at; pending = [];
    };
    for (const e of sorted) {
      const down = e.type.endsWith('_down'), up = e.type.endsWith('_up');
      const token = e.type.startsWith('key_') ? 'k:' + (e.code || e.key) : 'm:' + e.button;
      if (!held.size && pending.length && (down || e.type !== pending.at(-1).type || e.at - pending.at(-1).at > 250)) flush();
      if (down) held.add(token);
      pending.push(e);
      if (up) held.delete(token);
      if (!held.size && up) flush();
    }
    flush(); return steps;
  }
  function duration(steps) { return Math.round(steps.reduce((sum, s) => sum + s.wait + s.duration, 0)); }
  function resizeStep(step, ms) {
    const target = clamp(ms, 1, 600000), source = step.duration;
    step.events.forEach(e => { e.t = source ? e.t / source * target : (e.type.endsWith('_up') ? target : 0); });
    step.duration = target;
    Object.assign(step, describe(step.events));
  }
  function moveStep(step, x, y) {
    const dx = finite(x) - (step.x ?? 0), dy = finite(y) - (step.y ?? 0);
    step.events.forEach(e => { if (Number.isFinite(e.x)) { e.x += dx; e.y += dy; } });
    Object.assign(step, describe(step.events));
  }
  function sample() {
    const events = [
      {at: 350, type: 'mouse_down', button: 0, x: 150, y: 96},
      {at: 430, type: 'mouse_up', button: 0, x: 150, y: 96},
      {at: 900, type: 'key_down', key: 'Ctrl', code: 'ControlLeft'},
      {at: 930, type: 'key_down', key: 'C', code: 'KeyC'},
      {at: 990, type: 'key_up', key: 'C', code: 'KeyC'},
      {at: 1020, type: 'key_up', key: 'Ctrl', code: 'ControlLeft'},
      {at: 1500, type: 'mouse_down', button: 0, x: 312, y: 136},
      {at: 1580, type: 'mouse_up', button: 0, x: 312, y: 136},
      {at: 2100, type: 'key_down', key: 'Ctrl', code: 'ControlLeft'},
      {at: 2120, type: 'key_down', key: 'V', code: 'KeyV'},
      {at: 2200, type: 'key_up', key: 'V', code: 'KeyV'},
      {at: 2250, type: 'key_up', key: 'Ctrl', code: 'ControlLeft'},
      {at: 2670, type: 'mouse_down', button: 0, x: 95, y: 200},
      ...Array.from({length: 13}, (_, i) => ({at: 2700 + i * 40, type: 'move', x: Math.round(95 + i * 16), y: Math.round(200 - Math.sin(i / 12 * Math.PI) * 38)})),
      {at: 3240, type: 'mouse_up', button: 0, x: 287, y: 200},
      {at: 3660, type: 'wheel', x: 330, y: 220, dy: 240, dx: 0},
      {at: 4200, type: 'key_down', key: 'Shift', code: 'ShiftLeft'},
      {at: 4220, type: 'mouse_down', button: 0, x: 390, y: 86},
      {at: 4330, type: 'mouse_up', button: 0, x: 390, y: 86},
      {at: 4360, type: 'key_up', key: 'Shift', code: 'ShiftLeft'}
    ];
    return {id: uid(), name: '复制并整理 · 示例', sample: true, collapsed: false, steps: toSteps(events), coordinateSpace: 'prototype_canvas_css_px', canvas: {width: 460, height: 260}};
  }
  function defaults() {
    return {format: 'qingyun-web-prototype', version: 1, mode: 'clicker', engine: '原生', hotkey: 'F8', recordHotkey: 'F9', speed: 1, loops: 1, loopGap: 500, activeClicker: 0, activeMacro: 0,
      groups: [{id: uid(), name: '动作组 1', collapsed: false, actions: [{id: uid(), binding: 'Enter', enabled: true, hold: false, interval: 2000, pressMs: DEFAULT_PRESS_MS}, {id: uid(), binding: '鼠标左键', enabled: true, hold: false, interval: 99999, pressMs: DEFAULT_PRESS_MS}]}],
      macros: [{id: uid(), name: '录制 1', collapsed: false, sample: false, steps: [], coordinateSpace: 'prototype_canvas_css_px', canvas: {width: 460, height: 260}}]};
  }
  function validate(raw) {
    if (!raw || raw.format !== 'qingyun-web-prototype' || raw.version !== 1) throw new Error('请导入本网页原型导出的 JSON；桌面版配置使用不同格式。');
    const result = defaults();
    if (!Array.isArray(raw.groups) || !raw.groups.length || raw.groups.length > 50 || !Array.isArray(raw.macros) || !raw.macros.length || raw.macros.length > 50) throw new Error('分组数量无效（每种模式 1–50 组）。');
    const label = v => String(v || '').slice(0, 100);
    result.groups = raw.groups.map(g => {
      if (!Array.isArray(g.actions) || g.actions.length > 500) throw new Error('动作列表无效。');
      return {id: uid(), name: label(g.name) || '动作组', collapsed: !!g.collapsed, actions: g.actions.map(a => ({id: uid(), binding: label(a.binding), enabled: a.enabled !== false, hold: !!a.hold, interval: Math.round(clamp(a.interval, 1, 99999)), pressMs: Number.isFinite(a.pressMs) ? Math.round(clamp(a.pressMs, 0, 99999)) : DEFAULT_PRESS_MS}))};
    });
    let eventCount = 0;
    const types = new Set(['key_down', 'key_up', 'mouse_down', 'mouse_up', 'move', 'wheel']);
    result.macros = raw.macros.map(m => {
      if (!Array.isArray(m.steps) || m.steps.length > 1000) throw new Error('步骤列表无效。');
      const steps = m.steps.map(s => {
        if (!Array.isArray(s.events) || !s.events.length || (eventCount += s.events.length) > 20000) throw new Error('原始事件无效或数量过多。');
        let prev = -1;
        const held = new Set();
        const events = s.events.map(e => {
          if (!types.has(e.type) || !Number.isFinite(e.t) || e.t < prev || e.t < 0 || e.t > 600000) throw new Error('事件类型或时间无效。');
          prev = e.t;
          const event = {type: e.type, t: e.t};
          if (e.type.startsWith('key_')) { event.key = label(e.key); event.code = label(e.code); if (!event.key || !event.code) throw new Error('键盘事件缺少键值。'); }
          else { if (!Number.isFinite(e.x) || !Number.isFinite(e.y) || Math.abs(e.x) > 100000 || Math.abs(e.y) > 100000) throw new Error('坐标无效。'); event.x = e.x; event.y = e.y; }
          if (e.type.startsWith('mouse_')) { if (![0, 1, 2, 3, 4].includes(e.button)) throw new Error('鼠标按钮无效。'); event.button = e.button; }
          if (e.modifiers !== undefined) { if (!Array.isArray(e.modifiers) || e.modifiers.length > 4 || e.modifiers.some(key => !modifiers.includes(key))) throw new Error('修饰键状态无效。'); event.modifiers = [...new Set(e.modifiers)]; }
          if (e.type === 'wheel') { if (!Number.isFinite(e.dy) || !Number.isFinite(e.dx)) throw new Error('滚轮数据无效。'); event.dy = e.dy; event.dx = e.dx; }
          if (e.type.endsWith('_down') || e.type.endsWith('_up')) {
            const token = e.type.startsWith('key_') ? 'k:' + event.code : 'm:' + event.button;
            if (e.type.endsWith('_down')) { if (held.has(token)) throw new Error('重复按下事件。'); held.add(token); }
            else { if (!held.has(token)) throw new Error('松开事件缺少对应按下。'); held.delete(token); }
          }
          return event;
        });
        if (held.size) throw new Error('序列含未松开的按键。');
        return {id: uid(), ...describe(events), wait: Math.round(clamp(s.wait, 0, 600000)), duration: Math.round(events.at(-1).t), events};
      });
      return {id: uid(), name: label(m.name) || '录制', sample: !!m.sample, collapsed: !!m.collapsed, steps, coordinateSpace: 'prototype_canvas_css_px', canvas: {width: clamp(m.canvas?.width, 1, 2000), height: clamp(m.canvas?.height, 1, 2000)}};
    });
    result.mode = raw.mode === 'macro' ? 'macro' : 'clicker';
    result.engine = ['原生', 'AHK', 'AHK窗口'].includes(raw.engine) ? raw.engine : '原生';
    result.speed = clamp(raw.speed, 0.25, 4); result.loops = Math.round(clamp(raw.loops, 1, 99)); result.loopGap = Math.round(clamp(raw.loopGap, 0, 60000));
    result.activeClicker = Math.round(clamp(raw.activeClicker, 0, result.groups.length - 1));
    result.activeMacro = Math.round(clamp(raw.activeMacro, 0, result.macros.length - 1));
    result.hotkey = label(raw.hotkey) || 'F8'; result.recordHotkey = label(raw.recordHotkey) || 'F9';
    return result;
  }
  const api = {DEFAULT_PRESS_MS, uid, clamp, keyName, buttonName, describe, toSteps, duration, resizeStep, moveStep, sample, defaults, validate};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.QingyunModel = api;
})(typeof window === 'undefined' ? globalThis : window);
