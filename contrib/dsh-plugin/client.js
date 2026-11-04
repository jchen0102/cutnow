/**
 * vcut 剪辑台（右侧抽屉）：会话不被顶掉，工作台浮在右侧。
 * 侧栏底部按钮开关；数据来自本地引擎，与 agent 工具同一份 EDL。
 */
window.__ModuleLoader__.load({
  id: '@local/cutnow-panel',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useCallback, useRef } = React

    const BASE = 'http://127.0.0.1:8799'
    const fmt = (n) => (Number(n) || 0).toFixed(2)

    // ---- 开关状态：两个槽位共享 ----
    let open = true
    const subs = new Set()
    const setOpen = (v) => { open = v; subs.forEach((f) => f()) }
    const toggle = () => setOpen(!open)
    function useOpen() {
      const [, force] = useState(0)
      useEffect(() => { const cb = () => force((x) => x + 1); subs.add(cb); return () => subs.delete(cb) }, [])
      return open
    }

    const T = {
      zh: { render: '渲染新版本', rendering: '渲染中…', beats: '拍数', start: '源起点', apply: '应用',
            shots: '镜头', versions: '版本', decisions: '决策', total: '总长', empty: '还没有版本',
            failed: '连不上本地引擎', retry: '重试', close: '收起' },
      en: { render: 'Render', rendering: 'Rendering…', beats: 'Beats', start: 'Source in', apply: 'Apply',
            shots: 'Shots', versions: 'Versions', decisions: 'Decisions', total: 'Total', empty: 'No version',
            failed: 'Engine unreachable', retry: 'Retry', close: 'Hide' },
    }

    const S = {
      drawer: { position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(880px, 58vw)', minWidth: 460,
        zIndex: 40, display: 'flex', flexDirection: 'column', pointerEvents: 'auto',
        background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)',
        borderLeft: '1px solid var(--dsw-alias-border-l1)', boxShadow: '-16px 0 32px rgba(0,0,0,.18)' },
      head: { display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
        borderBottom: '1px solid var(--dsw-alias-border-l1)' },
      body: { flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '150px minmax(0,1fr) 230px' },
      col: { padding: 10, overflow: 'auto', borderRight: '1px solid var(--dsw-alias-border-l1)', minHeight: 0 },
      colLast: { padding: 10, overflow: 'auto', minHeight: 0 },
      h2: { fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)', margin: '2px 0 6px' },
      small: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' },
      item: (on) => ({ display: 'flex', gap: 6, alignItems: 'center', padding: 5, marginBottom: 4, cursor: 'pointer',
        borderRadius: 6, border: '1px solid ' + (on ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-border-l1)'),
        background: on ? 'var(--dsw-alias-bg-layer-1)' : 'transparent' }),
      thumb: { width: 42, height: 24, objectFit: 'cover', borderRadius: 3, background: '#000', flex: '0 0 auto' },
      btn: { padding: '5px 10px', borderRadius: 6, fontSize: 12, cursor: 'pointer',
        border: '1px solid var(--dsw-alias-border-l1)', background: 'var(--dsw-alias-bg-layer-1)', color: 'var(--dsw-alias-label-primary)' },
      btnPrimary: { padding: '5px 10px', borderRadius: 6, fontSize: 12, cursor: 'pointer', border: 'none',
        background: 'var(--dsw-alias-brand-primary)', color: '#fff', fontWeight: 600 },
      row: { display: 'flex', alignItems: 'center', gap: 6, margin: '5px 0' },
      input: { flex: 1, padding: '3px 5px', fontSize: 12, borderRadius: 5, background: 'var(--dsw-alias-bg-layer-1)',
        border: '1px solid var(--dsw-alias-border-l1)', color: 'var(--dsw-alias-label-primary)' },
    }

    function PanelBody({ ctx }) {
      const [state, setState] = useState(null)
      const [sel, setSel] = useState(0)
      const [draft, setDraft] = useState({ beats: 8, start: 0 })
      const [err, setErr] = useState(false)
      const [busy, setBusy] = useState(false)
      const [ver, setVer] = useState(null)
      const dirty = useRef(false)

      let lang = 'zh'
      try { const s = ctx?.locale?.getLocale?.(); if (s && String(s.id || '').startsWith('en')) lang = 'en' } catch {}
      const t = T[lang]

      const load = useCallback(async () => {
        try { const r = await fetch(BASE + '/api/state'); const s = await r.json(); setState(s); setErr(false); return s }
        catch { setErr(true); return null }
      }, [])

      useEffect(() => { load() }, [load])
      useEffect(() => {
        if (!state) return
        const c = state.clips[sel]
        if (c && !dirty.current) setDraft({ beats: c.beats, start: c.start })
      }, [state, sel])

      // 每 2.5s 同步一次：agent 在对话里改的，右侧自动跟上
      useEffect(() => {
        const id = setInterval(load, 2500)
        return () => clearInterval(id)
      }, [load])
      useEffect(() => {
        if (!state || state.job?.status !== 'running') return
        const id = setInterval(load, 1500)
        return () => clearInterval(id)
      }, [state, load])

      const apply = async () => {
        const r = await fetch(BASE + '/api/clip', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: sel, beats: Number(draft.beats), start: Number(draft.start) }) })
        dirty.current = false
        if (r.ok) setState(await r.json())
      }
      const doRender = async () => {
        setBusy(true)
        try {
          await fetch(BASE + '/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          for (let i = 0; i < 90; i++) {
            await new Promise((r) => setTimeout(r, 1000))
            const s = await load()
            if (!s) break
            if (s.job?.status === 'done') { const l = s.versions[s.versions.length - 1]; setVer(l && l.id); break }
            if (s.job?.status === 'error') break
          }
        } finally { setBusy(false) }
      }

      if (err) return h('div', { style: { ...S.col, width: '100%' } },
        h('div', { style: S.small }, t.failed), h('button', { style: S.btn, onClick: load }, t.retry))
      if (!state) return h('div', { style: { ...S.col, width: '100%' } }, h('div', { style: S.small }, '…'))

      const clips = state.clips || []
      const cur = clips[sel] || clips[0] || { beats: 8, start: 0, dur: 0, at: 0 }
      const vlist = state.versions || []
      const activeVer = vlist.find((v) => v.id === ver) || vlist[vlist.length - 1]
      const total = state.total || 1
      const beat = 60 / (state.bpm || 120)

      const tlW = 640, tlH = 92, trackY = 22, trackH = 46
      const ticks = []
      for (let i = 0; i * beat <= total; i++) {
        const x = (i * beat / total) * tlW
        ticks.push(h('line', { key: 't' + i, x1: x, y1: 0, x2: x, y2: tlH,
          stroke: i % 4 === 0 ? 'var(--dsw-alias-border-l2)' : 'var(--dsw-alias-border-l1)', strokeWidth: 1 }))
      }
      const blocks = clips.map((c, i) => {
        const x = (c.at / total) * tlW, w = Math.max(3, (c.dur / total) * tlW - 2)
        return h('g', { key: 'c' + i, style: { cursor: 'pointer' }, onClick: () => { dirty.current = false; setSel(i) } },
          h('rect', { x, y: trackY, width: w, height: trackH, rx: 4, fill: 'var(--dsw-alias-bg-layer-2)',
            stroke: i === sel ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-border-l1)', strokeWidth: i === sel ? 2 : 1 }),
          h('text', { x: x + 4, y: trackY + 13, fill: 'var(--dsw-alias-label-primary)', fontSize: 9 },
            (c.role || '') + ' ' + c.beats + '拍'),
          h('text', { x: x + 4, y: trackY + 25, fill: 'var(--dsw-alias-label-secondary)', fontSize: 8 },
            fmt(c.dur) + 's'))
      })

      return h('div', { style: { display: 'contents' } },
        h('div', { style: S.col },
          h('div', { style: S.h2 }, t.shots),
          clips.map((c, i) => h('div', { key: i, style: S.item(i === sel), onClick: () => { dirty.current = false; setSel(i) } },
            h('img', { src: BASE + '/api/thumb?i=' + i, style: S.thumb, alt: '' }),
            h('div', { style: { minWidth: 0 } },
              h('div', { style: { fontSize: 11, fontWeight: 600 } }, (c.role || '') + ' ' + c.beats + '拍'),
              h('div', { style: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)' } }, fmt(c.start) + 's')))),
          h('div', { style: { ...S.h2, marginTop: 10 } }, t.versions),
          vlist.slice().reverse().map((v) => h('div', { key: v.id, style: S.item(activeVer && v.id === activeVer.id), onClick: () => setVer(v.id) },
            h('div', { style: { fontSize: 11, fontWeight: 600 } }, v.id),
            h('div', { style: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)' } }, (v.bytes / 1e6).toFixed(1) + 'MB')))),

        h('div', { style: { ...S.col, display: 'flex', flexDirection: 'column', minHeight: 0 } },
          h('div', { style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 8, padding: 4, marginBottom: 6 } },
            h('svg', { viewBox: '0 0 ' + tlW + ' ' + tlH, style: { width: '100%', height: tlH, display: 'block' } }, ticks.concat(blocks))),
          h('div', { style: { flex: 1, minHeight: 0, background: '#000', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--dsw-alias-border-l1)' } },
            activeVer ? h('video', { key: activeVer.id, controls: true, src: BASE + activeVer.url, poster: BASE + '/api/poster',
              style: { width: '100%', height: '100%', objectFit: 'contain', background: '#000' } })
              : h('div', { style: { ...S.small, padding: 12 } }, t.empty))),

        h('div', { style: S.colLast },
          h('div', { style: S.h2 }, t.decisions),
          h('div', { style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 8, padding: 8, marginBottom: 8 } },
            h('div', { style: S.row }, h('div', { style: { width: 44, ...S.small } }, '#'), h('strong', { style: { fontSize: 12 } }, (sel + 1) + ' / ' + clips.length)),
            h('div', { style: S.row }, h('div', { style: { width: 44, ...S.small } }, t.beats),
              h('select', { style: S.input, value: draft.beats, onChange: (e) => { dirty.current = true; setDraft({ ...draft, beats: Number(e.target.value) }) } },
                [2, 4, 6, 8, 12, 16].map((b) => h('option', { key: b, value: b }, b + ' 拍 · ' + fmt(b * beat) + 's')))),
            h('div', { style: S.row }, h('div', { style: { width: 44, ...S.small } }, t.start),
              h('input', { type: 'number', step: '0.1', style: S.input, value: draft.start,
                onChange: (e) => { dirty.current = true; setDraft({ ...draft, start: Number(e.target.value) }) } })),
            h('button', { style: S.btnPrimary, onClick: apply }, t.apply),
            h('button', { style: { ...S.btnPrimary, width: '100%', marginTop: 6, opacity: busy ? 0.6 : 1 },
              disabled: busy, onClick: doRender }, busy ? t.rendering : t.render)),
          (state.ops || []).map((o, i) => h('div', { key: i, style: { borderLeft: '2px solid var(--dsw-alias-border-l1)', padding: '3px 0 3px 7px', marginBottom: 5 } },
            h('div', { style: { fontSize: 10, fontWeight: 600, color: 'var(--dsw-alias-brand-primary)' } }, o.op),
            h('div', { style: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)' } }, o.evidence || '')))))
    }

    function Decisions({ dec }) {
      const pill = (ok, text) => h('span', { style: { padding: '1px 7px', borderRadius: 10, fontSize: 11,
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid ' + (ok ? 'var(--dsw-alias-state-success-primary)' : 'var(--dsw-alias-state-error-primary)'),
        color: ok ? 'var(--dsw-alias-state-success-primary)' : 'var(--dsw-alias-state-error-primary)' } }, text)
      if (!dec) return h('div', { style: { ...S.col, gridColumn: '1 / -1' } }, h('div', { style: S.small }, '…'))
      const pre = dec.precheck
      const sel = dec.selection
      const batch = dec.batch || []
      return h('div', { style: { ...S.col, gridColumn: '1 / -1', gridRow: '1', borderRight: 'none' } },
        h('div', { style: S.h2 }, '素材准入'),
        h('div', { style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 8, padding: 10, marginBottom: 12 } },
          pre ? h('div', null,
            h('div', { style: { fontSize: 12 } }, 'sport_prob ', h('strong', null, pre.sport_prob), ' ',
              pill(pre.verdict === 'ok', pre.verdict === 'ok' ? '通过' : '拒绝')),
            h('div', { style: S.small }, '抽 ' + pre.frames + ' 帧判语义；低于阈值直接不剪'))
            : h('div', { style: S.small }, '最近一次运行没有准入步骤（单解法或旧记录）')),

        h('div', { style: S.h2 }, '选段'),
        sel ? h('div', { style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 8, padding: 10, marginBottom: 12 } },
          h('div', { style: { fontSize: 12 } }, '选中 ', h('strong', null, sel.segments), ' 刀 · 平均语义分 ',
            h('strong', null, sel.sem != null ? sel.sem : '—')),
          sel.audit ? h('div', { style: { ...S.small, marginTop: 4 } }, '逐刀：' + sel.audit.join(' / ')) : null)
          : h('div', { style: S.small }, '—'),

        h('div', { style: S.h2 }, '批量结果'),
        batch.length ? h('div', null, batch.map((r) => h('div', { key: r.i,
            style: { display: 'flex', gap: 6, alignItems: 'center', padding: '4px 0',
                     borderBottom: '1px solid var(--dsw-alias-border-l1)', fontSize: 11 } },
            h('span', { style: { width: 22, color: 'var(--dsw-alias-label-secondary)' } }, String(r.i).padStart(2, '0')),
            h('span', { style: { width: 70 } }, r.clip),
            pill(r.ok, r.ok ? (r.dur ? r.dur.toFixed(1) + 's' : '通过') : '拒绝'),
            h('span', { style: { ...S.small, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
              r.ok ? '语义 ' + (r.sem != null ? r.sem : '—') : (r.failed || '').replace('ERROR:', '')))))
          : h('div', { style: S.small }, '还没有批量记录'),

        h('div', { style: { ...S.h2, marginTop: 12 } }, '执行步骤'),
        (dec.steps || []).map((st, i) => h('div', { key: i, style: { display: 'flex', gap: 8, fontSize: 11, padding: '2px 0' } },
          h('span', { style: { width: 120, color: 'var(--dsw-alias-label-secondary)' } }, st.op),
          h('span', { style: { width: 44, color: 'var(--dsw-alias-label-secondary)' } }, (st.seconds || 0) + 's'),
          h('span', { style: { flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
            JSON.stringify(st.result || {}).slice(0, 90)))))
    }

    function Drawer({ ctx }) {
      const isOpen = useOpen()
      const [tab, setTab] = useState('timeline')
      const [dec, setDec] = useState(null)
      useEffect(() => {
        let alive = true
        const pull = async () => {
          try { const r = await fetch(BASE + '/api/decisions'); if (r.ok && alive) setDec(await r.json()) } catch {}
        }
        pull()
        const id = setInterval(pull, 5000)
        return () => { alive = false; clearInterval(id) }
      }, [])
      useEffect(() => {
        if (!isOpen) return
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [isOpen])
      if (!isOpen) return null
      const t = T['zh']
      return h('div', { style: S.drawer },
        h('div', { style: S.head },
          h('strong', { style: { fontSize: 12 } }, 'vcut 剪辑台'),
          h('span', { style: S.small }, '改一刀 → 左边说一句 → 右边看得见'),
          h('div', { style: { display: 'flex', gap: 4, marginLeft: 'auto' } },
            [['timeline', '时间线'], ['decisions', '决策']].map(([k, label]) => h('button', {
              key: k, onClick: () => setTab(k),
              style: { ...S.btn, padding: '3px 10px',
                background: tab === k ? 'var(--dsw-alias-bg-layer-2)' : 'transparent',
                borderColor: tab === k ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-border-l1)' } }, label)),
            ),
          h('button', { style: S.btn, marginLeft: 8, onClick: () => setOpen(false) }, t.close)),
        h('div', { style: S.body }, tab === 'decisions' ? h(Decisions, { dec }) : h(PanelBody, { ctx })))
    }

    function FooterAction({ wide }) {
      return h('button', {
        onClick: toggle,
        title: 'vcut 剪辑台',
        style: { display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 8px', borderRadius: 6,
          border: 'none', background: 'transparent', color: 'var(--dsw-alias-label-secondary)', cursor: 'pointer', fontSize: 12 },
      },
        h('svg', { viewBox: '0 0 64 64', width: 18, height: 18, 'aria-hidden': true, style: { display: 'block' } },
          h('rect', { x: 10, y: 14, width: 20, height: 36, rx: 5, fill: 'currentColor' }),
          h('rect', { x: 34, y: 22, width: 9, height: 28, rx: 3, fill: 'currentColor', opacity: 0.7 }),
          h('rect', { x: 46, y: 30, width: 6, height: 20, rx: 2, fill: 'currentColor', opacity: 0.45 })),
        wide ? h('span', null, 'vcut') : null)
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register(
          { name: 'sidebar.footer.action', id: 'vcut', order: 20, label: 'vcut' },
          (props) => h(FooterAction, { ...props })))
        ctx.slots.inject('shell.overlay', () => ctx.slots.register(
          { name: 'shell.overlay', id: 'vcut', order: 5 },
          (props) => h(Drawer, { ...props, ctx })))
      },
    }
  },
})
