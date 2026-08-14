import unittest

from hermes_runtime.domain.recovery import (
    ExecutionFailure,
    FailureType,
    RecoveryAction,
    RecoveryLevel,
    RecoveryPolicy,
    Severity,
    choose_recovery_action,
    classify_execution_failure,
)


class RecoveryDomainTests(unittest.TestCase):
    def failure(self, classification):
        return ExecutionFailure(
            "result-1",
            "FAILED_PERMANENT",
            classification,
            "test-adapter",
            "task-1",
        )

    def test_test_failure_maps_to_repair_ladder(self):
        feedback = classify_execution_failure(self.failure("test_assertion_failure"))
        self.assertEqual(FailureType.TEST_ASSERTION_FAILURE, feedback.failure_type)
        self.assertEqual(Severity.HIGH, feedback.severity)
        self.assertEqual(RecoveryLevel.L1_REPAIR, feedback.recovery_level)
        self.assertEqual(RecoveryAction.REPAIR, feedback.recommended_actions[0])
        action, level, reason = choose_recovery_action(
            feedback, 0, RecoveryPolicy(max_attempts=2)
        )
        self.assertEqual((RecoveryAction.REPAIR, RecoveryLevel.L1_REPAIR,
                          "RECOVERY_ATTEMPT_PLANNED"), (action, level, reason))

    def test_transient_failure_prefers_bounded_retry_then_human_gate(self):
        feedback = classify_execution_failure(self.failure("adapter-transient"))
        self.assertEqual(RecoveryAction.RETRY, feedback.recommended_actions[0])
        action, level, reason = choose_recovery_action(
            feedback, 1, RecoveryPolicy(max_attempts=1)
        )
        self.assertEqual((RecoveryAction.HUMAN_GATE, RecoveryLevel.L6_HUMAN_GATE,
                          "RECOVERY_EXHAUSTED"), (action, level, reason))


if __name__ == "__main__":
    unittest.main()
