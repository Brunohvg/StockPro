import pytest
from django.urls import reverse
from rest_framework import status

from tests.factories import ProductFactory


@pytest.mark.django_db
class TestAPIAuth:
    def test_obtain_token(self, client, user):
        """Verify that a user can obtain a JWT token"""
        # Ensure user has a known password
        user.set_password('pass123')
        user.save()

        url = reverse('token_obtain_pair')

        # TokenObtainPairView expects 'username' and 'password' by default
        # Our EmailBackend allows 'username' to be the email
        response = client.post(url, {
            'username': user.email,
            'password': 'pass123'
        }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' in response.data

    def test_api_tenant_isolation(self, client, tenant, user, member):
        """Verify that API results are correctly scoped to the requester's tenant"""
        # Ensure user has a known password and is active
        user.set_password('pass123')
        user.save()

        # Create product in User's tenant
        ProductFactory(tenant=tenant, name="My Tenant Product")

        # Create product in ANOTHER tenant
        ProductFactory(name="Foreign Product")

        # Obtain token
        token_url = reverse('token_obtain_pair')
        token_res = client.post(token_url, {
            'username': user.email,
            'password': 'pass123'
        }, format='json')

        assert token_res.status_code == status.HTTP_200_OK
        token = token_res.data['access']

        # Request products via API
        api_url = reverse('api-product-list')
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.get(api_url)

        assert response.status_code == status.HTTP_200_OK

        # Should only see p1
        results = response.data['results']
        product_names = [p['name'] for p in results]
        assert "My Tenant Product" in product_names
        assert "Foreign Product" not in product_names
        assert len(results) == 1
