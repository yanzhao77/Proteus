#!/usr/bin/env node
// 需求变更影响分析：读 tasks/*.yaml 的 dependsOn 图，计算受影响任务闭包
// 用法: node impact.js <project-dir> <seed...>   （seed 可以是任务 id 或路径片段）
import fs from 'node:fs'
import path from 'node:path'

const [, , proj, ...seeds] = process.argv
if (!proj || !seeds.length) { console.error('usage: impact.js <project-dir> <seed-task-or-path>...'); process.exit(2) }

function parseYamlSimple(text) {
  // 极简 yaml 子集：id:/title:/dependsOn: [..] 行
  const out = {}
  for (const line of text.split('\n')) {
    const m = line.match(/^(\w+):\s*(.*)$/)
    if (!m) continue
    const val = m[2].trim()
    if (val.startsWith('[')) out[m[1]] = val.replace(/[\[\]]/g, '').split(',').map(s => s.trim()).filter(Boolean)
    else out[m[1]] = val.replace(/^["']|["']$/g, '')
  }
  return out
}

const tasks = new Map()
for (const f of fs.readdirSync(path.join(proj, 'tasks')).filter(f => f.endsWith('.yaml'))) {
  const t = parseYamlSimple(fs.readFileSync(path.join(proj, 'tasks', f), 'utf8'))
  tasks.set(t.id, t)
}

// 依赖闭包（seed → 所有依赖它的下游任务）
const affected = new Set()
const visited = new Set()
function markDownstream(id) {
  if (visited.has(id)) return
  visited.add(id)
  for (const [tid, t] of tasks) {
    if ((t.dependsOn || []).includes(id)) { affected.add(tid); markDownstream(tid) }
  }
}
for (const seed of seeds) {
  // seed 是任务 id 或匹配 outputs 的路径片段
  let matched = [...tasks.keys()].filter(id => id === seed || (tasks.get(id).outputs || '').includes(seed))
  if (!matched.length) matched = [...tasks.keys()].filter(id => (tasks.get(id).title || '').includes(seed))
  for (const id of matched) { affected.add(id); markDownstream(id) }
}

const result = [...affected].map(id => ({ id, title: tasks.get(id).title, dependsOn: tasks.get(id).dependsOn || [], status: tasks.get(id).status }))
console.log(JSON.stringify({ seeds, affected: result, count: result.length }, null, 2))
