from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key"""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')

# Alias for get_item
@register.filter
def dict_get(dictionary, key):
    """Get an item from a dictionary by key (alias)"""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')
