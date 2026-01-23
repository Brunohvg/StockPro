import pytest
from django.urls import reverse
from rest_framework import status

from apps.inventory.models import ImportItem


@pytest.mark.django_db
class TestAPIStaging:
    def test_create_product_staged(self, client, tenant, user, member):
        """Verify that a product created via API with staged=true enters the review queue"""
        user.set_password('pass123')
        user.save()

        # Access token
        token_url = reverse('token_obtain_pair')
        token_res = client.post(token_url, {'username': user.email, 'password': 'pass123'}, format='json')
        token = token_res.data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        product_url = reverse('api-product-list') + "?staged=true"
        payload = {
            "sku": "API-STAGED-1",
            "name": "Staged Product via API",
            "product_type": "SIMPLE",
            "barcode": "123456789",
            "avg_unit_cost": 50.0
        }

        response = client.post(product_url, payload, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['status'] == 'staged'

        # Verify ImportItem created
        item = ImportItem.objects.get(supplier_sku="API-STAGED-1", tenant=tenant)
        assert item.source == 'API'
        assert item.status == 'PENDING'
        assert item.description == "Staged Product via API"
        assert item.quantity == 0

    def test_approve_staged_api_item(self, client, tenant, user, member):
        """Verify that an API staged item can be approved to create a real product"""
        # 1. Create staged item
        item = ImportItem.objects.create(
            tenant=tenant,
            source='API',
            supplier_sku="API-TO-APPROVE",
            description="Approve me",
            quantity=0,
            unit_cost=10.0,
            status='PENDING'
        )

        # 2. Login as admin to approve via view
        client.force_login(user)
        approve_url = reverse('inventory:pending_product_approve', kwargs={'pk': item.pk})

        # POST to approve
        response = client.post(approve_url, {'product_action': 'create_simple'})

        assert response.status_code == 302 # Redirect to list

        # 3. Verify Product exists
        from apps.products.models import Product
        product = Product.objects.get(sku="API-TO-APPROVE", tenant=tenant)
        assert product.name == "Approve me"

        # Verify NO stock movement was created (since qty was 0)
        from apps.inventory.models import StockMovement
        assert StockMovement.objects.filter(product=product).count() == 0

        item.refresh_from_db()
        assert item.status == 'DONE'
