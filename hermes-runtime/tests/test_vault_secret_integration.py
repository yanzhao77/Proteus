import os
import socket
import time
import unittest
from urllib.parse import urlsplit

from hermes_runtime.domain.secret_handles import SecretBoundaryRejected
from hermes_runtime.infrastructure.vault_secrets import VaultKv2Config, VaultKv2SecretManager


VAULT_URL = os.environ.get("HERMES_TEST_VAULT_URL")
VAULT_TOKEN = os.environ.get("HERMES_TEST_VAULT_TOKEN")


def _vault_ready() -> bool:
    try:
        parts = urlsplit(VAULT_URL)
        with socket.create_connection((parts.hostname, parts.port or 8200), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(VAULT_URL and VAULT_TOKEN, "requires real Vault via HERMES_TEST_VAULT_URL and HERMES_TEST_VAULT_TOKEN")
class VaultKv2IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import hvac

        deadline = time.time() + 30
        client = hvac.Client(url=VAULT_URL, token=VAULT_TOKEN)
        while time.time() < deadline:
            try:
                if client.is_authenticated():
                    break
            except OSError:
                pass
            time.sleep(0.5)
            client = hvac.Client(url=VAULT_URL, token=VAULT_TOKEN)
        if not client.is_authenticated():
            raise unittest.SkipTest("Vault not reachable or token rejected")
        cls.client = client
        cls.manager = VaultKv2SecretManager(client, VaultKv2Config())

    def test_register_metadata_and_resolution_boundary(self):
        canary = "vault-canary-value-9f3c"
        handle = self.manager.register("handle-1", canary, "project-1", {"purpose": "execution", "approver": "user-1"})
        self.assertNotIn(canary, repr(handle))
        self.assertNotIn(canary, str(handle))

        metadata = self.manager.get_metadata("handle-1")
        self.assertEqual(handle.secret_hash, metadata.secret_hash)
        self.assertEqual("project-1", metadata.scope)
        self.assertEqual("vault-kv2", metadata.provider)

        with self.assertRaisesRegex(SecretBoundaryRejected, "SECRET_RESOLUTION_UNAUTHORIZED"):
            self.manager.resolve_for_execution("handle-1", authorized_execution=False)

        resolved = self.manager.resolve_for_execution("handle-1", authorized_execution=True)
        self.assertEqual(canary, resolved)

        metadata_payload = repr(self.client.secrets.kv.v2.read_secret_version(mount_point="secret", path="hermes/metadata/handle-1"))
        self.assertNotIn(canary, metadata_payload)


if __name__ == "__main__":
    unittest.main()
