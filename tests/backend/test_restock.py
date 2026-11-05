"""
Tests for restocking endpoints (recommendations and submitted orders).
"""
import pytest

import main


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Submitted orders live in module memory; reset them between tests."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


class TestDemandForecastCosts:
    def test_forecasts_include_cost_and_lead_time(self, client):
        data = client.get("/api/demand").json()
        for f in data:
            assert f["unit_cost"] > 0
            assert f["lead_time_days"] > 0


class TestRestockRecommendations:
    def test_requires_budget(self, client):
        assert client.get("/api/restock/recommendations").status_code == 422

    def test_negative_budget_rejected(self, client):
        assert client.get("/api/restock/recommendations?budget=-1").status_code == 422

    def test_zero_budget_recommends_nothing(self, client):
        data = client.get("/api/restock/recommendations?budget=0").json()
        assert data["recommendations"] == []
        assert data["total_cost"] == 0

    def test_total_never_exceeds_budget(self, client):
        for budget in [50, 500, 1234.56, 5000, 9000]:
            data = client.get(f"/api/restock/recommendations?budget={budget}").json()
            assert data["total_cost"] <= budget
            assert data["remaining_budget"] == pytest.approx(budget - data["total_cost"], abs=0.01)
            line_sum = sum(r["line_total"] for r in data["recommendations"])
            assert line_sum == pytest.approx(data["total_cost"], abs=0.01)

    def test_only_items_with_demand_gap(self, client):
        data = client.get("/api/restock/recommendations?budget=1000000").json()
        skus = {r["item_sku"] for r in data["recommendations"]}
        # MTR-304 has decreasing demand (forecast below current), so no gap.
        assert "MTR-304" not in skus
        for r in data["recommendations"]:
            assert r["demand_gap"] > 0
            assert r["recommended_quantity"] <= r["demand_gap"]

    def test_large_budget_covers_full_restock(self, client):
        data = client.get("/api/restock/recommendations?budget=1000000").json()
        assert all(not r["partial"] for r in data["recommendations"])
        assert data["total_cost"] == pytest.approx(data["full_restock_cost"], abs=0.01)

    def test_increasing_trend_ranked_first(self, client):
        data = client.get("/api/restock/recommendations?budget=1000000").json()
        trends = [r["trend"] for r in data["recommendations"]]
        first_stable = trends.index("stable")
        assert all(t == "increasing" for t in trends[:first_stable])
        assert "increasing" not in trends[first_stable:]

    def test_small_budget_partially_fills_top_item(self, client):
        # WDG-001 (largest increasing gap, $45/unit) is first; $100 buys 2 units.
        data = client.get("/api/restock/recommendations?budget=100").json()
        top = data["recommendations"][0]
        assert top["item_sku"] == "WDG-001"
        assert top["recommended_quantity"] == 2
        assert top["partial"] is True


class TestRestockOrders:
    def test_initially_empty(self, client):
        assert client.get("/api/restock/orders").json() == []

    def test_place_order(self, client):
        payload = {"budget": 1000, "items": [
            {"item_sku": "GSK-203", "quantity": 10},
            {"item_sku": "CTL-330", "quantity": 1},
        ]}
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 201
        order = response.json()
        assert order["status"] == "Submitted"
        # 10 * 12.50 + 1 * 185.00, priced server-side
        assert order["total_value"] == pytest.approx(310.0)
        # Lead time is the slowest item (CTL-330, 21 days)
        assert order["lead_time_days"] == 21
        assert order["expected_delivery"] > order["order_date"]

        listed = client.get("/api/restock/orders").json()
        assert len(listed) == 1
        assert listed[0]["id"] == order["id"]

    def test_orders_listed_newest_first(self, client):
        for qty in (1, 2):
            client.post("/api/restock/orders", json={"budget": 1000, "items": [{"item_sku": "FLT-405", "quantity": qty}]})
        listed = client.get("/api/restock/orders").json()
        assert [o["items"][0]["quantity"] for o in listed] == [2, 1]

    def test_over_budget_rejected(self, client):
        payload = {"budget": 100, "items": [{"item_sku": "CTL-330", "quantity": 1}]}
        assert client.post("/api/restock/orders", json=payload).status_code == 400

    def test_unknown_sku_rejected(self, client):
        payload = {"budget": 1000, "items": [{"item_sku": "NOPE-1", "quantity": 1}]}
        assert client.post("/api/restock/orders", json=payload).status_code == 400

    def test_empty_or_invalid_items_rejected(self, client):
        assert client.post("/api/restock/orders", json={"budget": 100, "items": []}).status_code == 422
        bad_qty = {"budget": 100, "items": [{"item_sku": "FLT-405", "quantity": 0}]}
        assert client.post("/api/restock/orders", json=bad_qty).status_code == 422
