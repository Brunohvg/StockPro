import pytest
from django.urls import reverse
from rest_framework import status

from apps.core.models import VisualAuditLog
from apps.inventory.models import StockMovement
from tests.factories import ProductFactory


@pytest.mark.django_db
class TestAPIOrders:
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
        product = ProductFactory(tenant=tenant, current_stock=100, sku="SKU-ORDER-1")

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
        assert product.current_stock == 90

        movement = StockMovement.objects.get(external_order__external_order_id="12345")
        assert movement.quantity == 10
        assert movement.type == 'OUT'
        assert movement.source == 'NUVEMSHOP'

        # Verify Visual Audit
        audit = VisualAuditLog.objects.filter(entity_id=str(product.pk), external_ref="12345").first()
        assert audit is not None
        assert audit.diff['stock_change'] == -10.0
        assert audit.before_state['current_stock'] == 100.0
        assert audit.after_state['current_stock'] == 90.0
