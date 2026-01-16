from rest_framework import viewsets, mixins, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Product, StockMovement
from .serializers import ProductSerializer, StockMovementSerializer, CreateMovementSerializer
from .services import StockService

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    lookup_field = 'sku'

class StockMovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer

    @action(detail=False, methods=['post'], serializer_class=CreateMovementSerializer)
    def register(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            movement = StockService.create_movement(
                user=request.user,
                product_sku=serializer.validated_data['product_sku'],
                movement_type=serializer.validated_data['type'],
                quantity=serializer.validated_data['quantity'],
                reason=serializer.validated_data.get('reason', ''),
                source='API'
            )
            return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
