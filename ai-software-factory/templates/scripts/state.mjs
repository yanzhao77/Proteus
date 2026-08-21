#!/usr/bin/env node
// 读写 project.json（权威状态），原子写入 + 最小校验
// 用法: node state.mjs read <project.json> | node state.mjs write <project.json> <json-patch-file>
import fs from 'node:fs'
import path from 'node:path'

const STATUSES = [
  'PROJECT_CREATED', 'REQUIREMENT_ANALYSIS', 'REQUIREMENT_CLARIFICATION',
  'REQUIREMENT_APPROVED', 'PRODUCT_DESIGN', 'UX_DESIGN', 'ARCHITECTURE_DESIGN',
  'TECH_DESIGN_APPROVED', 'IMPLEMENTATION_PLANNING', 'IMPLEMENTATION',
  'INTEGRATION', 'QA', 'SECURITY_AUDIT', 'ACCEPTANCE', 'RELEASE', 'DELIVERED',
]
const RUN = ['RUNNING', 'PAUSED', 'FAILED', 'RETRYING', 'BLOCKED', 'WAITING_APPROVAL', 'COMPLETED', 'CANCELLED']

const [cmd, file, patchFile] = process.argv.slice(2)
if (!file) { console.error('usage: state.mjs read|write <project.json> [patch.json]'); process.exit(2) }

if (cmd === 'read') {
  console.log(fs.readFileSync(file, 'utf8'))
  process.exit(0)
}
if (cmd === 'write') {
  if (!patchFile) { console.error('write needs a patch file'); process.exit(2) }
  const state = JSON.parse(fs.readFileSync(file, 'utf8'))
  const patch = JSON.parse(fs.readFileSync(patchFile, 'utf8'))
  if (patch.status && !STATUSES.includes(patch.status)) { console.error('非法 status: ' + patch.status); process.exit(1) }
  if (patch.runStatus && !RUN.includes(patch.runStatus)) { console.error('非法 runStatus: ' + patch.runStatus); process.exit(1) }
  const next = { ...state, ...patch, revision: (state.revision ?? 0) + 1 }
  if (patch.event) next.events = [...(state.events ?? []), patch.event]
  const tmp = file + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2) + '\n')
  fs.renameSync(tmp, file)
  console.log(JSON.stringify({ ok: true, revision: next.revision, status: next.status, runStatus: next.runStatus }))
  process.exit(0)
}
console.error('unknown command: ' + cmd)
process.exit(2)
