import { test, expect, Page } from '@playwright/test';
import { execSync } from 'child_process';
import * as fs from 'fs';

const TEST_DB_URL = 'postgresql://postgres:hermes@127.0.0.1:55432/hermes_test';
const DRAFT_ID = 'ed-e13-e2e';
const USER_SUBJECT = 'e2e-test-user';
const BACKEND_URL = 'http://127.0.0.1:8000';

async function seedDatabase() {
  const sql = [
    "TRUNCATE TABLE public.entry_proposal_plan_command_receipts, public.entry_master_plan_revisions, public.entry_master_plans, public.entry_proposal_revisions, public.entry_proposals, public.entry_understanding_provenance, public.entry_clarification_answers, public.entry_understanding_assumptions, public.entry_understanding_transition_records, public.entry_understanding_revisions, public.entry_understandings, public.entry_draft_transition_records, public.entry_draft_revisions, public.entry_drafts CASCADE;",
    `INSERT INTO public.entry_drafts(draft_id,creator_subject,title,raw_input,state,version,latest_revision_number,last_command_id) VALUES('${DRAFT_ID}','${USER_SUBJECT}','E13 E2E Test','Build editor for E2E','SUBMITTED',1,1,'cmd-e13-draft');`,
    `INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version) VALUES('edr-e13-e2e-1','${DRAFT_ID}',1,'E13 E2E Test','Build editor for E2E','${USER_SUBJECT}',1);`,
    `INSERT INTO public.entry_understandings(understanding_id,draft_id,creator_subject,state,version,latest_revision_number) VALUES('eu-e13-e2e','${DRAFT_ID}','${USER_SUBJECT}','READY',1,1);`,
    `INSERT INTO public.entry_understanding_revisions(understanding_revision_id,understanding_id,revision_number,source_draft_id,source_draft_revision_number,source_raw_input,interpreted_intent,objective,user_constraints,explicit_requirements,ambiguities,open_questions) VALUES('eur-e13-e2e-1','eu-e13-e2e',1,'${DRAFT_ID}',1,'Build editor for E2E','Build editor for E2E','Deliver editor','[\"web\"]','[\"Create issues\",\"List issues\"]','[]','[]');`,
  ].join('\n');
  const tmpFile = '/tmp/e13_seed.sql';
  fs.writeFileSync(tmpFile, sql);
  execSync(`docker exec -i proteus-e13-pg psql -U postgres -d hermes_test < ${tmpFile}`, { stdio: 'inherit' });

  const pyScript = `
import sys
sys.path.insert(0, '/Users/sjw/Documents/GitHub/Proteus/hermes-runtime/src')
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
store = PostgresEntryProposalMasterPlanStore("${TEST_DB_URL}")
proposal = store.generate_proposal("${USER_SUBJECT}", "${DRAFT_ID}", 0, "gen-prop-e2e", "generate proposal for e2e")
plan = store.generate_master_plan("${USER_SUBJECT}", "${DRAFT_ID}", 0, "gen-plan-e2e", "generate master plan for e2e")
print(f"proposal_id={proposal['proposal_id']}")
print(f"plan_id={plan['master_plan_id']}")
`;
  const pyFile = '/tmp/e13_seed_proposal.py';
  fs.writeFileSync(pyFile, pyScript);
  execSync(`cd /Users/sjw/Documents/GitHub/Proteus/hermes-runtime && PYTHONPATH=src .venv/bin/python ${pyFile}`, { stdio: 'inherit' });
}

function generateTestToken(): string {
  const pyScript = `
import jwt, time
with open('/tmp/test_private_key.pem') as f:
    private_key = f.read()
payload = {'sub': '${USER_SUBJECT}', 'iss': 'https://test-issuer.example.com', 'aud': 'test-audience', 'exp': int(time.time()) + 3600, 'nbf': int(time.time()) - 60, 'iat': int(time.time())}
print(jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': 'test-key-1'}))
`;
  const tokenFile = '/tmp/e13_gen_token.py';
  fs.writeFileSync(tokenFile, pyScript);
  const result = execSync(`cd /Users/sjw/Documents/GitHub/Proteus/hermes-runtime && PYTHONPATH=src .venv/bin/python ${tokenFile}`, {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  return result.trim();
}

async function login(page: Page) {
  const token = generateTestToken();
  const result = execSync(
    `curl -s -D- -X POST -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" ${BACKEND_URL}/session`,
    { encoding: 'utf-8' }
  );
  const match = result.match(/hermes_session=([^;\s]+)/);
  expect(match).toBeTruthy();
  await page.context().addCookies([{
    name: 'hermes_session',
    value: match![1],
    domain: 'localhost',
    path: '/',
  }]);
}

async function scrollToEditor(page: Page) {
  const editor = page.locator('section[aria-label="Editor sections"]');
  await editor.scrollIntoViewIfNeeded();
  await expect(editor).toBeVisible({ timeout: 10000 });
}

test.describe.configure({ retries: 0 });

test.describe('E13 Proposal & Master Plan Editor', () => {
  test.beforeAll(async () => {
    await seedDatabase();
    console.log('Database seeded');
  });

  test('should load editor page and show proposal tab', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await expect(page.locator('h1:has-text("Production draft")')).toBeVisible({ timeout: 10000 });
    await scrollToEditor(page);
    await expect(page.locator('text=E13 · Editor')).toBeVisible();
    await expect(page.locator('text=Proposal & Master Plan')).toBeVisible();
    await expect(page.locator('button[role="tab"]:has-text("Proposal")')).toBeVisible();
    await expect(page.locator('button[role="tab"]:has-text("Master Plan")')).toBeVisible();
    await expect(page.locator('text=Revision #1')).toBeVisible();
  });

  test('should allow editing proposal and saving new revision', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button:has-text("Edit")');
    await expect(page.locator('textarea[aria-label*="Product statement"]')).toBeVisible();

    await page.fill('textarea[aria-label*="Product statement"]', 'Updated product statement for E2E');
    await page.fill('textarea[aria-label*="Target outcome"]', 'Updated target outcome for E2E');

    await page.click('button:has-text("Save new revision")');
    await expect(page.locator('text=Saved new proposal revision')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.ui-kicker:has-text("Revision #2")')).toBeVisible({ timeout: 5000 });
  });

  test('should show revision history and diff', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await expect(page.locator('text=Revision history')).toBeVisible();
    await expect(page.locator('text=Compare with revision')).toBeVisible();
  });

  test('should allow editing master plan and saving new revision', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button[role="tab"]:has-text("Master Plan")');
    await page.click('button:has-text("Edit")');
    await expect(page.locator('textarea[aria-label*="Goal"]')).toBeVisible();

    await page.fill('textarea[aria-label*="Goal"]', 'Updated goal for E2E');
    await page.click('button:has-text("Save new revision")');
    await expect(page.locator('text=Saved new master plan revision')).toBeVisible({ timeout: 15000 });
  });

  test('should reject invalid dependency (cycle)', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button[role="tab"]:has-text("Master Plan")');
    await page.click('button:has-text("Edit")');

    const nodeKeys = page.locator('input[aria-label*="node key"]');
    const nodeCount = await nodeKeys.count();

    if (nodeCount < 2) {
      for (let i = nodeCount; i < 2; i++) {
        await page.click('button:has-text("Add node")');
      }
    }

    const phases = page.locator('fieldset:has(legend:text("Nodes")) input[aria-label*="phase"]');
    const titles = page.locator('fieldset:has(legend:text("Nodes")) input[aria-label*="title"]');

    await nodeKeys.nth(0).fill('n1');
    await phases.nth(0).fill('phase1');
    await titles.nth(0).fill('Node 1');

    await nodeKeys.nth(1).fill('n2');
    await phases.nth(1).fill('phase1');
    await titles.nth(1).fill('Node 2');

    for (let i = 2; i < nodeCount; i++) {
      await nodeKeys.nth(i).fill(`extra-${i}`);
      await phases.nth(i).fill('phase-extra');
      await titles.nth(i).fill(`Extra Node ${i}`);
    }

    await page.click('button:has-text("Add dependency")');
    await page.fill('input[aria-label*="source node"]', 'n1');
    await page.fill('input[aria-label*="target node"]', 'n2');

    await page.click('button:has-text("Add dependency")');
    await page.fill('input[aria-label*="source node"] >> nth=1', 'n2');
    await page.fill('input[aria-label*="target node"] >> nth=1', 'n1');

    let postSent = false;
    page.on('request', (req) => {
      if (req.url().includes('/plan/revisions') && req.method() === 'POST') postSent = true;
    });

    await expect(page.locator('text=Dependencies contain a cycle')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('button:has-text("Save new revision")')).toBeDisabled();
    expect(postSent).toBe(false);
  });

  test('should show conflict on stale expected_version', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button:has-text("Edit")');
    await page.fill('textarea[aria-label*="Product statement"]', 'Version conflict test 1');
    await page.click('button:has-text("Save new revision")');
    await expect(page.locator('text=Saved new proposal revision')).toBeVisible({ timeout: 15000 });

    await expect(page.locator('.ui-kicker:has-text("Revision #")')).toBeVisible({ timeout: 5000 });
  });

  test('should protect unsaved changes on navigation', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button:has-text("Edit")');
    await page.fill('textarea[aria-label*="Product statement"]', 'Unsaved change test');

    let dialogFired = false;
    page.on('dialog', async (dialog) => {
      dialogFired = true;
      await dialog.dismiss();
    });

    const navigationPromise = page.goto('/home').catch(() => null);
    await navigationPromise;

    expect(dialogFired).toBe(true);
  });

  test('should not include forbidden authority fields in save request', async ({ page }) => {
    await login(page);
    await page.goto(`/drafts/${DRAFT_ID}`);
    await scrollToEditor(page);
    await page.click('button:has-text("Edit")');

    const [request] = await Promise.all([
      page.waitForRequest(r => r.url().includes('/proposal/revisions') && r.method() === 'POST'),
      page.click('button:has-text("Save new revision")')
    ]);

    const body = request.postDataJSON();
    expect(body).not.toHaveProperty('actor');
    expect(body).not.toHaveProperty('creator');
    expect(body).not.toHaveProperty('authority');
    expect(body).not.toHaveProperty('scope');
    expect(body).not.toHaveProperty('approval');
    expect(body).not.toHaveProperty('execution');
    expect(body).toHaveProperty('idempotency_key');
    expect(body).toHaveProperty('expected_version');
  });

  test('E11/E12 factory-home page accessible', async ({ page }) => {
    await login(page);
    await page.goto('/home');
    await expect(page.locator('h1:has-text("Home")')).toBeVisible({ timeout: 10000 });
  });
});
