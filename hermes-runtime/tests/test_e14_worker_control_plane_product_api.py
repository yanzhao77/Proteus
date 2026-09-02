import unittest

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest, ProductApiRejected


class _Read: pass
class _Gateway: pass


class _WorkerReadModel:
    def __init__(self):
        self.calls = []

    def list_workers(self, actor_scope):
        self.calls.append(("list_workers", actor_scope))
        return {"availability": "CURRENT", "reason": None, "items": [{"worker_id": "w-1"}]}

    def worker_detail(self, worker_id, actor_scope):
        self.calls.append(("worker_detail", worker_id, actor_scope))
        return {"availability": "CURRENT", "reason": None, "item": {"worker_id": worker_id}}

    def execution_queue(self, actor_scope):
        self.calls.append(("execution_queue", actor_scope))
        return {"availability": "CURRENT", "reason": None, "items": [{"queue_item_id": "q-1"}]}


class E14WorkerControlPlaneProductApiTests(unittest.TestCase):
    def request(self, method, path, body=None, subject="creator", actor_id=None):
        actor_id = actor_id or subject
        return ProductApiRequest(method, path, {}, body or {}, Actor(ActorType.USER, actor_id), subject)

    def facade(self, worker_read_model=None):
        return ProductApiFacade(
            _Read(),
            _Gateway(),
            worker_control_plane_read_model=worker_read_model,
        )

    def test_list_workers_passes_verified_actor_scope(self):
        worker = _WorkerReadModel()
        result = self.facade(worker).handle(self.request("GET", "/factory-home/workers"))
        self.assertEqual(200, result.status_code)
        self.assertEqual("CURRENT", result.body["availability"])
        self.assertEqual("w-1", result.body["items"][0]["worker_id"])
        kind, scope = worker.calls[0]
        self.assertEqual("list_workers", kind)
        self.assertIs(True, scope["identity_verified"])
        self.assertEqual("creator", scope["identity_subject"])
        self.assertEqual("creator", scope["actor_id"])
        self.assertEqual("user", scope["actor_type"])

    def test_worker_detail_passes_id_through(self):
        worker = _WorkerReadModel()
        result = self.facade(worker).handle(self.request("GET", "/factory-home/workers/w-1"))
        self.assertEqual(200, result.status_code)
        self.assertEqual("w-1", result.body["item"]["worker_id"])
        kind, worker_id, scope = worker.calls[0]
        self.assertEqual("worker_detail", kind)
        self.assertEqual("w-1", worker_id)
        self.assertEqual("creator", scope["identity_subject"])

    def test_execution_queue_passes_verified_actor_scope(self):
        worker = _WorkerReadModel()
        result = self.facade(worker).handle(self.request("GET", "/factory-home/execution-queue"))
        self.assertEqual(200, result.status_code)
        self.assertEqual("q-1", result.body["items"][0]["queue_item_id"])
        kind, scope = worker.calls[0]
        self.assertEqual("execution_queue", kind)
        self.assertIs(True, scope["identity_verified"])

    def test_verified_subject_is_authoritative_even_if_actor_id_differs(self):
        worker = _WorkerReadModel()
        result = self.facade(worker).handle(self.request("GET", "/factory-home/workers", subject="creator", actor_id="forged"))
        self.assertEqual(200, result.status_code)
        kind, scope = worker.calls[0]
        self.assertEqual("creator", scope["identity_subject"])
        self.assertIs(True, scope["identity_verified"])

    def test_unconfigured_read_model_returns_not_available_for_all_routes(self):
        facade = self.facade()  # default -> UnavailableWorkerControlPlaneReadModel
        for path in ("/factory-home/workers", "/factory-home/execution-queue"):
            result = facade.handle(self.request("GET", path))
            self.assertEqual(200, result.status_code)
            self.assertEqual("NOT_AVAILABLE", result.body["availability"])
            self.assertEqual("WORKER_CONTROL_PLANE_READ_MODEL_NOT_CONFIGURED", result.body["reason"])
            self.assertEqual([], result.body["items"])
        detail = facade.handle(self.request("GET", "/factory-home/workers/w-1"))
        self.assertEqual(200, detail.status_code)
        self.assertEqual("NOT_AVAILABLE", detail.body["availability"])
        self.assertEqual("WORKER_CONTROL_PLANE_READ_MODEL_NOT_CONFIGURED", detail.body["reason"])
        self.assertIsNone(detail.body["item"])

    def test_unknown_route_still_rejected(self):
        with self.assertRaises(ProductApiRejected):
            self.facade().handle(self.request("GET", "/factory-home/not-a-route"))


if __name__ == "__main__":
    unittest.main()
