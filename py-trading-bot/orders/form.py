#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar 21 19:42:27 2023

@author: maxime
"""

from django import forms
from orders.models import Action, Strategy

class ManualOrderForm(forms.Form):
    action = forms.ModelChoiceField(queryset=Action.objects.all())
    strategy = forms.ModelChoiceField(queryset=Strategy.objects.all())
    TrueFalse=(
        (True, "True"),
        (False,"False")
        )
    short = forms.ChoiceField(choices=TrueFalse)
    sl_threshold=forms.DecimalField(max_digits=100, decimal_places=5) #as price
    daily_sl_threshold=forms.DecimalField(max_digits=100, decimal_places=5) #as pu
    
    