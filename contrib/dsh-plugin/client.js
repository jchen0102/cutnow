/**
 * cutnow 剪辑台（主区页面）：和会话平级的一个页面，左栏入口切换。
 * 数据来自本地引擎，与 agent 工具同一份 EDL。
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
      page: { height: '100%', display: 'flex', flexDirection: 'column',
        background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)' },
      pageBody: { flex: 1, minHeight: 0, display: 'grid',
        gridTemplateColumns: '260px minmax(0,1fr) 330px', overflow: 'hidden' },
      board: { borderTop: '1px solid var(--dsw-alias-border-l1)', padding: '8px 16px', maxHeight: 150, overflow: 'auto' },
      boardRow: { display: 'grid', gridTemplateColumns: '90px 1fr 110px 120px 150px', gap: 8, alignItems: 'center',
        padding: '5px 0', borderBottom: '1px solid var(--dsw-alias-border-l1)', fontSize: 11 },
      emptyWrap: { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 },
      drop: { width: 'min(760px, 100%)', border: '2px dashed var(--dsw-alias-border-l2)', borderRadius: 14,
        padding: '40px 28px', textAlign: 'center', background: 'var(--dsw-alias-bg-layer-1)' },
      big: { fontSize: 20, fontWeight: 600, marginBottom: 8 },
      cmd: { display: 'flex', gap: 6, marginBottom: 8 },
      head: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
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
      const [cmd, setCmd] = useState('')
      const [cmdMsg, setCmdMsg] = useState('')
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
      const runCmd = async () => {
        const text = cmd.trim()
        if (!text) return
        try {
          const r = await fetch(BASE + '/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, index: sel }) })
          const j = await r.json()
          setCmdMsg(j.message || '')
          if (j.ok) { setCmd(''); dirty.current = false; await load() }
        } catch (e) { setCmdMsg(String(e.message || e)) }
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
          h('div', { style: S.h2 }, '说一句'),
          h('div', { style: S.cmd },
            h('input', { style: S.input, placeholder: '全长 15 秒 / 多 2 拍 / 重渲', value: cmd,
              onChange: (e) => setCmd(e.target.value),
              onKeyDown: (e) => { if (e.key === 'Enter') runCmd() } }),
            h('button', { style: S.btn, onClick: runCmd }, '执行')),
          cmdMsg ? h('div', { style: { ...S.small, marginBottom: 8 } }, cmdMsg) : null,
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

    async function uploadFile(file) {
      const r = await fetch(BASE + '/api/upload?name=' + encodeURIComponent(file.name), { method: 'POST', body: file })
      if (!r.ok) throw new Error('上传失败')
      return (await r.json()).path
    }

    function Empty({ snap, onDone }) {
      const [busy, setBusy] = useState(false)
      const [msg, setMsg] = useState('')
      const [over, setOver] = useState(false)
      const videoPick = useRef(null)
      const sbPick = useRef(null)

      const wait = async () => {
        for (let i = 0; i < 180; i++) {
          await new Promise((r) => setTimeout(r, 1500))
          const r = await fetch(BASE + '/api/state')
          const s = await r.json()
          const job = s.job || {}
          if (job.log) setMsg(job.status === 'running' ? job.log : (job.log || '').slice(0, 200))
          if (!s.empty && job.status === 'done') { onDone && onDone(); return }
          if (job.status === 'error') { setMsg(String(job.log || '').slice(0, 300)); return }
        }
      }

      const run = async (fn) => {
        setBusy(true); setMsg('')
        try { await fn(); await wait() } catch (e) { setMsg(String(e.message || e)) } finally { setBusy(false) }
      }

      const handleFiles = (files) => {
        const list = Array.from(files || [])
        if (!list.length) return
        run(async () => {
          const paths = []
          for (const f of list) paths.push(await uploadFile(f))
          const boards = paths.filter((p) => /\.json$/i.test(p))
          const videos = paths.filter((p) => !/\.json$/i.test(p))
          if (boards.length) {
            const r = await fetch(BASE + '/api/storyboard', { method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: boards[0], sources: videos.length ? videos : [] }) })
            if (!r.ok) throw new Error((await r.json()).error || '分镜导入失败')
          } else if (videos.length) {
            const r = await fetch(BASE + '/api/open', { method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: videos[0], solution: 'sports' }) })
            if (!r.ok) throw new Error((await r.json()).error || '分析失败')
          }
        })
      }

      const demo = () => run(async () => {
        const r = await fetch(BASE + '/api/demo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        if (!r.ok) throw new Error((await r.json()).error || '演示失败')
      })

      return h('div', { style: S.page },
        h('div', { style: S.head }, h('strong', { style: { fontSize: 15 } }, 'cutnow 剪辑台'),
          h('span', { style: S.small }, '素材 → 选段 → 出片 → 质检 → 审批')),
        h('div', { style: S.emptyWrap },
          h('div', {
            style: { ...S.drop, borderColor: over ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-border-l2)' },
            onDragOver: (e) => { e.preventDefault(); setOver(true) },
            onDragLeave: () => setOver(false),
            onDrop: (e) => { e.preventDefault(); setOver(false); handleFiles(e.dataTransfer.files) },
          },
            h('div', { style: S.big }, '把素材拖进来'),
            h('div', { style: { ...S.small, marginBottom: 18 } },
              '视频会先做素材准入再出片；分镜 .json 会按镜头直接剪。也支持 mp4 / mov / webm。'),
            h('div', { style: { display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' } },
              h('button', { style: S.btnPrimary, disabled: busy, onClick: demo }, busy ? '处理中…' : '没素材？看一条演示片'),
              h('button', { style: S.btn, disabled: busy, onClick: () => videoPick.current && videoPick.current.click() }, '选素材'),
              h('button', { style: S.btn, disabled: busy, onClick: () => sbPick.current && sbPick.current.click() }, '导入分镜')),
            h('input', { ref: videoPick, type: 'file', accept: 'video/*', multiple: true, style: { display: 'none' },
              onChange: (e) => handleFiles(e.target.files) }),
            h('input', { ref: sbPick, type: 'file', accept: '.json,video/*', multiple: true, style: { display: 'none' },
              onChange: (e) => handleFiles(e.target.files) }),
            msg ? h('div', { style: { ...S.small, marginTop: 16, maxWidth: 520, marginLeft: 'auto', marginRight: 'auto' } }, msg) : null))
      )
    }

    function statusPill(item) {
      const map = { delivered: ['已交付', 'var(--dsw-alias-state-success-primary)'],
                    approved: ['已审批', 'var(--dsw-alias-brand-primary)'],
                    unapproved: ['待审批', 'var(--dsw-alias-label-secondary)'] }
      const [text, color] = map[item.status] || map.unapproved
      return h('span', { style: { color, fontSize: 11 } }, '● ' + text + (item.approver ? ' · ' + item.approver : ''))
    }

    function Board({ rec, reload }) {
      const items = (rec && rec.items) || []
      const act = async (path, body) => {
        const r = await fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        if (!r.ok) { const j = await r.json().catch(() => ({})); window.alert(j.error || '操作失败') }
        reload && reload()
      }
      return h('div', { style: S.board },
        h('div', { style: { ...S.h2, margin: '0 0 4px' } }, '交付看板'),
        items.length ? items.slice(0, 8).map((it) => h('div', { key: it.run_id, style: S.boardRow },
          h('span', { style: { fontSize: 11, fontWeight: 600 } }, it.label),
          h('span', { style: { color: 'var(--dsw-alias-label-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
            (it.at || '') + ' · ' + (it.bytes / 1e6).toFixed(1) + 'MB · ' + it.sha),
          statusPill(it),
          h('button', { style: { ...S.btn, padding: '2px 8px' }, onClick: () => act('/api/approve', { run_id: it.run_id }) }, '审批'),
          h('button', { style: { ...S.btn, padding: '2px 8px' }, onClick: () => act('/api/deliver', { run_id: it.run_id }) }, '交付')))
          : h('div', { style: S.small }, '还没有渲染记录'))
    }

    function Page({ ctx }) {
      const [tab, setTab] = useState('timeline')
      const [dec, setDec] = useState(null)
      const [snap, setSnap] = useState(null)
      const [rec, setRec] = useState(null)
      const [err, setErr] = useState(false)

      const load = useCallback(async () => {
        try {
          const r = await fetch(BASE + '/api/state'); const s = await r.json()
          setSnap(s); setErr(false); return s
        } catch { setErr(true); return null }
      }, [])
      const loadRec = useCallback(async () => {
        try { const r = await fetch(BASE + '/api/records'); if (r.ok) setRec(await r.json()) } catch {}
      }, [])

      useEffect(() => { load(); loadRec(); const id = setInterval(() => { load(); loadRec() }, 2500); return () => clearInterval(id) }, [load, loadRec])
      useEffect(() => {
        let alive = true
        const pull = async () => { try { const r = await fetch(BASE + '/api/decisions'); if (r.ok && alive) setDec(await r.json()) } catch {} }
        pull(); const id = setInterval(pull, 5000); return () => { alive = false; clearInterval(id) }
      }, [])

      if (err) return h('div', { style: S.page },
        h('div', { style: S.emptyWrap }, h('div', { style: S.drop },
          h('div', { style: S.big }, '连不上本地引擎'),
          h('div', { style: S.small }, '引擎会在插件激活时自动拉起；等 2 秒点重试。'),
          h('div', { style: { marginTop: 14 } }, h('button', { style: S.btnPrimary, onClick: load }, '重试')))))
      if (!snap) return h('div', { style: S.page }, h('div', { style: S.emptyWrap }, h('div', { style: S.small }, '…')))
      if (snap.empty) return h(Empty, { snap, onDone: load })

      return h('div', { style: S.page },
        h('div', { style: S.head },
          h('strong', { style: { fontSize: 15 } }, 'cutnow 剪辑台'),
          h('span', { style: S.small }, (snap.title || '') + ' · ' + (snap.total ? snap.total.toFixed(1) + 's' : '')),
          h('div', { style: { display: 'flex', gap: 4, marginLeft: 'auto' } },
            [['timeline', '时间线'], ['decisions', '决策']].map(([k, label]) => h('button', {
              key: k, onClick: () => setTab(k),
              style: { ...S.btn, padding: '4px 12px',
                background: tab === k ? 'var(--dsw-alias-bg-layer-2)' : 'transparent',
                borderColor: tab === k ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-border-l1)' } }, label))),
        ),
        h('div', { style: S.pageBody }, tab === 'decisions' ? h(Decisions, { dec }) : h(PanelBody, { ctx })),
        h(Board, { rec, reload: loadRec }))
    }

    function DeskIcon({ size = 18 }) {
      return h('svg', { viewBox: '0 0 64 64', width: size, height: size, 'aria-hidden': true, style: { display: 'block' } },
        h('rect', { x: 10, y: 14, width: 20, height: 36, rx: 5, fill: 'currentColor' }),
        h('rect', { x: 34, y: 22, width: 9, height: 28, rx: 3, fill: 'currentColor', opacity: 0.7 }),
        h('rect', { x: 46, y: 30, width: 6, height: 20, rx: 2, fill: 'currentColor', opacity: 0.45 }))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        // 主区页面：与会话平级，不是浮层
        ctx.slots.inject('main', () => ctx.slots.register(
          { name: 'main', key: 'cutnow' },
          (props) => h(Page, { ...props, ctx })))
        // 左栏入口：点了就切到 main/cutnow
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register(
          { name: 'sidebar.panellist', id: 'cutnow', order: 6, label: '剪辑台' },
          (props) => h(DeskIcon, { ...props })))
      },
    }
  },
})
