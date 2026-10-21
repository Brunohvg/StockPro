import pytest
from django.urls import reverse
from rest_framework import status

from apps.core.models import VisualAuditLog
from apps.inventory.models import ExternalOrder, StockMovement
from tests.factories import ProductFactory, stock_in


@pytest.mark.django_db
class TestAPIOrders:
    @staticmethod
    def authenticate(client, user):
        user.set_password('pass123')
        user.save()
        token_res = client.post(
            reverse('token_obtain_pair'),
            {'username': user.email, 'password': 'pass123'},
            format='json',
        )
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_res.data['access']}")

    def test_consume_stock_via_api(self, client, tenant, user, member):
        """Verify that an external order consumes stock and logs correctly"""
        # Set password for token auth
        user.set_password('pass123')
        user.save()

        # Access token
        token_url = reverse('token_obtain_pair')
        token_res = client.post(token_url, {'username': user.email, 'password': 'pass123'}, format='json')
        token = token_res.data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        # Product with stock
        product = ProductFactory(tenant=tenant, sku="SKU-ORDER-1")
        stock_in(product, 100, user=user)

        consume_url = reverse('api-order-consume')
        payload = {
            "platform": "NUVEMSHOP",
            "external_order_id": "12345",
            "items": [
                {"sku": "SKU-ORDER-1", "quantity": 10}
            ]
        }

        response = client.post(consume_url, payload, format='json')

        assert response.status_code == status.HTTP_200_OK

        # Verify Stock Movement
        product.refresh_from_db()
        assert product.total_stock == 90

        movement = StockMovement.objects.get(external_order__external_order_id="12345")
        assert movement.quantity == 10
        assert movement.type == 'OUT'
        assert movement.source == 'NUVEMSHOP'

        # Verify Visual Audit (Should be on the Variant)
        variant = product.variants.first()
        audit = VisualAuditLog.objects.filter(entity_id=str(variant.pk), external_ref="12345").first()
        assert audit is not None
        assert audit.diff['stock_change'] == -10.0
        assert audit.before_state['current_stock'] == 100.0
        assert audit.after_state['current_stock'] == 90.0

    def test_replayed_order_is_idempotent_and_changed_payload_conflicts(self, client, tenant, user, member):
        self.authenticate(client, user)
        product = ProductFactory(tenant=tenant, sku="SKU-ORDER-REPLAY")
        stock_in(product, 20, user=user)
        url = reverse('api-order-consume')
        payload = {
            "platform": "NUVEMSHOP",
            "external_order_id": "replay-1",
            "items": [{"sku": "SKU-ORDER-REPLAY", "quantity": 3}],
        }

        first = client.post(url, payload, format='json')
        replay = client.post(url, payload, format='json')
        product.refresh_from_db()

        assert first.status_code == status.HTTP_200_OK
        assert replay.status_code == status.HTTP_200_OK
        assert replay.data == first.data
        assert product.total_stock == 17
        assert StockMovement.objects.filter(external_order__external_order_id="replay-1").count() == 1

        changed = {**payload, "items": [{"sku": "SKU-ORDER-REPLAY", "quantity": 4}]}
        conflict = client.post(url, changed, format='json')
        product.refresh_from_db()
        assert conflict.status_code == status.HTTP_409_CONFLICT
        assert product.total_stock == 17

    def test_precreated_unconsumed_external_order_can_be_consumed(self, client, tenant, user, member):
        self.authenticate(client, user)
        product = ProductFactory(tenant=tenant, sku="SKU-ORDER-PRECREATED")
        stock_in(product, 5, user=user)
        ExternalOrder.objects.create(
            tenant=tenant, platform="NUVEMSHOP", external_order_id="precreated-1"
        )

        response = client.post(reverse('api-order-consume'), {
            "platform": "NUVEMSHOP",
            "external_order_id": "precreated-1",
            "items": [{"sku": "SKU-ORDER-PRECREATED", "quantity": 1}],
        }, format='json')

        product.refresh_from_db()
        assert response.status_code == status.HTTP_200_OK
        assert product.total_stock == 4

    def test_order_failure_rolls_back_every_line_and_can_be_retried(self, client, tenant, user, member):
        self.authenticate(client, user)
        first_product = ProductFactory(tenant=tenant, sku="SKU-ORDER-ATOMIC-1")
        second_product = ProductFactory(tenant=tenant, sku="SKU-ORDER-ATOMIC-2")
        stock_in(first_product, 10, user=user)
        stock_in(second_product, 10, user=user)
        url = reverse('api-order-consume')
        payload = {
            "platform": "NUVEMSHOP",
            "external_order_id": "atomic-1",
            "items": [
                {"sku": "SKU-ORDER-ATOMIC-1", "quantity": 2},
                {"sku": "SKU-ORDER-MISSING", "quantity": 1},
            ],
        }

        failed = client.post(url, payload, format='json')
        first_product.refresh_from_db()
        assert failed.status_code == status.HTTP_207_MULTI_STATUS
        assert failed.data['processed_items'] == []
        assert failed.data['rolled_back'] is True
        assert first_product.total_stock == 10
        assert not ExternalOrder.objects.filter(tenant=tenant, external_order_id="atomic-1").exists()

        payload['items'][1] = {"sku": "SKU-ORDER-ATOMIC-2", "quantity": 1}
        success = client.post(url, payload, format='json')
        replay = client.post(url, payload, format='json')
        first_product.refresh_from_db()
        second_product.refresh_from_db()
        assert success.status_code == status.HTTP_200_OK
        assert replay.data == success.data
        assert first_product.total_stock == 8
        assert second_product.total_stock == 9
