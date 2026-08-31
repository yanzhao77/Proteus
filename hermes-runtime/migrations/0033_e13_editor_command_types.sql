-- E13 Proposal / Master Plan Editor: extend the E3 command-receipt command_type
-- domain to include the explicit save-revision semantic commands. The E3
-- revision tables, content columns and immutable triggers already express E13;
-- only the command-receipt CHECK constraint rejected the new command types.
-- No migration 0001-0032, role, grant, ACL, function owner, security mode or
-- P0-P6 authority is changed.

ALTER TABLE public.entry_proposal_plan_command_receipts
  DROP CONSTRAINT IF EXISTS entry_proposal_plan_command_receipts_command_type_check;

ALTER TABLE public.entry_proposal_plan_command_receipts
  ADD CONSTRAINT entry_proposal_plan_command_receipts_command_type_check
  CHECK (command_type IN (
    'GENERATE_PROPOSAL',
    'GENERATE_MASTER_PLAN',
    'SAVE_PROPOSAL_REVISION',
    'SAVE_MASTER_PLAN_REVISION'
  ));
