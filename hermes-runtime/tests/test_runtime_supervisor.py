import threading
import unittest

from hermes_runtime.application.supervisor import (
    OneShotCallableRole,
    RuntimeSupervisor,
    ServiceCriticality,
    ServiceLoopConfig,
    ServiceStatus,
    SupervisedServiceLoop,
)


class RuntimeSupervisorTests(unittest.TestCase):
    def test_loop_runs_bounded_batches_and_stops_cleanly(self):
        calls = []

        def handler(batch_size, stop_event):
            calls.append((batch_size, stop_event.is_set()))
            stop_event.set()
            return {"processed": batch_size}

        loop = SupervisedServiceLoop(
            OneShotCallableRole("relay", handler),
            ServiceLoopConfig(batch_size=7, poll_interval_seconds=0),
            sleep=lambda _seconds: None,
        )
        loop.run_forever()
        snapshot = loop.snapshot()
        self.assertEqual([(7, False)], calls)
        self.assertEqual(ServiceStatus.STOPPED, snapshot.status)

    def test_critical_loop_failure_degrades_readiness(self):
        def failing(_batch_size, _stop_event):
            raise RuntimeError("boom secret=not-reported")

        loop = SupervisedServiceLoop(
            OneShotCallableRole("scheduler", failing, ServiceCriticality.CRITICAL, True),
            ServiceLoopConfig(poll_interval_seconds=0, initial_backoff_seconds=0, max_consecutive_failures=2),
            sleep=lambda _seconds: None,
        )
        loop.run_forever(max_iterations=5)
        supervisor = RuntimeSupervisor((loop,))
        readiness = supervisor.readiness()
        self.assertFalse(readiness["ready"])
        self.assertEqual(("scheduler",), readiness["failed_critical_services"])
        self.assertEqual("RuntimeError", loop.snapshot().last_error_code)
        self.assertNotIn("secret", repr(readiness))

    def test_non_critical_failure_backs_off_without_readiness_failure(self):
        attempts = []

        def flaky(_batch_size, _stop_event):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("transient")
            _stop_event.set()
            return {"processed": 1}

        sleeps = []
        loop = SupervisedServiceLoop(
            OneShotCallableRole("telemetry-export", flaky, ServiceCriticality.NON_CRITICAL, False),
            ServiceLoopConfig(poll_interval_seconds=0, initial_backoff_seconds=1, jitter_ratio=0, max_consecutive_failures=10),
            sleep=sleeps.append,
        )
        loop.run_forever()
        self.assertEqual([1], sleeps)
        self.assertTrue(RuntimeSupervisor((loop,)).readiness()["ready"])

    def test_multi_instance_roles_declare_database_fencing_not_local_lock_correctness(self):
        safe_roles = (
            OneShotCallableRole("relay", lambda *_: {}, relies_on_database_fencing=True),
            OneShotCallableRole("scheduler", lambda *_: {}, relies_on_database_fencing=True),
            OneShotCallableRole("docker-worker", lambda *_: {}, relies_on_database_fencing=True),
            OneShotCallableRole("reconcile", lambda *_: {}, relies_on_database_fencing=True),
        )
        supervisor = RuntimeSupervisor(tuple(SupervisedServiceLoop(role, ServiceLoopConfig(), sleep=lambda _s: None) for role in safe_roles))
        self.assertTrue(all(snapshot.relies_on_database_fencing for snapshot in supervisor.snapshots()))

    def test_duplicate_service_names_and_local_parallelism_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "SERVICE_LOCAL_CONCURRENCY_UNSUPPORTED"):
            ServiceLoopConfig(max_concurrency=2).validate()

        left = SupervisedServiceLoop(OneShotCallableRole("relay", lambda *_: {}), ServiceLoopConfig(), sleep=lambda _s: None)
        right = SupervisedServiceLoop(OneShotCallableRole("relay", lambda *_: {}), ServiceLoopConfig(), sleep=lambda _s: None)
        with self.assertRaisesRegex(ValueError, "SUPERVISOR_DUPLICATE_SERVICE_NAME"):
            RuntimeSupervisor((left, right))

    def test_threaded_start_stop_sets_cancel_signal(self):
        entered = threading.Event()

        def blocking(_batch_size, stop_event):
            entered.set()
            while not stop_event.is_set():
                stop_event.wait(0.01)
            return {"stopped": True}

        loop = SupervisedServiceLoop(
            OneShotCallableRole("consumer", blocking),
            ServiceLoopConfig(poll_interval_seconds=0),
            sleep=lambda _seconds: None,
        )
        loop.start()
        self.assertTrue(entered.wait(1))
        loop.stop(timeout_seconds=1)
        self.assertEqual(ServiceStatus.STOPPED, loop.snapshot().status)


if __name__ == "__main__":
    unittest.main()
