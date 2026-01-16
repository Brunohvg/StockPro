"""
Products App - Product Catalog Management
"""
from django.db import models
from apps.tenants.models import Tenant, TenantMixin


class Category(TenantMixin):
    """Product category with stock rotation classification"""
    ROTATION_TYPES = [
        ('A', 'Alta Rotação'),
        ('B', 'Média Rotação'),
        ('C', 'Baixa Rotação'),
    ]
    name = models.CharField(max_length=100)
    rotation = models.CharField(max_length=1, choices=ROTATION_TYPES, default='B')

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"
        unique_together = ['tenant', 'name']

    def __str__(self):
        return self.name


class Brand(TenantMixin):
    """Product brand/manufacturer"""
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"
        unique_together = ['tenant', 'name']

    def __str__(self):
        return self.name


class Product(TenantMixin):
    """Main product entity with inventory tracking"""
    sku = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    uom = models.CharField(max_length=10, default='UN', verbose_name="Unidade")
    current_stock = models.IntegerField(default=0)
    minimum_stock = models.IntegerField(default=0)
    avg_unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        unique_together = ['tenant', 'sku']

    def __str__(self):
        return f"{self.sku} - {self.name}"

    @property
    def stock_value(self):
        if self.current_stock and self.avg_unit_cost:
            return self.current_stock * self.avg_unit_cost
        return 0

    @property
    def is_low_stock(self):
        return self.current_stock <= self.minimum_stock
