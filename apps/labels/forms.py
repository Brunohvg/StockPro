from django import forms

from .models import LabelSettings

INPUT = 'pf-input'
CHECK = 'h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500'


class LabelSettingsForm(forms.ModelForm):
    class Meta:
        model = LabelSettings
        fields = ['layout', 'code_label', 'width_mm', 'height_mm', 'columns', 'column_gap_mm', 'dpi', 'darkness', 'print_speed',
                  'offset_x_mm', 'offset_y_mm', 'show_store', 'store_text', 'show_name', 'show_variant',
                  'show_price', 'show_sku', 'show_barcode', 'code_source']

        widgets = {'layout': forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect)):
                field.widget.attrs['class'] = CHECK
            else:
                field.widget.attrs['class'] = INPUT
        for name in ('column_gap_mm', 'offset_x_mm', 'offset_y_mm'):
            self.fields[name].widget.attrs['step'] = '0.5'
        self.fields['show_name'].disabled = True  # o nome sempre vai
        self.fields['layout'].required = False

    def clean_layout(self):
        return self.cleaned_data.get('layout') or self.instance.layout or 'complete'

    def clean(self):
        data = super().clean()
        cols, width, gap = data.get('columns') or 1, data.get('width_mm') or 0, data.get('column_gap_mm') or 0
        if cols * width + (cols - 1) * float(gap) > 104:
            raise forms.ValidationError('A largura total da linha passa de 104 mm, a largura máxima de impressão das Zebra de mesa (ZD220, ZD230, GC420).')
        return data
