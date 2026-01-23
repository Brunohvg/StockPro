import os

from django import template

register = template.Library()

@register.filter
def basename(value):
    return os.path.basename(value)

@register.filter
def select_attr(iterable, attr):
    """Returns a list of values for the given attribute from an iterable of objects."""
    try:
        return [getattr(item, attr) for item in iterable if hasattr(item, attr)]
    except:
        return []

@register.filter
def equalto(iterable, value):
    """Filters a list to only include items equal to the given value."""
    try:
        return [item for item in iterable if item == value]
    except:
        return []

@register.filter
def multiply(value, arg):
    """Multiplies the value by the arg."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def divide(value, arg):
    """Divides the value by the arg."""
    try:
        return float(value) / float(arg) if float(arg) != 0 else 0
    except (ValueError, TypeError):
        return 0

@register.filter
def subtract(value, arg):
    """Subtracts the arg from the value."""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0

