import unittest

from hermes_runtime.domain.resource_accounting import (
    RESOURCE_UNITS,
    ResourceAccountingRejected,
    ResourceDimension,
    ThresholdPolicy,
    ThresholdStatus,
    available,
    evaluate_threshold,
    plan_settlement,
    reservation_is_feasible,
    validate_amounts,
    validate_currency,
)


class ResourceAccountingDomainTests(unittest.TestCase):
    def test_all_normative_dimensions_have_fixed_units(self):
        self.assertEqual(set(ResourceDimension), set(RESOURCE_UNITS))
        self.assertEqual(12, len(RESOURCE_UNITS))
        self.assertEqual(
            "currency_minor_unit",
            RESOURCE_UNITS[ResourceDimension.LLM_COST_MINOR],
        )

    def test_unknown_negative_boolean_and_empty_amounts_fail_closed(self):
        cases = (
            ({"unknown": 1}, "RESOURCE_DIMENSION_UNKNOWN"),
            ({"llm_tokens": -1}, "RESOURCE_AMOUNT_INVALID"),
            ({"llm_tokens": True}, "RESOURCE_AMOUNT_INVALID"),
            ({}, "RESOURCE_AMOUNT_INVALID"),
        )
        for amounts, code in cases:
            with self.subTest(amounts=amounts):
                with self.assertRaisesRegex(ResourceAccountingRejected, code):
                    validate_amounts(amounts)

    def test_currency_minor_units_require_matching_iso_currency(self):
        for currency in (None, "usd", "US", "USDD"):
            with self.subTest(currency=currency):
                with self.assertRaisesRegex(
                    ResourceAccountingRejected, "RESOURCE_CURRENCY_MISMATCH"
                ):
                    validate_currency({"llm_cost_minor": 1}, currency)
        validate_currency({"llm_cost_minor": 1}, "USD")
        validate_currency({"llm_tokens": 1}, None)

    def test_available_and_multidimensional_reservation_are_deterministic(self):
        balances = {
            "llm_tokens": (100, 20, 50),
            "agent_runs": (2, 0, 1),
        }
        self.assertEqual(30, available(*balances["llm_tokens"]))
        self.assertTrue(
            reservation_is_feasible(
                balances, {"llm_tokens": 20, "agent_runs": 1}
            )
        )
        self.assertFalse(
            reservation_is_feasible(
                balances, {"llm_tokens": 20, "agent_runs": 2}
            )
        )

    def test_threshold_boundaries_use_integer_basis_points(self):
        policy = ThresholdPolicy(7500, 9500, 10000)
        cases = (
            ((100, 74, 0), ThresholdStatus.NORMAL),
            ((100, 75, 0), ThresholdStatus.WARN),
            ((100, 95, 0), ThresholdStatus.GATE),
            ((100, 100, 0), ThresholdStatus.HARD_STOP),
            ((0, 0, 0), ThresholdStatus.NORMAL),
            ((0, 1, 0), ThresholdStatus.HARD_STOP),
        )
        for balance, expected in cases:
            with self.subTest(balance=balance):
                self.assertEqual(
                    expected,
                    evaluate_threshold({"llm_tokens": balance}, policy),
                )

    def test_settlement_records_actual_and_releases_full_reservation(self):
        for actual, expected_over in ((60, 0), (80, 0), (120, 40)):
            with self.subTest(actual=actual):
                plan = plan_settlement({"llm_tokens": 80}, {"llm_tokens": actual})
                self.assertEqual(actual, plan.consumed["llm_tokens"])
                self.assertEqual(80, plan.released["llm_tokens"])
                self.assertEqual(expected_over, plan.over_limit["llm_tokens"])


if __name__ == "__main__":
    unittest.main()
