from hermes_runtime.domain.human_gate import AuthorizationAssertion
from hermes_runtime.domain.identity import IdentityAssertionInput, to_authorization_assertion


class LocalIdentityAssertionProvider:
    """Deterministic local/test identity assertion provider.

    This is not a production IdP. It exists so product boundary tests can prove
    assertion shape, scope and expiry behavior before an OIDC/SAML adapter is
    chosen by a future ADR.
    """

    def issue(self, assertion_id: str, payload: IdentityAssertionInput) -> AuthorizationAssertion:
        return to_authorization_assertion(assertion_id, payload)
