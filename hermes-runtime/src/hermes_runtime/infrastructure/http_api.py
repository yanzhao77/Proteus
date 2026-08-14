from typing import Any, Mapping

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor
from hermes_runtime.domain.product_api import ProductApiRequest, ProductApiResponse


class InProcessHttpApiAdapter:
    """Small HTTP-shaped adapter over ProductApiFacade.

    P4 deliberately avoids starting a web server. This adapter keeps method,
    path, headers and body semantics testable so a future FastAPI/WSGI/ASGI
    adapter can wrap the same facade without gaining authority.
    """

    def __init__(self, facade: ProductApiFacade) -> None:
        self._facade = facade

    def dispatch(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        actor: Actor,
    ) -> ProductApiResponse:
        return self._facade.handle(
            ProductApiRequest(
                method=method,
                path=path,
                headers=headers,
                body=body,
                actor=actor,
            )
        )
