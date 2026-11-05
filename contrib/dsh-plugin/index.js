/**
 * cutnow 剪辑工作台 — Host 侧。
 * 三个工具直连本地引擎（edit-core/workbench/server.py），与面板共用同一份 EDL。
 * 工具注册失败不拖垮插件：错误写到 edit-core/out/plugin-errors.log，面板照常工作。
 */
import { spawn } from 'node:child_process'
import { appendFileSync, mkdirSync } from 'node:fs'

export const inject = ['tools']

// output.schema 必须是标准 JSON Schema：required 是对象级的数组，不能写在属性里
const obj = (props, required = []) => ({ type: 'object', additionalProperties: false, properties: props, required })

export function apply(ctx, config) {
  const root = config?.root ?? '/Users/jiaochen/Downloads/vibecoding/edit-core'
  const port = config?.port ?? 8799
  const base = `http://127.0.0.1:${port}`

  const log = (msg) => {
    try {
      mkdirSync(`${root}/out`, { recursive: true })
      appendFileSync(`${root}/out/plugin-errors.log`, `[${new Date().toISOString()}] ${msg}\n`)
    } catch {}
  }

  let child = null
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  async function reachable() {
    try { const r = await fetch(`${base}/api/state`, { signal: AbortSignal.timeout(1200) }); return r.ok } catch { return false }
  }

  async function ensure() {
    if (await reachable()) return
    if (!child) {
      child = spawn('python3', [`${root}/workbench/server.py`, String(port)], { cwd: root, stdio: 'ignore' })
      ctx.effect(() => () => { try { child?.kill() } catch {} child = null })
    }
    for (let i = 0; i < 40; i++) { await sleep(250); if (await reachable()) return }
    throw new Error('本地剪辑引擎未启动')
  }

  const text = (v) => [{ type: 'text', text: JSON.stringify(v, null, 2) }]

  const clipSchema = obj({
    index: { type: 'number' },
    start: { type: 'number' },
    dur: { type: 'number' },
    beats: { type: 'number' },
    role: { type: 'string' },
  }, ['index', 'start', 'dur', 'beats'])
  const clipsSchema = { type: 'array', items: clipSchema }

  const defs = [
    {
      name: 'vcut_state',
      description: '读取剪辑工作台状态：每个镜头的入点/拍数/时长、总长、已渲染版本、渲染任务。改片前先调用。',
      parameters: {},
      output: {
        schema: obj({
          title: { type: 'string' }, bpm: { type: 'number' },
          total: { type: 'number' }, clips: clipsSchema,
          versions: { type: 'array', items: { type: 'string' } },
          job: { type: 'string' },
        }, ['bpm', 'total', 'clips']),
        render: (_a, v) => text(v),
      },
      execute: async () => {
        await ensure()
        const s = await (await fetch(`${base}/api/state`)).json()
        return {
          title: s.title, bpm: s.bpm, total: s.total,
          clips: s.clips.map((c) => ({ index: c.index, start: c.start, dur: c.dur, beats: c.beats, role: c.role })),
          versions: (s.versions || []).map((v) => v.id),
          job: s.job?.status,
        }
      },
    },
    {
      name: 'vcut_edit_clip',
      description: '改一个镜头的拍数或源起点，并立即按节拍重排整条时间线（切点保持吸附在拍上）。只改 EDL，不出片；要成片再调 vcut_render。',
      parameters: {
        index: { type: 'number', required: true, description: '镜头序号，从 0 开始' },
        beats: { type: 'number', description: '新的拍数，如 4/8/12' },
        start: { type: 'number', description: '原片入点秒数' },
      },
      output: {
        schema: obj({ total: { type: 'number' }, clips: clipsSchema }, ['total', 'clips']),
        render: (_a, v) => text(v),
      },
      execute: async (args) => {
        await ensure()
        const r = await fetch(`${base}/api/clip`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: args.index, beats: args.beats, start: args.start }),
        })
        if (!r.ok) throw new Error(`改镜头失败 ${r.status}`)
        const s = await r.json()
        return { total: s.total, clips: s.clips.map((c) => ({ index: c.index, start: c.start, dur: c.dur, beats: c.beats, role: c.role })) }
      },
    },
    {
      name: 'vcut_render',
      description: '把当前 EDL 渲染成新版本（约 10 秒），阻塞到完成为止，返回版本 id 与文件路径。',
      parameters: {},
      output: {
        schema: obj({ version: { type: 'string' }, file: { type: 'string' }, bytes: { type: 'number' } }, ['version', 'file']),
        render: (_a, v) => text(v),
      },
      execute: async () => {
        await ensure()
        const before = await (await fetch(`${base}/api/state`)).json()
        const n0 = before.versions.length
        const r = await fetch(`${base}/api/render`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        if (!r.ok) throw new Error(`渲染请求失败 ${r.status}`)
        for (let i = 0; i < 120; i++) {
          await sleep(1000)
          const s = await (await fetch(`${base}/api/state`)).json()
          if (s.job?.status === 'error') throw new Error(`渲染失败：${s.job.log}`)
          if (s.job?.status === 'done' && s.versions.length > n0) {
            const v = s.versions[s.versions.length - 1]
            return { version: v.id, file: v.file, bytes: v.bytes }
          }
        }
        throw new Error('渲染超时')
      },
    },
  ]

  for (const def of defs) {
    try {
      ctx.tools.register(def)
    } catch (e) {
      log(`register ${def.name} failed: ${e && e.message}`)
    }
  }
  log('apply done')

  // 插件激活时就把引擎拉起来：否则应用重启后，面板会一直显示"连不上本地引擎"
  ensure().then(() => log('engine ready')).catch((e) => log(`engine autostart failed: ${e && e.message}`))
}
