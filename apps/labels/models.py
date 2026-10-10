from django.conf import settings
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.tenants.models import TenantMixin

PRESETS = [
    # (chave, rótulo, largura, altura, colunas, espaço entre colunas)
    ('40x25', '40 × 25 mm', 40, 25, 1, Decimal('0')),
    ('50x30', '50 × 30 mm', 50, 30, 1, Decimal('0')),
    ('60x40', '60 × 40 mm', 60, 40, 1, Decimal('0')),
    ('100x50', '100 × 50 mm', 100, 50, 1, Decimal('0')),
    ('2x50x25', '2 colunas 50 × 25 mm', 50, 25, 2, Decimal('2')),
    ('3x33x22', '3 colunas 33 × 22 mm', 33, 22, 3, Decimal('2')),
]

LAYOUT_CHOICES = [
    ('complete', 'Completa: loja, nome, variação, preço e código'),
    ('code_name', 'Código + nome + código de barras (etiqueta pequena)'),
]


class LabelSettings(TenantMixin):
    """Modelo de etiqueta da empresa: tamanho do rolo, impressora e o que aparece."""

    DPI_CHOICES = [(203, '203 dpi (8 pontos/mm), ex.: ZD220, ZD230, GC420'),
                   (300, '300 dpi (12 pontos/mm), ex.: ZD421 300, ZT230 300')]
    SPEED_CHOICES = [(0, 'Padrão da impressora'), (2, '2 pol/s (mais nítido)'), (3, '3 pol/s'),
                     (4, '4 pol/s'), (5, '5 pol/s'), (6, '6 pol/s (mais rápido)')]
    LAYOUT_CHOICES = LAYOUT_CHOICES
    CODE_CHOICES = [('auto', 'EAN do cadastro; sem EAN, o SKU'),
                    ('sku', 'Sempre o SKU')]

    width_mm = models.PositiveSmallIntegerField(
        'Largura da etiqueta (mm)', default=50, validators=[MinValueValidator(15), MaxValueValidator(120)])
    height_mm = models.PositiveSmallIntegerField(
        'Altura da etiqueta (mm)', default=30, validators=[MinValueValidator(10), MaxValueValidator(150)])
    columns = models.PositiveSmallIntegerField(
        'Etiquetas por linha (colunas)', default=1, validators=[MinValueValidator(1), MaxValueValidator(4)])
    column_gap_mm = models.DecimalField(
        'Espaço entre colunas (mm)', max_digits=3, decimal_places=1, default=Decimal('0'),
        validators=[MinValueValidator(0), MaxValueValidator(10)])
    dpi = models.PositiveSmallIntegerField('Resolução da impressora', choices=DPI_CHOICES, default=203)
    darkness = models.SmallIntegerField(
        'Ajuste de escuridão', default=0, validators=[MinValueValidator(-10), MaxValueValidator(10)],
        help_text='0 mantém o da impressora. Aumente se as barras saírem falhadas.')
    print_speed = models.PositiveSmallIntegerField('Velocidade', choices=SPEED_CHOICES, default=0)
    offset_x_mm = models.DecimalField(
        'Ajuste horizontal (mm)', max_digits=3, decimal_places=1, default=Decimal('0'),
        validators=[MinValueValidator(-10), MaxValueValidator(10)],
        help_text='Positivo empurra para a direita.')
    offset_y_mm = models.DecimalField(
        'Ajuste vertical (mm)', max_digits=3, decimal_places=1, default=Decimal('0'),
        validators=[MinValueValidator(-10), MaxValueValidator(10)],
        help_text='Positivo empurra para baixo (até 10 mm a 300 dpi, 15 mm a 203 dpi).')

    layout = models.CharField('Estilo da etiqueta', max_length=12, choices=LAYOUT_CHOICES, default='complete')
    code_label = models.CharField(
        'Texto antes do código', max_length=20, blank=True, default='CÓDIGO:',
        help_text='No estilo "código + nome". Ex.: CÓDIGO: 139557. Vazio imprime só o código.')

    show_store = models.BooleanField('Nome da loja', default=True)
    store_text = models.CharField(
        'Texto da loja', max_length=40, blank=True,
        help_text='Vazio usa o nome da empresa das Configurações.')
    show_name = models.BooleanField('Nome do produto', default=True)
    show_variant = models.BooleanField('Variação (cor, tamanho)', default=True)
    show_price = models.BooleanField('Preço de venda', default=True)
    show_sku = models.BooleanField('SKU', default=True)
    show_barcode = models.BooleanField('Código de barras', default=True)
    code_source = models.CharField('O que vai no código de barras', max_length=10,
                                   choices=CODE_CHOICES, default='auto')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração de etiqueta'
        verbose_name_plural = 'Configurações de etiqueta'
        constraints = [models.UniqueConstraint(fields=['tenant'], name='unique_label_settings_per_tenant')]

    def __str__(self):
        return f'Etiqueta {self.width_mm}x{self.height_mm} mm ({self.tenant})'

    @classmethod
    def for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj

    @property
    def size_label(self):
        cols = f'{self.columns} colunas de ' if self.columns > 1 else ''
        return f'{cols}{self.width_mm} × {self.height_mm} mm · {self.dpi} dpi'


class VariantLabel(TenantMixin):
    """
    Texto da etiqueta de um produto/variação, quando diferente do cadastro.
    Vazio = usa o padrão (nome do produto com a variação; código = SKU).
    """
    variant = models.OneToOneField('products.ProductVariant', on_delete=models.CASCADE,
                                   related_name='label_text')
    name = models.CharField('Nome na etiqueta', max_length=80, blank=True)
    code = models.CharField('Código impresso', max_length=30, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Texto de etiqueta'
        verbose_name_plural = 'Textos de etiqueta'

    def __str__(self):
        return f'{self.variant.sku}: {self.name or "(nome do cadastro)"}'
