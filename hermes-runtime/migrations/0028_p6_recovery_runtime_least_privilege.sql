-- P6 Recovery least-privilege repair.
-- 0024's owner grant remains required for the SECURITY DEFINER re-entry command;
-- this forward migration removes only the runtime's direct authority path.
BEGIN;

REVOKE UPDATE ON TABLE public.tasks FROM hermes_recovery_runtime;

COMMIT;
