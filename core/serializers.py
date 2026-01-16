from rest_framework import serializers
from .models import Product, StockMovement

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'category', 'brand', 'uom', 'minimum_stock', 'current_stock']
        read_only_fields = ['current_stock']

class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = ['id', 'product', 'type', 'quantity', 'balance_before', 'balance_after', 'user', 'reason', 'source', 'created_at']
        read_only_fields = ['id', 'balance_before', 'balance_after', 'user', 'created_at']

class CreateMovementSerializer(serializers.Serializer):
    product_sku = serializers.CharField()
    type = serializers.ChoiceField(choices=StockMovement.MOVEMENT_TYPES)
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True)

