"""P6 Autonomous Production Trial package.

The harness drives the real Proteus authority runtime through a complete
autonomous software-production lifecycle: Software Request -> Situation ->
Diagnosis -> Planning -> Policy/Risk -> Selection -> Execution (real worker)
-> Verification (real pytest) -> Recovery/Replan when needed -> Human Gate when
required -> Delivery.

The harness never writes authority directly: it only submits semantic commands
through the existing application services (the same path the API wraps) and
reads through query stores. Workers and verifiers are real subprocesses.
"""
